"""
SPI — Source Presence Index, a deterministic grounding metric (from CANYON).

Measures whether an answer actually stays inside its provided sources, with
no LLM judge involved:

- For an answerable task, SPI is the fraction of factual sentences carrying a
  valid citation [n] (n within the source range). Citations pointing outside
  the range count as uncited — an invented source is worse than none.
- For an unanswerable task (the sources genuinely don't contain the answer),
  SPI is 1.0 when the model refuses, 0.0 when it "answers" anyway. Refusing
  correctly is a grounding skill, not a failure.

Used by `scribe bench` over the checksum-locked grounded suite, giving the
harness a number for the claim "answers cite sources or say they can't".
"""

from __future__ import annotations

import re

CITATION = re.compile(r"\[(\d+)\]")

# Phrases (EN/SR) that count as a refusal to answer beyond the sources.
_REFUSAL_MARKERS = (
    "do not cover", "does not cover", "not in the sources", "no source",
    "cannot answer from", "sources do not contain", "not covered by the sources",
    "izvori ne pokrivaju", "nema u izvorima", "izvori ne sadrže",
    "ne mogu da odgovorim na osnovu izvora",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split into sentences; heading lines are dropped, bullet markers stripped."""
    parts = []
    for line in text.strip().splitlines():
        line = line.strip().lstrip("-*• ").strip()
        if not line or line.startswith("#"):
            continue
        for raw in _SENTENCE_SPLIT.split(line):
            s = raw.strip()
            if s:
                parts.append(s)
    return parts


def is_refusal(text: str) -> bool:
    """Whether the answer declines to go beyond the sources."""
    lowered = text.lower()
    return any(marker in lowered for marker in _REFUSAL_MARKERS)


def spi_score(answer: str, n_sources: int, answerable: bool = True) -> dict:
    """
    Score one answer. Returns a dict with `spi` (0..1) plus diagnostics:
    sentences, cited (validly), invalid_citations, refused.
    """
    answer = (answer or "").strip()
    refused = is_refusal(answer)

    if not answerable:
        return {
            "spi": 1.0 if refused else 0.0,
            "sentences": 0,
            "cited": 0,
            "invalid_citations": 0,
            "refused": refused,
        }

    sentences = split_sentences(answer)
    if not sentences or refused:
        # Refusing an answerable question grounds nothing.
        return {
            "spi": 0.0,
            "sentences": len(sentences),
            "cited": 0,
            "invalid_citations": 0,
            "refused": refused,
        }

    cited = 0
    invalid = 0
    for sentence in sentences:
        refs = [int(m) for m in CITATION.findall(sentence)]
        valid = [r for r in refs if 1 <= r <= n_sources]
        if len(valid) < len(refs):
            invalid += len(refs) - len(valid)
        if valid:
            cited += 1

    return {
        "spi": cited / len(sentences),
        "sentences": len(sentences),
        "cited": cited,
        "invalid_citations": invalid,
        "refused": False,
    }


def evaluate_grounded(tasks: list[dict], answerer) -> dict:
    """
    Run grounded tasks through `answerer` and aggregate SPI.

    Each task: {id, sources: [str], prompt, answerable: bool}. Pure function —
    `answerer(task) -> str` is injected, so the harness is testable offline.
    """
    results = []
    for i, task in enumerate(tasks):
        answer = answerer(task)
        score = spi_score(
            answer,
            n_sources=len(task.get("sources") or []),
            answerable=bool(task.get("answerable", True)),
        )
        results.append({"id": task.get("id", f"grounded-{i}"), "answer": answer, **score})
    n = len(results) or 1
    return {
        "spi": sum(r["spi"] for r in results) / n,
        "n": len(results),
        "invalid_citations": sum(r["invalid_citations"] for r in results),
        "results": results,
    }


def load_grounded_tasks(path=None) -> list[dict]:
    """Load the grounded held-out suite (JSONL)."""
    import json
    from pathlib import Path

    from scribe.evolve.evaluate import GROUNDED_FILE

    target = Path(path) if path else GROUNDED_FILE
    tasks = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            tasks.append(json.loads(line))
    return tasks


def run_spi_cli(config, console, limit=None) -> dict:
    """Run the grounded suite against the live model and print SPI."""
    from scribe.evolve.evaluate import make_grounded_answerer, verify_manifest
    from scribe.llm_adapter import LLMAdapter

    ok, detail = verify_manifest()
    if not ok:
        console.print(
            f"[warning]⚠ Held-out suite checksum check failed[/warning] "
            f"[dim]({detail})[/dim] — results may not be comparable."
        )

    tasks = load_grounded_tasks()
    if limit:
        tasks = tasks[:limit]

    adapter = LLMAdapter.from_config(config)
    console.print(f"[info]SPI grounding bench[/info] — {len(tasks)} grounded tasks\n")

    answerer = make_grounded_answerer(adapter)
    result = evaluate_grounded(tasks, answerer)
    for row in result["results"]:
        mark = (
            "[success]✓[/success]" if row["spi"] >= 0.8
            else "[warning]∼[/warning]" if row["spi"] > 0
            else "[error]✗[/error]"
        )
        console.print(
            f"  {mark} [accent]{row['id']:<28}[/accent] spi={row['spi']:.2f}  "
            f"cited={row['cited']}/{row['sentences']}"
            + (f"  [error]invalid={row['invalid_citations']}[/error]"
               if row["invalid_citations"] else "")
            + ("  [dim]refused[/dim]" if row["refused"] else "")
        )
    console.print(
        f"\n[bold]SPI:[/bold] [accent]{result['spi']:.3f}[/accent]  "
        f"[dim](source-grounding over {result['n']} tasks)[/dim]"
    )
    return result
