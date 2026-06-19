"""Tests for test-time reliability selection (pure, no model)."""

from __future__ import annotations

from scribe.reliability import (
    best_of_n,
    claim_coverage,
    consensus_score,
    score_candidate,
    select_best,
)


def test_claim_coverage_rewards_citations():
    cited = "Zelda leads the team [1]. The deadline is March [2]."
    uncited = "Zelda leads the team. The deadline is March."
    assert claim_coverage(cited) == 1.0
    assert claim_coverage(uncited) == 0.0
    assert claim_coverage("") == 0.0


def test_clean_refusal_counts_as_reliable():
    assert claim_coverage("The sources do not cover this.") == 1.0


def test_consensus_rewards_agreement():
    a = "the cap is 512 megabytes"
    twin = "the cap is 512 megabytes total"
    outlier = "bananas are yellow fruit"
    assert consensus_score(a, [a, twin, outlier]) > consensus_score(outlier, [a, twin, outlier])


def test_select_best_picks_most_grounded():
    grounded = "The cap is 512MB [1]."
    ungrounded = "The cap is probably 1GB or so."
    assert select_best([ungrounded, grounded], prefer_short=False) == grounded


def test_long_to_short_breaks_ties_toward_brevity():
    short = "Milena leads [1]."
    longwinded = (
        "After careful consideration of all the evidence available, "
        "it is clear that Milena leads the team [1]."
    )
    # Both fully cited (same score) -> prefer the shorter one.
    assert select_best([longwinded, short], prefer_short=True) == short
    assert select_best([longwinded, short], prefer_short=False) == longwinded


def test_best_of_n_uses_sampler_and_selects():
    pool = iter(
        [
            "Guess: maybe 1GB.",
            "The cap is 512MB [1].",
            "The cap is 512MB [1].",
        ]
    )
    out = best_of_n(lambda: next(pool), n=3)
    assert out == "The cap is 512MB [1]."


def test_select_best_handles_trivial_inputs():
    assert select_best([]) == ""
    assert select_best(["only one"]) == "only one"


def test_score_candidate_combines_signals():
    strong = "Milena leads [1]. Deadline March 2027 [1]."
    weak = "I think someone leads it, not sure."
    field = [strong, weak]
    assert score_candidate(strong, field) > score_candidate(weak, field)
