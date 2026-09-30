"""v1.3.0 bug-hunt regressions — one test per fix that had a concrete
failure scenario, grouped by the area it lives in."""
import math
import zipfile

import ezdxf
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent, QGraphicsView

from framedraft.document import (DimLine, Layer, MIRRORED_LAYERS,
                                 TextObject)
from helpers import arc, circle, closed_diamond, line, spline


# ═══════════════════════════════════════════════════════════ geometry / tools


def test_t_nearest_is_refined_between_samples():
    """A trim/split point lands ON the cut, not on the nearest 1/64 sample
    (which left a 100 mm line 0.7 mm short of a cut at x = 50.7)."""
    from framedraft.geometry import point_at_t, t_nearest
    c = line([(0, 0), (100, 0)])
    t = t_nearest(c, 50.7, 3.0)
    assert abs(t - 0.507) < 1e-5
    d = closed_diamond(0, 0, 20)
    t = t_nearest(d, 30.0, 3.3)          # off-curve probe near the right tip
    x, y = point_at_t(d, t)
    # the nearest point is at most a hair from the true foot on the curve
    best = min(math.hypot(px - 30.0, py - 3.3)
               for px, py in (point_at_t(d, i / 4000) for i in range(4001)))
    assert math.hypot(x - 30.0, y - 3.3) <= best + 1e-4


def test_intersection_params_are_refined():
    from framedraft.geometry import intersect_curve_params, point_at_t
    a = line([(0, 0), (100, 0)])
    b = line([(50.7, -10), (50.7, 10)])
    [t] = intersect_curve_params(a, b)
    x, _y = point_at_t(a, t)
    assert abs(x - 50.7) < 1e-4


def test_split_closed_spline_opens_it_in_one_piece():
    from framedraft.geometry import point_at_t, split_curve_at_t
    d = closed_diamond(0, 0, 20)
    opened, other = split_curve_at_t(d, 0.3)
    assert other is None and opened is not d
    assert opened.closed is False
    sx, sy = point_at_t(opened, 0.0)
    ex, ey = point_at_t(opened, 1.0)
    px, py = point_at_t(d, 0.3)
    assert math.hypot(sx - px, sy - py) < 1e-6 and math.hypot(ex - px, ey - py) < 1e-6
    # circles keep the two-arc result
    left, right = split_curve_at_t(circle(0, 0, 10), 0.3)
    assert right is not None and left.kind == "arc"


def test_extracted_piece_has_no_outside_handles():
    from framedraft.geometry import extract_open_segment
    piece = extract_open_segment(closed_diamond(0, 0, 20), 0.1, 0.6)
    assert piece.nodes[0].cp_in is None and piece.nodes[-1].cp_out is None


def test_cubic_tangent_retracted_handle_uses_next_control_point():
    from framedraft.geometry import _cubic_tangent
    p0, p1, p2, p3 = (0.0, 0.0), (0.0, 0.0), (10.0, 10.0), (20.0, 0.0)
    tx, ty = _cubic_tangent(p0, p1, p2, p3, 0.0)
    assert abs(tx - ty) < 1e-9          # towards p2 (45°), not the chord (0°)
    tx, ty = _cubic_tangent(p0, (5.0, 10.0), p3, p3, 1.0)
    assert ty < 0                        # towards p3 − p1, not the chord


def test_offset_circle_drops_group_id():
    from framedraft.geometry import offset_curve
    c = circle(0, 0, 5)
    c.group_id = "abcd"
    assert offset_curve(c, 1.0).group_id is None


def test_offset_tool_refuses_inward_past_the_radius():
    from framedraft.tools.offset import OffsetTool
    tool = OffsetTool(None)
    seen = []
    tool.status_message.connect(seen.append)
    tool.offset_applied.connect(lambda *a: seen.append("APPLIED"))
    tool._source_curve = arc(0, 0, 5, 0, 90)
    tool._input_str = "-8"
    tool._apply_offset()
    assert "APPLIED" not in seen and any("radius" in s for s in seen)


