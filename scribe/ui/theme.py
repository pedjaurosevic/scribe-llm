"""
Theme definitions for Scribe TUI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThemeColors:
    """Color palette for a theme."""

    background: str
    foreground: str
    primary: str
    secondary: str
    accent: str
    success: str
    warning: str
    error: str
    user_message: str
    assistant_message: str
    system_message: str
    dim: str


GRUVBOX_DARK_COLORS = ThemeColors(
    background="#282828",
    foreground="#ebdbb2",
    primary="#fb4934",
    secondary="#fabd2f",
    accent="#83a598",
    success="#b8bb26",
    warning="#fabd2f",
    error="#fb4934",
    user_message="#d3869b",
    assistant_message="#8ec07c",
    system_message="#83a598",
    dim="#a89984",
)


@dataclass
class Theme:
    """Theme configuration for Scribe TUI."""

    name: str
    colors: ThemeColors
    font_style: str | None = None

    @classmethod
    def gruvbox_dark(cls) -> Theme:
        """Get the Gruvbox Dark theme."""
        return cls(name="gruvbox-dark", colors=GRUVBOX_DARK_COLORS)

    def get_rich_styles(self) -> dict[str, str]:
        """Get Rich-compatible style dictionary."""
        return {
            "background": self.colors.background,
            "foreground": self.colors.foreground,
            "primary": self.colors.primary,
            "secondary": self.colors.secondary,
            "accent": self.colors.accent,
            "success": self.colors.success,
            "warning": self.colors.warning,
            "error": self.colors.error,
            "user": self.colors.user_message,
            "assistant": self.colors.assistant_message,
            "system": self.colors.system_message,
            "dim": self.colors.dim,
        }


AVAILABLE_THEMES = {
    "gruvbox-dark": Theme.gruvbox_dark(),
}
