"""
RAG (Retrieval-Augmented Generation) integration.

Provides semantic search over documents using LanceDB. The index location is
configurable, so it can be shared with another local agent
(`scribe.integrations.rag_path`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer

from scribe.memory.hybrid import FTSIndex, rrf_fuse

logger = logging.getLogger(__name__)

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
        # Lexical branch of hybrid search, one SQLite file next to LanceDB.
        self.fts = FTSIndex(self.db_path / "fts.db")

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

        Robust character-based chunking that guarantees no chunk exceeds chars_per_chunk.
        """
        chars_per_chunk = self.chunk_size * 4
        chunks = []
        paragraphs = text.split("\n\n")

        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # If a single paragraph is too large, split it recursively by single newlines
            if len(para) > chars_per_chunk:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""

                lines = para.split("\n")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if len(current_chunk) + len(line) + 1 <= chars_per_chunk:
                        current_chunk += line + "\n"
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        # If a single line is still too large, split by spaces
                        if len(line) > chars_per_chunk:
                            words = line.split(" ")
                            current_chunk = ""
                            for word in words:
                                if len(current_chunk) + len(word) + 1 <= chars_per_chunk:
                                    current_chunk += word + " "
                                else:
                                    if current_chunk:
                                        chunks.append(current_chunk.strip())
                                    current_chunk = word + " "
                        else:
                            current_chunk = line + "\n"
            elif len(current_chunk) + len(para) + 2 <= chars_per_chunk:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    @staticmethod
    def _document_title(file_path: Path) -> str:
        """Human-readable fallback title from the filename."""
        return file_path.stem.replace("_", " ").replace("-", " ").strip()

    @staticmethod
    def _first_heading(text: str) -> str:
        """Return the first Markdown-style heading in a chunk, if present."""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    return title
        return ""

    def _section_for_chunk(self, file_path: Path, chunk: str) -> str:
        """Best available section label for retrieval and citation context."""
        return self._first_heading(chunk) or self._document_title(file_path)

    @staticmethod
    def _with_chunk_context(content: str, source_name: str, section: str) -> str:
        """Prefix chunk text with lightweight context used by retrieval and grounding."""
        context = [f"Document: {source_name}"]
        if section:
            context.append(f"Section: {section}")
        return "\n".join(context) + "\n\n" + content

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
            section = self._section_for_chunk(file_path, chunk)
            indexed_content = self._with_chunk_context(chunk, file_path.name, section)
            chunk_id = f"{file_path.name}_{i}_{hash(indexed_content) % 100000:05d}"

            try:
                vector = self._embed([indexed_content])[0]
            except Exception:
                vector = [0.0] * EMBEDDING_DIM

            row = {
                "id": chunk_id,
                "content": indexed_content,
                "source_file": str(file_path),
                "chunk_index": i,
                "page": 0,
                "section": section,
                "created_at": datetime.now().isoformat(),
                "metadata": json.dumps({"original_name": file_path.name}),
                "vector": vector,
            }
            rows.append(row)

        if rows:
            self.table.add(rows)
            self.fts.add(rows)

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

        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(file_path)
                text = ""
                for page in reader.pages:
                    text += (page.extract_text() or "") + "\n\n"
                return text
            except Exception as e:
                logger.error(f"Failed to extract text from PDF {file_path.name}: {e}")
                return f"[Failed to extract content from {file_path.name}]"

        elif suffix == ".epub":
            return self._extract_epub(file_path)

        else:
            return f"[Content from {file_path.name}]"

    @staticmethod
    def _extract_epub(file_path: Path) -> str:
        """Extract plain text from an EPUB without extra dependencies.

        An EPUB is a ZIP of XHTML documents. We read the spine order from the
        OPF manifest and strip the markup with a tiny stdlib HTML parser, so no
        third-party EPUB library is needed.
        """
        import zipfile
        from html.parser import HTMLParser
        from xml.etree import ElementTree as ET

        class _TextExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.parts: list[str] = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True
                elif tag in ("p", "br", "div", "h1", "h2", "h3", "li"):
                    self.parts.append("\n")

            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False

            def handle_data(self, data):
                if not self._skip and data.strip():
                    self.parts.append(data)

        try:
            with zipfile.ZipFile(file_path) as zf:
                names = zf.namelist()
                # Find the OPF to read the reading order; fall back to all XHTML.
                opf_name = next((n for n in names if n.endswith(".opf")), None)
                html_files: list[str] = []
                if opf_name:
                    opf = ET.fromstring(zf.read(opf_name))
                    ns = {"opf": "http://www.idpf.org/2007/opf"}
                    base = opf_name.rsplit("/", 1)[0] if "/" in opf_name else ""
                    manifest = {
                        item.get("id"): item.get("href")
                        for item in opf.findall(".//opf:manifest/opf:item", ns)
                    }
                    for ref in opf.findall(".//opf:spine/opf:itemref", ns):
                        href = manifest.get(ref.get("idref"))
                        if href:
                            html_files.append(f"{base}/{href}" if base else href)
                if not html_files:
                    html_files = [
                        n for n in names if n.lower().endswith((".xhtml", ".html", ".htm"))
                    ]

                chunks: list[str] = []
                for name in html_files:
                    if name not in names:
                        continue
                    parser = _TextExtractor()
                    parser.feed(zf.read(name).decode("utf-8", "replace"))
                    chunks.append("".join(parser.parts))
                text = "\n\n".join(chunks)
                return text or f"[No extractable text in {file_path.name}]"
        except Exception as e:
            logger.error(f"Failed to extract text from EPUB {file_path.name}: {e}")
            return f"[Failed to extract content from {file_path.name}]"


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

    def _chunks_by_ids(self, ids: list[str]) -> list[DocumentChunk]:
        """Fetch chunks from the vector table preserving the given id order."""
        if not ids:
            return []
        try:
            df = self.table.to_pandas()
        except Exception:
            return []
        by_id = {row["id"]: row for _, row in df.iterrows()}
        chunks = []
        for chunk_id in ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            chunks.append(
                DocumentChunk(
                    id=row["id"],
                    content=row["content"],
                    source_file=row.get("source_file", ""),
                    chunk_index=row.get("chunk_index", 0),
                    page=row.get("page"),
                    section=row.get("section"),
                    created_at=row["created_at"],
                    metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
                )
            )
        return chunks

    def hybrid_search(self, query: str, limit: int = 5) -> list[DocumentChunk]:
        """
        RRF-fused retrieval: semantic ranking (vectors) + lexical ranking
        (FTS5), each over-fetched, fused by reciprocal rank.

        When the FTS index is empty (an index built before hybrid search
        existed), this degrades to pure semantic search; run reindex_fts()
        once to enable the lexical branch.
        """
        fetch = max(limit * 3, 10)
        semantic_ids = [c.id for c in self.search(query, limit=fetch)]
        lexical_ids = self.fts.search(query, limit=fetch)
        if not lexical_ids:
            return self._chunks_by_ids(semantic_ids[:limit])
        fused = rrf_fuse([semantic_ids, lexical_ids])
        return self._chunks_by_ids([doc_id for doc_id, _ in fused[:limit]])

    def reindex_fts(self) -> int:
        """Rebuild the lexical index from the vector table. Returns row count."""
        try:
            df = self.table.to_pandas()
        except Exception:
            return 0
        self.fts.clear()
        rows = [
            {
                "id": row["id"],
                "source_file": row.get("source_file", ""),
                "content": row["content"],
            }
            for _, row in df.iterrows()
        ]
        if rows:
            self.fts.add(rows)
        return len(rows)

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
        """Delete all chunks from a source file (both branches)."""
        try:
            self.table.delete(f"source_file = '{source_file}'")
            self.fts.delete_source(source_file)
            return True
        except Exception:
            return False


def get_rag_service(config=None) -> RAGService | None:
    """
    Get the RAG service.

    The index location comes from config: `scribe.integrations.rag_path` when
    set (an index shared with another agent), otherwise `scribe.rag.index_dir`
    (Scribe's own, default ~/.scribe/rag).

    Args:
        config: ScribeConfig to read paths from; loaded fresh when None.

    Returns:
        RAGService instance or None
    """
    if config is None:
        from scribe.config import ScribeConfig

        config = ScribeConfig()

    try:
        return RAGService(db_path=config.rag_db_path)
    except Exception:
        logger.warning("[RAG] Could not open index DB", exc_info=True)
        return None
