"""
Configuration management for Scribe.

Loads config from:
1. Environment variables (highest priority)
2. config.toml in current directory
3. ~/.config/scribe/config.toml
4. Built-in defaults
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import toml


class ScribeConfig:
    """
    Configuration manager for Scribe.

    Handles loading from TOML files and environment variables.
    """

    DEFAULT_CONFIG = {
        "scribe": {
            "base_url": "http://127.0.0.1:18083/v1",
            "model": "default",
            "api_key": "not-needed",
            "system_prompt": "You are Scribe, an autonomous research and writing agent.",
            "sme_enabled": True,
            "rag_enabled": True,
            "reasoning": False,
            "reasoning_mode": "native",
            "tool_grammar": "auto",
            "workspace_dir": "~/scribe-workspace",
            "tools_enabled": True,
        },
        "scribe.rag": {
            "embedding_model": "intfloat/multilingual-e5-small",
            "index_dir": "~/.scribe/rag",
        },
        "scribe.sme": {
            "db_path": "~/.scribe/sme",
        },
        # Optional bridges to other local agents/tools. All empty by default —
        # Scribe then uses only its own paths. Point these at another agent's
        # data to share it (e.g. a common semantic-memory DB for two agents).
        "scribe.integrations": {
            "sme_path": "",
            "rag_path": "",
            "brave_env_file": "",
        },
        "scribe.ui": {
            "theme": "gruvbox-dark",
            "show_progress": True,
            "streaming": True,
        },
        "scribe.web": {
            "pin": "2020",
        },
        "scribe.email": {
            "enabled": False,
            "address": "",
            "approved_sender": "",
            "secret": "",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "poll_interval": 30,
        },
        "scribe.limits": {
            "max_context_tokens": 131072,
            "max_response_tokens": 8192,
            "request_timeout_seconds": 600,
            "max_thinking_words": 30,
        },
    }

    def __init__(self, config_path: str | Path | None = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to config.toml. If None, uses default search paths.
        """
        self.config_path = config_path
        # Deep copy: a shallow one would share the section dicts, so set() or
        # a loaded file would mutate DEFAULT_CONFIG for every later instance.
        self._config = copy.deepcopy(self.DEFAULT_CONFIG)
        self._load()

    def _load(self) -> None:
        """Load configuration from file and environment variables."""
        config_file = self._find_config_file()

        if config_file and config_file.exists():
            with open(config_file) as f:
                user_config = toml.load(f)
                self._merge_config(user_config)

        self._apply_env_overrides()

    def _find_config_file(self) -> Path | None:
        """Find the config file using standard search paths."""
        if self.config_path:
            return Path(self.config_path)

        search_paths = [
            Path.cwd() / "config.toml",
            Path.home() / ".config" / "scribe" / "config.toml",
            Path.home() / ".scribe" / "config.toml",
        ]

        for path in search_paths:
            if path.exists():
                return path

        return None

    def _merge_config(self, user_config: dict[str, Any]) -> None:
        """Deep merge user config into default config."""
        for section, values in user_config.items():
            if section in self._config:
                if isinstance(values, dict):
                    self._config[section].update(values)
                else:
                    self._config[section] = values
            else:
                self._config[section] = values

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        env_mappings = {
            "SCRIBE_BASE_URL": ("scribe", "base_url"),
            "SCRIBE_MODEL": ("scribe", "model"),
            "SCRIBE_API_KEY": ("scribe", "api_key"),
            "SCRIBE_SYSTEM_PROMPT": ("scribe", "system_prompt"),
            "SCRIBE_CONFIG": ("_meta", "config_path"),
        }

        for env_var, (section, key) in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                if section == "_meta":
                    continue
                if section not in self._config:
                    self._config[section] = {}
                self._config[section][key] = value

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get a config value using dot notation.

        Args:
            *keys: Section and key path (e.g., "scribe", "base_url")
            default: Default value if not found

        Returns:
            Config value or default
        """
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, section: str, key: str, value: Any) -> None:
        """Set a config value in memory (does not persist)."""
        self._config.setdefault(section, {})[key] = value

    def save_value(self, section: str, key: str, value: Any) -> Path:
        """
        Set a value in memory and persist it to the user config file.

        Writes to the first existing config file, or creates
        ~/.config/scribe/config.toml. Returns the path written to.
        """
        self.set(section, key, value)

        target = self._find_config_file() or (
            Path.home() / ".config" / "scribe" / "config.toml"
        )
        target.parent.mkdir(parents=True, exist_ok=True)

        existing: dict[str, Any] = {}
        if target.exists():
            try:
                existing = toml.load(target)
            except Exception:
                existing = {}
        existing.setdefault(section, {})[key] = value

        with open(target, "w") as f:
            toml.dump(existing, f)
        return target

    @property
    def base_url(self) -> str:
        """Get the LLM server base URL."""
        return self.get("scribe", "base_url")

    @property
    def model(self) -> str:
        """Get the model name."""
        return self.get("scribe", "model")

    @property
    def api_key(self) -> str:
        """Get the API key."""
        return self.get("scribe", "api_key")

    @property
    def system_prompt(self) -> str:
        """Get the default system prompt."""
        return self.get("scribe", "system_prompt")

    @property
    def sme_enabled(self) -> bool:
        """Check if SME is enabled."""
        return self.get("scribe", "sme_enabled", default=True)

    @property
    def rag_enabled(self) -> bool:
        """Check if RAG is enabled."""
        return self.get("scribe", "rag_enabled", default=True)

    @property
    def reasoning(self) -> bool | str:
        """
        Whether the model thinks before answering (step-by-step in a <think> block).
        true / false / "auto" — "auto" runs the per-request reasoning gate
        (think only when the prompt benefits from it). Off by default; toggle
        live with /reasoning in the TUI and web chat.
        """
        return self.get("scribe", "reasoning", default=False)

    @property
    def tool_grammar(self) -> str:
        """
        GBNF tool-call enforcement mode: "auto" (repair broken calls with a
        grammar-constrained retry, llama.cpp only), "force", or "off".
        """
        return str(self.get("scribe", "tool_grammar", default="auto"))

    @property
    def reasoning_mode(self) -> str:
        """
        How thinking is produced when reasoning is on: "native" (server-side
        enable_thinking, llama.cpp) or "prompt" (the model writes the <think>
        block itself — Ollama, LM Studio, ...).
        """
        return str(self.get("scribe", "reasoning_mode", default="native"))

    @property
    def workspace_dir(self) -> str:
        """Local working directory Scribe operates in (expanded absolute path)."""
        raw = self.get("scribe", "workspace_dir", default="~/scribe-workspace")
        return os.path.expanduser(raw)

    @property
    def tools_enabled(self) -> bool:
        """Whether the model can call sandboxed workspace file tools."""
        return self.get("scribe", "tools_enabled", default=True)

    def _expanded_path(self, section: str, key: str, default: str = "") -> str:
        """Read a path setting, expanded; empty string when unset."""
        raw = str(self.get(section, key, default=default) or "").strip()
        return os.path.expanduser(raw) if raw else ""

    @property
    def sme_db_path(self) -> str:
        """
        Directory of the semantic-memory (SME) LanceDB.

        `scribe.integrations.sme_path` wins when set (shared DB with another
        agent), otherwise `scribe.sme.db_path` (Scribe's own).
        """
        shared = self._expanded_path("scribe.integrations", "sme_path")
        return shared or self._expanded_path("scribe.sme", "db_path", "~/.scribe/sme")

    @property
    def rag_db_path(self) -> str:
        """
        Directory of the RAG LanceDB index.

        `scribe.integrations.rag_path` wins when set (shared library with
        another agent), otherwise `scribe.rag.index_dir` (Scribe's own).
        """
        shared = self._expanded_path("scribe.integrations", "rag_path")
        return shared or self._expanded_path("scribe.rag", "index_dir", "~/.scribe/rag")

    @property
    def brave_env_file(self) -> str:
        """Optional extra env file to read a Brave Search API key from."""
        return self._expanded_path("scribe.integrations", "brave_env_file")

    @property
    def theme(self) -> str:
        """Get the UI theme."""
        return self.get("scribe.ui", "theme", default="gruvbox-dark")

    @property
    def web_pin(self) -> str:
        """PIN that gates the web UI. Empty string disables the gate."""
        return str(self.get("scribe.web", "pin", default="2020"))

    @property
    def max_context_tokens(self) -> int:
        """Get the max context window size."""
        return self.get("scribe.limits", "max_context_tokens", default=131072)

    @property
    def max_response_tokens(self) -> int:
        """Get the max response token limit."""
        return self.get("scribe.limits", "max_response_tokens", default=8192)

    @property
    def request_timeout(self) -> int:
        """Get the request timeout in seconds."""
        return self.get("scribe.limits", "request_timeout_seconds", default=600)

    @property
    def max_thinking_words(self) -> int:
        """Upper bound (in words) for the <think> block. Keeps reasoning minimal."""
        return self.get("scribe.limits", "max_thinking_words", default=30)

    @property
    def email_enabled(self) -> bool:
        """Whether the email bridge (send + command intake) is turned on."""
        return bool(self.get("scribe.email", "enabled", default=False))

    def email_config(self) -> dict:
        """
        Assemble email settings. The app password is read from the
        SCRIBE_EMAIL_PASSWORD env var first (preferred), falling back to
        `app_password` in config.toml. Never store it in the repo.
        """
        password = os.environ.get("SCRIBE_EMAIL_PASSWORD") or self.get(
            "scribe.email", "app_password", default=""
        )
        return {
            "enabled": bool(self.get("scribe.email", "enabled", default=False)),
            "address": self.get("scribe.email", "address", default=""),
            "password": password,
            "approved_sender": self.get("scribe.email", "approved_sender", default=""),
            "secret": str(self.get("scribe.email", "secret", default="")),
            "smtp_host": self.get("scribe.email", "smtp_host", default="smtp.gmail.com"),
            "smtp_port": int(self.get("scribe.email", "smtp_port", default=587)),
            "imap_host": self.get("scribe.email", "imap_host", default="imap.gmail.com"),
            "imap_port": int(self.get("scribe.email", "imap_port", default=993)),
            "poll_interval": int(self.get("scribe.email", "poll_interval", default=30)),
        }

    def __repr__(self) -> str:
        return f"ScribeConfig(base_url={self.base_url}, model={self.model})"
