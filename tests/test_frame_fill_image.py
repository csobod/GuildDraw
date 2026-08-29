"""Frame Fill from a material swatch — an acetate sample sheet in place of the
flat colour.

The swatch is scaled to span the Stock Blank width and centred vertically on
the origin, so the frame shows the piece of sheet it would be cut from. These
run against a real FrameScene (the fill is Qt boolean path ops + a texture
brush); conftest provides the shared QApplication.
"""
import os
import zipfile

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage

import framedraft.export.gdraw as gdraw_mod
from framedraft.canvas.scene import FILL_IMAGE_MAX_PX, FrameScene
from framedraft.document import Layer
from framedraft.export.gdraw import load_gdraw, save_gdraw
from framedraft.export.svg import load_svg, portable_fill, resolve_fill_image
from helpers import circle, closed_diamond


def _swatch(path, w=200, h=100, color="#b03030"):
    """Write a plain image standing in for a supplier's sample sheet."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return str(path)


def _filled_scene(image=None, blank_w=170.0):
    scene = FrameScene()
    scene.add_curve(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    scene.add_curve(circle(-15, 0, 8))
    scene.add_curve(circle(15, 0, 8))
    scene.set_fill_blank_width(blank_w)
    if image:
        assert scene.set_fill_image(image)
    assert scene.set_fill_visible(True) == "ok"
    return scene


# ------------------------------------------------------------------ scene

def test_swatch_replaces_the_colour_brush(tmp_path):
    scene = _filled_scene(_swatch(tmp_path / "acetate.png"))
    brush = scene._fill_item.brush()
    assert brush.style() == Qt.BrushStyle.TexturePattern
    assert not brush.texture().isNull()


def test_swatch_spans_the_blank_width_centred_vertically(tmp_path):
    # 200x100 px onto a 170 mm blank -> 170 x 85 mm, centred on the origin.
    scene = _filled_scene(_swatch(tmp_path / "acetate.png", 200, 100),
                          blank_w=170.0)
    t = scene._fill_item.brush().transform()
    top_left     = t.map(QPointF(0, 0))
    bottom_right = t.map(QPointF(200, 100))
    assert top_left.x()     == pytest.approx(-85.0)
    assert bottom_right.x() == pytest.approx(85.0)
    assert top_left.y()     == pytest.approx(-42.5)
    assert bottom_right.y() == pytest.approx(42.5)


def test_blank_width_change_rescales_the_swatch(tmp_path):
    scene = _filled_scene(_swatch(tmp_path / "acetate.png", 200, 100),
                          blank_w=170.0)
    scene.set_fill_blank_width(100.0)
    t = scene._fill_item.brush().transform()
    assert t.map(QPointF(0, 0)).x()     == pytest.approx(-50.0)
    assert t.map(QPointF(200, 100)).x() == pytest.approx(50.0)
    # Aspect ratio is preserved — the sheet isn't stretched to fit.
    assert t.map(QPointF(200, 100)).y() == pytest.approx(25.0)


def test_opacity_fades_the_swatch_through_the_item(tmp_path):
    """A texture brush carries no alpha, so the item does the fading — and the
    two paths must not compound."""
    scene = _filled_scene(_swatch(tmp_path / "acetate.png"))
    scene.set_fill_opacity(0.4)
    assert scene._fill_item.opacity() == pytest.approx(0.4)
    scene.clear_fill_image()
    assert scene._fill_item.opacity() == pytest.approx(1.0)
    assert scene._fill_item.brush().color().alphaF() == pytest.approx(0.4)


def test_clearing_the_swatch_restores_the_picked_colour(tmp_path):
    scene = _filled_scene(_swatch(tmp_path / "acetate.png"))
    scene.set_fill_color(QColor("#227744"))
    scene.clear_fill_image()
    assert not scene.has_fill_image()
    assert scene._fill_item.brush().style() == Qt.BrushStyle.SolidPattern
    assert scene._fill_item.brush().color().name() == "#227744"


def test_unreadable_swatch_is_refused_and_leaves_the_colour(tmp_path):
    bogus = tmp_path / "not-an-image.png"
    bogus.write_text("this is not a PNG")
    scene = _filled_scene()
    assert scene.set_fill_image(str(bogus)) is False
    assert not scene.has_fill_image()
    assert scene._fill_item.brush().style() == Qt.BrushStyle.SolidPattern


def test_oversized_swatch_is_capped(tmp_path):
    big = FILL_IMAGE_MAX_PX + 1200
    scene = _filled_scene(_swatch(tmp_path / "huge.png", big, big // 2))
    tex = scene._fill_item.brush().texture()
    assert max(tex.width(), tex.height()) == FILL_IMAGE_MAX_PX
    # Downscaling must not change where the sheet sits.
    t = scene._fill_item.brush().transform()
    assert t.map(QPointF(0, 0)).x() == pytest.approx(-85.0)
    assert t.map(QPointF(tex.width(), tex.height())).x() == pytest.approx(85.0)


def test_lens_apertures_stay_open_under_a_swatch(tmp_path):
    """The fill region is geometry, not paint — a swatch must not change it."""
    # Both scenes stay referenced: dropping one deletes its C++ items, and the
    # QPainterPath taken from a deleted item is a dangling read.
    plain, textured = _filled_scene(), _filled_scene(_swatch(tmp_path / "acetate.png"))
    colour_path = plain._fill_item.path()
    image_path  = textured._fill_item.path()
    assert image_path.contains(QPointF(0, -30))
    assert not image_path.contains(QPointF(-15, 0))     # lens aperture
    assert image_path.boundingRect() == colour_path.boundingRect()


def test_fill_state_reports_the_swatch(tmp_path):
    img = _swatch(tmp_path / "acetate.png")
    scene = _filled_scene(img)
    assert scene.fill_state()["image"] == img
    scene.clear_fill_image()
    assert scene.fill_state()["image"] == ""


def test_swatch_survives_a_geometry_edit(tmp_path):
    """The coalesced rebuild repaints the fill; the material must come back
    with it rather than reverting to the colour mid-edit."""
    scene = _filled_scene(_swatch(tmp_path / "acetate.png"))
    scene.add_curve(circle(0, 25, 4))
    scene.rebuild_fill()
    assert scene._fill_item.brush().style() == Qt.BrushStyle.TexturePattern


# ------------------------------------------------------------- persistence

@pytest.fixture()
def cache_root(tmp_path, monkeypatch):
    root = tmp_path / "imagecache"
    monkeypatch.setattr(gdraw_mod, "_IMAGE_CACHE_ROOT", root)
    return root


def _fill_data(img_path: str, style: str = "image") -> dict:
    return {"front": {"fill": {"visible": True, "color": "#2a6099",
                               "opacity": 0.5, "style": style,
                               "image": img_path}}}


def test_gdraw_embeds_the_swatch_and_strips_the_source_path(tmp_path, cache_root):
    img = tmp_path / "secret_home" / "UB-0614.png"
    img.parent.mkdir()
    _swatch(img)
    doc = tmp_path / "designs" / "frame.gdraw"
    doc.parent.mkdir()

    data = _fill_data(str(img))
    save_gdraw(data, str(doc))

    with zipfile.ZipFile(doc) as zf:
        members = [n for n in zf.namelist() if n.startswith("images/")]
        assert members == ["images/front_fill_UB-0614.png"]
        assert zf.read(members[0]) == img.read_bytes()
        svg_text = zf.read("front.svg").decode("utf-8")
    assert "secret_home" not in svg_text
    assert "images/front_fill_UB-0614.png" in svg_text
    # The caller's dict is untouched — autosave reuses it.
    assert data["front"]["fill"]["image"] == str(img)


def test_gdraw_round_trip_restores_a_usable_swatch(tmp_path, cache_root):
    img = _swatch(tmp_path / "UB-0614.png")
    doc = tmp_path / "frame.gdraw"
    save_gdraw(_fill_data(img), str(doc))

    fill = load_gdraw(str(doc))["front"]["fill"]
    assert fill["style"] == "image"
    assert os.path.isfile(fill["image"])
    assert str(cache_root) in fill["image"]
    scene = FrameScene()
    assert scene.set_fill_image(fill["image"]) is True


def test_damaged_archive_degrades_to_the_colour(tmp_path, cache_root):
    """Metadata naming a member the zip doesn't hold must not break the open."""
    img = _swatch(tmp_path / "UB-0614.png")
    doc = tmp_path / "frame.gdraw"
    save_gdraw(_fill_data(img), str(doc))

    stripped = tmp_path / "stripped.gdraw"
    with zipfile.ZipFile(doc) as src, zipfile.ZipFile(stripped, "w") as dst:
        for n in src.namelist():
            if not n.startswith("images/"):
                dst.writestr(n, src.read(n))

    fill = load_gdraw(str(stripped))["front"]["fill"]
    assert fill["image"] == ""
    assert fill["color"] == "#2a6099"


