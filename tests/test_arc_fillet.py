"""Geometry tests for the Start-End-Center arc and Fillet helpers."""
import math

import pytest

from framedraft.geometry import (
    arc_start_end_center, fillet_lines, point_at_t,
)
from framedraft.document import Curve, SplineNode, Layer


def _arc_curve(cx, cy, r, sa, ea):
    return Curve(kind="arc", layer=Layer.REF, nodes=[SplineNode(x=cx, y=cy)],
                 closed=False, radius=r, start_angle=sa, end_angle=ea)


# ---------------------------------------------------------------------------
# arc_start_end_center
# ---------------------------------------------------------------------------

def test_arc_sec_endpoints_lie_on_arc():
    # Quarter-ish arc: endpoints (10,0) and (0,10), centre near origin.
    res = arc_start_end_center(10.0, 0.0, 0.0, 10.0, 0.0, 0.0)
    assert res is not None
    cx, cy, r, sa, ea = res
    arc = _arc_curve(cx, cy, r, sa, ea)
    sx, sy = point_at_t(arc, 0.0)
    ex, ey = point_at_t(arc, 1.0)
    # Endpoints reproduced (arc may run either S->E or E->S; accept either).
    got = {(round(sx, 6), round(sy, 6)), (round(ex, 6), round(ey, 6))}
    assert (10.0, 0.0) in got and (0.0, 10.0) in got


def test_arc_sec_center_snapped_to_bisector():
    # Off-bisector clicked centre is projected onto the perpendicular bisector;
    # the chord midpoint here is (5,5) and the bisector is the line y=x.
    res = arc_start_end_center(10.0, 0.0, 0.0, 10.0, 3.0, 0.0)
    assert res is not None
    cx, cy, r, sa, ea = res
    assert cx == pytest.approx(cy, abs=1e-9)         # snapped onto y=x
    # equal radii to both endpoints
    assert math.hypot(10 - cx, 0 - cy) == pytest.approx(r, abs=1e-9)
    assert math.hypot(0 - cx, 10 - cy) == pytest.approx(r, abs=1e-9)


def test_arc_sec_center_side_flips_bulge():
    # Centre on opposite sides of the chord -> arcs bulge opposite ways, so
    # their midpoints straddle the chord midpoint.
    a = arc_start_end_center(-10.0, 0.0, 10.0, 0.0, 0.0, 8.0)
    b = arc_start_end_center(-10.0, 0.0, 10.0, 0.0, 0.0, -8.0)
    assert a and b
    mid_a = point_at_t(_arc_curve(*a), 0.5)
    mid_b = point_at_t(_arc_curve(*b), 0.5)
    assert mid_a[1] * mid_b[1] < 0     # one above, one below the chord (y=0)


def test_arc_sec_minor_arc():
    res = arc_start_end_center(10.0, 0.0, 0.0, 10.0, 0.0, 0.0)
    _, _, _, sa, ea = res
    assert (ea - sa) % 360 <= 180.0 + 1e-9


def test_arc_sec_degenerate():
    assert arc_start_end_center(5.0, 5.0, 5.0, 5.0, 0.0, 0.0) is None  # coincident


# ---------------------------------------------------------------------------
# fillet_lines
# ---------------------------------------------------------------------------

def test_fillet_right_angle():
    # Right-angle corner at origin; legs along +x and +y; r=5.
    res = fillet_lines((0.0, 0.0), (20.0, 0.0), (0.0, 20.0), 5.0)
    assert res is not None
    # For a 90° corner, tangent length == radius.
    assert res["tan_len"] == pytest.approx(5.0, abs=1e-9)
    assert res["t1"] == pytest.approx((5.0, 0.0), abs=1e-9)
    assert res["t2"] == pytest.approx((0.0, 5.0), abs=1e-9)
    assert res["center"] == pytest.approx((5.0, 5.0), abs=1e-9)
    # Tangent points are exactly r from the centre.
    for tp in (res["t1"], res["t2"]):
        assert math.hypot(tp[0] - res["center"][0],
                          tp[1] - res["center"][1]) == pytest.approx(5.0, abs=1e-9)


def test_fillet_arc_passes_tangent_points():
    res = fillet_lines((0.0, 0.0), (20.0, 0.0), (0.0, 20.0), 5.0)
    arc = _arc_curve(res["center"][0], res["center"][1], res["radius"],
                     res["start_deg"], res["end_deg"])
    p0 = point_at_t(arc, 0.0)
    p1 = point_at_t(arc, 1.0)
    pts = {(round(p0[0], 6), round(p0[1], 6)), (round(p1[0], 6), round(p1[1], 6))}
    assert (5.0, 0.0) in pts and (0.0, 5.0) in pts


def test_fillet_radius_too_large():
    # Legs only 3 mm long, but a right-angle fillet of r=5 needs tan_len=5.
    assert fillet_lines((0.0, 0.0), (3.0, 0.0), (0.0, 3.0), 5.0) is None


def test_fillet_collinear_legs():
    assert fillet_lines((0.0, 0.0), (10.0, 0.0), (-10.0, 0.0), 2.0) is None


def test_fillet_nonpositive_radius():
    assert fillet_lines((0.0, 0.0), (20.0, 0.0), (0.0, 20.0), 0.0) is None
