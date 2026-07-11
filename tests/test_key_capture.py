"""Preferences ▸ Hotkeys capture field — records the pressed combo as text.

int(event.modifiers()) raised TypeError on current PySide6 (the flags enum is
not int()-able), so every keypress in the capture field errored and nothing
was recorded; keyCombination() carries modifiers+key natively.
"""

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from framedraft.app import KeyCaptureEdit


def _press(widget, key, mods=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods))


def test_captures_plain_key():
    edit = KeyCaptureEdit()
    _press(edit, Qt.Key.Key_O)
    assert edit.text() == "O"


def test_captures_modified_combo():
    edit = KeyCaptureEdit()
    _press(edit, Qt.Key.Key_B,
           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert edit.text() == "Ctrl+Shift+B"


def test_escape_clears_and_lone_modifier_ignored():
    edit = KeyCaptureEdit()
    _press(edit, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    _press(edit, Qt.Key.Key_Shift)          # lone modifier: no change
    assert edit.text() == "Ctrl+B"
    _press(edit, Qt.Key.Key_Escape)
    assert edit.text() == ""
