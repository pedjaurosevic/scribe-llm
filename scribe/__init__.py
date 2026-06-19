"""
Scribe - Autonomous Research & Writing Agent

Universal TUI agent that connects to any llama.cpp server and uses
RAG + semantic memory to research, write, and remember across sessions.
"""

# Silence warning from torchao about incompatible PyTorch version
import logging

logging.getLogger("torchao").setLevel(logging.ERROR)

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        # Single source of truth: the installed distribution's version, so
        # `scribe-llm --version` always matches pyproject.toml / PyPI.
        __version__ = version("scribe-llm")
    except PackageNotFoundError:
        __version__ = "1.5.0"
except ImportError:  # pragma: no cover
    __version__ = "1.5.0"

__author__ = "Peterofovik"

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.session import SessionManager

__all__ = ["LLMAdapter", "ScribeConfig", "SessionManager"]
