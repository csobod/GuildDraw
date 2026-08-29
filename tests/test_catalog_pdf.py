"""PDF-for-Catalog export: component gathering, layout render, PDF write."""
import os

from PySide6.QtGui import QImage, QPainter, QColor

from framedraft.document import Curve, SplineNode, Layer
from framedraft.geometry import compute_catmull_handles
from framedraft.export.catalog_pdf import (
    paint_catalog, export_catalog_pdf, _content_bbox, PAPER_MM,
)


def _spline(pts, layer, closed=True):
    ns = [SplineNode(x=x, y=y) for x, y in pts]
    compute_catmull_handles(ns, closed)
    return Curve(kind="spline", layer=layer, nodes=ns, closed=closed)


def _sample_components():
    front = [_spline([(8, 0), (24, -16), (42, 0), (24, 17)], Layer.OUTLINE),
             _spline([(10, 0), (24, -13), (39, 0), (24, 14)], Layer.LENS)]
    temple = [_spline([(0, 0), (60, -3), (145, 2), (145, 10), (60, 9), (0, 8)],
                      Layer.OUTLINE)]
    return {"front": front, "temple_r": temple, "temple_l": list(temple)}


_SETTINGS = {
    "paper": "a5", "line_weight_mm": 0.6, "caption": True,
    "caption_font": "Courier New", "show_scale": False,
    "front_layers": ["OUTLINE", "LENS"], "temple_layers": ["OUTLINE"],
}


