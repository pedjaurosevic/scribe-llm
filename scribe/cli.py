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

import json
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


@main.command()
@click.argument("directory", default=".", type=click.Path())
@click.pass_context
def init(ctx, directory):
    """
    Create a project-local vault (config.toml + ./.scribe) so this directory
    has its own isolated RAG/SME stores. Idempotent — never overwrites.
    """
    from scribe.vault import init_vault

    console = ctx.obj["console"]
    report = init_vault(directory)
    for name in report["created"]:
        console.print(f"  [success]+[/success] {name}")
    for name in report["existing"]:
        console.print(f"  [dim]= {name} (kept)[/dim]")
    console.print(
        f"\n[info]Vault ready[/info] at [path]{report['vault']}[/path]. "
        "Run Scribe from this directory to use it."
    )


@main.command()
@click.option("--tailscale", is_flag=True, help="Also scan Tailscale peers")
@click.option("--set-default", is_flag=True,
              help="Save the first discovered endpoint as base_url")
@click.pass_context
def discover(ctx, tailscale, set_default):
    """Scan local (and optional Tailscale) ports for model servers."""
    from scribe.discovery import discover as scan

    console = ctx.obj["console"]
    console.print("[info]Scanning for model servers…[/info]")
    endpoints = scan(include_tailscale=tailscale)
    if not endpoints:
        console.print("[dim]No OpenAI-compatible servers found[/dim]")
        return
    for ep in endpoints:
        console.print(
            f"  [success]●[/success] [accent]{ep.base_url}[/accent]  "
            f"[dim]{', '.join(ep.models[:3])}"
            + (f" +{len(ep.models) - 3} more" if len(ep.models) > 3 else "")
            + "[/dim]"
        )
    if set_default:
        config = ctx.obj["config"]
        target = config.save_value("scribe", "base_url", endpoints[0].base_url)
        console.print(
            f"\n[success]✓[/success] Default base_url set to "
            f"[accent]{endpoints[0].base_url}[/accent] [dim]({target})[/dim]"
        )


@main.command()
@click.argument("prompt")
@click.option("--a", "model_a", required=True, help="First model name")
@click.option("--b", "model_b", required=True, help="Second model name")
@click.pass_context
def compare(ctx, prompt, model_a, model_b):
    """Blind A/B two models on one prompt; vote, then reveal."""
    from scribe.compare import Contestant, answer_with, build_blind

    console = ctx.obj["console"]
    adapter = LLMAdapter.from_config(ctx.obj["config"])

    console.print("[info]Querying both models…[/info]\n")
    left = Contestant(model_a, answer_with(adapter, model_a, prompt))
    right = Contestant(model_b, answer_with(adapter, model_b, prompt))
    blind = build_blind(prompt, left, right)

    for label in blind.labels():
        console.print(f"[bold accent]── {label} ──[/bold accent]")
        console.print(blind.slots[label].answer)
        console.print()

    vote = click.prompt("Which is better? (A/B/tie)", default="tie").strip().upper()
    vote = vote if vote in ("A", "B") else None
    result = blind.reveal(vote)

    console.print()
    console.print(f"  A = [accent]{result['A']}[/accent]")
    console.print(f"  B = [accent]{result['B']}[/accent]")
    if result["winner"]:
        console.print(f"  [success]Winner: {result['winner']}[/success]")
    else:
        console.print("  [dim]Tie / no vote[/dim]")


@main.command()
@click.pass_context
def pulse(ctx):
    """Record one heartbeat (wire to a systemd timer for continuity)."""
    from scribe.pulse import beat

    console = ctx.obj["console"]
    event = beat(ctx.obj["config"])
    mark = "[success]●[/success]" if event["server_up"] else "[error]○[/error]"
    console.print(f"{mark} pulse {event['ts']}  model={event['model'] or '—'}")


@main.command()
@click.pass_context
def diary(ctx):
    """Write a short reflection on today's sessions (opt-in continuity)."""
    from scribe.pulse import write_diary

    console = ctx.obj["console"]
    entry = write_diary(ctx.obj["config"])
    if entry:
        console.print(f"[success]✓[/success] Diary written to [path]{entry}[/path]")
    else:
        console.print("[dim]No sessions today — nothing to reflect on[/dim]")


@main.command()
@click.argument("fact")
@click.pass_context
def remember(ctx, fact):
    """Add a durable fact to the WorldModel (injected into every prompt)."""
    from scribe.worldmodel import remember as _remember

    console = ctx.obj["console"]
    wm = _remember(fact)
    console.print(
        f"[success]✓[/success] Remembered. WorldModel now holds "
        f"{len(wm.knowledge)} fact(s) [dim](rev {wm.revision})[/dim]."
    )


