"""
Scribe Web - FastAPI web server with streaming chat UI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.memory.sme import get_sme_service, recall_previous_session
from scribe.prompts import get_system_prompt
from scribe.session import SessionManager
from scribe.skills_executor import SkillsExecutor
from scribe.tools import fs

app = FastAPI(title="Scribe", description="Autonomous Research & Writing Agent")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

config = ScribeConfig()
adapter = LLMAdapter(base_url=config.base_url, model=config.model, enable_thinking=config.reasoning)
session_manager = SessionManager(config)
sme_service = get_sme_service()
skills_executor = SkillsExecutor()

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
    """Serve the main chat UI."""
    session_summary = recall_previous_session(sme_service)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "session_summary": session_summary,
        "model_name": adapter.get_model_name(),
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
        ),
    }]

    session_manager.start_session(topic="web_chat")

    try:
        while True:
            data = await websocket.receive_text()
            event = json.loads(data)

            if event.get("type") == "message":
                user_content = event.get("content", "").strip()
                if not user_content:
                    continue

                messages.append({"role": "user", "content": user_content})

                await websocket.send_json({
                    "type": "status",
                    "content": "Generating..."
                })

                tools = fs.TOOL_SCHEMAS if config.tools_enabled else None
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


def run(host: str = "0.0.0.0", port: int = 8765):
    """Run the web server."""
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
