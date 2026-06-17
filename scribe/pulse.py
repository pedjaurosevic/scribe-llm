"""
Pulse and Diary — lightweight continuity (from Konok).

Pulse: an append-only heartbeat log (`~/.scribe/pulse.jsonl`). A systemd timer
(or cron) calls `scribe-llm pulse` on an interval; each beat records that the agent
and its server are alive, with a one-line status. The log is the agent's proof
that time passed between sessions.

Diary: a nightly reflection. `scribe-llm diary` reads the day's session
transcripts and asks the model to write a short Markdown reflection to
`~/.scribe/diary/<date>.md`. Opt-in, cheap, and human-readable.

Both degrade to no-ops when their inputs are missing — they never block.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

PULSE_FILE = Path.home() / ".scribe" / "pulse.jsonl"
DIARY_DIR = Path.home() / ".scribe" / "diary"


def beat(config, path: Path | str | None = None) -> dict:
    """Record one heartbeat: timestamp, server reachability, model. Returns the
    event written."""
    from scribe.llm_adapter import LLMAdapter

    adapter = LLMAdapter.from_config(config)
    healthy = adapter.is_healthy()
    event = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "server_up": healthy,
        "model": adapter.get_model_name() if healthy else None,
    }
    target = Path(path) if path else PULSE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def last_beat(path: Path | str | None = None) -> dict | None:
    """The most recent heartbeat, or None."""
    target = Path(path) if path else PULSE_FILE
    if not target.exists():
        return None
    lines = [ln for ln in target.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def _todays_transcripts(sessions_dir: Path, day: str) -> list[str]:
    """Markdown transcripts for sessions created on `day` (YYYYMMDD prefix)."""
    if not sessions_dir.exists():
        return []
    texts = []
    for path in sorted(sessions_dir.glob(f"{day}_*.md")):
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return texts


def write_diary(config, on_date: date | None = None, diary_dir: Path | None = None) -> Path | None:
    """
    Reflect on a day's sessions and save a short Markdown entry.

    Returns the entry path, or None when there were no sessions that day (no
    empty diary entries are written).
    """
    from scribe.llm_adapter import LLMAdapter
    from scribe.session import SessionManager

    on_date = on_date or date.today()
    day = on_date.strftime("%Y%m%d")
    manager = SessionManager(config)
    transcripts = _todays_transcripts(manager.sessions_dir, day)
    if not transcripts:
        return None

    corpus = "\n\n---\n\n".join(transcripts)[:24000]
    system = (
        "You are Scribe, writing a brief private diary entry about your own work "
        "today. Reflect in 4-8 sentences: what the user worked on, what you did, "
        "what went well or badly, and what to remember next time. Write in the "
        "user's language. Be concrete and honest, not flattering."
    )
    adapter = LLMAdapter.from_config(config)
    reflection = adapter.complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Today's sessions:\n\n{corpus}"},
        ],
        temperature=0.7,
    ).strip()

    out_dir = diary_dir or DIARY_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    entry = out_dir / f"{on_date.isoformat()}.md"
    entry.write_text(
        f"# {on_date.isoformat()}\n\n{reflection}\n", encoding="utf-8"
    )
    return entry
