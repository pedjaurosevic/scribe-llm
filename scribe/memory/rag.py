"""
RAG (Retrieval-Augmented Generation) integration.

Provides semantic search over documents using LanceDB.
Integrates with existing Kon RAG system or creates new Scribe RAG.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer


DEFAULT_RAG_PATH = Path.home() / ".scribe" / "rag"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
TABLE_NAME = "documents"
CHUNK_SIZE = 512
EMBEDDING_DIM = 384


@dataclass
class DocumentChunk:
    """A chunk of a document."""

    id: str
    content: str
    source_file: str
    chunk_index: int
    page: int | None
    section: str | None
    created_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentChunk:
        return cls(**data)


class RAGService:
    """
    RAG service using LanceDB for semantic document search.

    Supports:
    - Adding documents (PDF, TXT, MD, etc.)
    - Chunking documents
    - Semantic search over chunks
    - Citation tracking
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        embedding_model: str = EMBEDDING_MODEL,
        chunk_size: int = CHUNK_SIZE,
    ):
        """
        Initialize RAG service.

        Args:
            db_path: Path to LanceDB database
            embedding_model: SentenceTransformer model name
            chunk_size: Chunk size in tokens (approximate)
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_RAG_PATH
        self.db_path.mkdir(parents=True, exist_ok=True)

        self.embedding_model = embedding_model
        self.chunk_size = chunk_size
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
        """Get or create document chunks table."""
        if self._table is None:
            self._table = self._get_or_create_table()
        return self._table

    def _get_or_create_table(self) -> Any:
        """Get or create the documents table."""
        try:
            return self.db.open_table(TABLE_NAME)
        except Exception:
            pass

        schema = pa.schema([
            ("id", pa.string()),
            ("content", pa.string()),
            ("source_file", pa.string()),
            ("chunk_index", pa.int32()),
            ("page", pa.int32()),
            ("section", pa.string()),
            ("created_at", pa.string()),
            ("metadata", pa.string()),
            ("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
        ])

        return self.db.create_table(TABLE_NAME, schema=schema)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""
        embeddings = self.model.encode(texts)
        return embeddings.tolist()

    def _chunk_text(self, text: str) -> list[str]:
        """
        Split text into chunks.

        Simple character-based chunking.
        """
        chars_per_chunk = self.chunk_size * 4
        chunks = []
        paragraphs = text.split("\n\n")

        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 <= chars_per_chunk:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def ingest_file(self, file_path: str | Path) -> int:
        """
        Ingest a document file.

        Args:
            file_path: Path to document

        Returns:
            Number of chunks added
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = self._extract_content(file_path)
        chunks = self._chunk_text(content)

        rows = []
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_path.name}_{i}_{hash(chunk) % 100000:05d}"

            try:
                vector = self._embed([chunk])[0]
            except Exception:
                vector = [0.0] * EMBEDDING_DIM

            row = {
                "id": chunk_id,
                "content": chunk,
                "source_file": str(file_path),
                "chunk_index": i,
                "page": 0,
                "section": "",
                "created_at": datetime.now().isoformat(),
                "metadata": json.dumps({"original_name": file_path.name}),
                "vector": vector,
            }
            rows.append(row)

        if rows:
            self.table.add(rows)

        return len(chunks)

    def _extract_content(self, file_path: Path) -> str:
        """Extract text content from a file."""
        suffix = file_path.suffix.lower()

        if suffix == ".txt":
            return file_path.read_text(encoding="utf-8")

        elif suffix == ".md":
            return file_path.read_text(encoding="utf-8")

        elif suffix == ".json":
            data = json.loads(file_path.read_text())
            return json.dumps(data, indent=2)

        else:
            return f"[Content from {file_path.name}]"

    def search(
        self,
        query: str,
        limit: int = 5,
        source_filter: str | None = None,
    ) -> list[DocumentChunk]:
        """
        Search documents semantically.

        Args:
            query: Search query
            limit: Max results
            source_filter: Optional source file filter

        Returns:
            List of matching document chunks
        """
        try:
            query_vector = self._embed([query])[0]

            results = (
                self.table.search(query_vector, vector_column_name="vector")
                .limit(limit)
                .to_pandas()
            )

            chunks = []
            for _, row in results.iterrows():
                if source_filter and row.get("source_file") != source_filter:
                    continue

                chunk = DocumentChunk(
                    id=row["id"],
                    content=row["content"],
                    source_file=row.get("source_file", ""),
                    chunk_index=row.get("chunk_index", 0),
                    page=row.get("page"),
                    section=row.get("section"),
                    created_at=row["created_at"],
                    metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
                )
                chunks.append(chunk)

            return chunks

        except Exception as e:
            print(f"[RAG] Search error: {e}")
            return []

    def list_sources(self) -> list[dict[str, Any]]:
        """
        List all indexed sources.

        Returns:
            List of dicts with source_file and chunk_count
        """
        try:
            df = self.table.to_pandas()
            if "source_file" not in df.columns:
                return []

            counts = df.groupby("source_file").size().reset_index(name="chunk_count")
            return counts.to_dict("records")

        except Exception:
            return []

    def count(self) -> int:
        """Get total number of chunks."""
        try:
            return self.table.count_rows()
        except Exception:
            return 0

    def delete_source(self, source_file: str) -> bool:
        """Delete all chunks from a source file."""
        try:
            self.table.delete(f"source_file = '{source_file}'")
            return True
        except Exception:
            return False


def get_rag_service() -> RAGService | None:
    """
    Get the RAG service.

    Tries to use existing Kon RAG or creates new Scribe RAG.

    Returns:
        RAGService instance or None
    """
    kon_rag_path = Path.home() / ".kon" / "library" / ".rag"

    if kon_rag_path.exists():
        try:
            service = RAGService(db_path=kon_rag_path)
            if service.count() >= 0:
                return service
        except Exception:
            pass

    scribe_rag_path = Path.home() / ".scribe" / "rag"
    try:
        service = RAGService(db_path=scribe_rag_path)
        return service
    except Exception:
        return None
