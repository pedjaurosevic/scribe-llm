"""
Immutable core — what the self-improvement loop may and may not rewrite.

A self-modifying agent that can edit its own safety code can also delete it.
The one rule that makes evolution safe is a hard boundary: the agent mutates
**only** prompts, skills and config; it can never touch the security core
(sandbox/gates/grammar), the evolve machinery itself, or the held-out suite it
is graded against (rewriting the exam is the purest form of cheating).

This module is the single source of truth for that boundary. It is pure — it
classifies repo-relative paths as strings, so it is testable without touching
the filesystem, and every write the loop attempts goes through
``assert_mutation_allowed`` first.

Three classes:
    - "mutable": the agent may rewrite it (skills, the prompt overlay).
    - "frozen":  inviolable by construction — the constitution and the
                 checksum-locked held-out eval. Denied even though it lives
                 under an otherwise-mutable tree.
    - "core":    security / evolve / harness code. Denied, full stop.
"""

from __future__ import annotations

from pathlib import PurePosixPath

# Roots the agent is allowed to rewrite (repo-relative, POSIX separators).
MUTABLE_ROOTS = (
    "scribe/skills/",
    "scribe/seed/system.md",
)

# Always denied, even when nested under a mutable root — the agent must never
# edit its own constitution or the exam it is scored against.
FROZEN_PATHS = (
    "scribe/seed/constitution.md",
    "scribe/seed/eval/",
)

# The security / evolve / harness core. Editing any of these could disable a
# safety layer or corrupt the grader, so they are off-limits regardless.
CORE_PATHS = (
    "scribe/tools/sandbox.py",
    "scribe/tools/shell.py",
    "scribe/tools/checkpoint.py",
    "scribe/tools/fs.py",
    "scribe/grammar.py",
    "scribe/evolve/",
    "scribe/mail.py",
    "scribe/web.py",
)


class ImmutableCoreError(PermissionError):
    """Raised when the evolve loop tries to mutate a protected path."""


def _norm(path: str) -> str:
    """Repo-relative POSIX string; absolute paths under the repo are trimmed."""
    p = PurePosixPath(str(path).replace("\\", "/"))
    parts = p.parts
    # Keep from the LAST 'scribe' segment so the package wins even when the repo
    # directory is also named scribe (/abs/scribe/scribe/x -> scribe/x).
    idxs = [i for i, seg in enumerate(parts) if seg == "scribe"]
    if idxs:
        p = PurePosixPath(*parts[idxs[-1]:])
    return p.as_posix()


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    for pre in prefixes:
        if pre.endswith("/"):
            if path == pre.rstrip("/") or path.startswith(pre):
                return True
        elif path == pre:
            return True
    return False


def classify_path(path: str) -> str:
    """
    Return "mutable", "frozen" or "core" for a repo path. Frozen and core both
    deny the write; the distinction is only for clearer diagnostics. Anything
    not explicitly mutable is denied (default-closed), so a new sensitive file
    is protected until someone opts it into a mutable root on purpose.
    """
    norm = _norm(path)
    if _under(norm, FROZEN_PATHS):
        return "frozen"
    if _under(norm, CORE_PATHS):
        return "core"
    if _under(norm, MUTABLE_ROOTS):
        return "mutable"
    return "core"  # default-closed: unknown paths are treated as protected


def is_mutation_allowed(path: str) -> bool:
    """True only when the evolve loop may rewrite ``path``."""
    return classify_path(path) == "mutable"


def assert_mutation_allowed(path: str) -> None:
    """Raise ``ImmutableCoreError`` unless ``path`` is mutable."""
    kind = classify_path(path)
    if kind != "mutable":
        raise ImmutableCoreError(
            f"refusing to mutate protected path ({kind}): {_norm(path)} — "
            "the evolve loop may only change skills and the prompt overlay"
        )
