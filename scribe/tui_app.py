"""
Scribe — full-screen Textual UI (experimental, "Crush-like" layout).

Pure Python (Textual is built on Rich; no Node.js/Go). Launch with:

    scribe-llm chat --textual

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
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
    TextArea,
)

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.memory.sme import get_sme_service
from scribe.prompts import get_code_system_prompt, get_system_prompt
from scribe.session import SessionManager
from scribe.ui.console import (
    DEFAULT_THEME,
    PALETTES,
    gradient_text,
    hatch_bar,
    list_themes,
)


def dashboard_columns(
    config, skills: list[str], rag_ready: bool, sme_count: int
) -> list[tuple[str, list[tuple[bool, str]]]]:
    """
    Build the splash-dashboard columns (Crush's LSPs/MCPs/Skills). Pure so it is
    testable without a UI: returns (heading, [(enabled, label), ...]) per column.
    """
    tools = [
        (bool(config.get("scribe", "tools_enabled", default=True)), "file tools"),
        (True, "web_search · web_fetch"),
        (True, "bash (/code, sandboxed)"),
    ]
    skill_rows = [(True, s) for s in skills] or [(False, "none")]
    memory = [
        (rag_ready, "RAG library"),
        (sme_count > 0, f"SME memory ({sme_count})"),
    ]
    return [("Tools", tools), ("Skills", skill_rows), ("Memory", memory)]


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


class Composer(TextArea):
    """
    Multi-line prompt composer (Crush-style). Enter sends, Ctrl+J inserts a
    newline, and long/multi-line pastes collapse into a `[paste #N]` chip that
    is re-expanded on submit (so the model still gets everything).
    """

    PASTE_THRESHOLD = 200

    class Submitted(Message):
        """Posted when the user presses Enter to send."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pastes: list[str] = []
        self.show_line_numbers = False

    def on_paste(self, event: events.Paste) -> None:
        text = event.text
        if len(text) < self.PASTE_THRESHOLD and "\n" not in text.strip():
            return  # short single-line paste inserts normally
        self.pastes.append(text)
        self.insert(f"[paste #{len(self.pastes)}: {len(text)} chars]")
        event.stop()
        event.prevent_default()

    def expand(self, value: str) -> str:
        def repl(m: re.Match) -> str:
            idx = int(m.group(1)) - 1
            return self.pastes[idx] if 0 <= idx < len(self.pastes) else m.group(0)
        return _PASTE_RE.sub(repl, value)

    def clear_pastes(self) -> None:
        self.pastes.clear()

    async def _on_key(self, event: events.Key) -> None:
        # Enter sends; Ctrl+J is the explicit "newline" so multi-line still works.
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(self.text))
            return
        if event.key == "ctrl+j":
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)


class ScribeCommands(Provider):
    """Command-palette entries (Ctrl+P): backend, sessions, themes, code, clear."""

    def _commands(self):
        app = self.app
        items = [
            ("Model backend…", app.action_models),
            ("Resume session…", app.action_sessions),
            ("Toggle code mode", lambda: app._cmd_code(off=app.code_mode)),
            ("Clear chat", lambda: app.call_later(app._do_clear)),
            ("Quit Scribe", app.action_quit),
        ]
        for name in list_themes():
            items.append((f"Theme → {name}", (lambda n=name: app.apply_named_theme(n))))
        return items

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, callback in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback)


