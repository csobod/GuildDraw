"""2.0.1: Trim, Split and the Intersection snap meet curves where they are.

Curves were met as polylines of 16 chords a segment, sampled again for every
pair. The chords lie inside a curve by their sagitta, so a line ending on a
curve from outside went unseen; a shallow crossing landed off by the sagitta
over the sine of its angle, up to 2 mm on the Frame Library; overlapping
curves crossed every 1 to 2.5 mm, so Trim removed a sliver; and one click on
a dense trace froze the window for seconds (the 2.0.1 investigation).
"""
import copy
import math
import time

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QGraphicsView

from framedraft import geometry as G
from framedraft.canvas.scene import FrameScene
from framedraft.geometry import (
    curve_intersections, dedup_ts_mm, intersect_curve_params, point_at_t,
    sample_curve, t_nearest,
)
from helpers import arc, circle, closed_diamond, line, spline


def _normal(c, t):
    h = 1e-6
    x0, y0 = point_at_t(c, max(0.0, t - h))
    x1, y1 = point_at_t(c, min(1.0, t + h))
    dx, dy = x1 - x0, y1 - y0
    d = math.hypot(dx, dy)
    return -dy / d, dx / d


def _dist_to(c, x, y):
    """Distance from (x, y) to curve *c*, measured on the curve itself."""
    px, py = point_at_t(c, t_nearest(c, x, y))
    return math.hypot(px - x, py - y)


def _connector(c, t, outside=True, length=5.0):
    """A line ending exactly on curve *c* at t, coming from outside it (or
    inside), as the on-curve and Nearest snaps draw one."""
    from shapely.geometry import Point, Polygon
    px, py = point_at_t(c, t)
    nx, ny = _normal(c, t)
    poly = Polygon([(x, y) for x, y, _ in sample_curve(c, 200)])
    q = (px + length * nx, py + length * ny)
    if poly.contains(Point(q)) == outside:
        q = (px - length * nx, py - length * ny)
    return line([q, (px, py)])


# ══════════════════════════════════════════ a line ending on a curve is seen


def test_a_line_ending_on_a_circle_from_outside_is_seen():
    """It was seen 36 times in 36 from inside the circle, never from outside."""
    c = circle(0, 0, 25)
    for side in (True, False):
        for k in range(36):
            t = (k + 0.3) / 36
            ln = _connector(c, t, outside=side)
            ts = intersect_curve_params(c, ln)
            assert len(ts) == 1, (side, k)
            x, y = point_at_t(c, ts[0])
            assert math.hypot(x - ln.nodes[-1].x, y - ln.nodes[-1].y) < 1e-6
            [(sx, sy)] = curve_intersections(c, ln)          # the Intersection snap
            assert math.hypot(sx - ln.nodes[-1].x, sy - ln.nodes[-1].y) < 1e-6


def test_a_line_ending_on_a_lens_at_a_snap_point_is_seen():
    lens = closed_diamond(r=25.0)
    snaps = [t for _x, _y, t in sample_curve(lens, 24)][:-1]   # the on-curve snap's points
    for side in (True, False):
        seen = sum(len(intersect_curve_params(lens, _connector(lens, t, side))) == 1
                   for t in snaps)
        assert seen == len(snaps), side


def test_an_end_a_hair_short_of_a_curve_meets_it_and_a_gap_does_not():
    """An end within the closure tolerance of a curve meets it, as the Frame
    Fill's stitch and the validator already take it; a real gap does not."""
    c = circle(0, 0, 25)
    for gap, met in ((0.0, True), (0.05, True), (0.09, True), (0.2, False), (1.0, False)):
        ln = line([(25 + gap + 5, 0.3), (25 + gap, 0.3)])
        assert len(intersect_curve_params(c, ln)) == (1 if met else 0), gap


def test_a_slight_overshoot_is_a_crossing_on_the_curve():
    """A line 0.035 mm past a 3-node lens, whose chords lay 0.069 mm inside it:
    140 such ends on the Frame Library went unseen."""
    lens = spline([(25, 0), (-12.5, 21.6), (-12.5, -21.6)], closed=True)
    for t in (0.07, 0.21, 0.4, 0.55, 0.9):
        px, py = point_at_t(lens, t)
        nx, ny = _normal(lens, t)
        for sign in (1, -1):
            ln = line([(px + sign * 4 * nx, py + sign * 4 * ny),
                       (px - sign * 0.035 * nx, py - sign * 0.035 * ny)])
            [t] = intersect_curve_params(lens, ln)
            assert math.dist(point_at_t(lens, t), (px, py)) < 1e-6