def test_plain_svg_stores_a_document_relative_swatch_path(tmp_path):
    doc_dir = tmp_path / "designs"
    doc_dir.mkdir()
    img = _swatch(doc_dir / "UB-0614.png")
    fill = {"visible": True, "color": "#2a6099", "opacity": 0.5,
            "style": "image", "image": img}

    out = portable_fill(fill, str(doc_dir / "frame.svg"))
    assert out["image"] == "UB-0614.png"
    assert fill["image"] == img            # input dict untouched

    resolve_fill_image(out, str(doc_dir / "frame.svg"))
    assert out["image"] == img


def test_swatch_outside_the_document_folder_keeps_only_its_name(tmp_path):
    elsewhere = tmp_path / "supplier_downloads"
    elsewhere.mkdir()
    img = _swatch(elsewhere / "UB-0614.png")
    doc_dir = tmp_path / "designs"
    doc_dir.mkdir()

    out = portable_fill({"image": img}, str(doc_dir / "frame.svg"))
    assert out["image"] == "UB-0614.png"
    # …and it must not resolve to the supplier folder on the way back in.
    resolve_fill_image(out, str(doc_dir / "frame.svg"))
    assert out["image"] == "UB-0614.png"


def test_pre_1_2_fill_block_loads_as_a_colour(tmp_path):
    """A file written before the swatch existed carries no style/image keys."""
    from framedraft.document import (Calibration, FormingMetadata,
                                     MachinedBridge, MirrorAxis)
    from framedraft.export.svg import save_svg
    path = str(tmp_path / "old.svg")
    save_svg(curves=[], path=path, calibration=Calibration(),
             mirror=MirrorAxis(), forming=FormingMetadata(),
             machined_bridge=MachinedBridge(),
             fill={"visible": True, "color": "#2a6099", "opacity": 0.5})
    fill = load_svg(path)["fill"]
    assert "image" not in fill
    assert fill.get("style") is None


