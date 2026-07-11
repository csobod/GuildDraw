"""RC4 M25 — the boxing-square "□" input helper (size notation A□DBL-Temple).

Covers: hotkey registration consistency, the focused-widget insert helper,
and the glyph surviving every sink it is typed into (library filenames,
engraving outlines).
"""

from PySide6.QtWidgets import QLabel, QLineEdit, QTextEdit

from framedraft import library as _lib
from framedraft.app import _HOTKEY_ACTION_DEFS, _TEXT_FIELD_HOTKEYS, _insert_text_into
from framedraft.document import Layer, TextObject
from framedraft.prefs import DEFAULTS
from framedraft.textpath import text_to_curves

SQ = "□"


# ------------------------------------------------------------- registration


def test_insert_square_hotkey_registered():
    assert DEFAULTS["hotkeys"]["insert_square"] == "Ctrl+Shift+B"
    assert "insert_square" in {k for k, _ in _HOTKEY_ACTION_DEFS}
    assert "insert_square" in _TEXT_FIELD_HOTKEYS


def test_hotkey_defs_match_prefs_defaults():
    # A prefs key without a Settings row (or vice versa) is silently dead.
    assert {k for k, _ in _HOTKEY_ACTION_DEFS} == set(DEFAULTS["hotkeys"])


# ------------------------------------------------------------ insert helper


def test_insert_into_line_edit_at_cursor():
    edit = QLineEdit()
    edit.setText("4927-145")
    edit.setCursorPosition(2)
    assert _insert_text_into(edit, SQ)
    assert edit.text() == f"49{SQ}27-145"


def test_insert_replaces_line_edit_selection():
    edit = QLineEdit()
    edit.setText("49x27")
    edit.setSelection(2, 1)
    assert _insert_text_into(edit, SQ)
    assert edit.text() == f"49{SQ}27"


def test_insert_into_text_edit():
    edit = QTextEdit()
    edit.setPlainText("size ")
    cursor = edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    edit.setTextCursor(cursor)
    assert _insert_text_into(edit, SQ)
    assert edit.toPlainText() == f"size {SQ}"


def test_insert_into_non_text_widget_is_noop():
    assert not _insert_text_into(QLabel("x"), SQ)
    assert not _insert_text_into(None, SQ)


# ------------------------------------------------------------- glyph sinks


def test_square_survives_safe_filename():
    assert _lib._safe_filename(f"49{SQ}27-145") == f"49{SQ}27-145"


def test_square_engraves_to_outline_curves():
    t = TextObject(text=f"49{SQ}27-145", family="Segoe UI", size_mm=5.0,
                   anchor_x=0.0, anchor_y=0.0, layer=Layer.ENGRAVING)
    curves = text_to_curves(t)
    # Every character including the □ must contribute closed outlines.
    assert len(curves) >= 9, "size-notation string lost glyph outlines"
    assert all(c.closed for c in curves)
