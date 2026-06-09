"""
UI layer - Rich console, progress, themes.
"""

from scribe.ui.console import get_console, get_default_console
from scribe.ui.progress import (
    StreamProgress,
    TokenCounter,
    create_default_progress,
)
from scribe.ui.theme import AVAILABLE_THEMES, Theme, ThemeColors

__all__ = [
    "get_console",
    "get_default_console",
    "create_default_progress",
    "StreamProgress",
    "TokenCounter",
    "Theme",
    "AVAILABLE_THEMES",
    "ThemeColors",
]
