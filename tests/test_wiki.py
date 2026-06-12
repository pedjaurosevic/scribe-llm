"""Wiki distiller: ledger, digests, pending selection, and the distill loop."""

import json
from types import SimpleNamespace

from scribe.session import SessionCheckpoint, SessionManager
from scribe.wiki import (
    distill,
    load_ledger,
    pending_sessions,
    rebuild_index,
    render_session,
    save_ledger,
    session_digest,
    sync_rag,
    wiki_dir,
)


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(workspace_dir=str(tmp_path / "ws"))


def _manager(tmp_path, monkeypatch) -> SessionManager:
    monkeypatch.setattr(SessionManager, "LEGACY_STATE_DIR", tmp_path / "legacy")
    return SessionManager(_config(tmp_path))


def _checkpoint(session_id="20260612_120000", topic="t", messages=None) -> SessionCheckpoint:
    return SessionCheckpoint(
        session_id=session_id,
        created_at="2026-06-12T12:00:00",
        topic=topic,
        status="completed",
        messages=messages
        if messages is not None
        else [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "Odlučili smo da koristimo GBNF."},
            {"role": "assistant", "content": "Zabeleženo: GBNF za tool pozive."},
        ],
    )


class TestScaffoldAndLedger:
    def test_wiki_dir_scaffolds_index_and_pages(self, tmp_path):
        wiki = wiki_dir(_config(tmp_path))
        assert (wiki / "pages").is_dir()
        assert "WIKI Index" in (wiki / "index.md").read_text()

    def test_ledger_round_trip(self, tmp_path):
        wiki = wiki_dir(_config(tmp_path))
        assert load_ledger(wiki) == {}
        save_ledger(wiki, {"a": "1"})
        assert load_ledger(wiki) == {"a": "1"}

    def test_corrupt_ledger_is_empty(self, tmp_path):
        wiki = wiki_dir(_config(tmp_path))
        (wiki / ".distilled.json").write_text("not json")
        assert load_ledger(wiki) == {}


class TestDigestAndRender:
    def test_digest_stable_and_content_sensitive(self):
        cp = _checkpoint()
        assert session_digest(cp) == session_digest(_checkpoint())
        changed = _checkpoint(messages=[{"role": "user", "content": "drugo"}])
        assert session_digest(cp) != session_digest(changed)

    def test_digest_ignores_system_messages(self):
        with_sys = _checkpoint()
        without_sys = _checkpoint(
            messages=[m for m in with_sys.messages if m["role"] != "system"]
        )
        assert session_digest(with_sys) == session_digest(without_sys)

    def test_render_skips_system(self):
        text = render_session(_checkpoint())
        assert "GBNF" in text
        assert "hidden" not in text


class TestPendingSelection:
    def _save(self, mgr, cp):
        mgr.current_session = cp
        mgr.checkpoint()

    def test_pending_skips_processed_and_respects_since(self, tmp_path, monkeypatch):
        mgr = _manager(tmp_path, monkeypatch)
        old = _checkpoint("20260601_080000")
        new = _checkpoint("20260612_090000")
        self._save(mgr, old)
        self._save(mgr, new)

        ledger = {old.session_id: session_digest(old)}
        ids = [sid for sid, _ in pending_sessions(mgr, ledger)]
        assert ids == [new.session_id]

        ids = [sid for sid, _ in pending_sessions(mgr, {}, since="20260610")]
        assert ids == [new.session_id]

    def test_changed_session_is_redistilled(self, tmp_path, monkeypatch):
        mgr = _manager(tmp_path, monkeypatch)
        cp = _checkpoint()
        self._save(mgr, cp)
        ledger = {cp.session_id: "stale-digest"}
        assert [sid for sid, _ in pending_sessions(mgr, ledger)] == [cp.session_id]


class _FakeAdapter:
    """First turn: write a page. Second turn: summary answer."""

    def __init__(self, answer="Zapisano u pages/odluke.md"):
        self.answer = answer
        self.turn = 0

    def streaming_turn(self, messages, tools=None, **kwargs):
        self.turn += 1
        if self.turn == 1:
            yield (
                "tool_calls",
                [
                    {
                        "id": "c1",
                        "name": "write_file",
                        "arguments": json.dumps(
                            {"path": "pages/odluke.md", "content": "# Odluke\n- GBNF\n"}
                        ),
                    },
                ],
            )
        else:
            yield ("answer", self.answer)