def test_draw_double_click_keeps_the_node_under_it():
    from framedraft.tools.draw import DrawTool
    tool = DrawTool(None)
    got = []
    tool.curve_added.connect(got.append)
    tool.activate("line", Layer.REF, QGraphicsScene(), None)
    tool.handle_press(QPointF(0, 0), use_snap=False)
    tool.handle_press(QPointF(10, 0), use_snap=False)    # the double-click's own press
    tool.handle_dbl_click(QPointF(10, 0), use_snap=False)
    [c] = got
    assert [(n.x, n.y) for n in c.nodes] == [(0, 0), (10, 0)]


def test_draw_escape_emits_canceled():
    from framedraft.tools.draw import DrawTool
    tool = DrawTool(None)
    seen = []
    tool.canceled.connect(lambda: seen.append("c"))
    tool.activate("line", Layer.REF, QGraphicsScene(), None)
    tool.handle_key(Qt.Key.Key_Escape)
    assert seen == ["c"] and not tool.active


def test_circle_escape_before_center_cancels():
    from framedraft.tools.circle import CircleTool
    tool = CircleTool(None)
    seen = []
    tool.canceled.connect(lambda: seen.append("c"))
    tool.activate("circle", Layer.LENS, QGraphicsScene(), None)
    assert tool.active
    assert tool.handle_key(Qt.Key.Key_Escape)
    assert seen == ["c"] and not tool.active


def test_dim_rejects_a_coincident_second_point():
    from framedraft.tools.dim import DimTool
    tool = DimTool(None)
    got, msgs = [], []
    tool.dim_added.connect(got.append)
    tool.status_message.connect(msgs.append)
    tool.activate(QGraphicsScene(), None)
    tool.handle_press(QPointF(5, 5), use_snap=False)
    tool.handle_press(QPointF(5, 5), use_snap=False)
    assert got == [] and any("same" in m for m in msgs)
    tool.handle_press(QPointF(15, 5), use_snap=False)
    assert len(got) == 1


# ═══════════════════════════════════════════════════════════════════ canvas


def _press(x, y):
    ev = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    ev.setButton(Qt.MouseButton.LeftButton)
    ev.setScenePos(QPointF(x, y))
    return ev


def _move(x, y):
    ev = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseMove)
    ev.setScenePos(QPointF(x, y))
    return ev


def test_node_click_without_motion_takes_no_undo_snapshot():
    from framedraft.canvas.items import NodeDot
    c = spline([(0, 0), (10, 5), (20, 0)])
    starts = []
    dot = NodeDot(c, 1, lambda _c: None, on_drag_start=lambda: starts.append(1))
    scene = QGraphicsScene()          # keep it alive: it owns the dot
    scene.addItem(dot)
    dot.mousePressEvent(_press(10, 5))
    assert starts == []                       # a click only selects
    dot.mouseMoveEvent(_move(12, 5))
    assert starts == [1]                      # the first real movement
    dot.mouseMoveEvent(_move(14, 5))
    assert starts == [1]


def test_drill_holes_ghost_like_they_export():
    from framedraft.canvas.scene import FrameScene, _GHOST_LAYERS
    from framedraft.export.dxf import _MIRROR_LAYERS
    from framedraft.tools.draw import _MIRROR_GHOST_LAYERS
    assert Layer.DRILL in _GHOST_LAYERS and Layer.DRILL in _MIRROR_GHOST_LAYERS
    assert _MIRROR_LAYERS == MIRRORED_LAYERS
    sc = FrameScene()
    sc.init_mirror()
    hole = circle(20, 0, 1.5, layer=Layer.DRILL)
    sc.add_curve(hole)
    assert id(hole) in sc._ghost_items


