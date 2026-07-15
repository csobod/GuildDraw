"""geometry.py — parameterisation, intersection, splitting, offset, bboxes."""
import math

import pytest

from framedraft.geometry import (
    point_at_t, arc_bbox, dedup_ts_mm, intersect_curve_params,
    split_curve_at_t, extract_open_segment, extract_wrapping_segment,
    t_nearest, offset_curve, sample_curve, circle_to_spline, arc_to_spline,
)
from helpers import line, spline, circle, arc


def pt_close(a, b, tol=1e-6):
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


# ---------------------------------------------------------------- point_at_t

def test_point_at_t_line_endpoints_and_interior():
    c = line([(0, 0), (10, 0), (20, 0)])
    assert point_at_t(c, 0.0) == (0, 0)
    assert point_at_t(c, 1.0) == (20, 0)
    assert point_at_t(c, 0.5) == (10, 0)
    assert point_at_t(c, 0.25) == (5, 0)


def test_point_at_t_circle_and_arc():
    c = circle(0, 0, 10)
    assert pt_close(point_at_t(c, 0.25), (0, 10))   # 90 deg = down-screen
    a = arc(0, 0, 10, 0, 90)
    assert pt_close(point_at_t(a, 0.0), (10, 0))
    assert pt_close(point_at_t(a, 1.0), (0, 10))


def test_point_at_t_spline_matches_nodes():
    s = spline([(0, 0), (10, 5), (20, 0)])
    assert pt_close(point_at_t(s, 0.0), (0, 0))
    assert pt_close(point_at_t(s, 0.5), (10, 5))
    assert pt_close(point_at_t(s, 1.0), (20, 0))


def test_t_nearest_recovers_point():
    s = spline([(0, 0), (10, 5), (20, 0)])
    t = t_nearest(s, 10, 5)
    assert abs(t - 0.5) < 0.05


# ------------------------------------------------------------------ arc_bbox

def test_arc_bbox_quarter():
    bx0, by0, bx1, by1 = arc_bbox(0, 0, 10, 0, 90)
    assert pt_close((bx0, by0), (0, 0)) and pt_close((bx1, by1), (10, 10))


def test_arc_bbox_degenerate_sweep_is_full_circle():
    assert all(abs(g - w) < 1e-9 for g, w in
               zip(arc_bbox(0, 0, 10, 45, 45), (-10, -10, 10, 10), strict=True))


# --------------------------------------------------------------- dedup_ts_mm

def test_dedup_keeps_points_3mm_apart_on_long_curve():
    # The old 0.04 t-space tolerance merged anything within 12 mm here.
    big = line([(i * 10, 0) for i in range(31)])      # 300 mm, 30 segments
    assert len(dedup_ts_mm(big, [0.50, 0.51])) == 2   # 3 mm apart


def test_dedup_merges_coincident_points():
    big = line([(i * 10, 0) for i in range(31)])
    assert len(dedup_ts_mm(big, [0.500, 0.5001])) == 1  # 0.03 mm apart