# ------------------------------------------------------------- app wiring

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


def _pick(monkeypatch, path):
    """Make the next swatch file dialog answer with *path* ('' = cancel)."""
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))


def test_choosing_a_swatch_switches_style_and_marks_dirty(fresh, tmp_path,
                                                          monkeypatch):
    img = _swatch(tmp_path / "UB-0614.png")
    _pick(monkeypatch, img)
    fresh._on_fill_image_clicked()

    ws = fresh._active_ws
    assert ws.fill_image == img
    assert ws.fill_style == "image"
    assert ws.scene.has_fill_image()
    assert fresh._fill_style_combo.currentData() == "image"
    assert fresh._fill_image_btn.text() == "UB-0614.png"
    assert fresh._dirty


def test_style_back_to_colour_keeps_the_swatch_attached(fresh, tmp_path,
                                                        monkeypatch):
    img = _swatch(tmp_path / "UB-0614.png")
    _pick(monkeypatch, img)
    fresh._on_fill_image_clicked()

    fresh._fill_style_combo.setCurrentIndex(
        fresh._fill_style_combo.findData("color"))
    ws = fresh._active_ws
    assert ws.fill_style == "color"
    assert not ws.scene.has_fill_image()      # the colour is showing…
    assert ws.fill_image == img               # …but the swatch is still there

    fresh._fill_style_combo.setCurrentIndex(
        fresh._fill_style_combo.findData("image"))
    assert ws.scene.has_fill_image()


def test_clearing_forgets_the_swatch(fresh, tmp_path, monkeypatch):
    _pick(monkeypatch, _swatch(tmp_path / "UB-0614.png"))
    fresh._on_fill_image_clicked()
    fresh._on_fill_image_cleared()

    ws = fresh._active_ws
    assert ws.fill_image == ""
    assert ws.fill_style == "color"
    assert not ws.scene.has_fill_image()
    assert fresh._fill_image_btn.text() == "Choose…"


def test_cancelling_the_auto_opened_picker_falls_back_to_colour(fresh,
                                                                monkeypatch):
    """Switching to Image opens the picker; backing out of it must not leave
    the combo on a style with nothing behind it."""
    _pick(monkeypatch, "")
    fresh._fill_style_combo.setCurrentIndex(
        fresh._fill_style_combo.findData("image"))
    assert fresh._active_ws.fill_style == "color"
    assert fresh._fill_style_combo.currentData() == "color"


