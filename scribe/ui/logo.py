"""
Scribe ASCII logos.

A big banner for the landing screen and a smaller one shown when a chat session
ends (next to the resume command). Pure text so any theme can color it.
"""

from __future__ import annotations

# Figlet "Standard" — landing page.
SCRIBE_BIG = r"""
 ____            _ _
/ ___|  ___ _ __(_) |__   ___
\___ \ / __| '__| | '_ \ / _ \
 ___) | (__| |  | | |_) |  __/
|____/ \___|_|  |_|_.__/ \___|
"""

# Figlet "Small" — session end / resume.
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
