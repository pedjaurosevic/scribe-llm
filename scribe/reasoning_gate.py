"""
Reasoning gate — decide per request whether the model should think.

Always-on reasoning wastes seconds on "hi", always-off cripples debugging.
With `reasoning = "auto"` in config, this gate inspects the latest user
message and turns server-side thinking (`chat_template_kwargs.enable_thinking`)
on only when the request plausibly benefits from it.

The heuristic is deliberately cheap (no LLM call) and bilingual, mirroring how
Scribe is actually used: English and Serbian prompts.
"""

from __future__ import annotations

import re

# Tasks that benefit from a thinking pass before the answer.
_TRIGGER_WORDS = (
    # English
    "why", "how", "explain", "debug", "fix", "error", "plan", "design",
    "compare", "analyze", "analyse", "prove", "calculate", "implement",
    "refactor", "optimize", "step", "algorithm", "trade-off", "tradeoff",
    # Serbian
    "zašto", "zasto", "kako", "objasni", "isprav", "grešk", "gresk",
    "plan", "uporedi", "analiz", "dokaži", "dokazi", "izračun", "izracun",
    "implementir", "refaktor", "optimizuj", "korak", "algorit",
)

# Short conversational openers that never need thinking on their own.
_SMALL_TALK = re.compile(
    r"^(hi|hey|hello|thanks|thank you|ok|okay|yes|no|zdravo|ćao|cao|"
    r"hvala|važi|vazi|da|ne|super|odlično|odlicno)\b[\s!,.?]*$",
    re.IGNORECASE,
)

_CODE_HINT = re.compile(r"```|\bdef\s|\bclass\s|\{.*\}|\bTraceback\b|0x[0-9a-fA-F]+")
_MULTI_STEP = re.compile(r"(^|\n)\s*(\d+[.)]|[-*]\s)", re.MULTILINE)


def should_think(text: str) -> bool:
    """
    True when the request looks like it benefits from a reasoning pass.

    Rules, in order: small talk never thinks; code, tracebacks, multi-step
    structure and long prompts always think; otherwise trigger keywords decide.
    """
    text = (text or "").strip()
    if not text or _SMALL_TALK.match(text):
        return False

    if _CODE_HINT.search(text) or _MULTI_STEP.search(text):
        return True

    words = text.split()
    if len(words) > 80:
        return True

    lowered = text.lower()
    if any(w in lowered for w in _TRIGGER_WORDS):
        return True

    # Question mark on a non-trivial sentence: lean towards thinking.
    return "?" in text and len(words) >= 12


def last_user_text(messages: list[dict]) -> str:
    """The content of the most recent user message, or empty string."""
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            content = msg.get("content")
            return content if isinstance(content, str) else ""
    return ""
