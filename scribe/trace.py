"""
ORORO traces — a deterministic, append-only record of what the agent did.

One JSONL file per session (`sessions/<id>/trace.jsonl`). Every event is one
canonical JSON line: sorted keys, explicit monotone `seq`, stable `kind`
vocabulary. Two runs of the same scenario diff cleanly line by line, and a
bug report can be a trace file instead of a prose reconstruction.

Event kinds (the stable vocabulary — extend, never repurpose):
    session_start   topic, mode
    turn_start      role, chars
    tool_call       name, arguments
    tool_result     name, ok, chars
    tool_repair     reason            (a GBNF grammar-retry fired)
    answer          chars, thinking_chars
    session_end     status
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

TRACE_FILE = "trace.jsonl"


class Tracer:
    """Append-only canonical-JSON event writer. Never raises into the host."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._seq = 0
        self._lock = threading.Lock()

    def event(self, kind: str, **payload) -> None:
        """Record one event. Failures are swallowed — tracing must not break
        the session it observes."""
        try:
            with self._lock:
                self._seq += 1
                record = {
                    "seq": self._seq,
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "kind": kind,
                    **payload,
                }
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        except OSError:
            pass


def read_trace(path: Path | str) -> list[dict]:
    """Load a trace file back into event dicts (skipping corrupt lines)."""
    events = []
    target = Path(path)
    if not target.exists():
        return events
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def trace_summary(path: Path | str) -> dict:
    """Aggregate one trace: event counts per kind plus basic shape checks."""
    events = read_trace(path)
    kinds: dict[str, int] = {}
    for e in events:
        kinds[e.get("kind", "?")] = kinds.get(e.get("kind", "?"), 0) + 1
    seqs = [e.get("seq", 0) for e in events]
    return {
        "events": len(events),
        "kinds": kinds,
        "monotone": seqs == sorted(seqs) and len(set(seqs)) == len(seqs),
    }
