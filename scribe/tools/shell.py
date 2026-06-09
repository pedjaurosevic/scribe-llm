"""
Shell tool for Scribe Code mode — run arbitrary bash commands.

Unlike the sandboxed filesystem tools in `fs.py`, this gives the model full
shell access on the user's machine. It is only advertised in `/code` mode, and
in the TUI every command is shown and confirmed before it runs.

Each call is an independent subprocess, so there is no persistent shell state
(no surviving `cd`); chain with `cd /path && cmd` when a directory matters.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

# Cap how much command output is read back into the context.
MAX_OUTPUT_CHARS = 10_000
DEFAULT_TIMEOUT = 120


def run_command(command: str, cwd: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """
    Run a bash command and return its combined stdout/stderr plus exit code.

    Never raises — failures (non-zero exit, timeout, spawn error) come back as
    text so the model can read and react to them.
    """
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            executable="/bin/bash",
        )
    except subprocess.TimeoutExpired:
        return f"[timeout] command exceeded {timeout}s"
    except Exception as e:  # pragma: no cover - defensive
        return f"Error running command: {e}"

    out = (proc.stdout or "") + (proc.stderr or "")
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(out)} chars total]"

    header = f"[exit {proc.returncode}]"
    return f"{header}\n{out}".rstrip() if out.strip() else header


# OpenAI-style tool schema advertised to the model in code mode.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": (
                "Run a bash command on the user's machine and return its output "
                "and exit code. You have full shell access. Each call is a fresh "
                "subprocess, so chain with 'cd /path && cmd' when the working "
                "directory matters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to run",
                    },
                },
                "required": ["command"],
            },
        },
    },
]


def parse_command(arguments: str | dict[str, Any]) -> str:
    """Extract the `command` string from JSON or dict tool arguments."""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return ""
    else:
        args = dict(arguments or {})
    return str(args.get("command", "")).strip()


def dispatch(
    cwd: Path,
    name: str,
    arguments: str | dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    Execute a shell tool call by name with JSON (or dict) arguments.

    Returns a short result string (also fed back to the model). Never raises.
    """
    if name != "run_bash":
        return f"Error: unknown tool '{name}'"

    command = parse_command(arguments)
    if not command:
        return "Error: empty command"

    return run_command(command, cwd=str(cwd), timeout=timeout)
