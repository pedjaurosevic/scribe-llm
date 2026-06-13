"""
Blind model compare — A/B two models without knowing which is which.

Asks the same prompt of two endpoints, shows the answers as "A" and "B" in a
shuffled order, takes the user's vote, then reveals the mapping. Removes the
halo bias of knowing which model produced an answer — the differentiator
borrowed from Odysseus, useful for picking a local model honestly and for
CANYON-style evaluation.

The core (`build_blind`, `reveal`) is pure and testable; the CLI wires real
adapters and prompts for a vote.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Contestant:
    """One side of a comparison: a label, its model name, and its answer."""

    model: str
    answer: str


@dataclass
class BlindComparison:
    """A shuffled A/B presentation whose mapping is hidden until reveal()."""

    prompt: str
    slots: dict[str, Contestant]   # "A"/"B" -> contestant (shuffled)
    _order: list[str]              # original [left, right] model order

    def labels(self) -> list[str]:
        return sorted(self.slots)

    def reveal(self, vote: str | None) -> dict:
        """
        Resolve a vote ("A"/"B"/None for tie) into a result dict naming the
        winning and losing models.
        """
        result = {
            "prompt": self.prompt,
            "A": self.slots["A"].model,
            "B": self.slots["B"].model,
            "vote": vote,
        }
        if vote in self.slots:
            result["winner"] = self.slots[vote].model
            other = "B" if vote == "A" else "A"
            result["loser"] = self.slots[other].model
        else:
            result["winner"] = None
        return result


def build_blind(
    prompt: str,
    left: Contestant,
    right: Contestant,
    rng: random.Random | None = None,
) -> BlindComparison:
    """Assign the two contestants to slots A/B in a random (seedable) order."""
    rng = rng or random.Random()
    contestants = [left, right]
    rng.shuffle(contestants)
    return BlindComparison(
        prompt=prompt,
        slots={"A": contestants[0], "B": contestants[1]},
        _order=[left.model, right.model],
    )


def answer_with(adapter, model: str, prompt: str, max_tokens: int = 512) -> str:
    """Get one answer from an adapter pinned to a specific model."""
    saved = adapter.model
    adapter.model = model
    adapter._resolved_model = None
    try:
        return adapter.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=max_tokens,
        ).strip()
    finally:
        adapter.model = saved
        adapter._resolved_model = None
