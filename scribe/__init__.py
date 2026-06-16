"""
Scribe - Autonomous Research & Writing Agent

Universal TUI agent that connects to any llama.cpp server and uses
RAG + semantic memory to research, write, and remember across sessions.
"""

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        # Single source of truth: the installed distribution's version, so
        # `scribe --version` always matches pyproject.toml / PyPI.
        __version__ = version("scribe-llm")
    except PackageNotFoundError:
        __version__ = "0.4.2"
except ImportError:  # pragma: no cover
    __version__ = "0.4.2"

__author__ = "Predrag Urošević"

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.session import SessionManager

__all__ = ["LLMAdapter", "ScribeConfig", "SessionManager"]
