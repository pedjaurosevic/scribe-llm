"""
Git checkpoint / rollback — the agent's undo button.

Snapshots the workspace as a git *tree object* through a temporary index, so
the user's real index, branches and stash are never touched and nothing shows
up in `git log`. Restore re-materializes a snapshot and removes files created
after it, returning the worktree to the exact captured state.

The intended loop (Synap's Git-rollback idea, without the MCTS):
    sha = snapshot(workspace)
    ... agent edits files / runs commands ...
    ok, output = verify(workspace, "pytest -q")
    if not ok:
        restore(workspace, sha)
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from scribe.tools.sandbox import run_sandboxed


def _git(repo: str, *args: str, index: str | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if index:
        env["GIT_INDEX_FILE"] = index
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def is_repo(workspace: str) -> bool:
    """Whether the workspace is inside a git repository."""
    return _git(workspace, "rev-parse", "--is-inside-work-tree").returncode == 0


def snapshot(workspace: str) -> str | None:
    """
    Capture the current worktree (tracked + untracked, minus ignored) as a
    tree object. Returns its sha, or None when the workspace is not a repo.
    """
    if not is_repo(workspace):
        return None
    # The index path must NOT exist yet: git rejects a zero-length index file
    # ("index file smaller than expected"), so a fresh name inside a temp dir
    # is used instead of NamedTemporaryFile.
    with tempfile.TemporaryDirectory(prefix="scribe-ckpt-") as tmpdir:
        index = str(Path(tmpdir) / "index")
        if _git(workspace, "add", "-A", index=index).returncode != 0:
            return None
        result = _git(workspace, "write-tree", index=index)
    return result.stdout.strip() if result.returncode == 0 else None


def restore(workspace: str, tree_sha: str) -> bool:
    """
    Return the worktree to a snapshot: overwrite changed files with their
    captured content and delete files that did not exist in the snapshot.
    """
    current = snapshot(workspace)
    if current is None:
        return False

    with tempfile.TemporaryDirectory(prefix="scribe-ckpt-") as tmpdir:
        index = str(Path(tmpdir) / "index")
        if _git(workspace, "read-tree", tree_sha, index=index).returncode != 0:
            return False
        if _git(workspace, "checkout-index", "-a", "-f", index=index).returncode != 0:
            return False

    # Files added since the snapshot are not covered by checkout-index;
    # diff the two trees and remove them explicitly.
    diff = _git(workspace, "diff-tree", "-r", "--name-status", tree_sha, current)
    if diff.returncode == 0:
        root = Path(workspace)
        for line in diff.stdout.splitlines():
            status, _, path = line.partition("\t")
            if status.strip() == "A" and path:
                target = root / path
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
    return True


def verify(workspace: str, test_command: str, timeout: int = 300) -> tuple[bool, str]:
    """
    Run the project's test command in the sandbox and report (passed, output).
    """
    try:
        proc = run_sandboxed(test_command, workspace, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"[timeout] verification exceeded {timeout}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out[-4000:]


# OpenAI-style schemas advertised to the model in code mode. The snapshot/
# restore pair lets the model fearlessly attempt multi-file changes: take a
# checkpoint, edit, run tests, and roll back itself when the attempt failed.
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "workspace_checkpoint",
            "description": (
                "Snapshot the entire workspace (a git tree object; branches and "
                "history stay untouched). Returns a checkpoint id. Take one "
                "BEFORE attempting risky multi-file changes."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_rollback",
            "description": (
                "Restore the workspace to a previous checkpoint id: changed "
                "files are reverted and files created since are deleted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "checkpoint_id": {
                        "type": "string",
                        "description": "Id returned by workspace_checkpoint",
                    },
                },
                "required": ["checkpoint_id"],
            },
        },
    },
]


def dispatch(workspace: str, name: str, arguments: str | dict) -> str:
    """Execute a checkpoint tool call. Returns a short result string."""
    import json as _json

    if isinstance(arguments, str):
        try:
            args = _json.loads(arguments or "{}")
        except _json.JSONDecodeError:
            args = {}
    else:
        args = dict(arguments or {})

    if name == "workspace_checkpoint":
        sha = snapshot(workspace)
        if not sha:
            return "Error: workspace is not a git repository (run `git init` first)"
        return f"checkpoint saved: {sha}"
    if name == "workspace_rollback":
        sha = str(args.get("checkpoint_id", "")).strip()
        if not sha:
            return "Error: checkpoint_id is required"
        return (
            f"workspace restored to {sha}"
            if restore(workspace, sha)
            else f"Error: could not restore checkpoint {sha}"
        )
    return f"Error: unknown tool '{name}'"


def keep_or_rollback(
    workspace: str,
    before_sha: str | None,
    test_command: str,
    timeout: int = 300,
) -> tuple[bool, str]:
    """
    The full loop's second half: after the agent edited the tree, run the
    test command; when it fails, restore the pre-edit snapshot. Returns
    (kept, output) — kept=False means the workspace is back at `before_sha`.
    """
    passed, output = verify(workspace, test_command, timeout=timeout)
    if passed or not before_sha:
        return passed, output
    restore(workspace, before_sha)
    return False, output
