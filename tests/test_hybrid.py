"""Tests for hybrid retrieval (FTS5 + vectors, RRF) and citation grounding."""

from __future__ import annotations

import pytest

from scribe.memory.hybrid import FTSIndex, _fts_escape, rrf_fuse
from scribe.prompts import GROUNDING_RULES, get_grounded_prompt, grounded_context


class TestRRF:
    def test_agreement_wins(self):
        fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
        ids = [doc_id for doc_id, _ in fused]
        # a and b appear in both lists near the top; c and d in one each.
        assert set(ids[:2]) == {"a", "b"}
        assert set(ids[2:]) == {"c", "d"}

    def test_single_ranking_preserved(self):
        fused = rrf_fuse([["x", "y", "z"]])
        assert [doc_id for doc_id, _ in fused] == ["x", "y", "z"]

    def test_lexical_only_hit_can_beat_deep_semantic(self):
        semantic = [f"s{i}" for i in range(20)] + ["needle"]
        lexical = ["needle"]
        fused = rrf_fuse([semantic, lexical])
        assert fused[0][0] in ("needle", "s0")
        # The needle (rank 21 + rank 1) must beat everything ranked ~5+
        ids = [doc_id for doc_id, _ in fused]
        assert ids.index("needle") < ids.index("s5")

    def test_empty_input(self):
        assert rrf_fuse([]) == []
        assert rrf_fuse([[], []]) == []

    def test_scores_are_descending(self):
        fused = rrf_fuse([["a", "b"], ["a", "c"]])
        scores = [s for _, s in fused]
        assert scores == sorted(scores, reverse=True)


class TestFTSEscape:
    def test_plain_terms_quoted(self):
        assert _fts_escape("hello world") == '"hello" OR "world"'

    def test_fts_syntax_neutralized(self):
        escaped = _fts_escape('drop AND "table" OR (x NEAR y)')
        # Operators survive only as quoted literal terms, never as syntax.
        assert '"AND"' in escaped and '"NEAR"' in escaped
        assert "(" not in escaped

    def test_unicode_terms(self):
        assert '"zašto"' in _fts_escape("zašto pada")

    def test_empty(self):
        assert _fts_escape("...") == ""


class TestFTSIndex:
    @pytest.fixture
    def index(self, tmp_path):
        idx = FTSIndex(tmp_path / "fts.db")
        idx.add(
            [
                {"id": "c1", "source_file": "a.md", "content": "RLIMIT_AS caps process mem"},
                {"id": "c2", "source_file": "a.md", "content": "bubblewrap isolates the fs"},
                {"id": "c3", "source_file": "b.md", "content": "reciprocal rank fusion merges"},
            ]
        )
        yield idx
        idx.close()

    def test_exact_identifier_found(self, index):
        assert index.search("RLIMIT_AS")[0] == "c1"

    def test_or_semantics(self, index):
        ids = index.search("bubblewrap fusion")
        assert set(ids) == {"c2", "c3"}

    def test_no_hits(self, index):
        assert index.search("quantum entanglement") == []

    def test_injection_is_inert(self, index):
        # FTS5 syntax in the query must not raise or match everything.
        assert index.search('"; DROP TABLE chunks; --') == []

    def test_delete_source(self, index):
        index.delete_source("a.md")
        assert index.count() == 1
        assert index.search("bubblewrap") == []

    def test_clear(self, index):
        index.clear()
        assert index.count() == 0


class FakeChunk:
    def __init__(self, content, source_file="doc.md", section=""):
        self.content = content
        self.source_file = source_file
        self.section = section


class TestGrounding:
    def test_sources_are_numbered(self):
        ctx = grounded_context([FakeChunk("alpha"), FakeChunk("beta", "x/ref.pdf")])
        assert "[1] (doc.md)" in ctx
        assert "[2] (ref.pdf)" in ctx
        assert "alpha" in ctx and "beta" in ctx

    def test_section_included(self):
        ctx = grounded_context([FakeChunk("alpha", section="Intro")])
        assert "[1] (doc.md, Intro)" in ctx

    def test_rules_demand_citations_and_refusal(self):
        assert "[1], [2]" in GROUNDING_RULES
        assert "do not cover" in GROUNDING_RULES
        assert "[CONTRADICTION" in GROUNDING_RULES

    def test_full_prompt_contains_rules_and_sources(self):
        prompt = get_grounded_prompt([FakeChunk("gamma")])
        assert "Grounding rules" in prompt
        assert "## Sources" in prompt
        assert "gamma" in prompt


class TestHybridSearchIntegration:
    """RAGService.hybrid_search with stubbed embeddings (no model download)."""

    @pytest.fixture
    def rag(self, tmp_path, monkeypatch):
        from scribe.memory.rag import RAGService

        service = RAGService(db_path=tmp_path / "rag")

        def fake_embed(texts):
            # Deterministic 384-dim vectors: hash-seeded, so identical text
            # maps to an identical vector and different text stays apart.
            out = []
            for t in texts:
                seed = abs(hash(t)) % 997
                out.append([((seed * (i + 1)) % 101) / 101.0 for i in range(384)])
            return out

        monkeypatch.setattr(service, "_embed", fake_embed)
        return service

    def test_ingest_populates_both_branches(self, rag, tmp_path):
        doc = tmp_path / "notes.md"
        doc.write_text("RLIMIT_AS caps memory.\n\nBubblewrap cuts network access.\n")
        added = rag.ingest_file(doc)
        assert added >= 1
        assert rag.fts.count() == added

    def test_hybrid_finds_exact_identifier(self, rag, tmp_path):
        doc = tmp_path / "notes.md"
        doc.write_text(
            "RLIMIT_AS caps process memory hard.\n\n"
            + "\n\n".join(f"Filler paragraph number {i} about cooking." for i in range(5))
        )
        rag.ingest_file(doc)
        results = rag.hybrid_search("RLIMIT_AS", limit=3)
        assert results
        assert any("RLIMIT_AS" in c.content for c in results[:1])

    def test_delete_source_clears_fts(self, rag, tmp_path):
        doc = tmp_path / "gone.md"
        doc.write_text("ephemeral content here")
        rag.ingest_file(doc)
        assert rag.fts.count() > 0
        rag.delete_source(str(doc))
        assert rag.fts.count() == 0

    def test_reindex_fts_rebuilds(self, rag, tmp_path):
        doc = tmp_path / "notes.md"
        doc.write_text("alpha beta gamma")
        rag.ingest_file(doc)
        rag.fts.clear()
        assert rag.fts.count() == 0
        assert rag.reindex_fts() >= 1
        assert rag.fts.search("alpha")