def _render(components, settings, caption, fills=None):
    pw, ph = PAPER_MM["a5"][1], PAPER_MM["a5"][0]   # landscape
    ppm = 150 / 25.4
    img = QImage(round(pw * ppm), round(ph * ppm), QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    paint_catalog(p, pw, ph, ppm, components, caption, settings, fills)
    p.end()
    return img


def _ink_count(img):
    return sum(1 for x in range(0, img.width(), 6) for y in range(0, img.height(), 6)
               if img.pixelColor(x, y) != QColor("#ffffff"))


def test_content_bbox_covers_geometry():
    c = _spline([(0, 0), (10, -5), (20, 0), (10, 8)], Layer.OUTLINE)
    bb = _content_bbox([c])
    assert bb is not None
    assert bb[0] <= 0 and bb[2] >= 20 and bb[1] <= -5 and bb[3] >= 8


def test_content_bbox_none_when_empty():
    assert _content_bbox([]) is None


def test_paint_draws_all_components_and_caption():
    img = _render(_sample_components(), _SETTINGS, "ACETATE-52-18-145")
    # a good amount of ink (three components + caption)
    assert _ink_count(img) > 200
    # caption is in the lower-right quadrant → that region has ink
    w, h = img.width(), img.height()
    lower_right = sum(
        1 for x in range(w * 3 // 4, w, 4) for y in range(h * 4 // 5, h, 4)
        if img.pixelColor(x, y) != QColor("#ffffff"))
    assert lower_right > 0, "no caption ink in the lower-right corner"


def test_paint_empty_components_is_noop():
    img = _render({"front": [], "temple_r": [], "temple_l": []}, _SETTINGS, "x")
    assert _ink_count(img) == 0


def test_caption_off_removes_lower_right_ink():
    s = {**_SETTINGS, "caption": False}
    img = _render(_sample_components(), s, "SHOULD-NOT-APPEAR")
    w, h = img.width(), img.height()
    lower_right = sum(
        1 for x in range(w * 3 // 4, w, 4) for y in range(h * 9 // 10, h, 4)
        if img.pixelColor(x, y) != QColor("#ffffff"))
    assert lower_right == 0


def test_export_writes_a_pdf(tmp_path):
    out = tmp_path / "catalog.pdf"
    export_catalog_pdf(str(out), _sample_components(), _SETTINGS, "MODEL-A")
    assert out.exists() and os.path.getsize(out) > 1000
    assert out.read_bytes()[:5] == b"%PDF-"


def test_export_half_letter(tmp_path):
    out = tmp_path / "hl.pdf"
    export_catalog_pdf(str(out), _sample_components(),
                       {**_SETTINGS, "paper": "half_letter"}, "MODEL-B")
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"


def _ink_centroid_y(img):
    total = wsum = 0
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            if img.pixelColor(x, y) != QColor("#ffffff"):
                total += 1
                wsum += y
    return (wsum / total) if total else 0.0


def test_content_offset_shifts_drawing_down_not_caption():
    """The vertical offset moves the drawing (front + temples) down the page;
    the caption stays pinned to the corner."""
    comps = _sample_components()
    centred = _render(comps, {**_SETTINGS, "content_offset_mm": 0.0}, "NAME")
    shifted = _render(comps, {**_SETTINGS, "content_offset_mm": 20.0}, "NAME")
    # ink overall moves down; a +20 mm shift at 150 dpi ≈ +118 px
    assert _ink_centroid_y(shifted) > _ink_centroid_y(centred) + 30
    # caption still present in the lower-right corner in both
    for img in (centred, shifted):
        w, h = img.width(), img.height()
        lr = sum(1 for x in range(w * 3 // 4, w, 4) for y in range(h * 4 // 5, h, 4)
                 if img.pixelColor(x, y) != QColor("#ffffff"))
        assert lr > 0


# ═══════════════════════════════════════════════════════════════════════
# Frame Fill / Lens Fill on the catalog sheet (v1.2)
#
# The overlays are display-only — they never become geometry — but a catalog
# page is the one export where the maker wants the colour, so Settings ▸ PDF
# can print them under the line work. The specs come straight off each
# workspace's live scene, so the sheet shows the tint the canvas shows.
# ═══════════════════════════════════════════════════════════════════════

from framedraft.canvas.scene import FrameScene                       # noqa: E402

_FILL_HEX = "#2a6099"


def _front_scene(fill=True, lens_fill=False):
    """A scene holding the sample front with the overlays switched on, and the
    same curve objects handed to the catalog as its "front" component."""
    scene = FrameScene()
    front = _sample_components()["front"]
    for c in front:
        scene.add_curve(c)
    if fill:
        scene.set_fill_color(_FILL_HEX)
        scene.set_fill_opacity(1.0)      # opaque, so a pixel probe reads it back
        assert scene.set_fill_visible(True) == "ok"
    if lens_fill:
        scene.set_lens_fill_colors("#101060", "#d0d0ff")
        scene.set_lens_fill_opacity(1.0)
        scene.set_lens_fill_intensity(1.0)
        assert scene.set_lens_fill_visible(True) == "ok"
    return scene, front


def _fills_for(scene):
    return {"front": {"frame": scene.fill_paint_spec(),
                      "lens":  scene.lens_fill_paint_spec()}}


def _colour_tally(img):
    """{hex: count} over a coarse grid of the sheet, whites dropped."""
    counts = {}
    for x in range(0, img.width(), 3):
        for y in range(0, img.height(), 3):
            c = img.pixelColor(x, y)
            if c != QColor("#ffffff"):
                counts[c.name()] = counts.get(c.name(), 0) + 1
    return counts


# ---------------------------------------------------------------- scene side

def test_scene_reports_no_fill_while_the_overlays_are_hidden():
    scene, _ = _front_scene(fill=False)
    assert scene.fill_paint_spec() is None
    assert scene.lens_fill_paint_spec() == []


def test_scene_reports_the_frame_fill_it_is_showing():
    scene, _ = _front_scene(fill=True)
    spec = scene.fill_paint_spec()
    assert spec is not None
    assert not spec["path"].isEmpty()
    assert spec["brush"].color().name() == _FILL_HEX
    # A colour brush carries its own alpha, so the painter must not fade it a
    # second time — that is the swatch's job, not the colour's.
    assert spec["opacity"] == 1.0


def test_scene_reports_one_spec_per_lens():
    scene, _ = _front_scene(fill=False, lens_fill=True)
    specs = scene.lens_fill_paint_spec()
    assert len(specs) == 1                       # the sample front has one lens
    path, brush = specs[0]
    assert not path.isEmpty()
    assert brush.gradient() is not None


def test_a_broken_outline_reports_no_frame_fill():
    """A perimeter that no longer closes can't be filled honestly on paper any
    more than it can on screen."""
    scene, front = _front_scene(fill=True)
    scene.remove_curve(front[0])                 # take the OUTLINE away
    assert scene.fill_paint_spec() is None


# ---------------------------------------------------------------- paint side

def test_the_frame_fill_floods_the_profile_on_the_sheet():
    scene, front = _front_scene(fill=True)
    # The front alone, so the temples' long strokes don't out-vote the flood.
    comps = {"front": front, "temple_r": [], "temple_l": []}

    plain  = _render(comps, _SETTINGS, "NAME")
    filled = _render(comps, _SETTINGS, "NAME", _fills_for(scene))

    assert _FILL_HEX not in _colour_tally(plain)
    # A flooded profile, not a tinted edge: the fill is the page's main colour.
    tally = _colour_tally(filled)
    assert max(tally, key=tally.get) == _FILL_HEX

    # …and every pixel it covers was bare paper before, so it went under the
    # line work rather than over it.
    flooded = [(x, y) for y in range(0, filled.height(), 2)
               for x in range(0, filled.width(), 2)
               if filled.pixelColor(x, y).name() == _FILL_HEX]
    assert len(flooded) > 200
    assert all(plain.pixelColor(x, y) == QColor("#ffffff") for x, y in flooded)


def test_the_lens_aperture_stays_out_of_the_frame_fill():
    """The fill is the OUTLINE minus the LENS apertures — printing it must not
    paint the lens shut."""
    scene, front = _front_scene(fill=True)
    comps = {**_sample_components(), "front": front}
    filled = _render(comps, _SETTINGS, "NAME", _fills_for(scene))
    # The lens centre (24, ~0 in scene mm) is the middle of the front row.
    w = filled.width()
    row_top = min(y for y in range(0, filled.height(), 2)
                  for x in range(0, w, 2)
                  if filled.pixelColor(x, y) != QColor("#ffffff"))
    # Sample a horizontal band a third of the way down the front and confirm
    # white (the open aperture) still survives inside the coloured profile.
    band = row_top + 40
    row = [filled.pixelColor(x, band).name() for x in range(0, w, 2)]
    assert _FILL_HEX in row
    first, last = row.index(_FILL_HEX), len(row) - 1 - row[::-1].index(_FILL_HEX)
    assert "#ffffff" in row[first:last], "the aperture was painted over"


def test_the_lens_fill_runs_dark_to_light_down_the_aperture():
    scene, front = _front_scene(fill=False, lens_fill=True)
    comps = {**_sample_components(), "front": front}
    img = _render(comps, _SETTINGS, "NAME", _fills_for(scene))
    tinted = [(x, y) for y in range(0, img.height(), 2)
              for x in range(0, img.width(), 2)
              if img.pixelColor(x, y).blue() > img.pixelColor(x, y).red() + 20]
    assert tinted, "no lens tint reached the sheet"
    ys = [y for _x, y in tinted]
    top_row, bottom_row = min(ys), max(ys)
    top    = [img.pixelColor(x, y) for x, y in tinted if y <= top_row + 2]
    bottom = [img.pixelColor(x, y) for x, y in tinted if y >= bottom_row - 2]
    # #101060 at the top, #d0d0ff at the bottom: the run gets lighter.
    assert (sum(c.lightness() for c in bottom) / len(bottom)
            > sum(c.lightness() for c in top) / len(top) + 20)


def test_no_fill_spec_paints_exactly_the_old_sheet():
    """fills=None and fills={} must both leave the pre-1.2 sheet untouched."""
    comps = _sample_components()
    a = _render(comps, _SETTINGS, "NAME", None)
    b = _render(comps, _SETTINGS, "NAME", {})
    assert _colour_tally(a) == _colour_tally(b)
    assert _ink_count(a) > 0


def test_a_fill_cannot_escape_its_own_component():
    """The fill comes off the OUTLINE/LENS layers whether or not the sheet is
    printing those, so an odd layer choice must not let a tint wash over the
    temples below it."""
    scene, front = _front_scene(fill=True)
    # Print the front's ENGRAVING layer — i.e. nothing of the profile the fill
    # was computed from — and give the row a tiny bbox to place against.
    tiny = [_spline([(24, -1), (25, -1), (25, 0), (24, 0)], Layer.ENGRAVING)]
    comps = {**_sample_components(), "front": tiny}
    img = _render(comps, _SETTINGS, "NAME", _fills_for(scene))
    # A hair of colour inside the 1 mm box is fine; a flooded page is not.
    assert _colour_tally(img).get(_FILL_HEX, 0) < 20


def test_export_writes_a_pdf_with_the_fills(tmp_path):
    scene, front = _front_scene(fill=True, lens_fill=True)
    comps = {**_sample_components(), "front": front}
    out = tmp_path / "filled.pdf"
    export_catalog_pdf(str(out), comps, _SETTINGS, "MODEL-C", _fills_for(scene))
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
    plain = tmp_path / "plain.pdf"
    export_catalog_pdf(str(plain), comps, _SETTINGS, "MODEL-C")
    assert os.path.getsize(out) > os.path.getsize(plain)


# ------------------------------------------------------------- app wiring

import pytest                                                       # noqa: E402


@pytest.fixture()
def win(tmp_path, monkeypatch):
    import framedraft.prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()


def _show_the_front_fill(win):
    from helpers import circle, closed_diamond
    from framedraft.document import Layer
    ws = win._workspaces[0]
    ws.add_curve(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    ws.add_curve(circle(-15, 0, 8))
    ws.add_curve(circle(15, 0, 8))
    win._fill_show_chk.setChecked(True)
    win._lens_fill_show_chk.setChecked(True)
    assert ws.scene.fill_paint_spec() is not None
    return ws


def test_settings_dialog_round_trips_the_fill_choice():
    from framedraft.app import SettingsDialog
    from framedraft.prefs import DEFAULTS
    dlg = SettingsDialog(dict(DEFAULTS), None)
    assert dlg.to_prefs()["catalog_pdf"]["include_fill"] is False
    dlg._cat_fill_chk.setChecked(True)
    assert dlg.to_prefs()["catalog_pdf"]["include_fill"] is True


def test_the_sheet_prints_line_work_only_by_default(win):
    _show_the_front_fill(win)
    assert win._prefs["catalog_pdf"]["include_fill"] is False
    assert win._gather_catalog_fills() == {}


def test_asking_for_the_fill_collects_the_showing_workspaces(win):
    _show_the_front_fill(win)
    win._prefs["catalog_pdf"]["include_fill"] = True
    fills = win._gather_catalog_fills()
    assert set(fills) == {"front"}          # the temples have no geometry
    assert fills["front"]["frame"] is not None
    assert len(fills["front"]["lens"]) == 2


def test_a_workspace_with_its_fill_off_contributes_nothing(win):
    _show_the_front_fill(win)
    win._prefs["catalog_pdf"]["include_fill"] = True
    win._fill_show_chk.setChecked(False)
    win._lens_fill_show_chk.setChecked(False)
    assert win._gather_catalog_fills() == {}
