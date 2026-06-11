import tempfile
from pathlib import Path

import pytest

from scribe.tools import fs, shell, web


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


class TestWebTools:
    def test_load_brave_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "test_key_123")
        assert web.load_brave_api_key() == "test_key_123"

    @pytest.fixture
    def mock_urlopen(self):
        from unittest.mock import MagicMock, patch
        with patch("urllib.request.urlopen") as mock:
            yield mock

    def test_web_search_success(self, mock_urlopen, monkeypatch):
        from unittest.mock import MagicMock
        monkeypatch.setenv("BRAVE_API_KEY", "test_key_123")
        
        # Mock response
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"web": {"results": [{"title": "Test Title", "url": "http://example.com", "description": "Test snippet"}]}}'
        mock_response.headers = {}
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = web.dispatch("web_search", {"query": "test query", "count": 1})
        assert "Test Title" in res
        assert "http://example.com" in res
        assert "Test snippet" in res

    def test_web_fetch_success(self, mock_urlopen):
        from unittest.mock import MagicMock
        # Mock HTML response
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html><head><title>Ignore</title></head><body><p>Hello World</p><script>ignore this</script></body></html>"
        mock_response.headers = {}
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = web.dispatch("web_fetch", {"url": "http://example.com"})
        assert "Hello World" in res
        assert "ignore this" not in res


def test_parse_text_tool_calls():
    from scribe.llm_adapter import parse_text_tool_calls
    
    # Test JSON action format
    raw_json = '{"action": "list_dir", "action_input": {"path": "."}}'
    res = parse_text_tool_calls(raw_json)
    assert len(res) == 1
    assert res[0]["name"] == "list_dir"
    assert "path" in res[0]["arguments"]

    # Test JSON action format with string action_input
    raw_json_str = '{"action": "list_dir", "action_input": "{\\"path\\": \\".\\"}"}'
    res = parse_text_tool_calls(raw_json_str)
    assert len(res) == 1
    assert res[0]["name"] == "list_dir"
    assert "path" in res[0]["arguments"]

    # Test markdown wrapped JSON
    wrapped_json = '```json\n{"action": "web_search", "action_input": "hello"}\n```'
    res = parse_text_tool_calls(wrapped_json)
    assert len(res) == 1
    assert res[0]["name"] == "web_search"
    assert "hello" in res[0]["arguments"]

    # Test ReAct format
    react = "Action: list_dir\nAction Input: {\"path\": \".\"}"
    res = parse_text_tool_calls(react)
    assert len(res) == 1
    assert res[0]["name"] == "list_dir"
    assert "path" in res[0]["arguments"]


