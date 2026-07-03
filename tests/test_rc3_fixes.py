"""RC3 audit regressions.

Covers the correctness fixes from the pre-RC3 audit:
  * split-at-node on a closed curve must yield independent endpoint nodes
    (deepcopy of the rotated list memoized the seam node into ONE shared
    object — dragging one endpoint silently moved the other);
  * OMA export traces the FINISHED (beveled) lens and its box records come
    from the same sampled/buffered geometry as the boxing panel;
  * one split click = one undo step, even for an intersection split;
  * Mirror-Close preserves hand-tuned Bézier handles;
  * File > New resets calibration and boxing snap/lock state;
  * bookmarks round-trip their dims and texts through save/load;
  * arc parameterisation helpers tolerate None angles and treat a zero
    sweep as a full circle (same rule as build_path);
  * hidden layers are not trim/split cutting edges.
"""
import math

import pytest

from framedraft.document import (
    Calibration, ControlPoint, Curve, DimLine, FormingMetadata, Layer,
    MachinedBridge, MirrorAxis, SplineNode, TextObject,
)
from framedraft.boxing import (
    bevel_outline_points, finished_box, finished_geometry,
)
from framedraft.export.oma import curve_to_trace, points_to_trace
from framedraft.geometry import (
    extract_open_segment, point_at_t, sample_curve,
)

from helpers import circle, closed_diamond, line, spline


# ---------------------------------------------------------------------------
# Qt-free: finished-lens OMA tracing
# ---------------------------------------------------------------------------

def test_finished_geometry_matches_split_helpers():
    c = circle(0, 0, 10)
    assert finished_geometry(c, 1.5) == (finished_box(c, 1.5),
                                         bevel_outline_points(c, 1.5))
    bb, outline = finished_geometry(c, 0.0)
    assert bb == finished_box(c, 0.0)
    assert outline is None          # no bevel — trace the bare shape


def test_points_to_trace_matches_curve_to_trace():
    from framedraft.export.oma import _SAMPLES_PER_SEG
    c = closed_diamond(r=20.0)
    samples = [(x, y) for x, y, _t in sample_curve(c, _SAMPLES_PER_SEG)]
    assert points_to_trace(samples, n=90) == pytest.approx(
        curve_to_trace(c, n=90))


def test_finished_trace_radii_grow_by_bevel_depth():
    c = circle(0, 0, 20.0)
    _bb, outline = finished_geometry(c, 1.0)
    radii = points_to_trace(outline, n=90)
    assert min(radii) == pytest.approx(21.0, abs=0.05)
    assert max(radii) == pytest.approx(21.0, abs=0.05)


def test_finished_box_is_sampled_not_control_point_bbox():
    # Nodes offset so the true extremes fall BETWEEN nodes: the control-point
    # bbox overestimates the box while the sampled basis stays true.
    pts = [(25 * math.cos(2 * math.pi * (i + 0.5) / 12),
            15 * math.sin(2 * math.pi * (i + 0.5) / 12)) for i in range(12)]
    c = spline(pts, closed=True, layer=Layer.LENS)
    bb, _ = finished_geometry(c, 0.0)
    cp_xs = [p.x for n in c.nodes for p in (n, n.cp_in, n.cp_out)]
    assert (bb[2] - bb[0]) < (max(cp_xs) - min(cp_xs)) - 0.2


# ---------------------------------------------------------------------------
# Qt-free: arc parameterisation guards
# ---------------------------------------------------------------------------

def test_sample_curve_arc_with_none_angles_does_not_crash():
    a = Curve(kind="arc", layer=Layer.REF, nodes=[SplineNode(0, 0)],
              radius=5.0)   # start/end angles left as None
    pts = sample_curve(a)
    assert len(pts) > 2


def test_zero_sweep_arc_is_a_full_circle():
    # build_path draws start==end as a full circle; point_at_t / sample_curve /
    # extract_open_segment must agree.
    a = Curve(kind="arc", layer=Layer.REF, nodes=[SplineNode(0, 0)],
              radius=5.0, start_angle=90.0, end_angle=90.0)
    x, y = point_at_t(a, 0.5)          # half-way round: 90 + 180 = 270 deg
    assert (x, y) == pytest.approx((0.0, -5.0), abs=1e-9)
    sub = extract_open_segment(a, 0.0, 0.25)
    assert (sub.end_angle - sub.start_angle) % 360 == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Qt-free-ish: hidden layers are not cutting edges
# ---------------------------------------------------------------------------

def test_visible_curves_filter_drops_hidden_layers():
    from framedraft.tools.trim import _visible_curves

    class _Scene:
        def is_layer_visible(self, layer):
            return layer is not Layer.REF

    visible = line([(0, 0), (1, 1)], layer=Layer.OUTLINE)
    hidden  = line([(0, 1), (1, 0)], layer=Layer.REF)
    assert _visible_curves(_Scene(), [visible, hidden]) == [visible]


# ---------------------------------------------------------------------------
# SVG round trip: bookmarks keep their dims and texts
# ---------------------------------------------------------------------------

