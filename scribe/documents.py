"""
Document store - file-based persistence for the web editor.

Each document is a folder under ``<workspace>/documents/<id>/``:

    documents/<id>/meta.json          — title, type, timestamps, chapter list
    documents/<id>/content.md         — body (type="doc")
    documents/<id>/chapters/<cid>.md  — chapter bodies (type="book")

A "doc" is a single flat markdown body. A "book" is a table of contents
(``chapters`` in meta.json) plus one markdown file per chapter, written and
exported page by page. The layout mirrors SessionManager: visible files in the
workspace, no hidden database.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

META_FILE = "meta.json"
CONTENT_FILE = "content.md"
CHAPTERS_DIR = "chapters"
HISTORY_DIR = "history"

# Sentinels the web editor uses to fence user-locked regions; kept in the saved
# body but stripped from any exported/printed output. Mirror web.LOCK_OPEN/CLOSE.
LOCK_OPEN = "⟦LOCK⟧"
LOCK_CLOSE = "⟦/LOCK⟧"


def _strip_locks(text: str) -> str:
    """Remove lock sentinels, leaving the locked text itself intact."""
    return text.replace(LOCK_OPEN, "").replace(LOCK_CLOSE, "")


def _now() -> str:
    """ISO-ish timestamp, second precision, no timezone noise."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _slugify(text: str) -> str:
    """Short, filesystem-safe slug from a title."""
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:40] or "untitled"


