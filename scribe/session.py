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
import shutil
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

    # Sessions used to live in the hidden ~/.scribe/sessions; they are now in
    # the visible workspace. Anything found here is migrated over on startup.
    LEGACY_STATE_DIR = Path.home() / ".scribe" / "sessions"
    CHECKPOINT_FILE = "checkpoint.json"
    LAST_SESSION_FILE = "last_session.txt"

    def __init__(self, config=None):
        """
        Initialize session manager.

        Args:
            config: ScribeConfig instance
        """
        self.config = config
        # Everything session-related lives in ONE visible workspace folder:
        #   sessions/<id>.md              — human-readable transcript
        #   sessions/<id>/checkpoint.json — resumable machine state
        #   sessions/last_session.txt     — pointer to the latest session
        self.sessions_dir = self._resolve_sessions_dir(config)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir = self.sessions_dir
        self._migrate_legacy_state()

        self.current_session: SessionCheckpoint | None = None
        self.session_history: list[str] = []

    @staticmethod
    def _resolve_sessions_dir(config) -> Path:
        """Sessions live in the workspace (visible), not in hidden ~/.scribe."""
        workspace = getattr(config, "workspace_dir", None) if config else None
        base = Path(workspace) if workspace else Path.home() / "scribe-workspace"
        return base.expanduser() / "sessions"

    def _migrate_legacy_state(self) -> None:
        """
        One-time move of checkpoints from the old hidden location into the
        workspace. Entries that already exist at the destination are left
        alone; the old (then empty) folder is not deleted.
        """
        legacy = self.LEGACY_STATE_DIR
        if not legacy.is_dir() or legacy.resolve() == self.sessions_dir.resolve():
            return
        for item in legacy.iterdir():
            target = self.sessions_dir / item.name
            if target.exists():
                continue
            try:
                shutil.move(str(item), str(target))
            except OSError:
                pass

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
        path = self.sessions_dir / checkpoint.session_id / self.CHECKPOINT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(checkpoint.to_dict(), f, indent=2)
        self._write_transcript(checkpoint)

    ROLE_HEADINGS = {"user": "👤 User", "assistant": "✍️ Scribe", "tool": "🔧 Tool"}

    def transcript_path(self, session_id: str) -> Path:
        return self.transcripts_dir / f"{session_id}.md"

    def _write_transcript(self, checkpoint: SessionCheckpoint) -> None:
        """
        Mirror the full session as a Markdown file in the workspace.

        Rewritten on every checkpoint, so the transcript is always complete and
        current — grep-able, RAG-ingestable, and readable in any editor.
        """
        lines = [
            "---",
            f"session: {checkpoint.session_id}",
            f"tag: {session_tag(checkpoint.session_id)}",
            f"topic: {checkpoint.topic}",
            f"status: {checkpoint.status}",
            f"created: {checkpoint.created_at}",
            f"updated: {datetime.now().isoformat()}",
            f"mode: {checkpoint.current_language_game}",
            "---",
            "",
            f"# Session {checkpoint.session_id} — {checkpoint.topic}",
            "",
        ]
        for msg in checkpoint.messages:
            role = msg.get("role", "")
            if role == "system":
                continue
            heading = self.ROLE_HEADINGS.get(role, role.capitalize())
            lines += [f"## {heading}", "", msg.get("content", ""), ""]
        self.transcript_path(checkpoint.session_id).write_text(
            "\n".join(lines), encoding="utf-8"
        )

    def search_transcripts(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Case-insensitive full-text search over all Markdown transcripts.

        Returns dicts with session_id, path, line number and the matching line,
        newest sessions first.
        """
        needle = query.lower()
        hits: list[dict[str, Any]] = []
        if not needle or not self.transcripts_dir.exists():
            return hits
        for path in sorted(self.transcripts_dir.glob("*.md"), reverse=True):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if needle in line.lower():
                    hits.append(
                        {
                            "session_id": path.stem,
                            "path": str(path),
                            "line": lineno,
                            "text": line.strip(),
                        }
                    )
                    if len(hits) >= limit:
                        return hits
        return hits

    def _update_last_session(self, checkpoint: SessionCheckpoint) -> None:
        """Update the last session reference."""
        path = self.sessions_dir / self.LAST_SESSION_FILE
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
        last_session_path = self.sessions_dir / self.LAST_SESSION_FILE
        if not last_session_path.exists():
            return None

        with open(last_session_path) as f:
            session_id = f.read().strip()

        checkpoint_path = self.sessions_dir / session_id / self.CHECKPOINT_FILE
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
        if not self.sessions_dir.exists():
            return []

        sessions = []
        for item in self.sessions_dir.iterdir():
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
        path = self.sessions_dir / session_id / self.CHECKPOINT_FILE
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
