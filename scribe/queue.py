"""
AFK task queue — define narrow tasks, let the model work them, you review.

The opposite of an open-ended agent loop that keeps pinging the model. You
queue tightly-scoped tasks (the strategic-programmer move: design the hard
parts, delegate the well-defined ones), then run them one at a time or in a
batch while away from the keyboard. Each task records its result so you return
as a manager reviewing finished work, not a babysitter watching a loop.

The queue is a JSON file; the run logic takes an injected ``executor`` callable,
so the whole thing is testable offline with a fake executor — no model needed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_QUEUE = Path.home() / "scribe-workspace" / "queue.json"

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Task:
    id: str
    prompt: str
    status: str = PENDING
    created_at: str = field(default_factory=_now)
    finished_at: str = ""
    result: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


class TaskQueue:
    """A file-backed FIFO of delegated tasks."""

    def __init__(self, queue_file: Path | str | None = None):
        self.queue_file = Path(queue_file) if queue_file else DEFAULT_QUEUE

    def _load(self) -> list[Task]:
        if self.queue_file.is_file():
            try:
                raw = json.loads(self.queue_file.read_text(encoding="utf-8"))
                return [Task.from_dict(t) for t in raw]
            except (json.JSONDecodeError, OSError, TypeError):
                return []
        return []

    def _save(self, tasks: list[Task]) -> None:
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        self.queue_file.write_text(
            json.dumps([t.to_dict() for t in tasks], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(self, prompt: str) -> Task:
        """Append a task; its id is a short zero-padded counter."""
        tasks = self._load()
        task = Task(id=f"t{len(tasks) + 1:03d}", prompt=prompt.strip())
        tasks.append(task)
        self._save(tasks)
        return task

    def list(self, status: str | None = None) -> list[Task]:
        tasks = self._load()
        return [t for t in tasks if status is None or t.status == status]

    def get(self, task_id: str) -> Task | None:
        return next((t for t in self._load() if t.id == task_id), None)

    def clear(self, status: str | None = None) -> int:
        """Remove tasks (all, or only those in ``status``). Returns count removed."""
        tasks = self._load()
        keep = [t for t in tasks if status is not None and t.status != status]
        removed = len(tasks) - len(keep)
        self._save(keep)
        return removed

    def _update(self, task_id: str, **changes) -> None:
        tasks = self._load()
        for t in tasks:
            if t.id == task_id:
                for k, v in changes.items():
                    setattr(t, k, v)
                break
        self._save(tasks)

    def run_next(self, executor: Callable[[str], str]) -> Task | None:
        """
        Run the oldest pending task through ``executor(prompt) -> result`` and
        record the outcome. Returns the finished Task, or None if the queue is
        empty. A raised executor becomes a FAILED task, never a crash.
        """
        pending = self.list(PENDING)
        if not pending:
            return None
        task = pending[0]
        self._update(task.id, status=RUNNING)
        try:
            result = executor(task.prompt)
            self._update(task.id, status=DONE, result=result, finished_at=_now())
        except Exception as exc:  # noqa: BLE001 — record any failure, don't crash the batch
            self._update(task.id, status=FAILED, error=str(exc), finished_at=_now())
        return self.get(task.id)

    def run_all(self, executor: Callable[[str], str]) -> list[Task]:
        """Run every pending task in order; returns the finished tasks."""
        done: list[Task] = []
        while True:
            task = self.run_next(executor)
            if task is None:
                break
            done.append(task)
        return done
