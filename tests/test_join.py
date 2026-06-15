"""Regression coverage for joining arcs/circles to lines.

The MainWindow join is Qt-coupled, but its fix hinges on a Qt-free invariant:
an arc converted with ``arc_to_spline`` must expose its true geometric
endpoints as the first/last nodes (the old bug read ``nodes[0]``/``nodes[-1]``
on an arc, which is only the centre, so endpoints never matched a line's end).
"""
import math

from framedraft.geometry import arc_to_spline, point_at_t
from helpers import arc, line


def test_arc_to_spline_exposes_endpoints_not_center():
    a = arc(0.0, 0.0, 10.0, 0.0, 90.0)          # centre (0,0), r=10
    sp = arc_to_spline(a)
    sx, sy = point_at_t(a, 0.0)
    ex, ey = point_at_t(a, 1.0)
    # First/last spline nodes are the arc endpoints, not the centre.
    assert math.hypot(sp.nodes[0].x - sx, sp.nodes[0].y - sy) < 1e-6
    assert math.hypot(sp.nodes[-1].x - ex, sp.nodes[-1].y - ey) < 1e-6
    assert (sp.nodes[0].x, sp.nodes[0].y) != (0.0, 0.0)   # not the centre


def test_line_meets_converted_arc_endpoint():
    # A line ending where the arc starts should now connect after conversion.
    sx, sy = point_at_t(arc(0.0, 0.0, 10.0, 0.0, 90.0), 0.0)   # (10, 0)
    ln = line([(-20.0, 0.0), (sx, sy)])
    sp = arc_to_spline(arc(0.0, 0.0, 10.0, 0.0, 90.0))
    gap = math.hypot(ln.nodes[-1].x - sp.nodes[0].x,
                     ln.nodes[-1].y - sp.nodes[0].y)
    assert gap < 1e-6
