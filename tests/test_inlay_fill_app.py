"""Inlay Fill in the app (BUILDPLAN *Road to 2.0*, item 7): the box under
Frame Fill on the tabs that have the INLAY layer, each tab's own settings,
the image and Tumble bodies, the round trip through the .gdraw, the
Preferences defaults, and the catalog page."""
import os
import zipfile

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

import framedraft.export.gdraw as gdraw_mod
from framedraft.canvas.scene import DEFAULT_INLAY_FILL_COLOR, DEFAULT_INLAY_FILL_OPACITY
from framedraft.document import Layer
from framedraft.prefs import DEFAULTS
from helpers import circle, closed_diamond


@pytest.fixture(scope="module")
def win():
    from framedraft.app import MainWindow
    w = MainWindow()
    yield w
    for ws in w._workspaces:
        ws.scene.clearSelection()
    w._dirty = False


@pytest.fixture()
def fresh(win):
    win._dirty = False
    win._new()
    win._ws_tab_widget.setCurrentIndex(0)
    return win


@pytest.fixture()
def cache_root(tmp_path, monkeypatch):
    root = tmp_path / "imagecache"
    monkeypatch.setattr(gdraw_mod, "_IMAGE_CACHE_ROOT", root)
    return root


def _image(path, w=300, h=200, color="#30c0b0"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return str(path)


def _pick(monkeypatch, path):
    """Make the next image file dialog answer with *path* ('' = cancel)."""
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))


def _front_with_seats(win, *centers):
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 45), circle(-17, 0, 11), circle(17, 0, 11)):
        ws.add_curve(c)
    for cx, cy in centers:
        ws.add_curve(closed_diamond(cx, cy, 6, layer=Layer.INLAY))
    win._do_layer_panel_refresh()                 # what the document change runs
    return ws


# ── The box ────────────────────────────────────────────────────────────────

def test_the_box_lives_where_the_inlay_layer_does(fresh):
    shown = []
    for i in range(4):
        fresh._ws_tab_widget.setCurrentIndex(i)
        QApplication.processEvents()
        shown.append(not fresh._inlay_fill_box.isHidden())
    assert shown == [True, True, True, False]      # front, temples; not the hinge
    fresh._ws_tab_widget.setCurrentIndex(0)


def test_showing_with_no_inlay_reverts_the_tick(fresh, monkeypatch):
    import framedraft.app as app_mod
    said = []
    monkeypatch.setattr(app_mod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: said.append(a[2])))
    fresh._inlay_fill_show_chk.setChecked(True)
    assert not fresh._inlay_fill_show_chk.isChecked()
    assert fresh._active_ws.inlay_fill_visible is False
    assert "no inlays" in said[0]


def test_showing_with_a_seat_sticks_and_marks_the_design(fresh):
    ws = _front_with_seats(fresh, (0, -30))
    fresh._dirty = False
    fresh._inlay_fill_show_chk.setChecked(True)
    assert ws.inlay_fill_visible is True
    assert len(ws.scene._inlay_fill_items) == 1
    assert fresh._dirty


def test_choosing_an_image_switches_the_style_and_names_the_file(fresh, tmp_path,
                                                                 monkeypatch):
    ws = _front_with_seats(fresh, (0, -30))
    _pick(monkeypatch, _image(tmp_path / "turquoise.png"))
    fresh._inlay_fill_style_combo.setCurrentIndex(1)   # Image: opens the picker
    assert ws.inlay_fill_style == "image"
    assert os.path.basename(ws.inlay_fill_image) == "turquoise.png"
    assert ws.scene.has_inlay_fill_image()
    assert fresh._swatch_btn_texts[fresh._inlay_fill_image_btn] == "turquoise.png"
    assert not fresh._inlay_fill_color_btn.isEnabled()
    # The ✕ forgets it and the color comes back.
    fresh._inlay_fill_image_clear_btn.click()
    assert (ws.inlay_fill_style, ws.inlay_fill_image) == ("color", "")
    assert fresh._inlay_fill_style_combo.currentData() == "color"


def test_leaving_the_picker_without_an_image_keeps_the_color(fresh, monkeypatch):
    ws = _front_with_seats(fresh, (0, -30))
    _pick(monkeypatch, "")
    fresh._inlay_fill_style_combo.setCurrentIndex(1)
    assert ws.inlay_fill_style == "color"
    assert fresh._inlay_fill_style_combo.currentData() == "color"


