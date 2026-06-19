"""
Tests for security hardening features in Scribe v1.1.0.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scribe.config import ScribeConfig
from scribe.tools.fs import WorkspaceError, _safe_path
from scribe.web import (
    _is_rate_limited,
    _record_attempt,
    _valid_ws_origin,
    app,
)


def test_config_api_key_redaction():
    """Verify API keys are redacted correctly to avoid exposure in UI/status."""
    # 1. No key / default key
    cfg = ScribeConfig()
    cfg.set("scribe", "api_key", "not-needed")
    assert cfg.redacted_api_key == "not-needed"

    cfg.set("scribe", "api_key", "")
    assert cfg.redacted_api_key == ""

    # 2. Short API key
    cfg.set("scribe", "api_key", "12345")
    assert cfg.redacted_api_key == "****45"

    # 3. Normal API key
    cfg.set("scribe", "api_key", "sk-abcdefghijklmnopqrstuvwxyz123456")
    assert cfg.redacted_api_key == "****3456"


def test_is_default_pin():
    """Verify default PIN detection."""
    cfg = ScribeConfig()
    cfg.set("scribe.web", "pin", "2020")
    assert cfg.is_default_pin is True

    cfg.set("scribe.web", "pin", "9999")
    assert cfg.is_default_pin is False


def test_safe_path_traversal_protection(tmp_path):
    """Verify that file tools reject path traversal attempts outside workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Valid relative path inside
    path = _safe_path(workspace, "notes/todo.md")
    assert path.relative_to(workspace) == Path("notes/todo.md")

    # Traversals attempting to escape
    with pytest.raises(WorkspaceError):
        _safe_path(workspace, "../etc/passwd")

    with pytest.raises(WorkspaceError):
        _safe_path(workspace, "notes/../../../etc/passwd")

    # Absolute path attempts
    with pytest.raises(WorkspaceError):
        _safe_path(workspace, "/etc/passwd")

    # Bypass allowed
    path = _safe_path(workspace, "../outside.txt", allow_outside=True)
    assert path == (workspace.parent / "outside.txt").resolve()


def test_security_headers():
    """Verify that HTTP security headers are correctly appended by middleware."""
    client = TestClient(app)
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["X-XSS-Protection"] == "0"
    assert "Content-Security-Policy" in response.headers


def test_login_rate_limiting():
    """Verify login rate limiter blocks brute force attempts."""
    ip = "192.168.1.99"
    # Ensure starting state is clean
    from scribe.web import _login_attempts
    _login_attempts.clear()

    assert _is_rate_limited(ip) is False

    # Perform 4 attempts
    for _ in range(4):
        _record_attempt(ip)
        assert _is_rate_limited(ip) is False

    # 5th attempt trigger
    _record_attempt(ip)
    assert _is_rate_limited(ip) is True


def test_websocket_origin_check():
    """Verify WebSocket cross-origin checks reject CSWSH attempts."""
    class DummyHeaders:
        def __init__(self, headers_dict):
            self.headers_dict = headers_dict

        def get(self, key, default=""):
            return self.headers_dict.get(key.lower(), default)

    class DummyWebSocket:
        def __init__(self, headers_dict):
            self.headers = DummyHeaders(headers_dict)

    # 1. No origin header (e.g. CLI/python script, non-browser)
    ws = DummyWebSocket({"host": "localhost:8765"})
    assert _valid_ws_origin(ws) is True

    # 2. Matching origin
    ws = DummyWebSocket({"host": "localhost:8765", "origin": "http://localhost:8765"})
    assert _valid_ws_origin(ws) is True

    # 3. Matching origin with https
    ws = DummyWebSocket({"host": "localhost:8765", "origin": "https://localhost:8765"})
    assert _valid_ws_origin(ws) is True

    # 4. Mismatching origin
    ws = DummyWebSocket({"host": "localhost:8765", "origin": "http://malicious.com"})
    assert _valid_ws_origin(ws) is False


def test_pin_initialization(tmp_path, monkeypatch):
    """Verify that PIN is correctly initialized and saved when not configured."""
    config_file = tmp_path / "config.toml"

    # 1. Create a config with no pin
    config_file.write_text("[scribe]\nmodel = 'test-model'\n")

    cfg = ScribeConfig()
    # Direct search to our temp config file
    monkeypatch.setattr(cfg, "_find_config_file", lambda: config_file)
    # Reload config
    cfg._config = {}
    cfg._merge_config({"scribe": {"model": "test-model"}})
    cfg.config_path = str(config_file)

    assert cfg.is_pin_configured() is False

    # Ensure it generates a random pin when stdin is not a TTY
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    generated_pin = cfg.ensure_web_pin()
    assert len(generated_pin) == 4
    assert generated_pin.isdigit()

    # Check that it got saved to config file
    assert cfg.is_pin_configured() is True
    assert cfg.web_pin == generated_pin

    # Reload config and check it persists
    import toml
    saved_data = toml.load(config_file)
    assert saved_data["scribe.web"]["pin"] == generated_pin

