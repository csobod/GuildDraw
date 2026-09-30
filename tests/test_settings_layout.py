"""Preferences layout, carried over from GuildModel: every tab scrolls, the
dialog opens at its content's size within the screen and remembers the size
the maker leaves it at, guidance is a short themed hint, and the lists it
shows (toolbar buttons, fixed shortcuts) are complete."""
import copy
import json

import pytest
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QDialog, QLabel,
                               QScrollArea, QTabWidget)

import framedraft.prefs as prefs_mod
from framedraft.app import (SettingsDialog, _FIXED_SHORTCUTS, _TOOLBAR_ACTION_DEFS)


def _dialog(**over):
    return SettingsDialog({**copy.deepcopy(prefs_mod.DEFAULTS), **over})


def test_every_tab_scrolls_and_the_dialog_fits_the_screen():
    dlg = _dialog()
    dlg.show()
    QApplication.processEvents()
    try:
        avail = QApplication.primaryScreen().availableGeometry()
        tabs = dlg.findChild(QTabWidget)
        assert tabs.count() == 6
        for i in range(tabs.count()):
            assert isinstance(tabs.widget(i), QScrollArea), tabs.tabText(i)
        assert tabs.tabText(5) == "Print && PDF"          # shows as "Print & PDF"
        assert dlg.minimumSizeHint().height() < avail.height() // 2
        assert dlg.minimumSizeHint().width() < 600      # the hints wrap
        assert dlg.minimumWidth() <= dlg.width() <= int(avail.width() * 0.8)
        assert dlg.minimumHeight() <= dlg.height() <= int(avail.height() * 0.8)
        assert dlg.isSizeGripEnabled()
    finally:
        dlg.close()


def test_a_remembered_size_is_honored_and_clamped():
    avail = QApplication.primaryScreen().availableGeometry()
    dlg = _dialog(prefs_dialog_size=[600, 9000])
    try:
        assert dlg.width() == 600
        assert dlg.height() == max(int(avail.height() * 0.8), dlg.minimumHeight())
    finally:
        dlg.close()
    for junk in ([float("nan"), 500], [True, 400], "600x500", [0, 0]):
        d = _dialog(prefs_dialog_size=junk)                  # ignored, never raises
        d.close()


def test_hints_are_themed_not_hard_coded_gray():
    dlg = _dialog()
    try:
        hints = [lb for lb in dlg.findChildren(QLabel) if lb.objectName() == "hintLabel"]
        assert len(hints) >= 4
        for lb in dlg.findChildren(QLabel):
            assert "#888" not in lb.styleSheet()
    finally:
        dlg.close()


def test_spin_boxes_settle_on_commit():
    dlg = _dialog()
    try:
        boxes = dlg.findChildren(QAbstractSpinBox)
        assert boxes and all(not b.keyboardTracking() for b in boxes)
    finally:
        dlg.close()


def test_the_toolbar_tab_lists_every_button_and_round_trips():
    """Text was missing from the list, so it could not be hidden."""
    assert {k for k, _l, _h in _TOOLBAR_ACTION_DEFS} == set(prefs_mod.DEFAULTS["toolbar"])
    dlg = _dialog()
    try:
        assert set(dlg._tb_checks) == set(prefs_mod.DEFAULTS["toolbar"])
        dlg._tb_checks["text"].setChecked(False)
        assert dlg.to_prefs()["toolbar"]["text"] is False
    finally:
        dlg.close()


def test_the_dialog_hands_back_what_it_was_given():
    """The rewrite moved every control; the values must not move with them."""
    d = copy.deepcopy(prefs_mod.DEFAULTS)
    dlg = SettingsDialog(d)
    try:
        out = dlg.to_prefs()
    finally:
        dlg.close()
    for key, value in out.items():
        if key == "theme":
            assert value == {"light": {}, "dark": {}}
        elif key == "viewport":
            assert value == d["viewport"]
        elif isinstance(value, float):
            assert value == pytest.approx(d[key]), key
        else:
            assert value == d[key], key


def test_every_fixed_shortcut_is_listed_and_refused():
    shown = {k for _name, keys in _FIXED_SHORTCUTS for k in keys}
    assert shown <= SettingsDialog._RESERVED_KEYS
    assert SettingsDialog._RESERVED_KEYS - shown == {"Delete", "Escape"}  # long spellings
    dlg = _dialog()
    try:
        texts = {lb.text() for lb in dlg.findChildren(QLabel)}
        for name, keys in _FIXED_SHORTCUTS:
            assert name in texts and " / ".join(keys) in texts, name
        dlg._key_edits[0].setText("Ctrl+D")                  # Duplicate's
        assert not dlg._ok_btn.isEnabled()
        assert "reserved" in dlg._conflict_label.text()
    finally:
        dlg.close()


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    monkeypatch.setattr(MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    w = MainWindow()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()


def test_the_size_the_maker_leaves_is_kept_on_cancel(win, tmp_path, monkeypatch):
    def cancel_after_resize(self):
        self.resize(640, 560)
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(SettingsDialog, "exec", cancel_after_resize)
    win._open_settings()
    assert win._prefs["prefs_dialog_size"] == [640, 560]
    saved = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert saved["prefs_dialog_size"] == [640, 560]
