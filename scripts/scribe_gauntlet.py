#!/usr/bin/env python3
"""One-hour-ish Scribe gauntlet.

This is a repeatable local benchmark for the parts that make Scribe different:
runtime health, grammar-constrained tool calls, web fetching, RAG grounding,
sandbox boundaries, and session continuity.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.memory.rag import RAGService
from scribe.prompts import FILE_WRITE_VERIFICATION_RULES, get_grounded_prompt
from scribe.session import SessionManager
from scribe.status import collect_status
from scribe.tools import fs, web
from scribe.tools.sandbox import gate_command


@dataclass
class Check:
    phase: str
    name: str
    ok: bool
    seconds: float
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class Gauntlet:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.started = getattr(args, "_run_started", None) or datetime.now().strftime(
            "%Y%m%d-%H%M%S"
        )
        suffix = getattr(args, "_run_suffix", "")
        stem = f"gauntlet-{self.started}{suffix}"
        if args.label:
            stem = f"{stem}-{_slug(args.label)}"
        self.out_dir = Path(args.out_dir) / stem
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.checks: list[Check] = []
        self.config = ScribeConfig()
        self.adapter = LLMAdapter.from_config(self.config)

    def record(self, phase: str, name: str, fn) -> Any:
        start = time.perf_counter()
        ok = False
        detail = ""
        data: dict[str, Any] = {}
        result = None
        try:
            result = fn()
            if isinstance(result, tuple):
                ok, detail, data = result
            else:
                ok = bool(result)
        except Exception as exc:  # noqa: BLE001 - benchmark must continue
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
        seconds = time.perf_counter() - start
        self.checks.append(Check(phase, name, ok, seconds, detail, data))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {phase} :: {name} ({seconds:.2f}s) {detail}")
        return result

    def run(self) -> int:
        self.preflight()
        self.tool_grammar()
        self.web_fetch()
        self.rag_grounding()
        self.sandbox_checks()
        self.session_checks()
        if not self.args.quick:
            self.agent_loop_probe()
        if self.args.hard:
            self.hard_web_synthesis()
            self.hard_rag_conflict()
            if not self.args.quick:
                self.hard_agent_loop_probe()
        self.write_reports()
        failed = [c for c in self.checks if not c.ok]
        return 1 if failed else 0

    def preflight(self) -> None:
        def status_check():
            status = collect_status(self.config)
            server = status.get("server", {})
            ok = (
                status.get("version") == "2.0.1"
                and server.get("reachable") is True
                and server.get("grammar_enforcement") is True
            )
            detail = (
                f"version={status.get('version')} reachable={server.get('reachable')} "
                f"grammar={server.get('grammar_enforcement')} model={server.get('model')}"
            )
            return ok, detail, {"status": status}

        def model_ping():
            answer = self.adapter.complete(
                [
                    {"role": "system", "content": "Answer with exactly: pong"},
                    {"role": "user", "content": "ping"},
                ],
                temperature=0,
                max_tokens=16,
            )
            return "pong" in answer.lower(), answer.strip(), {"answer": answer}

        self.record("preflight", "status contract", status_check)
        self.record("preflight", "model ping", model_ping)

    def tool_grammar(self) -> None:
        cases = [
            ("List the workspace root.", "list_dir"),
            ("Read the file named notes.md.", "read_file"),
            ("Create a directory named drafts.", "make_dir"),
            ("Write hello to notes/hello.txt.", "write_file"),
        ]

        for prompt, expected in cases:
            def run_case(prompt=prompt, expected=expected):
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "Return exactly one tool call for the user's request. "
                            "Do not answer in prose."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
                calls = self.adapter.forced_tool_call(
                    messages,
                    fs.TOOL_SCHEMAS,
                    temperature=0,
                    max_tokens=160,
                )
                got = calls[0]["name"] if calls else ""
                args = calls[0].get("arguments", "") if calls else ""
                valid_json = True
                try:
                    json.loads(args or "{}")
                except json.JSONDecodeError:
                    valid_json = False
                ok = got == expected and valid_json
                return ok, f"expected={expected} got={got}", {"calls": calls}

            self.record("tool_grammar", expected, run_case)

    @contextlib.contextmanager
    def local_site(self):
        with tempfile.TemporaryDirectory(prefix="scribe-gauntlet-web-") as td:
            root = Path(td)
            (root / "index.html").write_text(
                """
                <html><head><title>Scribe Gauntlet</title><style>.x{}</style></head>
                <body><nav>ignore navigation</nav>
                <h1>Scribe Gauntlet Alpha</h1>
                <p>The control answer is amber-lake-42.</p>
                <p>The scraping test should ignore scripts and keep paragraphs.</p>
                <script>var hidden = 'do-not-read';</script>
                </body></html>
                """,
                encoding="utf-8",
            )
            (root / "large.html").write_text(
                "<html><body>" + "<p>chunk marker zeta.</p>" * 1200 + "</body></html>",
                encoding="utf-8",
            )

            class Handler(SimpleHTTPRequestHandler):
                def log_message(self, format, *args):  # noqa: A002
                    return

            old_cwd = Path.cwd()
            os.chdir(root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{server.server_port}"
            finally:
                server.shutdown()
                server.server_close()
                os.chdir(old_cwd)

    def web_fetch(self) -> None:
        with self.local_site() as base:
            def fetch_index():
                text = web.web_fetch(f"{base}/index.html")
                ok = "amber-lake-42" in text and "do-not-read" not in text
                return ok, f"chars={len(text)}", {"text_sample": text[:500]}

            def fetch_large():
                text = web.web_fetch(f"{base}/large.html")
                ok = "chunk marker zeta" in text and len(text) <= web.MAX_FETCH_CHARS + 200
                return ok, f"chars={len(text)}", {}

            def fetch_missing():
                text = web.web_fetch(f"{base}/missing.html")
                ok = text.startswith("Error fetching URL:")
                return ok, text[:160], {}

            def synthesize():
                fetched = web.web_fetch(f"{base}/index.html")
                answer = self.adapter.complete(
                    [
                        {
                            "role": "system",
                            "content": "Answer only from the fetched page text. Keep it short.",
                        },
                        {
                            "role": "user",
                            "content": f"What is the control answer?\n\nPAGE:\n{fetched}",
                        },
                    ],
                    temperature=0,
                    max_tokens=80,
                )
                ok = "amber-lake-42" in answer
                return ok, answer.strip(), {"answer": answer}

            self.record("web_fetch", "local html extraction", fetch_index)
            self.record("web_fetch", "large page truncation", fetch_large)
            self.record("web_fetch", "missing URL error", fetch_missing)
            self.record("web_fetch", "LLM synthesis from fetched page", synthesize)

    def rag_grounding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scribe-gauntlet-rag-") as td:
            root = Path(td)
            docs = root / "docs"
            docs.mkdir()
            (docs / "alpha.md").write_text(
                "# Alpha\n\nProject Helios uses codename amber-lake-42 for release notes.",
                encoding="utf-8",
            )
            (docs / "beta.md").write_text(
                "# Beta\n\nProject Helios owner is Mira. Deployment window is Friday.",
                encoding="utf-8",
            )
            (docs / "conflict.md").write_text(
                "# Conflict\n\nProject Helios owner is Nikola, according to an older note.",
                encoding="utf-8",
            )
            rag = RAGService(db_path=root / "rag")
            for path in docs.iterdir():
                rag.ingest_file(path)

            def retrieval():
                hits = rag.hybrid_search("What is the Helios codename?", limit=3)
                joined = "\n".join(h.content for h in hits)
                ok = "amber-lake-42" in joined
                return ok, f"hits={len(hits)}", {"hits": [h.to_dict() for h in hits]}

            def grounded_answer():
                chunks = rag.hybrid_search("What is the Helios codename?", limit=4)
                answer = self.adapter.complete(
                    [
                        {"role": "system", "content": get_grounded_prompt(chunks)},
                        {"role": "user", "content": "What is the Helios codename?"},
                    ],
                    temperature=0,
                    max_tokens=160,
                )
                ok = "amber-lake-42" in answer and re.search(r"\[\d+\]", answer) is not None
                return ok, answer.strip(), {"answer": answer}

            def unsupported_answer():
                chunks = rag.hybrid_search("What is the Helios budget?", limit=4)
                answer = self.adapter.complete(
                    [
                        {"role": "system", "content": get_grounded_prompt(chunks)},
                        {"role": "user", "content": "What is the Helios budget?"},
                    ],
                    temperature=0,
                    max_tokens=120,
                )
                ok = "do not cover" in answer.lower()
                return ok, answer.strip(), {"answer": answer}

            self.record("rag", "hybrid retrieval finds control fact", retrieval)
            self.record("rag", "grounded answer cites source", grounded_answer)
            self.record("rag", "unsupported question refuses", unsupported_answer)

    def sandbox_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scribe-gauntlet-ws-") as td:
            workspace = Path(td)
            (workspace / "safe.txt").write_text("safe", encoding="utf-8")

            def path_escape():
                result = fs.dispatch(workspace, "read_file", {"path": "../safe.txt"})
                return result.startswith("Error:"), result, {}

            def normal_write():
                result = fs.dispatch(
                    workspace,
                    "write_file",
                    {"path": "notes/result.txt", "content": "ok"},
                )
                ok = (workspace / "notes" / "result.txt").read_text(encoding="utf-8") == "ok"
                return ok, result, {}

            def destructive_gate():
                reason = gate_command("rm -rf $HOME")
                return reason is not None, reason or "not refused", {}

            self.record("sandbox", "workspace path escape blocked", path_escape)
            self.record("sandbox", "normal workspace write allowed", normal_write)
            self.record("sandbox", "destructive command gate", destructive_gate)

    def session_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scribe-gauntlet-session-") as td:
            cfg = ScribeConfig()
            cfg.set("scribe", "workspace_dir", str(Path(td) / "workspace"))
            manager = SessionManager(cfg)

            def checkpoint_and_search():
                session = manager.start_session(topic="gauntlet", language_game="chat")
                manager.add_message("user", "Remember gauntlet-token-77.")
                manager.add_message("assistant", "Stored gauntlet-token-77 in this session.")
                manager.checkpoint()
                hits = manager.search_transcripts("gauntlet-token-77", limit=5)
                ok = bool(hits) and manager.transcript_path(session.session_id).exists()
                return ok, f"hits={len(hits)} session={session.session_id}", {"hits": hits}

            self.record("session", "checkpoint transcript search", checkpoint_and_search)

    def agent_loop_probe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scribe-gauntlet-agent-") as td:
            workspace = Path(td)

            def loop_once():
                messages: list[dict[str, Any]] = [
                    {
                        "role": "system",
                        "content": (
                            "You are Scribe in a test workspace. Use tools to create "
                            "answer.txt containing exactly gauntlet-agent-ok."
                        ),
                    },
                    {"role": "user", "content": "Create the requested file now."},
                ]
                final = ""
                for _ in range(4):
                    tool_calls = None
                    answer = ""
                    for kind, payload in self.adapter.streaming_turn(
                        messages,
                        tools=fs.TOOL_SCHEMAS,
                        temperature=0,
                        max_tokens=240,
                    ):
                        if kind == "answer":
                            answer += payload
                        elif kind == "tool_calls":
                            tool_calls = payload
                    if not tool_calls:
                        final = answer
                        break
                    messages.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "tool_calls": [
                                {
                                    "id": c["id"],
                                    "type": "function",
                                    "function": {
                                        "name": c["name"],
                                        "arguments": c["arguments"],
                                    },
                                }
                                for c in tool_calls
                            ],
                        }
                    )
                    for call in tool_calls:
                        result = fs.dispatch(workspace, call["name"], call["arguments"])
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": result,
                            }
                        )
                target = workspace / "answer.txt"
                ok = target.exists() and target.read_text(encoding="utf-8").strip() == (
                    "gauntlet-agent-ok"
                )
                return ok, final.strip()[:200], {"workspace": str(workspace)}

            self.record("agent_loop", "create file through tool loop", loop_once)

    def hard_web_synthesis(self) -> None:
        with self.local_site() as base:
            def multipage_fetch_and_summarize():
                # Create an extra page in the server root by using the fact that
                # local_site chdir'd into it while the context is active.
                Path("timeline.html").write_text(
                    """
                    <html><body>
                    <h1>Helios Timeline</h1>
                    <p>Phase one starts on Monday.</p>
                    <p>Phase two starts on Wednesday.</p>
                    <p>The release owner for timeline work is Mira.</p>
                    </body></html>
                    """,
                    encoding="utf-8",
                )
                page_a = web.web_fetch(f"{base}/index.html")
                page_b = web.web_fetch(f"{base}/timeline.html")
                answer = self.adapter.complete(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Answer only from the two page texts. Return one short "
                                "sentence containing the control answer and the owner."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"PAGE A:\n{page_a}\n\nPAGE B:\n{page_b}\n\n"
                                "What are the control answer and timeline owner?"
                            ),
                        },
                    ],
                    temperature=0,
                    max_tokens=120,
                )
                ok = "amber-lake-42" in answer and "Mira" in answer
                return ok, answer.strip(), {"answer": answer}

            self.record("hard_web", "multi-page local synthesis", multipage_fetch_and_summarize)

    def hard_rag_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scribe-gauntlet-hard-rag-") as td:
            root = Path(td)
            docs = root / "docs"
            docs.mkdir()
            (docs / "owner-a.md").write_text(
                "# Owner A\n\nThe current owner of Project Helios is Mira.",
                encoding="utf-8",
            )
            (docs / "owner-b.md").write_text(
                "# Owner B\n\nThe current owner of Project Helios is Nikola.",
                encoding="utf-8",
            )
            rag = RAGService(db_path=root / "rag")
            for path in docs.iterdir():
                rag.ingest_file(path)

            def conflict_answer():
                chunks = rag.hybrid_search("Who is the current owner of Project Helios?", limit=4)
                answer = self.adapter.complete(
                    [
                        {"role": "system", "content": get_grounded_prompt(chunks)},
                        {"role": "user", "content": "Who is the current owner of Project Helios?"},
                    ],
                    temperature=0,
                    max_tokens=220,
                )
                low = answer.lower()
                ok = "mira" in low and "nikola" in low and "contradiction" in low
                return (
                    ok,
                    answer.strip(),
                    {"answer": answer, "chunks": [c.to_dict() for c in chunks]},
                )

            self.record("hard_rag", "conflicting sources are marked", conflict_answer)

    def hard_agent_loop_probe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scribe-gauntlet-hard-agent-") as td:
            workspace = Path(td)

            def multi_step_loop():
                transcript: list[dict[str, Any]] = []
                messages: list[dict[str, Any]] = [
                    {
                        "role": "system",
                        "content": (
                            "You are Scribe in a test workspace. Use tools only. "
                            "Create data/input.txt with 'alpha beta gamma'. Then read it, "
                            "create reports/summary.md with exactly one line of content:\n\n"
                            "```text\n"
                            "Summary: alpha beta gamma.\n"
                            "```\n\n"
                            f"{FILE_WRITE_VERIFICATION_RULES}"
                        ),
                    },
                    {"role": "user", "content": "Complete the multi-step file task."},
                ]
                final = ""
                for _ in range(8):
                    tool_calls = None
                    answer = ""
                    for kind, payload in self.adapter.streaming_turn(
                        messages,
                        tools=fs.TOOL_SCHEMAS,
                        temperature=0,
                        max_tokens=320,
                    ):
                        if kind == "answer":
                            answer += payload
                        elif kind == "tool_calls":
                            tool_calls = payload
                    if not tool_calls:
                        final = answer
                        transcript.append({"role": "assistant", "content": answer})
                        break
                    transcript.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "tool_calls": tool_calls,
                        }
                    )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "tool_calls": [
                                {
                                    "id": c["id"],
                                    "type": "function",
                                    "function": {
                                        "name": c["name"],
                                        "arguments": c["arguments"],
                                    },
                                }
                                for c in tool_calls
                            ],
                        }
                    )
                    for call in tool_calls:
                        result = fs.dispatch(workspace, call["name"], call["arguments"])
                        transcript.append(
                            {
                                "role": "tool",
                                "name": call["name"],
                                "arguments": call["arguments"],
                                "content": result,
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": result,
                            }
                        )

                target = workspace / "reports" / "summary.md"
                content = target.read_text(encoding="utf-8") if target.exists() else ""
                ok = "Summary: alpha beta gamma." in content
                return (
                    ok,
                    final.strip()[:200],
                    {
                        "workspace": str(workspace),
                        "content": content,
                        "transcript": transcript,
                    },
                )

            self.record("hard_agent_loop", "multi-step read/write workflow", multi_step_loop)

    def write_reports(self) -> None:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.ok)
        data = {
            "started": self.started,
            "label": self.args.label,
            "run_index": getattr(self.args, "_run_index", 1),
            "summary": {
                "passed": passed,
                "failed": total - passed,
                "total": total,
                "pass_rate": passed / total if total else 0,
            },
            "checks": [asdict(c) for c in self.checks],
        }
        (self.out_dir / "result.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        lines = [
            "# Scribe Gauntlet Report",
            "",
            f"- started: {self.started}",
            f"- passed: {passed}/{total}",
            f"- failed: {total - passed}",
            "",
            "| Phase | Check | Result | Seconds | Detail |",
            "|---|---|---:|---:|---|",
        ]
        for c in self.checks:
            result = "PASS" if c.ok else "FAIL"
            detail = c.detail.replace("\n", " ")[:300]
            lines.append(f"| {c.phase} | {c.name} | {result} | {c.seconds:.2f} | {detail} |")
        (self.out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nReport: {self.out_dir / 'report.md'}")
        print(f"JSON:   {self.out_dir / 'result.json'}")


def _slug(text: str) -> str:
    """Filesystem-friendly label fragment."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip()).strip("-").lower()
    return slug[:48] or "run"


