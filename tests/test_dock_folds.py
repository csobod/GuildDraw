"""The Properties dock's sections fold under their headers (BUILDPLAN *Road to
2.0*, item 5), as GuildModel's dock does since its M20, and the dock
remembers the folds in prefs["dock_folds"]: only the ones turned from how
they open, by title."""
import json

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.collapsible import CollapsibleBox

_SECTIONS = {
    "Drawing", "Layers", "Measurements · front", "Measurements · temple",
    "Construction (Forming)", "Boxing System", "Stock Blank", "Pad Block",
    "Frame Fill", "Inlay Fill", "Lens Fill", "Reference Images", "Calibration",
    "Place Hole",
}


@pytest.fixture()
def prefs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    return tmp_path


def _window():
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    return w


def _close(w):
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def test_a_header_folds_its_section_away_and_back():
    box = CollapsibleBox("Frame Fill")
    assert box.header.objectName() == "collapsibleHeader"   # GuildModel's QSS name
    assert box.is_expanded() and not box.body.isHidden()
    assert box.header.arrowType() == Qt.ArrowType.DownArrow
    seen = []
    box.toggled.connect(seen.append)
    box.header.click()
    assert not box.is_expanded() and box.body.isHidden()
    assert box.header.arrowType() == Qt.ArrowType.RightArrow
    box.set_expanded(True)
    assert seen == [False, True] and not box.body.isHidden()
    box.set_title("Measurements — Temple R")
    assert box.title() == "Measurements — Temple R"
    box.deleteLater()


def test_every_section_of_the_dock_folds(prefs_dir):
    w = _window()
    try:
        assert set(w._folds) == _SECTIONS
        assert all(isinstance(b, CollapsibleBox) for b in w._folds.values())
        # The two Measurements sections share a title, never a fold.
        assert w._folds["Measurements · front"] is w._meas_front_box
        assert w._folds["Measurements · temple"] is w._meas_temple_box
    finally:
        _close(w)


def test_the_folds_are_remembered_by_title_and_only_the_turned_ones(prefs_dir):
    w = _window()
    w._folds["Lens Fill"].set_expanded(False)
    w._folds["Boxing System"].set_expanded(False)
    w._folds["Boxing System"].set_expanded(True)      # back as it opens
    assert w._fold_state() == {"Lens Fill": False}
    _close(w)
    saved = json.loads((prefs_dir / "prefs.json").read_text())
    assert saved["dock_folds"] == {"Lens Fill": False}

    w = _window()                                     # the next session
    try:
        assert not w._folds["Lens Fill"].is_expanded()
        assert all(box.is_expanded() for key, box in w._folds.items()
                   if key != "Lens Fill")
    finally:
        _close(w)


def test_a_damaged_fold_record_opens_every_section(prefs_dir):
    (prefs_dir / "prefs.json").write_text(json.dumps({"dock_folds": "nonsense"}))
    w = _window()
    try:
        assert all(box.is_expanded() for box in w._folds.values())
    finally:
        _close(w)


def test_a_fold_never_moves_the_temple_title(prefs_dir):
    w = _window()
    try:
        w._ws_tab_widget.setCurrentIndex(2)            # Temple L
        QApplication.processEvents()
        assert w._meas_temple_box.title() == "Measurements — Temple L"
        assert w._meas_temple_box.header.text() == "Measurements — Temple L"
    finally:
        _close(w)


def test_the_wheel_guard_still_covers_a_spin_box_in_a_fold(prefs_dir):
    w = _window()
    try:
        spin = w._inlay_fill_opacity_slider
        before = spin.value()
        pos = QPointF(spin.rect().center())
        ev = QWheelEvent(pos, QPointF(spin.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                         QPoint(0, 120), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                         False)
        QApplication.sendEvent(spin, ev)
        assert spin.value() == before                  # unfocused: the panel scrolls
        assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus
    finally:
        _close(w)