def test_text_on_locked_layer_is_not_editable():
    from framedraft.canvas.scene import FrameScene
    sc = FrameScene()
    edits = []
    sc.set_text_edit_callback(edits.append)
    t = TextObject(text="X", family="Arial", size_mm=4.0)
    item = sc.add_text(t)
    sc.set_layer_locked(Layer.ENGRAVING, True)
    ev = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    item.mouseDoubleClickEvent(ev)
    assert edits == []
    sc.set_layer_locked(Layer.ENGRAVING, False)
    item.mouseDoubleClickEvent(ev)
    assert edits == [t]


def test_text_item_is_not_qt_movable():
    """Text rides the view's drag path (with curves and dims), not Qt's."""
    from framedraft.canvas.scene import FrameScene
    sc = FrameScene()
    item = sc.add_text(TextObject(text="X", family="Arial", size_mm=4.0))
    assert not (item.flags() & item.GraphicsItemFlag.ItemIsMovable)


def test_mirror_snap_does_not_steal_an_endpoint_on_the_axis():
    from framedraft.canvas.scene import FrameScene
    from framedraft.canvas.snapping import SnapEngine
    sc = FrameScene()
    view = QGraphicsView(sc)
    eng = SnapEngine(sc)
    eng.set_doc_curves([line([(0, 10), (30, 12)])])
    eng.set_mirror(0.0, True)
    p = eng.snap(QPointF(0.5, 11.2), [], view)
    assert (p.x(), p.y()) == (0.0, 10.0)      # the endpoint, not (0, 11.2)
    p = eng.snap(QPointF(0.5, 40.0), [], view)
    assert (p.x(), p.y()) == (0.0, 40.0)      # projection still works alone


def test_px_dist_keeps_sub_pixel_precision():
    from framedraft.canvas.snapping import px_dist
    view = QGraphicsView(QGraphicsScene())
    assert abs(px_dist(view, QPointF(0, 0), QPointF(1.2, 0)) - 1.2) < 1e-9


def test_angle_in_arc_treats_equal_angles_as_full_circle():
    from framedraft.canvas.snapping import _angle_in_arc
    assert _angle_in_arc(90.0, 30.0, 30.0)


def test_hiding_outline_pauses_the_fill_instead_of_switching_it_off():
    from framedraft.canvas.scene import FrameScene
    sc = FrameScene()
    sc.init_mirror()
    for c in (closed_diamond(0, 0, 40, layer=Layer.OUTLINE), circle(-15, 0, 8),
              circle(15, 0, 8)):
        sc.add_curve(c)
    disabled = []
    sc.fill_auto_disabled = disabled.append
    assert sc.set_fill_visible(True) == "ok"
    sc.set_layer_visible(Layer.OUTLINE, False)
    assert sc.fill_state()["visible"] is True and disabled == []
    assert not sc._fill_item.isVisible()
    sc.set_layer_visible(Layer.OUTLINE, True)
    assert sc._fill_item.isVisible()


def test_face_added_after_calibration_takes_that_scale(tmp_path):
    from PySide6.QtGui import QImage
    from framedraft.canvas.scene import FrameScene
    img = tmp_path / "f.png"
    QImage(400, 300, QImage.Format.Format_RGB32).save(str(img))
    sc = FrameScene()
    sc.add_face(str(img))
    sc.set_face_calibration(4.0)              # 4 px per mm → 0.25 scale
    sc.add_face(str(img))
    assert abs(sc.get_face_item(1).scale() - 0.25) < 1e-9
    sc.clear_faces()
    assert sc.sceneRect().width() == 300      # default extents restored


def test_theme_overrides_of_the_wrong_shape_are_ignored():
    from framedraft import theme
    theme.set_overrides({"light": "#fff", "dark": None})
    theme.set_overrides({})


