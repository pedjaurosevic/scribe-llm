"""
EVOLVE-SCRIBE — Phase 0: score the current Scribe on a frozen held-out suite.

This establishes a baseline fitness number. No mutation, no automation — just a
measurement, plus the safety scaffolding (a checksum-locked eval the agent does
not author, and an append-only ledger). See ``EVOLVE-SCRIBE.md``.

Design note: ``evaluate()`` is pure — it takes an ``answerer`` and a ``judge``
callable, so it is fully testable without a live model. The CLI wires real ones.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
EVAL_DIR = SEED_DIR / "eval"
TASKS_FILE = EVAL_DIR / "tasks.jsonl"
GROUNDED_FILE = EVAL_DIR / "grounded.jsonl"
MANIFEST_FILE = EVAL_DIR / "MANIFEST.sha256"
LEDGER_FILE = Path.home() / ".scribe" / "evolve" / "ledger.jsonl"

# A grader that returns ONLY a tiny JSON verdict, to keep parsing robust.
JUDGE_SYSTEM = (
    "You are a strict grader. You are given a task, the expected answer "
    "language, an ideal-answer rubric, and a candidate answer. Output ONLY a "
    'JSON object: {"score": <integer 0-10>, "language_ok": <true|false>}. '
    "`score` rates correctness and appropriateness (10 = perfect, 0 = wrong/"
    "empty). `language_ok` is whether the candidate is written in the expected "
    "language. Output nothing but the JSON."
)


# --------------------------------------------------------------------- loading
def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_tasks(path: Path = TASKS_FILE) -> list[dict]:
    """Load the held-out tasks from a JSONL file."""
    tasks = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            tasks.append(json.loads(line))
    return tasks


def verify_manifest(
    tasks_path: Path = TASKS_FILE, manifest_path: Path = MANIFEST_FILE
) -> tuple[bool, str]:
    """
    Check every suite file listed in the checksum manifest.

    Returns (ok, detail). ok is False if the manifest is missing or any listed
    file no longer matches — a signal that a held-out suite was touched.
    The single-file `tasks_path` argument is kept for backward compatibility:
    files in the manifest are resolved relative to its directory.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return False, "manifest missing"
    base = manifest_path.parent
    last_digest = ""
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        expected, name = parts
        target = base / name
        if not target.exists():
            return False, f"{name} missing"
        got = file_sha256(target)
        if expected != got:
            return False, f"{name}: expected {expected[:12]}…, got {got[:12]}…"
        last_digest = got
    return True, last_digest


def write_manifest(
    tasks_path: Path = TASKS_FILE, manifest_path: Path = MANIFEST_FILE
) -> str:
    """
    (Re)write the checksum manifest covering every eval suite file present.
    Returns the tasks digest (kept for backward compatibility).
    """
    manifest_path = Path(manifest_path)
    lines = []
    digest = file_sha256(tasks_path)
    lines.append(f"{digest}  {Path(tasks_path).name}")
    grounded = manifest_path.parent / GROUNDED_FILE.name
    if grounded.exists():
        lines.append(f"{file_sha256(grounded)}  {grounded.name}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return digest


# --------------------------------------------------------------------- scoring
def word_count(text: str) -> int:
    return len(text.split())


def parse_judge(out: str) -> tuple[int, bool]:
    """Parse the grader output into (score 0-10, language_ok)."""
    match = re.search(r"\{.*\}", out, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            score = int(data.get("score", 0))
            lang = bool(data.get("language_ok", True))
            return max(0, min(10, score)), lang
        except (ValueError, TypeError):
            pass
    num = re.search(r"\b(10|[0-9])\b", out)
    return (int(num.group(1)) if num else 0), True


def evaluate(
    tasks: list[dict],
    answerer: Callable[[dict], str],
    judge: Callable[[dict, str], tuple[int, bool]],
    on_task: Callable[[int, int, dict], None] | None = None,
) -> dict:
    """
    Run every task through ``answerer``, grade with ``judge``, and aggregate.

    Returns a dict with the mean ``fitness`` (0..1) and per-task results, plus
    the language-match and brevity invariant pass rates.
    """
    results: list[dict] = []
    for i, task in enumerate(tasks):
        answer = answerer(task)
        score10, lang_ok = judge(task, answer)
        words = word_count(answer)
        brief_ok = words <= int(task.get("max_words", 60))
        row = {
            "id": task.get("id", f"task-{i}"),
            "score": score10 / 10.0,
            "lang_ok": lang_ok,
            "brief_ok": brief_ok,
            "words": words,
            "answer": answer,
        }
        results.append(row)
        if on_task:
            on_task(i + 1, len(tasks), row)

    n = len(results) or 1
    return {
        "fitness": sum(r["score"] for r in results) / n,
        "n": len(results),
        "lang_ok_rate": sum(1 for r in results if r["lang_ok"]) / n,
        "brief_ok_rate": sum(1 for r in results if r["brief_ok"]) / n,
        "results": results,
    }


# ---------------------------------------------------------------- live wiring
def _complete(adapter, messages: list[dict]) -> str:
    """Collect just the answer channel from a streaming turn."""
    out = ""
    for kind, text in adapter.streaming_events(messages):
        if kind == "answer":
            out += text
    return out.strip()


def make_answerer(adapter, config) -> Callable[[dict], str]:
    """An answerer that asks the real Scribe (with its real system prompt)."""
    from scribe.prompts import get_system_prompt

    system = get_system_prompt(
        config.reasoning,
        workspace=str(Path(config.workspace_dir)),
        max_thinking_words=config.max_thinking_words,
        mode=config.reasoning_mode,
    )

    def answerer(task: dict) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task["prompt"]},
        ]
        return _complete(adapter, messages)

    return answerer


