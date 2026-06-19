"""
Scribe Web - FastAPI web server with streaming chat UI.
"""

# Security: this module implements rate-limiting, security headers, audit
# logging, WebSocket origin checks, and cookie hardening.  See the
# ``require_pin`` and ``security_headers`` middlewares.

from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import signal
import struct
import subprocess
import tempfile
import time
from pathlib import Path

# The integrated terminal needs a POSIX pseudo-terminal (Linux/macOS/WSL).
# These modules don't exist on native Windows; the rest of the web UI — editor,
# chat, book export — still works there, only the terminal is unavailable.
try:
    import fcntl
    import pty
    import termios

    _PTY_AVAILABLE = True
except ImportError:  # native Windows
    _PTY_AVAILABLE = False

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scribe.config import ScribeConfig
from scribe.documents import DocumentStore
from scribe.llm_adapter import LLMAdapter
from scribe.memory.sme import get_sme_service, recall_previous_session
from scribe.prompts import get_system_prompt
from scribe.session import SessionManager
from scribe.skills_executor import SkillsExecutor
from scribe.tools import fs, web

app = FastAPI(title="Scribe", description="Autonomous Research & Writing Agent")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

config = ScribeConfig()
adapter = LLMAdapter.from_config(config)
session_manager = SessionManager(config)
sme_service = get_sme_service()
skills_executor = SkillsExecutor()
store = DocumentStore(config)

# Local working directory Scribe operates in.
WORKSPACE_DIR = Path(config.workspace_dir)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Ingest material (PDF/TXT/MD/EPUB) uploaded through the web UI lives here, in a
# clear visible folder, and is indexed into RAG as source material.
RESOURCES_DIR = WORKSPACE_DIR / "resources"
RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
INGEST_SUFFIXES = {".pdf", ".txt", ".md", ".epub"}

# The RAG service pulls in sentence-transformers, so build it lazily on first
# ingest instead of paying the import cost on every server start.
_rag_service = None


def _get_rag():
    """Return a shared RAGService, importing/initialising it on first use."""
    global _rag_service
    if _rag_service is None:
        from scribe.memory.rag import get_rag_service
        _rag_service = get_rag_service(config)
    return _rag_service


# --- PIN gate -------------------------------------------------------------
# The web UI binds to all interfaces, so we gate it behind a PIN. The cookie
# never stores the PIN itself, only a derived token, and is compared in
# constant time. An empty pin in config disables the gate entirely.
AUTH_COOKIE = "scribe_auth"
_PIN = config.web_pin


def _expected_token() -> str:
    """Derive the opaque session token from the configured PIN."""
    return hashlib.sha256(f"scribe-gate:{_PIN}".encode()).hexdigest()


def _is_authed(request_or_ws) -> bool:
    """True when the request/websocket carries a valid auth cookie."""
    if not _PIN:
        return True
    token = request_or_ws.cookies.get(AUTH_COOKIE, "")
    return hmac.compare_digest(token, _expected_token())


# --- Security: audit logger ------------------------------------------------
security_log = logging.getLogger("scribe.security")


# --- Security: rate limiting ------------------------------------------------
# In-memory sliding-window rate limiter for the login endpoint. Prevents PIN
# brute-force: max RATE_LIMIT_MAX attempts within RATE_LIMIT_WINDOW seconds per
# client IP.  Entries auto-expire on access.

RATE_LIMIT_WINDOW = 300  # seconds
RATE_LIMIT_MAX = 5       # max attempts per window

_login_attempts: dict[str, list[float]] = collections.defaultdict(list)


def _is_rate_limited(client_ip: str) -> bool:
    """True when the client has exceeded the login attempt limit."""
    now = time.monotonic()
    window = _login_attempts[client_ip]
    # Expire old entries.
    _login_attempts[client_ip] = window = [t for t in window if now - t < RATE_LIMIT_WINDOW]
    return len(window) >= RATE_LIMIT_MAX


def _record_attempt(client_ip: str) -> None:
    """Record a login attempt timestamp."""
    _login_attempts[client_ip].append(time.monotonic())


