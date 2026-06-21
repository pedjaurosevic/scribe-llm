"""The Textual footer must always fit on exactly one row (model name shrinks)."""

from rich.cells import cell_len

from scribe.tui_app import build_status_line
from scribe.ui.console import PALETTES

MODEL = "gemma-4-12B-it-Q4_K_M.gguf"
PAL = PALETTES["ink"]


def _line(width, code_mode):
    return build_status_line(width, MODEL, 26.9, 1.3, 131, 1.0, code_mode, PAL).plain


def test_never_exceeds_width():
    for width in range(10, 130):
        for code in (False, True):
            text = _line(width, code)
            assert "\n" not in text
            assert cell_len(text) <= width, (width, code, cell_len(text))


def test_model_name_shrinks_with_ellipsis():
    # Narrow enough that the full name cannot fit, but pills do.
    text = _line(60, code_mode=True)
    assert "tok/s" in text and "ctx" in text  # pills kept whole
    assert "…" in text                         # model name was shortened


def test_full_name_when_wide():
    text = _line(120, code_mode=True)
    assert MODEL in text
    assert "⌘ CODE" in text


def test_code_pill_only_when_code_mode():
    assert "⌘ CODE" not in _line(120, code_mode=False)
    assert "⌘ CODE" in _line(120, code_mode=True)
