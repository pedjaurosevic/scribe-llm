"""
Execution sandbox — let the agent try more because it can break less.

Three independent layers, each degrading gracefully when unavailable:

1. Command gate: a cheap pattern check that refuses obviously destructive
   shell commands (recursive rm on /, mkfs, raw dd to block devices, fork
   bombs, ...) before anything runs. Always on for agent-issued commands.
2. AST gate: for Python code the agent wrote, parse and refuse modules and
   calls that have no business in generated code (ctypes, os.system, ...).
3. bubblewrap: when `bwrap` is installed, agent commands run in a container
   with a read-only root, the workspace bind-mounted read-write, no network,
   and CPU/memory rlimits. Without bwrap only the gates apply.
"""

from __future__ import annotations

import ast
import re
import resource
import shutil
import subprocess

# ── Layer 1: command gate ──────────────────────────────────────────────────

# Each entry: (compiled pattern, human reason). Tuned for catastrophes, not
# for policing the user — interactive commands the user confirmed still pass
# through this gate, so false positives must stay near zero.
_DENY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*[rR])[a-zA-Z]*\s+(/|~|\$HOME)(\s|$|\*)"),
     "recursive force-delete of / or home"),
    (re.compile(r"\bmkfs(\.\w+)?\b"), "filesystem format"),
    (re.compile(r"\bdd\b[^|;&]*\bof=/dev/(sd|nvme|vd|hd|mmcblk)"), "raw write to block device"),
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;"), "fork bomb"),
    (re.compile(r"\b(shutdown|reboot|poweroff|halt)\b"), "power control"),
    (re.compile(r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?[0-7]{3,4}\s+/(\s|$)"), "recursive chmod of /"),
    (re.compile(r">\s*/dev/(sd|nvme|vd|hd|mmcblk)"), "redirect onto block device"),
    (re.compile(r"\bgit\s+push\s+[^|;&]*--force"), "force push"),
]


def gate_command(command: str) -> str | None:
    """Reason the command is refused, or None when it may run."""
    for pattern, reason in _DENY_PATTERNS:
        if pattern.search(command):
            return reason
    return None


# ── Layer 2: AST gate for generated Python ─────────────────────────────────

_BLOCKED_MODULES = {"ctypes", "multiprocessing", "socketserver"}
_BLOCKED_CALLS = {
    ("os", "system"), ("os", "execv"), ("os", "execve"), ("os", "fork"),
    ("os", "kill"), ("os", "killpg"), ("shutil", "rmtree"),
}


def gate_python(code: str) -> str | None:
    """
    Reason the Python source is refused, or None when it may run.

    A syntax error is itself a refusal: code that does not parse should be
    fixed, not executed.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"syntax error: {exc.msg} (line {exc.lineno})"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_MODULES:
                    return f"blocked module: {root}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _BLOCKED_MODULES:
                return f"blocked module: {root}"
        elif isinstance(node, ast.Call):
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and (fn.value.id, fn.attr) in _BLOCKED_CALLS
            ):
                return f"blocked call: {fn.value.id}.{fn.attr}"
            if isinstance(fn, ast.Name) and fn.id in ("eval", "exec"):
                return f"blocked call: {fn.id}"
    return None


# ── Layer 3: bubblewrap container ──────────────────────────────────────────

def bwrap_available() -> bool:
    """Whether the bubblewrap binary is on PATH."""
    return shutil.which("bwrap") is not None


def wrap_argv(command: str, workspace: str, network: bool = False) -> list[str]:
    """
    bubblewrap argv for one bash command: read-only root, the workspace
    bind-mounted read-write, fresh /tmp, no network unless asked for.
    """
    # The workspace bind comes AFTER the /tmp tmpfs: mounts apply in order,
    # and a workspace living under /tmp (pytest tmp dirs) must not be
    # shadowed by the fresh tmpfs.
    argv = [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--bind", workspace, workspace,
        "--die-with-parent",
        "--chdir", workspace,
    ]
    if not network:
        argv.append("--unshare-net")
    argv += ["bash", "-c", command]
    return argv


def _rlimits(timeout: int):
    """preexec_fn applying CPU and memory ceilings to the child."""
    def apply() -> None:
        cpu = max(timeout, 30)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        mem = 4 * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    return apply


def run_sandboxed(
    command: str,
    workspace: str,
    timeout: int = 120,
    network: bool = False,
) -> subprocess.CompletedProcess[str]:
    """
    Run one bash command inside the sandbox (bwrap when available, rlimits
    always). The command gate is the caller's responsibility — this function
    only contains, it does not judge.
    """
    if bwrap_available():
        argv: list[str] | str = wrap_argv(command, workspace, network=network)
        shell = False
    else:
        argv = command
        shell = True
    return subprocess.run(
        argv,
        shell=shell,
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout,
        preexec_fn=_rlimits(timeout),
        executable="/bin/bash" if shell else None,
    )
