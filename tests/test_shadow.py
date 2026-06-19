"""Tests for the shadow-deployment transaction (pure, injected callables)."""

from __future__ import annotations

from scribe.evolve.shadow import FileChange, ShadowResult, shadow_deploy


class Recorder:
    """Records which transaction steps ran, to assert atomicity."""

    def __init__(self):
        self.applied = False
        self.committed = False
        self.rolled_back = False

    def apply(self, changes):
        self.applied = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


MUTABLE = [FileChange("scribe/skills/writer/SKILL.md", "new content")]
CORE = [FileChange("scribe/tools/sandbox.py", "evil")]


def test_kept_when_score_improves():
    r = Recorder()
    res = shadow_deploy(
        MUTABLE, apply_change=r.apply, run_eval=lambda: 0.9,
        commit=r.commit, rollback=r.rollback, baseline=0.7,
    )
    assert res.status == "kept"
    assert r.committed and not r.rolled_back


def test_rolled_back_when_score_regresses():
    r = Recorder()
    res = shadow_deploy(
        MUTABLE, apply_change=r.apply, run_eval=lambda: 0.5,
        commit=r.commit, rollback=r.rollback, baseline=0.7,
    )
    assert res.status == "rolled_back"
    assert r.rolled_back and not r.committed


def test_rejected_for_protected_path_before_apply():
    r = Recorder()
    res = shadow_deploy(
        CORE, apply_change=r.apply, run_eval=lambda: 1.0,
        commit=r.commit, rollback=r.rollback, baseline=0.0,
    )
    assert res.status == "rejected"
    # Nothing was touched — the guard fired before any side effect.
    assert not r.applied and not r.committed and not r.rolled_back


def test_eval_exception_rolls_back():
    r = Recorder()

    def boom():
        raise RuntimeError("server down")

    res = shadow_deploy(
        MUTABLE, apply_change=r.apply, run_eval=boom,
        commit=r.commit, rollback=r.rollback, baseline=0.5,
    )
    assert res.status == "failed"
    assert r.rolled_back and not r.committed


def test_apply_exception_rolls_back():
    r = Recorder()

    def bad_apply(_):
        raise OSError("disk full")

    res = shadow_deploy(
        MUTABLE, apply_change=bad_apply, run_eval=lambda: 1.0,
        commit=r.commit, rollback=r.rollback, baseline=0.0,
    )
    assert res.status == "failed"
    assert r.rolled_back and not r.committed


def test_min_improvement_threshold():
    r = Recorder()
    # Equal to baseline but min_improvement requires strictly more.
    res = shadow_deploy(
        MUTABLE, apply_change=r.apply, run_eval=lambda: 0.70,
        commit=r.commit, rollback=r.rollback, baseline=0.70, min_improvement=0.05,
    )
    assert res.status == "rolled_back"


def test_empty_changes_rejected():
    r = Recorder()
    res = shadow_deploy(
        [], apply_change=r.apply, run_eval=lambda: 1.0,
        commit=r.commit, rollback=r.rollback, baseline=0.0,
    )
    assert isinstance(res, ShadowResult) and res.status == "rejected"
    assert not r.applied
