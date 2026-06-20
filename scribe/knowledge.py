"""
Curated OKF knowledge bases — mount, browse, search and ground over them.

A knowledge base is an Open Knowledge Format bundle (the same shape Scribe's
own ``wiki distill`` produces): a directory of ``*.md`` pages with optional
YAML frontmatter, an ``index.md`` and inter-page markdown links. This module
lets a user *mount* such bundles by name and gives the agent three moves over
them — **search** (find relevant pages/passages), **navigate** (follow the OKF
link graph) and **ground** (answer strictly from the pages with `[n]` citations,
reusing ``prompts.grounded_context``).

The registry is a small JSON file (``~/.scribe/knowledge.json`` by default);
the retrieval core is pure and file-based, so it is fully testable offline with
a fixture bundle — no model and no vector store required.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from scribe.wiki import _page_meta, parse_frontmatter

DEFAULT_REGISTRY = Path.home() / ".scribe" / "knowledge.json"

# Reserved OKF filenames that are structure, not knowledge content.
_RESERVED = {"index.md", "log.md"}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


@dataclass
class KBChunk:
    """A retrieved passage, shaped for ``prompts.grounded_context`` (.content /
    .source_file / .section) so KB answers cite sources like the rest of Scribe."""

    content: str
    source_file: str
    section: str = ""
    score: float = 0.0


def _split_blocks(body: str) -> list[tuple[str, str]]:
    """
    Split a page body into (section_heading, block) pairs. Blocks are
    blank-line-separated paragraphs; the section is the nearest heading above.
    """
    blocks: list[tuple[str, str]] = []
    section = ""
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            blocks.append((section, text))
        buf.clear()

    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            flush()
            section = s.lstrip("#").strip()
        elif not s:
            flush()
        else:
            buf.append(line)
    flush()
    return blocks


def _overlap(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & _tokenize(text)) / len(query_tokens)


class KnowledgeBase:
    """One mounted OKF bundle directory."""

    def __init__(self, name: str, path: Path | str):
        self.name = name
        self.path = Path(path).expanduser()

    @property
    def pages_dir(self) -> Path:
        """Pages live under ``pages/`` when present, else the bundle root."""
        sub = self.path / "pages"
        return sub if sub.is_dir() else self.path

    def pages(self) -> list[Path]:
        """All knowledge pages (``*.md``), excluding reserved OKF files."""
        if not self.pages_dir.is_dir():
            return []
        return sorted(
            p for p in self.pages_dir.glob("*.md") if p.name.lower() not in _RESERVED
        )

    def page_count(self) -> int:
        return len(self.pages())

    def titles(self) -> list[tuple[str, str]]:
        """(filename, title) for every page — a cheap table of contents."""
        return [(p.name, _page_meta(p)[0]) for p in self.pages()]

    def search(self, query: str, limit: int = 5) -> list[tuple[Path, float]]:
        """Rank pages by lexical overlap of the query with title + body."""
        q = _tokenize(query)
        scored: list[tuple[Path, float]] = []
        for page in self.pages():
            try:
                text = page.read_text(encoding="utf-8")
            except OSError:
                continue
            _, body = parse_frontmatter(text)
            title = _page_meta(page)[0]
            score = _overlap(q, title) * 2.0 + _overlap(q, body)
            if score > 0:
                scored.append((page, score))
        scored.sort(key=lambda ps: (-ps[1], ps[0].name))
        return scored[:limit]

    def chunks_for(self, query: str, limit: int = 5) -> list[KBChunk]:
        """
        Top passages across the whole base for grounded answering. Scores
        blocks (paragraphs) individually so citations point at the precise
        passage, not the whole page.
        """
        q = _tokenize(query)
        chunks: list[KBChunk] = []
        for page in self.pages():
            try:
                text = page.read_text(encoding="utf-8")
            except OSError:
                continue
            _, body = parse_frontmatter(text)
            for section, block in _split_blocks(body):
                score = _overlap(q, block) + _overlap(q, section) * 0.5
                if score > 0:
                    chunks.append(
                        KBChunk(content=block, source_file=page.name, section=section, score=score)
                    )
        chunks.sort(key=lambda c: (-c.score, c.source_file))
        return chunks[:limit]

    def links(self, page_name: str) -> list[tuple[str, str]]:
        """Outgoing markdown links ``[text](target)`` from a page — the OKF graph."""
        page = self.pages_dir / page_name
        if not page.is_file():
            return []
        try:
            text = page.read_text(encoding="utf-8")
        except OSError:
            return []
        return re.findall(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)", text)


class KnowledgeRegistry:
    """A name → bundle-path registry, persisted as JSON."""

    def __init__(self, registry_file: Path | str | None = None):
        self.registry_file = Path(registry_file) if registry_file else DEFAULT_REGISTRY

    def _load(self) -> dict[str, str]:
        if self.registry_file.is_file():
            try:
                return json.loads(self.registry_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self, data: dict[str, str]) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list(self) -> list[KnowledgeBase]:
        return [KnowledgeBase(name, path) for name, path in sorted(self._load().items())]

    def get(self, name: str) -> KnowledgeBase | None:
        path = self._load().get(name)
        return KnowledgeBase(name, path) if path else None

    def add(self, name: str, path: Path | str) -> KnowledgeBase:
        """Mount a bundle. Raises ValueError if it has no OKF pages."""
        kb = KnowledgeBase(name, path)
        if not kb.path.is_dir():
            raise ValueError(f"not a directory: {kb.path}")
        if kb.page_count() == 0:
            raise ValueError(f"no OKF pages found under {kb.path} (expected *.md)")
        data = self._load()
        data[name] = str(kb.path)
        self._save(data)
        return kb

    def remove(self, name: str) -> bool:
        data = self._load()
        if name in data:
            del data[name]
            self._save(data)
            return True
        return False
