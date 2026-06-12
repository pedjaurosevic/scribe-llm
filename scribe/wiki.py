"""
Wiki distiller — batch-process saved sessions into durable WIKI knowledge.

Reads session checkpoints from the workspace (`sessions/<id>/checkpoint.json`),
runs each one through a headless model turn with file tools sandboxed to the
WIKI folder, and records what was processed in a ledger (`WIKI/.distilled.json`)
keyed by a content digest — so a session is re-distilled only when it changed.

The model curates, it does not transcribe: it extracts decisions, conclusions,
facts and open questions into per-topic pages and keeps `index.md` current,
following the wiki-memory skill's rules. Sessions with nothing durable are
marked processed and skipped forever.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from scribe.session import SessionCheckpoint, SessionManager, session_tag

logger = logging.getLogger(__name__)

LEDGER_FILE = ".distilled.json"
RAG_SYNC_FILE = ".rag-sync.json"
INDEX_FILE = "index.md"
PAGES_DIR = "pages"

# Cap how much of a session is shown to the model.
MAX_SESSION_CHARS = 16_000

INDEX_SKELETON = """# WIKI Index

Kurirano znanje destilovano iz sesija (`scribe wiki distill`).

## Pages
"""

DISTILL_SYSTEM = """You are Scribe's wiki distiller, a careful knowledge curator.

You are given the transcript of ONE past session. Your job is to preserve only
its DURABLE knowledge in the local wiki, then stop.

What counts as durable: decisions made, conclusions reached, verified facts,
architecture/design notes, important preferences, open questions. What does
NOT: greetings, chit-chat, transient errors, anything trivially re-derivable.

Your file tools operate INSIDE the wiki folder:
- pages/<topic>.md  — one page per topic, kebab-case file names
- index.md          — the table of contents

How to work:
1. Read the transcript and decide if it contains anything durable.
   If it does NOT, reply with exactly: SKIP
2. Otherwise, for each topic: read_file the existing page first if it may
   exist, MERGE new knowledge into it (never erase existing content), or
   create a new page. Keep pages short and factual. Start every page with a
   `# Title` heading. Mark each new entry with the source session:
   `(sesija <id>, tag <tag>)`.
3. index.md is maintained automatically — never edit it yourself.
4. Write pages in the language the session was held in.

Finally, answer with ONE short sentence describing what you stored (or SKIP).
"""

DISTILL_TASK = """Session to distill:
- id: {session_id}
- tag: {tag}
- topic: {topic}
- date: {created_at}

Transcript follows between the markers.

