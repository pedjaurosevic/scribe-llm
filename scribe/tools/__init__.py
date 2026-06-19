"""
Tool integrations for Scribe.

Provides wrappers around external tools like web search, web fetch, and bash.
"""

from __future__ import annotations

import subprocess
from typing import Any


def web_search(query: str, count: int = 5) -> list[dict[str, str]]:
    """
    Search the web using DuckDuckGo.

    Args:
        query: Search query
        count: Number of results to return

    Returns:
        List of dicts with 'title', 'url', 'snippet'
    """
    try:
        result = subprocess.run(
            ["ddgr", "-n", str(count), "--json", query],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            import json
            results = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    try:
                        data = json.loads(line)
                        results.append({
                            "title": data.get("title", ""),
                            "url": data.get("url", ""),
                            "snippet": data.get("body", ""),
                        })
                    except json.JSONDecodeError:
                        continue
            return results
    except FileNotFoundError:
        pass

    return []


def web_fetch(url: str, timeout: int = 30) -> dict[str, Any]:
    """
    Fetch and parse a web page.

    Args:
        url: URL to fetch
        timeout: Request timeout

    Returns:
        Dict with 'title', 'content', 'url'
    """
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return {
                "url": url,
                "content": result.stdout[:10000],
                "title": url,
            }
    except Exception:
        pass

    return {"url": url, "content": "", "title": ""}


def bash(command: str, timeout: int = 60) -> dict[str, Any]:
    """
    Execute a bash command.

    Routes through the sandbox command gate to refuse obviously destructive
    commands (recursive rm on /, mkfs, fork bombs, etc.).

    Args:
        command: Command to execute
        timeout: Timeout in seconds

    Returns:
        Dict with 'stdout', 'stderr', 'returncode'
    """
    from scribe.tools.sandbox import gate_command

    reason = gate_command(command)
    if reason:
        return {
            "stdout": "",
            "stderr": f"[refused] command gate: {reason}",
            "returncode": 1,
        }
    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
