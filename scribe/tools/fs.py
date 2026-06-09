"""
Sandboxed filesystem tools for Scribe.

Every operation is confined to the workspace directory. Paths are resolved and
checked so the model can never read or write outside the workspace (no `..`
traversal, no absolute escapes).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Cap how much file content we read back into the context.
MAX_READ_CHARS = 10_000


class WorkspaceError(Exception):
    """Raised when a tool call would leave the workspace or otherwise fails."""


def _safe_path(workspace: Path, rel: str, allow_outside: bool = False) -> Path:
    """
    Resolve `rel` against `workspace`.

    By default anything that escapes the workspace is rejected. When
    `allow_outside` is True the path is resolved without the boundary check,
    so absolute paths and `..` traversal reach the rest of the filesystem.
    """
    workspace = workspace.resolve()
    target = (workspace / rel).resolve()
    if not allow_outside and target != workspace and workspace not in target.parents:
        raise WorkspaceError(f"Path '{rel}' is outside the workspace")
    return target


def _display(workspace: Path, target: Path) -> str:
    """Show a workspace-relative path when inside, otherwise the absolute one."""
    try:
        return str(target.relative_to(workspace.resolve()))
    except ValueError:
        return str(target)


def write_file(workspace: Path, path: str, content: str = "", allow_outside: bool = False) -> str:
    """Create or overwrite a file (parent dirs are created)."""
    target = _safe_path(workspace, path, allow_outside)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {_display(workspace, target)}"


def read_file(workspace: Path, path: str, allow_outside: bool = False) -> str:
    """Return the text content of a file (truncated if very large)."""
    target = _safe_path(workspace, path, allow_outside)
    if not target.is_file():
        raise WorkspaceError(f"File not found: {path}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + f"\n... [truncated, {len(text)} chars total]"
    return text


def make_dir(workspace: Path, path: str, allow_outside: bool = False) -> str:
    """Create a directory (and parents) inside the workspace."""
    target = _safe_path(workspace, path, allow_outside)
    target.mkdir(parents=True, exist_ok=True)
    return f"Created directory {_display(workspace, target)}"


def list_dir(workspace: Path, path: str = ".", allow_outside: bool = False) -> str:
    """List entries in a directory inside the workspace."""
    target = _safe_path(workspace, path, allow_outside)
    if not target.exists():
        raise WorkspaceError(f"Path not found: {path}")
    if target.is_file():
        return f"{path} (file, {target.stat().st_size} bytes)"
    entries = []
    for item in sorted(target.iterdir()):
        suffix = "/" if item.is_dir() else ""
        entries.append(f"{item.name}{suffix}")
    listing = "\n".join(entries) if entries else "(empty)"
    return f"{_display(workspace, target) or '.'}:\n{listing}"


# OpenAI-style tool schemas advertised to the model.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a file in the workspace. "
                "Parent folders are created automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the workspace, e.g. notes/todo.md",
                    },
                    "content": {"type": "string", "description": "Full text content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_dir",
            "description": "Create a directory (and parents) in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to the workspace",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the contents of a directory in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to the workspace (default '.')",
                    },
                },
                "required": [],
            },
        },
    },
]


_DISPATCH: dict[str, Callable[..., str]] = {
    "write_file": write_file,
    "read_file": read_file,
    "make_dir": make_dir,
    "list_dir": list_dir,
}


def dispatch(
    workspace: Path,
    name: str,
    arguments: str | dict[str, Any],
    allow_outside: bool = False,
) -> str:
    """
    Execute a tool call by name with JSON (or dict) arguments.

    `allow_outside` is supplied by the caller (the TUI permission state), never
    by the model — it is stripped from the model arguments before dispatch.

    Returns a short human-readable result string (also fed back to the model).
    Never raises — errors are returned as text so the model can react.
    """
    func = _DISPATCH.get(name)
    if func is None:
        return f"Error: unknown tool '{name}'"

    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError as e:
            return f"Error: invalid arguments for {name}: {e}"
    else:
        args = dict(arguments or {})

    # The model must not be able to grant itself out-of-workspace access.
    args.pop("allow_outside", None)

    try:
        return func(workspace, allow_outside=allow_outside, **args)
    except WorkspaceError as e:
        return f"Error: {e}"
    except TypeError as e:
        return f"Error: bad arguments for {name}: {e}"
    except Exception as e:  # pragma: no cover - defensive
        return f"Error running {name}: {e}"