def test_select_items_emits_once():
    from framedraft.canvas.scene import FrameScene
    sc = FrameScene()
    items = [sc.add_curve(line([(0, i), (10, i)])) for i in range(20)]
    n = []
    sc.selectionChanged.connect(lambda: n.append(1))
    sc.select_items(items)
    assert len(n) == 1 and len(sc.selectedItems()) == 20


# ═══════════════════════════════════════════════════════════════════ export


def _dxf(tmp_path, build):
    doc = ezdxf.new("R2000")
    build(doc.modelspace(), doc)
    p = tmp_path / "in.dxf"
    doc.saveas(str(p))
    return str(p)


def test_periodic_closed_spline_imports_instead_of_aborting(tmp_path):
    from ezdxf.math import closed_uniform_bspline
    from framedraft.export.dxf_import import import_dxf

    def build(msp, _doc):
        sp = msp.add_spline()
        sp.apply_construction_tool(
            closed_uniform_bspline([(0, 0), (10, 0), (10, 10), (0, 10)], order=4))
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.OUTLINE)
    [c] = curves
    assert c.kind == "spline" and c.closed


def test_mirrored_ocs_entities_land_where_the_cad_file_shows_them(tmp_path):
    from framedraft.export.dxf_import import import_dxf

    def build(msp, _doc):
        msp.add_circle((10, 5), 2, dxfattribs={"extrusion": (0, 0, -1)})
    [c] = import_dxf(_dxf(tmp_path, build), Layer.OUTLINE)[0]
    # OCS (10, 5) with extrusion −Z is WCS (−10, 5); scene negates Y
    assert abs(c.nodes[0].x - (-10)) < 1e-9 and abs(c.nodes[0].y - (-5)) < 1e-9


def test_block_references_are_expanded(tmp_path):
    from framedraft.export.dxf_import import import_dxf

    def build(msp, doc):
        blk = doc.blocks.new("HINGE")
        blk.add_line((0, 0), (10, 0))
        blk.add_circle((5, 5), 2)
        msp.add_blockref("HINGE", (100, 50), dxfattribs={"xscale": 2, "yscale": 2})
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.HINGE)
    kinds = sorted(c.kind for c in curves)
    assert kinds == ["circle", "line"]
    circ = next(c for c in curves if c.kind == "circle")
    assert abs(circ.radius - 4.0) < 1e-9 and abs(circ.nodes[0].x - 110) < 1e-9
    assert not any("INSERT" in n for n in notes)


def test_3d_polyline_is_reported_not_swallowed(tmp_path):
    from framedraft.export.dxf_import import import_dxf

    def build(msp, _doc):
        msp.add_polyline3d([(0, 0, 0), (10, 0, 1), (10, 10, 2)])
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.OUTLINE)
    assert curves == [] and any("POLYLINE" in n for n in notes)


def test_prefs_load_hands_out_copies(tmp_path, monkeypatch):
    import framedraft.prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    p = prefs_mod.load()
    p["catalog_pdf"]["include_fill"] = True
    p["recent_files"].append("x")
    assert prefs_mod.DEFAULTS["catalog_pdf"]["include_fill"] is False
    assert prefs_mod.DEFAULTS["recent_files"] == []
    prefs_mod.save(p)
    q = prefs_mod.load()
    q["catalog_pdf"]["front_layers"].append("REF")
    assert "REF" not in prefs_mod.DEFAULTS["catalog_pdf"]["front_layers"]


def test_gdraw_refuses_an_oversized_member_before_inflating_it(tmp_path):
    from framedraft.export import svg as svg_mod
    from framedraft.export.gdraw import load_gdraw
    big = tmp_path / "bomb.gdraw"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", '{"version": 1, "active_tab": "front"}')
        zf.writestr("front.svg", b"0" * (svg_mod._MAX_SVG_BYTES + 1024))
    assert big.stat().st_size < 1024 * 1024
    res = load_gdraw(str(big))
    assert res["errors"] and "Refusing" in res["errors"][0]
    assert res["front"]["curves"] == []