===== TRANSCRIPT START =====
{transcript}
===== TRANSCRIPT END =====
"""


def wiki_dir(config) -> Path:
    """The WIKI folder inside the workspace, scaffolded if missing."""
    wiki = Path(config.workspace_dir).expanduser() / "WIKI"
    (wiki / PAGES_DIR).mkdir(parents=True, exist_ok=True)
    index = wiki / INDEX_FILE
    if not index.exists():
        index.write_text(INDEX_SKELETON, encoding="utf-8")
    return wiki


def load_ledger(wiki: Path) -> dict[str, str]:
    """Map of session_id -> content digest already distilled."""
    path = wiki / LEDGER_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_ledger(wiki: Path, ledger: dict[str, str]) -> None:
    (wiki / LEDGER_FILE).write_text(
        json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8"
    )


def _page_title_and_hook(page: Path) -> tuple[str, str]:
    """Title = first `#` heading (or the file stem); hook = first prose line."""
    title, hook = page.stem.replace("-", " ").replace("_", " "), ""
    try:
        lines = page.read_text(encoding="utf-8").splitlines()
    except OSError:
        return title, hook
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if title == page.stem.replace("-", " ").replace("_", " "):
                title = stripped.lstrip("#").strip() or title
            continue
        hook = stripped.lstrip("*- ").replace("**", "").strip()
        break
    if len(hook) > 80:
        hook = hook[:77] + "..."
    return title, hook


def rebuild_index(wiki: Path) -> None:
    """
    Regenerate index.md from pages/*.md.

    The index is built programmatically (not by the model) so it can never be
    clobbered or drift out of sync with the actual pages.
    """
    lines = [
        "# WIKI Index",
        "",
        "Kurirano znanje destilovano iz sesija (`scribe wiki distill`).",
        "",
        "## Pages",
        "",
    ]
    for page in sorted((wiki / PAGES_DIR).glob("*.md")):
        title, hook = _page_title_and_hook(page)
        entry = f"- [{title}]({PAGES_DIR}/{page.name})"
        lines.append(f"{entry} — {hook}" if hook else entry)
    (wiki / INDEX_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _page_digests(wiki: Path) -> dict[str, str]:
    """sha256 per wiki page, keyed by file name."""
    digests: dict[str, str] = {}
    for page in sorted((wiki / PAGES_DIR).glob("*.md")):
        try:
            digests[page.name] = hashlib.sha256(page.read_bytes()).hexdigest()
        except OSError:
            continue
    return digests


def sync_rag(wiki: Path, rag) -> list[str]:
    """
    (Re-)ingest wiki pages into RAG — only the ones new or changed since the
    last sync (tracked in `.rag-sync.json`). Returns the synced page names.
    """
    sync_path = wiki / RAG_SYNC_FILE
    try:
        synced = json.loads(sync_path.read_text(encoding="utf-8"))
        if not isinstance(synced, dict):
            synced = {}
    except (OSError, json.JSONDecodeError):
        synced = {}

    ingested: list[str] = []
    for name, digest in _page_digests(wiki).items():
        if synced.get(name) == digest:
            continue
        page = wiki / PAGES_DIR / name
        try:
            rag.delete_source(str(page))
            rag.ingest_file(page)
        except Exception:
            logger.warning("[wiki] RAG ingest failed for %s", name, exc_info=True)
            continue
        synced[name] = digest
        ingested.append(name)

    if ingested:
        sync_path.write_text(
            json.dumps(synced, indent=2, sort_keys=True), encoding="utf-8"
        )
    return ingested


def _visible_messages(checkpoint: SessionCheckpoint) -> list[dict[str, str]]:
    return [m for m in checkpoint.messages if m.get("role") != "system"]


def session_digest(checkpoint: SessionCheckpoint) -> str:
    """Stable digest of the distill-relevant content of a session."""
    payload = json.dumps(_visible_messages(checkpoint), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_session(checkpoint: SessionCheckpoint) -> str:
    """The transcript text shown to the model (system messages excluded)."""
    lines: list[str] = []
    for msg in _visible_messages(checkpoint):
        role = msg.get("role", "").capitalize()
        lines += [f"## {role}", "", msg.get("content", ""), ""]
    text = "\n".join(lines).strip()
    if len(text) > MAX_SESSION_CHARS:
        text = text[:MAX_SESSION_CHARS] + "\n... [truncated]"
    return text


def pending_sessions(
    manager: SessionManager,
    ledger: dict[str, str],
    since: str | None = None,
) -> list[tuple[str, SessionCheckpoint]]:
    """
    Sessions that still need distilling, oldest first.

    A session is pending when it has visible content and its digest is not in
    the ledger (so an edited/resumed session is re-distilled). `since` keeps
    only sessions on/after a YYYYMMDD date.
    """
    pending: list[tuple[str, SessionCheckpoint]] = []
    for session_id in sorted(manager.list_sessions()):
        if since and session_id[:8] < since[:8]:
            continue
        checkpoint = manager.load_session(session_id)
        if checkpoint is None or not _visible_messages(checkpoint):
            continue
        if ledger.get(session_id) == session_digest(checkpoint):
            continue
        pending.append((session_id, checkpoint))
    return pending


def distill_session(
    adapter,
    wiki: Path,
    checkpoint: SessionCheckpoint,
    max_iters: int = 8,
) -> str:
    """
    One headless distill turn: the model reads the transcript and curates the
    wiki via file tools sandboxed to the wiki folder. Returns its summary line.
    """
    from scribe.prompts import _with_constitution
    from scribe.tools import fs

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _with_constitution(DISTILL_SYSTEM)},
        {
            "role": "user",
            "content": DISTILL_TASK.format(
                session_id=checkpoint.session_id,
                tag=session_tag(checkpoint.session_id),
                topic=checkpoint.topic,
                created_at=checkpoint.created_at,
                transcript=render_session(checkpoint),
            ),
        },
    ]

    final_answer = ""
    for _ in range(max_iters):
        answer_text = ""
        tool_calls = None
        for kind, payload in adapter.streaming_turn(messages, tools=fs.TOOL_SCHEMAS):
            if kind == "answer":
                answer_text += payload
            elif kind == "tool_calls":
                tool_calls = payload

        if not tool_calls:
            final_answer = answer_text
            break

        messages.append(
            {
                "role": "assistant",
                "content": answer_text,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in tool_calls
                ],
            }
        )
        for c in tool_calls:
            result = fs.dispatch(wiki, c["name"], c["arguments"])
            messages.append(
                {"role": "tool", "tool_call_id": c["id"], "content": result}
            )

    return final_answer.strip() or "(no summary)"


def distill(
    config,
    since: str | None = None,
    limit: int | None = None,
    adapter=None,
    on_progress=None,
) -> list[dict[str, str]]:
    """
    Distill all pending sessions into the wiki.

    The ledger is saved after every session, so an interrupted run resumes
    where it stopped. Returns one result dict per processed session.

    Args:
        config: ScribeConfig.
        since: Only sessions on/after this YYYYMMDD date.
        limit: Process at most this many sessions.
        adapter: LLMAdapter override (built from config when None).
        on_progress: Optional callback(session_id, summary) per session.
    """
    if adapter is None:
        from scribe.llm_adapter import LLMAdapter

        adapter = LLMAdapter.from_config(config)

    wiki = wiki_dir(config)
    manager = SessionManager(config)
    ledger = load_ledger(wiki)

    results: list[dict[str, str]] = []
    for session_id, checkpoint in pending_sessions(manager, ledger, since=since):
        if limit is not None and len(results) >= limit:
            break
        try:
            summary = distill_session(adapter, wiki, checkpoint)
        except Exception as e:
            logger.warning("[wiki] distill failed for %s", session_id, exc_info=True)
            results.append(
                {"session": session_id, "status": "error", "summary": str(e)}
            )
            continue

        status = "skipped" if summary.strip().upper().startswith("SKIP") else "stored"
        ledger[session_id] = session_digest(checkpoint)
        save_ledger(wiki, ledger)
        if status == "stored":
            rebuild_index(wiki)
        results.append({"session": session_id, "status": status, "summary": summary})
        if on_progress:
            on_progress(session_id, summary)

    return results