class DocumentStore:
    """Create, list, load, save and export documents and books."""

    def __init__(self, config=None):
        workspace = getattr(config, "workspace_dir", None) if config else None
        base = Path(workspace) if workspace else Path.home() / "scribe-workspace"
        self.root = base.expanduser() / "documents"
        self.root.mkdir(parents=True, exist_ok=True)

    # --- paths ------------------------------------------------------------

    def _dir(self, doc_id: str) -> Path:
        return self.root / doc_id

    def _meta_path(self, doc_id: str) -> Path:
        return self._dir(doc_id) / META_FILE

    def _chapter_path(self, doc_id: str, chapter_id: str) -> Path:
        return self._dir(doc_id) / CHAPTERS_DIR / f"{chapter_id}.md"

    def _read_meta(self, doc_id: str) -> dict[str, Any]:
        return json.loads(self._meta_path(doc_id).read_text(encoding="utf-8"))

    def _write_meta(self, meta: dict[str, Any]) -> None:
        meta["updated"] = _now()
        self._meta_path(meta["id"]).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # --- lifecycle --------------------------------------------------------

    def create(self, title: str, doc_type: str = "doc") -> dict[str, Any]:
        """Create a new document or book and return its meta."""
        title = title.strip() or "Untitled"
        doc_type = "book" if doc_type == "book" else "doc"
        doc_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}"

        doc_dir = self._dir(doc_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        now = _now()
        meta = {
            "id": doc_id,
            "title": title,
            "type": doc_type,
            "created": now,
            "updated": now,
            "chapters": [],
        }
        self._write_meta(meta)
        if doc_type == "book":
            (doc_dir / CHAPTERS_DIR).mkdir(exist_ok=True)
        else:
            (doc_dir / CONTENT_FILE).write_text("", encoding="utf-8")
        return meta

    def exists(self, doc_id: str) -> bool:
        return self._meta_path(doc_id).is_file()

    def list(self) -> list[dict[str, Any]]:
        """All documents, newest first (lightweight meta for the sidebar)."""
        items: list[dict[str, Any]] = []
        for meta_file in self.root.glob(f"*/{META_FILE}"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            items.append({
                "id": meta["id"],
                "title": meta.get("title", "Untitled"),
                "type": meta.get("type", "doc"),
                "updated": meta.get("updated", ""),
            })
        items.sort(key=lambda m: m["updated"], reverse=True)
        return items

    def load(self, doc_id: str) -> dict[str, Any] | None:
        """Full document: meta + body (doc) or chapter bodies (book)."""
        if not self.exists(doc_id):
            return None
        meta = self._read_meta(doc_id)
        if meta.get("type") == "book":
            chapters = []
            for ch in meta.get("chapters", []):
                path = self._chapter_path(doc_id, ch["id"])
                body = path.read_text(encoding="utf-8") if path.is_file() else ""
                chapters.append({"id": ch["id"], "title": ch["title"], "content": body})
            return {**meta, "chapters": chapters}
        content_path = self._dir(doc_id) / CONTENT_FILE
        content = content_path.read_text(encoding="utf-8") if content_path.is_file() else ""
        return {**meta, "content": content}

    # --- writes -----------------------------------------------------------

    def rename(self, doc_id: str, title: str) -> dict[str, Any]:
        meta = self._read_meta(doc_id)
        meta["title"] = title.strip() or meta["title"]
        self._write_meta(meta)
        return meta

    def save_content(self, doc_id: str, content: str) -> None:
        """Save the flat body of a 'doc' (autosave)."""
        (self._dir(doc_id) / CONTENT_FILE).write_text(content, encoding="utf-8")
        self._write_meta(self._read_meta(doc_id))

    def save_chapter(self, doc_id: str, chapter_id: str, content: str) -> None:
        """Save one chapter body of a 'book' (autosave)."""
        path = self._chapter_path(doc_id, chapter_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._write_meta(self._read_meta(doc_id))

    def add_chapter(self, doc_id: str, title: str) -> dict[str, Any]:
        """Append a chapter to a book's table of contents; return the chapter."""
        meta = self._read_meta(doc_id)
        chapter_id = f"ch{len(meta.get('chapters', [])) + 1:02d}-{_slugify(title)}"
        chapter = {"id": chapter_id, "title": title.strip() or "Untitled"}
        meta.setdefault("chapters", []).append(chapter)
        self._chapter_path(doc_id, chapter_id).parent.mkdir(parents=True, exist_ok=True)
        self._chapter_path(doc_id, chapter_id).write_text("", encoding="utf-8")
        self._write_meta(meta)
        return chapter

    def set_toc(self, doc_id: str, titles: list[str]) -> dict[str, Any]:
        """Replace a book's chapter list with these titles (TOC generation).

        Existing chapter bodies are preserved when a title is unchanged at the
        same position; new titles get empty bodies.
        """
        meta = self._read_meta(doc_id)
        old = {c["id"]: c for c in meta.get("chapters", [])}
        new_chapters = []
        for i, title in enumerate(titles, start=1):
            title = title.strip()
            if not title:
                continue
            chapter_id = f"ch{i:02d}-{_slugify(title)}"
            new_chapters.append({"id": chapter_id, "title": title})
            path = self._chapter_path(doc_id, chapter_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                path.write_text("", encoding="utf-8")
            old.pop(chapter_id, None)
        meta["chapters"] = new_chapters
        self._write_meta(meta)
        return meta

    def delete(self, doc_id: str) -> bool:
        """Delete a document folder. Triggered only by an explicit user action."""
        if not self.exists(doc_id):
            return False
        shutil.rmtree(self._dir(doc_id))
        return True

    # --- history / versioning ---------------------------------------------
    # Every iteration is a JSON snapshot under ``documents/<id>/history/``.
    # The payload mirrors ``load()`` (content for a doc, chapter bodies for a
    # book) so a restore is a straight write-back with no guesswork.

    def _history_dir(self, doc_id: str) -> Path:
        return self._dir(doc_id) / HISTORY_DIR

    def snapshot(self, doc_id: str, label: str = "") -> dict[str, Any] | None:
        """Save the current state as a timestamped version; return its stamp."""
        doc = self.load(doc_id)
        if doc is None:
            return None
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        hist_dir = self._history_dir(doc_id)
        hist_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "ts": ts,
            "label": label.strip(),
            "type": doc.get("type", "doc"),
            "title": doc.get("title", "Untitled"),
        }
        if doc.get("type") == "book":
            payload["chapters"] = [
                {"id": c["id"], "title": c["title"], "content": c.get("content", "")}
                for c in doc.get("chapters", [])
            ]
        else:
            payload["content"] = doc.get("content", "")
        # A monotonic suffix keeps two snapshots in the same second distinct.
        path = hist_dir / f"{ts}.json"
        n = 1
        while path.exists():
            path = hist_dir / f"{ts}-{n}.json"
            n += 1
        payload["ts"] = path.stem
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"ts": payload["ts"], "label": payload["label"]}

    def list_history(self, doc_id: str) -> list[dict[str, Any]]:
        """All snapshots, newest first (stamp + label only)."""
        hist_dir = self._history_dir(doc_id)
        if not hist_dir.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for snap in hist_dir.glob("*.json"):
            try:
                data = json.loads(snap.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            items.append({"ts": data.get("ts", snap.stem), "label": data.get("label", "")})
        items.sort(key=lambda m: m["ts"], reverse=True)
        return items

    def get_history(self, doc_id: str, ts: str) -> dict[str, Any] | None:
        """Load one snapshot's full payload for preview."""
        path = self._history_dir(doc_id) / f"{ts}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def restore(self, doc_id: str, ts: str) -> bool:
        """Roll the document back to a snapshot.

        The current state is snapshotted first (label ``before restore``) so the
        rollback itself is reversible.
        """
        snap = self.get_history(doc_id, ts)
        if snap is None or not self.exists(doc_id):
            return False
        self.snapshot(doc_id, label="before restore")
        if snap.get("type") == "book":
            for ch in snap.get("chapters", []):
                self.save_chapter(doc_id, ch["id"], ch.get("content", ""))
        else:
            self.save_content(doc_id, snap.get("content", ""))
        return True

    # --- export -----------------------------------------------------------

    def assemble_markdown(self, doc_id: str) -> str:
        """Single markdown string for MD/PDF export: ``# Title`` then ``## Chapter``.

        Title-as-H1 with chapters as H2 reads naturally as one flat document
        (and gives the print/PDF view a clear hierarchy).
        """
        doc = self.load(doc_id)
        if doc is None:
            return ""
        if doc.get("type") == "book":
            parts = [f"# {doc['title']}\n"]
            for ch in doc.get("chapters", []):
                parts.append(f"\n## {ch['title']}\n\n{_strip_locks(ch['content'])}\n")
            return "\n".join(parts)
        return f"# {doc['title']}\n\n{_strip_locks(doc.get('content', ''))}\n"

    def assemble_epub_markdown(self, doc_id: str) -> str:
        """Markdown for EPUB: each chapter as ``# Heading`` (H1).

        Pandoc splits an EPUB into one section/file per top-level heading, so
        chapters must be H1 to land in their own pages. The book title is NOT
        embedded here — it is passed to pandoc as ``--metadata title`` which
        renders a proper title page.
        """
        doc = self.load(doc_id)
        if doc is None:
            return ""
        if doc.get("type") == "book":
            parts = []
            for ch in doc.get("chapters", []):
                parts.append(f"# {ch['title']}\n\n{_strip_locks(ch['content'])}\n")
            return "\n".join(parts)
        return f"# {doc['title']}\n\n{_strip_locks(doc.get('content', ''))}\n"
