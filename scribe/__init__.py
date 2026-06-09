"""
Scribe - Autonomous Research & Writing Agent

Universal TUI agent that connects to any llama.cpp server and uses
RAG + semantic memory to research, write, and remember across sessions.
"""

__version__ = "0.2.1"
__author__ = "Predrag Urošević"

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.session import SessionManager

__all__ = ["LLMAdapter", "ScribeConfig", "SessionManager"]
