"""Every enabled button and action in the main window, pressed as a user would.

The rest of the suite calls the handlers directly, so a control wired wrong
passed it: Add Image… handed clicked's checked=False to _add_face as the path
and opened nothing; View ▸ Properties Panel raised on every click; Reset All
Layer Colors raised at the first layer the grid has no row for. Each press here
goes through the control's own signal. A press may not raise, and a control
whose label promises a dialog ("…") must open one.

Every dialog is answered Cancel, so nothing is written but the scratch
preferences and library conftest sets up.
"""
import gc
import sys
import traceback

import pytest
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QImage
from PySide6.QtPrintSupport import QPageSetupDialog, QPrintDialog
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QColorDialog, QDialog, QFileDialog,
    QFontDialog, QInputDialog, QMenu, QMessageBox, QPushButton, QToolButton,
)

import framedraft.app as app_mod
from helpers import circle, closed_diamond

# "…" controls that start a canvas tool rather than open a dialog.
_NO_DIALOG = {"Calibrate (2-point)…"}
# Pressing these would end the window under test.
_SKIP = {"Quit", "Exit", "Close"}
# Qt's own dialogs: the app builds one, the stubbed exec never shows it, and its
# buttons are Qt's to test (the print dialog's Properties crashes unprepared).
_STOCK = (QPrintDialog, QPageSetupDialog, QFileDialog, QColorDialog,
          QFontDialog, QMessageBox)


@pytest.fixture()
def answered(monkeypatch):
    """Every modal answered Cancel and recorded; every slot's exception kept."""
    opened, errors = [], []

    def cancel(name, value):
        def stub(*_a, **_k):
            opened.append(name)
            return value
        return staticmethod(stub)

    def cancel_exec(name, value):
        def stub(self, *_a, **_k):
            opened.append(name)
            return value
        return stub

    no = QMessageBox.StandardButton.Cancel
    for owner, answers in {
        QFileDialog: {"getOpenFileName": ("", ""), "getSaveFileName": ("", ""),
                      "getOpenFileNames": ([], ""), "getExistingDirectory": ""},
        QInputDialog: {"getText": ("", False), "getDouble": (0.0, False),
                       "getInt": (0, False), "getItem": ("", False),
                       "getMultiLineText": ("", False)},
        QColorDialog: {"getColor": QColor()},
        QFontDialog: {"getFont": (False, QFont())},
        QMessageBox: {"about": None, "critical": no, "information": no,
                      "question": no, "warning": no},
    }.items():
        for name, value in answers.items():
            monkeypatch.setattr(owner, name, cancel(name, value))
    for owner in (QMessageBox, QDialog, QPrintDialog, QPageSetupDialog):
        monkeypatch.setattr(owner, "exec", cancel_exec(
            f"{owner.__name__}.exec", int(no) if owner is QMessageBox else 0))
    monkeypatch.setattr(QMenu, "exec", cancel_exec("QMenu.exec", None))
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda *_a: opened.append("openUrl")))
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: errors.append(
        "".join(traceback.format_exception(t, v, tb))))
    return opened, errors


