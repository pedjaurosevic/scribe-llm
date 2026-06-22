"""Tests for ORORO traces, the status contract, and the project vault."""

from __future__ import annotations

from scribe.config import ScribeConfig
from scribe.session import SessionManager
from scribe.status import collect_status
from scribe.trace import Tracer, read_trace, trace_summary
from scribe.vault import VAULT_DIR, init_vault


class TestTracer:
    def test_events_are_canonical_and_monotone(self, tmp_path):
        tracer = Tracer(tmp_path / "trace.jsonl")
        tracer.event("session_start", topic="x", mode="chat")
        tracer.event("tool_call", name="read_file", arguments='{"path": "a"}')
        tracer.event("session_end", status="completed")

        events = read_trace(tmp_path / "trace.jsonl")
        assert [e["kind"] for e in events] == [
            "session_start", "tool_call", "session_end"
        ]
        assert [e["seq"] for e in events] == [1, 2, 3]
        # Canonical: keys sorted on disk.
        first_line = (tmp_path / "trace.jsonl").read_text().splitlines()[0]
        assert first_line.index('"kind"') < first_line.index('"mode"')

    def test_summary_counts_kinds(self, tmp_path):
        tracer = Tracer(tmp_path / "t.jsonl")
        tracer.event("tool_call", name="a")
        tracer.event("tool_call", name="b")
        tracer.event("answer", chars=10)
        summary = trace_summary(tmp_path / "t.jsonl")
        assert summary["events"] == 3
        assert summary["kinds"]["tool_call"] == 2
        assert summary["monotone"]

    def test_writes_never_raise(self, tmp_path):
        # Pointing at an unwritable path must be swallowed, not raised.
        tracer = Tracer(tmp_path / "nope" / "deep" / "t.jsonl")
        tracer.event("x")  # parent is created; should succeed silently
        assert (tmp_path / "nope" / "deep" / "t.jsonl").exists()

    def test_read_missing_file(self, tmp_path):
        assert read_trace(tmp_path / "absent.jsonl") == []

    def test_corrupt_lines_skipped(self, tmp_path):
        path = tmp_path / "t.jsonl"
        path.write_text('{"seq": 1, "kind": "a"}\nnot json\n{"seq": 2, "kind": "b"}\n')
        events = read_trace(path)
        assert [e["kind"] for e in events] == ["a", "b"]


class TestSessionTracing:
    def _config(self, tmp_path):
        cfg = ScribeConfig()
        cfg.set("scribe", "workspace_dir", str(tmp_path / "ws"))
        return cfg

    def test_session_lifecycle_is_traced(self, tmp_path):
        manager = SessionManager(self._config(tmp_path))
        manager.start_session(topic="demo", language_game="code")
        manager.add_message("user", "hello there")
        manager.trace("tool_call", name="run_bash", arguments="ls")
        manager.end_session("completed")

        sid = manager.current_session.session_id
        events = read_trace(manager.sessions_dir / sid / "trace.jsonl")
        kinds = [e["kind"] for e in events]
        assert kinds[0] == "session_start"
        assert "turn_start" in kinds
        assert "tool_call" in kinds
        assert kinds[-1] == "session_end"

    def test_trace_noop_without_session(self, tmp_path):
        manager = SessionManager(self._config(tmp_path))
        # No active session — must not raise.
        manager.trace("tool_call", name="x")


class TestStatusContract:
    def test_contract_has_stable_top_level_keys(self, tmp_path, monkeypatch):
        cfg = ScribeConfig()
        cfg.set("scribe", "workspace_dir", str(tmp_path / "ws"))
        # Avoid a real network probe / model download.
        monkeypatch.setattr(
            "scribe.llm_adapter.LLMAdapter.is_healthy", lambda self: False
        )
        status = collect_status(cfg)
        expected_keys = (
            "version", "server", "capabilities", "workspace",
            "sessions", "rag", "sme", "bench",
        )
        for key in expected_keys:
            assert key in status
        assert status["server"]["reachable"] is False
        assert status["capabilities"]["tool_grammar"] in ("auto", "force", "off")

    def test_status_survives_broken_rag(self, tmp_path, monkeypatch):
        cfg = ScribeConfig()
        monkeypatch.setattr(
            "scribe.llm_adapter.LLMAdapter.is_healthy", lambda self: False
        )
        cfg.set("scribe.rag", "index_dir", str(tmp_path / "missing-rag"))
        status = collect_status(cfg)
        assert status["rag"]["available"] is False

    def test_status_counts_rag_without_loading_service(self, tmp_path, monkeypatch):
        cfg = ScribeConfig()
        cfg.set("scribe.rag", "index_dir", str(tmp_path / "rag"))
        monkeypatch.setattr(
            "scribe.llm_adapter.LLMAdapter.is_healthy", lambda self: False
        )

        from scribe.memory.hybrid import FTSIndex

        idx = FTSIndex(tmp_path / "rag" / "fts.db")
        idx.add([
            {"id": "a1", "source_file": "a.md", "content": "alpha"},
            {"id": "a2", "source_file": "a.md", "content": "beta"},
            {"id": "b1", "source_file": "b.md", "content": "gamma"},
        ])
        idx.close()

        status = collect_status(cfg)
        assert status["rag"]["available"] is True
        assert status["rag"]["chunks"] == 3
        assert status["rag"]["fts_chunks"] == 3
        assert status["rag"]["sources"] == 2
        assert status["rag"]["mode"] == "fast"


class TestVault:
    def test_init_creates_vault(self, tmp_path):
        report = init_vault(tmp_path)
        assert "config.toml" in report["created"]
        assert (tmp_path / "config.toml").exists()
        assert (tmp_path / VAULT_DIR / "rag").is_dir()
        assert (tmp_path / VAULT_DIR / "sme").is_dir()

    def test_init_is_idempotent(self, tmp_path):
        init_vault(tmp_path)
        report = init_vault(tmp_path)
        assert "config.toml" in report["existing"]
        assert report["created"] == [] or all(
            "config.toml" != c for c in report["created"]
        )

    def test_vault_config_overrides_paths(self, tmp_path):
        init_vault(tmp_path)
        cfg = ScribeConfig(tmp_path / "config.toml")
        assert str(tmp_path) in cfg.rag_db_path
        assert VAULT_DIR in cfg.rag_db_path
        assert VAULT_DIR in cfg.sme_db_path

    def test_gitignore_added_in_repo(self, tmp_path):
        (tmp_path / ".git").mkdir()
        init_vault(tmp_path)
        assert f"{VAULT_DIR}/" in (tmp_path / ".gitignore").read_text()

    def test_no_gitignore_outside_repo(self, tmp_path):
        init_vault(tmp_path)
        assert not (tmp_path / ".gitignore").exists()
