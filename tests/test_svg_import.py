"""SVG import (v1.3.1) — paths as exact splines, shapes, transforms, units,
layer policy, the hairline seam, placement, and the app-level pour."""
import math

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.document import (
    Calibration, FormingMetadata, Layer, MachinedBridge, MirrorAxis,
)
from framedraft.export.svg import save_svg
from framedraft.export.svg_import import (
    content_bbox, import_svg, place_curves, read_svg,
)
from framedraft.geometry import point_at_t, sample_curve
from helpers import spline

_MM_PER_PX = 25.4 / 96.0


def _svg(body: str, attrs: str = "") -> str:
    return (f'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" {attrs}>'
            f"{body}</svg>")


def _write(tmp_path, body, attrs="", name="in.svg"):
    p = tmp_path / name
    p.write_text(_svg(body, attrs), encoding="utf-8")
    return str(p)


def _read(tmp_path, body, attrs="", layer=Layer.REF, ws="front"):
    return read_svg(_write(tmp_path, body, attrs), layer, ws)


def _bbox(c):
    """Sampled extent, every node included (the importer's own sampler)."""
    return content_bbox([c])


def _gaps(c):
    ns = c.nodes
    return [math.hypot(ns[i].x - ns[i - 1].x, ns[i].y - ns[i - 1].y) for i in range(1, len(ns))]


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def test_declared_millimeters_against_a_viewbox_scale_exactly(tmp_path):
    doc = _read(tmp_path, '<rect x="0" y="0" width="200" height="400"/>',
                'width="100mm" height="200mm" viewBox="0 0 200 400"')
    assert doc.physical is True
    assert doc.bbox == pytest.approx((0, 0, 100, 200))


def test_a_viewbox_alone_is_read_at_96_px_per_inch(tmp_path):
    doc = _read(tmp_path, '<rect x="0" y="0" width="96" height="96"/>',
                'viewBox="0 0 500 600"')
    assert doc.physical is False
    assert doc.width_mm == pytest.approx(25.4) and doc.height_mm == pytest.approx(25.4)


def test_inches_and_px_widths_without_a_viewbox(tmp_path):
    doc = _read(tmp_path, '<rect x="0" y="0" width="1" height="1"/>', 'width="2in" height="2in"')
    assert doc.physical and doc.width_mm == pytest.approx(25.4)
    doc = _read(tmp_path, '<rect x="0" y="0" width="96" height="48"/>', 'width="96px" height="48px"')
    assert not doc.physical and doc.width_mm == pytest.approx(25.4)


def test_guilddraw_own_svg_comes_back_where_it_was_drawn(tmp_path):
    src = spline([(-20, -5), (0, -12), (20, -5), (0, 8)], closed=True, layer=Layer.LENS)
    path = str(tmp_path / "own.svg")
    save_svg(curves=[src], path=path, calibration=Calibration(), mirror=MirrorAxis(),
             forming=FormingMetadata(), machined_bridge=MachinedBridge())
    doc = read_svg(path, Layer.REF, "front")
    assert doc.physical and doc.guilddraw_native
    assert any("File ▸ Open" in n for n in doc.notes)
    assert len(doc.curves) == 1
    got = doc.curves[0]
    assert got.kind == "spline" and got.closed and got.layer is Layer.LENS   # data-layer kept
    for i in range(50):
        t = i / 49
        ex, ey = point_at_t(src, t)
        gx, gy = point_at_t(got, t)
        assert math.hypot(ex - gx, ey - gy) < 2e-3


# ---------------------------------------------------------------------------
# Path data
# ---------------------------------------------------------------------------

def test_cubic_path_keeps_its_anchors_and_handles_exactly(tmp_path):
    d = "M 0,0 C 10,20 30,20 40,0 c 5,-10 15,-10 20,0"
    doc = _read(tmp_path, f'<path d="{d}"/>', 'width="100mm" viewBox="0 0 100 100"')
    c = doc.curves[0]
    assert c.kind == "spline" and not c.closed and len(c.nodes) == 3
    n0, n1, n2 = c.nodes
    assert (n0.x, n0.y) == (0, 0) and n0.cp_in is None
    assert (n0.cp_out.x, n0.cp_out.y) == (10, 20)
    assert (n1.cp_in.x, n1.cp_in.y) == (30, 20) and (n1.x, n1.y) == (40, 0)
    assert (n1.cp_out.x, n1.cp_out.y) == (45, -10)
    assert (n2.cp_in.x, n2.cp_in.y) == (55, -10) and (n2.x, n2.y) == (60, 0)
    assert n2.cp_out is None


