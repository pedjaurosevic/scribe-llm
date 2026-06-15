"""
Scribe Web - FastAPI web server with streaming chat UI.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import pty
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
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
async def require_pin(request: Request, call_next):
    """Block every HTTP route until the PIN cookie is present and valid."""
    open_paths = ("/login", "/static", "/favicon.ico")
    if _PIN and not request.url.path.startswith(open_paths) and not _is_authed(request):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_form():
    """Serve the PIN entry page."""
    return LOGIN_HTML.format(error="")


@app.post("/login", response_class=HTMLResponse)
async def login_submit(pin: str = Form("")):
    """Check the PIN; on success set the auth cookie and enter the UI."""
    if hmac.compare_digest(pin, _PIN):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            AUTH_COOKIE,
            _expected_token(),
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )
        return resp
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
    return templates.TemplateResponse("editor.html", {
        "request": request,
        "model_name": adapter.get_model_name(),
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
        return PlainTextResponse("pandoc nije instaliran na sistemu.", status_code=501)

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
        return PlainTextResponse(f"pandoc greška: {msg}", status_code=500)

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


def _compose_writing_prompt(instruction: str, doc_context: str, mode: str) -> str:
    """Wrap the user's command with the current document so the model writes
    content meant to be inserted straight into the editor.

    The model answer is streamed verbatim into the document, so we ask for the
    raw markdown body only — no chat-style preamble, no meta commentary.
    """
    unit = "poglavlja" if mode == "book" else "dokumenta"
    parts = []
    if doc_context.strip():
        parts.append(f"[Trenutni sadržaj {unit}]:\n{doc_context.strip()}")
    parts.append(f"[Zadatak]: {instruction}")
    parts.append(
        "Odgovori ISKLJUČIVO tekstom (markdown) koji treba da stoji u "
        f"{unit}, bez uvodnih fraza, pozdrava ili komentara o tome šta radiš."
    )
    return "\n\n".join(parts)


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for streaming chat."""
    # HTTP middleware does not cover websockets, so gate the cookie here.
    if not _is_authed(websocket):
        await websocket.close(code=1008)  # policy violation
        return

    await manager.connect(websocket)

    messages = [{
        "role": "system",
        "content": get_system_prompt(
            config.reasoning,
            workspace=str(WORKSPACE_DIR),
            max_thinking_words=config.max_thinking_words,
            mode=config.reasoning_mode,
        ),
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
                        note = "✓ Reasoning ON — model razmišlja pre odgovora."
                    else:
                        directive = (
                            "Reasoning is now OFF. Do NOT produce a <think> "
                            "block or any step-by-step reasoning. Answer "
                            "directly and concisely in the user's language."
                        )
                        note = "→ Reasoning OFF — model odgovara direktno."
                    messages.append({"role": "system", "content": directive})
                    await websocket.send_json(
                        {"type": "chunk", "content": note, "full": note}
                    )
                    await websocket.send_json({"type": "done", "content": note})
                    continue

                doc_context = event.get("doc_context", "")
                mode = event.get("mode", "free")
                if doc_context or mode == "book":
                    model_input = _compose_writing_prompt(user_content, doc_context, mode)
                else:
                    model_input = user_content
                messages.append({"role": "user", "content": model_input})

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

                # Store only the clean final answer, not the reasoning.
                messages.append({"role": "assistant", "content": final_answer})
                session_manager.add_message("user", user_content)
                session_manager.add_message("assistant", final_answer)

                await websocket.send_json({
                    "type": "done",
                    "content": final_answer,
                })

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
    await websocket.accept()

    master_fd, slave_fd = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash")
    proc = subprocess.Popen(
        [shell, "-l"],
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


def run(host: str = "0.0.0.0", port: int = 8765):
    """Run the web server."""
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
