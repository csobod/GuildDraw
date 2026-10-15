"""The origin, visible and checked (BUILDPLAN *Road to 1.4*, item 1).

GuildModel 1.8.2 places a part by the drawing's origin. The temple stock guide
carries the core line at y = 0, the temple blank is a preference shared by both
temple tabs, and the readiness dot's fit warning follows the stock guide.
"""
import copy

import pytest
from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsScene

import framedraft.prefs as prefs_mod
from framedraft.construction import RectGuide
from framedraft.document import Layer

from helpers import circle, closed_diamond, line


def test_rect_guide_draws_the_core_line_only_when_asked():
    scene = QGraphicsScene()
    g = RectGuide(scene, "guide.stock", width_mm=170.0, height_mm=30.0,
                  core_line=True)
    assert g._items == []                         # hidden: nothing drawn
    g.set_visible(True)
    assert len(g._items) == 2
    core = g._items[1]
    assert isinstance(core, QGraphicsLineItem)
    ln = core.line()
    assert (ln.x1(), ln.y1(), ln.x2(), ln.y2()) == (-85.0, 0.0, 85.0, 0.0)
    g.set_width(200.0)                            # the line spans the blank
    assert g._items[1].line().x2() == 100.0
    g.set_core_line(False)
    assert len(g._items) == 1
    assert (g.width_mm, g.height_mm, g.core_line) == (200.0, 30.0, False)


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def test_temples_carry_the_core_line_and_the_front_does_not(win):
    front, temple_r, temple_l, hinge = win._workspaces
    assert front.stock_guide.core_line is False
    assert hinge.stock_guide.core_line is False
    for t in (temple_r, temple_l):
        assert t.stock_guide.core_line is True
        # GuildModel's default temple blank (TempleParams: 170 × 30 mm)
        assert (t.stock_guide.width_mm, t.stock_guide.height_mm) == (170.0, 30.0)
        assert len(t.stock_guide._items) == 2     # shown, with the line


def test_the_temple_blank_is_one_preference_for_both_temples(win):
    front, temple_r, temple_l, _ = win._workspaces
    assert win._prefs["temple_stock_width_mm"] == 170.0
    p = copy.deepcopy(win._prefs)
    p["temple_stock_width_mm"] = 180.0
    win._apply_settings(p)                        # on the front tab
    assert front.stock_guide.width_mm == 170.0    # the front's own stock, untouched
    assert temple_r.stock_w == 180.0 and temple_l.stock_w == 180.0
    # The batch export checks every tab: the inactive temples' new blank,
    # though their guides catch up only on activation.
    assert win._stock_mm(temple_r) == win._stock_mm(temple_l) == (180.0, 30.0)
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    assert win._stock_w_spin.value() == 180.0
    assert temple_r.stock_guide.width_mm == 180.0
    # Changed while a temple is active: its live widgets take it at once
    p["temple_stock_height_mm"] = 32.0
    win._apply_settings(p)
    assert win._stock_h_spin.value() == 32.0
    assert temple_r.stock_guide.height_mm == 32.0
    assert temple_l.stock_h == 32.0


def test_the_readiness_dot_follows_the_stock_guide(win):
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
              circle(-15, 0, 10), circle(15, 0, 10)):
        ws.add_curve(c)
    win._update_readiness()
    dot = win._readiness_dot
    assert "stock guide" not in dot.toolTip()     # ±40 fits 170 × 85
    win._stock_w_spin.setValue(60.0)
    assert "10.0 mm past the 60 × 85 mm stock guide" in dot.toolTip()
    win._stock_h_spin.setValue(50.0)
    assert "15.0 mm past the 60 × 50 mm stock guide" in dot.toolTip()
    assert dot.state() == "green"


def test_a_temple_off_the_core_line_stays_green_with_the_warning(win):
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    ws = win._active_ws
    ws.add_curve(line([(0, 7), (120, 7), (120, 17), (0, 17)], closed=True,
                      layer=Layer.OUTLINE))
    win._update_readiness()
    dot = win._readiness_dot
    assert dot.state() == "green"
    assert "core line" in dot.toolTip()
