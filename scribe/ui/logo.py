"""
Scribe ASCII logos.

A big "ANSI Shadow" banner for the landing screen and a compact wordmark for
tight spots. Pure text so any theme can color it (the splash renders it with a
diagonal brand gradient via `console.gradient_block`).
"""

from __future__ import annotations

# "SCRIBE" in the ANSI Shadow figlet font — 43 cells wide, 6 rows. The block
# glyphs (█) plus box-drawing edges read as a solid, modern wordmark and color
# beautifully under a gradient.
SCRIBE_BIG = r"""
███████╗ ██████╗██████╗ ██╗██████╗ ███████╗
██╔════╝██╔════╝██╔══██╗██║██╔══██╗██╔════╝
███████╗██║     ██████╔╝██║██████╔╝█████╗
╚════██║██║     ██╔══██╗██║██╔══██╗██╔══╝
███████║╚██████╗██║  ██║██║██████╔╝███████╗
╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝
"""

# Subtitle that completes the "SCRIBE-LLM" wordmark and states the identity.
SCRIBE_TAGLINE = "L · L · M   —   local-first investigative language agent"

# Compact one-line wordmark for the top bar.
SCRIBE_WORDMARK = "✶ SCRIBE·LLM"

# Smaller banner for the classic UI's session-end / resume screen.
SCRIBE_SMALL = r"""
 ___         _ _
/ __| __ _ _(_) |__  ___
\__ \/ _| '_| | '_ \/ -_)
|___/\__|_| |_|_.__/\___|
"""


def logo_lines(small: bool = False) -> list[str]:
    """Return the logo as a list of lines (no leading/trailing blank lines)."""
    art = SCRIBE_SMALL if small else SCRIBE_BIG
    return art.strip("\n").splitlines()


def banner_lines() -> list[str]:
    """The big SCRIBE banner rows, padded to equal width.

    Trailing whitespace in the source art is fragile (editors trim it), so the
    rows are right-padded here to a uniform width — keeping the right edge clean
    regardless of how the literal was saved.
    """
    rows = SCRIBE_BIG.strip("\n").splitlines()
    width = max((len(r) for r in rows), default=0)
    return [r.ljust(width) for r in rows]