def _write_series_report(
    out_dir: Path,
    series_started: str,
    label: str,
    runs: list[dict[str, Any]],
    elapsed: float,
) -> tuple[Path, Path]:
    total_checks = sum(r["summary"]["total"] for r in runs)
    total_passed = sum(r["summary"]["passed"] for r in runs)
    total_failed = sum(r["summary"]["failed"] for r in runs)
    data = {
        "started": series_started,
        "label": label,
        "elapsed_seconds": elapsed,
        "summary": {
            "runs": len(runs),
            "passed": total_passed,
            "failed": total_failed,
            "total": total_checks,
            "pass_rate": total_passed / total_checks if total_checks else 0,
        },
        "runs": runs,
    }
    suffix = f"-{_slug(label)}" if label else ""
    json_path = out_dir / f"series-{series_started}{suffix}.json"
    md_path = out_dir / f"series-{series_started}{suffix}.md"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Scribe Gauntlet Series",
        "",
        f"- started: {series_started}",
        f"- label: {label or '(none)'}",
        f"- elapsed seconds: {elapsed:.2f}",
        f"- runs: {len(runs)}",
        f"- passed: {total_passed}/{total_checks}",
        f"- failed: {total_failed}",
        "",
        "| Run | Passed | Failed | Checks | Check Seconds | Report |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for run in runs:
        seconds = sum(c["seconds"] for c in run["checks"])
        report = Path(run["report"]).name
        lines.append(
            f"| {run['run_dir']} | {run['summary']['passed']} | "
            f"{run['summary']['failed']} | {run['summary']['total']} | "
            f"{seconds:.2f} | {report} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def run_series(args: argparse.Namespace) -> int:
    """Run one or more gauntlet passes and write an aggregate report."""
    series_started = datetime.now().strftime("%Y%m%d-%H%M%S")
    deadline = (
        time.monotonic() + args.duration_minutes * 60
        if args.duration_minutes and args.duration_minutes > 0
        else None
    )
    target_runs = max(1, args.repetitions)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    exit_code = 0
    started_perf = time.perf_counter()
    idx = 1
    while True:
        if idx > target_runs and deadline is None:
            break
        if deadline is not None and idx > target_runs and time.monotonic() >= deadline:
            break

        args._run_started = series_started
        args._run_index = idx
        args._run_suffix = f"-r{idx:03d}"
        print(f"\n=== Scribe gauntlet run {idx} ===")
        code = Gauntlet(args).run()
        exit_code = max(exit_code, code)

        result_path = sorted(out_dir.glob(f"gauntlet-{series_started}-r{idx:03d}*/result.json"))[-1]
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["run_dir"] = result_path.parent.name
        result["report"] = str(result_path.parent / "report.md")
        result["json"] = str(result_path)
        runs.append(result)
        idx += 1

        if deadline is not None and time.monotonic() >= deadline and idx > target_runs:
            break

    elapsed = time.perf_counter() - started_perf
    md_path, json_path = _write_series_report(out_dir, series_started, args.label, runs, elapsed)
    print(f"\nSeries report: {md_path}")
    print(f"Series JSON:   {json_path}")
    return exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Scribe gauntlet benchmark.")
    parser.add_argument("--out-dir", default="bench/results", help="Where to write reports.")
    parser.add_argument("--label", default="", help="Optional label for this run/series.")
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Number of gauntlet passes to run.",
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=0.0,
        help=(
            "Keep running until this many minutes have elapsed. If combined with "
            "--repetitions, runs at least that many passes."
        ),
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip the final multi-turn agent-loop probe.",
    )
    parser.add_argument(
        "--hard",
        action="store_true",
        help="Run stricter conflict, multi-page, and multi-step checks.",
    )
    return parser.parse_args()


def main() -> int:
    return run_series(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
