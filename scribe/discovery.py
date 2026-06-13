"""
Model discovery — find OpenAI-compatible servers without hand-editing config.

Scans the common local serve ports (llama.cpp, vLLM, Ollama, LM Studio) on
localhost, plus any Tailscale peers when `tailscale` is available, and reports
which expose a `/v1/models` endpoint and what they serve. Lifted in spirit
from Odysseus, kept lean: pure stdlib + httpx, short timeouts, parallel probes.
"""

from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

# Common OpenAI-compatible serve ports. 18083 is Scribe's own default.
DEFAULT_PORTS = (18083, 8080, 8000, 8001, 1234, 11434, 5000)


@dataclass
class Endpoint:
    """A reachable OpenAI-compatible server."""

    host: str
    port: int
    models: list[str]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"


def _probe(host: str, port: int, timeout: float) -> Endpoint | None:
    """Probe one host:port for a /v1/models listing. None when unreachable."""
    try:
        r = httpx.get(f"http://{host}:{port}/v1/models", timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if models:
            return Endpoint(host=host, port=port, models=models)
    except Exception:
        pass
    return None


def tailscale_hosts() -> list[str]:
    """Peer IPs from `tailscale status`, or [] when Tailscale is absent."""
    if not shutil.which("tailscale"):
        return []
    try:
        out = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=4,
        )
        if out.returncode != 0:
            return []
        import json

        data = json.loads(out.stdout)
        hosts = []
        for peer in (data.get("Peer") or {}).values():
            ips = peer.get("TailscaleIPs") or []
            if ips:
                hosts.append(ips[0])
        return hosts
    except Exception:
        return []


def discover(
    hosts: list[str] | None = None,
    ports: tuple[int, ...] = DEFAULT_PORTS,
    include_tailscale: bool = False,
    timeout: float = 1.5,
) -> list[Endpoint]:
    """
    Scan host×port in parallel and return reachable endpoints, localhost first.
    """
    hosts = list(hosts or ["127.0.0.1"])
    if include_tailscale:
        for h in tailscale_hosts():
            if h not in hosts:
                hosts.append(h)

    targets = [(h, p) for h in hosts for p in ports]
    found: list[Endpoint] = []
    with ThreadPoolExecutor(max_workers=min(16, len(targets) or 1)) as pool:
        for ep in pool.map(lambda t: _probe(t[0], t[1], timeout), targets):
            if ep is not None:
                found.append(ep)

    # localhost endpoints first, then by host/port for stable output.
    def sort_key(ep: Endpoint):
        local = 0 if ep.host in ("127.0.0.1", "localhost") else 1
        return (local, ep.host, ep.port)

    return sorted(found, key=sort_key)