def test_gdraw_never_persists_a_member_name_without_bytes(tmp_path):
    from framedraft.document import FaceImage
    from framedraft.export.gdraw import _embed_face_images, _embed_fill_image
    with zipfile.ZipFile(tmp_path / "t.gdraw", "w") as zf:
        [fi] = _embed_face_images(zf, "front", [FaceImage(path="images/front_0_p.png")])
        fill = _embed_fill_image(zf, "front", {"image": "images/front_fill_s.jpg"})
        assert zf.namelist() == []
    assert fi.path == "front_0_p.png" and fill["image"] == "front_fill_s.jpg"


def test_oma_request_record_without_data_is_tolerated():
    from framedraft.export.oma import parse_oma
    job = parse_oma("REQ=FIL\r\nTRCFMT=1;?;E;R;F\r\nTRCFMT=1;4;E;L;F\r\n"
                    "R=2000;2000;2000;2000\r\n")
    assert set(job.traces) == {"L"}


def test_catalog_bbox_is_the_drawn_extent():
    from framedraft.export.catalog_pdf import _content_bbox
    d = closed_diamond(0, 0, 20)
    for n in d.nodes:                      # exaggerate the handles
        if n.cp_out:
            n.cp_out.x *= 3; n.cp_out.y *= 3
        if n.cp_in:
            n.cp_in.x *= 3; n.cp_in.y *= 3
    x0, y0, x1, y1 = _content_bbox([d])
    ctrl = max(abs(cp.x) for n in d.nodes for cp in (n.cp_in, n.cp_out) if cp)
    assert 40 <= x1 - x0 < 2 * ctrl - 1e-6     # inside the control polygon
    assert 40 <= y1 - y0 < 2 * ctrl - 1e-6


