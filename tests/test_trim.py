"""Reliability checks for trimming arcs/circles/curves (geometry layer).

The TrimTool itself is Qt-coupled, but it delegates all the hard work to
``intersect_curve_params`` + ``dedup_ts_mm`` + the segment extractors. These
exercise the arc/circle paths that the maker reported wanting confidence in.
"""
import math

from framedraft.geometry import (
    intersect_curve_params, dedup_ts_mm, point_at_t,
    extract_open_segment, extract_wrapping_segment,
)
from helpers import line, circle, arc, closed_diamond


def _on_curve(curve, t, expect_xy, tol=1e-3):
    x, y = point_at_t(curve, t)
    assert math.hypot(x - expect_xy[0], y - expect_xy[1]) < tol


def test_arc_crossed_by_line():
    # Semicircle 0->180 (passes through (0,10) in y-down scene); vertical x=0.
    a = arc(0, 0, 10, 0, 180)
    chord = line([(0, -20), (0, 20)])
    ts = dedup_ts_mm(a, intersect_curve_params(a, chord))
    assert len(ts) == 1
    _on_curve(a, ts[0], (0.0, 10.0))


def test_arc_crossed_by_circle():
    a = arc(0, 0, 10, 0, 180)
    other = circle(15, 0, 10)     # centres 15 apart, equal r -> cross at x=7.5
    ts = dedup_ts_mm(a, intersect_curve_params(a, other))
    assert len(ts) >= 1
    for t in ts:
        x, y = point_at_t(a, t)
        assert math.hypot(x, y) == 10.0 or abs(math.hypot(x, y) - 10.0) < 1e-6


def test_trim_arc_keeps_two_segments():
    # Open arc crossed once by a line -> trimming the clicked half leaves the
    # other open segment (mirrors TrimTool's open-curve branch).
    a = arc(0, 0, 10, 0, 180)
    chord = line([(0, -20), (0, 20)])
    ts = sorted(dedup_ts_mm(a, intersect_curve_params(a, chord)))
    t = ts[0]
    left = extract_open_segment(a, 0.0, t)
    right = extract_open_segment(a, t, 1.0)
    # Continuity: left ends and right starts at the same split point.
    le = point_at_t(left, 1.0)
    rs = point_at_t(right, 0.0)
    assert math.hypot(le[0] - rs[0], le[1] - rs[1]) < 1e-3


def test_trim_circle_between_two_chords():
    # Circle cut by two vertical chords -> two intersections; removing the
    # near arc keeps the wrapping arc (TrimTool's closed-curve branch).
    c = circle(0, 0, 10)
    left_chord  = line([(-5, -20), (-5, 20)])
    right_chord = line([(5, -20), (5, 20)])
    raw = intersect_curve_params(c, left_chord) + intersect_curve_params(c, right_chord)
    ts = dedup_ts_mm(c, raw)
    assert len(ts) == 4    # each chord crosses the circle twice
    ts_s = sorted(ts)
    seg = extract_wrapping_segment(c, ts_s[-1], ts_s[0])
    # The kept segment is a real curve with distinct endpoints.
    s = point_at_t(seg, 0.0)
    e = point_at_t(seg, 1.0)
    assert math.hypot(s[0] - e[0], s[1] - e[1]) > 1.0


def test_trim_spline_by_line():
    diamond = closed_diamond(cx=0, cy=0, r=20)
    chord = line([(-40, 0), (40, 0)])   # horizontal through the middle
    ts = dedup_ts_mm(diamond, intersect_curve_params(diamond, chord))
    assert len(ts) == 2
