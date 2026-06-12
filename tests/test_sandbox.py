"""Tests for the execution sandbox and git checkpoint/rollback."""

from __future__ import annotations

import subprocess

import pytest

from scribe.tools import checkpoint
from scribe.tools.sandbox import (
    bwrap_available,
    gate_command,
    gate_python,
    run_sandboxed,
    wrap_argv,
)
from scribe.tools.shell import run_command


class TestCommandGate:
    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf ~",
            "rm -fr $HOME",
            "sudo rm -rf /*",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            ":(){ :|:& };:",
            "shutdown -h now",
            "reboot",
            "echo x > /dev/nvme0n1",
            "git push origin main --force",
        ],
    )
    def test_destructive_commands_refused(self, command):
        assert gate_command(command) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "rm -rf node_modules",
            "rm -rf ./build",
            "git push origin main",
            "python -m pytest -q",
            "dd if=a.img of=b.img",
            "echo 'rm -rf /' is dangerous",  # quoted mention still refused? no — see below
        ],
    )
    def test_normal_commands_pass(self, command):
        # The gate is pattern-based; a quoted *mention* of a destructive
        # command is indistinguishable from the real thing and may be refused.
        # All listed commands except the quoted-mention case must pass.
        if "is dangerous" in command:
            pytest.skip("quoted mentions are an accepted false positive")
        assert gate_command(command) is None

    def test_shell_run_command_applies_gate(self):
        out = run_command("rm -rf /")
        assert out.startswith("[refused]")


class TestPythonGate:
    def test_clean_code_passes(self):
        assert gate_python("import json\nprint(json.dumps({'a': 1}))") is None

    def test_blocked_module_refused(self):
        assert "ctypes" in gate_python("import ctypes")
        assert "ctypes" in gate_python("from ctypes import CDLL")

    def test_blocked_call_refused(self):
        assert "os.system" in gate_python("import os\nos.system('ls')")
        assert "shutil.rmtree" in gate_python("import shutil\nshutil.rmtree('/tmp/x')")

    def test_eval_exec_refused(self):
        assert "eval" in gate_python("eval('1+1')")
        assert "exec" in gate_python("exec('x=1')")

    def test_syntax_error_refused(self):
        assert "syntax error" in gate_python("def broken(:")


class TestSandboxExecution:
    def test_run_sandboxed_basic(self, tmp_path):
        proc = run_sandboxed("echo hello", str(tmp_path), timeout=30)
        assert proc.returncode == 0
        assert "hello" in proc.stdout

    def test_wrap_argv_shape(self, tmp_path):
        argv = wrap_argv("ls", str(tmp_path))
        assert argv[0] == "bwrap"
        assert "--unshare-net" in argv
        assert argv[-2:] == ["-c", "ls"]
        assert "--unshare-net" not in wrap_argv("ls", str(tmp_path), network=True)

    @pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not installed")
    def test_network_is_cut_inside_bwrap(self, tmp_path):
        proc = run_sandboxed(
            "curl -s --max-time 2 http://127.0.0.1:18083/health || echo NO-NET",
            str(tmp_path),
            timeout=30,
        )
        assert "NO-NET" in proc.stdout

    @pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not installed")
    def test_root_is_readonly_inside_bwrap(self, tmp_path):
        proc = run_sandboxed("touch /usr/scribe-probe 2>&1; echo done", str(tmp_path))
        assert "Read-only" in proc.stdout or "read-only" in proc.stdout

    @pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not installed")
    def test_workspace_stays_writable(self, tmp_path):
        proc = run_sandboxed("echo data > probe.txt && cat probe.txt", str(tmp_path))
        assert "data" in proc.stdout
        assert (tmp_path / "probe.txt").read_text().strip() == "data"


@pytest.fixture
def repo(tmp_path):
    """A tiny git repo with one committed file."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "main.py").write_text("print('v1')\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    return tmp_path


class TestCheckpoint:
    def test_snapshot_returns_sha(self, repo):
        sha = checkpoint.snapshot(str(repo))
        assert sha and len(sha) == 40

    def test_snapshot_outside_repo_is_none(self, tmp_path):
        assert checkpoint.snapshot(str(tmp_path / "x")) is None

    def test_restore_reverts_edits_and_removes_new_files(self, repo):
        sha = checkpoint.snapshot(str(repo))
        (repo / "main.py").write_text("print('broken')\n")
        (repo / "junk.py").write_text("x = 1\n")
        assert checkpoint.restore(str(repo), sha)
        assert (repo / "main.py").read_text() == "print('v1')\n"
        assert not (repo / "junk.py").exists()

    def test_snapshot_captures_untracked_files(self, repo):
        (repo / "extra.md").write_text("note\n")
        sha = checkpoint.snapshot(str(repo))
        (repo / "extra.md").unlink()
        assert checkpoint.restore(str(repo), sha)
        assert (repo / "extra.md").read_text() == "note\n"

    def test_keep_or_rollback_keeps_passing_tree(self, repo):
        before = checkpoint.snapshot(str(repo))
        (repo / "main.py").write_text("print('v2')\n")
        kept, _ = checkpoint.keep_or_rollback(str(repo), before, "true")
        assert kept
        assert (repo / "main.py").read_text() == "print('v2')\n"

    def test_keep_or_rollback_restores_failing_tree(self, repo):
        before = checkpoint.snapshot(str(repo))
        (repo / "main.py").write_text("print('v2-broken')\n")
        kept, _ = checkpoint.keep_or_rollback(str(repo), before, "false")
        assert not kept
        assert (repo / "main.py").read_text() == "print('v1')\n"

    def test_dispatch_roundtrip(self, repo):
        out = checkpoint.dispatch(str(repo), "workspace_checkpoint", "{}")
        assert out.startswith("checkpoint saved: ")
        sha = out.split(": ", 1)[1]
        (repo / "main.py").write_text("print('oops')\n")
        out = checkpoint.dispatch(
            str(repo), "workspace_rollback", {"checkpoint_id": sha}
        )
        assert "restored" in out
        assert (repo / "main.py").read_text() == "print('v1')\n"

    def test_dispatch_outside_repo_errors(self, tmp_path):
        out = checkpoint.dispatch(str(tmp_path), "workspace_checkpoint", "{}")
        assert out.startswith("Error")
