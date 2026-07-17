"""
Multi-model grounding leaderboard.

Runs the deterministic SPI grounding suite (see `scribe.evolve.spi`) against
several models and ranks them, so the claim "answers cite sources or say they
can't" becomes a comparable number across local and cloud backends — a
measuring instrument, not a single self-reported score.

The core `run_multi_model_bench` is a pure function: the per-model `answerer`
is injected via `answerer_factory`, so the ranking logic is tested offline with
no server. The CLI wiring (`run_leaderboard_cli`) supplies a real
llama.cpp/OpenAI-compatible answerer.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from scribe.evolve.spi import evaluate_grounded


def run_multi_model_bench(
    model_specs: list[dict],
    answerer_factory: Callable[[dict], Callable[[dict], str]],
    tasks: list[dict],
) -> dict:
    """
    Run the grounded SPI suite against several models and rank them.

    Args:
        model_specs: list of {name, base_url, model, api_key_env?} entries.
        answerer_factory: spec -> answerer(task)->str. Injected so the ranking
            is testable without a live server.
        tasks: grounded suite tasks (see `spi.load_grounded_tasks`).

    Returns a report dict: {ts, n_tasks, rows} where rows are ranked by SPI
    descending, ties broken by fewer invalid citations.
    """
    rows = []
    for spec in model_specs:
        base = {
            "name": spec.get("name") or spec.get("model") or spec.get("base_url") or "?",
            "model": spec.get("model", "default"),
            "base_url": spec.get("base_url", ""),
        }
        answerer = answerer_factory(spec)
        try:
            result = evaluate_grounded(tasks, answerer)
        except Exception as exc:
            # One unreachable/broken server must not kill the whole run;
            # the failure stays visible as an unranked row.
            rows.append(
                {
                    **base,
                    "spi": None,
                    "invalid_citations": None,
                    "n": 0,
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                }
            )
            continue
        rows.append(
            {
                **base,
                "spi": round(result["spi"], 4),
                "invalid_citations": result["invalid_citations"],
                "n": result["n"],
            }
        )
    scored = [r for r in rows if r["spi"] is not None]
    failed = [r for r in rows if r["spi"] is None]
    scored.sort(key=lambda r: (-r["spi"], r["invalid_citations"], r["name"]))
    rows = scored + failed
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "n_tasks": len(tasks),
        "rows": rows,
    }


def render_leaderboard_md(report: dict, suite_checksum: str | None = None) -> str:
    """Render a report as a GitHub-friendly markdown leaderboard."""
    lines = [
        "# Scribe Grounding Leaderboard",
        "",
        "Source-Presence Index (SPI) over the checksum-locked grounded suite "
        f"({report['n_tasks']} tasks). Higher is better: SPI 1.00 means every "
        "factual sentence carries a valid `[n]` citation (or the model correctly "
        "refuses when the sources don't cover the question). No LLM judge is "
        "involved — the metric is deterministic.",
        "",
        "_Generated " + report["ts"]
        + (f" · suite `{suite_checksum[:12]}`" if suite_checksum else "")
        + "_",
        "",
        "| Rank | Model | SPI | Invalid citations |",
        "| ---: | :--- | ---: | ---: |",
    ]
    for row in report["rows"]:
        if row.get("spi") is None:
            lines.append(
                f"| {row['rank']} | {row['name']} ⚠ `{row.get('error', 'failed')}` "
                "| — | — |"
            )
        else:
            lines.append(
                f"| {row['rank']} | {row['name']} | {row['spi']:.3f} | "
                f"{row['invalid_citations']} |"
            )
    lines.append("")
    return "\n".join(lines)


def _make_answerer_factory(timeout: int = 600):
    """
    Build a factory that turns a model spec into a live grounded answerer.

    The API key is read from the env var named by `api_key_env` (so secrets stay
    out of config.toml), falling back to "not-needed" for local llama.cpp.
    """
    from scribe.evolve.evaluate import make_grounded_answerer
    from scribe.llm_adapter import LLMAdapter

    def factory(spec: dict) -> Callable[[dict], str]:
        api_key = "not-needed"
        env_name = spec.get("api_key_env")
        if env_name:
            api_key = os.environ.get(env_name, "") or "not-needed"
        adapter = LLMAdapter(
            base_url=spec.get("base_url"),
            api_key=api_key,
            model=spec.get("model"),
            timeout=timeout,
        )
        return make_grounded_answerer(adapter)

    return factory


def run_leaderboard_cli(config, console, limit=None) -> dict | None:
    """Run the multi-model grounding bench from `[scribe.bench]` config."""
    from scribe.evolve.evaluate import verify_manifest
    from scribe.evolve.spi import load_grounded_tasks

    specs = getattr(config, "bench_models", None) or []
    if not specs:
        console.print(
            "[warning]No models configured for the leaderboard.[/warning] "
            "Add a [accent][scribe.bench][/accent] section with a "
            "[accent]models[/accent] list (name/base_url/model)."
        )
        return None

    ok, checksum = verify_manifest()
    if not ok:
        console.print(
            f"[warning]⚠ Held-out suite checksum check failed[/warning] "
            f"[dim]({checksum})[/dim] — results may not be comparable."
        )
        checksum = None

    tasks = load_grounded_tasks()
    if limit:
        tasks = tasks[:limit]

    console.print(
        f"[info]Grounding leaderboard[/info] — {len(specs)} models × "
        f"{len(tasks)} grounded tasks\n"
    )

    factory = _make_answerer_factory(timeout=config.request_timeout)
    report = run_multi_model_bench(specs, factory, tasks)

    for row in report["rows"]:
        if row.get("spi") is None:
            console.print(
                f"  [accent]{row['rank']}.[/accent] [bold]{row['name']:<24}[/bold] "
                f"[error]✗ {row.get('error', 'failed')}[/error]"
            )
            continue
        console.print(
            f"  [accent]{row['rank']}.[/accent] [bold]{row['name']:<24}[/bold] "
            f"spi=[accent]{row['spi']:.3f}[/accent]"
            + (f"  [error]invalid={row['invalid_citations']}[/error]"
               if row["invalid_citations"] else "")
        )

    md = render_leaderboard_md(report, checksum)
    out_md = Path("docs") / "leaderboard.md"
    out_json = Path("docs") / "leaderboard.json"
    try:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md, encoding="utf-8")
        out_json.write_text(
            json.dumps({"suite_checksum": checksum, **report}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(f"\n[success]✓[/success] Wrote [accent]{out_md}[/accent] and "
                      f"[accent]{out_json}[/accent]")
    except OSError as exc:
        console.print(f"\n[warning]Could not write leaderboard files: {exc}[/warning]")

    return report