def test_bookmark_dims_and_texts_round_trip(tmp_path):
    from framedraft.export.svg import load_svg, save_svg

    bm = {
        "name": "rev1", "timestamp": "12:00:00",
        "snapshot": {
            "curves": [closed_diamond()],
            "dims":   [DimLine(x0=0, y0=0, x1=10, y1=0, offset=2.5)],
            "texts":  [TextObject(text="GASM", family="Arial", size_mm=4.0,
                                  rotation=15.0, anchor_x=1.0, anchor_y=2.0)],
        },
    }
    path = str(tmp_path / "bm.svg")
    save_svg(curves=[closed_diamond()], path=path,
             calibration=Calibration(), mirror=MirrorAxis(),
             forming=FormingMetadata(), machined_bridge=MachinedBridge(),
             bookmarks=[bm])

    snap = load_svg(path)["bookmarks"][0]["snapshot"]
    assert len(snap["curves"]) == 1
    d = snap["dims"][0]
    assert (d.x0, d.y0, d.x1, d.y1, d.offset) == (0, 0, 10, 0, 2.5)
    t = snap["texts"][0]
    assert (t.text, t.size_mm, t.rotation) == ("GASM", 4.0, 15.0)
    assert (t.anchor_x, t.anchor_y) == (1.0, 2.0)


# ---------------------------------------------------------------------------
# App-level regressions (one shared MainWindow — construction is slow)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def win():
    from framedraft.app import MainWindow
    w = MainWindow()
    yield w
    w._dirty = False


@pytest.fixture()
def fresh(win):
    """A clean document on the Frame Front tab before each app-level test."""
    win._dirty = False
    win._new()
    win._ws_tab_widget.setCurrentIndex(0)
    return win


def test_split_at_node_closed_curve_endpoints_independent(fresh):
    win = fresh
    ws = win._active_ws
    item = ws.add_curve(closed_diamond())
    item.setSelected(True)

    dot = next(d for d in win._edit_tool._dots if d.node_index == 2)
    win._edit_tool._on_node_clicked(dot)
    win._split_at_node()

    (result,) = ws.doc_curves
    assert not result.closed
    assert len(result.nodes) == 5           # 4 nodes + duplicated seam
    first, last = result.nodes[0], result.nodes[-1]
    assert first is not last                # the actual regression
    first.x += 5.0
    assert last.x == pytest.approx(first.x - 5.0)


def test_intersection_split_is_one_undo_step(fresh):
    win = fresh
    ws = win._active_ws
    c1 = ws.add_curve(line([(-10, 0), (10, 0)])).curve
    c2 = ws.add_curve(line([(0, -10), (0, 10)])).curve

    pairs = [
        (c1, [line([(-10, 0), (0, 0)]), line([(0, 0), (10, 0)])]),
        (c2, [line([(0, -10), (0, 0)]), line([(0, 0), (0, 10)])]),
    ]
    depth = len(ws.undo_stack)
    win._on_split_applied(pairs)

    assert len(ws.undo_stack) == depth + 1  # one click, one undo step
    assert c1 not in ws.doc_curves and c2 not in ws.doc_curves
    assert len(ws.doc_curves) == 4


def test_mirror_close_preserves_hand_tuned_handles(fresh):
    win = fresh
    ws = win._active_ws
    c = spline([(0, -10), (15, 0), (0, 10)], closed=False, layer=Layer.LENS)
    c.nodes[1].cp_in = ControlPoint(13.0, -5.0)   # the maker's custom handle
    item = ws.add_curve(c)
    item.setSelected(True)

    win._copy_across_mirror()

    (result,) = [k for k in ws.doc_curves if k.closed]
    assert len(result.nodes) == 4               # 3 kept + 1 mirrored interior
    kept = result.nodes[1]
    assert (kept.cp_in.x, kept.cp_in.y) == (13.0, -5.0)   # preserved verbatim
    mirrored = result.nodes[3]
    assert (mirrored.x, mirrored.y) == pytest.approx((-15.0, 0.0))
    # Reverse traversal: the mirrored node's cp_out is the reflected cp_in.
    assert (mirrored.cp_out.x, mirrored.cp_out.y) == pytest.approx((-13.0, -5.0))
    # Seam nodes sit on the axis with mirror-symmetric handle pairs.
    seam = result.nodes[0]
    assert seam.x == pytest.approx(0.0)
    assert seam.cp_in.x == pytest.approx(-seam.cp_out.x)
    assert seam.cp_in.y == pytest.approx(seam.cp_out.y)


def test_file_new_resets_calibration_and_boxing_lock(fresh):
    win = fresh
    ws = win._active_ws
    ws.image_px_per_mm = 2.5
    ws.boxing_snapped = True
    ws.shape_locked = True
    ws.outline_locked = True

    win._dirty = False
    win._new()

    assert ws.image_px_per_mm is None
    assert not ws.boxing_snapped
    assert not ws.shape_locked
    assert not ws.outline_locked


def test_save_actions_have_shortcuts(fresh):
    # Extract plain strings while iterating — stashing QAction/QMenu wrappers
    # from a discarded generator trips shiboken wrapper invalidation.
    win = fresh
    shortcuts = {}
    for top in win.menuBar().actions():
        if top.text() == "File" and top.menu() is not None:
            for act in top.menu().actions():
                shortcuts[act.text()] = act.shortcut().toString()
    assert shortcuts["Save"] == "Ctrl+S"
    assert shortcuts["Save As…"] == "Ctrl+Shift+S"


def test_failed_insert_keeps_redo_stack(fresh):
    win = fresh
    ws = win._active_ws
    circle_item = ws.add_curve(circle(0, 0, 10))
    win._push_undo_snapshot()
    win._undo()
    assert ws.redo_stack                       # a redo future exists

    # Circles reject node insertion — the attempt must not clear redo.
    from PySide6.QtCore import QPointF
    win._insert_node(circle_item.curve, QPointF(10, 0))
    assert ws.redo_stack
