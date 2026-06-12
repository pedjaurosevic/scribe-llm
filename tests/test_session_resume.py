"""Session tagging + resume-by-tag lookup."""

from types import SimpleNamespace

from scribe.session import SessionManager, session_tag


def isolated_manager(tmp_path, monkeypatch) -> SessionManager:
    """A SessionManager whose state AND transcripts stay inside tmp_path."""
    # Point the legacy dir somewhere empty so migration never touches the
    # real ~/.scribe/sessions during tests.
    monkeypatch.setattr(SessionManager, "LEGACY_STATE_DIR", tmp_path / "legacy")
    return SessionManager(SimpleNamespace(workspace_dir=str(tmp_path / "ws")))


def test_everything_lives_in_one_visible_workspace_folder(tmp_path, monkeypatch):
    mgr = isolated_manager(tmp_path, monkeypatch)
    cp = mgr.start_session(topic="layout")
    mgr.add_message("user", "zdravo")
    mgr.end_session()

    sessions = tmp_path / "ws" / "sessions"
    assert mgr.sessions_dir == sessions
    assert (sessions / cp.session_id / "checkpoint.json").is_file()
    assert (sessions / f"{cp.session_id}.md").is_file()
    assert (sessions / "last_session.txt").read_text().strip() == cp.session_id


def test_legacy_sessions_are_migrated(tmp_path, monkeypatch):
    # Simulate the old hidden layout ...
    legacy = tmp_path / "legacy"
    old = legacy / "20260101_120000"
    old.mkdir(parents=True)
    (old / "checkpoint.json").write_text(
        '{"session_id": "20260101_120000", "created_at": "x", '
        '"topic": "old", "status": "completed", "messages": [], '
        '"current_language_game": "chat", "metadata": {}}'
    )
    (legacy / "last_session.txt").write_text("20260101_120000")

    # ... then start a manager: the content must move into the workspace.
    mgr = isolated_manager(tmp_path, monkeypatch)
    assert (mgr.sessions_dir / "20260101_120000" / "checkpoint.json").is_file()
    assert not (legacy / "20260101_120000").exists()
    assert mgr.get_last_session().topic == "old"
    assert "20260101_120000" in mgr.list_sessions()


def test_session_tag_is_stable_and_short():
    a = session_tag("20260608_234338")
    b = session_tag("20260608_234338")
    assert a == b and len(a) == 5
    assert session_tag("20260608_234338") != session_tag("20260608_234339")


def test_find_by_tag(tmp_path, monkeypatch):
    mgr = isolated_manager(tmp_path, monkeypatch)
    cp = mgr.start_session(topic="t")
    mgr.add_message("user", "hi")
    mgr.end_session()

    tag = session_tag(cp.session_id)
    assert mgr.find_by_tag(tag) == cp.session_id
    assert mgr.find_by_tag("#" + tag) == cp.session_id   # leading # tolerated
    assert mgr.find_by_tag(cp.session_id) == cp.session_id
    assert mgr.find_by_tag("zzzzz") is None

    restored = mgr.load_session(mgr.find_by_tag(tag))
    assert any(m["content"] == "hi" for m in restored.messages)


def test_transcript_written_on_every_checkpoint(tmp_path, monkeypatch):
    mgr = isolated_manager(tmp_path, monkeypatch)
    cp = mgr.start_session(topic="trains")
    mgr.add_message("system", "internal prompt — must not leak")
    mgr.add_message("user", "Koliko je sati u Tokiju?")
    mgr.add_message("assistant", "Devet uveče.")
    mgr.checkpoint()

    md = mgr.transcript_path(cp.session_id).read_text(encoding="utf-8")
    assert md.startswith("---")                       # frontmatter present
    assert f"tag: {session_tag(cp.session_id)}" in md
    assert "Koliko je sati u Tokiju?" in md
    assert "Devet uveče." in md
    assert "internal prompt" not in md                # system messages skipped
    assert "status: active" in md

    # the transcript is rewritten as the session evolves
    mgr.add_message("user", "Hvala!")
    mgr.end_session()
    md = mgr.transcript_path(cp.session_id).read_text(encoding="utf-8")
    assert "Hvala!" in md
    assert "status: completed" in md


def test_search_transcripts(tmp_path, monkeypatch):
    mgr = isolated_manager(tmp_path, monkeypatch)
    cp = mgr.start_session(topic="search")
    mgr.add_message("user", "Pričamo o Peirceovoj semiotici.")
    mgr.end_session()

    hits = mgr.search_transcripts("SEMIOTICI")        # case-insensitive
    assert hits and hits[0]["session_id"] == cp.session_id
    assert "semiotici" in hits[0]["text"].lower()
    assert mgr.search_transcripts("nepostojeci-pojam-xyz") == []
    assert mgr.search_transcripts("") == []
