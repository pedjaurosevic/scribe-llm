"""Tests for the email bridge — no network, pure logic and config wiring."""

from __future__ import annotations

import pytest

from scribe.config import ScribeConfig
from scribe.mail import EmailBridge, IncomingCommand


def test_instruction_strips_secret_token_and_joins_body():
    cmd = IncomingCommand(
        sender="me@example.com",
        subject="[scribe:s3cret] summarize notes",
        body="focus on the open items",
        message_id="<1@x>",
    )
    out = cmd.instruction("s3cret")
    assert "[scribe:s3cret]" not in out
    assert out == "summarize notes\nfocus on the open items"


def test_instruction_subject_only():
    cmd = IncomingCommand("me@x.com", "[scribe:k] list the workspace", "", "<2@x>")
    assert cmd.instruction("k") == "list the workspace"


def test_bridge_requires_credentials():
    with pytest.raises(ValueError):
        EmailBridge(address="", password="")


def test_bridge_defaults_approved_sender_to_self():
    b = EmailBridge("a@gmail.com", "pw")
    assert b.approved_sender == "a@gmail.com"


def test_poll_fails_closed_without_secret():
    # No secret configured → never accept commands, no network touched.
    b = EmailBridge("a@gmail.com", "pw", secret="")
    assert b.poll_commands() == []


def test_email_config_reads_env_password(monkeypatch):
    monkeypatch.setenv("SCRIBE_EMAIL_PASSWORD", "from-env")
    cfg = ScribeConfig()
    ecfg = cfg.email_config()
    assert ecfg["password"] == "from-env"
    assert ecfg["smtp_host"] == "smtp.gmail.com"
    assert ecfg["imap_port"] == 993
    assert ecfg["enabled"] is False
