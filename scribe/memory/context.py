"""
Cascade of trust — one precedence order over the three memory sources.

Small local models hallucinate when a stale RAG passage, a wrong thing the
agent tried in a past session (SME), and an absolute WorldModel fact all land
in the window with equal weight. This module imposes a single ordering before
anything reaches the prompt:

    1. WorldModel  — absolute truth, rendered into the system prompt; overrides all.
    2. RAG sources — factual / procedural knowledge, numbered [n] for citation.
    3. SME         — episodic working memory, ranked by recency + significance
                     + relevance, and explicitly the least trusted tier.

The ranking core is pure and duck-typed: SME entries only need ``.content``,
``.created_at`` (ISO 8601) and ``.metadata`` (a dict), so the cascade is
testable offline with plain stand-ins, no SME/RAG service required.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# Default weights for the SME ranking signal. Equal by default; callers (or a
# future config knob) can retune without touching the call sites.
RECENCY_WEIGHT = 1.0
SIGNIFICANCE_WEIGHT = 1.0
RELEVANCE_WEIGHT = 1.0

# A memory this old contributes half its recency score; newer wins.
RECENCY_HALFLIFE_DAYS = 7.0

# The instruction that turns the ordering into model behaviour. Kept short on
# purpose — long rules leak tokens and small models skim them.
CASCADE_RESOLUTION = (
    "## Trust precedence (when these disagree)\n"
    "\n"
    '1. The facts under "Who and where you are" are absolute — they override'
    " every source below.\n"
    "2. For technical facts and code syntax, trust the numbered Sources [n].\n"
    "3. For what the user wants and earlier context, trust Working memory —"
    " and treat it as the least reliable tier.\n"
    "\n"
    "If a Source and Working memory disagree on a code example, use the Source"
    " for syntax and Working memory only for the user's intent. Never blend a"
    " WorldModel fact with a source that contradicts it."
)


def _tokenize(text: str) -> set[str]:
    """Lowercase word set, for a cheap deterministic relevance signal."""
    return set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


def recency_score(created_at: str, now: datetime) -> float:
    """
    Exponential-decay recency in [0, 1]: 1.0 for "just now", 0.5 at one
    half-life. Unparseable timestamps yield a neutral 0.5 rather than crashing.
    """
    try:
        ts = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return 0.5
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALFLIFE_DAYS)


def significance_score(entry) -> float:
    """
    Significance in [0, 1] from ``entry.metadata['significance']`` when present
    (already 0–1), else a neutral 0.5. Lets the SME writer mark what matters.
    """
    meta = getattr(entry, "metadata", None) or {}
    raw = meta.get("significance", 0.5)
    try:
        return max(0.0, min(1.0, float(raw)))
    except (ValueError, TypeError):
        return 0.5


def relevance_score(query: str, content: str) -> float:
    """
    Lexical overlap in [0, 1]: fraction of the query's words present in the
    entry. Cheap and deterministic — semantic recall already happened in RAG;
    here we only need a stable rerank signal for episodic memory.
    """
    q = _tokenize(query)
    if not q:
        return 0.0
    return len(q & _tokenize(content)) / len(q)


def score_entry(
    entry,
    query: str,
    now: datetime,
    *,
    recency_w: float = RECENCY_WEIGHT,
    significance_w: float = SIGNIFICANCE_WEIGHT,
    relevance_w: float = RELEVANCE_WEIGHT,
) -> float:
    """Weighted recency + significance + relevance for one SME entry."""
    return (
        recency_w * recency_score(getattr(entry, "created_at", ""), now)
        + significance_w * significance_score(entry)
        + relevance_w * relevance_score(query, getattr(entry, "content", ""))
    )


def rank_sme(entries, query: str, now: datetime | None = None, limit: int = 5, **weights):
    """
    Rank SME entries best-first by the cascade score and keep the top ``limit``.
    Pure: pass any objects exposing ``.content`` / ``.created_at`` / ``.metadata``.
    """
    now = now or datetime.now(timezone.utc)
    ranked = sorted(entries, key=lambda e: score_entry(e, query, now, **weights), reverse=True)
    return ranked[:limit]


def assemble_context(
    *,
    worldmodel_block: str = "",
    chunks=None,
    sme_entries=None,
    query: str = "",
    now: datetime | None = None,
    sme_limit: int = 5,
) -> str:
    """
    Compose the full trusted-context block in precedence order, with the
    conflict-resolution note appended only when more than one tier is present
    (a single tier cannot conflict with itself, so the note is dead weight).

    ``chunks`` are RAG chunks (``.content`` / ``.source_file``); ``sme_entries``
    are episodic memories. Both default to empty.
    """
    from scribe.prompts import grounded_context

    chunks = list(chunks or [])
    sme_entries = list(sme_entries or [])

    tiers = 0
    parts: list[str] = []

    if worldmodel_block.strip():
        parts.append(worldmodel_block.rstrip())
        tiers += 1

    if chunks:
        parts.append(grounded_context(chunks).rstrip())
        tiers += 1

    top = rank_sme(sme_entries, query, now=now, limit=sme_limit)
    if top:
        lines = ["## Working memory (recent, may be uncertain)", ""]
        lines += [f"- {getattr(e, 'content', '').strip()}" for e in top]
        parts.append("\n".join(lines))
        tiers += 1

    if tiers > 1:
        parts.append(CASCADE_RESOLUTION)

    return "\n\n".join(parts)