class ModelsScreen(ModalScreen):
    """Crush-style modal to switch the model backend (Ctrl+L).

    Local llama.cpp or any OpenAI-compatible API. The API key field is masked
    (password input); leaving it blank uses the local default or the
    SCRIBE_API_KEY environment variable, so the key need never be typed in.
    Returns a dict to the app on save, or None on cancel.
    """

    CSS = """
    ModelsScreen { align: center middle; }
    #dialog {
        width: 72; height: auto; padding: 1 2;
        border: round $accent; background: $panel;
    }
    #dialog Label { margin: 1 0 0 0; color: $text-muted; }
    #dialog Input { margin: 0; }
    #buttons { height: auto; margin-top: 1; align-horizontal: right; }
    #buttons Button { margin-left: 1; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, base_url: str, model: str, theme_name: str):
        super().__init__()
        self._base_url = base_url
        self._model = model
        self._theme_name = theme_name

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(gradient_text("✶ Model Backend", self._theme_name))
            yield Label("Base URL")
            yield Input(value=self._base_url, id="base", placeholder="http://127.0.0.1:18083/v1")
            yield Label("Model id (blank = local 'default')")
            yield Input(value="" if self._model == "default" else self._model,
                        id="model", placeholder="e.g. deepseek-chat")
            yield Label("API key (hidden; blank = local / SCRIBE_API_KEY)")
            yield Input(password=True, id="key", placeholder="sk-…")
            with Horizontal(id="buttons"):
                yield Button("Local", id="local")
                yield Button("Cancel", id="cancel")
                yield Button("Save API", id="save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#base", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        base = self.query_one("#base", Input).value.strip()
        if event.button.id == "local":
            self.dismiss({
                "kind": "local",
                "base_url": base or "http://127.0.0.1:18083/v1",
                "model": "default", "api_key": "not-needed", "tool_grammar": "auto",
            })
            return
        # Save API
        model = self.query_one("#model", Input).value.strip()
        key = self.query_one("#key", Input).value.strip() or "not-needed"
        if not base or not model:
            self.query_one("#dialog", Vertical).styles.border = ("round", "red")
            return
        self.dismiss({
            "kind": "api", "base_url": base, "model": model,
            "api_key": key, "tool_grammar": "off",
        })


class SessionsScreen(ModalScreen):
    """Crush-style modal to resume a past session (Ctrl+S).

    Lists recent sessions newest-first; selecting one returns its id to the app,
    which reloads its transcript. Returns the chosen session id, or None.
    """

    CSS = """
    SessionsScreen { align: center middle; }
    #dialog {
        width: 80; height: auto; max-height: 80%; padding: 1 2;
        border: round $accent; background: $panel;
    }
    #dialog ListView { height: auto; max-height: 20; margin-top: 1; background: $panel; }
    #dialog ListItem { padding: 0 1; }
    #hint { color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, sessions: list[tuple[str, str]], theme_name: str):
        super().__init__()
        self._sessions = sessions
        self._theme_name = theme_name

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(gradient_text("✶ Resume session", self._theme_name))
            if self._sessions:
                lv = ListView(
                    *[ListItem(Label(label), id=f"s_{sid}") for sid, label in self._sessions]
                )
                yield lv
                yield Static("Enter to resume · Esc to cancel", id="hint")
            else:
                yield Static("No saved sessions yet.", id="hint")

    def on_mount(self) -> None:
        if self._sessions:
            self.query_one(ListView).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        sid = (event.item.id or "")[2:]  # strip the "s_" prefix
        self.dismiss(sid or None)


