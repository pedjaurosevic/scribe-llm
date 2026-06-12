"""
Scribe — full-screen Textual UI (experimental, "Crush-like" layout).

Pure Python (Textual is built on Rich; no Node.js/Go). Launch with:

    scribe chat --textual

The classic Rich/scroll UI in `tui.py` stays the default and keeps the full
tool-calling /code flow; this app focuses on the look: a docked title bar, a
scrolling chat, an input box, and a single-line themed status footer.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from rich.cells import cell_len
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Markdown, Static

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.memory.sme import get_sme_service
from scribe.prompts import get_code_system_prompt, get_system_prompt
from scribe.session import SessionManager
from scribe.ui.console import DEFAULT_THEME, PALETTES, list_themes


def build_status_line(
    width: int,
    model: str,
    tok_s: float,
    used_k: float,
    total_k: int,
    pct: float,
    code_mode: bool,
    palette: dict[str, str],
) -> Text:
    """
    Build the footer status line so it ALWAYS fits on one row.

    The pills (optional ⌘ CODE, tok/s, ctx) are kept whole; only the model name
    is shortened (with an ellipsis) to whatever space is left. If even the pills
    do not fit, the model pill is dropped and the line is cropped as a last
    resort. Returns a no-wrap Rich Text.
    """
    bg = palette["bg"]

    def pill(label: str, color: str) -> tuple[str, str]:
        return f" {label} ", f"bold {bg} on {color}"

    code_label, code_style = pill("⌘ CODE", palette["warning"])
    speed_label, speed_style = pill(f"{tok_s:.1f} tok/s", palette["success"])
    ctx_label, ctx_style = pill(
        f"ctx {used_k:.1f}k/{total_k}k {pct:.0f}%", palette["secondary"]
    )

    lead = 2
    sep = 1
    code_w = (cell_len(code_label) + sep) if code_mode else 0

    # Width consumed by everything except the model name's own characters:
    # leading margin + (code pill) + model pill padding (2) + sep + speed + sep + ctx.
    non_model = (
        lead + code_w + 2 + sep + cell_len(speed_label) + sep + cell_len(ctx_label)
    )
    avail = width - non_model

    show_model = avail >= 1
    name = model
    if show_model and cell_len(name) > avail:
        # Reserve one cell for the ellipsis.
        cut = max(0, avail - 1)
        name = name[:cut] + "…" if cut > 0 else "…"

    t = Text(no_wrap=True, overflow="crop", end="")
    t.append(" " * lead)
    if code_mode:
        t.append(code_label, style=code_style)
        t.append(" ")
    if show_model:
        m_label, m_style = pill(name, palette["accent"])
        t.append(m_label, style=m_style)
        t.append(" ")
    t.append(speed_label, style=speed_style)
    t.append(" ")
    t.append(ctx_label, style=ctx_style)
    # Hard guarantee: never exceed the row, even on absurdly narrow terminals.
    t.truncate(max(0, width), overflow="crop")
    return t


_PASTE_RE = re.compile(r"\[paste #(\d+): \d+ chars\]")


class PasteInput(Input):
    """
    Input that collapses long/multi-line pastes into a `[paste #N: M chars]`
    chip (like Codex / Claude Code) instead of dumping the whole blob.

    The full text is kept in ``pastes`` and re-expanded on submit, so the model
    still receives everything while the input and chat stay readable.
    """

    PASTE_THRESHOLD = 200  # chars; multi-line pastes always collapse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pastes: list[str] = []

    def _should_collapse(self, text: str) -> bool:
        return len(text) >= self.PASTE_THRESHOLD or "\n" in text.strip()

    def on_paste(self, event: events.Paste) -> None:
        text = event.text
        if not self._should_collapse(text):
            return  # short single-line paste: let Input insert it normally
        self.pastes.append(text)
        chip = f"[paste #{len(self.pastes)}: {len(text)} chars]"
        try:
            self.insert_text_at_cursor(chip)
        except Exception:
            self.value += chip
        event.stop()
        event.prevent_default()

    def expand(self, value: str) -> str:
        """Replace every chip with its stored full text."""
        def repl(m: re.Match) -> str:
            idx = int(m.group(1)) - 1
            return self.pastes[idx] if 0 <= idx < len(self.pastes) else m.group(0)
        return _PASTE_RE.sub(repl, value)

    def clear_pastes(self) -> None:
        self.pastes.clear()


class ScribeApp(App):
    """Full-screen Textual chat for Scribe."""

    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 1; padding: 0 1; }
    #chat { height: 1fr; padding: 1 2; }
    #chat .msg-user { margin: 0 0 1 0; }
    #chat .msg-scribe { margin: 0 0 1 0; padding: 0; background: transparent; }
    #chat .thinking { margin: 0 0 1 0; color: $text-muted; }
    Input#prompt { height: 3; margin: 0 1; }
    #status { height: 1; }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, config: ScribeConfig | None = None):
        super().__init__()
        self.config = config or ScribeConfig()
        self.theme_name = self.config.theme
        if self.theme_name not in list_themes():
            self.theme_name = DEFAULT_THEME

        self.adapter = LLMAdapter.from_config(self.config)
        self.session = SessionManager(self.config)
        self.sme = get_sme_service()

        self.workspace = Path(self.config.workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.code_mode = False
        self._last_tok_s = 0.0

        self.messages: list[dict] = [{
            "role": "system",
            "content": get_system_prompt(
                self.config.reasoning,
                workspace=str(self.workspace),
                max_thinking_words=self.config.max_thinking_words,
                mode=self.config.reasoning_mode,
            ),
        }]

        # Widgets for the in-flight turn.
        self._cur_md: Markdown | None = None
        self._cur_thinking: Static | None = None
        self._busy = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="topbar")
            yield VerticalScroll(id="chat")
            yield PasteInput(placeholder="Pitaj nešto…  (/help, /theme, /code, /quit)", id="prompt")
            yield Static(id="status")

    def on_mount(self) -> None:
        self.session.start_session(topic="textual_chat")
        self._apply_theme()
        self._set_topbar()
        self._refresh_status()
        self.query_one("#prompt", Input).focus()

    # ------------------------------------------------------------------- theme
    def _palette(self) -> dict[str, str]:
        return PALETTES.get(self.theme_name, PALETTES[DEFAULT_THEME])

    def _apply_theme(self) -> None:
        p = self._palette()
        self.screen.styles.background = p["bg"]
        self.screen.styles.color = p["fg"]
        top = self.query_one("#topbar", Static)
        top.styles.background = p["accent"]
        top.styles.color = p["bg"]
        inp = self.query_one("#prompt", Input)
        inp.styles.border = ("round", p["accent"])
        self._set_topbar()
        self._refresh_status()

    def _set_topbar(self) -> None:
        model = self.adapter.get_model_name()
        mode = "  ·  ⌘ CODE" if self.code_mode else ""
        self.query_one("#topbar", Static).update(f" ✶ Scribe   ·   {model}{mode}")

    def _refresh_status(self) -> None:
        try:
            status = self.query_one("#status", Static)
        except Exception:
            return
        width = status.size.width or 80
        used = self._ctx_tokens()
        total = self.config.max_context_tokens or 1
        line = build_status_line(
            width=width,
            model=self.adapter.get_model_name(),
            tok_s=self._last_tok_s,
            used_k=used / 1000,
            total_k=total // 1000,
            pct=used / total * 100,
            code_mode=self.code_mode,
            palette=self._palette(),
        )
        status.update(line)

    def on_resize(self, event) -> None:
        self._refresh_status()

    def _ctx_tokens(self) -> int:
        chars = sum(len(m.get("content") or "") for m in self.messages)
        return chars // 4

    # ------------------------------------------------------------------- input
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        inp = self.query_one("#prompt", PasteInput)
        shown = event.value.strip()          # may contain [paste #N] chips
        full = inp.expand(shown)             # chips expanded to real text
        inp.value = ""
        inp.clear_pastes()
        if not shown or self._busy:
            return
        if shown.startswith("/"):
            await self._handle_command(shown)
            return

        await self._add_user(shown)          # show the collapsed chip in chat
        self.messages.append({"role": "user", "content": full})  # model gets all

        chat = self.query_one("#chat", VerticalScroll)
        self._cur_thinking = Static("💭 razmišlja…", classes="thinking")
        await chat.mount(self._cur_thinking)
        self._cur_md = Markdown("", classes="msg-scribe")
        await chat.mount(self._cur_md)
        chat.scroll_end()

        self._busy = True
        self._run_turn()

    async def _add_user(self, text: str) -> None:
        p = self._palette()
        body = Text()
        body.append("› ", style=f"bold {p['user']}")
        body.append(text)
        await self.query_one("#chat", VerticalScroll).mount(
            Static(body, classes="msg-user")
        )

    # --------------------------------------------------------------- streaming
    @work(thread=True, exclusive=True)
    def _run_turn(self) -> None:
        """Stream one reply in a thread so the UI stays responsive."""
        thinking = ""
        answer = ""
        tokens = 0
        t0 = time.perf_counter()
        try:
            for kind, chunk in self.adapter.streaming_events(self.messages):
                tokens += 1
                if kind == "thinking":
                    thinking += chunk
                    self.call_from_thread(self._on_thinking, thinking)
                else:
                    answer += chunk
                    self.call_from_thread(self._on_answer, answer)
        except Exception as e:  # surface errors in the chat
            self.call_from_thread(self._on_answer, f"**Error:** {e}")
            answer = answer or f"Error: {e}"

        dt = max(time.perf_counter() - t0, 1e-6)
        self.call_from_thread(self._finish_turn, answer, thinking, tokens / dt)

    def _on_thinking(self, thinking: str) -> None:
        if self._cur_thinking is not None:
            tail = " ".join(thinking.split())[-100:]
            self._cur_thinking.update(f"💭 {tail}")
            self.query_one("#chat", VerticalScroll).scroll_end()

    def _on_answer(self, answer: str) -> None:
        # First answer token: drop the thinking marquee.
        if self._cur_thinking is not None:
            self._cur_thinking.remove()
            self._cur_thinking = None
        if self._cur_md is not None:
            self._cur_md.update(answer)
            self.query_one("#chat", VerticalScroll).scroll_end()

    def _finish_turn(self, answer: str, thinking: str, tok_s: float) -> None:
        if self._cur_thinking is not None:
            self._cur_thinking.remove()
            self._cur_thinking = None
        # Safety net: if the model only produced thinking, show it as the answer.
        if not answer.strip() and thinking.strip() and self._cur_md is not None:
            self._cur_md.update(thinking)
            answer = thinking
        self._last_tok_s = tok_s
        if answer.strip():
            self.messages.append({"role": "assistant", "content": answer})
            self.session.add_message("assistant", answer)
        self._cur_md = None
        self._busy = False
        self._refresh_status()

    # -------------------------------------------------------------- commands
    async def _handle_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            self.exit()
        elif cmd == "/clear":
            await self.query_one("#chat", VerticalScroll).remove_children()
            self.messages = self.messages[:1]
            self._refresh_status()
        elif cmd == "/theme":
            await self._cmd_theme(arg)
        elif cmd in ("/code", "/chat"):
            self._cmd_code(off=(cmd == "/chat" or arg.lower() in ("off", "exit")))
        elif cmd == "/help":
            await self._note(
                "Commands: /theme NAME · /code · /chat · /clear · /quit\n"
                f"Themes: {', '.join(list_themes())}"
            )
        else:
            await self._note(f"Unknown command: {cmd}")

    async def _cmd_theme(self, name: str) -> None:
        if not name:
            await self._note("Themes: " + ", ".join(
                (f"[{t}]" if t == self.theme_name else t) for t in list_themes()
            ))
            return
        if name not in list_themes():
            await self._note(f"Unknown theme: {name}")
            return
        self.theme_name = name
        self._apply_theme()
        try:
            self.config.save_value("scribe.ui", "theme", name)
        except Exception:
            pass
        await self._note(f"Theme → {name}")

    def _cmd_code(self, off: bool) -> None:
        if off:
            if self.code_mode:
                self.code_mode = False
                self.messages.append({
                    "role": "system",
                    "content": "Code mode OFF. You are Scribe again; keep answers short.",
                })
        else:
            if not self.code_mode:
                self.code_mode = True
                self.messages.append({
                    "role": "system",
                    "content": get_code_system_prompt(
                        str(Path.cwd()),
                        max_thinking_words=self.config.max_thinking_words,
                    ),
                })
        self._set_topbar()
        self._refresh_status()

    async def _note(self, text: str) -> None:
        p = self._palette()
        await self.query_one("#chat", VerticalScroll).mount(
            Static(Text(text, style=p["secondary"]), classes="msg-user")
        )
        self.query_one("#chat", VerticalScroll).scroll_end()


def run_app(config: ScribeConfig | None = None) -> None:
    """Entry point for `scribe chat --textual`."""
    ScribeApp(config).run()