def _client_ip(request: Request) -> str:
    """Best-effort client IP (X-Forwarded-For aware)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- Security: WebSocket origin check --------------------------------------

def _valid_ws_origin(websocket: WebSocket) -> bool:
    """Reject WebSocket upgrades from foreign origins (CSWSH protection)."""
    origin = websocket.headers.get("origin", "")
    if not origin:
        # No Origin header — non-browser client; allow (same as before).
        return True
    host = websocket.headers.get("host", "")
    # Strip scheme from origin and compare host parts.
    origin_host = origin.split("://", 1)[-1].rstrip("/")
    return origin_host == host


LOGIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Scribe — PIN</title>
<style>
  body{{background:#282828;color:#ebdbb2;font-family:monospace;display:flex;
       height:100vh;margin:0;align-items:center;justify-content:center}}
  form{{background:#3c3836;padding:2rem;border-radius:10px;text-align:center;
        box-shadow:0 8px 30px rgba(0,0,0,.4)}}
  h1{{color:#8ec07c;margin:0 0 1rem;font-size:1.2rem}}
  input{{background:#282828;border:1px solid #504945;color:#ebdbb2;
         font-size:1.4rem;padding:.5rem;width:8rem;text-align:center;
         letter-spacing:.4rem;border-radius:6px}}
  button{{margin-top:1rem;background:#8ec07c;color:#282828;border:0;
          padding:.5rem 1.5rem;font-size:1rem;border-radius:6px;cursor:pointer}}
  .err{{color:#fb4934;margin-top:.8rem;min-height:1rem}}
</style></head><body>
<form method="post" action="/login">
  <h1>🔒 Scribe</h1>
  <input name="pin" type="password" inputmode="numeric" autofocus
         placeholder="PIN" autocomplete="off">
  <div class="err">{error}</div>
  <button type="submit">Unlock</button>
</form></body></html>"""


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to every HTTP response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"
    # CSP: allow inline styles/scripts (the SPA needs them) but nothing else.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'"
    )
    return response


@app.middleware("http")
async def require_pin(request: Request, call_next):
    """Block every HTTP route until the PIN cookie is present and valid."""
    open_paths = ("/login", "/static", "/favicon.ico")
    if _PIN and not request.url.path.startswith(open_paths) and not _is_authed(request):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """Serve the PIN entry page."""
    ip = _client_ip(request)
    if _is_rate_limited(ip):
        return HTMLResponse(
            LOGIN_HTML.format(error="Too many attempts — try again later."),
            status_code=429,
            headers={"Retry-After": str(RATE_LIMIT_WINDOW)},
        )
    return LOGIN_HTML.format(error="")


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, pin: str = Form("")):
    """Check the PIN; on success set the auth cookie and enter the UI."""
    ip = _client_ip(request)
    if _is_rate_limited(ip):
        security_log.warning("login rate-limited ip=%s", ip)
        return HTMLResponse(
            LOGIN_HTML.format(error="Too many attempts — try again later."),
            status_code=429,
            headers={"Retry-After": str(RATE_LIMIT_WINDOW)},
        )
    _record_attempt(ip)
    if hmac.compare_digest(pin, _PIN):
        security_log.info("login success ip=%s", ip)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            AUTH_COOKIE,
            _expected_token(),
            httponly=True,
            samesite="strict",
            max_age=60 * 60 * 24,  # 24 hours (was 7 days)
        )
        return resp
    security_log.warning("login failed ip=%s", ip)
    return HTMLResponse(LOGIN_HTML.format(error="Wrong PIN"), status_code=401)


