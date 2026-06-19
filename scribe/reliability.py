"""
Test-time reliability — sample several answers, keep the most trustworthy one.

A 12B model improves a lot when you stop taking its first answer on faith. For
verifiable, grounded tasks we draw N candidates and score each on two signals:

    - claim coverage: in a grounded answer, what fraction of claim-sentences
      actually carry a [n] citation (or are an explicit refusal). Uncited
      assertions are the hallucination surface, so more coverage = more trust.
    - consensus: how much a candidate agrees with the others (self-consistency).
      A lone outlier among five is usually the wrong one.

Then **long-to-short**: among candidates within a small margin of the best
score, prefer the *shortest* — reason broadly, answer economically, and avoid
the failure mode of burning tokens on a worse, longer answer.

Everything here is pure: ``best_of_n`` takes a ``sampler`` callable, so the
selection logic is testable without a live model.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_CITATION = re.compile(r"\[\d+\]|\[CONTRADICTION")
_REFUSAL = re.compile(r"do not cover|cannot|can't|no source", re.IGNORECASE)

CLAIM_WEIGHT = 1.0
CONSENSUS_WEIGHT = 1.0
# A candidate this much below the best is never chosen on brevity grounds.
SHORT_MARGIN = 0.05


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text) if s.strip()]


def claim_coverage(answer: str) -> float:
    """
    Fraction of sentences that are grounded — carry a [n]/[CONTRADICTION]
    citation or are an explicit "the sources do not cover this" refusal. Empty
    text scores 0.0; a clean refusal scores 1.0 (a reliable non-answer).
    """
    sents = _sentences(answer)
    if not sents:
        return 0.0
    grounded = sum(1 for s in sents if _CITATION.search(s) or _REFUSAL.search(s))
    return grounded / len(sents)


def consensus_score(answer: str, others: list[str]) -> float:
    """Mean token-Jaccard agreement of ``answer`` with the other candidates."""
    peers = [o for o in others if o is not answer]
    if not peers:
        return 0.0
    a = _tokens(answer)
    if not a:
        return 0.0
    sims = []
    for o in peers:
        b = _tokens(o)
        union = a | b
        sims.append(len(a & b) / len(union) if union else 0.0)
    return sum(sims) / len(sims)


def score_candidate(
    answer: str,
    others: list[str],
    *,
    claim_w: float = CLAIM_WEIGHT,
    consensus_w: float = CONSENSUS_WEIGHT,
) -> float:
    """Combined reliability: claim coverage + agreement with the field."""
    return claim_w * claim_coverage(answer) + consensus_w * consensus_score(answer, others)


def select_best(
    candidates: list[str],
    *,
    prefer_short: bool = True,
    margin: float = SHORT_MARGIN,
    **weights,
) -> str:
    """
    Pick the most reliable candidate. With ``prefer_short`` (default), break
    near-ties (within ``margin`` of the top score) toward the shortest answer.
    """
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]
    scored = [(c, score_candidate(c, candidates, **weights)) for c in candidates]
    best = max(s for _, s in scored)
    contenders = [c for c, s in scored if s >= best - margin]
    if prefer_short and contenders:
        return min(contenders, key=len)
    return max(scored, key=lambda cs: cs[1])[0]


def best_of_n(
    sampler: Callable[[], str],
    n: int = 5,
    *,
    prefer_short: bool = True,
    margin: float = SHORT_MARGIN,
    **weights,
) -> str:
    """Draw ``n`` candidates from ``sampler`` and return the most reliable one."""
    candidates = [sampler() for _ in range(max(1, n))]
    return select_best(candidates, prefer_short=prefer_short, margin=margin, **weights)
