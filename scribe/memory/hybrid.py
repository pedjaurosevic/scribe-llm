"""
Hybrid retrieval — lexical FTS5 + semantic vectors, fused with RRF.

Embeddings find meaning but miss exact identifiers ("RLIMIT_AS", error codes,
function names); full-text search finds exact terms but misses paraphrase.
Reciprocal Rank Fusion combines both rankings without score calibration:

    score(d) = Σ_r 1 / (k + rank_r(d))

The FTS index is a single SQLite file living next to the LanceDB directory,
populated at ingest time and rebuildable from the vector table at any moment
(`RAGService.reindex_fts`).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

RRF_K = 60


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """
    Fuse ranked id lists into one ranking by reciprocal rank.

    Order within each input list is the ranking (best first). Returns
    (id, score) pairs sorted best-first; ids missing from a list simply get no
    contribution from it.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _fts_escape(query: str) -> str:
    """
    Turn free text into a safe FTS5 OR-query: bare terms, quoted, no syntax.
    """
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    return " OR ".join(f'"{t}"' for t in terms[:32])


class FTSIndex:
    """Lexical branch: SQLite FTS5 over chunk content."""

    def __init__(self, db_file: Path | str):
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_file))
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
                "id UNINDEXED, source_file UNINDEXED, content"
                ")"
            )
        return self._conn

    def add(self, rows: list[dict]) -> None:
        """Index chunk rows (needs id, source_file, content keys)."""
        self.conn.executemany(
            "INSERT INTO chunks (id, source_file, content) VALUES (?, ?, ?)",
            [(r["id"], r.get("source_file", ""), r["content"]) for r in rows],
        )
        self.conn.commit()

    def search(self, query: str, limit: int = 10) -> list[str]:
        """Ranked chunk ids (best first) for a free-text query."""
        fts_query = _fts_escape(query)
        if not fts_query:
            return []
        try:
            cur = self.conn.execute(
                "SELECT id FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit),
            )
        except sqlite3.OperationalError:
            return []
        return [row[0] for row in cur.fetchall()]

    def delete_source(self, source_file: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE source_file = ?", (source_file,))
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM chunks")
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