@main.command()
@click.argument("session_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Emit raw trace events")
@click.pass_context
def trace(ctx, session_id, as_json):
    """Show the ORORO trace for a session (latest when omitted)."""
    from scribe.session import SessionManager
    from scribe.trace import TRACE_FILE, read_trace, trace_summary

    console = ctx.obj["console"]
    manager = SessionManager(ctx.obj["config"])
    if not session_id:
        sessions = manager.list_sessions()
        session_id = sessions[0] if sessions else None
    if not session_id:
        console.print("[dim]No sessions found[/dim]")
        return
    path = manager.sessions_dir / session_id / TRACE_FILE
    if as_json:
        for event in read_trace(path):
            click.echo(json.dumps(event, sort_keys=True, ensure_ascii=False))
        return
    summary = trace_summary(path)
    console.print(f"[bold]Trace {session_id}[/bold] — {summary['events']} events")
    for kind, n in sorted(summary["kinds"].items()):
        console.print(f"  {kind:<14} {n}")
    if summary["events"] and not summary["monotone"]:
        console.print("  [error]⚠ sequence not monotone[/error]")


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
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to (default localhost; use 0.0.0.0 to expose on the network)",
)
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
    if host == "0.0.0.0":
        console.print(
            "[yellow]  ! Bound to 0.0.0.0 — reachable from the network. "
            "The web UI includes a shell terminal; keep the PIN set.[/yellow]"
        )
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
def wiki():
    """Wiki operations (distill sessions into durable knowledge)."""
    pass


@wiki.command("distill")
@click.option("--since", default=None, help="Only sessions on/after this date (YYYYMMDD)")
@click.option("--limit", "-n", type=int, default=None, help="Process at most N sessions")
@click.option("--dry-run", is_flag=True, help="List pending sessions without processing")
@click.option("--no-rag", is_flag=True, help="Skip re-ingesting changed pages into RAG")
@click.pass_context
def wiki_distill(ctx, since, limit, dry_run, no_rag):
    """Distill saved sessions into WIKI pages (decisions, conclusions, facts)."""
    from scribe import wiki as wiki_mod

    console = ctx.obj["console"]
    config = ctx.obj["config"]

    wiki_path = wiki_mod.wiki_dir(config)
    manager = SessionManager(config)
    ledger = wiki_mod.load_ledger(wiki_path)
    pending = wiki_mod.pending_sessions(manager, ledger, since=since)

    if not pending:
        console.print("[success]✓[/success] Nothing to distill — wiki is up to date.")
        return

    console.print(
        f"[info]Pending:[/info] {len(pending)} session(s) → [file]{wiki_path}[/file]"
    )
    if dry_run:
        for session_id, checkpoint in pending:
            console.print(f"  • {session_id}  [dim]{checkpoint.topic}[/dim]")
        return

    adapter = LLMAdapter.from_config(config)
    if not adapter.is_healthy():
        console.print("[error]LLM server not reachable — start it first.[/error]")
        return

    def on_progress(session_id: str, summary: str) -> None:
        console.print(f"  [success]✓[/success] {session_id}: {summary[:100]}")

    results = wiki_mod.distill(
        config, since=since, limit=limit, adapter=adapter, on_progress=on_progress
    )

    stored = sum(1 for r in results if r["status"] == "stored")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors = [r for r in results if r["status"] == "error"]
    console.print(
        f"\n[bold]Done:[/bold] {stored} stored, {skipped} skipped"
        + (f", [error]{len(errors)} failed[/error]" if errors else "")
    )
    for r in errors:
        console.print(f"  [error]✗[/error] {r['session']}: {r['summary'][:100]}")

    # Make the curated knowledge semantically searchable too.
    if stored and not no_rag:
        rag = get_rag_service(config)
        if rag:
            ingested = wiki_mod.sync_rag(wiki_path, rag)
            if ingested:
                console.print(
                    f"[info]RAG:[/info] re-ingested {len(ingested)} page(s): "
                    + ", ".join(ingested)
                )
        else:
            console.print("[warning]RAG:[/warning] not available, pages not ingested")


@main.group()
def rag():
    """RAG operations (document semantic search)."""
    pass


@rag.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=5, help="Number of results")
@click.option(
    "--semantic-only",
    is_flag=True,
    help="Skip the lexical FTS branch (pure vector search)",
)
@click.pass_context
def rag_search(ctx, query, limit, semantic_only):
    """Search documents (hybrid: vectors + FTS5, RRF-fused)."""
    console = ctx.obj["console"]
    rag = get_rag_service()

    if not rag:
        console.print("[error]RAG not available[/error]")
        return

    results = (
        rag.search(query, limit=limit)
        if semantic_only
        else rag.hybrid_search(query, limit=limit)
    )

    if not results:
        console.print("[dim]No results found[/dim]")
        return

    for r in results:
        source = Path(r.source_file).name if r.source_file else "unknown"
        console.print(f"[bold cyan]{source}[/bold cyan]")
        console.print(f"  {r.content[:200]}...")
        console.print()