class TestDistill:
    def test_distill_writes_pages_and_ledger(self, tmp_path, monkeypatch):
        cfg = _config(tmp_path)
        mgr = _manager(tmp_path, monkeypatch)
        cp = _checkpoint()
        mgr.current_session = cp
        mgr.checkpoint()

        results = distill(cfg, adapter=_FakeAdapter())
        assert [r["status"] for r in results] == ["stored"]

        wiki = wiki_dir(cfg)
        assert "GBNF" in (wiki / "pages" / "odluke.md").read_text()
        assert "Odluke" in (wiki / "index.md").read_text()
        assert load_ledger(wiki) == {cp.session_id: session_digest(cp)}

        # Second run: nothing pending anymore.
        assert distill(cfg, adapter=_FakeAdapter()) == []

    def test_skip_answer_marks_session_processed(self, tmp_path, monkeypatch):
        cfg = _config(tmp_path)
        mgr = _manager(tmp_path, monkeypatch)
        cp = _checkpoint()
        mgr.current_session = cp
        mgr.checkpoint()

        class _SkipAdapter:
            def streaming_turn(self, messages, tools=None, **kwargs):
                yield ("answer", "SKIP")

        results = distill(cfg, adapter=_SkipAdapter())
        assert [r["status"] for r in results] == ["skipped"]
        assert cp.session_id in load_ledger(wiki_dir(cfg))

    def test_error_does_not_poison_ledger(self, tmp_path, monkeypatch):
        cfg = _config(tmp_path)
        mgr = _manager(tmp_path, monkeypatch)
        cp = _checkpoint()
        mgr.current_session = cp
        mgr.checkpoint()

        class _BrokenAdapter:
            def streaming_turn(self, messages, tools=None, **kwargs):
                raise OSError("server down")
                yield  # pragma: no cover

        results = distill(cfg, adapter=_BrokenAdapter())
        assert [r["status"] for r in results] == ["error"]
        # Not in the ledger → will be retried next run.
        assert cp.session_id not in load_ledger(wiki_dir(cfg))


class TestIndexAndRagSync:
    def test_rebuild_index_from_pages(self, tmp_path):
        wiki = wiki_dir(_config(tmp_path))
        (wiki / "pages" / "deadlock.md").write_text(
            "# Deadlock (Mrtva petlja)\n\nStanje u kojem procesi cekaju jedni druge.\n"
        )
        (wiki / "pages" / "no-heading.md").write_text("samo tekst bez naslova\n")
        rebuild_index(wiki)

        index = (wiki / "index.md").read_text()
        assert "[Deadlock (Mrtva petlja)](pages/deadlock.md)" in index
        assert "Stanje u kojem procesi" in index            # hook line
        assert "[no heading](pages/no-heading.md)" in index  # stem fallback

    class _FakeRag:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def delete_source(self, source):
            self.calls.append(("delete", source))

        def ingest_file(self, path):
            self.calls.append(("ingest", str(path)))
            return 1

    def test_sync_rag_only_changed_pages(self, tmp_path):
        wiki = wiki_dir(_config(tmp_path))
        page = wiki / "pages" / "a.md"
        page.write_text("# A\nv1\n")

        rag = self._FakeRag()
        assert sync_rag(wiki, rag) == ["a.md"]
        # Unchanged → nothing re-ingested.
        assert sync_rag(wiki, rag) == []
        # Changed → re-ingested (delete old chunks first).
        page.write_text("# A\nv2\n")
        assert sync_rag(wiki, rag) == ["a.md"]
        assert ("delete", str(page)) in rag.calls

    def test_sync_rag_failure_is_retried_next_time(self, tmp_path):
        wiki = wiki_dir(_config(tmp_path))
        (wiki / "pages" / "a.md").write_text("# A\nv1\n")

        class _BrokenRag(self._FakeRag):
            def ingest_file(self, path):
                raise OSError("rag down")

        assert sync_rag(wiki, _BrokenRag()) == []
        # Not recorded as synced → a working service picks it up.
        assert sync_rag(wiki, self._FakeRag()) == ["a.md"]

    def test_distill_rebuilds_index(self, tmp_path, monkeypatch):
        cfg = _config(tmp_path)
        mgr = _manager(tmp_path, monkeypatch)
        mgr.current_session = _checkpoint()
        mgr.checkpoint()

        distill(cfg, adapter=_FakeAdapter())
        index = (wiki_dir(cfg) / "index.md").read_text()
        assert "[Odluke](pages/odluke.md)" in index