def test_straight_segments_in_a_spline_have_no_handles(tmp_path):
    d = "M 0 0 L 10 0 C 15 5 15 15 10 20 H 0 V 0 Z"
    c = _read(tmp_path, f'<path d="{d}"/>', 'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert c.kind == "spline" and c.closed
    assert len(c.nodes) == 4                         # (0,0) (10,0) (10,20) (0,20); Z folds
    assert c.nodes[0].cp_out is None and c.nodes[1].cp_in is None
    assert c.nodes[1].cp_out is not None and c.nodes[2].cp_in is not None
    assert c.nodes[2].cp_out is None and c.nodes[3].cp_in is None
    assert c.nodes[0].cp_in is None                  # the wrap V 0 → start is straight


def test_polyline_path_imports_as_a_line_curve_with_z_folded(tmp_path):
    c = _read(tmp_path, '<path d="M0 0 L10 0 L10 10 L0 10 L0 0 Z"/>',
              'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert c.kind == "line" and c.closed
    assert [(n.x, n.y) for n in c.nodes] == [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_implicit_repetition_and_relative_moves(tmp_path):
    # pairs after m are relative lineto; a second subpath starts with m from the pen
    d = "m 10,10 20,0 0,20 z m 5,5 10,0"
    doc = _read(tmp_path, f'<path d="{d}"/>', 'width="100mm" viewBox="0 0 100 100"')
    assert len(doc.curves) == 2
    tri, seg = doc.curves
    assert tri.closed and [(n.x, n.y) for n in tri.nodes] == [(10, 10), (30, 10), (30, 30)]
    # after z the pen is back at the subpath start (10,10); m 5,5 → (15,15)
    assert [(n.x, n.y) for n in seg.nodes] == [(15, 15), (25, 15)] and not seg.closed


def test_quadratic_is_raised_to_the_same_curve(tmp_path):
    c = _read(tmp_path, '<path d="M 0 0 Q 10 20 20 0"/>',
              'width="100mm" viewBox="0 0 100 100"').curves[0]
    # the quadratic's midpoint is (10, 10); the elevated cubic passes through it
    x, y = point_at_t(c, 0.5)
    assert (x, y) == pytest.approx((10, 10), abs=1e-9)
    assert (c.nodes[0].cp_out.x, c.nodes[0].cp_out.y) == pytest.approx((20 / 3, 40 / 3))


def test_smooth_continuations_reflect_the_previous_handle(tmp_path):
    d = "M 0 0 C 0 10 10 10 10 0 S 20 -10 20 0 Q 25 10 30 0 T 40 0"
    c = _read(tmp_path, f'<path d="{d}"/>', 'width="100mm" viewBox="0 0 100 100"').curves[0]
    n1 = c.nodes[1]                                  # (10,0): cp_in (10,10) → cp_out (10,-10)
    assert (n1.cp_out.x, n1.cp_out.y) == pytest.approx((10, -10))
    # T reflects Q's control (25,10) about (30,0) → (35,-10); cubic c1 = p + 2/3 (q - p)
    n3 = c.nodes[3]
    assert (n3.cp_out.x, n3.cp_out.y) == pytest.approx((30 + 2 / 3 * 5, -2 / 3 * 10))


def test_arc_flags_glued_to_the_next_number(tmp_path):
    # "0 01 10 10": large=0, sweep=1, then x=10 y=10 — a number regex would read 01 as 1
    c = _read(tmp_path, '<path d="M 0 0 a 10 10 0 01 10 10"/>',
              'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert c.kind == "spline" and len(c.nodes) == 2
    x, y = point_at_t(c, 1.0)
    assert (x, y) == pytest.approx((10, 10))


# sweep=1 runs in the positive-angle direction: from (0,0) at 270° about (0,10)
# to (10,10) at 0°; sweep=0 is the other small arc, about (10,0).
@pytest.mark.parametrize("sweep,center", [(1, (0, 10)), (0, (10, 0))])
def test_arc_sweep_picks_the_center_and_stays_on_the_circle(tmp_path, sweep, center):
    c = _read(tmp_path, f'<path d="M 0 0 A 10 10 0 0 {sweep} 10 10"/>',
              'width="100mm" viewBox="0 0 100 100"').curves[0]
    for x, y, _t in sample_curve(c, n_per_seg=32):
        assert math.hypot(x - center[0], y - center[1]) == pytest.approx(10.0, abs=3e-3)


def test_a_full_turn_arc_pair_is_a_closed_ring(tmp_path):
    d = "M 10 0 A 10 10 0 1 1 -10 0 A 10 10 0 1 1 10 0 Z"
    c = _read(tmp_path, f'<path d="{d}"/>', 'width="100mm" viewBox="-50 -50 100 100"').curves[0]
    assert c.closed and len(c.nodes) == 4            # two half turns, two quarters each
    assert _bbox(c) == pytest.approx((-10, -10, 10, 10), abs=3e-3)


def test_hairline_closing_segment_folds_into_the_seam(tmp_path):
    # a converter ended the last cubic 4 µm short of the start, then wrote Z
    d = "M 0 0 C 0 10 10 10 10 0 C 10 -10 0.004 -10 0.004 -0.002 Z"
    c = _read(tmp_path, f'<path d="{d}"/>', 'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert c.closed and len(c.nodes) == 2
    assert min(_gaps(c)) > 1.0
    assert c.nodes[0].cp_in is not None              # the arriving handle survived the fold


def test_zero_length_segments_are_dropped(tmp_path):
    c = _read(tmp_path, '<path d="M 0 0 L 0 0 L 10 0 L 10 0 L 10 10"/>',
              'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert c.kind == "line" and [(n.x, n.y) for n in c.nodes] == [(0, 0), (10, 0), (10, 10)]


def test_malformed_path_is_reported_not_fatal(tmp_path):
    doc = _read(tmp_path, '<path d="M 0 0 L 10 x"/><path d="M 0 0 L 5 5"/>',
                'width="100mm" viewBox="0 0 100 100"')
    assert len(doc.curves) == 1
    assert any("malformed path×1" in n for n in doc.notes)


# ---------------------------------------------------------------------------
# Shapes and transforms
# ---------------------------------------------------------------------------

def test_rect_line_polyline_polygon(tmp_path):
    body = ('<rect x="1" y="2" width="3" height="4"/>'
            '<line x1="0" y1="0" x2="5" y2="5"/>'
            '<polyline points="0,0 1,1 2,0"/>'
            '<polygon points="0,0 4,0 4,4"/>')
    doc = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"')
    rect, line, pl, pg = doc.curves
    assert rect.kind == "line" and rect.closed and len(rect.nodes) == 4
    assert _bbox(rect) == pytest.approx((1, 2, 4, 6))
    assert line.kind == "line" and len(line.nodes) == 2 and not line.closed
    assert pl.kind == "line" and len(pl.nodes) == 3 and not pl.closed
    assert pg.kind == "line" and pg.closed and len(pg.nodes) == 3


def test_rounded_rect_is_a_closed_spline_within_its_box(tmp_path):
    c = _read(tmp_path, '<rect x="0" y="0" width="20" height="10" rx="3"/>',
              'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert c.kind == "spline" and c.closed
    assert _bbox(c) == pytest.approx((0, 0, 20, 10), abs=1e-3)
    assert point_at_t(c, 0.0)[0] == pytest.approx(3.0)   # starts after the first corner


def test_circle_stays_a_circle_under_a_similarity(tmp_path):
    c = _read(tmp_path, '<g transform="translate(5,5) rotate(30) scale(2)"><circle cx="1" cy="0" r="3"/></g>',
              'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert c.kind == "circle" and c.radius == pytest.approx(6.0)
    cx, cy = c.nodes[0].x, c.nodes[0].y
    assert (cx, cy) == pytest.approx((5 + 2 * math.cos(math.radians(30)),
                                      5 + 2 * math.sin(math.radians(30))))


def test_circle_under_a_stretch_becomes_a_spline_ellipse(tmp_path):
    c = _read(tmp_path, '<circle cx="0" cy="0" r="5" transform="scale(2,1)"/>',
              'width="100mm" viewBox="-50 -50 100 100"').curves[0]
    assert c.kind == "spline" and c.closed and len(c.nodes) == 4
    assert _bbox(c) == pytest.approx((-10, -5, 10, 5), abs=3e-3)


def test_ellipse_element(tmp_path):
    c = _read(tmp_path, '<ellipse cx="0" cy="0" rx="8" ry="2"/>',
              'width="100mm" viewBox="-50 -50 100 100"').curves[0]
    assert c.kind == "spline" and c.closed
    assert _bbox(c) == pytest.approx((-8, -2, 8, 2), abs=3e-3)


def test_transforms_compose_outermost_first_through_groups(tmp_path):
    # inner translate applies first, then the outer scale: (1,1) → (2,2) → (4,4)... per SVG
    body = '<g transform="scale(2)"><g transform="translate(1,1)"><rect x="0" y="0" width="1" height="1"/></g></g>'
    c = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert _bbox(c) == pytest.approx((2, 2, 4, 4))


def test_matrix_rotate_about_a_point_and_skew(tmp_path):
    body = ('<rect x="0" y="0" width="10" height="2" transform="rotate(90 0 0)"/>'
            '<rect x="0" y="0" width="10" height="2" transform="matrix(1 0 0 1 100 0)"/>'
            '<rect x="0" y="0" width="10" height="10" transform="skewX(45)"/>')
    doc = _read(tmp_path, body, 'width="300mm" viewBox="0 0 300 300"')
    rot, mat, skew = doc.curves
    assert _bbox(rot) == pytest.approx((-2, 0, 0, 10), abs=1e-9)
    assert _bbox(mat) == pytest.approx((100, 0, 110, 2))
    assert _bbox(skew) == pytest.approx((0, 0, 20, 10), abs=1e-9)   # the top edge slides 10


def test_nested_svg_places_its_content_at_x_y(tmp_path):
    body = '<svg x="10" y="20" width="50" height="50"><rect x="0" y="0" width="1" height="1"/></svg>'
    c = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"').curves[0]
    assert _bbox(c) == pytest.approx((10, 20, 11, 21))


# ---------------------------------------------------------------------------
# What is skipped, what is reported
# ---------------------------------------------------------------------------

def test_defs_hidden_and_foreign_namespace_elements_are_skipped(tmp_path):
    body = ('<defs><rect x="0" y="0" width="1" height="1"/></defs>'
            '<g style="display:none"><rect x="0" y="0" width="1" height="1"/></g>'
            '<rect display="none" x="0" y="0" width="1" height="1"/>'
            '<inkscape:namedview id="nv"/>'
            '<rect x="5" y="5" width="1" height="1"/>')
    doc = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"')
    assert len(doc.curves) == 1 and doc.notes == []


def test_text_use_and_image_are_counted(tmp_path):
    body = ('<text x="0" y="0">Hi</text><use href="#a"/><use href="#b"/>'
            '<image href="x.png" width="1" height="1"/><rect x="0" y="0" width="1" height="1"/>')
    doc = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"')
    assert len(doc.curves) == 1
    note = next(n for n in doc.notes if n.startswith("Skipped"))
    assert "text×1 (convert text to paths" in note
    assert "use×2 (expand clones" in note and "image×1" in note


def test_empty_file_has_no_curves(tmp_path):
    doc = _read(tmp_path, "", 'width="100mm" viewBox="0 0 100 100"')
    assert doc.curves == [] and doc.bbox is None and doc.width_mm == 0.0


def test_not_svg_and_dtd_are_refused(tmp_path):
    p = tmp_path / "x.svg"
    p.write_text("<html/>", encoding="utf-8")
    with pytest.raises(ValueError, match="not <svg>"):
        read_svg(str(p), Layer.REF)
    p.write_text('<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    with pytest.raises(ValueError, match="DTD"):
        read_svg(str(p), Layer.REF)
    p.write_text("not xml at all", encoding="utf-8")
    with pytest.raises(ValueError, match="valid SVG"):
        read_svg(str(p), Layer.REF)


# ---------------------------------------------------------------------------
# Layer policy
# ---------------------------------------------------------------------------

def test_inkscape_layer_label_valid_here_is_kept(tmp_path):
    body = '<g inkscape:groupmode="layer" inkscape:label="LENS"><rect x="0" y="0" width="1" height="1"/></g>'
    doc = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"', layer=Layer.REF, ws="front")
    assert doc.curves[0].layer is Layer.LENS and doc.notes == []


def test_recognized_label_invalid_for_workspace_is_refiled_and_reported(tmp_path):
    body = '<g id="lens"><rect x="0" y="0" width="1" height="1"/></g>'
    doc = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"',
                layer=Layer.ENGRAVING, ws="temple_r")
    assert doc.curves[0].layer is Layer.ENGRAVING
    assert any("labeled LENS placed on ENGRAVING" in n for n in doc.notes)


def test_unlabeled_shapes_land_on_the_active_layer_quietly(tmp_path):
    body = '<g id="Layer_1"><path d="M 0 0 L 1 1"/></g>'
    doc = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"',
                layer=Layer.ENGRAVING, ws="temple_r")
    assert doc.curves[0].layer is Layer.ENGRAVING and doc.notes == []


def test_a_shapes_own_id_overrides_the_group_hint(tmp_path):
    body = '<g inkscape:label="LENS"><rect id="REF" x="0" y="0" width="1" height="1"/></g>'
    doc = _read(tmp_path, body, 'width="100mm" viewBox="0 0 100 100"')
    assert doc.curves[0].layer is Layer.REF


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def test_place_curves_scales_about_the_content_center_and_moves_it(tmp_path):
    doc = _read(tmp_path, '<rect x="100" y="200" width="40" height="20"/><circle cx="120" cy="210" r="5"/>',
                'width="400mm" viewBox="0 0 400 400"')
    placed = place_curves(doc.curves, scale=0.5, center=(-3.0, 7.0))
    bb = content_bbox(placed)
    assert bb == pytest.approx((-13, 2, 7, 12), abs=1e-9)        # 20 × 10 around (-3, 7)
    assert placed[1].kind == "circle" and placed[1].radius == pytest.approx(2.5)
    assert (placed[1].nodes[0].x, placed[1].nodes[0].y) == pytest.approx((-3, 7))
    # the originals are untouched
    assert doc.bbox == pytest.approx((100, 200, 140, 220))


def test_place_curves_identity_is_the_files_own_placement(tmp_path):
    doc = _read(tmp_path, '<rect x="10" y="10" width="5" height="5"/>',
                'width="100mm" viewBox="0 0 100 100"')
    placed = place_curves(doc.curves)
    assert content_bbox(placed) == pytest.approx(doc.bbox)
    assert placed[0] is not doc.curves[0]


def test_import_svg_is_read_plus_place(tmp_path):
    path = _write(tmp_path, '<rect x="0" y="0" width="10" height="10"/>',
                  'width="100mm" viewBox="0 0 100 100"')
    curves, notes = import_svg(path, Layer.REF, "front", scale=2.0, center=(0.0, 0.0))
    assert notes == [] and content_bbox(curves) == pytest.approx((-10, -10, 10, 10))


# ---------------------------------------------------------------------------
# The app: File ▸ Import ▸ SVG…
# ---------------------------------------------------------------------------

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


def _drive_import(win, tmp_path, monkeypatch, answer, ws_index=1):
    path = _write(tmp_path, '<path d="M 0 0 C 100 200 300 200 400 0 Z"/>',
                  'viewBox="0 0 500 600"', name="logo.svg")
    from framedraft import app as app_mod
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr(type(win), "_ask_svg_import", lambda self, doc, name: answer)
    win._activate_workspace(ws_index) if hasattr(win, "_activate_workspace") else None
    win._import_svg()
    QApplication.processEvents()
    return win._active_ws


def test_import_lands_selected_on_the_active_layer_at_the_chosen_size(win, tmp_path, monkeypatch):
    ws = win._active_ws
    ws.active_layer = Layer.REF
    before = len(ws.doc_curves)
    # 400 px wide → scale to 8 mm, centered on the view
    scale = 8.0 / (400 * _MM_PER_PX)
    ws = _drive_import(win, tmp_path, monkeypatch, (scale, True), ws_index=0)
    new = ws.doc_curves[before:]
    assert len(new) == 1 and new[0].layer is Layer.REF and new[0].closed
    bb = _bbox(new[0])
    assert bb[2] - bb[0] == pytest.approx(8.0, abs=1e-3)
    r = win._view_source_rect()
    assert (bb[0] + bb[2]) / 2 == pytest.approx(r.center().x(), abs=1e-6)
    assert [i.curve for i in win.scene.selectedItems() if hasattr(i, "curve")] == new
    assert "Imported 1 curve(s)" in win._status.currentMessage()


def test_canceling_the_size_dialog_imports_nothing(win, tmp_path, monkeypatch):
    ws = win._active_ws
    before = len(ws.doc_curves)
    _drive_import(win, tmp_path, monkeypatch, None, ws_index=0)
    assert len(win._active_ws.doc_curves) == before


def test_import_is_one_undo_step(win, tmp_path, monkeypatch):
    ws = win._active_ws
    before = len(ws.doc_curves)
    _drive_import(win, tmp_path, monkeypatch, (1.0, False), ws_index=0)
    assert len(win._active_ws.doc_curves) == before + 1
    win._undo()
    QApplication.processEvents()
    assert len(win._active_ws.doc_curves) == before
