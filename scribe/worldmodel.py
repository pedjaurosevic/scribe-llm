"""
WorldModel — the agent's persistent sense of who and where it is (from Konok).

A small typed record (identity / environment / knowledge / drives) that is
ALWAYS rendered into the system prompt. The lesson behind "always" is the Kon
E2B identity bug: when a fallback path skipped the persona, the agent "forgot
who it was". Here there is no persona-less path — `render()` is pure and a
missing file yields the seed defaults, never an empty block.

Stored as JSON at ~/.scribe/worldmodel.json (or a vault-local path). Cheap to
read, hand-editable, and versioned by a single `revision` counter so two
machines can tell which copy is newer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path.home() / ".scribe" / "worldmodel.json"


@dataclass
class WorldModel:
    """The four facets injected into every system prompt."""

    identity: str = (
        "You are Scribe, a local-first research, writing and coding agent "
        "running on the user's own machine."
    )
    environment: dict = field(default_factory=dict)   # host, workspace, server, model
    knowledge: list[str] = field(default_factory=list)  # durable facts about the user/project
    drives: list[str] = field(
        default_factory=lambda: [
            "Ground every claim in a source or say you cannot.",
            "Prefer the simplest solution that works.",
            "Keep answers short and in the user's language.",
        ]
    )
    revision: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> WorldModel:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)

    def render(self) -> str:
        """
        The system-prompt block. Always non-empty — the identity line alone is
        a valid persona, so there is no path that drops the agent's self.
        """
        lines = ["## Who and where you are", "", self.identity, ""]
        if self.environment:
            lines.append("Environment:")
            for key in ("host", "workspace", "server", "model"):
                if self.environment.get(key):
                    lines.append(f"- {key}: {self.environment[key]}")
            lines.append("")
        if self.knowledge:
            lines.append("What you know about the user and project:")
            lines += [f"- {item}" for item in self.knowledge]
            lines.append("")
        if self.drives:
            lines.append("What you value (in order):")
            lines += [f"- {item}" for item in self.drives]
        return "\n".join(lines).rstrip()


def load_worldmodel(path: Path | str | None = None) -> WorldModel:
    """Load the WorldModel, returning seed defaults when no file exists or it
    is unreadable — never an empty persona."""
    target = Path(path) if path else DEFAULT_PATH
    if target.exists():
        try:
            return WorldModel.from_dict(json.loads(target.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    return WorldModel()


def save_worldmodel(wm: WorldModel, path: Path | str | None = None) -> Path:
    """Persist the WorldModel, bumping its revision and timestamp."""
    target = Path(path) if path else DEFAULT_PATH
    wm.revision += 1
    wm.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(wm.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def remember(fact: str, path: Path | str | None = None) -> WorldModel:
    """Append a durable fact to the WorldModel's knowledge (deduped)."""
    wm = load_worldmodel(path)
    fact = fact.strip()
    if fact and fact not in wm.knowledge:
        wm.knowledge.append(fact)
        save_worldmodel(wm, path)
    return wm
