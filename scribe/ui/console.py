"""
Rich Console setup and theme configuration.

Themes are defined as small palettes (a handful of hex colors) that expand into
the full set of Rich styles the app uses. This keeps adding a theme to a few
lines and guarantees every theme defines every style key.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

# Seven curated themes for 2.0.1 — each a distinct *mood*, not a port of an
# existing scheme. Every palette defines the same keys so a theme is complete by
# construction. `accent` is the primary brand color (logo, borders, pills);
# `secondary` is the complementary hue that closes the brand gradient.
#
#   ink     scholarly manuscript — gold on deep charcoal-navy   (default brand)
#   charm   Crush homage — hot pink → electric violet, near-black
#   aurora  icy north — cyan → indigo on deep navy
#   ember   forge — ember orange → crimson on warm black
#   moss    botanical — lime-sage → teal on deep forest
#   paper   daylight manuscript — ink on warm off-white (the one light theme)
#   synth   neon synthwave — electric cyan → magenta on jet black
PALETTES: dict[str, dict[str, str]] = {
    "ink": {
        "bg": "#11131a", "fg": "#e8e0cf", "accent": "#d4a44c", "secondary": "#c97f3a",
        "success": "#9bbf6a", "warning": "#e0b04a", "error": "#d6604d",
        "user": "#c9a0dc", "assistant": "#7fb0a6",
    },
    "charm": {
        "bg": "#15131c", "fg": "#e6e0ec", "accent": "#ff5faf", "secondary": "#9d7bff",
        "success": "#1fe0b0", "warning": "#ffcf6b", "error": "#ff5f87",
        "user": "#9d7bff", "assistant": "#ff8fcf",
    },
    "aurora": {
        "bg": "#0d1b2a", "fg": "#cdd9e5", "accent": "#56cfe1", "secondary": "#7b8cde",
        "success": "#80ed99", "warning": "#ffd166", "error": "#ff6b6b",
        "user": "#9b8cff", "assistant": "#64dfdf",
    },
    "ember": {
        "bg": "#1a1310", "fg": "#ece2d0", "accent": "#ff7a3c", "secondary": "#e84855",
        "success": "#c5d86d", "warning": "#ffb13c", "error": "#f25c54",
        "user": "#ffa552", "assistant": "#e8a87c",
    },
    "moss": {
        "bg": "#121a14", "fg": "#dbe4d0", "accent": "#9bcf52", "secondary": "#3fae8f",
        "success": "#b5e655", "warning": "#e8c75a", "error": "#e0685a",
        "user": "#a3d977", "assistant": "#5fc9a3",
    },
    "paper": {
        "bg": "#f4efe6", "fg": "#2b2b2b", "accent": "#9c3d2e", "secondary": "#1f6f6b",
        "success": "#4a7c34", "warning": "#b07d1a", "error": "#a83232",
        "user": "#7a3e9c", "assistant": "#1f6f6b",
    },
    "synth": {
        "bg": "#0b0a14", "fg": "#e0d6ff", "accent": "#22d3ee", "secondary": "#f72585",
        "success": "#3ef2a0", "warning": "#ffd000", "error": "#ff3864",
        "user": "#ff5fd2", "assistant": "#22d3ee",
    },
}

# Brand gradient ends (logo, cursor, hatch). Default is accent→secondary; only
# override when a theme reads better with a hand-picked pair (the light theme
# wants warm-on-warm rather than crimson→teal clashing).
GRADIENT_ENDS: dict[str, tuple[str, str]] = {
    "paper": ("#9c3d2e", "#c9772f"),
}

DEFAULT_THEME = "ink"


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


def hatch_bar(label: str, theme: str = DEFAULT_THEME, width: int = 80):
    """A Crush-style diagonal-hatch header: ``label`` then a gradient ``╱`` fill.

    Mirrors Crush's ``╱╱╱`` texture on title/section bars. Returns a Rich Text
    of exactly ``width`` cells (label + a space, padded with hatch glyphs that
    fade across the brand gradient).
    """
    from rich.text import Text

    start, end = gradient_ends(theme)
    sr, sg, sb = _hex_to_rgb(start)
    er, eg, eb = _hex_to_rgb(end)

    out = Text()
    prefix = f"{label} " if label else ""
    out.append_text(gradient_text(prefix, theme)) if prefix else None
    fill = max(0, width - len(prefix))
    n = max(fill - 1, 1)
    for i in range(fill):
        t = i / n
        r = round(sr + (er - sr) * t)
        g = round(sg + (eg - sg) * t)
        b = round(sb + (eb - sb) * t)
        out.append("╱", style=f"#{r:02x}{g:02x}{b:02x}")
    return out


def gradient_block(lines: list[str], theme: str = DEFAULT_THEME):
    """Color a multi-line ASCII block with a *diagonal* brand gradient.

    Each glyph's color is picked by its (x + y) position across the whole block,
    so the primary→secondary gradient flows top-left → bottom-right like Crush's
    logo. Returns one Rich Text with embedded newlines; spaces stay uncolored.
    """
    from rich.text import Text

    start, end = gradient_ends(theme)
    sr, sg, sb = _hex_to_rgb(start)
    er, eg, eb = _hex_to_rgb(end)
    height = max(len(lines), 1)
    width = max((len(ln) for ln in lines), default=1)
    span = max(width + height - 2, 1)

    out = Text()
    for y, line in enumerate(lines):
        for x, ch in enumerate(line):
            if ch == " ":
                out.append(" ")
                continue
            t = (x + y) / span
            r = round(sr + (er - sr) * t)
            g = round(sg + (eg - sg) * t)
            b = round(sb + (eb - sb) * t)
            out.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
        if y < height - 1:
            out.append("\n")
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