# ══════════════════════════════════════════ crossings land on both curves


@pytest.mark.parametrize("deg", [30.0, 10.0, 5.0, 2.0, 1.0])
def test_a_shallow_crossing_lands_on_both_curves(deg):
    """Off by sagitta / sin(angle) before: 1 mm on a circle of R 100 at 2°."""
    R = 100.0
    c = circle(0, 0, R)
    for k in range(12):
        t0 = (k + 0.37) / 12
        px, py = point_at_t(c, t0)
        a = 2 * math.pi * t0 + math.pi / 2 + math.radians(deg)   # tangent turned by deg
        dx, dy = math.cos(a), math.sin(a)
        ln = line([(px - 10 * dx, py - 10 * dy), (px + 10 * dx, py + 10 * dy)])
        ts = intersect_curve_params(ln, c)
        assert ts, (deg, k)
        for t in ts:
            x, y = point_at_t(ln, t)
            assert abs(math.hypot(x, y) - R) < 1e-6
        for t in intersect_curve_params(c, ln):
            x, y = point_at_t(c, t)
            assert abs((x - px) * dy - (y - py) * dx) < 1e-6   # on the line


def test_a_crossing_of_two_splines_lands_on_both():
    lens = closed_diamond(r=25.0)
    other = spline([(-40, 3), (-10, 1.0), (10, 2.0), (40, 0)])
    ts = dedup_ts_mm(lens, intersect_curve_params(lens, other))
    assert len(ts) == 2
    for t in ts:
        assert _dist_to(other, *point_at_t(lens, t)) < 1e-6


def test_a_line_trimmed_to_a_large_arc_ends_on_it():
    """The trimmed end sat 0.143 mm inside an arc of R 150, past the 0.1 mm
    closure tolerance."""
    a = arc(0, 0, 150, 200, 290)
    for k in range(20):
        t = 0.05 + 0.9 * k / 19
        px, py = point_at_t(a, t)
        ln = line([(px * 0.98, py * 0.98), (px * 1.02, py * 1.02)])
        [tl] = intersect_curve_params(ln, a)
        x, y = point_at_t(G.extract_open_segment(ln, 0.0, tl), 1.0)
        assert abs(math.hypot(x, y) - 150.0) < 1e-6


# ══════════════════════════════════════════ overlaps meet at their two ends


def test_a_datum_along_a_straight_edge_meets_it_at_the_corners():
    """44 crossings, 23 after the merge, every 1.25 to 2.5 mm along the edge."""
    outline = line([(0, 0), (40, 0), (40, 20), (0, 20)], closed=True)
    datum = line([(-10, 0), (50, 0)])
    ts = dedup_ts_mm(datum, intersect_curve_params(datum, outline))
    assert sorted(round(point_at_t(datum, t)[0], 9) for t in ts) == [0.0, 40.0]
    ts = dedup_ts_mm(outline, intersect_curve_params(outline, datum))
    assert sorted((round(x, 9), round(y, 9)) for x, y in
                  (point_at_t(outline, t) for t in ts)) == [(0.0, 0.0), (40.0, 0.0)]
    pts = curve_intersections(datum, outline)
    assert sorted((round(x, 9), round(y, 9)) for x, y in pts) == [(0.0, 0.0), (40.0, 0.0)]


def test_a_duplicated_lens_does_not_cross_its_copy():
    """128 crossings, 64 after the merge: Trim removed a 2.3 mm sliver."""
    lens = closed_diamond(r=25.0)
    twin = copy.deepcopy(lens)
    assert intersect_curve_params(lens, twin) == []
    assert curve_intersections(lens, twin) == []
    # A copy split off it lies along it too.
    piece = G.extract_open_segment(lens, 0.1, 0.45)
    ts = intersect_curve_params(lens, piece)
    ends = [point_at_t(piece, 0.0), point_at_t(piece, 1.0)]
    assert len(dedup_ts_mm(lens, ts)) == 2
    for t in ts:
        x, y = point_at_t(lens, t)
        assert min(math.hypot(x - ex, y - ey) for ex, ey in ends) < 0.02


# ══════════════════════════════════════════ the tools


def _view(scene, center=(0.0, 0.0)):
    view = QGraphicsView(scene)
    view.resize(800, 600)
    view.centerOn(*center)
    QApplication.processEvents()
    return view


