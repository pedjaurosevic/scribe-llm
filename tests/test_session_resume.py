"""Session tagging + resume-by-tag lookup."""


from scribe.session import SessionManager, session_tag


def test_session_tag_is_stable_and_short():
    a = session_tag("20260608_234338")
    b = session_tag("20260608_234338")
    assert a == b and len(a) == 5
    assert session_tag("20260608_234338") != session_tag("20260608_234339")


def test_find_by_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(SessionManager, "STATE_DIR", tmp_path / "sessions")
    mgr = SessionManager()
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