def test_tumble_waits_for_an_image_on_two_bodies(fresh, tmp_path, monkeypatch):
    ws = _front_with_seats(fresh, (-12, -30))
    assert not fresh._inlay_fill_tumble_chk.isEnabled()      # a color
    _pick(monkeypatch, _image(tmp_path / "turquoise.png"))
    fresh._on_inlay_fill_image_clicked()
    assert not fresh._inlay_fill_tumble_chk.isEnabled()      # one body
    ws.add_curve(closed_diamond(12, -30, 6, layer=Layer.INLAY))
    fresh._do_layer_panel_refresh()
    assert fresh._inlay_fill_tumble_chk.isEnabled()          # two bodies
    fresh._inlay_fill_show_chk.setChecked(True)
    fresh._inlay_fill_tumble_chk.setChecked(True)
    assert ws.inlay_fill_tumble and ws.scene._inlay_fill_tumble


def test_each_tab_keeps_its_own_inlay_fill(fresh):
    front = _front_with_seats(fresh, (0, -30))
    fresh._inlay_fill_show_chk.setChecked(True)
    fresh._inlay_fill_opacity_slider.setValue(40)
    fresh._ws_tab_widget.setCurrentIndex(1)                  # Temple R
    QApplication.processEvents()
    temple = fresh._active_ws
    assert not fresh._inlay_fill_show_chk.isChecked()
    assert fresh._inlay_fill_opacity_slider.value() == round(
        DEFAULT_INLAY_FILL_OPACITY * 100)
    temple.add_curve(closed_diamond(60, 0, 50))
    temple.add_curve(closed_diamond(60, 0, 4, layer=Layer.INLAY))
    fresh._inlay_fill_show_chk.setChecked(True)
    fresh._ws_tab_widget.setCurrentIndex(0)
    QApplication.processEvents()
    assert fresh._inlay_fill_opacity_slider.value() == 40
    assert front.inlay_fill_opacity == pytest.approx(0.40)
    assert temple.inlay_fill_visible and front.inlay_fill_visible


# ── The file ───────────────────────────────────────────────────────────────

def test_the_inlay_fill_survives_a_gdraw_round_trip(fresh, tmp_path, monkeypatch,
                                                    cache_root):
    ws = _front_with_seats(fresh, (-12, -30), (12, -30))
    _pick(monkeypatch, _image(tmp_path / "turquoise.png"))
    fresh._on_inlay_fill_image_clicked()
    fresh._inlay_fill_show_chk.setChecked(True)
    fresh._inlay_fill_tumble_chk.setChecked(True)
    fresh._inlay_fill_opacity_slider.setValue(70)
    shown = [it.brush().transform() for it in ws.scene._inlay_fill_items]

    doc = str(tmp_path / "frame.gdraw")
    fresh._do_save_gdraw(doc)
    fresh._dirty = False
    with zipfile.ZipFile(doc) as zf:
        members = [n for n in zf.namelist() if n.startswith("images/")]
    assert members == ["images/front_inlay_fill_turquoise.png"]

    fresh._new()
    assert fresh._active_ws.inlay_fill_image == ""
    fresh._open_gdraw(doc, remember=False)
    ws = fresh._active_ws
    assert (ws.inlay_fill_visible, ws.inlay_fill_style, ws.inlay_fill_tumble) == \
        (True, "image", True)
    assert ws.inlay_fill_opacity == pytest.approx(0.70)
    assert os.path.basename(ws.inlay_fill_image) == "turquoise.png"
    assert str(cache_root) in ws.inlay_fill_image
    # The file reopens tumbled the same way it was saved.
    assert [it.brush().transform() for it in ws.scene._inlay_fill_items] == shown
    assert fresh._inlay_fill_tumble_chk.isChecked()
    assert fresh._inlay_fill_style_combo.currentData() == "image"


def test_an_older_file_opens_with_the_fill_off_at_the_defaults(fresh):
    ws = fresh._active_ws
    fresh._load_ws_data(ws, {})
    assert ws.inlay_fill_visible is False
    assert (ws.inlay_fill_color, ws.inlay_fill_style, ws.inlay_fill_tumble) == \
        (DEFAULT_INLAY_FILL_COLOR, "color", False)
    assert ws.inlay_fill_opacity == pytest.approx(DEFAULT_INLAY_FILL_OPACITY)


def test_a_missing_image_falls_back_to_the_color(fresh, tmp_path):
    ws = fresh._active_ws
    fresh._load_ws_data(ws, {"inlay_fill": {
        "visible": False, "color": "#227744", "opacity": 0.5, "style": "image",
        "image": str(tmp_path / "gone.png"), "tumble": True}})
    assert ws.inlay_fill_style == "color"
    assert ws.inlay_fill_color == "#227744"
    assert "couldn't be read" in fresh._status.currentMessage()


