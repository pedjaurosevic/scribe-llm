"""
Web tools for Scribe — search the web using Brave Search and fetch page content.
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
    Search for Brave Search API Key in env vars, Scribe config, and Kon configs.
    """
    # 1. Environment variables
    key = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
    if key:
        return key.strip()

    # 2. Scribe Config (via config.toml)
    try:
        from scribe.config import ScribeConfig
        cfg = ScribeConfig()
        key = cfg.get("scribe", "brave_api_key") or cfg.get("scribe.search", "api_key")
        if key:
            return key.strip()
    except Exception:
        pass

    # 3. Kon environment files (standard location)
    for p in [Path.home() / ".kon" / ".env.brave", Path.home() / ".env"]:
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


def web_search(query: str, count: int = 5) -> str:
    """
    Search the web using the Brave Search API.
    """
    api_key = load_brave_api_key()
    if not api_key:
        return (
            "Error: Brave Search API key is not configured.\n"
            "Please add it to ~/.config/scribe/config.toml under [scribe] as brave_api_key=...\n"
            "or set the BRAVE_API_KEY environment variable."
        )

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
    except Exception as e:
        return f"Error querying Brave Search API: {e}"

    results = data.get("web", {}).get("results", [])
    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        link = r.get("url", "")
        snippet = r.get("description", "")
        lines.append(f"{i}. **{title}**")
        lines.append(f"   URL: {link}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
        lines.append("")

    return "\n".join(lines).strip()


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.ignore_tags = {"script", "style", "head", "nav", "footer", "meta", "link"}
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
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
            return text[:MAX_FETCH_CHARS] + f"\n\n... [Content truncated, {len(text)} characters total]"
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
                "Search the web using Brave Search. Returns titles, URLs, and text snippets."
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