def test_template_page_clips_an_oversized_piece_at_the_margin():
    from PySide6.QtGui import QColor, QImage, QPainter
    from framedraft.export.template_print import (
        MARGIN_MM, RULER_STRIP_MM, component_sizes, layout_pages,
        paint_template_page, printable_area)
    comps = {"front": {"curves": [closed_diamond(0, 0, 200)], "texts": []}}
    sizes = component_sizes(comps)
    pw, ph = 215.9, 279.4
    pages = layout_pages(sizes, *printable_area(pw, ph))
    ppm = 100 / 25.4
    img = QImage(round(pw * ppm), round(ph * ppm), QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    paint_template_page(p, ppm, pw, ph, pages[0], comps,
                        {"line_weight_mm": 0.35, "labels": False}, "")
    p.end()
    strip_top = round((ph - MARGIN_MM - RULER_STRIP_MM) * ppm)
    # The ruler rows of the strip, to the right of the 100 mm ruler, hold no
    # ink: the piece is cut off at the printable area above the strip.
    y0 = strip_top + round(4.5 * ppm)
    y1 = strip_top + round(8.4 * ppm)
    x0 = round((MARGIN_MM + 100 + 8) * ppm)
    stray = [(x, y) for y in range(y0, y1, 2) for x in range(x0, img.width(), 2)
             if img.pixelColor(x, y) != QColor("#ffffff")]
    assert stray == []
    # …whereas without the clip the piece would reach the page edge: it is
    # 200 mm tall on a 245 mm printable height, so it does reach the strip.
    assert sizes[0][3] + 5 > printable_area(pw, ph)[1]


def test_template_pdf_has_the_requested_page_size(tmp_path):
    import re
    from framedraft.export.template_print import export_template_pdf
    comps = {"front": {"curves": [closed_diamond(0, 0, 20)], "texts": []}}
    out = tmp_path / "a4.pdf"
    export_template_pdf(str(out), comps, {"paper": "a4", "orientation": "portrait",
                                           "line_weight_mm": 0.35, "labels": True})
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", out.read_bytes())
    w, h = float(m.group(1)) / 72 * 25.4, float(m.group(2)) / 72 * 25.4
    assert abs(w - 210) < 1 and abs(h - 297) < 1


def test_dxf_contract_spline_is_the_exact_bezier(tmp_path):
    """The export contract, asserted on the written file rather than through
    a round trip that shares ezdxf on both sides: degree-3 SPLINE entities
    whose control points ARE the Bézier polygon (Y negated), a closed
    contour flagged closed with its wrap segment back to node 0, and
    $INSUNITS = 4 (mm)."""
    from framedraft.export.dxf import export_dxf
    d = closed_diamond(0, 0, 20)
    out = tmp_path / "c.dxf"
    export_dxf(curves=[d], path=str(out), mirror_on=False)
    doc = ezdxf.readfile(str(out))
    assert doc.header["$INSUNITS"] == 4
    [sp] = list(doc.modelspace())
    assert sp.dxftype() == "SPLINE" and sp.dxf.degree == 3
    assert sp.dxf.flags & 1                          # closed
    cps = [(round(float(p[0]), 6), round(float(p[1]), 6)) for p in sp.control_points]
    n = d.nodes
    # first segment: node0, node0.cp_out, node1.cp_in, node1 — with Y negated
    expect = [(n[0].x, -n[0].y), (n[0].cp_out.x, -n[0].cp_out.y),
              (n[1].cp_in.x, -n[1].cp_in.y), (n[1].x, -n[1].y)]
    assert cps[:4] == [(round(x, 6), round(y, 6)) for x, y in expect]
    # the wrap segment ends back at node 0
    assert cps[-1] == (round(n[0].x, 6), round(-n[0].y, 6))


# ═══════════════════════════════════════════════════════════════════════ app


@pytest.fixture()
def win(tmp_path, monkeypatch):
    import framedraft.prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    monkeypatch.setattr(MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    w = MainWindow()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()


def test_deleting_one_of_two_identical_curves_keeps_document_and_scene_in_step(win):
    ws = win._workspaces[0]
    a = ws.add_curve(circle(0, 0, 3, layer=Layer.DRILL))
    b = ws.add_curve(circle(0, 0, 3, layer=Layer.DRILL))
    win.scene.clearSelection()
    b.setSelected(True)
    win._delete_selected()
    assert ws.doc_curves == [a.curve] and ws.doc_curves[0] is a.curve
    assert id(a.curve) in ws.scene._curve_items
    assert id(b.curve) not in ws.scene._curve_items


def test_select_all_does_not_run_the_validator_per_item(win, monkeypatch):
    import framedraft.app as app_mod
    ws = win._workspaces[0]
    for i in range(40):
        ws.add_curve(line([(0, i), (10, i)]))
    calls = []
    real = app_mod.readiness_state
    monkeypatch.setattr(app_mod, "readiness_state",
                        lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    win._select_all()
    assert len(win.scene.selectedItems()) == 40
    assert len(calls) == 0


def test_measurements_use_drawn_extents(win):
    from framedraft.app import _curves_bbox
    d = closed_diamond(0, 0, 20)
    for n in d.nodes:
        if n.cp_out:
            n.cp_out.x *= 3; n.cp_out.y *= 3
        if n.cp_in:
            n.cp_in.x *= 3; n.cp_in.y *= 3
    x0, _y0, x1, _y1 = _curves_bbox([d])
    ctrl = max(abs(cp.x) for n in d.nodes for cp in (n.cp_in, n.cp_out) if cp)
    assert 40 <= x1 - x0 < 2 * ctrl - 1e-6


def test_explode_leaves_circles_and_arcs_whole(win):
    ws = win._workspaces[0]
    c = ws.add_curve(circle(0, 0, 5))
    win.scene.clearSelection()
    c.setSelected(True)
    win._explode_selected()
    assert ws.doc_curves == [c.curve]
    assert "no segments" in win._status.currentMessage()


def test_tab_switch_refreshes_the_undo_menu(win):
    front = win._workspaces[0]
    front.push_undo_snapshot()
    win._update_undo_actions()
    assert win._act_undo.isEnabled()
    win._ws_tab_widget.setCurrentIndex(1)
    assert not win._act_undo.isEnabled()      # Temple R has no history


def test_temple_copy_refuses_an_empty_source(win, monkeypatch):
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: pytest.fail("asked")))
    win._ws_tab_widget.setCurrentIndex(2)
    win._copy_temple_to_other()
    assert "empty" in win._status.currentMessage()


def test_temple_copy_keeps_groups_and_dim_side(win, monkeypatch):
    import framedraft.app as app_mod
    monkeypatch.setattr(
        app_mod.QMessageBox, "question",
        staticmethod(lambda *a, **k: app_mod.QMessageBox.StandardButton.Yes))
    win._ws_tab_widget.setCurrentIndex(1)
    ws = win._active_ws
    a = line([(0, 0), (10, 0)], layer=Layer.HINGE)
    b = line([(0, 5), (10, 5)], layer=Layer.HINGE)
    a.group_id = b.group_id = "grp1"
    ws.add_curve(a); ws.add_curve(b)
    ws.add_dim(DimLine(0, 0, 10, 0, offset=3.0))
    win._copy_temple_to_other()
    tgt = win._active_ws
    gids = {c.group_id for c in tgt.doc_curves}
    assert len(gids) == 1 and None not in gids and "grp1" not in gids
    assert tgt.doc_dims[0].offset == -3.0


def test_point_move_accepts_a_text_only_selection(win):
    win._ws_tab_widget.setCurrentIndex(1)
    ws = win._active_ws
    t = TextObject(text="R", family="Arial", size_mm=4.0, anchor_x=10, anchor_y=5)
    item = ws.add_text(t)
    win.scene.clearSelection()
    item.setSelected(True)
    win._set_tool_point_move()
    assert win._point_move_tool.active
    win._on_point_moved(2.0, 1.0)
    assert (t.anchor_x, t.anchor_y) == (12.0, 6.0)


def test_line_tool_escape_restores_select_mode(win):
    ws = win._workspaces[0]
    it = ws.add_curve(line([(0, 0), (10, 0)]))
    win._set_tool_line()
    assert not (it.flags() & it.GraphicsItemFlag.ItemIsSelectable)
    win.view._draw_tool.handle_key(Qt.Key.Key_Escape)
    assert win.view._draw_tool is None
    assert it.flags() & it.GraphicsItemFlag.ItemIsSelectable
    assert win._act_select.isChecked()


def test_text_rows_can_be_moved_between_layers_but_locked_rows_cannot(win):
    win._ws_tab_widget.setCurrentIndex(1)
    ws = win._active_ws
    t = ws.add_text(TextObject(text="R", family="Arial", size_mm=4.0))
    win._move_curve_items_to_layer([t], Layer.REF)
    assert t.text_obj.layer is Layer.REF
    ws.scene.set_layer_locked(Layer.REF, True)
    win._move_curve_items_to_layer([t], Layer.ENGRAVING)
    assert t.text_obj.layer is Layer.REF
    assert "locked" in win._status.currentMessage()


def test_opening_an_svg_clears_the_other_workspaces(win, tmp_path):
    win._workspaces[1].add_curve(line([(0, 0), (140, 0)], layer=Layer.OUTLINE))
    svg = tmp_path / "front.svg"
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    win._do_save_svg(str(svg))
    win._dirty = False
    win._open_svg(str(svg))
    assert win._workspaces[1].doc_curves == []
    assert len(win._workspaces[0].doc_curves) == 1


def test_svg_document_save_writes_the_front_from_any_tab(win, tmp_path, monkeypatch):
    from framedraft.export.svg import load_svg
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    win._workspaces[1].add_curve(line([(0, 0), (140, 0)], layer=Layer.OUTLINE))
    win._ws_tab_widget.setCurrentIndex(1)
    # Temple R has work a .svg cannot hold: the save asks first (the UI
    # review, 2026-09-29); "Save Front Only" writes the front as before.
    monkeypatch.setattr(win, "_ask_svg_scope", lambda *_a: "front")
    p = tmp_path / "doc.svg"
    win._do_save(str(p))
    [c] = load_svg(str(p))["curves"]
    assert c.kind == "spline" and c.closed          # the front's diamond


def test_save_as_appends_the_project_suffix(win, tmp_path, monkeypatch):
    import framedraft.app as app_mod
    bare = tmp_path / "myframe"
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(bare), "GuildDraw Project (*.gdraw)")))
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    win._save_as()
    assert (tmp_path / "myframe.gdraw").exists()
    assert zipfile.is_zipfile(tmp_path / "myframe.gdraw")
    assert win._current_path.endswith(".gdraw")