@pytest.fixture()
def win(answered, tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod.MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    w = app_mod.MainWindow()
    w.show()
    QApplication.processEvents()
    yield w
    w._dirty = False
    for top in QApplication.topLevelWidgets():
        if top is not w and isinstance(top, QDialog):
            top.hide()
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    gc.collect()


def _label(control) -> str:
    text = control.text() or control.toolTip().split("\n")[0]
    return (text or control.objectName()).replace("&", "")


def _stock_owned(widget) -> bool:
    w = widget.parentWidget()
    while w is not None:
        if isinstance(w, _STOCK):
            return True
        w = w.parentWidget()
    return False


def _actions(win) -> list:
    """Each enabled action once."""
    seen, out = set(), []
    actions = list(win.findChildren(QAction))
    for menu in win.menuBar().findChildren(QMenu):
        actions += menu.actions()
    for a in actions:
        if (id(a) in seen or a.isSeparator() or a.menu() is not None
                or not a.isEnabled()):
            continue
        seen.add(id(a))
        out.append(a)
    return out


def _buttons(win):
    """Each enabled button no action backs. Gathered after the actions have
    run: Preferences… leaves its dialog behind, and its buttons count."""
    for b in win.findChildren(QAbstractButton):
        if not isinstance(b, (QPushButton, QToolButton)) or not b.isEnabled():
            continue
        if b.objectName().startswith("qt_") or _stock_owned(b):
            continue
        if isinstance(b, QToolButton) and (
                b.defaultAction() is not None or b.menu() is not None
                or b.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup):
            continue
        yield b


def _press_everything(win, answered) -> list[str]:
    opened, errors = answered
    faults = []
    pressed = _actions(win)

    def controls():
        yield from pressed
        yield from list(_buttons(win))

    for control in controls():
        label = _label(control)
        if label.rstrip(" …") in _SKIP:
            continue
        n_open, n_err = len(opened), len(errors)
        tops = {id(t) for t in QApplication.topLevelWidgets() if t.isVisible()}
        try:
            control.trigger() if isinstance(control, QAction) else control.click()
            QApplication.processEvents()
        except Exception:
            errors.append(traceback.format_exc())
        shown = [t for t in QApplication.topLevelWidgets()
                 if t.isVisible() and id(t) not in tops and t is not win]
        for t in shown:
            t.hide()
        if len(errors) > n_err:
            last = errors[-1].strip().splitlines()[-1]
            faults.append(f"{label!r} raised {last}")
        elif (label.rstrip().endswith("…") and label not in _NO_DIALOG
                and len(opened) == n_open and not shown):
            faults.append(f"{label!r} promises a dialog and opened none")
    return faults


def test_every_control_answers_in_an_empty_window(win, answered):
    assert _press_everything(win, answered) == []


def test_every_control_answers_with_a_photo_and_a_selection(
        win, answered, tmp_path, monkeypatch):
    photo = tmp_path / "face.png"
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("#a08060"))
    img.save(str(photo))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *_a, **_k: (str(photo), "")))
    win._add_face()
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *_a, **_k: answered[0].append(
                            "getOpenFileName") or ("", "")))
    ws = win._active_ws
    ws.add_curve(closed_diamond())
    ws.add_curve(circle(40.0, 0.0, 5.0))
    win._select_all()
    QApplication.processEvents()
    assert win.scene.face_count() == 1 and win.scene.selectedItems()
    assert _press_everything(win, answered) == []


def test_the_add_image_button_opens_the_file_dialog(win, answered):
    """The Canvas tab's own button, clicked: the dialog it opened was none."""
    btn = next(b for b in win.findChildren(QPushButton)
               if b.text() == "Add Image…")
    btn.click()
    assert "getOpenFileName" in answered[0]


def test_the_properties_panel_menu_entry_hides_and_shows_the_panel(win, answered):
    act = win._menu_panel
    act.setChecked(win._prop_dock.isVisible())   # as the menu sets it opening
    act.trigger()
    QApplication.processEvents()
    assert not win._prop_dock.isVisible() and not act.isChecked()
    act.trigger()
    QApplication.processEvents()
    assert win._prop_dock.isVisible() and act.isChecked()
    assert answered[1] == []


def test_reset_all_layer_colors_redraws_every_row(win, answered):
    """BRIDGE has no row in the grid; reaching it raised, and the rows after
    it kept the overrides just cleared."""
    dlg = app_mod.SettingsDialog({**win._prefs, "theme": {
        "light": {"layer.INLAY": "#123456"}, "dark": {}}}, win)
    inlay = dlg._layer_btns[("INLAY", "light")]
    assert inlay.text() == "#123456"
    next(b for b in dlg.findChildren(QPushButton)
         if b.text() == "Reset All Layer Colors").click()
    assert answered[1] == []
    assert inlay.text() == "default"
    dlg.deleteLater()
