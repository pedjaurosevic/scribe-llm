"""
Rich Console setup and theme configuration.

Themes are defined as small palettes (a handful of hex colors) that expand into
the full set of Rich styles the app uses. This keeps adding a theme to a few
lines and guarantees every theme defines every style key.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

# Each palette: bg/fg plus the semantic accents. `accent` is the primary brand
# color (borders, Scribe header, pills); `secondary` is a complementary hue.
PALETTES: dict[str, dict[str, str]] = {
    "gruvbox-dark": {
        "bg": "#282828", "fg": "#ebdbb2", "accent": "#83a598", "secondary": "#fabd2f",
        "success": "#b8bb26", "warning": "#fabd2f", "error": "#fb4934",
        "user": "#d3869b", "assistant": "#8ec07c",
    },
    "dracula": {
        "bg": "#282a36", "fg": "#f8f8f2", "accent": "#bd93f9", "secondary": "#ff79c6",
        "success": "#50fa7b", "warning": "#f1fa8c", "error": "#ff5555",
        "user": "#ff79c6", "assistant": "#8be9fd",
    },
    "tokyo-night": {
        "bg": "#1a1b26", "fg": "#c0caf5", "accent": "#7aa2f7", "secondary": "#bb9af7",
        "success": "#9ece6a", "warning": "#e0af68", "error": "#f7768e",
        "user": "#bb9af7", "assistant": "#7dcfff",
    },
    "nord": {
        "bg": "#2e3440", "fg": "#d8dee9", "accent": "#88c0d0", "secondary": "#81a1c1",
        "success": "#a3be8c", "warning": "#ebcb8b", "error": "#bf616a",
        "user": "#b48ead", "assistant": "#8fbcbb",
    },
    "catppuccin": {
        "bg": "#1e1e2e", "fg": "#cdd6f4", "accent": "#cba6f7", "secondary": "#f5c2e7",
        "success": "#a6e3a1", "warning": "#f9e2af", "error": "#f38ba8",
        "user": "#f5c2e7", "assistant": "#94e2d5",
    },
    "solarized-dark": {
        "bg": "#002b36", "fg": "#93a1a1", "accent": "#268bd2", "secondary": "#2aa198",
        "success": "#859900", "warning": "#b58900", "error": "#dc322f",
        "user": "#d33682", "assistant": "#2aa198",
    },
    # Charm-inspired palette (à la Charmbracelet's Crush): hot pink primary,
    # electric purple secondary, mint success, on a near-black background.
    "charm": {
        "bg": "#171717", "fg": "#dbdbdb", "accent": "#ff5faf", "secondary": "#8b5dff",
        "success": "#00d7af", "warning": "#ffd787", "error": "#ff5f87",
        "user": "#8b5dff", "assistant": "#ff5faf",
    },
}

# Two ends of the brand gradient (Crush uses primary→secondary for the logo,
# cursor and accents). Falls back to accent↔secondary for non-charm themes.
GRADIENT_ENDS: dict[str, tuple[str, str]] = {
    "charm": ("#ff5faf", "#8b5dff"),
}

DEFAULT_THEME = "gruvbox-dark"


def _lighten(hex_color: str, amount: float = 0.12) -> str:
    """Blend a hex color toward white by `amount` (0..1). Used for surfaces."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def _styles(p: dict[str, str]) -> dict[str, str]:
    """Expand a palette into the full Rich style table the app uses."""
    surface = _lighten(p["bg"], 0.12)
    return {
        # surfaces
        "surface": surface,
        # user message bubble: normal text on a slightly lighter (greyer) bg
        "user.msg": f"{p['fg']} on {surface}",
        # semantic
        "success": p["success"],
        "warning": p["warning"],
        "error": p["error"],
        "info": p["accent"],
        "user": f"bold {p['user']}",
        "assistant": p["assistant"],
        "scribe": p["accent"],
        "system": p["accent"],
        "accent": p["accent"],
        "secondary": p["secondary"],
        "metadata": "dim",
        "path": f"underline {p['success']}",
        "command": f"bold {p['accent']}",
        "output": p["fg"],
        "timestamp": "dim",
        # progress / spinner
        "progress": p["accent"],
        "progress.full": p["success"],
        "progress.complete": p["success"],
        "progress.remaining": p["warning"],
        "spinner": p["accent"],
        # repr
        "repr.number": p["warning"],
        "repr.str": p["success"],
        "repr.bool": p["accent"],
        "repr.type": p["error"],
        # panels
        "panel.title": f"bold {p['accent']}",
        "panel.border": p["accent"],
        "status.bar": f"reverse {p['fg']} on {p['accent']}",
        # Crush-style status pills (colored background, bg-colored text)
        "pill.model": f"bold {p['bg']} on {p['accent']}",
        "pill.speed": f"bold {p['bg']} on {p['success']}",
        "pill.ctx": f"bold {p['bg']} on {p['secondary']}",
        "pill.code": f"bold {p['bg']} on {p['warning']}",
    }


THEMES: dict[str, dict[str, str]] = {name: _styles(p) for name, p in PALETTES.items()}


def list_themes() -> list[str]:
    """Names of all available themes."""
    return list(THEMES.keys())


def theme_accent(theme: str) -> str:
    """The accent (primary) hex color of a theme, for swatches/previews."""
    return PALETTES.get(theme, PALETTES[DEFAULT_THEME])["accent"]


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def gradient_ends(theme: str) -> tuple[str, str]:
    """Start/end hex colors of a theme's brand gradient (primary→secondary)."""
    if theme in GRADIENT_ENDS:
        return GRADIENT_ENDS[theme]
    p = PALETTES.get(theme, PALETTES[DEFAULT_THEME])
    return p["accent"], p["secondary"]


def gradient_text(text: str, theme: str = DEFAULT_THEME, *, bold: bool = True):
    """Render text with a per-character primary→secondary color gradient.

    Mirrors Crush's gradient accents (a smooth foreground transition across the
    string). Returns a Rich Text; whitespace is spanned but not colored.
    """
    from rich.text import Text

    start, end = gradient_ends(theme)
    sr, sg, sb = _hex_to_rgb(start)
    er, eg, eb = _hex_to_rgb(end)
    out = Text()
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        t = i / n
        r = round(sr + (er - sr) * t)
        g = round(sg + (eg - sg) * t)
        b = round(sb + (eb - sb) * t)
        style = f"#{r:02x}{g:02x}{b:02x}"
        out.append(ch, style=f"bold {style}" if bold else style)
    return out


def get_console(theme: str = DEFAULT_THEME, **kwargs) -> Console:
    """
    Get a Rich Console with the named theme.

    Args:
        theme: One of `list_themes()`. Unknown names fall back to the default.
        **kwargs: Additional arguments passed to Console.

    Returns:
        Configured Console instance.
    """
    styles = THEMES.get(theme, THEMES[DEFAULT_THEME])
    return Console(theme=Theme(styles), **kwargs)


def get_default_console() -> Console:
    """Get the default Scribe console (default theme, terminal forced)."""
    return get_console(force_terminal=True)