def test_ensure_suffix():
    from framedraft.app import MainWindow
    assert MainWindow._ensure_suffix("a", ".dxf") == "a.dxf"
    assert MainWindow._ensure_suffix("a.DXF", ".dxf") == "a.DXF"


def test_loading_a_file_resets_session_locks(win, tmp_path):
    ws = win._workspaces[0]
    ws.add_curve(closed_diamond(0, 0, 20, layer=Layer.LENS))
    p = tmp_path / "a.gdraw"
    win._do_save(str(p))
    ws.boxing_snapped = True
    ws.shape_locked = True
    ws.bevel_preset, ws.bevel_depth = "custom", 2.5
    win._dirty = False
    win._open_gdraw(str(p))
    assert ws.shape_locked is False and ws.boxing_snapped is False
    assert ws.bevel_preset == "acetate"


def test_open_gdraw_reports_status_and_drops_path_on_errors(win, tmp_path):
    bad = tmp_path / "bad.gdraw"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("manifest.json", '{"version": 1, "active_tab": "front"}')
        zf.writestr("front.svg", "<not svg")
    import framedraft.app as app_mod
    app_mod.QMessageBox.warning = staticmethod(lambda *a, **k: None)
    assert win._open_gdraw(str(bad)) == "errors"
    assert win._current_path is None
    good = tmp_path / "good.gdraw"
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    win._do_save(str(good))
    win._dirty = False
    assert win._open_gdraw(str(good)) == "ok"


