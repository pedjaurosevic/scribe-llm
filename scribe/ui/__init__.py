"""
UI layer - Rich console, progress, themes.
"""

from scribe.ui.console import get_console, get_default_console
from scribe.ui.progress import (
    create_default_progress,
    StreamProgress,
    TokenCounter,
)
from scribe.ui.theme import Theme, AVAILABLE_THEMES, ThemeColors

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
