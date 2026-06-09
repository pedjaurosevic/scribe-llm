import tempfile
from pathlib import Path

import pytest

from scribe.tools import fs, shell


@pytest.fixture
def workspace():
    return Path(tempfile.mkdtemp())


class TestWorkspaceFileTools:
    def test_write_and_read(self, workspace):
        fs.dispatch(workspace, "write_file", {"path": "a.txt", "content": "hello"})
        assert (workspace / "a.txt").read_text() == "hello"
        assert "hello" in fs.dispatch(workspace, "read_file", {"path": "a.txt"})

    def test_make_dir_and_nested_write(self, workspace):
        fs.dispatch(workspace, "make_dir", {"path": "notes"})
        assert (workspace / "notes").is_dir()
        fs.dispatch(workspace, "write_file", {"path": "notes/x.md", "content": "y"})
        assert (workspace / "notes" / "x.md").read_text() == "y"

    def test_list_dir(self, workspace):
        fs.dispatch(workspace, "write_file", {"path": "f.txt", "content": ""})
        listing = fs.dispatch(workspace, "list_dir", {"path": "."})
        assert "f.txt" in listing

    def test_traversal_is_blocked(self, workspace):
        result = fs.dispatch(workspace, "write_file", {"path": "../evil.txt", "content": "x"})
        assert "outside the workspace" in result
        assert not (workspace.parent / "evil.txt").exists()

    def test_absolute_path_is_blocked(self, workspace):
        result = fs.dispatch(workspace, "read_file", {"path": "/etc/passwd"})
        assert "outside the workspace" in result

    def test_unknown_tool(self, workspace):
        assert "unknown tool" in fs.dispatch(workspace, "nope", {})

    def test_bad_json_arguments(self, workspace):
        assert "invalid arguments" in fs.dispatch(workspace, "write_file", "{not json")


class TestShellTool:
    def test_run_command_output_and_exit(self, workspace):
        result = shell.dispatch(workspace, "run_bash", {"command": "echo hello"})
        assert "hello" in result
        assert "[exit 0]" in result

    def test_runs_in_given_cwd(self, workspace):
        (workspace / "marker.txt").write_text("x")
        result = shell.dispatch(workspace, "run_bash", {"command": "ls"})
        assert "marker.txt" in result

    def test_nonzero_exit_is_reported(self, workspace):
        result = shell.dispatch(workspace, "run_bash", {"command": "exit 3"})
        assert "[exit 3]" in result

    def test_parse_command(self):
        assert shell.parse_command('{"command": "ls -la"}') == "ls -la"
        assert shell.parse_command({"command": "pwd"}) == "pwd"

    def test_empty_command(self, workspace):
        assert "empty command" in shell.dispatch(workspace, "run_bash", {"command": "  "})

    def test_unknown_tool(self, workspace):
        assert "unknown tool" in shell.dispatch(workspace, "nope", {})

    def test_timeout(self, workspace):
        result = shell.dispatch(workspace, "run_bash", {"command": "sleep 5"}, timeout=1)
        assert "timeout" in result.lower()