def test_hotkey_conflict_with_a_reserved_shortcut_is_flagged():
    from framedraft.app import SettingsDialog
    from framedraft.prefs import DEFAULTS
    dlg = SettingsDialog(dict(DEFAULTS), None)
    assert dlg._ok_btn.isEnabled()
    dlg._key_edits[0].setText("Ctrl+Z")
    dlg._check_conflicts()
    assert not dlg._ok_btn.isEnabled()
    assert "reserved" in dlg._conflict_label.text()


def test_drill_datum_is_the_od_lens(win):
    front = win._workspaces[0]
    front.add_curve(circle(25, 0, 10, layer=Layer.LENS))     # OS, drawn first
    front.add_curve(circle(-25, 0, 10, layer=Layer.LENS))    # OD
    cx, _cy = win._lens_boxing_center()
    assert cx < 0


def test_settings_apply_leaves_the_selected_curve_weight_alone(win):
    ws = win._workspaces[0]
    it = ws.add_curve(line([(0, 0), (10, 0)]))
    it.curve.line_weight = 1.5
    win.scene.clearSelection()
    it.setSelected(True)
    from framedraft.app import SettingsDialog
    dlg = SettingsDialog(dict(win._prefs), None)
    dlg._weight_spin.setValue(3.25)
    depth = len(ws.undo_stack)
    win._apply_settings(dlg.to_prefs())
    assert it.curve.line_weight == 1.5
    assert len(ws.undo_stack) == depth
