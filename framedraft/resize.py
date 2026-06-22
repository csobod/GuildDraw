"""
Auto-resize a locked lens to target boxing measurements (Qt-free).

A locked lens keeps its shape but is resized by typing new A/B boxing values.
``scale_curve_about`` returns a NEW curve scaled by (sx, sy) about a pivot;
``size_to_finished_ab`` works out the scale factors that make a lens's *finished*
(beveled) box hit the requested A/B and applies them about the nasal edge so the
DBL (nasal-edge spacing) is preserved — DBL is changed by moving the lens, not by
resizing.  Scene units are mm.
"""
from __future__ import annotations

import copy

from .boxing import lens_bbox
from .document import ControlPoint, Curve
from .geometry import arc_to_spline, circle_to_spline

_MIN_BARE_MM = 0.5   # never scale a finished target below this bare dimension


def scale_curve_about(curve: Curve, px: float, py: float,
                      sx: float, sy: float) -> Curve:
    """Return a copy of *curve* scaled by (sx, sy) about pivot (px, py).

    A non-uniform scale turns a circle/arc into an ellipse, which the primitive
    can't represent, so it is converted to a spline first (same rule as the
    Transform dialog)."""
    uniform = abs(sx - sy) < 1e-9
    c = curve
    if c.kind in ("circle", "arc") and not uniform:
        c = circle_to_spline(c) if c.kind == "circle" else arc_to_spline(c)

    def xf(x: float, y: float) -> tuple[float, float]:
        return (px + (x - px) * sx, py + (y - py) * sy)

    if c.kind in ("circle", "arc"):
        c = copy.deepcopy(c)
        c.nodes[0].x, c.nodes[0].y = xf(c.nodes[0].x, c.nodes[0].y)
        c.radius = (c.radius or 0.0) * abs(sx)
        return c

    c = copy.deepcopy(c)
    for n in c.nodes:
        n.x, n.y = xf(n.x, n.y)
        if n.cp_in:
            n.cp_in = ControlPoint(*xf(n.cp_in.x, n.cp_in.y))
        if n.cp_out:
            n.cp_out = ControlPoint(*xf(n.cp_out.x, n.cp_out.y))
    return c


def size_to_finished_ab(curve: Curve, target_a: float | None, target_b: float | None,
                        bevel_depth: float, axis_x: float = 0.0) -> Curve | None:
    """Resize *curve* so its FINISHED (beveled) box hits the given target(s).

    Pass ``None`` for an axis to leave it untouched — so changing only A never
    perturbs B (and vice versa).  The bare-shape target is the finished target
    minus 2·bevel.  The horizontal scale pivots on the **nasal edge** (bbox edge
    nearest *axis_x*) so the DBL is preserved; the vertical scale pivots on the
    box centre.  Returns a new curve, or None if nothing changes.
    """
    bb = lens_bbox(curve)
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    cur_a = x1 - x0
    cur_b = y1 - y0
    d = max(0.0, bevel_depth)

    sx = sy = 1.0
    if target_a is not None and cur_a > 1e-9:
        sx = max(_MIN_BARE_MM, target_a - 2 * d) / cur_a
    if target_b is not None and cur_b > 1e-9:
        sy = max(_MIN_BARE_MM, target_b - 2 * d) / cur_b
    if abs(sx - 1.0) < 1e-9 and abs(sy - 1.0) < 1e-9:
        return None   # no effective change

    # Nasal edge = the bbox edge closest to the mirror axis (preserves DBL).
    box_cx = (x0 + x1) / 2
    pivot_x = x0 if box_cx >= axis_x else x1
    pivot_y = (y0 + y1) / 2
    return scale_curve_about(curve, pivot_x, pivot_y, sx, sy)
