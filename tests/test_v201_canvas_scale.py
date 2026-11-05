"""2.0.1: the canvas at the scale of an import (BUILDPLAN, "The offset's
cousins", items 9 and 10). One dense curve, the kind a DXF or SVG trace, an
Explode or a large Rebuild count makes, lagged the canvas in five places: a
node drag redrew every handle line on the curve; a node insert scanned 200
points on every segment; the Perpendicular and On-curve snaps re-sampled each
nearby curve on every mouse move, and the Intersection snap every pair after
any edit; and the Frame Fill's end stitch compared every end with every
other. The canvas also took a sweep under 0.001 degrees for a full circle,
where geometry takes only one under 1e-9.

Where it can, a test counts the work (lines redrawn, curves sampled) rather
than timing it; each answer is held to the one the old code gave."""
import math
import time

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsView

import framedraft.canvas.snapping as snapping
from framedraft.canvas.items import HandleDot, build_path
from framedraft.canvas.scene import FrameScene, _FILL_STITCH_TOL_MM, _snap_free_ends
from framedraft.canvas.snapping import SNAP_TYPE_KEYS, SnapEngine, _angle_in_arc
from framedraft.document import ControlPoint, SplineNode
from framedraft.geometry import _arc_sweep_deg, arc_bbox
from framedraft.tools.edit import EditTool
from helpers import arc, line, spline


