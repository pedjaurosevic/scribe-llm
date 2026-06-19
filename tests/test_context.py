"""Tests for the cascade-of-trust context assembly (pure, no server)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from scribe.memory.context import (
    CASCADE_RESOLUTION,
    assemble_context,
    rank_sme,
    recency_score,
    relevance_score,
    score_entry,
    significance_score,
)

NOW = datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class FakeEntry:
    content: str
    created_at: str
    metadata: dict = field(default_factory=dict)


@dataclass
class FakeChunk:
    content: str
    source_file: str = "doc.md"
    section: str = ""


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def test_recency_decays_and_clamps():
    assert recency_score(_iso(0), NOW) == 1.0
    assert abs(recency_score(_iso(7), NOW) - 0.5) < 1e-9  # one half-life
    assert recency_score(_iso(0), NOW) > recency_score(_iso(30), NOW)
    assert recency_score("not-a-date", NOW) == 0.5  # neutral, never crashes


def test_significance_from_metadata():
    assert significance_score(FakeEntry("x", _iso(0), {"significance": 1.0})) == 1.0
    assert significance_score(FakeEntry("x", _iso(0), {})) == 0.5  # default
    assert significance_score(FakeEntry("x", _iso(0), {"significance": "bad"})) == 0.5


def test_relevance_is_query_overlap():
    assert relevance_score("rlimit memory cap", "the RLIMIT_AS memory cap") > 0
    assert relevance_score("zebra", "the RLIMIT_AS memory cap") == 0.0
    assert relevance_score("", "anything") == 0.0


def test_rank_prefers_recent_significant_relevant():
    recent = FakeEntry("user prefers srpski for chat", _iso(0), {"significance": 0.9})
    stale = FakeEntry("user prefers srpski for chat", _iso(90), {"significance": 0.9})
    irrelevant = FakeEntry("unrelated note about cats", _iso(0), {"significance": 0.9})
    ranked = rank_sme([stale, irrelevant, recent], query="srpski chat", now=NOW, limit=3)
    assert ranked[0] is recent  # recency breaks the tie against the stale twin
    assert ranked.index(recent) < ranked.index(irrelevant)


def test_rank_respects_limit():
    entries = [FakeEntry(f"note {i}", _iso(i)) for i in range(10)]
    assert len(rank_sme(entries, query="note", now=NOW, limit=3)) == 3


def test_assemble_orders_tiers_and_adds_resolution():
    out = assemble_context(
        worldmodel_block="## Who and where you are\n\nYou are Scribe.",
        chunks=[FakeChunk("The cap is 512MB.", "spec.md")],
        sme_entries=[FakeEntry("user is on a 12GB GPU", _iso(0))],
        query="memory cap",
        now=NOW,
    )
    # Precedence order: WorldModel, then Sources, then Working memory.
    assert out.index("Who and where you are") < out.index("## Sources")
    assert out.index("## Sources") < out.index("## Working memory")
    # Multiple tiers -> conflict-resolution note is present.
    assert CASCADE_RESOLUTION in out


def test_single_tier_skips_resolution_note():
    out = assemble_context(worldmodel_block="## Who and where you are\n\nYou are Scribe.")
    assert CASCADE_RESOLUTION not in out  # nothing to conflict with
    assert "Who and where you are" in out


def test_empty_inputs_yield_empty_string():
    assert assemble_context() == ""


def test_system_prompt_carries_cascade_with_worldmodel():
    # Live wiring: the precedence rule reaches the model whenever the agent has
    # a WorldModel, and can be turned off.
    from scribe.prompts import get_system_prompt
    from scribe.worldmodel import WorldModel

    wm = WorldModel()
    assert CASCADE_RESOLUTION in get_system_prompt(worldmodel=wm)
    assert CASCADE_RESOLUTION not in get_system_prompt(worldmodel=wm, memory_cascade=False)
    assert CASCADE_RESOLUTION not in get_system_prompt()  # no worldmodel -> no note


def test_score_entry_combines_all_three_signals():
    weak = FakeEntry("cats", _iso(90), {"significance": 0.0})
    strong = FakeEntry("memory cap rlimit", _iso(0), {"significance": 1.0})
    assert score_entry(strong, "memory cap", NOW) > score_entry(weak, "memory cap", NOW)
