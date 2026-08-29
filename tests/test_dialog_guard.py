"""The suite's own hang guard (conftest.no_unanswered_modals).

A modal dialog raised under pytest never gets an answer — it spins its own
event loop until the run is killed, printing nothing that names the test. The
guard turns each blocking entry point into an immediate, named failure. These
pin that it is armed, and that a test which legitimately means to reach a
dialog can still stub it.
"""
import pytest
from PySide6.QtWidgets import (
    QColorDialog, QDialog, QFileDialog, QInputDialog, QMessageBox,
)

from conftest import UnexpectedDialog


def test_an_unstubbed_message_box_fails_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QMessageBox.warning(None, "t", "t")


def test_an_unstubbed_file_dialog_fails_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QFileDialog.getSaveFileName(None, "t", "", "*")


def test_an_unstubbed_input_dialog_fails_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QInputDialog.getItem(None, "t", "t", ["a"], 0, False)


def test_an_unstubbed_colour_picker_fails_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QColorDialog.getColor()


def test_an_unstubbed_dialog_exec_fails_instead_of_blocking():
    """Covers the dialogs the app exec()s itself — Settings, Text, Transform."""
    with pytest.raises(UnexpectedDialog):
        QDialog().exec()


def test_the_message_names_the_call_that_would_have_blocked():
    with pytest.raises(UnexpectedDialog, match=r"QMessageBox\.critical\(\)"):
        QMessageBox.critical(None, "t", "t")


def test_a_test_that_stubs_a_dialog_still_gets_its_own_answer(monkeypatch):
    """The guard goes on first, so a test's own patch wins — otherwise every
    existing dialog-driving test would have broken."""
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard))
    assert QMessageBox.warning(None, "t", "t") is QMessageBox.StandardButton.Discard


def test_every_dialog_static_the_app_calls_is_guarded():
    """conftest's list is hand-maintained. This fails the day a new blocking
    entry point is used and nobody adds it — the alternative being that the
    suite silently goes back to hanging on it.

    Only the class-qualified statics can be found this way; the instance calls
    (`dlg.exec()`, `menu.exec()`) are covered by patching QDialog and QMenu
    themselves, which needs no list.
    """
    import pathlib
    import re

    from conftest import _BLOCKING

    guarded = {(owner.__name__, name)
               for owner, names in _BLOCKING.items() for name in names}
    watched = sorted({owner.__name__ for owner in _BLOCKING})
    call = re.compile(r"\b(" + "|".join(watched) + r")\.([A-Za-z_]\w*)\s*\(")

    src = pathlib.Path(__file__).resolve().parents[1] / "framedraft"
    used = {}
    for path in sorted(src.rglob("*.py")):
        for cls, meth in call.findall(path.read_text(encoding="utf-8")):
            used.setdefault((cls, meth), path.name)

    unguarded = {k: v for k, v in used.items() if k not in guarded}
    assert not unguarded, (
        "dialog entry points the app calls but conftest does not guard: "
        + ", ".join(f"{c}.{m}() in {f}" for (c, m), f in sorted(unguarded.items()))
        + " — add it to _BLOCKING, or list it here if it does not block."
    )