def _scene_with(curves):
    scene = FrameScene()
    for c in curves:
        scene.add_curve(c)
    return scene


def _trim(curves, click, center=(0.0, 0.0)):
    from framedraft.tools.trim import TrimTool
    scene = _scene_with(curves)
    tool = TrimTool()
    got, msgs = [], []
    tool.trim_applied.connect(lambda orig, rest: got.append((orig, rest)))
    tool.status_message.connect(msgs.append)
    tool.activate(scene, _view(scene, center), lambda: curves)
    tool.handle_press(QPointF(*click))
    return got, msgs


def _split(curves, click, center=(0.0, 0.0)):
    from framedraft.tools.split import SplitTool
    scene = _scene_with(curves)
    tool = SplitTool()
    got, msgs = [], []
    tool.split_applied.connect(got.append)
    tool.status_message.connect(msgs.append)
    tool.activate(scene, _view(scene, center), lambda: curves)
    tool.handle_press(QPointF(*click))
    return got, msgs


def _ends(c):
    return point_at_t(c, 0.0), point_at_t(c, 1.0)


def test_trim_cuts_a_lens_between_two_connectors_from_outside():
    lens = circle(0, 0, 25)
    c1, c2 = _connector(lens, 0.10), _connector(lens, 0.30)
    j1, j2 = (c1.nodes[-1].x, c1.nodes[-1].y), (c2.nodes[-1].x, c2.nodes[-1].y)
    mx, my = point_at_t(lens, 0.2)

    [(orig, rest)], _msgs = _trim([lens, c1, c2], (mx, my))

    assert orig is lens and len(rest) == 1
    for end in _ends(rest[0]):
        assert min(math.dist(end, j1), math.dist(end, j2)) < 1e-6
    assert math.dist(*_ends(rest[0])) > 1.0


def test_split_snaps_to_a_junction_from_outside():
    lens = closed_diamond(r=25.0)
    con = _connector(lens, 0.6)
    jx, jy = con.nodes[-1].x, con.nodes[-1].y
    t_near = G.t_nearest(lens, jx, jy) + 0.005          # about 0.9 mm along the lens
    cx, cy = point_at_t(lens, t_near)

    [pairs], _msgs = _split([lens, con], (cx, cy), center=(cx, cy))

    [(orig, [opened])] = pairs
    assert orig is lens
    x, y = point_at_t(opened, 0.0)
    assert math.hypot(x - jx, y - jy) < 1e-6


def test_trim_a_datum_along_an_edge_removes_the_whole_overlap():
    outline = line([(0, 0), (40, 0), (40, 20), (0, 20)], closed=True)
    datum = line([(-10, 0), (50, 0)])

    [(orig, rest)], _msgs = _trim([outline, datum], (20.0, 0.0), center=(20, 0))

    assert orig is datum
    assert sorted((round(point_at_t(c, 0)[0], 9), round(point_at_t(c, 1)[0], 9))
                  for c in rest) == [(-10.0, 0.0), (40.0, 50.0)]


def test_trim_keeps_a_long_head_of_a_dense_polyline():
    """The keep test was in t: past 500 nodes, a crossing in the first 15 mm
    deleted the head with the clicked piece ("1 segment kept")."""
    n = 2000
    pts = [(0.0, 0.0)] + [(30.0 + 10 * math.sin(math.pi * k / (2 * n)),
                           10 - 10 * math.cos(math.pi * k / (2 * n))) for k in range(n + 1)]
    target = line(pts)
    cuts = [line([(20.0, -3), (20.0, 3)]), line([(25.0, -3), (25.0, 3)])]

    [(orig, rest)], _msgs = _trim([target] + cuts, (22.0, 0.0), center=(20, 0))

    assert orig is target and len(rest) == 2
    head, tail = sorted(rest, key=lambda c: c.nodes[0].x)
    (hs, he), (ts, _te) = _ends(head), _ends(tail)
    assert hs == (0.0, 0.0)
    assert math.dist(he, (20.0, 0.0)) < 1e-9 and math.dist(ts, (25.0, 0.0)) < 1e-9


def _dense_lens(n):
    return spline([(26 * math.cos(2 * math.pi * i / n), 19 * math.sin(2 * math.pi * i / n))
                   for i in range(n)], closed=True)


