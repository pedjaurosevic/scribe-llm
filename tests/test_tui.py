"""Tests for the pure TUI helpers (no running app)."""

from __future__ import annotations

from rich.cells import cell_len

from scribe.config import ScribeConfig
from scribe.tui_app import dashboard_columns
from scribe.ui.console import hatch_bar


def test_hatch_bar_fills_to_width():
    bar = hatch_bar("Commands", "charm", width=40)
    assert cell_len(bar.plain) == 40
    assert bar.plain.startswith("Commands ")
    assert "╱" in bar.plain


def test_hatch_bar_no_label():
    bar = hatch_bar("", "charm", width=20)
    assert bar.plain == "╱" * 20


def test_dashboard_columns_shape():
    cols = dashboard_columns(ScribeConfig(), ["writer", "grill"], rag_ready=True, sme_count=5)
    headings = [h for h, _ in cols]
    assert headings == ["Tools", "Skills", "Memory"]
    skills_col = dict(cols)["Skills"]
    assert ("writer" in [label for _, label in skills_col])


def test_dashboard_columns_empty_skills_shows_none():
    cols = dashboard_columns(ScribeConfig(), [], rag_ready=False, sme_count=0)
    skills_col = dict(cols)["Skills"]
    assert skills_col == [(False, "none")]
    # Memory dots are off when nothing is ready.
    memory_col = dict(cols)["Memory"]
    assert all(not on for on, _ in memory_col)
