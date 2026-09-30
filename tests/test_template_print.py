"""Print Front + Temples — 1:1 cutting templates (v1.3): layout, page
choice, painting at true scale, PDF pagination, and the app wiring."""
import re

import pytest
from PySide6.QtGui import QImage, QPainter, QColor

from framedraft.document import Curve, SplineNode, Layer, TextObject
from framedraft.geometry import compute_catmull_handles
from framedraft.export.template_print import (
    PAPER_SIZES, MARGIN_MM, LABEL_MM, RULER_STRIP_MM,
    component_bbox, component_sizes, printable_area, layout_pages,
    pages_clipped, resolve_page, paint_template_page, export_template_pdf,
)
from helpers import closed_diamond, line


def _spline(pts, layer, closed=True):
    ns = [SplineNode(x=x, y=y) for x, y in pts]
    compute_catmull_handles(ns, closed)
    return Curve(kind="spline", layer=layer, nodes=ns, closed=closed)


def _components():
    front = [_spline([(-70, 0), (-40, -22), (0, -10), (40, -22), (70, 0),
                      (40, 22), (0, 12), (-40, 22)], Layer.OUTLINE),
             _spline([(-60, 0), (-40, -16), (-20, 0), (-40, 16)], Layer.LENS),
             _spline([(20, 0), (40, -16), (60, 0), (40, 16)], Layer.LENS)]
    temple = [_spline([(0, 0), (70, -3), (145, 2), (145, 10), (70, 9), (0, 8)],
                      Layer.OUTLINE)]
    return {"front":    {"curves": front, "texts": []},
            "temple_r": {"curves": temple, "texts": []},
            "temple_l": {"curves": list(temple), "texts": []}}


def _tall_components():
    """A 100 mm-tall front (a big goggle) so a small sheet has to paginate."""
    comps = _components()
    comps["front"]["curves"] = [
        _spline([(-70, 0), (-40, -50), (0, -30), (40, -50), (70, 0),
                 (40, 50), (0, 30), (-40, 50)], Layer.OUTLINE)]
    return comps


_SETTINGS = {"paper": "letter", "orientation": "auto",
             "line_weight_mm": 0.35, "labels": True}


