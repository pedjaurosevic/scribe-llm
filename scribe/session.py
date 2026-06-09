"""
Session Manager - Handles session state, checkpoints, and SME auto-recall.

At session start:
1. Loads last session state
2. Queries SME for previous session summary
3. Presents to user for confirmation

At session end:
1. Saves session summary to SME
2. Creates checkpoint for resumable state
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def session_tag(session_id: str) -> str:
    """Short, stable, shell-safe tag (hashtag) for a session id."""
    return hashlib.sha1(session_id.encode()).hexdigest()[:5]


@dataclass
class SessionCheckpoint:
    """Represents a checkpoint of session state."""

    session_id: str
    created_at: str
    topic: str
    status: str
    messages: list[dict[str, str]] = field(default_factory=list)
    current_language_game: str = "chat"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionCheckpoint:
        return cls(**data)


class SessionManager:
    """
    Manages session state, checkpoints, and memory.

    Handles:
    - Session lifecycle (start/end)
    - Checkpoint saving/loading
    - SME integration for cross-session memory
    - Language game tracking
    """

    STATE_DIR = Path.home() / ".scribe" / "sessions"
    CHECKPOINT_FILE = "checkpoint.json"
    LAST_SESSION_FILE = "last_session.txt"

    def __init__(self, config=None):
        """
        Initialize session manager.

        Args:
            config: ScribeConfig instance
        """
        self.config = config
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)

        self.current_session: SessionCheckpoint | None = None
        self.session_history: list[str] = []

    def start_session(self, topic: str = "new", language_game: str = "chat") -> SessionCheckpoint:
        """
        Start a new session.

        Args:
            topic: Topic or project name
            language_game: Current language game mode

        Returns:
            New session checkpoint
        """
        session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.current_session = SessionCheckpoint(
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            topic=topic,
            status="active",
            current_language_game=language_game,
        )
        return self.current_session

    def end_session(self, status: str = "completed") -> None:
        """
        End the current session.

        Args:
            status: Final status (completed, interrupted, error)
        """
        if self.current_session:
            self.current_session.status = status
            self._save_checkpoint(self.current_session)
            self._update_last_session(self.current_session)
            self._add_to_sme(self.current_session)

    def checkpoint(self) -> None:
        """Persist the current session now (so a crash is still resumable)."""
        if self.current_session:
            self._save_checkpoint(self.current_session)
            self._update_last_session(self.current_session)

    def _save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        """Save checkpoint to disk."""
        path = self.STATE_DIR / checkpoint.session_id / self.CHECKPOINT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(checkpoint.to_dict(), f, indent=2)

    def _update_last_session(self, checkpoint: SessionCheckpoint) -> None:
        """Update the last session reference."""
        path = self.STATE_DIR / self.LAST_SESSION_FILE
        with open(path, "w") as f:
            f.write(checkpoint.session_id)

    def _add_to_sme(self, checkpoint: SessionCheckpoint) -> None:
        """
        Hook for persisting a session summary to SME.

        The TUI and web layers write richer summaries to SME directly (they hold
        the SME service and the message history), so this stays a no-op to avoid
        double-writing. Kept as an extension point for headless callers.
        """
        return None

    def get_last_session(self) -> SessionCheckpoint | None:
        """
        Get the last session checkpoint.

        Returns:
            Last session checkpoint or None
        """
        last_session_path = self.STATE_DIR / self.LAST_SESSION_FILE
        if not last_session_path.exists():
            return None

        with open(last_session_path) as f:
            session_id = f.read().strip()

        checkpoint_path = self.STATE_DIR / session_id / self.CHECKPOINT_FILE
        if not checkpoint_path.exists():
            return None

        with open(checkpoint_path) as f:
            data = json.load(f)
            return SessionCheckpoint.from_dict(data)

    def recall_previous_session(self) -> str:
        """
        Query SME for previous session summary.

        This is the auto-recall at session start.

        Returns:
            Human-readable summary of previous session
        """
        last_session = self.get_last_session()
        if not last_session:
            return "No previous session found."

        return (
            f"Previous session: {last_session.topic}\n"
            f"Status: {last_session.status}\n"
            f"Language game: {last_session.current_language_game}\n"
            f"Date: {last_session.created_at}"
        )

    def list_sessions(self) -> list[str]:
        """
        List all session IDs.

        Returns:
            List of session IDs sorted by most recent
        """
        if not self.STATE_DIR.exists():
            return []

        sessions = []
        for item in self.STATE_DIR.iterdir():
            if item.is_dir() and (item / self.CHECKPOINT_FILE).exists():
                sessions.append(item.name)

        return sorted(sessions, reverse=True)

    def load_session(self, session_id: str) -> SessionCheckpoint | None:
        """
        Load a specific session by ID.

        Args:
            session_id: Session ID to load

        Returns:
            Session checkpoint or None
        """
        path = self.STATE_DIR / session_id / self.CHECKPOINT_FILE
        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)
            return SessionCheckpoint.from_dict(data)

    def find_by_tag(self, tag: str) -> str | None:
        """
        Resolve a session by its tag (with or without a leading '#'), or by a
        full/partial session id. Returns the session id or None.
        """
        tag = tag.lstrip("#").strip().lower()
        if not tag:
            return None
        for sid in self.list_sessions():
            if session_tag(sid) == tag or sid == tag or sid.endswith(tag):
                return sid
        return None

    def update_status(self, status: str) -> None:
        """
        Update current session status.

        Args:
            status: New status string
        """
        if self.current_session:
            self.current_session.status = status

    def add_message(self, role: str, content: str) -> None:
        """
        Add a message to the current session.

        Args:
            role: Message role (user/assistant/system)
            content: Message content
        """
        if self.current_session:
            self.current_session.messages.append({"role": role, "content": content})

    def get_recent_messages(self, count: int = 10) -> list[dict[str, str]]:
        """
        Get the most recent messages from current session.

        Args:
            count: Number of messages to retrieve

        Returns:
            List of message dicts
        """
        if not self.current_session:
            return []

        messages = self.current_session.messages
        return messages[-count:] if len(messages) > count else messages
