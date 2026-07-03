"""
Boxing-system math (Qt-free).

The boxing system measures a *finished* lens — including its bevel — even though
the frame is drawn from the bare lens-material shape.  These helpers turn a LENS
``Curve`` plus a bevel depth into the finished bounding box (for A/B/DBL) and the
bevel-offset outline (the "full lens depth" guide line the BoxingGuide draws).

Everything is derived from the *sampled* curve via Shapely so the box hugs the
true visible shape (not control-point extents) and the bevel offset stays clean
on complex / concave lens curves.  Scene units are mm.
"""
from __future__ import annotations

import shapely.geometry as _sg

from .document import Curve
from .geometry import point_at_t

_SAMPLES = 256       # polygon sample points around the curve
_JOIN_ROUND = 1      # shapely round join — smooth offset, no mitre spikes


def lens_polygon(curve: Curve):
    """Shapely polygon of the sampled curve (validity-repaired)."""
    n = _SAMPLES
    pts = [point_at_t(curve, i / n) for i in range(n + 1)]
    poly = _sg.Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def lens_bbox(curve: Curve) -> tuple[float, float, float, float] | None:
    """True (min_x, min_y, max_x, max_y) of a lens curve, from its sampled shape."""
    poly = lens_polygon(curve)
    if poly.is_empty:
        return None
    return poly.bounds


def union_bbox(curves) -> tuple[float, float, float, float] | None:
    """Sampled bounding box over several curves (same basis as the boxing guide
    and the resizer, so measurements / box / resize never disagree)."""
    boxes = [lens_bbox(c) for c in curves if c.nodes]
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def finished_box(curve: Curve, depth_mm: float) -> tuple[float, float, float, float] | None:
    """Bounding box of the finished (beveled) lens = the sampled shape grown
    outward by *depth_mm*.  ``depth_mm <= 0`` returns the bare bbox."""
    poly = lens_polygon(curve)
    if poly.is_empty:
        return None
    if depth_mm and depth_mm > 0:
        poly = poly.buffer(depth_mm, join_style=_JOIN_ROUND)
        if poly.is_empty:
            return None
    return poly.bounds


def bevel_outline_points(curve: Curve, depth_mm: float) -> list[tuple[float, float]] | None:
    """Polyline points of the lens offset OUTWARD by *depth_mm* — the finished-lens
    ("full depth") guide outline.  Returns None when there is no bevel.

    Shapely ``buffer`` with a positive distance always expands outward, so the
    result is correct regardless of node winding and clean on concave shapes.
    """
    if not depth_mm or depth_mm <= 0:
        return None
    poly = lens_polygon(curve)
    if poly.is_empty:
        return None
    buf = poly.buffer(depth_mm, join_style=_JOIN_ROUND)
    if buf.is_empty:
        return None
    if buf.geom_type == "MultiPolygon":
        buf = max(buf.geoms, key=lambda g: g.area)
    return [(float(x), float(y)) for x, y in buf.exterior.coords]


def finished_geometry(curve: Curve, depth_mm: float
                      ) -> tuple[tuple[float, float, float, float] | None,
                                 list[tuple[float, float]] | None]:
    """(finished bbox, bevel outline points) in ONE buffer pass.

    Equivalent to ``(finished_box(c, d), bevel_outline_points(c, d))`` but
    builds the sampled polygon and its outward buffer once — the snapped
    boxing guide calls this per lens on every live geometry change.
    The outline is None when depth <= 0 (no bevel to draw).
    """
    poly = lens_polygon(curve)
    if poly.is_empty:
        return None, None
    if not depth_mm or depth_mm <= 0:
        return poly.bounds, None
    buf = poly.buffer(depth_mm, join_style=_JOIN_ROUND)
    if buf.is_empty:
        return None, None
    bounds = buf.bounds
    if buf.geom_type == "MultiPolygon":
        buf = max(buf.geoms, key=lambda g: g.area)
    return bounds, [(float(x), float(y)) for x, y in buf.exterior.coords]


def finished_ab(shape_a: float, shape_b: float, depth_mm: float) -> tuple[float, float]:
    """Finished A/B = bare-shape A/B grown by 2·depth (depth on each side)."""
    d = max(0.0, depth_mm)
    return shape_a + 2 * d, shape_b + 2 * d


def finished_dbl(shape_dbl: float, depth_mm: float) -> float:
    """Finished DBL = bare-shape DBL minus 2·depth — the beveled nasal edges sit
    *depth* closer to centre than the bare-material edges, narrowing the gap."""
    return shape_dbl - 2 * max(0.0, depth_mm)