class ScribeApp(App):
    """Full-screen Textual chat for Scribe."""

    COMMANDS = App.COMMANDS | {ScribeCommands}

    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 1; padding: 0 1; }
    #chat { height: 1fr; padding: 1 2; }
    #chat .msg-user { margin: 0 0 1 0; }
    #chat .msg-scribe-head { margin: 0; padding: 0; }
    #chat .msg-scribe { margin: 0 0 1 0; padding: 0; background: transparent; }
    #chat .thinking { margin: 0 0 1 0; color: $text-muted; }
    #chat .splash { margin: 0 0 1 0; }
    #prompt { height: auto; min-height: 3; max-height: 12; margin: 0 1; }
    #status { height: 1; }
    #hints { height: 1; padding: 0 1; }
    """

    BINDINGS = [
        # Two-step exit: Ctrl+D arms it, Ctrl+C confirms. Priority so they fire
        # even while the composer has focus.
        Binding("ctrl+d", "arm_exit", "Exit", priority=True),
        Binding("ctrl+c", "confirm_exit", "Quit", priority=True),
        ("ctrl+l", "models", "Models"),
        ("ctrl+s", "sessions", "Sessions"),
    ]

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
        self._exit_armed = False

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
            yield Composer(id="prompt")
            yield Static(id="status")
            yield Static(id="hints")

    def on_mount(self) -> None:
        self.session.start_session(topic="textual_chat")
        self._apply_theme()
        self._set_topbar()
        self._refresh_status()
        self._set_hints()
        self._show_splash()
        self.query_one("#prompt", Composer).focus()

    def _set_hints(self) -> None:
        """Persistent Crush-style keybind hint bar."""
        p = self._palette()
        hints = Text(no_wrap=True, overflow="ellipsis", end="")
        for i, (key, what) in enumerate(
            [("/", "komande"), ("^L", "modeli"), ("^S", "sesije"),
             ("^J", "novi red"), ("^D ^C", "izlaz")]
        ):
            if i:
                hints.append("  ·  ", style="dim")
            hints.append(key, style=f"bold {p['accent']}")
            hints.append(f" {what}", style=p["fg"])
        try:
            self.query_one("#hints", Static).update(hints)
        except Exception:
            pass

    def _show_splash(self) -> None:
        """Crush-style launch dashboard: cwd, model chip, capability columns."""
        from rich.table import Table

        p = self._palette()
        body = Text()
        body.append("  ")
        body.append_text(gradient_text("✶ SCRIBE", self.theme_name))
        body.append(f"   {self.workspace}\n", style="dim")
        body.append_text(hatch_bar("", self.theme_name, width=46))
        body.append("\n\n")
        think = "off" if not self.config.reasoning else "on"
        body.append("  ◇ ", style=p["secondary"])
        body.append(self.adapter.get_model_name(), style=f"bold {p['accent']}")
        body.append(f"  ·  reasoning: {think}\n", style="dim")

        skills = []
        try:
            from scribe.skills_executor import SkillsRegistry
            skills = [s.name for s in SkillsRegistry().list()][:8]
        except Exception:
            pass
        rag_ready = bool(self.config.get("scribe", "tools_enabled", default=True))
        try:
            sme_count = self.sme.count()
        except Exception:
            sme_count = 0

        cols = dashboard_columns(self.config, skills, rag_ready, sme_count)
        table = Table.grid(padding=(0, 3))
        for _ in cols:
            table.add_column()
        headers = [Text(h, style=f"bold {p['secondary']}") for h, _ in cols]
        table.add_row(*headers)
        depth = max(len(rows) for _, rows in cols)
        for r in range(depth):
            cells = []
            for _, rows in cols:
                if r < len(rows):
                    on, label = rows[r]
                    cell = Text()
                    cell.append("● " if on else "○ ", style=p["success"] if on else "dim")
                    cell.append(label, style=p["fg"] if on else "dim")
                    cells.append(cell)
                else:
                    cells.append(Text(""))
            table.add_row(*cells)

        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(body, classes="splash"))
        chat.mount(Static(table, classes="splash"))

    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Typing just `/` in an empty prompt opens the command palette (Crush)."""
        composer = self.query_one("#prompt", Composer)
        if self._exit_armed and composer.text:
            self._disarm_exit()  # started typing again — cancel the pending exit
        if composer.text == "/":
            composer.text = ""
            self.action_command_palette()

    # ------------------------------------------------------------------- exit
    def action_arm_exit(self) -> None:
        """Ctrl+D: arm the exit; the actual quit happens on Ctrl+C."""
        self._exit_armed = True
        p = self._palette()
        msg = Text()
        msg.append(" ⏻ Izlazak spreman — pritisni ", style=f"bold {p['warning']}")
        msg.append("Ctrl+C", style=f"bold {p['accent']}")
        msg.append(" za izlaz  ·  bilo šta drugo otkazuje", style=f"bold {p['warning']}")
        try:
            self.query_one("#hints", Static).update(msg)
        except Exception:
            pass

    def action_confirm_exit(self) -> None:
        """Ctrl+C: quit only when the exit was armed with Ctrl+D first."""
        if self._exit_armed:
            self.exit()
            return
        p = self._palette()
        hint = Text()
        hint.append(" Pritisni ", style="dim")
        hint.append("Ctrl+D", style=f"bold {p['accent']}")
        hint.append(" pa ", style="dim")
        hint.append("Ctrl+C", style=f"bold {p['accent']}")
        hint.append(" za izlaz", style="dim")
        try:
            self.query_one("#hints", Static).update(hint)
        except Exception:
            pass

    def _disarm_exit(self) -> None:
        self._exit_armed = False
        self._set_hints()

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
        inp = self.query_one("#prompt", Composer)
        inp.styles.border = ("round", p["accent"])
        self._set_topbar()
        self._refresh_status()

    def _set_topbar(self) -> None:
        model = self.adapter.get_model_name()
        p = self._palette()
        bar = Text(no_wrap=True, overflow="ellipsis", end="")
        bar.append(" ")
        # Gradient brand wordmark (Crush-style primary→secondary).
        bar.append_text(gradient_text("✶ SCRIBE", self.theme_name))
        bar.append("  ·  ◇ ", style=p["bg"])
        bar.append(model, style=f"bold {p['bg']}")
        think = "off" if not self.config.reasoning else "on"
        bar.append(f"  ·  think:{think}", style=p["bg"])
        if self.code_mode:
            bar.append("  ·  ⌘ CODE", style=f"bold {p['bg']}")
        self.query_one("#topbar", Static).update(bar)

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
    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        if self._exit_armed:
            self._disarm_exit()  # sending a message clearly means "don't exit"
        inp = self.query_one("#prompt", Composer)
        shown = event.value.strip()          # may contain [paste #N] chips
        full = inp.expand(shown)             # chips expanded to real text
        inp.text = ""
        inp.clear_pastes()
        if not shown or self._busy:
            return
        if shown.startswith("/"):
            await self._handle_command(shown)
            return

        await self._add_user(shown)          # show the collapsed chip in chat
        self.messages.append({"role": "user", "content": full})  # model gets all

        chat = self.query_one("#chat", VerticalScroll)
        p = self._palette()
        await chat.mount(
            Static(Text("✦ Scribe", style=f"bold {p['accent']}"), classes="msg-scribe-head")
        )
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
        body.append("▌ You\n", style=f"bold {p['user']}")
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
            await self._do_clear()
        elif cmd == "/theme":
            await self._cmd_theme(arg)
        elif cmd in ("/code", "/chat"):
            self._cmd_code(off=(cmd == "/chat" or arg.lower() in ("off", "exit")))
        elif cmd == "/help":
            await self._note(
                "Commands: /theme NAME · /code · /chat · /clear · /quit\n"
                "Keys: Ctrl+L model backend · Ctrl+P command palette\n"
                f"Themes: {', '.join(list_themes())}"
            )
        else:
            await self._note(f"Unknown command: {cmd}")

    async def _do_clear(self) -> None:
        await self.query_one("#chat", VerticalScroll).remove_children()
        self.messages = self.messages[:1]
        self._refresh_status()

    def apply_named_theme(self, name: str) -> None:
        """Switch theme by name (used by the command palette)."""
        if name not in list_themes():
            return
        self.theme_name = name
        self._apply_theme()
        try:
            self.config.save_value("scribe.ui", "theme", name)
        except Exception:
            pass

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

    # --------------------------------------------------------------- models
    def action_models(self) -> None:
        """Open the model-backend modal (Ctrl+L)."""
        if self._busy:
            return

        def _applied(result: dict | None) -> None:
            if not result:
                return
            try:
                self.config.save_value("scribe", "base_url", result["base_url"])
                self.config.save_value("scribe", "model", result["model"])
                self.config.save_value("scribe", "api_key", result["api_key"])
                self.config.save_value("scribe", "tool_grammar", result["tool_grammar"])
            except Exception as e:
                self.call_later(self._note, f"⚠ Could not save backend: {e}")
                return
            self.adapter = LLMAdapter.from_config(self.config)
            self._set_topbar()
            self._refresh_status()
            self.call_later(self._note, f"✦ Backend → {result['base_url']}")

        self.push_screen(
            ModelsScreen(self.config.base_url, self.config.model, self.theme_name),
            _applied,
        )

    # ------------------------------------------------------------- sessions
    def action_sessions(self) -> None:
        """Open the resume-session modal (Ctrl+S)."""
        if self._busy:
            return
        rows: list[tuple[str, str]] = []
        for sid in self.session.list_sessions()[:30]:
            cp = self.session.load_session(sid)
            if cp is None:
                continue
            n = len([m for m in cp.messages if m.get("role") in ("user", "assistant")])
            rows.append((sid, f"{sid}   ·   {cp.topic or '—'}   ·   {n} turns"))
        self.push_screen(SessionsScreen(rows, self.theme_name), self._resume_session)

    def _resume_session(self, sid: str | None) -> None:
        if not sid:
            return
        cp = self.session.load_session(sid)
        if cp is None:
            return
        restored = [m for m in cp.messages if m.get("role") in ("user", "assistant")]
        self.messages = self.messages[:1] + restored
        self.call_later(self._repaint_chat, sid)

    async def _repaint_chat(self, sid: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        await chat.remove_children()
        p = self._palette()
        for m in self.messages[1:]:
            if m.get("role") == "user":
                await self._add_user(m.get("content", ""))
            elif m.get("role") == "assistant":
                await chat.mount(
                    Static(Text("✦ Scribe", style=f"bold {p['accent']}"),
                           classes="msg-scribe-head")
                )
                await chat.mount(Markdown(m.get("content", ""), classes="msg-scribe"))
        await self._note(f"↩ Resumed session {sid}")
        chat.scroll_end()
        self._refresh_status()

    async def _note(self, text: str) -> None:
        p = self._palette()
        await self.query_one("#chat", VerticalScroll).mount(
            Static(Text(text, style=p["secondary"]), classes="msg-user")
        )
        self.query_one("#chat", VerticalScroll).scroll_end()


def run_app(config: ScribeConfig | None = None) -> None:
    """Entry point for `scribe-llm chat --textual`."""
    ScribeApp(config).run()
