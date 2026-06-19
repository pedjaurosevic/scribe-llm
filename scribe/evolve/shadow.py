"""
Shadow deployment — apply a self-proposed change only if it survives the exam.

A safe evolution step is transactional: the agent's proposed edit is applied to
a *shadow* (a throwaway git branch / worktree), the checksum-locked held-out
suite is run against it, an oracle scores the result, and the change is kept
**only** if it does not regress — otherwise it is rolled back and discarded.
Nothing reaches the live tree on a failure or an error.

Two guarantees compose here:
  - the immutable-core guard ([[guard]]) rejects any change outside the mutable
    surface (skills / prompt overlay) *before* anything is applied;
  - the apply → eval → keep/rollback sequence is atomic — a raised apply or
    eval always rolls back, and ``commit`` only runs on a clean pass.

``shadow_deploy`` is pure: the git/bwrap/eval steps are injected as callables,
so the whole transaction is testable offline with fakes and no model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from scribe.evolve.guard import classify_path, is_mutation_allowed


@dataclass
class FileChange:
    """One proposed edit: replace ``path`` with ``new_content``."""

    path: str
    new_content: str


@dataclass
class ShadowResult:
    status: str  # "kept" | "rolled_back" | "rejected" | "failed"
    score: float | None
    baseline: float
    reason: str = ""


def shadow_deploy(
    changes: list[FileChange],
    *,
    apply_change: Callable[[list[FileChange]], None],
    run_eval: Callable[[], float],
    commit: Callable[[], None],
    rollback: Callable[[], None],
    baseline: float,
    min_improvement: float = 0.0,
) -> ShadowResult:
    """
    Run one transactional shadow deployment.

    Order: guard every path → apply to the shadow → run the held-out eval →
    keep if ``score >= baseline + min_improvement`` else roll back. Any
    exception during apply or eval rolls back and returns "failed"; ``commit``
    is never called unless the change passed.
    """
    if not changes:
        return ShadowResult("rejected", None, baseline, "no changes proposed")

    # 1. Boundary: refuse anything outside the mutable surface before touching
    #    the tree at all.
    for ch in changes:
        if not is_mutation_allowed(ch.path):
            return ShadowResult(
                "rejected", None, baseline,
                f"path is {classify_path(ch.path)}, not mutable: {ch.path}",
            )

    # 2. Apply to the shadow.
    try:
        apply_change(changes)
    except Exception as exc:  # noqa: BLE001 — any failure must roll back cleanly
        rollback()
        return ShadowResult("failed", None, baseline, f"apply failed: {exc}")

    # 3. Grade against the held-out suite.
    try:
        score = run_eval()
    except Exception as exc:  # noqa: BLE001
        rollback()
        return ShadowResult("failed", None, baseline, f"eval failed: {exc}")

    # 4. Keep only on a non-regression; otherwise discard.
    threshold = baseline + min_improvement
    if score >= threshold:
        try:
            commit()
        except Exception as exc:  # noqa: BLE001
            rollback()
            return ShadowResult("failed", score, baseline, f"commit failed: {exc}")
        return ShadowResult(
            "kept", score, baseline, f"{score:.3f} >= {threshold:.3f} — kept"
        )

    rollback()
    return ShadowResult(
        "rolled_back", score, baseline, f"{score:.3f} < {threshold:.3f} — rolled back"
    )