def make_judge(adapter) -> Callable[[dict, str], tuple[int, bool]]:
    """A judge backed by the same model (single-model self-judge for Phase 0)."""

    def judge(task: dict, answer: str) -> tuple[int, bool]:
        user = (
            f"Task: {task['prompt']}\n"
            f"Expected language: {task.get('lang', 'same as task')}\n"
            f"Ideal answer (rubric): {task.get('rubric', '')}\n"
            f"Candidate answer: {answer}\n\nGrade now."
        )
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user},
        ]
        return parse_judge(_complete(adapter, messages))

    return judge


def make_grounded_answerer(adapter) -> Callable[[dict], str]:
    """
    An answerer for the grounded suite: the task's raw source strings are
    wrapped as chunks and served through the real grounded prompt, so the
    bench measures exactly what `rag ask` does in production.
    """
    from scribe.prompts import get_grounded_prompt

    class _SourceChunk:
        def __init__(self, content: str, index: int):
            self.content = content
            self.source_file = f"source-{index}"
            self.section = ""

    def answerer(task: dict) -> str:
        chunks = [
            _SourceChunk(text, i + 1) for i, text in enumerate(task.get("sources") or [])
        ]
        messages = [
            {"role": "system", "content": get_grounded_prompt(chunks)},
            {"role": "user", "content": task["prompt"]},
        ]
        return _complete(adapter, messages)

    return answerer


def append_ledger(result: dict, model: str, extra: dict | None = None) -> Path:
    """Append a baseline generation to the evolve ledger."""
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "gen": 0,
        "type": "baseline",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "fitness": round(result["fitness"], 4),
        "n": result["n"],
        "lang_ok_rate": round(result["lang_ok_rate"], 4),
        "brief_ok_rate": round(result["brief_ok_rate"], 4),
    }
    if extra:
        entry.update(extra)
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return LEDGER_FILE


def run_eval_cli(config, console, limit=None, write_ledger=True) -> dict:
    """Wire up real answerer/judge, run the suite, and print a report."""
    from rich.box import ROUNDED
    from rich.panel import Panel

    from scribe.llm_adapter import LLMAdapter

    ok, detail = verify_manifest()
    if not ok:
        console.print(
            f"[warning]⚠ Held-out suite checksum check failed[/warning] "
            f"[dim]({detail})[/dim] — results may not be comparable."
        )

    tasks = load_tasks()
    if limit:
        tasks = tasks[:limit]

    adapter = LLMAdapter.from_config(config)
    answerer = make_answerer(adapter, config)
    judge = make_judge(adapter)

    console.print(
        f"[info]EVOLVE-SCRIBE eval[/info] — {len(tasks)} held-out tasks "
        f"[dim](checksum {'ok' if ok else 'MISMATCH'})[/dim]\n"
    )

    def on_task(i: int, n: int, row: dict) -> None:
        mark = (
            "[success]✓[/success]" if row["score"] >= 0.7
            else "[warning]∼[/warning]" if row["score"] > 0
            else "[error]✗[/error]"
        )
        lang = "ok" if row["lang_ok"] else "[error]X[/error]"
        brief = "ok" if row["brief_ok"] else "[warning]long[/warning]"
        console.print(
            f"  {mark} [{i}/{n}] [accent]{row['id']:<18}[/accent] "
            f"score={row['score']:.2f}  lang={lang}  len={brief}({row['words']})"
        )

    result = evaluate(tasks, answerer, judge, on_task=on_task)

    body = (
        f"[bold]Fitness:[/bold] [accent]{result['fitness']:.3f}[/accent]  "
        f"[dim](mean judge score over {result['n']} tasks)[/dim]\n"
        f"Language match: {result['lang_ok_rate']*100:.0f}%   "
        f"Brevity kept:   {result['brief_ok_rate']*100:.0f}%"
    )
    if write_ledger:
        path = append_ledger(result, adapter.get_model_name(),
                             extra={"subset": bool(limit)})
        body += f"\n[dim]Logged to {path}[/dim]"

    console.print()
    console.print(Panel(body, title="[scribe]▌ Baseline[/scribe]",
                        border_style="scribe", box=ROUNDED, padding=(1, 2)))
    return result
