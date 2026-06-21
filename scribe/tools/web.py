"""
Web tools for Scribe — search the web and fetch page content.

Search uses the Brave Search API when a key is configured, and falls back to
DuckDuckGo's HTML endpoint (no API key needed) otherwise, so research works
out of the box.
"""

from __future__ import annotations

import gzip
import json
import os
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# Maximum characters returned by web_fetch to avoid blowing up the context window.
MAX_FETCH_CHARS = 15000


def load_brave_api_key() -> str | None:
    """
    Search for a Brave Search API key in env vars, Scribe config, and env files
    (the configured `scribe.integrations.brave_env_file`, then ~/.env).
    """
    # 1. Environment variables
    key = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
    if key:
        return key.strip()

    # 2. Scribe Config (via config.toml)
    env_files = [Path.home() / ".env"]
    try:
        from scribe.config import ScribeConfig
        cfg = ScribeConfig()
        key = cfg.get("scribe", "brave_api_key") or cfg.get("scribe.search", "api_key")
        if key:
            return key.strip()
        if cfg.brave_env_file:
            env_files.insert(0, Path(cfg.brave_env_file))
    except Exception:
        pass

    # 3. Env files (configured integration file first, then the generic ~/.env)
    for p in env_files:
        try:
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() in ("BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"):
                            return v.strip()
        except Exception:
            pass

    return None


class _DuckDuckGoParser(HTMLParser):
    """
    Extract results from the DuckDuckGo HTML endpoint (html.duckduckgo.com).

    Each result is an <a class="result__a" href="...">Title</a> followed by an
    element with class "result__snippet". Hrefs are DDG redirect links carrying
    the real URL in the `uddg` query parameter.
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False

    @staticmethod
    def _real_url(href: str) -> str:
        if "uddg=" in href:
            qs = urllib.parse.urlparse(href).query
            target = urllib.parse.parse_qs(qs).get("uddg", [""])[0]
            if target:
                return target
        return href

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag == "a" and "result__a" in cls:
            self._in_title = True
            self.results.append({
                "title": "",
                "url": self._real_url(dict(attrs).get("href", "")),
                "snippet": "",
            })
        elif "result__snippet" in cls and self.results:
            self._in_snippet = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title:
            self._in_title = False
        elif self._in_snippet and tag in ("a", "td", "div", "span"):
            self._in_snippet = False

    def handle_data(self, data):
        if not self.results:
            return
        if self._in_title:
            self.results[-1]["title"] += data
        elif self._in_snippet:
            self.results[-1]["snippet"] += data


def _format_results(results: list[dict[str, str]], engine: str) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title") or "(no title)"
        lines.append(f"{i}. **{title.strip()}**")
        lines.append(f"   URL: {r.get('url', '')}")
        snippet = (r.get("snippet") or "").strip()
        if snippet:
            lines.append(f"   Snippet: {snippet}")
        lines.append("")
    lines.append(f"[search engine: {engine}]")
    return "\n".join(lines).strip()


def duckduckgo_search(query: str, count: int = 5) -> str:
    """
    Search the web with DuckDuckGo's HTML endpoint — no API key required.

    Used as the default engine when no Brave Search API key is configured, so
    research works out of the box.
    """
    params = urllib.parse.urlencode({"q": query.strip()})
    request = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?{params}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "text/html",
            "Accept-Encoding": "gzip",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_data = response.read()
            if "gzip" in (response.headers.get("Content-Encoding") or "").lower():
                raw_data = gzip.decompress(raw_data)
            html = raw_data.decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error querying DuckDuckGo: {e}"

    parser = _DuckDuckGoParser()
    try:
        parser.feed(html)
    except Exception as e:
        return f"Error parsing DuckDuckGo results: {e}"

    results = parser.results[: min(max(1, count), 10)]
    if not results:
        return "No results found."
    return _format_results(results, "DuckDuckGo")


def web_search(query: str, count: int = 5) -> str:
    """
    Search the web. Uses the Brave Search API when a key is configured,
    otherwise falls back to DuckDuckGo (no key needed).
    """
    api_key = load_brave_api_key()
    if not api_key:
        return duckduckgo_search(query, count)

    params = urllib.parse.urlencode({
        "q": query.strip(),
        "count": min(max(1, count), 10),
    })
    req_url = f"https://api.search.brave.com/res/v1/web/search?{params}"

    request = urllib.request.Request(
        req_url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
            "User-Agent": "ScribeAgent/0.2.1"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_data = response.read()
            encoding = response.headers.get("Content-Encoding", "")
            if "gzip" in encoding.lower():
                raw_data = gzip.decompress(raw_data)
            data = json.loads(raw_data.decode("utf-8"))
    except Exception:
        # Brave is down or the key is bad — research should still work.
        return duckduckgo_search(query, count)

    results = data.get("web", {}).get("results", [])
    if not results:
        return "No results found."

    normalized = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("description", ""),
        }
        for r in results
    ]
    return _format_results(normalized, "Brave Search")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.ignore_tags = {"script", "style", "head", "nav", "footer"}
        self.ignore_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.ignore_tags:
            self.ignore_depth += 1
        elif tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"}:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in self.ignore_tags:
            self.ignore_depth = max(0, self.ignore_depth - 1)

    def handle_data(self, data):
        if self.ignore_depth == 0:
            cleaned = data.strip()
            if cleaned:
                self.text.append(cleaned)


def web_fetch(url: str) -> str:
    """
    Fetch web page contents and extract readable text.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept-Encoding": "gzip",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_data = response.read()
            encoding = response.headers.get("Content-Encoding", "")
            if "gzip" in encoding.lower():
                raw_data = gzip.decompress(raw_data)

            try:
                html = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                html = raw_data.decode("latin-1", errors="replace")
    except Exception as e:
        return f"Error fetching URL: {e}"

    try:
        extractor = TextExtractor()
        extractor.feed(html)
        text = "\n".join(extractor.text)

        # Collapse multi-newlines
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")

        text = text.strip()
        if len(text) > MAX_FETCH_CHARS:
            truncated_note = f"\n\n... [Content truncated, {len(text)} characters total]"
            return text[:MAX_FETCH_CHARS] + truncated_note
        return text
    except Exception as e:
        return f"Error parsing web page content: {e}"


# OpenAI-style tool schemas
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web (Brave Search when an API key is configured, "
                "DuckDuckGo otherwise). Returns titles, URLs, and text snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to send to Brave Search.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of results to retrieve (default 5, max 10).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a web page by URL and extract readable text content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL of the webpage to fetch.",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

_DISPATCH = {
    "web_search": web_search,
    "web_fetch": web_fetch,
}


def dispatch(name: str, arguments: str | dict[str, Any]) -> str:
    """
    Execute a web tool call.
    """
    func = _DISPATCH.get(name)
    if func is None:
        return f"Error: unknown tool '{name}'"

    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError as e:
            return f"Error: invalid arguments for {name}: {e}"
    else:
        args = dict(arguments or {})

    try:
        return func(**args)
    except Exception as e:
        return f"Error running {name}: {e}"