@rag.command("ask")
@click.argument("question")
@click.option("--limit", "-n", default=6, help="Number of source chunks to retrieve")
@click.pass_context
def rag_ask(ctx, question, limit):
    """
    Grounded Q&A: every claim cites a retrieved source, contradictions are
    tagged, and an answer outside the sources is refused.
    """
    from scribe.llm_adapter import LLMAdapter
    from scribe.prompts import get_grounded_prompt

    console = ctx.obj["console"]
    config = ScribeConfig()
    rag = get_rag_service(config)

    if not rag:
        console.print("[error]RAG not available[/error]")
        return
    chunks = rag.hybrid_search(question, limit=limit)
    if not chunks:
        console.print("[dim]No sources found — ingest documents first[/dim]")
        return

    for n, c in enumerate(chunks, 1):
        name = Path(c.source_file).name if c.source_file else "unknown"
        console.print(f"[dim][{n}] {name}[/dim]")

    adapter = LLMAdapter.from_config(config)
    messages = [
        {"role": "system", "content": get_grounded_prompt(chunks)},
        {"role": "user", "content": question},
    ]
    console.print()
    for chunk in adapter.streaming_complete(messages, temperature=0.3):
        console.print(chunk, end="")
    console.print()


@rag.command("reindex")
@click.pass_context
def rag_reindex(ctx):
    """Rebuild the lexical (FTS5) index from the vector table."""
    console = ctx.obj["console"]
    rag = get_rag_service()

    if not rag:
        console.print("[error]RAG not available[/error]")
        return
    count = rag.reindex_fts()
    console.print(f"[success]✓[/success] Lexical index rebuilt: {count} chunks")


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
        console.print(f"\nTranscripts (Markdown): {session_mgr.transcripts_dir}")
    else:
        console.print("No sessions found.")


@session.command("search")
@click.argument("query")
@click.option("--limit", default=20, show_default=True, help="Max matches to show.")
@click.pass_context
def session_search(ctx, query, limit):
    """Full-text search across all session transcripts."""
    console = ctx.obj["console"]
    session_mgr = SessionManager(ctx.obj["config"])

    hits = session_mgr.search_transcripts(query, limit=limit)
    if not hits:
        console.print(f"No matches for '{query}' in {session_mgr.transcripts_dir}")
        return
    current = None
    for hit in hits:
        if hit["session_id"] != current:
            current = hit["session_id"]
            console.print(f"\n[bold]{current}[/bold]  ({hit['path']})")
        console.print(f"  {hit['line']}: {hit['text']}")


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


@main.command()
@click.option("--fitness", is_flag=True, help="Run only the fitness suite (judge-scored)")
@click.option("--spi", "spi_only", is_flag=True, help="Run only the SPI grounding suite")
@click.option("--limit", "-n", default=None, type=int,
              help="Only run the first N tasks of each suite")
@click.pass_context
def bench(ctx, fitness, spi_only, limit):
    """
    Quality gate: fitness (held-out tasks, oracle judge) + SPI (source
    grounding, deterministic). Run before shipping any harness change.
    """
    from scribe.evolve.evaluate import run_eval_cli
    from scribe.evolve.spi import run_spi_cli

    console = ctx.obj["console"]
    run_both = not (fitness or spi_only)
    if fitness or run_both:
        run_eval_cli(ctx.obj["config"], console, limit=limit, write_ledger=False)
    if spi_only or run_both:
        if run_both:
            console.print()
        run_spi_cli(ctx.obj["config"], console, limit=limit)


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
@click.option("--json", "as_json", is_flag=True,
              help="Emit the machine-readable status contract")
@click.pass_context
def status(ctx, as_json):
    """Check system status (server, capabilities, memory, bench)."""
    from scribe.status import collect_status, render_status

    console = ctx.obj["console"]
    config = ctx.obj["config"]
    report = collect_status(config)
    if as_json:
        click.echo(json.dumps(report, indent=2, ensure_ascii=False))
        return
    render_status(report, console)

    ecfg = config.email_config()
    if ecfg["enabled"] and ecfg["address"] and ecfg["password"]:
        intake = "commands ON" if ecfg["secret"] else "send-only (no secret)"
        console.print(f"[info]Email:[/info] {ecfg['address']} ({intake})")
    else:
        console.print("[dim]email: disabled[/dim]")


if __name__ == "__main__":
    main()
