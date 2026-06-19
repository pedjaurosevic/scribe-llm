"""Tests for the immutable-core boundary (pure path classification)."""

from __future__ import annotations

import pytest

from scribe.evolve.guard import (
    ImmutableCoreError,
    assert_mutation_allowed,
    classify_path,
    is_mutation_allowed,
)


@pytest.mark.parametrize(
    "path",
    [
        "scribe/skills/writer/SKILL.md",
        "scribe/skills/new-skill/SKILL.md",
        "scribe/seed/system.md",
    ],
)
def test_mutable_paths_allowed(path):
    assert classify_path(path) == "mutable"
    assert is_mutation_allowed(path)


@pytest.mark.parametrize(
    "path",
    [
        "scribe/seed/constitution.md",
        "scribe/seed/eval/tasks.jsonl",
        "scribe/seed/eval/MANIFEST.sha256",
    ],
)
def test_frozen_paths_denied(path):
    assert classify_path(path) == "frozen"
    assert not is_mutation_allowed(path)


@pytest.mark.parametrize(
    "path",
    [
        "scribe/tools/sandbox.py",
        "scribe/grammar.py",
        "scribe/evolve/guard.py",
        "scribe/web.py",
        "scribe/mail.py",
    ],
)
def test_core_paths_denied(path):
    assert classify_path(path) == "core"
    assert not is_mutation_allowed(path)


def test_unknown_path_is_default_closed():
    # A path under no mutable root is protected until opted in on purpose.
    assert classify_path("scribe/llm_adapter.py") == "core"
    assert not is_mutation_allowed("scribe/some_new_file.py")


def test_absolute_path_is_normalised():
    abs_skill = "/home/user/scribe/scribe/skills/writer/SKILL.md"
    assert is_mutation_allowed(abs_skill)
    abs_core = "/home/user/scribe/scribe/tools/sandbox.py"
    assert not is_mutation_allowed(abs_core)


def test_assert_raises_for_protected_and_passes_for_mutable():
    assert_mutation_allowed("scribe/skills/writer/SKILL.md")  # no raise
    with pytest.raises(ImmutableCoreError):
        assert_mutation_allowed("scribe/tools/sandbox.py")
    with pytest.raises(ImmutableCoreError):
        assert_mutation_allowed("scribe/seed/eval/tasks.jsonl")
