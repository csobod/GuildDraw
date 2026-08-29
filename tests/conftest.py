"""Session-wide Qt application, and a guard against modal dialogs.

Some tests need a Qt application instance. Creating it here — before any test
module is imported — guarantees a single, shared QApplication. It must be the
QtWidgets variant: the widget-based tests (QMainWindow/QToolBar) crash under a
bare QGuiApplication, which is what an individual module would otherwise create
first. The default platform plugin is used (not "offscreen") so font-dependent
tests (text-outline geometry) still see real system fonts — the offscreen
plugin exposes none.
"""
import pytest
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QDialog, QFileDialog, QFontDialog,
    QInputDialog, QMenu, QMessageBox,
)

_app = QApplication.instance() or QApplication([])


class UnexpectedDialog(AssertionError):
    """A test reached a modal dialog that nothing had stubbed."""


# Every blocking entry point the app opens a dialog through. A modal raised
# under pytest never gets an answer: it spins its own event loop until the run
# is killed, with no output naming the test. That is how three hangs here have
# started — the swatch picker, the OMA import, and twice over the
# unsaved-changes prompt a fixture forgot to defuse (a window closing dirty, and
# _do_save_gdraw leaving the flag up before _new()). CI carries a per-test
# timeout to catch the symptom; this removes the cause.
_BLOCKING = {
    QColorDialog: ("getColor",),
    QFileDialog:  ("getExistingDirectory", "getOpenFileName",
                   "getOpenFileNames", "getSaveFileName"),
    QFontDialog:  ("getFont",),
    QInputDialog: ("getDouble", "getInt", "getItem", "getMultiLineText",
                   "getText"),
    QMessageBox:  ("about", "critical", "information", "question", "warning"),
    # Covers every dialog the app exec()s itself — Settings, Text, Transform,
    # the drill/hinge library. QMessageBox's own statics reach C++ directly and
    # never come through here, which is why they are listed above as well.
    QDialog:      ("exec",),
    # Not a dialog, same trap: the Layers panel's context menu runs its own
    # event loop too.
    QMenu:        ("exec",),
}


def _refuse(owner, name):
    def blocked(*_args, **_kwargs):
        raise UnexpectedDialog(
            f"{owner.__name__}.{name}() opened a modal dialog. Nothing can "
            f"answer it under pytest, so the run would block until it is "
            f"killed. Stub it with monkeypatch.setattr if the test means to "
            f"reach it, or fix the path that got here."
        )
    return staticmethod(blocked)


@pytest.fixture(autouse=True)
def no_unanswered_modals(monkeypatch):
    """Turn an unstubbed modal into a named failure instead of a hang.

    A test that means to reach one stubs it exactly as before: this runs first,
    so the test's own patch goes on top, and monkeypatch unwinds both.
    """
    for owner, names in _BLOCKING.items():
        for name in names:
            monkeypatch.setattr(owner, name, _refuse(owner, name))