def test_stock_width_spin_rescales_the_swatch(fresh, tmp_path, monkeypatch):
    _pick(monkeypatch, _swatch(tmp_path / "UB-0614.png", 200, 100))
    fresh._on_fill_image_clicked()
    fresh._stock_w_spin.setValue(120.0)

    ws = fresh._active_ws
    assert ws.scene.fill_blank_width() == pytest.approx(120.0)
    assert ws.stock_w == pytest.approx(120.0)
    # …and the guide it shares the number with still tracks it.
    assert ws.stock_guide._width_mm == pytest.approx(120.0)


def test_swatch_survives_a_gdraw_round_trip(fresh, tmp_path, monkeypatch,
                                            cache_root):
    from helpers import circle, closed_diamond
    fresh._active_ws.add_curve(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    fresh._active_ws.add_curve(circle(-15, 0, 8))
    _pick(monkeypatch, _swatch(tmp_path / "UB-0614.png"))
    fresh._on_fill_image_clicked()
    fresh._fill_show_chk.setChecked(True)

    doc = str(tmp_path / "frame.gdraw")
    fresh._do_save_gdraw(doc)
    # _do_save_gdraw is the writer, not File ▸ Save — it leaves the dirty flag
    # up, and _new() would then block on the unsaved-changes dialog forever.
    fresh._dirty = False
    fresh._new()
    assert fresh._active_ws.fill_image == ""
    fresh._open_gdraw(doc, remember=False)

    ws = fresh._active_ws
    assert ws.fill_style == "image"
    assert os.path.basename(ws.fill_image) == "UB-0614.png"
    assert ws.scene.has_fill_image()
    assert fresh._fill_style_combo.currentData() == "image"


def test_load_with_a_missing_swatch_shows_the_colour(fresh, tmp_path):
    ws = fresh._active_ws
    fresh._load_ws_data(ws, {"fill": {"visible": False, "color": "#227744",
                                      "opacity": 0.5, "style": "image",
                                      "image": str(tmp_path / "gone.png")}})
    assert ws.fill_style == "color"
    assert not ws.scene.has_fill_image()


def test_unknown_style_degrades_to_colour(fresh):
    ws = fresh._active_ws
    fresh._load_ws_data(ws, {"fill": {"style": "hologram", "image": ""}})
    assert ws.fill_style == "color"


def test_pre_1_2_document_loads_with_no_swatch(fresh):
    ws = fresh._active_ws
    fresh._load_ws_data(ws, {"fill": {"visible": False, "color": "#2a6099",
                                      "opacity": 0.5}})
    assert ws.fill_style == "color"
    assert ws.fill_image == ""


def test_image_style_with_no_swatch_normalises_to_colour(fresh):
    """A file claiming Image with nothing behind it would show the colour under
    a combo saying otherwise."""
    ws = fresh._active_ws
    fresh._load_ws_data(ws, {"fill": {"style": "image", "image": ""}})
    assert ws.fill_style == "color"
    assert fresh._fill_style_combo.currentData() == "color"


# ------------------------------------------------------------ swatch row

def test_the_clear_button_is_a_square_not_a_button_width(fresh):
    """The app stylesheet's `QPushButton { min-width: 54px }` is promoted over
    a plain setFixedWidth, so the ✕ came out 76 px wide and crowded the swatch
    name beside it. It should be a square the height of the row."""
    btn = fresh._fill_image_clear_btn
    assert btn.width() == btn.height()
    assert btn.width() <= 34
    assert btn.maximumWidth() == btn.width()      # the local rule really took


def test_a_long_swatch_name_is_elided_not_expanded(fresh, tmp_path, monkeypatch):
    """A supplier's file name can run past the sidebar; the button keeps the
    full name in its tooltip and elides the middle rather than dragging the
    panel wider."""
    long_name = "TORTOISE-DEMI-AMBER-LAMINATE-3MM-SHEET-BATCH-2026-04.png"
    img = _swatch(tmp_path / long_name)
    _pick(monkeypatch, img)
    fresh._on_fill_image_clicked()

    assert fresh._fill_image_full_text == long_name
    assert fresh._fill_image_btn.toolTip() == img
    shown = fresh._fill_image_btn.text()
    assert shown == long_name or "…" in shown
