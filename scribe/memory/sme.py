"""
SME (Semantic Memory Engine) - LanceDB-backed cross-session memory.

Provides persistent semantic memory using LanceDB embeddings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer

DEFAULT_SME_PATH = Path.home() / ".scribe" / "sme"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
TABLE_NAME = "memories"
EMBEDDING_DIM = 384


@dataclass
class MemoryEntry:
    """A semantic memory entry."""

    id: str
    content: str
    session_id: str | None
    topic: str | None
    created_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        return cls(**data)


class SMEService:
    """
    Semantic Memory Engine using LanceDB.

    Stores semantic embeddings of session summaries and key facts
    for cross-session recall.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        embedding_model: str = EMBEDDING_MODEL,
    ):
        """
        Initialize SME service.

        Args:
            db_path: Path to LanceDB database. Defaults to ~/.scribe/sme
            embedding_model: SentenceTransformer model name
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_SME_PATH
        self.db_path.mkdir(parents=True, exist_ok=True)

        self.embedding_model = embedding_model
        self._model: SentenceTransformer | None = None
        self._db: lancedb.LanceDB | None = None
        self._table: Any | None = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy-load embedding model."""
        if self._model is None:
            self._model = SentenceTransformer(self.embedding_model)
        return self._model

    @property
    def db(self) -> lancedb.LanceDB:
        """Get or create database connection."""
        if self._db is None:
            self._db = lancedb.connect(str(self.db_path))
        return self._db

    @property
    def table(self) -> Any:
        """Get or create memory table."""
        if self._table is None:
            self._table = self._get_or_create_table()
        return self._table

    def _get_or_create_table(self) -> Any:
        """Get or create the memories table."""
        try:
            return self.db.open_table(TABLE_NAME)
        except Exception:
            pass

        schema = pa.schema([
            ("id", pa.string()),
            ("content", pa.string()),
            ("session_id", pa.string()),
            ("topic", pa.string()),
            ("created_at", pa.string()),
            ("metadata", pa.string()),
            ("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
        ])

        return self.db.create_table(TABLE_NAME, schema=schema)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""
        embeddings = self.model.encode(texts)
        return embeddings.tolist()

    def add(
        self,
        content: str,
        session_id: str | None = None,
        topic: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a memory entry.

        Args:
            content: Text content to remember
            session_id: Associated session ID
            topic: Topic or theme
            metadata: Additional metadata

        Returns:
            Entry ID
        """
        entry_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(content) % 100000:05d}"

        try:
            vector = self._embed([content])[0]
        except Exception as e:
            print(f"[SME] Embedding error: {e}")
            vector = [0.0] * EMBEDDING_DIM

        row = {
            "id": entry_id,
            "content": content,
            "session_id": session_id or "",
            "topic": topic or "",
            "created_at": datetime.now().isoformat(),
            "metadata": json.dumps(metadata or {}),
            "vector": vector,
        }

        self.table.add([row])
        return entry_id

    def search(
        self,
        query: str,
        limit: int = 5,
        topic: str | None = None,
    ) -> list[MemoryEntry]:
        """
        Search semantic memory.

        Args:
            query: Search query text
            limit: Max results
            topic: Optional topic filter

        Returns:
            List of matching memory entries
        """
        try:
            query_vector = self._embed([query])[0]

            results = (
                self.table.search(query_vector, vector_column_name="vector")
                .limit(limit)
                .to_pandas()
            )

            entries = []
            for _, row in results.iterrows():
                if topic and row.get("topic") != topic:
                    continue

                entry = MemoryEntry(
                    id=row["id"],
                    content=row["content"],
                    session_id=row.get("session_id") or None,
                    topic=row.get("topic") or None,
                    created_at=row["created_at"],
                    metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
                )
                entries.append(entry)

            return entries

        except Exception as e:
            print(f"[SME] Search error: {e}")
            return self._search_by_text(query, limit, topic)

    def _search_by_text(
        self,
        query: str,
        limit: int,
        topic: str | None = None,
    ) -> list[MemoryEntry]:
        """Fallback text search when embeddings unavailable."""
        try:
            results = self.table.search(query).limit(limit).to_pandas()

            entries = []
            for _, row in results.iterrows():
                if topic and row.get("topic") != topic:
                    continue

                entry = MemoryEntry(
                    id=row["id"],
                    content=row["content"],
                    session_id=row.get("session_id") or None,
                    topic=row.get("topic") or None,
                    created_at=row["created_at"],
                    metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
                )
                entries.append(entry)

            return entries

        except Exception:
            return []

    def get_recent(self, limit: int = 10) -> list[MemoryEntry]:
        """
        Get recent memory entries.

        Args:
            limit: Max entries to return

        Returns:
            List of recent entries
        """
        try:
            df = self.table.to_pandas()
            df = df.sort_values("created_at", ascending=False).head(limit)

            return [
                MemoryEntry(
                    id=row["id"],
                    content=row["content"],
                    session_id=row.get("session_id") or None,
                    topic=row.get("topic") or None,
                    created_at=row["created_at"],
                    metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
                )
                for _, row in df.iterrows()
            ]

        except Exception:
            return []

    def delete(self, entry_id: str) -> bool:
        """
        Delete a memory entry.

        Args:
            entry_id: ID of entry to delete

        Returns:
            True if deleted
        """
        try:
            self.table.delete(f"id = '{entry_id}'")
            return True
        except Exception:
            return False

    def count(self) -> int:
        """Get total number of memory entries."""
        try:
            return self.table.count_rows()
        except Exception:
            return 0


def get_sme_service() -> SMEService | None:
    """
    Get the SME service, preferring existing Kon SME if available.

    Returns:
        SMEService instance or None if no storage available
    """
    kon_sme_path = Path.home() / ".kon" / "sme"

    if kon_sme_path.exists():
        try:
            service = SMEService(db_path=kon_sme_path)
            if service.count() >= 0:
                return service
        except Exception:
            pass

    scribe_sme_path = Path.home() / ".scribe" / "sme"
    try:
        service = SMEService(db_path=scribe_sme_path)
        return service
    except Exception:
        return None


def recall_previous_session(sme: SMEService | None = None) -> str:
    """
    Recall the previous session summary.

    Args:
        sme: SME service instance

    Returns:
        Human-readable session summary
    """
    if sme is None:
        sme = get_sme_service()

    if sme is None:
        return "No previous session found."

    try:
        recent = sme.get_recent(limit=3)

        if not recent:
            return "No previous session found."

        for entry in recent:
            if entry.topic and entry.topic != "new_chat":
                return (
                    f"Topic: {entry.topic}\n"
                    f"Summary: {entry.content}\n"
                    f"Session: {entry.session_id}\n"
                    f"Date: {entry.created_at}"
                )

        latest = recent[0]
        return (
            f"Topic: {latest.topic or 'general'}\n"
            f"Summary: {latest.content}\n"
            f"Session: {latest.session_id}\n"
            f"Date: {latest.created_at}"
        )

    except Exception as e:
        return f"Could not recall: {e}"