def test_dedup_merges_across_closed_seam():
    sq = line([(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
    assert len(dedup_ts_mm(sq, [0.001, 0.999])) == 1


# ------------------------------------------------------------- intersections

def test_crossing_lines_intersect_once():
    a = line([(0, 0), (100, 0)])
    b = line([(50, -50), (50, 50)])
    ts = intersect_curve_params(a, b)
    assert len(ts) == 1 and abs(ts[0] - 0.5) < 0.02


def test_endpoint_touch_is_filtered_on_open_curves():
    a = line([(0, 0), (100, 0)])
    touch = line([(0, 0), (0, 50)])
    assert intersect_curve_params(a, touch) == []


def test_circle_line_two_intersections():
    c = circle(0, 0, 10)
    chord = line([(-20, 0), (20, 0)])
    ts = dedup_ts_mm(c, intersect_curve_params(c, chord))
    assert len(ts) == 2


# ----------------------------------------------------------------- splitting

def test_split_rejects_near_endpoint():
    a = line([(0, 0), (100, 0)])
    left, right = split_curve_at_t(a, 0.001)   # 0.1 mm from start
    assert right is None and left is a


def test_split_halves_are_continuous():
    s = spline([(0, 0), (10, 8), (20, 0), (30, -8), (40, 0)])
    mid = point_at_t(s, 0.5)
    left, right = split_curve_at_t(s, 0.5)
    assert right is not None
    assert pt_close(point_at_t(left, 1.0), mid, tol=1e-3)
    assert pt_close(point_at_t(right, 0.0), mid, tol=1e-3)
    assert pt_close(point_at_t(left, 0.0), (0, 0), tol=1e-3)
    assert pt_close(point_at_t(right, 1.0), (40, 0), tol=1e-3)


def test_split_circle_yields_arcs():
    c = circle(0, 0, 10)
    left, right = split_curve_at_t(c, 0.5)
    assert left.kind == "arc" and right.kind == "arc"
    assert left.radius == right.radius == 10


# ---------------------------------------------------------------- extraction

def test_extract_open_segment_endpoints():
    s = spline([(0, 0), (10, 8), (20, 0), (30, -8), (40, 0)])
    seg = extract_open_segment(s, 0.25, 0.75)
    assert pt_close(point_at_t(seg, 0.0), point_at_t(s, 0.25), tol=1e-3)
    assert pt_close(point_at_t(seg, 1.0), point_at_t(s, 0.75), tol=1e-3)
    assert seg.closed is False


def test_extract_wrapping_segment_on_closed_polyline():
    sq = line([(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
    seg = extract_wrapping_segment(sq, 0.875, 0.125)
    assert pt_close((seg.nodes[0].x, seg.nodes[0].y), point_at_t(sq, 0.875), tol=1e-6)
    assert pt_close((seg.nodes[-1].x, seg.nodes[-1].y), point_at_t(sq, 0.125), tol=1e-6)
    assert seg.closed is False


# -------------------------------------------------------------------- offset

def _dist_to_sampled(px, py, pts):
    """Distance from (px, py) to the polyline through pts (with projection)."""
    best = float("inf")
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-18:
            d2 = (px - ax) ** 2 + (py - ay) ** 2
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            d2 = (px - ax - dx * t) ** 2 + (py - ay - dy * t) ** 2
        best = min(best, d2)
    return math.sqrt(best)


def max_parallel_error(src, off, d, n_src=64, n_off=32):
    """Worst |distance(offset point → source curve) − |d|| over the offset."""
    src_pts = [(x, y) for x, y, _ in sample_curve(src, n_src)]
    return max(abs(_dist_to_sampled(x, y, src_pts) - abs(d))
               for x, y, _ in sample_curve(off, n_off))


def test_offset_line_left_normal():
    c = line([(0, 0), (10, 0)])
    off = offset_curve(c, 2.0)
    assert pt_close((off.nodes[0].x, off.nodes[0].y), (0, 2))
    assert pt_close((off.nodes[1].x, off.nodes[1].y), (10, 2))


def test_offset_circle_is_analytic():
    assert offset_curve(circle(0, 0, 10), 2.0).radius == 12.0
    assert offset_curve(circle(0, 0, 10), -20.0).radius == 0.0  # clamped


def test_offset_preserves_structure():
    s = spline([(0, -20), (20, 0), (0, 20), (-20, 0)], closed=True)
    off = offset_curve(s, 3.0)
    assert off.kind == "spline" and off.closed is True
    assert off.layer == s.layer
    # M31.1 refits the offset to a compact node set — it must stay parallel
    # without exploding the node count (a lens outline stays a handful of nodes).
    assert max_parallel_error(s, off, 3.0) < 0.05
    assert len(off.nodes) <= 12


# ------------------------------------------------------- conic → spline

def test_circle_to_spline_radial_accuracy():
    c = circle(5, -3, 20)
    s = circle_to_spline(c)
    assert s.kind == "spline" and s.closed and len(s.nodes) == 4
    for x, y, _t in sample_curve(s, 32):
        r = math.hypot(x - 5, y + 3)
        assert abs(r - 20) < 20 * 0.001, r   # ≤0.1% radial deviation


def test_arc_to_spline_endpoints_and_accuracy():
    a = arc(0, 0, 15, 30, 200)               # 170° sweep → 2 segments
    s = arc_to_spline(a)
    assert s.kind == "spline" and not s.closed
    assert pt_close((s.nodes[0].x, s.nodes[0].y), point_at_t(a, 0.0), tol=1e-9)
    assert pt_close((s.nodes[-1].x, s.nodes[-1].y), point_at_t(a, 1.0), tol=1e-9)
    for x, y, _t in sample_curve(s, 32):
        assert abs(math.hypot(x, y) - 15) < 15 * 0.001


@pytest.mark.parametrize("d", [2.0, -2.0])
def test_offset_spline_is_truly_parallel(d):
    """GitHub issue #6 — the offset must track the drawn curve (handles
    included) everywhere, not just at the nodes."""
    s = spline([(0, -20), (20, 0), (0, 20), (-20, 0)], closed=True)
    assert max_parallel_error(s, offset_curve(s, d), d) < 0.05


@pytest.mark.parametrize("d", [1.0, 2.5, -1.5])
def test_offset_custom_handles_parallel(d):
    """Hand-tuned (non-Catmull) handles are part of the shape the offset
    must follow — the old node-polygon offset discarded them."""
    s = spline([(0, -22), (28, -15), (33, 5), (15, 24), (-20, 18), (-30, -8)],
               closed=True)
    from framedraft.document import ControlPoint
    s.nodes[1].cp_out = ControlPoint(s.nodes[1].x + 9, s.nodes[1].y + 6)
    s.nodes[1].cp_in  = ControlPoint(s.nodes[1].x - 9, s.nodes[1].y - 6)
    s.nodes[3].cp_out = ControlPoint(s.nodes[3].x - 12, s.nodes[3].y + 1)
    s.nodes[3].cp_in  = ControlPoint(s.nodes[3].x + 12, s.nodes[3].y - 1)
    assert max_parallel_error(s, offset_curve(s, d), d) < 0.05


def test_offset_reduces_nodes_end_to_end():
    """M31.1: offset_curve refits its own Tiller–Hanson result to a compact,
    editable node set — a two-node closed lens offsets to ≤10 nodes, not ~28,
    while staying parallel."""
    from framedraft.geometry import _offset_spline
    from framedraft.document import Curve, SplineNode, ControlPoint, Layer
    r, k = 20.0, (4.0 / 3.0) * 20.0
    a = SplineNode(x=r, y=0.0);  a.cp_out = ControlPoint(r, k);   a.cp_in = ControlPoint(r, -k)
    b = SplineNode(x=-r, y=0.0); b.cp_out = ControlPoint(-r, -k); b.cp_in = ControlPoint(-r, k)
    lens = Curve(kind="spline", layer=Layer.LENS, nodes=[a, b], closed=True)

    raw = _offset_spline(lens, 2.0)
    off = offset_curve(lens, 2.0)
    assert len(off.nodes) <= 10 < len(raw.nodes)
    assert off.closed is True
    assert max_parallel_error(lens, off, 2.0) < 0.05


@pytest.mark.parametrize("d", [2.0, -2.0, 5.0])
def test_offset_two_node_closed_spline(d):
    """GitHub issue #5 — a closed spline with only two nodes (circle drawn
    with two handle-controlled points) must offset to a real ring, not a line."""
    from framedraft.document import Curve, SplineNode, ControlPoint, Layer
    r, k = 20.0, (4.0 / 3.0) * 20.0     # single-cubic semicircle handles
    a = SplineNode(x=r, y=0.0)
    a.cp_out = ControlPoint(r, k);   a.cp_in = ControlPoint(r, -k)
    b = SplineNode(x=-r, y=0.0)
    b.cp_out = ControlPoint(-r, -k); b.cp_in = ControlPoint(-r, k)
    c = Curve(kind="spline", layer=Layer.LENS, nodes=[a, b], closed=True)

    off = offset_curve(c, d)
    ys = [y for _x, y, _t in sample_curve(off, 32)]
    xs = [x for x, _y, _t in sample_curve(off, 32)]
    assert max(ys) - min(ys) > 1.0, "offset collapsed to a line (issue #5)"
    assert max_parallel_error(c, off, d) < 0.05
    assert ((max(xs) - min(xs)) > 2 * r) == (d > 0), "wrong offset direction"


@pytest.mark.parametrize("d", [2.0, -2.0])
def test_offset_open_spline_parallel_and_endpoints(d):
    s = spline([(0, 0), (15, 12), (30, -12), (45, 0)], closed=False)
    off = offset_curve(s, d)
    assert off.closed is False
    assert max_parallel_error(s, off, d) < 0.05
    # endpoints displaced exactly |d| from the source endpoints
    for t in (0.0, 1.0):
        sx, sy = point_at_t(s, t)
        ox, oy = point_at_t(off, t)
        assert abs(math.hypot(ox - sx, oy - sy) - abs(d)) < 1e-6


def test_offset_spline_g1_smooth():
    """GitHub issue #6 — no kinks: wherever the source is smooth, cp_in/node/
    cp_out of the offset must stay collinear."""
    s = spline([(0, -20), (20, 0), (0, 20), (-20, 0)], closed=True)
    off = offset_curve(s, 2.0)
    for nd in off.nodes:
        if not (nd.cp_in and nd.cp_out):
            continue
        v1 = (nd.x - nd.cp_in.x, nd.y - nd.cp_in.y)
        v2 = (nd.cp_out.x - nd.x, nd.cp_out.y - nd.y)
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        sin_kink = abs(v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)
        assert math.degrees(math.asin(min(1.0, sin_kink))) < 1.0


def test_offset_corner_spline_bevels_and_stays_closed():
    """Broken-handle corners get a straight bevel join; result stays closed."""
    s = spline([(0, 0), (30, 0), (30, 30), (0, 30)], closed=True)
    for nd in s.nodes:
        nd.cp_in = nd.cp_out = None     # straight segments, hard corners
    off = offset_curve(s, 2.0)
    assert off.closed is True
    src_pts = [(x, y) for x, y, _ in sample_curve(s, 64)]
    dists = [_dist_to_sampled(x, y, src_pts) for x, y, _ in sample_curve(off, 32)]
    # bevel chords the corner arc: distance stays within [d·cos45°, d]
    assert min(dists) > 2.0 * math.cos(math.radians(45)) - 0.05
    assert max(dists) < 2.05


_DIAMOND      = [(0, -20), (20, 0), (0, 20), (-20, 0)]
_DIAMOND_REV  = list(reversed(_DIAMOND))


@pytest.mark.parametrize("pts", [_DIAMOND, _DIAMOND_REV])
@pytest.mark.parametrize("kind", ["line", "spline"])
def test_offset_closed_positive_is_outward_any_winding(pts, kind):
    """GitHub issue #1 — +d must grow a closed shape whatever the winding
    (the old left-normal rule sent +d inward on one of the two windings)."""
    make = line if kind == "line" else spline
    c = make(pts, closed=True)
    outward = offset_curve(c, 2.8)
    inward  = offset_curve(c, -2.8)
    src_r = [math.hypot(x, y) for x, y, _ in sample_curve(c, 16)]
    out_r = [math.hypot(x, y) for x, y, _ in sample_curve(outward, 16)]
    in_r  = [math.hypot(x, y) for x, y, _ in sample_curve(inward, 16)]
    assert min(out_r) > min(src_r) - 1e-6 and max(out_r) > max(src_r), \
        "positive offset went inward"
    assert max(in_r) < max(src_r) + 1e-6 and min(in_r) < min(src_r), \
        "negative offset went outward"
