"""Tests for curated OKF knowledge bases (pure, file-based, no model)."""

from __future__ import annotations

import pytest

from scribe.knowledge import KnowledgeBase, KnowledgeRegistry
from scribe.prompts import grounded_context


def _make_bundle(root):
    pages = root / "pages"
    pages.mkdir(parents=True)
    (pages / "rlimits.md").write_text(
        "---\ntype: reference\ntitle: Resource limits\n---\n\n"
        "# Resource limits\n\n"
        "RLIMIT_AS caps the address space a process may map.\n\n"
        "## See also\n\n"
        "Related: [sandbox](sandbox.md).\n",
        encoding="utf-8",
    )
    (pages / "sandbox.md").write_text(
        "# Sandbox\n\nThe bubblewrap container mounts a read-only root.\n",
        encoding="utf-8",
    )
    (pages / "index.md").write_text(
        "# Index\n\n- [Resource limits](rlimits.md)\n", encoding="utf-8"
    )
    return root


def test_pages_excludes_reserved(tmp_path):
    kb = KnowledgeBase("kb", _make_bundle(tmp_path))
    names = {p.name for p in kb.pages()}
    assert names == {"rlimits.md", "sandbox.md"}  # index.md excluded
    assert kb.page_count() == 2


def test_titles_reads_frontmatter(tmp_path):
    kb = KnowledgeBase("kb", _make_bundle(tmp_path))
    titles = dict(kb.titles())
    assert titles["rlimits.md"] == "Resource limits"


def test_search_ranks_relevant_page_first(tmp_path):
    kb = KnowledgeBase("kb", _make_bundle(tmp_path))
    ranked = kb.search("RLIMIT_AS address space", limit=5)
    assert ranked[0][0].name == "rlimits.md"


def test_search_empty_on_no_match(tmp_path):
    kb = KnowledgeBase("kb", _make_bundle(tmp_path))
    assert kb.search("quantum chromodynamics") == []


def test_chunks_for_are_grounding_shaped(tmp_path):
    kb = KnowledgeBase("kb", _make_bundle(tmp_path))
    chunks = kb.chunks_for("read-only root bubblewrap", limit=3)
    assert chunks and chunks[0].source_file == "sandbox.md"
    # Slots straight into the grounded-context renderer with [n] citations.
    block = grounded_context(chunks)
    assert "[1]" in block and "read-only root" in block


def test_links_extracts_okf_graph(tmp_path):
    kb = KnowledgeBase("kb", _make_bundle(tmp_path))
    links = kb.links("rlimits.md")
    assert ("sandbox", "sandbox.md") in links


def test_registry_add_list_get_remove(tmp_path):
    bundle = _make_bundle(tmp_path / "bundle")
    reg = KnowledgeRegistry(tmp_path / "registry.json")
    reg.add("security", bundle)
    assert [kb.name for kb in reg.list()] == ["security"]
    assert reg.get("security").page_count() == 2
    assert reg.remove("security") is True
    assert reg.get("security") is None
    assert reg.remove("security") is False  # idempotent


def test_registry_rejects_non_okf_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    reg = KnowledgeRegistry(tmp_path / "reg.json")
    with pytest.raises(ValueError):
        reg.add("empty", empty)
    with pytest.raises(ValueError):
        reg.add("missing", tmp_path / "does-not-exist")
