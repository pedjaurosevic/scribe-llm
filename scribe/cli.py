"""
Scribe CLI - Command line interface.

Usage:
    scribe chat                    # Start interactive TUI chat
    scribe memory recall QUERY    # Recall from SME
    scribe session last           # Show last session
    scribe status                # Check system status
    scribe rag search QUERY      # Search documents
    scribe rag ingest FILE      # Add document to RAG
"""

from __future__ import annotations

import locale
import sys
from pathlib import Path

import click

# Initialize the C-level locale from the environment so GNU readline handles
# multibyte (UTF-8) input correctly, and make stdin/stdout tolerant of stray
# bytes instead of crashing the whole TUI on a single bad input.
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from scribe import __version__
from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.memory import get_rag_service, get_sme_service, recall_previous_session
from scribe.session import SessionManager
from scribe.ui import get_default_console


@click.group()
@click.version_option(version=__version__)
@click.pass_context
def main(ctx):
    """Scribe - Autonomous Research & Writing Agent."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = ScribeConfig()
    ctx.obj["console"] = get_default_console()


@main.command(context_settings={"ignore_unknown_options": True})
@click.option("--textual", "-t", is_flag=True, default=False,
              help="Use the full-screen Textual UI (experimental)")
@click.option("--resume", "-r", default=None, metavar="TAG",
              help="Resume a past session by its tag (e.g. --resume a1b2c)")
@click.argument("subargs", nargs=-1)
@click.pass_context
def chat(ctx, textual, resume, subargs):
    """Start the interactive TUI chat session.

    Resume a session:  scribe chat resume [TAG]
    (no TAG resumes the most recent session).
    """
    config = ctx.obj["config"]

    # Friendly form:  scribe chat resume [TAG]
    if subargs and subargs[0].lower() == "resume":
        resume = subargs[1] if len(subargs) > 1 else "last"

    if textual:
        if resume:
            ctx.obj["console"].print(
                "[warning]⚠[/warning] --resume is not supported in the Textual UI yet; "
                "using it without resume."
            )
        from scribe.tui_app import run_app
        run_app(config)
    else:
        from scribe.tui import run_tui
        run_tui(config, resume_tag=resume)


@main.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8765, help="Port to bind to")
@click.pass_context
def web(ctx, host, port):
    """Start the web UI server."""
    from scribe.web import run

    console = ctx.obj["console"]
    console.print("[bold cyan]Starting Scribe Web UI[/bold cyan]")
    console.print(f"  Host: {host}")
    console.print(f"  Port: {port}")
    console.print(f"  URL:  http://localhost:{port}")
    console.print()
    console.print("[dim]Press Ctrl+C to stop[/dim]")

    run(host=host, port=port)


@main.group()
def memory():
    """Memory operations (SME - cross-session semantic memory)."""
    pass


@memory.command("recall")
@click.argument("query")
@click.option("--limit", "-n", default=5, help="Number of results")
@click.pass_context
def memory_recall(ctx, query, limit):
    """Recall information from semantic memory."""
    console = ctx.obj["console"]
    sme = get_sme_service()

    if not sme:
        console.print("[error]SME not available[/error]")
        return

    results = sme.search(query, limit=limit)

    if not results:
        console.print("[dim]No results found[/dim]")
        return

    for r in results:
        console.print(f"[bold cyan]{r.topic or 'general'}[/bold cyan]")
        console.print(f"  {r.content[:200]}...")
        console.print(f"  [dim]Session: {r.session_id} | Date: {r.created_at[:10]}[/dim]")
        console.print()


@memory.command("stats")
@click.pass_context
def memory_stats(ctx):
    """Show memory statistics."""
    console = ctx.obj["console"]
    sme = get_sme_service()

    if not sme:
        console.print("[error]SME not available[/error]")
        return

    count = sme.count()
    recent = sme.get_recent(limit=3)

    console.print("[bold]Memory Statistics[/bold]")
    console.print(f"  Total entries: {count}")
    console.print()

    if recent:
        console.print("[bold]Recent entries:[/bold]")
        for r in recent:
            console.print(f"  • [{r.topic or 'general'}] {r.content[:60]}...")


@main.group()
def rag():
    """RAG operations (document semantic search)."""
    pass


@rag.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=5, help="Number of results")
@click.pass_context
def rag_search(ctx, query, limit):
    """Search documents semantically."""
    console = ctx.obj["console"]
    rag = get_rag_service()

    if not rag:
        console.print("[error]RAG not available[/error]")
        return

    results = rag.search(query, limit=limit)

    if not results:
        console.print("[dim]No results found[/dim]")
        return

    for r in results:
        source = Path(r.source_file).name if r.source_file else "unknown"
        console.print(f"[bold cyan]{source}[/bold cyan]")
        console.print(f"  {r.content[:200]}...")
        console.print()


@rag.command("ingest")
@click.argument("file_path", type=click.Path(exists=True))
@click.pass_context
def rag_ingest(ctx, file_path):
    """Add a document to RAG index."""
    console = ctx.obj["console"]
    rag = get_rag_service()

    if not rag:
        console.print("[error]RAG not available[/error]")
        return

    try:
        count = rag.ingest_file(file_path)
        console.print(f"[success]✓[/success] Added {count} chunks from [file]{file_path}[/file]")
    except Exception as e:
        console.print(f"[error]Error:[/error] {e}")


@rag.command("sources")
@click.pass_context
def rag_sources(ctx):
    """List indexed document sources."""
    console = ctx.obj["console"]
    rag = get_rag_service()

    if not rag:
        console.print("[error]RAG not available[/error]")
        return

    sources = rag.list_sources()

    if not sources:
        console.print("[dim]No documents indexed[/dim]")
        return

    console.print(f"[bold]Indexed Sources ({len(sources)})[/bold]")
    for s in sources:
        name = Path(s["source_file"]).name if s.get("source_file") else "unknown"
        console.print(f"  • {name}: {s['chunk_count']} chunks")


@rag.command("stats")
@click.pass_context
def rag_stats(ctx):
    """Show RAG statistics."""
    console = ctx.obj["console"]
    rag = get_rag_service()

    if not rag:
        console.print("[error]RAG not available[/error]")
        return

    count = rag.count()
    sources = rag.list_sources()

    console.print("[bold]RAG Statistics[/bold]")
    console.print(f"  Total chunks: {count}")
    console.print(f"  Sources: {len(sources)}")


@main.group()
def session():
    """Session management."""
    pass


@session.command("last")
@click.pass_context
def session_last(ctx):
    """Show the last session summary."""
    console = ctx.obj["console"]
    sme = get_sme_service()

    result = recall_previous_session(sme)
    console.print(result)


@session.command("list")
@click.pass_context
def session_list(ctx):
    """List all sessions."""
    console = ctx.obj["console"]
    session_mgr = SessionManager(ctx.obj["config"])

    sessions = session_mgr.list_sessions()
    if sessions:
        console.print("[bold]Sessions:[/bold]")
        for sid in sessions:
            console.print(f"  {sid}")
    else:
        console.print("No sessions found.")


@main.group()
def config():
    """Configuration management."""
    pass


@config.command("show")
@click.pass_context
def config_show(ctx):
    """Show current configuration."""
    console = ctx.obj["console"]
    cfg = ctx.obj["config"]

    console.print("[bold]Scribe Configuration[/bold]")
    console.print(f"  base_url: {cfg.base_url}")
    console.print(f"  model: {cfg.model}")
    console.print(f"  theme: {cfg.theme}")
    console.print(f"  sme_enabled: {cfg.sme_enabled}")
    console.print(f"  rag_enabled: {cfg.rag_enabled}")


@main.group()
def evolve():
    """EVOLVE-SCRIBE — bounded self-improvement (Phase 0: baseline eval)."""
    pass


@evolve.command("eval")
@click.option("--limit", "-n", default=None, type=int,
              help="Only run the first N tasks (quick check)")
@click.option("--no-ledger", is_flag=True, default=False,
              help="Do not append the result to the evolve ledger")
@click.pass_context
def evolve_eval(ctx, limit, no_ledger):
    """Score the current Scribe on the frozen held-out suite (baseline)."""
    from scribe.evolve.evaluate import run_eval_cli

    run_eval_cli(ctx.obj["config"], ctx.obj["console"], limit=limit,
                 write_ledger=not no_ledger)


@main.group()
def mail():
    """Email bridge — send notifications and accept commands by email."""
    pass


@mail.command("send")
@click.argument("subject")
@click.argument("body", default="")
@click.option("--to", default=None, help="Recipient (default: approved sender)")
@click.pass_context
def mail_send(ctx, subject, body, to):
    """Send an email. BODY is optional; reads stdin if a single '-' is given."""
    from scribe.mail import build_bridge

    console = ctx.obj["console"]
    config = ctx.obj["config"]

    if body == "-":
        body = sys.stdin.read()

    try:
        bridge = build_bridge(config)
        bridge.send(subject, body, to=to)
        console.print(f"[success]✓[/success] Sent: {subject}")
    except Exception as e:
        console.print(f"[error]✗ Send failed:[/error] {e}")
        sys.exit(1)


@mail.command("watch")
@click.option("--once", is_flag=True, default=False,
              help="Poll a single time and exit (for testing)")
@click.pass_context
def mail_watch(ctx, once):
    """Poll the inbox and run approved commands, replying with the result."""
    import time

    from scribe.mail import build_bridge, execute_instruction

    console = ctx.obj["console"]
    config = ctx.obj["config"]
    cfg = config.email_config()

    if not cfg["secret"]:
        console.print("[error]No secret set.[/error] Command intake is disabled "
                      "until you set [scribe.email].secret.")
        sys.exit(1)

    try:
        bridge = build_bridge(config)
    except Exception as e:
        console.print(f"[error]✗ Email not configured:[/error] {e}")
        sys.exit(1)

    interval = cfg["poll_interval"]
    console.print(f"[info]Watching inbox[/info] for commands from "
                  f"[path]{bridge.approved_sender}[/path] (every {interval}s). "
                  "Ctrl-C to stop.")

    while True:
        try:
            for cmd in bridge.poll_commands():
                console.print(f"[info]→ Command:[/info] {cmd.subject}")
                instruction = cmd.instruction(cfg["secret"])
                answer = execute_instruction(config, instruction)
                bridge.send(
                    f"Re: {cmd.subject}",
                    answer,
                    to=cmd.sender,
                    in_reply_to=cmd.message_id,
                )
                console.print(f"[success]✓[/success] Replied to {cmd.sender}")
        except KeyboardInterrupt:
            console.print("\n[info]Stopped.[/info]")
            break
        except Exception as e:
            console.print(f"[warning]Poll error:[/warning] {e}")

        if once:
            break
        time.sleep(interval)


@main.command()
@click.pass_context
def status(ctx):
    """Check system status."""
    console = ctx.obj["console"]
    config = ctx.obj["config"]

    adapter = LLMAdapter.from_config(config)

    console.print("[bold]System Status[/bold]\n")

    if adapter.is_healthy():
        model_name = adapter.get_model_name()
        console.print(f"[success]✓[/success] LLM Server: Connected ({model_name})")
    else:
        console.print("[error]✗[/error] LLM Server: Not reachable")

    session_mgr = SessionManager(config)
    sessions = session_mgr.list_sessions()
    console.print(f"[info]Sessions:[/info] {len(sessions)} total")

    sme = get_sme_service()
    if sme:
        console.print(f"[info]Memory:[/info] {sme.count()} entries")
    else:
        console.print("[warning]Memory:[/warning] not available")

    rag = get_rag_service()
    if rag:
        console.print(
            f"[info]RAG:[/info] {rag.count()} chunks "
            f"from {len(rag.list_sources())} sources"
        )
    else:
        console.print("[warning]RAG:[/warning] not available")

    ecfg = config.email_config()
    if ecfg["enabled"] and ecfg["address"] and ecfg["password"]:
        intake = "commands ON" if ecfg["secret"] else "send-only (no secret)"
        console.print(f"[info]Email:[/info] {ecfg['address']} ({intake})")
    else:
        console.print("[warning]Email:[/warning] disabled")


if __name__ == "__main__":
    main()