def test_a_plain_svg_keeps_the_inlay_image_beside_it(fresh, tmp_path, monkeypatch):
    from framedraft.export.svg import load_svg
    _front_with_seats(fresh, (0, -30))
    img = _image(tmp_path / "turquoise.png")
    _pick(monkeypatch, img)
    fresh._on_inlay_fill_image_clicked()
    path = str(tmp_path / "frame.svg")
    fresh._do_save_svg(path)
    fresh._dirty = False
    saved = load_svg(path)["inlay_fill"]
    assert saved["image"] == "turquoise.png"        # relative: no home folder
    assert saved["style"] == "image"


def test_new_resets_to_the_preferred_defaults(fresh):
    ws = _front_with_seats(fresh, (0, -30))
    fresh._inlay_fill_show_chk.setChecked(True)
    fresh._prefs["inlay_fill_color"] = "#884422"
    fresh._prefs["inlay_fill_opacity_pct"] = 55
    try:
        fresh._dirty = False
        fresh._new()
        assert ws.inlay_fill_visible is False
        assert ws.inlay_fill_color == "#884422"
        assert ws.inlay_fill_opacity == pytest.approx(0.55)
    finally:
        fresh._prefs["inlay_fill_color"] = DEFAULTS["inlay_fill_color"]
        fresh._prefs["inlay_fill_opacity_pct"] = DEFAULTS["inlay_fill_opacity_pct"]


# ── Preferences ────────────────────────────────────────────────────────────

def test_the_shipped_defaults_match_the_scene():
    assert DEFAULTS["inlay_fill_color"] == DEFAULT_INLAY_FILL_COLOR
    assert DEFAULTS["inlay_fill_opacity_pct"] == round(DEFAULT_INLAY_FILL_OPACITY * 100)


def test_preferences_hand_back_the_inlay_defaults(fresh):
    from framedraft.app import SettingsDialog
    dlg = SettingsDialog(dict(fresh._prefs), fresh)
    dlg._inlay_default_color = "#556677"
    dlg._inlay_opacity_spin.setValue(60)
    values = dlg.to_prefs()
    assert (values["inlay_fill_color"], values["inlay_fill_opacity_pct"]) == \
        ("#556677", 60)
    dlg.deleteLater()


def test_a_new_default_moves_only_the_fills_still_on_the_old_one(fresh):
    import copy
    front, temple = fresh._workspaces[0], fresh._workspaces[1]
    temple.inlay_fill_color = "#010203"                      # dialed in
    p = copy.deepcopy(fresh._prefs)
    p["inlay_fill_color"] = "#998877"
    p["inlay_fill_opacity_pct"] = 50
    try:
        fresh._apply_settings(p)
        assert front.inlay_fill_color == "#998877"
        assert front.inlay_fill_opacity == pytest.approx(0.50)
        assert temple.inlay_fill_color == "#010203"
        assert fresh._inlay_fill_opacity_slider.value() == 50
    finally:
        p["inlay_fill_color"] = DEFAULTS["inlay_fill_color"]
        p["inlay_fill_opacity_pct"] = DEFAULTS["inlay_fill_opacity_pct"]
        fresh._apply_settings(p)


# ── The catalog page ───────────────────────────────────────────────────────

def test_the_catalog_gathers_the_inlay_with_the_fills(fresh):
    _front_with_seats(fresh, (-12, -30), (12, -30))
    fresh._inlay_fill_show_chk.setChecked(True)
    cfg = fresh._prefs.setdefault("catalog_pdf", {})
    was = cfg.get("include_fill", False)
    cfg["include_fill"] = True
    try:
        fills = fresh._gather_catalog_fills()
    finally:
        cfg["include_fill"] = was
    assert len(fills["front"]["inlay"]) == 2
    assert fills["front"]["frame"] is None                   # Frame Fill is off


def test_the_catalog_paints_the_inlay_over_the_frame():
    from framedraft.export.catalog_pdf import _draw_fill
    frame_path, inlay_path = QPainterPath(), QPainterPath()
    frame_path.addRect(QRectF(0, 0, 100, 100))
    inlay_path.addRect(QRectF(40, 40, 20, 20))
    img = QImage(100, 100, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    _draw_fill(p, {"frame": {"path": frame_path, "brush": QBrush(QColor("#0000ff")),
                             "opacity": 1.0},
                   "inlay": [(inlay_path, QBrush(QColor("#ff0000")), 1.0)],
                   "lens": []},
               QRectF(0, 0, 100, 100))
    p.end()
    assert img.pixelColor(50, 50).name() == "#ff0000"
    assert img.pixelColor(10, 10).name() == "#0000ff"
