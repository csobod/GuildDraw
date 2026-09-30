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
    # exec: a QMessageBox built by hand (custom buttons) runs through its own
    # exec, which the QDialog entry below does not reach.
    QMessageBox:  ("about", "critical", "information", "question", "warning",
                   "exec"),
    # Covers every dialog the app exec()s itself — Settings, Text, Transform,
    # the drill/hinge library. QMessageBox's own statics reach C++ directly and
    # never come through here, which is why they are listed above as well.
    QDialog:      ("exec",),
    # Not a dialog, same trap: the Layers panel's context menu runs its own
    # event loop too.
    QMenu:        ("exec",),
}
# The print dialogs bind their own exec too; the QDialog entry misses them.
from PySide6.QtPrintSupport import QPageSetupDialog, QPrintDialog  # noqa: E402
_BLOCKING[QPrintDialog] = ("exec",)
_BLOCKING[QPageSetupDialog] = ("exec",)


def _refuse(owner, name):
    def blocked(*_args, **_kwargs):
        raise UnexpectedDialog(
            f"{owner.__name__}.{name}() opened a modal dialog. Nothing can "
            f"answer it under pytest, so the run would block until it is "
            f"killed. Stub it with monkeypatch.setattr if the test means to "
            f"reach it, or fix the path that got here."
        )
    return staticmethod(blocked)


@pytest.fixture(autouse=True, scope="session")
def scratch_prefs(tmp_path_factory):
    """Every test reads and writes a scratch prefs file, never the
    developer's real ~/.guilddraw/prefs.json. Several module-scoped
    MainWindow fixtures used to load the real one (so a dark-mode or hotkey
    preference changed what a test saw) and any path through _save_prefs
    wrote back into it. Tests that want their own file still monkeypatch
    prefs._FILE on top of this."""
    import framedraft.prefs as prefs_mod
    d = tmp_path_factory.mktemp("prefs")
    mp = pytest.MonkeyPatch()
    mp.setattr(prefs_mod, "_DIR", d)
    mp.setattr(prefs_mod, "_FILE", d / "prefs.json")
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def no_unanswered_modals(monkeypatch):
    """Turn an unstubbed modal into a named failure instead of a hang.

    A test that means to reach one stubs it exactly as before: this runs first,
    so the test's own patch goes on top, and monkeypatch unwinds both.
    """
    for owner, names in _BLOCKING.items():
        for name in names:
            monkeypatch.setattr(owner, name, _refuse(owner, name))


@pytest.fixture(autouse=True)
def windows_really_go():
    """Destroy what a test handed to deleteLater().

    pytest runs no event loop, and Qt only honors a deferred delete from one
    (or when asked, as here). Without this, every MainWindow a fixture closed
    stayed alive for the rest of the session: about 9 MB each, and every new
    window's stylesheet pass re-polished all of them, so the suite slowed with
    each window test until it took 23 minutes — past the CI gate's 20.
    Autouse fixtures tear down last, so this runs after the test's own
    fixtures have closed their windows.
    """
    yield
    # A dialog a test built and closed (or never showed) is the test's own;
    # nothing in the app keeps one between uses.
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QDialog):
            w.deleteLater()
    _flush_deferred_deletes()


def _flush_deferred_deletes():
    from PySide6.QtCore import QEvent
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True, scope="module")
def nothing_outlives_its_module():
    """A module-scoped window fixture ends with its module. Several never
    deleted theirs, and six such windows were alive by the end of a run.
    deleteLater, not close(): no closeEvent, so no unsaved-changes prompt can
    be raised here, where the modal guard is no longer in force."""
    yield
    for w in QApplication.topLevelWidgets():
        if w.parent() is None and w.metaObject().className() != "QTipLabel":
            w.deleteLater()
    _flush_deferred_deletes()
