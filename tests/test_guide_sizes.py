"""Guide sizes in the .gdraw (BUILDPLAN *Road to 2.0*, item 3): each
workspace's stock guide, and the front's pad block, are written with the
design and read back on open, so a design reopens on the blank it was drawn
against and a later save never swaps it for the session's."""
import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.document import Layer
from helpers import circle, closed_diamond


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


def _tab(win, i):
    win._ws_tab_widget.setCurrentIndex(i)
    QApplication.processEvents()
    return win._active_ws


def test_a_design_reopens_on_the_blank_it_was_drawn_against(win, tmp_path):
    front = win._active_ws
    for c in (closed_diamond(0, 0, 40), circle(-15, 0, 10), circle(15, 0, 10)):
        front.add_curve(c)
    win._stock_w_spin.setValue(180.0)
    win._stock_h_spin.setValue(90.0)
    win._pad_w_spin.setValue(50.0)
    temple = _tab(win, 1)
    win._stock_w_spin.setValue(175.0)
    _tab(win, 0)
    path = str(tmp_path / "frame.gdraw")
    win._do_save_gdraw(path)
    win._dirty = False

    # Another design's session sizes, then the file again.
    win._stock_w_spin.setValue(150.0)
    _tab(win, 1)
    win._stock_w_spin.setValue(160.0)
    _tab(win, 0)
    assert win._dirty                    # the sizes are saved with the design
    win._dirty = False
    win._new()
    win._open_gdraw(path, remember=False)

    assert (front.stock_w, front.stock_h, front.pad_w) == (180.0, 90.0, 50.0)
    assert win._stock_w_spin.value() == 180.0          # the active tab's sidebar
    assert front.stock_guide.width_mm == 180.0
    assert front.scene.fill_blank_width() == 180.0     # the swatch spans it
    assert win._stock_mm(front) == (180.0, 90.0)       # and the fit warning
    assert temple.stock_w == 175.0 and temple.stock_guide.width_mm == 175.0
    _tab(win, 1)
    assert win._stock_w_spin.value() == 175.0


def test_an_older_file_takes_the_sizes_preferences_start_at(win):
    # It kept the previous document's, which the next save wrote into it
    # (the 2.0 bug hunt).
    front = win._active_ws
    front.stock_w, front.pad_h = 165.0, 30.0
    win._load_ws_data(front, {"curves": []})
    assert (front.stock_w, front.pad_h) == (170.0, 45.0)
    temple = win._workspaces[1]
    temple.stock_w = 120.0
    win._load_ws_data(temple, {"curves": []})
    assert (temple.stock_w, temple.stock_h) == (170.0, 30.0)   # the temple blank


def test_a_damaged_size_is_held_to_the_sidebar_range(win):
    front = win._active_ws
    win._load_ws_data(front, {"guides": {
        "stock": {"width_mm": 9999, "height_mm": "wide"},
        "pad": {"width_mm": -3, "height_mm": 40}}})
    assert front.stock_w == 400.0                      # clamped
    assert front.stock_h == 85.0                       # unreadable: the default
    assert (front.pad_w, front.pad_h) == (10.0, 40.0)


def test_a_plain_svg_carries_them_too(win, tmp_path):
    from framedraft.export.svg import load_svg
    front = win._active_ws
    front.add_curve(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    win._stock_w_spin.setValue(182.0)
    path = str(tmp_path / "frame.svg")
    win._do_save_svg(path)
    win._dirty = False
    guides = load_svg(path)["guides"]
    assert guides["stock"]["width_mm"] == 182.0
    assert set(guides) == {"stock", "pad", "construction", "boxing"}



def test_the_measurements_a_front_is_drawn_to_travel_and_reset(win, tmp_path):
    """Crest height, crest width, angle height and the free boxing A/B/DBL
    were the session's: unsaved, unstarred, and carried into the next design."""
    front = win._active_ws
    front.add_curve(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    win._dirty = False
    win._guide_crest_height_spin.setValue(5.0)
    assert win._dirty
    win._guide_spread_spin.setValue(6.0)
    win._guide_drop_spin.setValue(3.0)
    win._boxing_a_spin.setValue(44.0)
    path = str(tmp_path / "measured.gdraw")
    assert win._do_save(path)
    win._new()
    assert win._guide_crest_height_spin.value() == 0.0
    assert win._boxing_a_spin.value() == win._prefs["boxing_a_mm"]
    win._open_gdraw(path, remember=False)
    assert (win._guide_crest_height_spin.value(), win._guide_spread_spin.value(),
            win._guide_drop_spin.value(), win._boxing_a_spin.value()) == (5.0, 6.0, 3.0, 44.0)


def test_the_arms_hang_from_the_crest():
    from PySide6.QtWidgets import QGraphicsScene
    from framedraft.construction import ConstructionGuides
    scene = QGraphicsScene()
    g = ConstructionGuides(scene)
    g.set_apical_radius(8.0)
    g.set_spread(8.0)
    g.set_pivot_y(8.0)
    g.set_crest_height(10.0)                  # 10 mm above the datum line
    arms = [it for it in g._items if hasattr(it, "line")]
    starts = sorted((round(it.line().x1(), 6), round(it.line().y1(), 6)) for it in arms)
    # The crest's top at y = -10 (scene y-down); the pivots 8 below it, at the
    # arc's quadrants (±8, -2).
    assert starts == [(-8.0, -2.0), (8.0, -2.0)]
