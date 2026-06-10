"""geometry.mirror_curve — the single mirror transform used by scene ghosts,
DXF export, Mirror (bake), Temple Copy, and draw-tool previews.

Reflection invariant: the mirrored curve's point set must equal the reflection
of the original's point set (orientation may reverse, so compare as sets).
"""
import math

import pytest

from framedraft.geometry import mirror_curve, sample_curve
from helpers import line, spline, circle, arc


def reflect(pt, axis_x=0.0, horizontal=False):
    x, y = pt
    if horizontal:
        return (x, -y)
    return (2.0 * axis_x - x, y)


def assert_point_sets_match(mirrored, original, axis_x=0.0, horizontal=False,
                            tol=1e-6):
    """Every reflected sample of the original lies on the mirrored curve."""
    m_pts = [(x, y) for x, y, _ in sample_curve(mirrored, 32)]
    for x, y, _ in sample_curve(original, 32):
        rx, ry = reflect((x, y), axis_x, horizontal)
        d = min(math.hypot(rx - mx, ry - my) for mx, my in m_pts)
        assert d < 0.05, f"reflected point ({rx:.3f},{ry:.3f}) missing (d={d:.3f})"


@pytest.mark.parametrize("horizontal", [False, True])
def test_line_nodes_reflect_exactly(horizontal):
    c = line([(1, 2), (10, 5), (12, -3)])
    m = mirror_curve(c, axis_x=4.0, horizontal=horizontal)
    for n, o in zip(m.nodes, c.nodes, strict=True):
        assert (n.x, n.y) == reflect((o.x, o.y), 4.0, horizontal)
    assert m.kind == "line" and m.closed == c.closed


@pytest.mark.parametrize("horizontal", [False, True])
def test_spline_handles_reflect(horizontal):
    c = spline([(0, 0), (10, 8), (20, 0)])
    m = mirror_curve(c, axis_x=2.0, horizontal=horizontal)
    for n, o in zip(m.nodes, c.nodes, strict=True):
        assert (n.cp_in.x, n.cp_in.y) == reflect((o.cp_in.x, o.cp_in.y), 2.0, horizontal)
        assert (n.cp_out.x, n.cp_out.y) == reflect((o.cp_out.x, o.cp_out.y), 2.0, horizontal)
    assert_point_sets_match(m, c, 2.0, horizontal)


def test_circle_reflects_center_keeps_radius():
    c = circle(7, 3, 5)
    m = mirror_curve(c, axis_x=2.0)
    assert (m.nodes[0].x, m.nodes[0].y) == (-3, 3) and m.radius == 5
    mh = mirror_curve(c, horizontal=True)
    assert (mh.nodes[0].x, mh.nodes[0].y) == (7, -3)


@pytest.mark.parametrize("horizontal", [False, True])
@pytest.mark.parametrize("angles", [(0, 90), (30, 200), (300, 60)])
def test_arc_point_set_is_reflected(angles, horizontal):
    c = arc(4, -2, 10, *angles)
    m = mirror_curve(c, axis_x=1.0, horizontal=horizontal)
    assert m.kind == "arc" and m.radius == 10
    assert_point_sets_match(m, c, 1.0, horizontal)
    # endpoints map onto each other (as a set — sweep direction may swap)
    def ends(cv):
        pts = [(x, y) for x, y, _ in sample_curve(cv, 8)]
        return {tuple(round(v, 4) for v in pts[0]),
                tuple(round(v, 4) for v in pts[-1])}
    expected = {tuple(round(v, 4) for v in reflect(p, 1.0, horizontal))
                for p in ends(c)}
    assert ends(m) == expected


def test_mirror_preserves_metadata():
    c = spline([(0, 0), (10, 8), (20, 0)], closed=False)
    c.line_weight = 2.5
    m = mirror_curve(c, axis_x=0.0)
    assert m.line_weight == 2.5
    assert m.layer == c.layer
    assert m.mirrored is False     # result is real geometry, not a ghost
    assert m.nodes is not c.nodes  # deep, not aliased


def test_double_mirror_is_identity():
    c = spline([(2, 1), (8, 6), (14, -2)])
    mm = mirror_curve(mirror_curve(c, axis_x=3.0), axis_x=3.0)
    for n, o in zip(mm.nodes, c.nodes, strict=True):
        assert math.hypot(n.x - o.x, n.y - o.y) < 1e-9
