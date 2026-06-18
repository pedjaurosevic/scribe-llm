"""
Scribe TUI - Beautiful Rich-based terminal interface.

Main chat interface with:
- Streaming responses with progress
- Session auto-recall via SME
- Skills system integration
- Language game indicators
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Enables GNU readline line editing for input() (arrow keys, and correct
# backspace/cursor across wrapped lines once the prompt's color codes are
# hidden from readline's width math — see _get_input).
try:
    import readline  # noqa: F401
except ImportError:
    readline = None

from rich.box import ROUNDED
from rich.cells import cell_len
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.memory.sme import get_sme_service, recall_previous_session
from scribe.prompts import get_code_system_prompt, get_system_prompt
from scribe.session import SessionManager, session_tag
from scribe.skills_executor import SkillsExecutor
from scribe.ui.console import get_console, list_themes, theme_accent
from scribe.ui.logo import logo_lines


class ScribeTUI:
    """
    Main TUI for Scribe chat.

    Features:
    - Rich console with Gruvbox theme
    - Streaming responses with progress
    - Session auto-recall
    - Skills system integration
    """

    def __init__(self, config: ScribeConfig | None = None, resume_tag: str | None = None):
        """Initialize Scribe TUI."""
        self.config = config or ScribeConfig()
        self._resumed = False
        self._resume_error: str | None = None
        self.theme_name = self.config.theme
        if self.theme_name not in list_themes():
            self.theme_name = "gruvbox-dark"
        self.console = get_console(
            theme=self.theme_name,
            force_terminal=True,
            markup=True,
        )
        self.adapter = LLMAdapter.from_config(self.config)
        self.session = SessionManager(self.config)
        self.sme = get_sme_service()
        self.skills = SkillsExecutor()
        self.messages: list[dict[str, str]] = []
        self.running = False

        # When False, file tools are sandboxed to the workspace. Toggled via
        # the /permissions command (with an explicit confirmation).
        self.allow_outside = False

        # /code mode: Scribe Code — a terminal expert with full bash access.
        # Commands run in code_cwd (where Scribe was launched), each confirmed.
        self.code_mode = False
        self.code_cwd = Path.cwd()

        # Whether the model reasons before answering. Toggled live with
        # /reasoning; applies to both normal and code mode.
        self.reasoning = self.config.reasoning

        # Generation speed of the last reply, for the status line.
        self._last_tok_s = 0.0

        # Local working directory Scribe operates in.
        self.workspace = Path(self.config.workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)

        # WorldModel keeps the agent's identity stable across sessions; its
        # live environment is refreshed each launch but the persona persists.
        from scribe.worldmodel import load_worldmodel, save_worldmodel

        self.worldmodel = load_worldmodel()
        self.worldmodel.environment.update({
            "workspace": str(self.workspace),
            "server": self.config.base_url,
            "model": self.config.model,
        })
        try:
            save_worldmodel(self.worldmodel)
        except OSError:
            pass

        self.messages.append({
            "role": "system",
            "content": get_system_prompt(
                self.config.reasoning,
                workspace=str(self.workspace),
                max_thinking_words=self.config.max_thinking_words,
                mode=self.config.reasoning_mode,
                worldmodel=self.worldmodel,
            ),
        })

        if resume_tag:
            self._resume_from(resume_tag)

    def _resume_from(self, tag: str) -> None:
        """Reload a past session (by tag, or the most recent) and continue it."""
        if tag.lstrip("#").lower() in ("last", "__last__", ""):
            cp = self.session.get_last_session()
        else:
            sid = self.session.find_by_tag(tag)
            cp = self.session.load_session(sid) if sid else None
        if not cp:
            self._resume_error = tag
            return

        restored = [m for m in cp.messages if m.get("role") in ("user", "assistant")]
        self.messages.extend(restored)

        # Keep the SAME session id so its resume tag stays stable.
        cp.status = "active"
        self.session.current_session = cp
        self._resumed = True

    def run(self):
        """Run the interactive chat loop."""
        self.running = True

        self._show_welcome()
        if self._resume_error:
            self.console.print(
                f"[warning]⚠[/warning] No session found for tag "
                f"[accent]#{self._resume_error}[/accent] — starting fresh.\n"
            )
        if self._resumed:
            self._show_resume_banner()
        else:
            self._recall_session()

        while self.running:
            try:
                user_input = self._get_input()
                if user_input is None:
                    break

                if user_input.startswith("/"):
                    self._handle_command(user_input)
                elif user_input.strip():
                    self._chat(user_input)

            except (KeyboardInterrupt, EOFError):
                self._handle_exit()
                break

        self._cleanup()

    def _print_logo(self, small: bool = False):
        """Print the Scribe ASCII logo in the theme accent, with a 2-col margin.

        Rendered via styled Text (not markup) because the art contains
        backslashes that would otherwise escape Rich markup brackets.
        """
        self.console.print()
        for line in logo_lines(small=small):
            self.console.print(Text(f"  {line}", style="accent"))
        self.console.print()

    def _show_welcome(self):
        """Show welcome message and system status."""
        self._print_logo()
        self.console.print(
            "  [dim]Autonomous Research & Writing Agent[/dim]"
        )
        self.console.print()

        if self.adapter.is_healthy():
            model_name = self.adapter.get_model_name()
            self.console.print(f"[success]✓[/success] Connected to [green]{model_name}[/green]")
        else:
            self.console.print("[error]✗[/error] LLM server not reachable")

        if self.sme:
            count = self.sme.count()
            self.console.print(f"[info]ℹ[/info] Memory: [dim]{count} entries[/dim]")
        else:
            self.console.print("[warning]⚠[/warning] Memory: not available")

        self.console.print(
            "  [dim]/help for commands · /models to switch backend (llama.cpp or API key)[/dim]"
        )
        self.console.print()

    def _show_resume_banner(self):
        """Announce a resumed session and how many turns were restored."""
        cp = self.session.current_session
        turns = len([m for m in self.messages if m.get("role") in ("user", "assistant")])
        self.console.print(Panel(
            f"[success]✓[/success] Resumed session [accent]#{session_tag(cp.session_id)}[/accent] "
            f"[dim]({cp.topic})[/dim]\n"
            f"[dim]{turns} messages restored — continue where you left off.[/dim]",
            border_style="scribe",
            box=ROUNDED,
            padding=(0, 2),
        ))
        self.console.print()

    def _recall_session(self):
        """Recall previous session using SME."""
        summary = recall_previous_session(self.sme)

        if "No previous session found" not in summary:
            self.console.print(Panel(
                f"[dim]Previous session:[/dim]\n{summary}",
                title="Session Recall",
                border_style="yellow",
            ))
            self.console.print()

            if self._confirm("Continue where we left off?"):
                self.console.print("[success]✓[/success] Continuing session")
                self._resume_from("last")
                self._show_resume_banner()
            else:
                self.session.start_session(topic="new_chat")
                self.console.print("[info]→[/info] Starting fresh")
                if self.messages and self.messages[0]["role"] == "system":
                    self.messages[0]["content"] += (
                        "\n\n## Previous Session Memory\n"
                        "You have recalled the following summary of the user's previous session:\n"
                        f"{summary}\n"
                        "If the user asks about the previous session, refer to this memory."
                    )
        else:
            self.session.start_session(topic="new_chat")

        self.console.print()

    def _get_input(self) -> str | None:
        """Get user input with Rich styling."""
        try:
            # Built-in input() (with readline) so editing works across wrapped
            # lines. The color escapes are wrapped in \001..\002 so readline
            # excludes them from its column math — otherwise backspace/cursor
            # break once the typed text wraps to the next row.
            color = "1;33" if self.code_mode else "1;35"
            glyph = "⌘" if self.code_mode else "›"
            prompt = f"  \001\033[{color}m\002{glyph}\001\033[0m\002 "
            user_input = input(prompt)
            if user_input == "":
                return None
            return user_input
        except (KeyboardInterrupt, EOFError):
            return None
        except UnicodeDecodeError:
            # Stray/garbled bytes in the terminal input (e.g. truncated
            # multibyte paste). Warn and keep the chat loop alive.
            self.console.print(
                "[warning]⚠[/warning] Unos je sadržao neispravne bajtove (encoding). "
                "Pokušaj ponovo."
            )
            return ""

    def _confirm(self, question: str) -> bool:
        """Ask for user confirmation."""
        self.console.print(f"[yellow]?[/yellow] {question} (y/n)")
        answer = self.console.input("  › ").strip().lower()
        return answer in ("y", "yes")

    def _echo_user(self, text: str):
        """
        Re-render the just-typed message as a left-aligned bubble on a slightly
        lighter (greyer) background, so user turns read differently from
        Scribe's replies.

        On a real terminal the raw input line is erased first (it was echoed by
        readline) and replaced by the bubble; otherwise the bubble is just
        appended.
        """
        if sys.stdout.isatty():
            width = self.console.width or 80
            # "  › " prompt is 4 visible cells; figure out how many rows the
            # input occupied so we can erase exactly that.
            rows = max(1, (4 + cell_len(text) + width - 1) // width)
            sys.stdout.write(f"\033[{rows}A\033[J")
            sys.stdout.flush()

        # Header mirrors Scribe's own "▌ Scribe" so each turn reads as a titled
        # message; "You" matches the web chat's sender label.
        self.console.print("  [user]▌[/user] [user]You[/user]")
        bubble = Padding(Text(text, style="user.msg"), (0, 1),
                         style="user.msg", expand=False)
        self.console.print(Padding(bubble, (0, 0, 0, 2)))

    def _chat(self, user_input: str):
        """Process a chat message with skill detection."""
        self._echo_user(user_input)
        should_use_skill, skill_name = self.skills.should_use_skill(user_input)

        if should_use_skill and skill_name:
            self.console.print(f"[dim]Activating skill: {skill_name}[/dim]")
            result = self.skills.execute_skill(skill_name, {"task": user_input})

            if result.success:
                skill_prompt = result.output
                self.messages.append({"role": "user", "content": f"{user_input}\n\n{skill_prompt}"})
            else:
                self.messages.append({"role": "user", "content": user_input})
        else:
            self.messages.append({"role": "user", "content": user_input})

        self.console.print()

        if self.config.tools_enabled:
            response_text = self._respond_with_tools()
        else:
            response_text = self._stream_response()

        self.console.print()

        if response_text:
            self.messages.append({"role": "assistant", "content": response_text})
            self.session.add_message("user", user_input)
            self.session.add_message("assistant", response_text)

            if self.sme and self.session.current_session:
                self.sme.add(
                    content=f"User: {user_input[:100]}... / Assistant: {response_text[:100]}...",
                    session_id=self.session.current_session.session_id,
                    topic=self.session.current_session.topic,
                    metadata={"type": "interaction"},
                )

            # Autosave after every turn so a crash is still resumable.
            self.session.checkpoint()

        # Status line under the reply: model · tok/s · context usage.
        self._print_status_line()

    def _thinking_line(self, thinking_text: str) -> Text:
        """One-line 'marquee' showing the tail of the live reasoning stream."""
        flat = " ".join(thinking_text.split())
        width = max(20, self.console.width - 6)
        tail = flat[-width:] if flat else "…"
        return Text(f"  💭 {tail}", style="dim", no_wrap=True, overflow="crop")

    def _print_scribe_panel(self, answer_text: str) -> None:
        """
        Print the final answer once as the pale-blue Scribe panel.

        Done outside any Live region: a tall Markdown answer printed once does
        not trigger Live's overflow-redraw, which otherwise stacks duplicate,
        half-drawn panels on long replies.
        """
        self.console.print(Panel(
            Markdown(answer_text, code_theme="ansi_dark"),
            title="[scribe]▌ Scribe[/scribe]",
            border_style="scribe",
            box=ROUNDED,
            padding=(1, 2),
        ))

    def _consume_stream(self, events):
        """
        Consume a (kind, payload) event stream and render it in the TUI.

        While the model is only reasoning, a transient one-line marquee shows the
        tail of the thinking. As soon as the answer starts, the marquee is
        dropped and the answer streams token by token, rendered as Markdown one
        paragraph at a time: each finished paragraph (split on a blank line) is
        committed as cleanly formatted text before the next one begins. Keeping
        each Live region to a single paragraph avoids the tall-panel overflow
        redraw that used to stack half-drawn duplicates.

        Returns (thinking_text, answer_text, tool_calls, gen_tokens).
        """

        thinking_text = ""
        answer_text = ""
        tool_calls = None
        gen_tokens = 0

        think_live = None      # transient one-line reasoning marquee
        ans_live = None        # markdown live for the in-progress paragraph
        committed = 0          # chars of answer already finalized
        header_printed = False

        def _md(text: str) -> Padding:
            # 2-char left/right margin around the streamed answer.
            return Padding(Markdown(text, code_theme="ansi_dark"), (0, 2))

        def _stop(live):
            if live is not None:
                live.stop()

        try:
            for kind, payload in events:
                if kind == "tool_calls":
                    tool_calls = payload
                    continue

                if kind == "thinking":
                    thinking_text += payload
                    gen_tokens += 1
                    if ans_live is None:
                        if think_live is None:
                            think_live = Live(
                                self._thinking_line(""), console=self.console,
                                refresh_per_second=12, transient=True,
                            )
                            think_live.start()
                        think_live.update(self._thinking_line(thinking_text))
                    continue

                # kind == "answer": switch from marquee to streamed paragraphs.
                answer_text += payload
                gen_tokens += 1

                if think_live is not None:
                    think_live.stop()
                    think_live = None

                if not header_printed:
                    self.console.print("  [scribe]▌[/scribe] [accent]Scribe[/accent]")
                    header_printed = True

                if ans_live is None:
                    ans_live = Live(
                        _md(answer_text[committed:]), console=self.console,
                        refresh_per_second=12, transient=False,
                    )
                    ans_live.start()
                else:
                    ans_live.update(_md(answer_text[committed:]))

                # Commit every completed paragraph (text up to a blank line).
                while "\n\n" in answer_text[committed:]:
                    idx = answer_text.index("\n\n", committed)
                    para = answer_text[committed:idx]
                    ans_live.update(_md(para))
                    ans_live.stop()
                    ans_live = None
                    committed = idx + 2
                    self.console.print()  # blank line between paragraphs
                    tail = answer_text[committed:]
                    if tail:
                        ans_live = Live(
                            _md(tail), console=self.console,
                            refresh_per_second=12, transient=False,
                        )
                        ans_live.start()
        finally:
            _stop(think_live)
            if ans_live is not None:
                ans_live.update(_md(answer_text[committed:]))
                ans_live.stop()

        return thinking_text, answer_text, tool_calls, gen_tokens

    def _estimated_context_tokens(self) -> int:
        """Rough token count of the conversation so far (~4 chars/token)."""
        chars = 0
        for m in self.messages:
            chars += len(m.get("content") or "")
            for tc in m.get("tool_calls", []) or []:
                chars += len(str(tc))
        return chars // 4

    def _print_status_line(self) -> None:
        """One dim line under the reply: model · tok/s · context usage."""
        used = self._estimated_context_tokens()
        total = self.config.max_context_tokens or 1
        pct = used / total * 100

        line = Text(no_wrap=True, overflow="crop")
        line.append("  ")
        if self.reasoning:
            line.append(" ✓think ", style="warning")
            line.append(" ")
        if self.code_mode:
            line.append(" ⌘ CODE ", style="pill.code")
            line.append(" ")
        line.append(f" {self.adapter.get_model_name()} ", style="pill.model")
        line.append(" ")
        line.append(f" {self._last_tok_s:.1f} tok/s ", style="pill.speed")
        line.append(" ")
        line.append(f" ctx {used/1000:.1f}k/{total//1000}k {pct:.0f}% ", style="pill.ctx")
        self.console.print(line)
        # Breathing room before the next prompt.
        self.console.print()

    def _respond_with_tools(self, max_iters: int = 6) -> str:
        """
        Run the model with sandboxed workspace file tools, streaming.

        Loop: stream one turn -> while reasoning, show a one-line marquee; the
        answer streams token by token. If the model requests tool calls, run
        them inside the workspace, feed results back, and repeat (up to
        max_iters). Returns the final answer text; intermediate tool turns are
        appended to self.messages directly.
        """
        from scribe.tools import fs, shell, web

        gen_tokens = 0
        t0 = time.perf_counter()

        for _ in range(max_iters):
            try:
                thinking_text, answer_text, tool_calls, toks = self._consume_stream(
                    self.adapter.streaming_turn(self.messages, tools=self._active_tools())
                )
                gen_tokens += toks
            except Exception as e:
                self.console.print(f"[error]Error:[/error] {e}")
                return ""

            if not tool_calls:
                # If </think> never closed, surface the thinking as the answer.
                if not answer_text.strip() and thinking_text.strip():
                    answer_text = thinking_text
                    self._print_scribe_panel(answer_text)
                self._last_tok_s = gen_tokens / max(time.perf_counter() - t0, 1e-6)
                return answer_text.strip()

            # Record the assistant turn that requested the calls (required by the
            # tool-calling protocol before the tool results).
            self.messages.append({
                "role": "assistant",
                "content": answer_text,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            })

            # Execute each call and feed the result back. Bash runs in the code
            # working directory and is confirmed first; file tools stay in the
            # workspace (unless /permissions unlocked).
            if getattr(self.adapter, "last_tool_repair", None):
                self.session.trace("tool_repair", reason=self.adapter.last_tool_repair)
            for tc in tool_calls:
                self.session.trace(
                    "tool_call", name=tc["name"], arguments=str(tc["arguments"])[:500]
                )
                if tc["name"] == "run_bash":
                    command = shell.parse_command(tc["arguments"])
                    self.console.print(
                        f"[yellow]⌘[/yellow] [bold]{command}[/bold]  "
                        f"[dim]({self.code_cwd})[/dim]"
                    )
                    if self._confirm("Run this command?"):
                        result = shell.dispatch(self.code_cwd, tc["name"], tc["arguments"])
                    else:
                        result = "User declined to run this command."
                        self.console.print("[info]→[/info] Skipped.")
                elif tc["name"] in ("web_search", "web_fetch"):
                    result = web.dispatch(tc["name"], tc["arguments"])
                    self.console.print(
                        f"[cyan]🌐[/cyan] [bold]{tc['name']}[/bold] [dim]{tc['arguments']}[/dim]"
                    )
                elif tc["name"] in ("workspace_checkpoint", "workspace_rollback"):
                    from scribe.tools import checkpoint

                    result = checkpoint.dispatch(self.code_cwd, tc["name"], tc["arguments"])
                    self.console.print(
                        f"[cyan]⎌[/cyan] [bold]{tc['name']}[/bold] [dim]{tc['arguments']}[/dim]"
                    )
                else:
                    result = fs.dispatch(
                        self.workspace, tc["name"], tc["arguments"],
                        allow_outside=self.allow_outside,
                    )
                    self.console.print(
                        f"[cyan]⚙[/cyan] [bold]{tc['name']}[/bold] [dim]{tc['arguments']}[/dim]"
                    )
                self.console.print(f"  [dim]{result}[/dim]")
                self.session.trace(
                    "tool_result",
                    name=tc["name"],
                    ok=not str(result).startswith(("Error", "[refused]", "[timeout]")),
                    chars=len(str(result)),
                )
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        self._last_tok_s = gen_tokens / max(time.perf_counter() - t0, 1e-6)
        self.console.print("[warning]⚠[/warning] Tool loop limit reached.")
        return ""

    def _stream_response(self) -> str:
        """
        Stream the response, splitting the reasoning block from the answer.

        While the model is only reasoning, a one-line marquee shows the tail of
        the thinking stream. Once the answer starts, it streams token by token,
        rendered as Markdown one paragraph at a time.
        """
        t0 = time.perf_counter()

        try:
            thinking_text, answer_text, _tool_calls, gen_tokens = self._consume_stream(
                self.adapter.streaming_events(self.messages)
            )
        except Exception as e:
            self.console.print(f"\n[error]Error:[/error] {e}")
            return ""

        # If </think> never closed, surface the thinking as the answer.
        if not answer_text.strip() and thinking_text.strip():
            answer_text = thinking_text
            self._print_scribe_panel(answer_text)

        self._last_tok_s = gen_tokens / max(time.perf_counter() - t0, 1e-6)
        return answer_text.strip()

    def _streaming_progress(self) -> Progress:
        """Create streaming progress indicator."""
        return Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[cyan]Generating...[/cyan]"),
            TextColumn("[dim]{task.fields[char_count]} chars[/dim]"),
            console=self.console,
            transient=True,
        )

    def _generate_response(self, progress: Progress) -> str:
        """Generate streaming response from LLM."""
        task_id = progress.add_task("generate", total=None, char_count="0")
        response_text = ""

        try:
            for chunk in self.adapter.streaming_complete(self.messages):
                response_text += chunk
                progress.update(
                    task_id,
                    char_count=f"{len(response_text)}",
                )

        except Exception as e:
            self.console.print(f"\n[error]Error:[/error] {e}")
            return ""

        progress.remove_task(task_id)
        return response_text

    def _display_response(self, text: str):
        """Display LLM response with Rich styling."""
        if text.startswith("```") or text.startswith("#"):
            try:
                md = Markdown(text)
                self.console.print(md)
                return
            except Exception:
                pass

        self.console.print(Panel(
            text,
            title="[scribe]Scribe[/scribe]",
            border_style="scribe",
            padding=(1, 2),
        ))

    def _handle_command(self, command: str):
        """Handle slash commands."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            self._show_help()
        elif cmd in ("/quit", "/exit", "/q"):
            self.running = False
        elif cmd == "/clear":
            self.console.clear()
        elif cmd == "/session":
            self._show_session_info()
        elif cmd == "/skills":
            self._list_skills()
        elif cmd == "/status":
            self._show_status()
        elif cmd == "/memory":
            self._show_memory()
        elif cmd == "/permissions":
            self._handle_permissions(arg)
        elif cmd in ("/code", "/chat"):
            self._toggle_code_mode(arg, force_off=(cmd == "/chat"))
        elif cmd == "/theme":
            self._handle_theme(arg)
        elif cmd in ("/models", "/model"):
            self._handle_models(arg)
        elif cmd == "/reasoning":
            self._toggle_reasoning(arg)
        else:
            self.console.print(f"[warning]Unknown command:[/warning] {cmd}")
            self.console.print("Type /help for available commands")

    def _handle_permissions(self, arg: str):
        """
        Inspect or change file-tool access.

        /permissions          — show current state
        /permissions unlock   — allow tools outside the workspace (asks first)
        /permissions lock     — restrict tools back to the workspace
        """
        action = arg.strip().lower()

        if action in ("", "status"):
            state = "[error]UNLOCKED[/error] (tools can reach the whole filesystem)" \
                if self.allow_outside else "[success]LOCKED[/success] (tools confined to workspace)"
            self.console.print(Panel(
                f"Workspace: [path]{self.workspace}[/path]\n"
                f"File tools: {state}\n\n"
                "[dim]/permissions unlock[/dim] — let Scribe read/write outside the folder\n"
                "[dim]/permissions lock[/dim]   — restrict back to the workspace",
                title="[scribe]Permissions[/scribe]",
                border_style="scribe",
            ))
            return

        if action == "lock":
            self.allow_outside = False
            self.messages.append({
                "role": "system",
                "content": "File access is now RESTRICTED to the workspace. All "
                           "paths must stay inside it.",
            })
            self.console.print("[success]✓[/success] File tools restricted to the workspace.")
            return

        if action == "unlock":
            if self.allow_outside:
                self.console.print("[info]→[/info] Already unlocked.")
                return
            self.console.print(
                "[warning]⚠ This lets Scribe read AND overwrite files anywhere on "
                "this machine, outside its workspace.[/warning]"
            )
            if not self._confirm("Grant full filesystem access?"):
                self.console.print("[info]→[/info] Canceled. Tools stay sandboxed.")
                return
            self.allow_outside = True
            self.messages.append({
                "role": "system",
                "content": "File access is now UNRESTRICTED. The write_file, "
                           "read_file, make_dir and list_dir tools accept absolute "
                           "paths anywhere on the machine, not just the workspace. "
                           "Use this power carefully and only as the user asks.",
            })
            self.console.print("[error]●[/error] File tools can now leave the workspace.")
            return

        self.console.print(f"[warning]Unknown option:[/warning] {action}")
        self.console.print("Use: /permissions [status|unlock|lock]")

    def _handle_theme(self, arg: str = ""):
        """
        Show or switch the color theme.

        /theme         — list themes (current marked)
        /theme NAME    — switch to NAME and remember it
        """
        name = arg.strip().lower()
        themes = list_themes()

        if not name:
            self.console.print(self._theme_list_panel(themes))
            return

        if name not in themes:
            self.console.print(f"[warning]Unknown theme:[/warning] {name}")
            self.console.print(self._theme_list_panel(themes))
            return

        # Rebuild the console with the new palette (margins are per-renderable,
        # so swapping the console is safe).
        self.theme_name = name
        self.console = get_console(theme=name, force_terminal=True, markup=True)
        try:
            target = self.config.save_value("scribe.ui", "theme", name)
            saved = f"[dim]saved to {target}[/dim]"
        except Exception as e:
            saved = f"[dim]session only (could not save: {e})[/dim]"

        self.console.print(Panel(
            f"[scribe]✶[/scribe] Theme set to [accent]{name}[/accent]\n{saved}",
            border_style="scribe",
            box=ROUNDED,
            padding=(0, 2),
        ))

    def _theme_list_panel(self, themes: list[str]) -> Panel:
        """A rounded panel listing themes, each with its accent swatch."""
        lines = []
        for t in themes:
            marker = "[accent]●[/accent]" if t == self.theme_name else "[dim]○[/dim]"
            swatch = f"[{theme_accent(t)}]████[/{theme_accent(t)}]"
            current = " [dim](current)[/dim]" if t == self.theme_name else ""
            lines.append(f"{marker} {swatch}  {t}{current}")
        body = "\n".join(lines) + "\n\n[dim]Use /theme NAME to switch.[/dim]"
        return Panel(body, title="[scribe]Themes[/scribe]", border_style="scribe",
                     box=ROUNDED, padding=(1, 2))

    def _handle_models(self, arg: str = ""):
        """
        Choose the model backend: a local llama.cpp server or any
        OpenAI-compatible API (OpenRouter, Groq, DeepSeek, ...).

        /models          — show current backend and a short menu
        /models local    — point Scribe at a local llama.cpp server
        /models api      — enter an OpenAI-compatible base URL + API key
        """
        choice = arg.strip().lower()

        if choice in ("", "show", "status"):
            self.console.print(self._models_panel())
            choice = self.console.input(
                "  [dim]Choose[/dim] [accent]1[/accent] [dim]llama.cpp /[/dim] "
                "[accent]2[/accent] [dim]API /[/dim] [accent]Enter[/accent] [dim]cancel ›[/dim] "
            ).strip().lower()

        if choice in ("1", "local", "llama", "llama.cpp", "llamacpp"):
            self._configure_local()
        elif choice in ("2", "api", "cloud", "openai"):
            self._configure_api()
        elif choice in ("", "cancel", "q"):
            self.console.print("[dim]→ No changes.[/dim]")
        else:
            self.console.print(f"[warning]Unknown option:[/warning] {choice}")
            self.console.print("[dim]Use /models, /models local or /models api.[/dim]")

    def _models_panel(self) -> Panel:
        """Show the active backend so the user knows what they are changing."""
        key = self.config.api_key
        has_key = bool(key) and key not in ("not-needed", "")
        key_state = "[success]set[/success]" if has_key else "[dim]none (local)[/dim]"
        body = (
            f"[dim]Base URL[/dim]  [accent]{self.config.base_url}[/accent]\n"
            f"[dim]Model[/dim]     {self.config.model}\n"
            f"[dim]API key[/dim]   {key_state}\n\n"
            "[accent]1[/accent] llama.cpp  "
            "[dim]— local server, no API key, GBNF tool grammar[/dim]\n"
            "[accent]2[/accent] API        "
            "[dim]— OpenAI-compatible endpoint + key (cloud or remote)[/dim]"
        )
        return Panel(body, title="[scribe]Model backend[/scribe]",
                     border_style="scribe", box=ROUNDED, padding=(1, 2))

    def _configure_local(self):
        """Point Scribe at a local llama.cpp (OpenAI-compatible) server."""
        default = "http://127.0.0.1:18083/v1"
        url = self.console.input(
            f"  [dim]Base URL[/dim] [accent](Enter = {default})[/accent] [dim]›[/dim] "
        ).strip() or default
        self._apply_backend(
            base_url=url, model="default", api_key="not-needed", tool_grammar="auto"
        )

    def _configure_api(self):
        """Enter an OpenAI-compatible API endpoint, model and key."""
        url = self.console.input(
            "  [dim]Base URL (e.g. https://openrouter.ai/api/v1)[/dim] [dim]›[/dim] "
        ).strip()
        if not url:
            self.console.print("[dim]→ Canceled (no base URL).[/dim]")
            return
        model = self.console.input(
            "  [dim]Model id (e.g. deepseek-chat)[/dim] [dim]›[/dim] "
        ).strip()
        if not model:
            self.console.print("[dim]→ Canceled (no model).[/dim]")
            return
        # password=True hides the key as it is typed (mirrors the web modal's
        # masked input), so it never shows on screen or in scrollback.
        key = self.console.input(
            "  [dim]API key (hidden; stored in your local config; or leave empty "
            "to use SCRIBE_API_KEY)[/dim] [dim]›[/dim] ",
            password=True,
        ).strip() or "not-needed"
        # Cloud backends do not support GBNF grammar; fall back to plain parsing.
        self._apply_backend(
            base_url=url, model=model, api_key=key, tool_grammar="off"
        )

    def _apply_backend(self, base_url: str, model: str, api_key: str, tool_grammar: str):
        """Persist backend settings, rebuild the adapter, and report health."""
        try:
            self.config.save_value("scribe", "base_url", base_url)
            self.config.save_value("scribe", "model", model)
            self.config.save_value("scribe", "api_key", api_key)
            target = self.config.save_value("scribe", "tool_grammar", tool_grammar)
            saved = f"[dim]saved to {target}[/dim]"
        except Exception as e:
            saved = f"[dim]session only (could not save: {e})[/dim]"

        # Rebuild the adapter from the updated config so the next turn uses it.
        self.adapter = LLMAdapter.from_config(self.config)
        self.context["server"] = self.config.base_url
        self.context["model"] = self.config.model

        if self.adapter.is_healthy():
            name = self.adapter.get_model_name()
            health = f"[success]✓[/success] Connected to [green]{name}[/green]"
        else:
            health = "[warning]⚠[/warning] Saved, but the server is not reachable yet."

        self.console.print(Panel(
            f"[scribe]✶[/scribe] Backend set to [accent]{base_url}[/accent]\n"
            f"{health}\n{saved}",
            border_style="scribe", box=ROUNDED, padding=(0, 2),
        ))

    def _toggle_reasoning(self, arg: str = ""):
        """
        Turn the model's reasoning on/off live, for both normal and code mode.

        /reasoning           — toggle on/off
        /reasoning on|off|auto — set explicitly

        ON  = always think (reason briefly, then a short answer). OFF = never
        think (answer directly). AUTO = the reasoning gate decides per
        request. Works mid-conversation.
        """
        action = arg.strip().lower()
        if action in ("on", "true", "1"):
            self.reasoning, mode = True, "on"
        elif action in ("off", "false", "0"):
            self.reasoning, mode = False, "off"
        elif action == "auto":
            self.reasoning, mode = True, "auto"
        else:
            self.reasoning = not self.reasoning
            mode = "on" if self.reasoning else "off"

        # Drive both knobs the adapter reads: thinking_mode is checked first,
        # enable_thinking is the static fallback.
        self.adapter.thinking_mode = mode
        self.adapter.enable_thinking = self.reasoning
        if mode == "auto":
            self.console.print(
                "[success]✓[/success] Reasoning [accent]AUTO[/accent] "
                "[dim]— model misli samo kad se isplati[/dim]"
            )
            return

        # Steer the model with a fresh directive (latest system message wins),
        # so it also stops/starts emitting any inline <think>.
        if self.reasoning:
            self.messages.append({
                "role": "system",
                "content": "Reasoning is now ON. Think step by step inside a "
                           "<think> block, then give a SHORT final answer in the "
                           "user's language.",
            })
            self.console.print(
                "[success]✓[/success] Reasoning [accent]ON[/accent] "
                "[dim]— model razmišlja pre odgovora[/dim]"
            )
        else:
            self.messages.append({
                "role": "system",
                "content": "Reasoning is now OFF. Do NOT produce a <think> block "
                           "or any step-by-step reasoning. Answer directly and "
                           "concisely in the user's language.",
            })
            self.console.print(
                "[info]→[/info] Reasoning [accent]OFF[/accent] "
                "[dim]— model odgovara direktno (bez razmišljanja)[/dim]"
            )

    def _toggle_code_mode(self, arg: str = "", force_off: bool = False):
        """
        Enter or leave Scribe Code mode (terminal expert with bash access).

        /code        — enter code mode (asks for confirmation first)
        /code off    — leave code mode
        /chat        — leave code mode (alias)
        """
        action = arg.strip().lower()
        leaving = force_off or action in ("off", "exit", "stop")

        if self.code_mode and leaving:
            self.code_mode = False
            self.messages.append({
                "role": "system",
                "content": "Code mode is OFF. You are Scribe again — the bash tool "
                           "is no longer available; keep answers short.",
            })
            self.console.print("[info]→[/info] Back to chat mode.")
            return

        if self.code_mode:
            self.console.print("[info]→[/info] Already in code mode. Use /chat to leave.")
            return

        if leaving:
            self.console.print("[info]→[/info] Not in code mode.")
            return

        # Entering: full shell access is powerful, so confirm once.
        self.console.print(
            "[warning]⚠ Code mode gives Scribe FULL shell access on this machine "
            "(every bash command). You approve each command before it runs.[/warning]"
        )
        if not self._confirm("Enter Scribe Code mode?"):
            self.console.print("[info]→[/info] Canceled.")
            return

        self.code_mode = True
        self.messages.append({
            "role": "system",
            "content": get_code_system_prompt(
                str(self.code_cwd), max_thinking_words=self.config.max_thinking_words
            ),
        })
        self.console.print(Panel(
            f"[bold yellow]⌘ Scribe Code[/bold yellow] — terminal expert\n"
            f"Working dir: [path]{self.code_cwd}[/path]\n\n"
            "[dim]Full bash access. Each command is shown and confirmed.\n"
            "Type /chat (or /code off) to leave.[/dim]",
            title="[scribe]Scribe Code[/scribe]",
            border_style="warning",
            box=ROUNDED,
        ))

    def _active_tools(self) -> list[dict]:
        """Tool schemas advertised to the model for the current mode."""
        from scribe.tools import checkpoint, fs, shell, web

        if self.code_mode:
            return (
                fs.TOOL_SCHEMAS
                + shell.TOOL_SCHEMAS
                + checkpoint.TOOL_SCHEMAS
                + web.TOOL_SCHEMAS
            )
        return fs.TOOL_SCHEMAS + web.TOOL_SCHEMAS

    def _show_help(self):
        """Show help. Command names stand out; explanations stay dim."""
        commands = [
            ("/models", "Switch backend: local llama.cpp or an OpenAI-compatible API"),
            ("/reasoning", "Thinking on/off/auto (e.g. /reasoning auto)"),
            ("/code", "Enter Scribe Code (terminal expert, full bash access)"),
            ("/chat", "Leave code mode, back to normal chat"),
            ("/theme", "List or switch color theme (e.g. /theme dracula)"),
            ("/permissions", "Show/allow file access outside the workspace"),
            ("/status", "Show system status"),
            ("/session", "Show current session"),
            ("/skills", "List available skills"),
            ("/memory", "Show memory stats"),
            ("/clear", "Clear screen"),
            ("/help", "Show this help"),
            ("/quit", "Exit Scribe"),
        ]
        width = max(len(name) for name, _ in commands)
        lines = [
            f"[accent]{name.ljust(width)}[/accent]  [dim]{desc}[/dim]"
            for name, desc in commands
        ]
        self.console.print(Panel(
            "\n".join(lines),
            title="[scribe]Commands[/scribe]",
            border_style="scribe",
            box=ROUNDED,
            padding=(1, 2),
        ))

    def _show_session_info(self):
        """Show current session information."""
        if self.session.current_session:
            cp = self.session.current_session
            info = f"""
**Session:** `{cp.session_id}`
**Topic:** {cp.topic}
**Status:** {cp.status}
**Language Game:** {cp.current_language_game}
**Messages:** {len(cp.messages)}
            """
            self.console.print(Panel(info.strip(), title="Session Info", border_style="cyan"))

    def _list_skills(self):
        """List available skills."""
        skills = self.skills.registry.list()

        if not skills:
            self.console.print("[dim]No skills available[/dim]")
            return

        table = Table(title="Available Skills", show_header=True)
        table.add_column("Skill", style="cyan")
        table.add_column("Description", style="white")

        for skill in skills:
            table.add_row(skill.name, skill.description)

        self.console.print(table)

    def _show_memory(self):
        """Show memory statistics."""
        if not self.sme:
            self.console.print("[warning]Memory not available[/warning]")
            return

        count = self.sme.count()
        recent = self.sme.get_recent(limit=3)

        self.console.print(Panel(
            f"**Total entries:** {count}",
            title="Memory Stats",
            border_style="cyan",
        ))

        if recent:
            self.console.print("\n[bold]Recent:[/bold]")
            for entry in recent:
                self.console.print(f"  • [{entry.topic or 'general'}] {entry.content[:60]}...")

    def _show_status(self):
        """Show system status."""
        table = Table(title="System Status", show_header=False)
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="white")

        server_status = (
            "[success]✓ Connected[/success]"
            if self.adapter.is_healthy()
            else "[error]✗ Disconnected[/error]"
        )
        table.add_row("LLM Server", server_status)
        table.add_row("Model", self.adapter.get_model_name())
        table.add_row("Base URL", self.config.base_url)
        table.add_row("Sessions", str(len(self.session.list_sessions())))

        if self.sme:
            table.add_row("Memory Entries", str(self.sme.count()))
        else:
            table.add_row("Memory", "[warning]unavailable[/warning]")

        table.add_row("Skills", str(len(self.skills.registry.list())))

        self.console.print(table)

    def _handle_exit(self):
        """Handle graceful exit."""
        self.console.print("\n[dim]Exiting...[/dim]")

    def _cleanup(self):
        """Cleanup at exit."""
        if self.session.current_session:
            tag = session_tag(self.session.current_session.session_id)
            self.session.end_session()

            if self.sme:
                summary = " ".join(
                    f"{m['role']}: {m['content'][:50]}..."
                    for m in self.session.get_recent_messages(5)
                )
                self.sme.add(
                    content=summary,
                    session_id=self.session.current_session.session_id,
                    topic=self.session.current_session.topic,
                    metadata={
                        "type": "session_summary",
                        "status": self.session.current_session.status,
                        "message_count": len(self.session.current_session.messages),
                    },
                )

            # Small logo + the exact command to resume this very session.
            self._print_logo(small=True)
            self.console.print(
                f"  [dim]Session saved as[/dim] [accent]#{tag}[/accent]"
                f"[dim]. Continue it with:[/dim]"
            )
            self.console.print(f"  [command]scribe-llm chat resume {tag}[/command]")
            self.console.print(
                "  [dim]or just[/dim] [command]scribe-llm chat resume[/command] "
                "[dim]for the most recent.[/dim]"
            )
            self.console.print()


def run_tui(config: ScribeConfig | None = None, resume_tag: str | None = None):
    """Run the Scribe TUI."""
    tui = ScribeTUI(config, resume_tag=resume_tag)
    tui.run()