def _render(components, settings, page_w, page_h, placements, ppm=150 / 25.4,
            footer="MODEL · page 1 of 1"):
    img = QImage(round(page_w * ppm), round(page_h * ppm),
                 QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    paint_template_page(p, ppm, page_w, page_h, placements, components,
                        settings, footer)
    p.end()
    return img


def _ink_span_x(img, y0, y1, step=1):
    """(min_x, max_x) of non-white pixels between rows y0..y1."""
    xs = [x for y in range(y0, y1, 3) for x in range(0, img.width(), step)
          if img.pixelColor(x, y) != QColor("#ffffff")]
    return (min(xs), max(xs)) if xs else None


# ------------------------------------------------------------------ layout


def test_component_bbox_covers_curves_and_text():
    comp = {"curves": [line([(0, 0), (30, 0)])],
            "texts": [TextObject(text="HE", family="Arial", size_mm=5.0,
                                 anchor_x=50.0, anchor_y=-10.0)]}
    bb = component_bbox(comp)
    assert bb[0] <= 0 and bb[2] >= 50 and bb[1] <= -14.5 and bb[3] >= 0


def test_component_bbox_none_when_empty():
    assert component_bbox({"curves": [], "texts": []}) is None
    assert component_sizes({"front": {"curves": [], "texts": []}}) == []


def test_three_pieces_fit_one_letter_page_centered():
    sizes = component_sizes(_components())
    assert [s[0] for s in sizes] == ["front", "temple_r", "temple_l"]
    pw, ph, orient = resolve_page(_SETTINGS, sizes)
    assert orient == "landscape" and (pw, ph) == (279.4, 215.9)
    aw, ah = printable_area(pw, ph)
    pages = layout_pages(sizes, aw, ah)
    assert len(pages) == 1
    for (key, x, _y), (_k, _bb, w, _h) in zip(pages[0], sizes, strict=True):
        assert abs((x + w / 2) - aw / 2) < 1e-6, f"{key} not centered"
    # first piece sits right under its label; the rest stack downward
    assert pages[0][0][2] == LABEL_MM
    assert pages[0][0][2] < pages[0][1][2] < pages[0][2][2]
    assert not pages_clipped(sizes, aw, ah)


def test_stack_spills_onto_a_second_page():
    sizes = component_sizes(_tall_components())
    aw, ah = printable_area(210.0, 148.0)   # A5 landscape: 190 × 114
    pages = layout_pages(sizes, aw, ah)
    assert len(pages) == 2
    assert [p[0] for p in pages[0]] == ["front"]
    assert [p[0] for p in pages[1]] == ["temple_r", "temple_l"]
    assert not pages_clipped(sizes, aw, ah)
    # A5 portrait is narrower than the 145 mm temple, so that print is cropped
    assert pages_clipped(component_sizes(_components()),
                         *printable_area(*PAPER_SIZES["a5"][1:]))


def test_oversized_piece_gets_its_own_page_and_is_reported():
    huge = {"front": {"curves": [closed_diamond(0, 0, 200)], "texts": []},
            "temple_r": {"curves": [line([(0, 0), (20, 0)])], "texts": []}}
    sizes = component_sizes(huge)
    aw, ah = printable_area(215.9, 279.4)
    pages = layout_pages(sizes, aw, ah)
    assert len(pages) == 2 and pages[0][0][0] == "front"
    assert pages_clipped(sizes, aw, ah)


def test_orientation_can_be_forced():
    sizes = component_sizes(_components())
    assert resolve_page({**_SETTINGS, "orientation": "portrait"}, sizes)[:2] \
        == (215.9, 279.4)
    assert resolve_page({**_SETTINGS, "orientation": "landscape"}, sizes)[:2] \
        == (279.4, 215.9)
    # unknown paper / orientation fall back rather than raise
    pw, ph, orient = resolve_page({"paper": "nope", "orientation": "??"}, sizes)
    assert {pw, ph} == {215.9, 279.4} and orient in ("portrait", "landscape")


def test_auto_prefers_portrait_when_it_saves_a_page():
    # Three tall, narrow pieces: landscape Letter (196 mm tall printable)
    # needs two pages, portrait (259 mm) takes them in one.
    tall = {k: {"curves": [line([(0, 0), (0, 60), (10, 60), (10, 0)], closed=True)],
                "texts": []} for k in ("front", "temple_r", "temple_l")}
    assert resolve_page(_SETTINGS, component_sizes(tall))[2] == "portrait"


# ---------------------------------------------------------------- painting


def test_paint_is_true_scale():
    """A 100 mm wide piece spans 100 mm of paper (±1 %)."""
    ppm = 150 / 25.4
    comps = {"front": {"curves": [line([(0, 0), (100, 0), (100, 20), (0, 20)],
                                        closed=True)], "texts": []}}
    sizes = component_sizes(comps)
    pw, ph = 279.4, 215.9
    aw, ah = printable_area(pw, ph)
    pages = layout_pages(sizes, aw, ah)
    img = _render(comps, {**_SETTINGS, "labels": False}, pw, ph, pages[0], ppm)
    _key, x, y = pages[0][0]
    top = round((MARGIN_MM + y) * ppm)
    span = _ink_span_x(img, top + 2, top + round(18 * ppm))
    assert span is not None
    width_mm = (span[1] - span[0]) / ppm
    assert abs(width_mm - 100.0) < 1.0, f"drawn width {width_mm:.2f} mm"
    # …and it is centered on the printable width
    center_mm = (span[0] + span[1]) / 2 / ppm
    assert abs(center_mm - pw / 2) < 1.0


def test_paint_draws_ruler_and_footer_in_the_bottom_strip():
    ppm = 150 / 25.4
    comps = _components()
    sizes = component_sizes(comps)
    pw, ph = 279.4, 215.9
    aw, ah = printable_area(pw, ph)
    img = _render(comps, _SETTINGS, pw, ph, layout_pages(sizes, aw, ah)[0], ppm)
    strip_top = round((ph - MARGIN_MM - RULER_STRIP_MM) * ppm)
    strip_bot = round((ph - MARGIN_MM) * ppm)
    span = _ink_span_x(img, strip_top, strip_bot)
    assert span is not None
    # ruler starts at the margin and the footer reaches the right margin
    assert abs(span[0] / ppm - MARGIN_MM) < 1.5
    assert span[1] / ppm > pw - MARGIN_MM - 5.0
    # nothing is drawn below the bottom margin
    assert _ink_span_x(img, strip_bot + 2, img.height()) is None


def test_labels_can_be_switched_off():
    ppm = 150 / 25.4
    comps = {"front": {"curves": [closed_diamond(0, 0, 20)], "texts": []}}
    sizes = component_sizes(comps)
    pw, ph = 215.9, 279.4
    aw, ah = printable_area(pw, ph)
    pages = layout_pages(sizes, aw, ah)
    _key, x, y = pages[0][0]
    label_top = round((MARGIN_MM + y - LABEL_MM) * ppm)
    label_bot = round((MARGIN_MM + y) * ppm) - 2
    with_lbl = _render(comps, _SETTINGS, pw, ph, pages[0], ppm, footer="")
    without  = _render(comps, {**_SETTINGS, "labels": False}, pw, ph,
                       pages[0], ppm, footer="")
    assert _ink_span_x(with_lbl, label_top, label_bot) is not None
    assert _ink_span_x(without, label_top, label_bot) is None


def test_engraving_text_prints_with_its_temple():
    ppm = 150 / 25.4
    comps = {"temple_r": {"curves": [],
                          "texts": [TextObject(text="GUILD", family="Arial",
                                               size_mm=6.0)]}}
    sizes = component_sizes(comps)
    pw, ph = 279.4, 215.9
    aw, ah = printable_area(pw, ph)
    pages = layout_pages(sizes, aw, ah)
    img = _render(comps, {**_SETTINGS, "labels": False}, pw, ph, pages[0], ppm,
                  footer="")
    _key, x, y = pages[0][0]
    top = round((MARGIN_MM + y) * ppm)
    assert _ink_span_x(img, top, top + round(6 * ppm)) is not None


# --------------------------------------------------------------------- PDF


def _pdf_page_count(path) -> int:
    data = open(path, "rb").read()
    return len(re.findall(rb"/Type\s*/Page\b", data))


def test_export_writes_one_page_on_letter(tmp_path):
    out = tmp_path / "templates.pdf"
    pages, clipped = export_template_pdf(str(out), _components(), _SETTINGS,
                                         "MODEL-A")
    assert out.exists() and out.stat().st_size > 1000
    assert (pages, clipped) == (1, False)
    assert _pdf_page_count(out) == 1


def test_export_paginates_on_small_paper(tmp_path):
    out = tmp_path / "a5.pdf"
    pages, clipped = export_template_pdf(
        str(out), _tall_components(),
        {**_SETTINGS, "paper": "a5", "orientation": "landscape"}, "")
    assert pages == 2 and clipped is False
    assert _pdf_page_count(out) == 2


def test_every_paper_size_renders(tmp_path):
    for key in PAPER_SIZES:
        out = tmp_path / f"{key}.pdf"
        pages, _c = export_template_pdf(str(out), _components(),
                                        {**_SETTINGS, "paper": key})
        assert pages >= 1 and out.exists(), key


# --------------------------------------------------------------------- app


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


def test_settings_dialog_round_trips_template_prefs():
    from framedraft.app import SettingsDialog
    from framedraft.prefs import DEFAULTS
    dlg = SettingsDialog(dict(DEFAULTS), None)
    tp = dlg.to_prefs()["template_print"]
    assert tp == DEFAULTS["template_print"]
    dlg._tp_paper.setCurrentIndex(dlg._tp_paper.findData("a4"))
    dlg._tp_orient.setCurrentIndex(dlg._tp_orient.findData("portrait"))
    dlg._tp_lw.setValue(0.5)
    dlg._tp_labels_chk.setChecked(False)
    tp = dlg.to_prefs()["template_print"]
    assert tp == {"paper": "a4", "orientation": "portrait",
                  "line_weight_mm": 0.5, "labels": False}


def test_prefs_load_deep_merges_template_print(tmp_path, monkeypatch):
    import json
    import framedraft.prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(
        json.dumps({"template_print": {"paper": "a3"}}), encoding="utf-8")
    p = prefs_mod.load()
    assert p["template_print"]["paper"] == "a3"
    assert p["template_print"]["orientation"] == "auto"   # default survived


def test_gather_includes_ghost_hidden_layers_and_text(win):
    from framedraft.document import Layer
    front, tr, tl = win._workspaces[:3]
    half = _spline([(0, -20), (30, -22), (40, 0), (30, 20), (0, 18)],
                   Layer.OUTLINE, closed=False)
    front.add_curve(half)
    front.add_curve(closed_diamond(20, 0, 8, layer=Layer.LENS))
    front.add_curve(line([(0, 30), (40, 30)], layer=Layer.REF))
    front.scene.set_layer_visible(Layer.REF, False)
    tr.add_curve(line([(0, 0), (140, 0), (140, 8), (0, 8)], closed=True,
                      layer=Layer.OUTLINE))
    tr.add_text(TextObject(text="R", family="Arial", size_mm=4.0,
                           anchor_x=20, anchor_y=6))
    tr.add_text(TextObject(text="   ", family="Arial", size_mm=4.0))
    comps = win._gather_template_components()
    # front: mirror on by default → the half outline and the lens come twice;
    # the hidden REF line is left out
    assert len(comps["front"]["curves"]) == 4
    assert all(c.layer is not Layer.REF for c in comps["front"]["curves"])
    # temple: its outline (+ the horizontal ghost) and only the real text
    assert len(comps["temple_r"]["curves"]) == 2
    assert [t.text for t in comps["temple_r"]["texts"]] == ["R"]
    assert comps["temple_l"] == {"curves": [], "texts": []}


def test_export_action_writes_the_pdf(win, tmp_path, monkeypatch):
    import framedraft.app as app_mod
    out = tmp_path / "t.pdf"
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win._workspaces[0].add_curve(closed_diamond(0, 0, 25))
    win._export_pdf_templates()
    assert out.exists() and _pdf_page_count(out) == 1
    assert "1 page" in win._status.currentMessage()


def test_export_with_nothing_visible_informs(win, monkeypatch):
    import framedraft.app as app_mod
    seen = []
    monkeypatch.setattr(app_mod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: seen.append(a[1])))
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: pytest.fail("no dialog")))
    win._export_pdf_templates()
    assert seen and "Front + Temples" in seen[0]


def test_menu_entries_exist(win):
    texts = [a.text() for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu()))
             for a in m.actions()]
    assert any("Print Front + Temples" in t for t in texts)
    assert any("PDF Front + Temples" in t for t in texts)