@app.get("/logout")
async def logout():
    """Clear the auth cookie."""
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(AUTH_COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serve the document editor UI (dark Google-Docs style)."""
    session_summary = recall_previous_session(sme_service)
    return templates.TemplateResponse("editor.html", {
        "request": request,
        "model_name": adapter.get_model_name(),
        "session_summary": session_summary,
    })


@app.get("/chat", response_class=HTMLResponse)
async def chat_ui(request: Request):
    """Serve the original plain chat UI."""
    session_summary = recall_previous_session(sme_service)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "session_summary": session_summary,
        "model_name": adapter.get_model_name(),
    })


# --- Document store REST API ---------------------------------------------


@app.get("/api/docs")
async def api_list_docs():
    """List all documents/books, newest first (for the sidebar)."""
    return {"documents": store.list()}


@app.post("/api/docs")
async def api_create_doc(request: Request):
    """Create a new document or book."""
    body = await request.json()
    title = body.get("title", "Untitled")
    doc_type = body.get("type", "doc")
    return store.create(title, doc_type)


@app.get("/api/docs/{doc_id}")
async def api_get_doc(doc_id: str):
    """Load full document (meta + body, or chapter bodies for a book)."""
    doc = store.load(doc_id)
    if doc is None:
        return PlainTextResponse("Not found", status_code=404)
    return doc


@app.put("/api/docs/{doc_id}")
async def api_save_doc(doc_id: str, request: Request):
    """Autosave: body of a doc, one chapter of a book, and/or the title."""
    if not store.exists(doc_id):
        return PlainTextResponse("Not found", status_code=404)
    body = await request.json()
    if "title" in body:
        store.rename(doc_id, body["title"])
    if "chapter_id" in body:
        store.save_chapter(doc_id, body["chapter_id"], body.get("content", ""))
    elif "content" in body:
        store.save_content(doc_id, body["content"])
    return {"ok": True}


@app.post("/api/docs/{doc_id}/chapters")
async def api_add_chapter(doc_id: str, request: Request):
    """Append one chapter, or replace the whole TOC with a list of titles."""
    if not store.exists(doc_id):
        return PlainTextResponse("Not found", status_code=404)
    body = await request.json()
    if "titles" in body:
        return store.set_toc(doc_id, body["titles"])
    return store.add_chapter(doc_id, body.get("title", "Untitled"))


@app.delete("/api/docs/{doc_id}")
async def api_delete_doc(doc_id: str):
    """Delete a document (only ever called from an explicit UI action)."""
    return {"ok": store.delete(doc_id)}


# --- Document history / versioning ---------------------------------------


@app.post("/api/docs/{doc_id}/snapshot")
async def api_snapshot(doc_id: str, request: Request):
    """Save the current document state as a version the user can return to."""
    if not store.exists(doc_id):
        return PlainTextResponse("Not found", status_code=404)
    body = await request.json() if await request.body() else {}
    label = body.get("label", "") if isinstance(body, dict) else ""
    snap = store.snapshot(doc_id, label=label)
    return snap or {"error": "could not snapshot"}


@app.get("/api/docs/{doc_id}/history")
async def api_history(doc_id: str):
    """List all saved versions of a document, newest first."""
    if not store.exists(doc_id):
        return PlainTextResponse("Not found", status_code=404)
    return {"history": store.list_history(doc_id)}


@app.get("/api/docs/{doc_id}/history/{ts}")
async def api_history_get(doc_id: str, ts: str):
    """Load one version's full content for preview."""
    snap = store.get_history(doc_id, ts)
    if snap is None:
        return PlainTextResponse("Not found", status_code=404)
    return snap


@app.post("/api/docs/{doc_id}/history/{ts}/restore")
async def api_history_restore(doc_id: str, ts: str):
    """Roll the document back to a version (current state is snapshotted first)."""
    if not store.restore(doc_id, ts):
        return PlainTextResponse("Not found", status_code=404)
    return {"ok": True}


# --- Resources / ingest material -----------------------------------------
# Uploaded source files (PDF/TXT/MD/EPUB) are saved under <workspace>/resources
# and indexed into RAG so the model can ground its writing in them.


def _resource_entries() -> list[dict]:
    """List ingested resource files with size and modified time."""
    entries = []
    for p in sorted(RESOURCES_DIR.iterdir(), key=lambda x: x.name.lower()):
        if p.is_file() and not p.name.startswith("."):
            stat = p.stat()
            entries.append({
                "name": p.name,
                "size": stat.st_size,
                "suffix": p.suffix.lower().lstrip("."),
                "ingested": p.suffix.lower() in INGEST_SUFFIXES,
            })
    return entries


@app.get("/api/resources")
async def api_resources():
    """List ingest material the user has uploaded through the web UI."""
    return {"resources": _resource_entries()}


@app.post("/api/resources")
async def api_ingest(file: UploadFile = File(...)):
    """Save an uploaded PDF/TXT/MD/EPUB to the resources folder and index it."""
    name = os.path.basename(file.filename or "").strip()
    if not name:
        return JSONResponse({"error": "Missing filename"}, status_code=400)
    suffix = Path(name).suffix.lower()
    if suffix not in INGEST_SUFFIXES:
        return JSONResponse(
            {"error": f"Unsupported type '{suffix}'. Allowed: PDF, TXT, MD, EPUB."},
            status_code=400,
        )

    dest = RESOURCES_DIR / name
    # Avoid clobbering an existing resource of the same name.
    stem, n = dest.stem, 1
    while dest.exists():
        dest = RESOURCES_DIR / f"{stem}-{n}{suffix}"
        n += 1
    dest.write_bytes(await file.read())

    chunks = 0
    error = None
    try:
        rag = _get_rag()
        if rag is not None:
            chunks = rag.ingest_file(dest)
    except Exception as e:  # indexing failed, but the file is saved
        error = str(e)

    return {
        "ok": True,
        "name": dest.name,
        "chunks": chunks,
        "indexed": error is None and chunks > 0,
        "error": error,
    }


@app.delete("/api/resources/{name}")
async def api_delete_resource(name: str):
    """Delete an uploaded resource file (explicit user action)."""
    target = RESOURCES_DIR / os.path.basename(name)
    if target.is_file() and target.parent == RESOURCES_DIR:
        target.unlink()
        return {"ok": True}
    return PlainTextResponse("Not found", status_code=404)


# --- Export ---------------------------------------------------------------


@app.get("/api/docs/{doc_id}/export.md")
async def export_md(doc_id: str):
    """Download the assembled markdown."""
    if not store.exists(doc_id):
        return PlainTextResponse("Not found", status_code=404)
    md = store.assemble_markdown(doc_id)
    filename = f"{doc_id}.md"
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/docs/{doc_id}/export.epub")
async def export_epub(doc_id: str):
    """Convert the assembled markdown to EPUB via pandoc."""
    if not store.exists(doc_id):
        return PlainTextResponse("Not found", status_code=404)
    if shutil.which("pandoc") is None:
        return PlainTextResponse("pandoc is not installed on the system.", status_code=501)

    doc = store.load(doc_id)
    md = store.assemble_epub_markdown(doc_id)
    tmpdir = Path(tempfile.mkdtemp(prefix="scribe-epub-"))
    md_path = tmpdir / "book.md"
    epub_path = tmpdir / "book.epub"
    md_path.write_text(md, encoding="utf-8")
    try:
        subprocess.run(
            [
                "pandoc", str(md_path), "-o", str(epub_path),
                "--metadata", f"title={doc.get('title', 'Untitled')}",
                "--toc",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        detail = getattr(e, "stderr", b"")
        msg = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else str(e)
        return PlainTextResponse(f"pandoc error: {msg}", status_code=500)

    return FileResponse(
        str(epub_path),
        media_type="application/epub+zip",
        filename=f"{doc.get('title', doc_id)}.epub",
    )


@app.get("/print/{doc_id}", response_class=HTMLResponse)
async def print_view(doc_id: str, request: Request):
    """Clean light 'paper' page for browser Save-as-PDF."""
    doc = store.load(doc_id)
    if doc is None:
        return PlainTextResponse("Not found", status_code=404)
    return templates.TemplateResponse("print.html", {
        "request": request,
        "title": doc.get("title", "Untitled"),
        "markdown": store.assemble_markdown(doc_id),
    })


# --- Workspace file explorer ---------------------------------------------
# A real VSCode-style file tree of the workspace. Every path is resolved and
# confined to WORKSPACE_DIR through fs._safe_path, so the browser can never
# read or write outside the workspace.

_TEXT_MAX = 2_000_000  # refuse to open files larger than ~2 MB in the editor


def _list_dir(rel: str) -> list[dict]:
    """List one directory level (folders first, then files), workspace-scoped."""
    target = fs._safe_path(WORKSPACE_DIR, rel or ".")
    if not target.is_dir():
        raise fs.WorkspaceError(f"Not a directory: {rel}")
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.name.startswith("."):
            continue  # hide dotfiles, like a clean explorer
        entries.append({
            "name": p.name,
            "path": str(p.relative_to(WORKSPACE_DIR)),
            "type": "dir" if p.is_dir() else "file",
        })
    return entries


@app.get("/api/files")
async def api_files(path: str = ""):
    """List a workspace directory for the file tree (lazy, one level)."""
    try:
        return {"path": path, "entries": _list_dir(path)}
    except (fs.WorkspaceError, OSError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/file")
async def api_read_file(path: str):
    """Read a workspace text file into the editor."""
    try:
        target = fs._safe_path(WORKSPACE_DIR, path)
        if not target.is_file():
            return JSONResponse({"error": "Not a file"}, status_code=404)
        if target.stat().st_size > _TEXT_MAX:
            return JSONResponse({"error": "File too large to open"}, status_code=413)
        return {"path": path, "content": target.read_text(encoding="utf-8", errors="replace")}
    except (fs.WorkspaceError, OSError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.put("/api/file")
async def api_write_file(request: Request):
    """Save the editor contents back to a workspace file."""
    data = await request.json()
    path = (data.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "Missing path"}, status_code=400)
    try:
        fs.write_file(WORKSPACE_DIR, path, data.get("content", ""))
        return {"ok": True, "path": path}
    except (fs.WorkspaceError, OSError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# --- Model backend switcher (mirrors the TUI /models command) -------------


@app.get("/api/backend")
async def api_get_backend():
    """Report the active model backend so the UI can show it."""
    key = config.api_key
    return {
        "base_url": config.base_url,
        "model": config.model,
        "has_key": bool(key) and key not in ("not-needed", ""),
        "healthy": adapter.is_healthy(),
        "model_name": adapter.get_model_name(),
    }


@app.post("/api/backend")
async def api_set_backend(request: Request):
    """
    Switch the model backend at runtime: a local llama.cpp server or any
    OpenAI-compatible API. Persists to the user config and rebuilds the
    adapter so the next chat turn uses it — no server restart.
    """
    global adapter
    data = await request.json()
    kind = (data.get("kind") or "").strip().lower()

    if kind == "local":
        base_url = (data.get("base_url") or "http://127.0.0.1:18083/v1").strip()
        model, api_key, grammar = "default", "not-needed", "auto"
    elif kind == "api":
        base_url = (data.get("base_url") or "").strip()
        model = (data.get("model") or "").strip()
        if not base_url or not model:
            return JSONResponse(
                {"error": "API backend needs base_url and model"}, status_code=400
            )
        # Cloud endpoints do not support GBNF grammar; fall back to parsing.
        api_key = (data.get("api_key") or "").strip() or "not-needed"
        grammar = "off"
    else:
        return JSONResponse({"error": "kind must be 'local' or 'api'"}, status_code=400)

    try:
        config.save_value("scribe", "base_url", base_url)
        config.save_value("scribe", "model", model)
        config.save_value("scribe", "api_key", api_key)
        config.save_value("scribe", "tool_grammar", grammar)
    except Exception as e:
        return JSONResponse({"error": f"Could not save config: {e}"}, status_code=500)

    adapter = LLMAdapter.from_config(config)
    return {
        "ok": True,
        "base_url": config.base_url,
        "model": config.model,
        "healthy": adapter.is_healthy(),
        "model_name": adapter.get_model_name(),
    }


@app.get("/status")
async def status():
    """Return system status."""
    return {
        "healthy": adapter.is_healthy(),
        "model": adapter.get_model_name(),
        "base_url": config.base_url,
    }


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass


manager = ConnectionManager()

# Sentinels that fence a user-locked region inside the document body. They are
# shared with the front-end (editor.html) and stripped from MD/EPUB exports.
LOCK_OPEN = "⟦LOCK⟧"
LOCK_CLOSE = "⟦/LOCK⟧"


def _has_resources() -> bool:
    """True when the user has uploaded any ingest material to ground on."""
    try:
        return any(
            p.is_file() and not p.name.startswith(".") for p in RESOURCES_DIR.iterdir()
        )
    except OSError:
        return False


def _grounded_chunks(query: str, k: int = 5):
    """Return the raw RAG chunks for a grounded Q&A turn (or [] on any failure)."""
    if not query.strip():
        return []
    try:
        rag = _get_rag()
        if rag is None:
            return []
        return rag.search(query, limit=k)
    except Exception:
        return []


def _retrieve_sources(query: str, k: int = 4) -> tuple[str, int]:
    """Retrieve relevant chunks from RAG to ground a writing/chat turn.

    Returns ``(sources_block, count)``. Empty/0 when there is nothing to ground
    on, RAG is unavailable, or the search fails — grounding is best-effort and
    never blocks a turn.
    """
    if not query.strip() or not _has_resources():
        return "", 0
    try:
        rag = _get_rag()
        if rag is None:
            return "", 0
        chunks = rag.search(query, limit=k)
    except Exception:
        return "", 0
    if not chunks:
        return "", 0
    lines = [
        "You have retrieved the following passages from the user's own ingested "
        "resources for the CURRENT request. They are authoritative reference "
        "material that the user explicitly added.",
        "",
        "RULES:",
        "- If these passages contain the answer, you MUST answer from them and "
        "cite inline as [n]. Do not claim the information is missing.",
        "- Only say information is unavailable if it is genuinely absent from "
        "every passage below.",
        "- Prefer these passages over your own assumptions or memory.",
        "",
        "## Retrieved sources",
        "",
    ]
    for n, c in enumerate(chunks, 1):
        name = (getattr(c, "source_file", "") or "source").rsplit("/", 1)[-1]
        lines.append(f"[{n}] ({name})")
        lines.append((getattr(c, "content", "") or "").strip())
        lines.append("")
    return "\n".join(lines), len(chunks)


def _compose_writing_prompt(instruction: str, doc_context: str, mode: str) -> str:
    """Wrap the user's command with the current document so the model writes
    content meant to be inserted straight into the editor.

    The model answer is streamed verbatim into the document, so we ask for the
    raw markdown body only — no chat-style preamble, no meta commentary.
    """
    unit = "chapter" if mode == "book" else "document"
    parts = []
    if doc_context.strip():
        parts.append(f"[Current {unit} content]:\n{doc_context.strip()}")
    parts.append(f"[User Instruction/Question]: {instruction}")
    rules = (
        f"You are helping the user edit this {unit}.\n"
        f"If the user wants you to write, edit, update, or rewrite the content of the {unit}, "
        f"you MUST wrap the entire updated markdown content for the {unit} inside "
        "`<doc_content>...</doc_content>` tags. "
        "Do not include any introductory phrases, greetings, or commentary inside the "
        "`<doc_content>` tags.\n"
        "However, if the user is asking a question, discussing, explaining, or if you are "
        "not sure whether they want to write directly to the document/chapter, do NOT use "
        "`<doc_content>` tags. Instead, reply in the chatbox to discuss or ask for confirmation."
    )
    # Locked regions arrive wrapped in sentinels; the model must keep them
    # byte-for-byte, sentinels included, so the UI can re-anchor them.
    if LOCK_OPEN in doc_context:
        rules += (
            f"\n\nIMPORTANT: text wrapped between `{LOCK_OPEN}` and `{LOCK_CLOSE}` is LOCKED "
            "by the user. You MUST reproduce every locked region exactly as-is, including "
            "the sentinels, and you must NOT rephrase, move, summarise or delete anything "
            "inside them. Edit only the text outside the locked regions."
        )
    parts.append(rules)
    return "\n\n".join(parts)


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for streaming chat."""
    # HTTP middleware does not cover websockets, so gate the cookie here.
    if not _is_authed(websocket):
        await websocket.close(code=1008)  # policy violation
        return
    # Reject cross-origin connections (CSWSH protection).
    if not _valid_ws_origin(websocket):
        security_log.warning("ws/chat rejected foreign origin=%s", websocket.headers.get("origin"))
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)

    session_summary = recall_previous_session(sme_service)
    system_content = get_system_prompt(
        config.reasoning,
        workspace=str(WORKSPACE_DIR),
        max_thinking_words=config.max_thinking_words,
        mode=config.reasoning_mode,
    )
    if session_summary and "No previous session found" not in session_summary:
        system_content += (
            "\n\n## Previous Session Memory\n"
            "You have recalled the following summary of the user's previous session:\n"
            f"{session_summary}\n"
            "If the user asks about the previous session, refer to this memory."
        )

    messages = [{
        "role": "system",
        "content": system_content,
    }]

    # Per-connection reasoning state, toggled live with the /reasoning command
    # (same semantics as the TUI toggle).
    reasoning = config.reasoning

    session_manager.start_session(topic="web_chat")

    try:
        while True:
            data = await websocket.receive_text()
            event = json.loads(data)

            if event.get("type") == "message":
                user_content = event.get("content", "").strip()
                if not user_content:
                    continue

                # /reasoning [on|off] — handled here, never sent to the model.
                if user_content.lower().startswith("/reasoning"):
                    arg = user_content[len("/reasoning"):].strip().lower()
                    if arg in ("on", "true", "1"):
                        reasoning = True
                    elif arg in ("off", "false", "0"):
                        reasoning = False
                    else:
                        reasoning = not reasoning

                    adapter.enable_thinking = reasoning
                    if reasoning:
                        directive = (
                            "Reasoning is now ON. Think step by step inside a "
                            "<think> block, then give a SHORT final answer in "
                            "the user's language."
                        )
                        note = "✓ Reasoning ON — model thinks before responding."
                    else:
                        directive = (
                            "Reasoning is now OFF. Do NOT produce a <think> "
                            "block or any step-by-step reasoning. Answer "
                            "directly and concisely in the user's language."
                        )
                        note = "→ Reasoning OFF — model answers directly."
                    messages.append({"role": "system", "content": directive})
                    await websocket.send_json(
                        {"type": "chunk", "content": note, "full": note}
                    )
                    await websocket.send_json({"type": "done", "content": note})
                    continue

                doc_context = event.get("doc_context", "")
                mode = event.get("mode", "free")

                # Skill detection (e.g. deep-research)
                should_use_skill, skill_name = skills_executor.should_use_skill(user_content)
                if should_use_skill and skill_name:
                    result = skills_executor.execute_skill(skill_name, {"task": user_content})
                    if result.success:
                        user_content = f"{user_content}\n\n{result.output}"

                # Ground the turn in ingested resources (best-effort, off-thread
                # so the embedding search never blocks the event loop).
                sources_block, n_sources = "", 0
                if _has_resources():
                    await websocket.send_json({
                        "type": "status", "content": "Reading your resources…"
                    })
                    loop = asyncio.get_event_loop()
                    sources_block, n_sources = await loop.run_in_executor(
                        None, _retrieve_sources, user_content
                    )

                if doc_context or mode == "book":
                    model_input = _compose_writing_prompt(user_content, doc_context, mode)
                else:
                    model_input = user_content
                # Sources ride at the end of the user turn (recency) — close to
                # where the model starts answering. Folding them into the system
                # prompt fought the session-recall text already living there.
                if sources_block:
                    model_input = model_input + "\n\n" + sources_block
                messages.append({"role": "user", "content": model_input})
                _orig_system = None

                if n_sources:
                    await websocket.send_json({
                        "type": "tool",
                        "name": "grounding",
                        "args": {"query": user_content[:80]},
                        "result": f"Using {n_sources} passage(s) from your ingested resources.",
                    })

                await websocket.send_json({
                    "type": "status",
                    "content": "Generating..."
                })

                tools = fs.TOOL_SCHEMAS + web.TOOL_SCHEMAS if config.tools_enabled else None
                final_answer = ""

                for _ in range(6):
                    thinking_text = ""
                    answer_text = ""
                    tool_calls = None

                    async for kind, payload in adapter.streaming_turn_async(messages, tools=tools):
                        if kind == "thinking":
                            thinking_text += payload
                            await websocket.send_json({
                                "type": "thinking",
                                "content": payload,
                                "full": thinking_text,
                            })
                        elif kind == "answer":
                            answer_text += payload
                            await websocket.send_json({
                                "type": "chunk",
                                "content": payload,
                                "full": answer_text,
                            })
                        elif kind == "tool_calls":
                            tool_calls = payload

                    if not tool_calls:
                        # Safety net: if </think> never closed, surface thinking.
                        if not answer_text.strip() and thinking_text.strip():
                            answer_text = thinking_text
                            await websocket.send_json({
                                "type": "chunk",
                                "content": answer_text,
                                "full": answer_text,
                            })
                        final_answer = answer_text
                        break

                    # Record the assistant turn that requested the calls.
                    messages.append({
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
                    })

                    # Execute each call inside the workspace and feed results back.
                    for c in tool_calls:
                        if c["name"] in ("web_search", "web_fetch"):
                            result = web.dispatch(c["name"], c["arguments"])
                        else:
                            result = fs.dispatch(WORKSPACE_DIR, c["name"], c["arguments"])
                        await websocket.send_json({
                            "type": "tool",
                            "name": c["name"],
                            "args": c["arguments"],
                            "result": result,
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": result,
                        })

                # Restore the primary system prompt (grounding was injected for
                # this turn only, so it doesn't accumulate across the session).
                if _orig_system is not None:
                    messages[0]["content"] = _orig_system

                # Store only the clean final answer, not the reasoning.
                messages.append({"role": "assistant", "content": final_answer})
                session_manager.add_message("user", user_content)
                session_manager.add_message("assistant", final_answer)

                await websocket.send_json({
                    "type": "done",
                    "content": final_answer,
                })

            elif event.get("type") == "ask_sources":
                # Grounded Q&A over ingested resources, isolated from the chat/
                # writing history — this mirrors the proven `rag ask` path:
                # grounding rules + numbered sources ARE the system prompt, so
                # the model answers reliably from the resources and cites [n].
                question = event.get("content", "").strip()
                if not question:
                    continue
                await websocket.send_json({
                    "type": "status", "content": "Searching your resources…"
                })
                loop = asyncio.get_event_loop()
                chunks = await loop.run_in_executor(None, _grounded_chunks, question)
                if not chunks:
                    msg = ("No ingested resources matched that question. Add "
                           "PDF/TXT/MD/EPUB in the Resources panel first.")
                    await websocket.send_json({"type": "chunk", "content": msg, "full": msg})
                    await websocket.send_json({"type": "done", "content": msg})
                    continue

                names = []
                for c in chunks:
                    nm = (getattr(c, "source_file", "") or "source").rsplit("/", 1)[-1]
                    if nm not in names:
                        names.append(nm)
                await websocket.send_json({
                    "type": "tool",
                    "name": "grounded answer",
                    "args": {"query": question[:80]},
                    "result": "Sources: " + ", ".join(names),
                })

                from scribe.prompts import get_grounded_prompt
                gmsgs = [
                    {"role": "system", "content": get_grounded_prompt(chunks)},
                    {"role": "user", "content": question},
                ]
                answer = ""
                async for kind, payload in adapter.streaming_turn_async(gmsgs, tools=None):
                    if kind == "answer":
                        answer += payload
                        await websocket.send_json({
                            "type": "chunk", "content": payload, "full": answer
                        })
                    elif kind == "thinking":
                        await websocket.send_json({
                            "type": "thinking", "content": payload, "full": payload
                        })
                if not answer.strip():
                    answer = "The sources do not cover this."
                    await websocket.send_json({"type": "chunk", "content": answer, "full": answer})
                await websocket.send_json({"type": "done", "content": answer})

            elif event.get("type") == "clear":
                messages = [messages[0]]
                session_manager.end_session()
                session_manager.start_session(topic="web_chat")
                await websocket.send_json({"type": "cleared"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        session_manager.end_session()
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "content": str(e)
        })
        manager.disconnect(websocket)


@app.post("/api/chat")
async def chat(request: Request):
    """HTTP endpoint for non-streaming chat."""
    body = await request.json()
    message = body.get("message", "")

    messages = [{"role": "user", "content": message}]

    response = adapter.complete(messages)

    return {"response": response}


# --- Integrated terminal (PTY over WebSocket, VSCode-style) ---------------

# One-time tokens for the terminal WebSocket. A client mints a token over the
# authed HTTP channel and spends it to open the socket; it is single-use and
# short-lived, so a stale or replayed URL cannot reopen a shell.
_TERMINAL_TOKEN_TTL = 30.0
_terminal_tokens: dict[str, float] = {}


def _prune_terminal_tokens() -> None:
    now = time.time()
    for tok in [t for t, exp in _terminal_tokens.items() if exp < now]:
        _terminal_tokens.pop(tok, None)


def _mint_terminal_token() -> str:
    _prune_terminal_tokens()
    token = secrets.token_urlsafe(32)
    _terminal_tokens[token] = time.time() + _TERMINAL_TOKEN_TTL
    return token


def _consume_terminal_token(token: str | None) -> bool:
    """Validate and burn a one-time token. False if missing, unknown or expired."""
    if not token:
        return False
    _prune_terminal_tokens()
    expiry = _terminal_tokens.pop(token, None)
    return expiry is not None and expiry >= time.time()


def build_terminal_argv(shell: str, workspace, *, bwrap: bool, restricted: bool) -> list[str]:
    """
    Build the PTY command. With ``bwrap`` the shell runs inside a read-only-root
    bubblewrap container (the real barrier). Without it, ``restricted`` wraps a
    bash shell in restricted mode (rbash) to shrink the blast radius.
    """
    if bwrap:
        argv = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--bind", str(workspace), str(workspace),
            "--die-with-parent",
            "--chdir", str(workspace),
            shell,
        ]
        if "bash" in shell:
            argv.append("-l")
        return argv
    argv = [shell]
    if restricted and "bash" in shell:
        argv.append("--restricted")
    if "bash" in shell:
        argv.append("-l")
    return argv


@app.get("/api/terminal-token")
async def api_terminal_token(request: Request):
    """Mint a one-time token for opening the terminal WebSocket (authed)."""
    if not _is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"token": _mint_terminal_token()}


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Tell the PTY its window size so curses/editors render correctly."""
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass


@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    """Spawn a real login shell in a PTY and bridge it to xterm.js.

    Gated by the same PIN as the rest of the UI. The shell starts in the
    workspace; output is streamed as binary frames (avoids breaking multi-byte
    UTF-8), input/resize arrive as JSON text frames.
    """
    if not _is_authed(websocket):
        await websocket.close(code=1008)
        return
    # Reject cross-origin connections (CSWSH protection).
    if not _valid_ws_origin(websocket):
        security_log.warning(
            "ws/terminal rejected foreign origin=%s",
            websocket.headers.get("origin"),
        )
        await websocket.close(code=1008)
        return
    # Spend the one-time token minted over the authed HTTP channel.
    if not _consume_terminal_token(websocket.query_params.get("token")):
        security_log.warning("ws/terminal rejected missing/invalid one-time token")
        await websocket.close(code=1008)
        return
    await websocket.accept()
    security_log.info("terminal opened origin=%s", websocket.headers.get("origin", ""))

    if not _PTY_AVAILABLE:
        # Native Windows: no PTY. Tell the client instead of crashing.
        await websocket.send_bytes(
            b"\r\n\x1b[33mIntegrated terminal is not supported on this platform "
            b"(requires POSIX PTY: Linux, macOS or WSL).\x1b[0m\r\n"
        )
        await websocket.close()
        return

    from scribe.tools.sandbox import bwrap_available

    sandboxed = bwrap_available()
    if not sandboxed and config.get("scribe.web", "require_sandbox", default=False):
        # Fail closed: refuse an unsandboxed shell rather than degrade silently.
        await websocket.send_bytes(
            b"\r\n\x1b[31mTerminal refused: bubblewrap (bwrap) is required but not "
            b"available, and scribe.web.require_sandbox is set.\x1b[0m\r\n"
        )
        await websocket.close()
        return

    master_fd, slave_fd = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash")
    cmd = build_terminal_argv(
        shell,
        WORKSPACE_DIR,
        bwrap=sandboxed,
        restricted=bool(config.get("scribe.web", "restricted_shell", default=True)),
    )

    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(WORKSPACE_DIR),
        start_new_session=True,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    os.close(slave_fd)

    loop = asyncio.get_event_loop()
    out_queue: asyncio.Queue = asyncio.Queue()

    def _on_readable():
        try:
            data = os.read(master_fd, 65536)
        except OSError:
            data = b""
        if data:
            out_queue.put_nowait(data)
        else:
            loop.remove_reader(master_fd)
            out_queue.put_nowait(None)  # EOF

    loop.add_reader(master_fd, _on_readable)

    async def _pump_output():
        while True:
            data = await out_queue.get()
            if data is None:
                break
            try:
                await websocket.send_bytes(data)
            except Exception:
                break

    out_task = asyncio.create_task(_pump_output())

    try:
        while True:
            raw = await websocket.receive_text()
            event = json.loads(raw)
            if event.get("type") == "input":
                os.write(master_fd, event.get("data", "").encode())
            elif event.get("type") == "resize":
                _set_winsize(master_fd, int(event.get("rows", 24)), int(event.get("cols", 80)))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        security_log.info("terminal closed pid=%s", proc.pid)
        try:
            loop.remove_reader(master_fd)
        except (ValueError, OSError):
            pass
        out_task.cancel()
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGHUP)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.close(master_fd)
        except OSError:
            pass


def run(host: str = "127.0.0.1", port: int = 8765):
    """Run the web server.

    Binds to localhost by default: the web UI exposes a shell terminal
    (`/ws/terminal`), so it should not be reachable from the network unless the
    operator explicitly opts in with `--host 0.0.0.0`.
    """
    global _PIN
    _PIN = config.ensure_web_pin()

    if config.is_default_pin:
        security_log.warning(
            "Web UI PIN is the factory default '2020'. "
            "Change it in ~/.config/scribe/config.toml → [scribe.web] pin = \"...\" "
            "for security."
        )
    if host != "127.0.0.1":
        security_log.warning(
            "Web UI bound to %s — the integrated terminal is accessible "
            "over the network. Make sure the PIN is strong.", host
        )
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
