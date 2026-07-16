"""
Machine-readable status contract (`scribe-llm status --json`).

One stable JSON document describing the whole installation: version, server
reachability, capability flags (grammar enforcement, sandbox), memory/RAG
counts, sessions, and the latest bench numbers. Keys are append-only — tools
built against this contract keep working across Scribe versions.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scribe import __version__


def collect_status(config) -> dict[str, Any]:
    """Assemble the status document. Every probe degrades to a null/False —
    status collection must never crash, whatever is broken."""
    from scribe.llm_adapter import LLMAdapter
    from scribe.tools.sandbox import bwrap_available

    adapter = LLMAdapter.from_config(config)
    healthy = adapter.is_healthy()

    status: dict[str, Any] = {
        "version": __version__,
        "server": {
            "base_url": config.base_url,
            "reachable": healthy,
            "model": adapter.get_model_name() if healthy else None,
            "grammar_enforcement": adapter.grammar_supported() if healthy else False,
        },
        "capabilities": {
            "sandbox_bwrap": bwrap_available(),
            "tool_grammar": getattr(config, "tool_grammar", "auto"),
            "reasoning": config.reasoning,
            "tools_enabled": config.tools_enabled,
        },
        "workspace": {
            "dir": config.workspace_dir,
            "exists": Path(config.workspace_dir).is_dir(),
        },
        "sessions": _sessions_block(config),
        "rag": _rag_block(config),
        "sme": _sme_block(config),
        "bench": _bench_block(),
    }
    return status


def _sessions_block(config) -> dict[str, Any]:
    try:
        from scribe.session import SessionManager

        manager = SessionManager(config)
        sessions = manager.list_sessions()
        return {"count": len(sessions), "last": sessions[0] if sessions else None}
    except Exception:
        return {"count": 0, "last": None}


def _rag_block(config) -> dict[str, Any]:
    """Fast RAG status without constructing RAGService.

    RAGService owns the embedding model and semantic search stack. Status should
    be a cheap liveness contract, so it reads existing FTS/LanceDB metadata
    directly and never imports sentence-transformers.
    """
    db_path = Path(getattr(config, "rag_db_path", ""))
    fts = _rag_fts_block(db_path / "fts.db")
    if fts is not None:
        return {
            "available": True,
            "chunks": fts["chunks"],
            "fts_chunks": fts["chunks"],
            "sources": fts["sources"],
            "mode": "fast",
        }

    lance = _rag_lance_block(db_path)
    if lance is not None:
        return {
            "available": True,
            "chunks": lance["chunks"],
            "fts_chunks": None,
            "sources": None,
            "mode": "fast",
        }

    return {"available": db_path.exists(), "chunks": 0, "fts_chunks": 0, "sources": 0}


def _rag_fts_block(db_file: Path) -> dict[str, int] | None:
    """Read chunk/source counts from an existing FTS DB without creating it."""
    if not db_file.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            sources = conn.execute(
                "SELECT COUNT(DISTINCT source_file) FROM chunks WHERE source_file != ''"
            ).fetchone()[0]
            return {"chunks": int(chunks), "sources": int(sources)}
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _rag_lance_block(db_path: Path) -> dict[str, int] | None:
    """Fallback to LanceDB row count; still avoids RAGService/embeddings."""
    if not (db_path / "documents.lance").exists():
        return None
    try:
        import lancedb

        table = lancedb.connect(str(db_path)).open_table("documents")
        return {"chunks": int(table.count_rows())}
    except Exception:
        return None


def _sme_block(config) -> dict[str, Any]:
    try:
        return {
            "enabled": bool(config.sme_enabled),
            "db_path": config.sme_db_path,
            "exists": Path(config.sme_db_path).exists(),
        }
    except Exception:
        return {"enabled": False}


def _bench_block() -> dict[str, Any]:
    """Latest entry from the evolve ledger, when one exists."""
    try:
        from scribe.evolve.evaluate import LEDGER_FILE

        if not LEDGER_FILE.exists():
            return {"last": None}
        lines = [
            line for line in LEDGER_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {"last": json.loads(lines[-1]) if lines else None}
    except Exception:
        return {"last": None}


def render_status(status: dict[str, Any], console) -> None:
    """Human-readable rendering of the same document."""
    server = status["server"]
    caps = status["capabilities"]
    mark = "[success]●[/success]" if server["reachable"] else "[error]○[/error]"
    console.print(f"[bold]Scribe {status['version']}[/bold]")
    console.print(
        f"  {mark} server  {server['base_url']}"
        + (f"  [accent]{server['model']}[/accent]" if server["model"] else "")
    )
    console.print(
        f"  grammar={'on' if server['grammar_enforcement'] else 'n/a'}  "
        f"sandbox={'bwrap' if caps['sandbox_bwrap'] else 'rlimits-only'}  "
        f"reasoning={caps['reasoning']}"
    )
    console.print(
        f"  sessions: {status['sessions']['count']}"
        f"   rag chunks: {status['rag'].get('chunks', '—')}"
        f" (fts {status['rag'].get('fts_chunks', '—')})"
    )
    last = status["bench"]["last"]
    if last:
        console.print(
            f"  last bench: fitness={last.get('fitness')} "
            f"[dim]({last.get('ts', '')})[/dim]"
        )
    sme = status["sme"]
    if sme.get("enabled"):
        console.print(f"  memory: [dim]{sme.get('db_path')}[/dim]")
