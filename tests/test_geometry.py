"""geometry.py — parameterisation, intersection, splitting, offset, bboxes."""
import math

import pytest

from framedraft.geometry import (
    point_at_t, arc_bbox, dedup_ts_mm, intersect_curve_params,
    split_curve_at_t, extract_open_segment, extract_wrapping_segment,
    t_nearest, offset_curve,
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
    assert len(off.nodes) == len(s.nodes)


@pytest.mark.parametrize("d", [2.0, -2.0])
def test_offset_distance_roughly_constant(d):
    s = spline([(0, -20), (20, 0), (0, 20), (-20, 0)], closed=True)
    off = offset_curve(s, d)
    # node-to-node displacement should be |d| within a loose tolerance
    for a, b in zip(s.nodes, off.nodes, strict=True):
        assert abs(math.hypot(b.x - a.x, b.y - a.y) - abs(d)) < 0.5
