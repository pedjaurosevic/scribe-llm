"""
Provenance World Model - Factual statements bound to fetched source spans.
Uses sqlite-vec for vector search and FTS5 for lexical search to build
a hybrid Claim Store.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite_vec
from sentence_transformers import SentenceTransformer

from scribe.memory.hybrid import _fts_escape, rrf_fuse
from scribe.tools.web import web_fetch

DEFAULT_CLAIMS_DB = Path.home() / ".scribe" / "claims.db"

# JSON Schema for a single step of the action loop
AGENT_STEP_SCHEMA = {
    "name": "AgentStep",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "rationale": {
                "type": "string",
                "description": "Advisory reasoning for the next step. Never actuates."
            },
            "type": {
                "type": "string",
                "enum": ["action", "final_answer"]
            },
            "action": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": ["navigate", "fetch", "extract", "quote"]
                    },
                    "url": {"type": "string"},
                    "query": {"type": "string"},
                    "selector_or_char_range": {"type": "string"}
                },
                "required": ["name"],
                "additionalProperties": False
            },
            "final_answer": {
                "type": "object",
                "properties": {
                    "statements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "cited_span_ids": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            },
                            "required": ["text", "cited_span_ids"],
                            "additionalProperties": False
                        }
                    },
                    "contradictions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "statement_a": {"type": "string"},
                                "span_id_a": {"type": "string"},
                                "statement_b": {"type": "string"},
                                "span_id_b": {"type": "string"},
                                "explanation": {"type": "string"}
                            },
                            "required": [
                                "statement_a", "span_id_a", "statement_b",
                                "span_id_b", "explanation"
                            ],
                            "additionalProperties": False
                        }
                    }
                },
                "required": ["statements", "contradictions"],
                "additionalProperties": False
            }
        },
        "required": ["rationale", "type"],
        "additionalProperties": False
    }
}


class ClaimStore:
    """
    SQLite-based Claim Store combining vector search (sqlite-vec) and full-text
    search (FTS5) for hybrid retrieval of read sources.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_CLAIMS_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._transformer: SentenceTransformer | None = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE,
            text TEXT,
            status TEXT,
            confidence REAL,
            evidence_url TEXT,
            evidence_span TEXT,
            fetched_at TEXT
        )
        """)
        self._conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_claims USING vec0(
            embedding float[384]
        )
        """)
        self._conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_claims USING fts5(
            text,
            content_rowid=rowid
        )
        """)
        self._conn.commit()

    @property
    def transformer(self) -> SentenceTransformer:
        if self._transformer is None:
            self._transformer = SentenceTransformer("intfloat/multilingual-e5-small")
        return self._transformer

    def embed(self, text: str) -> list[float]:
        return self.transformer.encode([text])[0].tolist()

    def add_claim(
        self,
        claim_id: str,
        text: str,
        status: str,
        confidence: float,
        url: str,
        selector_or_char_range: str,
        fetched_at: str,
        embedding: list[float] | None = None,
    ) -> None:
        if embedding is None:
            embedding = self.embed(text)

        cursor = self._conn.cursor()
        try:
            cursor.execute("""
            INSERT OR REPLACE INTO claims (id, text, status, confidence, evidence_url, evidence_span, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (claim_id, text, status, confidence, url, selector_or_char_range, fetched_at))
            rowid = cursor.lastrowid

            vec_bytes = struct.pack("384f", *embedding)
            cursor.execute("""
            INSERT OR REPLACE INTO vec_claims (rowid, embedding)
            VALUES (?, ?)
            """, (rowid, vec_bytes))

            cursor.execute("""
            INSERT OR REPLACE INTO fts_claims (rowid, text)
            VALUES (?, ?)
            """, (rowid, text))

            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            raise e

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        embedding = self.embed(query)
        vec_bytes = struct.pack("384f", *embedding)
        cursor = self._conn.cursor()

        cursor.execute("""
        SELECT rowid FROM vec_claims WHERE embedding MATCH ? AND k = ?
        """, (vec_bytes, limit * 2))
        vector_rank = [row[0] for row in cursor.fetchall()]

        fts_query = _fts_escape(query)
        fts_rank = []
        if fts_query:
            try:
                cursor.execute("""
                SELECT rowid FROM fts_claims WHERE fts_claims MATCH ? ORDER BY rank LIMIT ?
                """, (fts_query, limit * 2))
                fts_rank = [row[0] for row in cursor.fetchall()]
            except sqlite3.OperationalError:
                pass

        rankings = [[str(r) for r in vector_rank], [str(r) for r in fts_rank]]
        fused = rrf_fuse(rankings)

        results = []
        for rowid_str, _ in fused[:limit]:
            rowid = int(rowid_str)
            cursor.execute("""
            SELECT id, text, status, confidence, evidence_url, evidence_span, fetched_at
            FROM claims WHERE rowid = ?
            """, (rowid,))
            row = cursor.fetchone()
            if row:
                results.append({
                    "id": row[0],
                    "text": row[1],
                    "status": row[2],
                    "confidence": row[3],
                    "evidence": {
                        "url": row[4],
                        "selector_or_char_range": row[5],
                        "fetched_at": row[6],
                    },
                })
        return results

    def clear(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM claims")
        cursor.execute("DELETE FROM vec_claims")
        cursor.execute("DELETE FROM fts_claims")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def process_agent_response(
    response_json: dict[str, Any], fetch_log: dict[str, dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    """
    Validate cited spans deterministically. Block statements with no valid citation.
    Returns:
        (formatted_text, list_of_claims_to_add)
    """
    statements = response_json.get("final_answer", {}).get("statements", [])
    contradictions = response_json.get("final_answer", {}).get("contradictions", [])

    verified_statements = []
    blocked_statements = []
    verified_claims = []
    timestamps = []

    for stmt in statements:
        text = stmt.get("text", "").strip()
        cited_ids = stmt.get("cited_span_ids", [])

        valid_citations = []
        for cid in cited_ids:
            if cid in fetch_log:
                valid_citations.append(cid)
                ts = fetch_log[cid].get("fetched_at")
                if ts:
                    timestamps.append(ts)

        if not valid_citations:
            blocked_statements.append(text)
        else:
            verified_statements.append((text, valid_citations))
            for cid in valid_citations:
                span_data = fetch_log[cid]
                claim_id = f"c_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{hash(text) % 100000:05d}"
                verified_claims.append({
                    "id": claim_id,
                    "text": text,
                    "status": "verified",
                    "confidence": 1.0,
                    "url": span_data["url"],
                    "evidence_span": cid,
                    "fetched_at": span_data["fetched_at"],
                })

    verified_contradictions = []
    for contra in contradictions:
        sa = contra.get("statement_a", "").strip()
        sb = contra.get("statement_b", "").strip()
        cid_a = contra.get("span_id_a", "").strip()
        cid_b = contra.get("span_id_b", "").strip()
        expl = contra.get("explanation", "").strip()

        if cid_a in fetch_log and cid_b in fetch_log:
            verified_contradictions.append({
                "statement_a": sa,
                "span_id_a": cid_a,
                "statement_b": sb,
                "span_id_b": cid_b,
                "explanation": expl,
            })
            if fetch_log[cid_a].get("fetched_at"):
                timestamps.append(fetch_log[cid_a]["fetched_at"])
            if fetch_log[cid_b].get("fetched_at"):
                timestamps.append(fetch_log[cid_b]["fetched_at"])

    if timestamps:
        ref_time = max(timestamps)
    else:
        ref_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    output_lines = [f"As of {ref_time}:"]

    if not verified_statements and not verified_contradictions:
        output_lines.append("The sources do not contain this information.")
    else:
        for text, cids in verified_statements:
            cids_str = ", ".join(cids)
            output_lines.append(f"- {text} [{cids_str}]")

        if verified_contradictions:
            output_lines.append("\n[CONTRADICTION DETECTED]")
            for idx, c in enumerate(verified_contradictions, 1):
                output_lines.append(f"{idx}. Source A: {c['statement_a']} [{c['span_id_a']}]")
                output_lines.append(f"   Source B: {c['statement_b']} [{c['span_id_b']}]")
                output_lines.append(f"   Explanation: {c['explanation']}")

    if blocked_statements:
        output_lines.append("\n[BLOCKED STATEMENTS (unverified/no source span):]")
        for b in blocked_statements:
            output_lines.append(f"- {b}")

    return "\n".join(output_lines), verified_claims


async def run_provenance_loop(
    adapter: Any,
    query: str,
    claim_store: ClaimStore,
    max_steps: int = 5,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Run the typed action loop: navigate/fetch/extract/quote as typed actions
    via json_schema, enforcing empty-retrieval honesty and contradiction detection.
    """
    past_claims = claim_store.search(query, limit=5)
    past_context = ""
    if past_claims:
        past_context = "Past known claims from ClaimStore:\n"
        for pc in past_claims:
            past_context += f"- {pc['text']} (source: {pc['evidence']['url']}, fetched: {pc['evidence']['fetched_at']})\n"

    system_content = (
        "You are Scribe, an investigative research agent. You are operating in a typed action loop.\n"
        "Your task is to answer the user query based ONLY on the sources you fetch during this session. "
        "Do NOT use any prior knowledge or assumptions. If the fetched sources do not contain the answer, "
        "you MUST state that the sources do not say so.\n\n"
        "Every statement you make in your final answer must be linked to a valid span ID from the fetched context.\n"
        "If you find conflicting info in the fetched pages, output them in the 'contradictions' section with their span IDs.\n\n"
        "To fetch a page, output an action of type navigate or fetch with the url.\n"
        "When page content is provided, it will have line prefix span IDs like [s1_1], [s1_2] etc. "
        "Use these exact span IDs for citations in your final answer.\n\n"
    )
    if past_context:
        system_content += past_context + "\n"

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": query},
    ]

    fetch_log: dict[str, dict[str, Any]] = {}
    source_counter = 0

    for step in range(max_steps):
        try:
            res_text = adapter.complete(
                messages,
                response_format={"type": "json_schema", "json_schema": AGENT_STEP_SCHEMA},
                temperature=0.0,
            )
            step_data = json.loads(res_text)
        except Exception as e:
            return f"Error executing LLM turn: {e}", []

        step_type = step_data.get("type")
        rationale = step_data.get("rationale", "")

        if step_type == "final_answer" or step == max_steps - 1:
            formatted, new_claims = process_agent_response(step_data, fetch_log)
            for nc in new_claims:
                claim_store.add_claim(
                    claim_id=nc["id"],
                    text=nc["text"],
                    status=nc["status"],
                    confidence=nc["confidence"],
                    url=nc["url"],
                    selector_or_char_range=nc["evidence_span"],
                    fetched_at=nc["fetched_at"],
                )
            return formatted, new_claims

        action_data = step_data.get("action", {})
        action_name = action_data.get("name")
        url = action_data.get("url")

        if not url:
            messages.append({
                "role": "system",
                "content": "Action failed: Missing 'url' parameter. Try again or return final answer.",
            })
            continue

        source_counter += 1
        source_prefix = f"s{source_counter}"

        content = web_fetch(url)
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = content.split("\n")
        span_lines = []
        for idx, line in enumerate(lines):
            line_str = line.strip()
            if line_str:
                span_id = f"{source_prefix}_{idx+1}"
                fetch_log[span_id] = {
                    "id": span_id,
                    "text": line_str,
                    "url": url,
                    "fetched_at": fetched_at,
                }
                span_lines.append(f"[{span_id}] {line_str}")

        formatted_content = "\n".join(span_lines)
        messages.append({
            "role": "assistant",
            "content": f"Action rationale: {rationale}\nI choose to {action_name} URL: {url}",
        })
        messages.append({
            "role": "user",
            "content": f"Fetched content from {url} (as of {fetched_at}):\n{formatted_content}",
        })

    return "Failed to get final answer within maximum steps.", []


async def run_provenance_loop_ws(
    websocket: Any,
    query: str,
    claim_store: ClaimStore,
    adapter: Any,
    max_steps: int = 5,
) -> str:
    """
    WebSocket-aware variant of run_provenance_loop that streams step-by-step
    statuses, rationale, and action executions directly to the Web UI.
    """
    await websocket.send_json({
        "type": "status",
        "content": "Searching past claims in ClaimStore...",
    })
    past_claims = claim_store.search(query, limit=5)
    past_context = ""
    if past_claims:
        past_context = "Past known claims from ClaimStore:\n"
        for pc in past_claims:
            past_context += f"- {pc['text']} (source: {pc['evidence']['url']}, fetched: {pc['evidence']['fetched_at']})\n"

    system_content = (
        "You are Scribe, an investigative research agent. You are operating in a typed action loop.\n"
        "Your task is to answer the user query based ONLY on the sources you fetch during this session. "
        "Do NOT use any prior knowledge or assumptions. If the fetched sources do not contain the answer, "
        "you MUST state that the sources do not say so.\n\n"
        "Every statement you make in your final answer must be linked to a valid span ID from the fetched context.\n"
        "If you find conflicting info in the fetched pages, output them in the 'contradictions' section with their span IDs.\n\n"
        "To fetch a page, output an action of type navigate or fetch with the url.\n"
        "When page content is provided, it will have line prefix span IDs like [s1_1], [s1_2] etc. "
        "Use these exact span IDs for citations in your final answer.\n\n"
    )
    if past_context:
        system_content += past_context + "\n"

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": query},
    ]

    fetch_log: dict[str, dict[str, Any]] = {}
    source_counter = 0
    final_text = ""

    for step in range(max_steps):
        await websocket.send_json({
            "type": "status",
            "content": f"Deciding next step (turn {step+1})...",
        })

        try:
            res_text = adapter.complete(
                messages,
                response_format={"type": "json_schema", "json_schema": AGENT_STEP_SCHEMA},
                temperature=0.0,
            )
            step_data = json.loads(res_text)
        except Exception as e:
            err_msg = f"Error executing LLM turn: {e}"
            await websocket.send_json({"type": "chunk", "content": err_msg, "full": err_msg})
            return err_msg

        step_type = step_data.get("type")
        rationale = step_data.get("rationale", "")

        if rationale:
            await websocket.send_json({
                "type": "thinking",
                "content": f"[Rationale] {rationale}\n",
                "full": rationale,
            })

        if step_type == "final_answer" or step == max_steps - 1:
            await websocket.send_json({
                "type": "status",
                "content": "Verifying citations and grounding...",
            })
            formatted, new_claims = process_agent_response(step_data, fetch_log)
            for nc in new_claims:
                claim_store.add_claim(
                    claim_id=nc["id"],
                    text=nc["text"],
                    status=nc["status"],
                    confidence=nc["confidence"],
                    url=nc["url"],
                    selector_or_char_range=nc["evidence_span"],
                    fetched_at=nc["fetched_at"],
                )
            await websocket.send_json({
                "type": "chunk",
                "content": formatted,
                "full": formatted,
            })
            final_text = formatted
            break

        action_data = step_data.get("action", {})
        action_name = action_data.get("name")
        url = action_data.get("url")

        if not url:
            messages.append({
                "role": "system",
                "content": "Action failed: Missing 'url' parameter. Try again or return final answer.",
            })
            continue

        source_counter += 1
        source_prefix = f"s{source_counter}"

        await websocket.send_json({
            "type": "status",
            "content": f"Executing action '{action_name}' on {url}...",
        })

        content = web_fetch(url)
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = content.split("\n")
        span_lines = []
        for idx, line in enumerate(lines):
            line_str = line.strip()
            if line_str:
                span_id = f"{source_prefix}_{idx+1}"
                fetch_log[span_id] = {
                    "id": span_id,
                    "text": line_str,
                    "url": url,
                    "fetched_at": fetched_at,
                }
                span_lines.append(f"[{span_id}] {line_str}")

        formatted_content = "\n".join(span_lines)

        await websocket.send_json({
            "type": "tool",
            "name": action_name,
            "args": {"url": url},
            "result": f"Fetched {len(span_lines)} lines.",
        })

        messages.append({
            "role": "assistant",
            "content": f"Action rationale: {rationale}\nI choose to {action_name} URL: {url}",
        })
        messages.append({
            "role": "user",
            "content": f"Fetched content from {url} (as of {fetched_at}):\n{formatted_content}",
        })

    return final_text