def _lens(n, a=25.0, b=17.0, cx=0.0, cy=0.0):
    return [(cx + a * math.cos(2 * math.pi * i / n),
             cy + b * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _shift(curve, dx, dy):
    for nd in curve.nodes:
        nd.x += dx
        nd.y += dy
        for which in ("cp_in", "cp_out"):
            cp = getattr(nd, which)
            if cp is not None:
                setattr(nd, which, ControlPoint(cp.x + dx, cp.y + dy))


def _counted(monkeypatch, module, name):
    """Patch module.name with a wrapper that records each call."""
    calls = []
    real = getattr(module, name)

    def wrapper(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)
    monkeypatch.setattr(module, name, wrapper)
    return calls


# ── Dragging a node of a dense spline ────────────────────────────────────

@pytest.fixture()
def selected():
    """select(curve) -> (scene, tool), the curve selected and its dots shown;
    the tool lets go of the scene's signal before the scene goes."""
    made = []

    def select(curve):
        scene = FrameScene()
        tool = EditTool(scene)
        made.append((scene, tool))
        scene.add_curve(curve).setSelected(True)
        assert len(tool._dots) == len(curve.nodes)
        return scene, tool
    yield select
    for scene, tool in made:
        scene.selectionChanged.disconnect(tool._on_selection)
        tool.clear()


def _count_set_line(tool):
    calls = []
    for item in tool._lines:
        real = item.setLine
        item.setLine = (lambda *a, real=real: (calls.append(a), real(*a))[1])
    return calls


def _assert_lines_follow_the_model(tool, curve):
    for entry in tool._line_data:
        node = curve.nodes[entry["node_index"]]
        cp = getattr(node, entry["which"])
        ln = entry["line_item"].line()
        assert (ln.x1(), ln.y1(), ln.x2(), ln.y2()) == pytest.approx(
            (node.x, node.y, cp.x, cp.y), abs=1e-12)
        hp = entry["handle_dot"].pos()
        assert (hp.x(), hp.y()) == pytest.approx((cp.x, cp.y), abs=1e-12)


def _handle(tool, index, which):
    return next(h for h in tool._handles
                if isinstance(h, HandleDot) and h._node_index == index
                and h._which == which)


def test_a_node_drag_redraws_only_the_handle_lines_beside_it(selected):
    """Every line on the curve was set again on each tick, 2 a node: 96 to
    127 ms a tick at 5000 nodes. A drag moves one node and its handles."""
    c = spline(_lens(400), closed=True)
    _scene, tool = selected(c)
    calls = _count_set_line(tool)

    dot = tool._dots[200]
    dot.setPos(dot.pos() + QPointF(0.7, -0.4))            # one drag tick
    assert 0 < len(calls) <= 6
    _assert_lines_follow_the_model(tool, c)

    calls.clear()
    h = _handle(tool, 100, "cp_out")                       # turns its sibling too
    h.setPos(h.pos() + QPointF(0.2, 0.5))
    assert 0 < len(calls) <= 6
    _assert_lines_follow_the_model(tool, c)


@pytest.mark.parametrize("closed", [True, False])
def test_dragging_the_first_or_last_node_keeps_every_line_on_its_handle(
        selected, closed):
    c = spline(_lens(12), closed=closed)
    _scene, tool = selected(c)
    for i in (0, len(c.nodes) - 1, 0):
        dot = tool._dots[i]
        dot.setPos(dot.pos() + QPointF(1.5, 0.5))
        _assert_lines_follow_the_model(tool, c)
        h = _handle(tool, i, "cp_in" if i else "cp_out")
        h.setPos(h.pos() + QPointF(-0.3, 0.8))
        _assert_lines_follow_the_model(tool, c)


# ── Inserting a node ─────────────────────────────────────────────────────

def _insert_by_full_scan(curve, mx, my):
    """2.0.0's insert: the nearest of 201 points on every segment, the first
    one met on a tie, split there by de Casteljau."""
    nodes = curve.nodes
    n = len(nodes)
    pairs = list(range(n - 1)) + ([n - 1] if curve.closed else [])

    def ends(i):
        a, b = nodes[i], nodes[(i + 1) % n]
        p0 = (a.x, a.y)
        p1 = (a.cp_out.x, a.cp_out.y) if a.cp_out else p0
        p2 = (b.cp_in.x, b.cp_in.y) if b.cp_in else (b.x, b.y)
        return a, b, p0, p1, p2, (b.x, b.y)

    best_d, best_seg, best_t = float("inf"), -1, 0.5
    for i in pairs:
        _a, _b, p0, p1, p2, p3 = ends(i)
        for s in range(201):
            t = s / 200
            bx = EditTool._cubic(p0[0], p1[0], p2[0], p3[0], t)
            by = EditTool._cubic(p0[1], p1[1], p2[1], p3[1], t)
            d = math.hypot(mx - bx, my - by)
            if d < best_d:
                best_d, best_seg, best_t = d, i, t
    if best_seg < 0:
        return False
    a, b, p0, p1, p2, p3 = ends(best_seg)
    t, lerp = best_t, EditTool._lerp
    ax, ay = lerp(p0[0], p1[0], t), lerp(p0[1], p1[1], t)
    bx, by = lerp(p1[0], p2[0], t), lerp(p1[1], p2[1], t)
    cx, cy = lerp(p2[0], p3[0], t), lerp(p2[1], p3[1], t)
    dx, dy = lerp(ax, bx, t), lerp(ay, by, t)
    ex, ey = lerp(bx, cx, t), lerp(by, cy, t)
    a.cp_out = ControlPoint(ax, ay)
    b.cp_in = ControlPoint(cx, cy)
    nodes.insert(best_seg + 1, SplineNode(
        x=lerp(dx, ex, t), y=lerp(dy, ey, t),
        cp_in=ControlPoint(dx, dy), cp_out=ControlPoint(ex, ey)))
    return True


def _flat(curve):
    out = []
    for nd in curve.nodes:
        out.append((nd.x, nd.y))
        for cp in (nd.cp_in, nd.cp_out):
            out.append(None if cp is None else (cp.x, cp.y))
    return out


def _corner_spline():
    """Handles missing at some nodes, and one segment of zero length."""
    c = spline([(0, 0), (10, 5), (10, 5), (20, -3), (32, 8), (40, 0)])
    c.nodes[0].cp_out = None
    c.nodes[3].cp_in = None
    c.nodes[3].cp_out = None
    return c


_INSERT_CASES = [
    # (curve builder, cursor)
    (lambda: spline(_lens(2000), closed=True), (0.0, -17.01)),
    (lambda: spline(_lens(2000), closed=True), (25.0, 0.0)),       # on node 0: the seam
    (lambda: spline(_lens(2000), closed=True), (0.0, 0.0)),        # two nearest, a tie
    (lambda: spline(_lens(2000), closed=True), (90.0, 70.0)),      # far off
    (lambda: spline(_lens(64), closed=True), (17.6, 12.3)),
    (lambda: spline(_lens(64), closed=False), (25.0, -0.2)),       # past the open end
    (lambda: spline(_lens(500, cx=3.0), closed=False), (8.0, 16.0)),
    (_corner_spline, (10.0, 5.0)),                                 # on the doubled node
    (_corner_spline, (20.0, -3.0)),
    (_corner_spline, (26.0, 2.5)),
    (lambda: spline([(0, 0), (10, 0)]), (5.0, 3.0)),
    (lambda: spline([(0, 0), (10, 0)], closed=True), (5.0, 0.0)),
]


@pytest.mark.parametrize("make, cursor", _INSERT_CASES)
def test_an_inserted_node_lands_where_the_full_scan_put_it(make, cursor):
    want, got = make(), make()
    scene = FrameScene()
    assert _insert_by_full_scan(want, *cursor)
    assert EditTool(scene).insert_node_at(got, QPointF(*cursor))
    assert len(got.nodes) == len(want.nodes)
    for g, w in zip(_flat(got), _flat(want), strict=True):
        assert (g is None) == (w is None)
        if g is not None:
            assert g == pytest.approx(w, abs=1e-9)


def test_a_node_insert_on_a_dense_spline_scans_only_the_segments_by_the_cursor(
        monkeypatch):
    """200 points on all 2000 segments: 0.49 s at 5000 nodes. The segments
    whose control box lies farther than the nearest point found cannot hold
    a nearer one, so they are passed over."""
    evals = []
    real = EditTool._cubic
    monkeypatch.setattr(EditTool, "_cubic", staticmethod(
        lambda *a: (evals.append(1), real(*a))[1]))
    c = spline(_lens(2000), closed=True)
    scene = FrameScene()
    assert EditTool(scene).insert_node_at(c, QPointF(0.0, -17.01))
    assert len(c.nodes) == 2001
    assert 0 < len(evals) <= 8 * 2 * 201           # a handful of segments


# ── The snap engine ──────────────────────────────────────────────────────

def _engine(curves):
    scene = FrameScene()
    view = QGraphicsView(scene)
    eng = SnapEngine(scene)
    eng.set_doc_curves(curves)
    return scene, view, eng


def _only(*keys):
    return {k: (k in keys) for k in SNAP_TYPE_KEYS}


def _kind(eng):
    return eng._indicator_key[0] if eng._indicator_key else None


def test_the_perpendicular_snap_samples_a_spline_once_until_it_changes(monkeypatch):
    """On by default, it sampled every spline near the cursor on every move
    while a line was drawn: 50 ms a move at 2000 nodes, 121 at 5000."""
    sampled = _counted(monkeypatch, snapping, "sample_curve")
    c = spline(_lens(400), closed=True)
    other = line([(-60, -40), (60, -40)])
    scene, view, eng = _engine([c, other])
    eng.set_enabled_types(_only("perpendicular"))
    anchor = [SplineNode(x=0.0, y=60.0)]
    for dx in (0.3, 0.1, -0.2, 0.4):
        p = eng.snap(QPointF(dx, 17.4), anchor, view)
        assert (p.x(), p.y()) == pytest.approx((0.0, 17.0), abs=1e-4)
        assert _kind(eng) == "perpendicular"
    assert len(sampled) == 1

    _shift(other, 0.0, 1.0)                    # another curve's edit
    scene.refresh_curve(other)
    eng.snap(QPointF(0.2, 17.4), anchor, view)
    assert len(sampled) == 1

    _shift(c, 0.0, 1.0)                        # its own
    scene.refresh_curve(c)
    p = eng.snap(QPointF(0.2, 18.4), anchor, view)
    assert (p.x(), p.y()) == pytest.approx((0.0, 18.0), abs=1e-4)
    assert len(sampled) == 2


def test_the_on_curve_snap_samples_a_curve_once_until_it_changes(monkeypatch):
    sampled = _counted(monkeypatch, snapping, "sample_curve")
    c = spline(_lens(400), closed=True)
    scene, view, eng = _engine([c])
    eng.set_enabled_types(_only("curve"))
    for x in (25.3, 25.2, 25.4):
        p = eng.snap(QPointF(x, 0.0), [], view)
        assert (p.x(), p.y()) == pytest.approx((25.0, 0.0), abs=1e-6)
        assert _kind(eng) == "curve"
    assert len(sampled) == 1

    _shift(c, 0.0, 2.0)
    scene.refresh_curve(c)
    p = eng.snap(QPointF(25.3, 2.0), [], view)
    assert (p.x(), p.y()) == pytest.approx((25.0, 2.0), abs=1e-6)
    assert len(sampled) == 2


def test_the_intersection_snap_recomputes_only_the_pairs_of_a_changed_curve(
        monkeypatch):
    """The whole cache was dropped on any edit, and the next move recomputed
    every nearby pair: up to 0.56 s."""
    met = _counted(monkeypatch, snapping, "curve_intersections")
    rows = [line([(-6, y), (6, y)]) for y in (-2.0, 2.0)]
    cols = [line([(x, -6), (x, 6)]) for x in (-2.0, 2.0)]
    scene, view, eng = _engine(rows + cols)
    eng.set_enabled_types(_only("intersection"))

    p = eng.snap(QPointF(2.3, 2.4), [], view)
    assert (p.x(), p.y()) == pytest.approx((2.0, 2.0), abs=1e-9)
    assert len(met) == 6                       # every pair of four, once
    eng.snap(QPointF(-2.2, 1.7), [], view)
    assert len(met) == 6

    scene.revision += 1                        # a revision, nothing changed
    eng.snap(QPointF(-2.2, 1.7), [], view)
    assert len(met) == 6

    _shift(cols[1], 1.0, 0.0)                  # x = 2 moves to x = 3
    scene.refresh_curve(cols[1])
    p = eng.snap(QPointF(3.3, 2.4), [], view)
    assert (p.x(), p.y()) == pytest.approx((3.0, 2.0), abs=1e-9)
    assert len(met) == 6 + 3                   # its three pairs only
    assert _kind(eng) == "intersection"


def test_the_intersection_snap_forgets_a_removed_curve():
    a = line([(-6, 0), (6, 0)])
    b = line([(0, -6), (0, 6)])
    curves = [a, b]
    scene, view, eng = _engine(curves)
    eng.set_enabled_types(_only("intersection"))
    p = eng.snap(QPointF(0.3, 0.2), [], view)
    assert (p.x(), p.y()) == pytest.approx((0.0, 0.0), abs=1e-9)
    curves.remove(b)
    scene.revision += 1
    p = eng.snap(QPointF(0.3, 0.2), [], view)
    assert (p.x(), p.y()) == (0.3, 0.2)
    assert not eng._isect_cache                # nor holds it


# ── The Frame Fill's end stitch ──────────────────────────────────────────

def _exploded(n, r=100.0):
    from shapely.geometry import LineString
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    return [LineString([pts[i], pts[(i + 1) % n]]) for i in range(n)]


def _stitch_time(lines):
    best = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        _snap_free_ends(lines, _FILL_STITCH_TOL_MM)
        best = min(best, time.perf_counter() - t0)
    return best


def test_the_fill_stitch_grows_with_the_pieces_not_their_square():
    """An outline exploded into 1800 pieces took 369 ms a rebuild, on every
    drag tick while the fill was on: each end looked for its partner among
    all the others. Eight times the pieces cost about eight times the time
    now; it was over thirty."""
    small, big = _exploded(200), _exploded(1600)
    out = _snap_free_ends(big, _FILL_STITCH_TOL_MM)
    assert [list(a.coords) for a in out] == [list(b.coords) for b in big]
    assert _stitch_time(big) < 16 * _stitch_time(small)


# ── The arc-sweep rule ───────────────────────────────────────────────────

def test_a_sliver_arc_draws_as_the_sliver_geometry_sees():
    """A fillet of nearly straight legs: the canvas drew a full circle, and
    geometry and the DXF a dot-sized arc."""
    a = arc(0.0, 0.0, 5.0, 0.0, 0.0005)
    r = build_path(a).boundingRect()
    assert r.width() < 0.01 and r.height() < 0.01
    x0, y0, x1, y1 = arc_bbox(0.0, 0.0, 5.0, 0.0, 0.0005)
    assert x1 - x0 < 0.01 and y1 - y0 < 0.01


def test_a_sliver_arc_offers_no_quadrant_it_does_not_reach():
    _s, view, eng = _engine([arc(0.0, 0.0, 5.0, 0.0, 0.0005)])
    eng.set_enabled_types(_only("quadrant"))
    eng.set_radius_px(2)                         # 2 mm: one quadrant at a time
    p = eng.snap(QPointF(0.3, 5.2), [], view)
    assert (p.x(), p.y()) == (0.3, 5.2)
    p = eng.snap(QPointF(5.2, 0.3), [], view)
    assert (p.x(), p.y()) == (5.0, 0.0)          # its start is on 0 degrees


@pytest.mark.parametrize("sweep", [0.0, 1e-12, 1e-10, 1e-8, 1e-6, 1e-4, 0.0009,
                                   0.002, 1.0, 90.0, 359.9999])
def test_the_canvas_and_geometry_agree_on_a_full_circle(sweep):
    a = arc(0.0, 0.0, 5.0, 30.0, 30.0 + sweep)
    x0, y0, x1, y1 = arc_bbox(0.0, 0.0, 5.0, a.start_angle, a.end_angle)
    r = build_path(a).boundingRect()
    assert (r.left(), r.top(), r.right(), r.bottom()) == pytest.approx(
        (x0, y0, x1, y1), abs=0.01)
    # Just short of the start: on the arc only when it is a full circle.
    assert (_angle_in_arc(29.99995, a.start_angle, a.end_angle)
            == (_arc_sweep_deg(a) == 360.0))
