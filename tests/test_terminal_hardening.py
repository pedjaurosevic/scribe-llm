"""Tests for the integrated-terminal hardening (one-time token + argv)."""

from __future__ import annotations

import time

from scribe.web import (
    _consume_terminal_token,
    _mint_terminal_token,
    _terminal_tokens,
    build_terminal_argv,
)


def test_argv_uses_bwrap_when_sandboxed():
    argv = build_terminal_argv("/bin/bash", "/work", bwrap=True, restricted=True)
    assert argv[0] == "bwrap"
    assert "--ro-bind" in argv and "--unshare" not in argv  # ro root is the barrier
    assert argv[-1] == "-l"  # login bash inside the container


def test_argv_restricts_fallback_shell():
    argv = build_terminal_argv("/bin/bash", "/work", bwrap=False, restricted=True)
    assert argv == ["/bin/bash", "--restricted", "-l"]


def test_argv_unrestricted_fallback_when_disabled():
    argv = build_terminal_argv("/bin/bash", "/work", bwrap=False, restricted=False)
    assert "--restricted" not in argv
    assert argv == ["/bin/bash", "-l"]


def test_argv_non_bash_shell_gets_no_bash_flags():
    argv = build_terminal_argv("/bin/sh", "/work", bwrap=False, restricted=True)
    assert argv == ["/bin/sh"]  # --restricted/-l are bash-only


def test_token_is_single_use():
    token = _mint_terminal_token()
    assert _consume_terminal_token(token) is True
    assert _consume_terminal_token(token) is False  # already spent


def test_token_rejects_missing_and_unknown():
    assert _consume_terminal_token(None) is False
    assert _consume_terminal_token("") is False
    assert _consume_terminal_token("not-a-real-token") is False


def test_token_rejects_expired():
    token = _mint_terminal_token()
    _terminal_tokens[token] = time.time() - 1  # force expiry
    assert _consume_terminal_token(token) is False