def test_a_click_on_a_dense_trace_does_not_resample_it_per_curve(monkeypatch):
    """A 2000-node trace among 100 far curves: 7.4 s a Trim click, every curve
    sampling the trace twice and each crossing found by a Python scan."""
    target = _dense_lens(2000)
    chord = line([(-40, 0.3), (40, 0.3)])
    far = [line([(100 + m, 0), (100 + m, 5)]) for m in range(100)]
    curves = [target, chord] + far
    scene = _scene_with(curves)
    view = _view(scene, center=(26, 0))

    calls = [0]
    real = G._bezier_eval

    def counted(*a):
        calls[0] += 1
        return real(*a)
    monkeypatch.setattr(G, "_bezier_eval", counted)

    from framedraft.tools.split import SplitTool
    from framedraft.tools.trim import TrimTool
    got = []
    trim = TrimTool()
    trim.trim_applied.connect(lambda orig, rest: got.append(rest))
    trim.activate(scene, view, lambda: curves)
    t0 = time.perf_counter()
    trim.handle_press(QPointF(26.0, 0.0))
    took = time.perf_counter() - t0
    assert len(got) == 1 and len(got[0]) == 1
    assert calls[0] < 5000, calls[0]          # was 6.4 million
    assert took < 1.0, took                    # generous: 50 ms here, 7.4 s before

    calls[0] = 0
    split = SplitTool()
    split.split_applied.connect(got.append)
    split.activate(scene, view, lambda: curves)
    split.handle_press(QPointF(26.0, 0.0))
    assert len(got) == 2
    assert calls[0] < 5000, calls[0]


def test_trim_says_when_a_curve_lies_on_its_copy():
    """Trimming one of two copied lenses removed a 2.3 mm sliver of it."""
    lens = closed_diamond(r=25.0)
    twin = copy.deepcopy(lens)
    got, msgs = _trim([lens, twin], point_at_t(lens, 0.3))
    assert got == []
    assert "lies on another along its whole length" in msgs[-1]


# ══════════════════════════════════════════ features under a millimeter


def test_a_line_across_both_arms_of_a_hairpin_crosses_it_twice():
    """Arms 0.4 mm apart: by their straight-line distance the two crossings
    merged into one, and Trim then cut between the wrong pair."""
    hairpin = line([(0, 0), (30, 0), (30, 0.4), (0, 0.4)])
    cut = line([(15, -3), (15, 3)])
    ts = dedup_ts_mm(hairpin, intersect_curve_params(hairpin, cut))
    assert sorted(round(point_at_t(hairpin, t)[1], 9) for t in ts) == [0.0, 0.4]


def test_a_small_circle_crossed_by_a_diameter_has_two_crossings():
    c = circle(0, 0, 0.2)
    ts = dedup_ts_mm(c, intersect_curve_params(c, line([(-1, 0), (1, 0)])))
    assert sorted(round(point_at_t(c, t)[0], 9) for t in ts) == [-0.2, 0.2]


def test_a_line_under_a_millimeter_can_be_cut_and_split():
    short = line([(0, 0), (0.4, 0)])
    [t] = intersect_curve_params(short, line([(0.2, -1), (0.2, 1)]))
    assert math.dist(point_at_t(short, t), (0.2, 0.0)) < 1e-9

    [pairs], _msgs = _split([short], (0.2, 0.0), center=(0.2, 0.0))

    [(orig, [left, right])] = pairs
    assert orig is short
    assert math.dist(point_at_t(left, 1.0), (0.2, 0.0)) < 1e-9


def test_a_short_overlap_on_a_straight_spline_run_meets_at_its_ends():
    """A straight run with its handles retracted is not uniform in t; the
    ends of a short overlap on it are placed on the curve, not by t."""
    from framedraft.document import Layer, SplineNode
    from framedraft.document import Curve
    box = Curve(kind="spline", layer=Layer.OUTLINE, closed=True,
                nodes=[SplineNode(x=x, y=y) for x, y in ((0, 0), (40, 0), (40, 20), (0, 20))])
    ref = line([(10, 0), (12, 0)])
    ts = dedup_ts_mm(box, intersect_curve_params(box, ref))
    assert sorted((round(x, 9), round(y, 9)) for x, y in
                  (point_at_t(box, t) for t in ts)) == [(10.0, 0.0), (12.0, 0.0)]
    tee = line([(25, -5), (25, 0)])                       # a T on the same run
    [t] = intersect_curve_params(box, tee)
    assert math.dist(point_at_t(box, t), (25.0, 0.0)) < 1e-9
