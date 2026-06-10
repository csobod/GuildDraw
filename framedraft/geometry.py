"""
Shared geometry helpers for Trim and Split tools.

Curve parameterisation: t in [0.0, 1.0].
  t=0 = curve start, t=1 = curve end (same physical point as t=0 for closed
  curves/circles).

  For spline/line with N nodes:
    open   — N-1 segments; segment i covers t in [i/(N-1), (i+1)/(N-1)]
    closed — N  segments; last segment connects nodes[-1] back to nodes[0]

  Circle : t maps to angle 0 -> 360 deg (atan2 scene convention, 0=right,
           90=down-screen).  extract_open_segment uses start=t*360,
           end=t*360 so the modulo in the arc sweep formula handles wrapping
           automatically.

  Arc    : t in [0,1] spans linearly from start_angle to end_angle.
"""

from __future__ import annotations
import math
from typing import List, Tuple

from .document import Curve, SplineNode, ControlPoint

import shapely.geometry as _sg

_SAMPLES_PER_SEG = 16   # polyline samples per Bezier segment
_DEDUP_TOL_MM    = 0.5  # intersection points closer than this (mm) merge as one
_END_TOL_MM      = 0.25 # intersections/splits this close (mm) to an endpoint are ignored


# ---------------------------------------------------------------------------
# Low-level Bezier helpers
# ---------------------------------------------------------------------------

def _seg_pts(a: SplineNode, b: SplineNode):
    """Return (p0, p1, p2, p3) control points for spline segment a->b."""
    p0 = (a.x, a.y)
    p1 = (a.cp_out.x, a.cp_out.y) if a.cp_out else p0
    p2 = (b.cp_in.x,  b.cp_in.y)  if b.cp_in  else (b.x, b.y)
    p3 = (b.x, b.y)
    return p0, p1, p2, p3


def _bezier_eval(p0, p1, p2, p3, t: float) -> Tuple[float, float]:
    u = 1.0 - t
    return (
        u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0],
        u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1],
    )


def split_bezier_at_t(p0, p1, p2, p3, t: float):
    """
    De Casteljau split at t in [0, 1].
    Returns (left, right) as lists of 4 (x, y) points.
    """
    def _l(a, b, s): return (a[0]*(1-s)+b[0]*s, a[1]*(1-s)+b[1]*s)
    q0 = _l(p0, p1, t); q1 = _l(p1, p2, t); q2 = _l(p2, p3, t)
    r0 = _l(q0, q1, t); r1 = _l(q1, q2, t)
    m  = _l(r0, r1, t)
    return [p0, q0, r0, m], [m, r1, q2, p3]


def _copy_node(n: SplineNode) -> SplineNode:
    nn = SplineNode(x=n.x, y=n.y)
    if n.cp_in:
        nn.cp_in  = ControlPoint(n.cp_in.x,  n.cp_in.y)
    if n.cp_out:
        nn.cp_out = ControlPoint(n.cp_out.x, n.cp_out.y)
    return nn


# ---------------------------------------------------------------------------
# Parameterisation helpers
# ---------------------------------------------------------------------------

def _n_segs(curve: Curve) -> int:
    """Total number of segments in the curve."""
    n = len(curve.nodes)
    if curve.kind in ("circle", "arc"):
        return 1
    return n if curve.closed else max(n - 1, 0)


def _seg_nodes(curve: Curve, seg: int):
    """Return (node_a, node_b) for segment index seg."""
    nodes = curve.nodes
    return nodes[seg], nodes[(seg + 1) % len(nodes)]


def point_at_t(curve: Curve, t: float) -> Tuple[float, float]:
    """Evaluate the curve exactly at parameter t in [0, 1] (no sampling)."""
    t = max(0.0, min(1.0, t))
    nodes = curve.nodes

    if curve.kind == "circle":
        cx, cy, r = nodes[0].x, nodes[0].y, curve.radius or 0.0
        a = 2 * math.pi * t
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    if curve.kind == "arc":
        cx, cy, r = nodes[0].x, nodes[0].y, curve.radius or 0.0
        sa = math.radians(curve.start_angle or 0.0)
        sw = math.radians(((curve.end_angle or 0.0) - (curve.start_angle or 0.0)) % 360)
        a  = sa + sw * t
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    if not nodes:
        return (0.0, 0.0)
    ns = _n_segs(curve)
    if ns == 0:
        return (nodes[0].x, nodes[0].y)

    scaled = t * ns
    seg    = min(int(scaled), ns - 1)
    local  = scaled - seg
    a, b   = _seg_nodes(curve, seg)
    if curve.kind == "spline":
        p0, p1, p2, p3 = _seg_pts(a, b)
        return _bezier_eval(p0, p1, p2, p3, local)
    return (a.x + (b.x - a.x) * local, a.y + (b.y - a.y) * local)


def arc_bbox(cx: float, cy: float, r: float,
             start_deg: float, end_deg: float
             ) -> Tuple[float, float, float, float]:
    """True (min_x, min_y, max_x, max_y) extents of an arc.

    Angles use the scene atan2 convention (degrees; 0=right, 90=down-screen);
    the sweep runs from start_deg to end_deg in the positive direction (mod 360),
    matching build_path and sample_curve.
    """
    sweep = (end_deg - start_deg) % 360
    if sweep < 1e-9:
        sweep = 360.0
    pts = []
    for a in (start_deg, end_deg):
        rad = math.radians(a)
        pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
    for q in (0.0, 90.0, 180.0, 270.0):
        if ((q - start_deg) % 360) <= sweep:
            rad = math.radians(q)
            pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


_KAPPA = 0.5522847498307936   # 4/3·tan(π/8): cubic Bézier quarter-circle constant


def circle_to_spline(curve: Curve) -> Curve:
    """4-segment closed cubic-Bézier approximation of a circle (≤0.028% error).

    Used when a non-uniform scale would turn the circle into an ellipse,
    which the circle primitive cannot represent.
    """
    cx, cy = curve.nodes[0].x, curve.nodes[0].y
    r = curve.radius or 0.0
    k = _KAPPA * r
    nodes = []
    for ang in (0.0, 90.0, 180.0, 270.0):
        a = math.radians(ang)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        tx, ty = -math.sin(a), math.cos(a)   # unit tangent, increasing angle
        n = SplineNode(x=x, y=y)
        n.cp_out = ControlPoint(x + tx * k, y + ty * k)
        n.cp_in  = ControlPoint(x - tx * k, y - ty * k)
        nodes.append(n)
    return Curve(kind="spline", layer=curve.layer, nodes=nodes, closed=True,
                 line_weight=curve.line_weight, group_id=curve.group_id)


def arc_to_spline(curve: Curve) -> Curve:
    """Open cubic-Bézier approximation of an arc (≤90° per segment)."""
    cx, cy = curve.nodes[0].x, curve.nodes[0].y
    r  = curve.radius or 0.0
    sa = curve.start_angle or 0.0
    sweep = ((curve.end_angle or 0.0) - sa) % 360
    if sweep < 1e-9:
        sweep = 360.0
    nseg = max(1, int(math.ceil(sweep / 90.0)))
    step = math.radians(sweep / nseg)
    k = (4.0 / 3.0) * math.tan(step / 4.0) * r
    nodes = []
    a0 = math.radians(sa)
    for i in range(nseg + 1):
        a = a0 + step * i
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        tx, ty = -math.sin(a), math.cos(a)
        n = SplineNode(x=x, y=y)
        n.cp_out = ControlPoint(x + tx * k, y + ty * k)
        n.cp_in  = ControlPoint(x - tx * k, y - ty * k)
        nodes.append(n)
    nodes[0].cp_in   = None
    nodes[-1].cp_out = None
    return Curve(kind="spline", layer=curve.layer, nodes=nodes, closed=False,
                 line_weight=curve.line_weight, group_id=curve.group_id)


def mirror_curve(curve: Curve, axis_x: float = 0.0,
                 horizontal: bool = False) -> Curve:
    """Reflect *curve* across the mirror axis, returning a new independent Curve.

    horizontal=False: vertical axis at x = axis_x (front / hinge workspaces).
    horizontal=True : horizontal axis at y = 0 (temple workspaces); axis_x unused.

    Single source of truth for mirror math — used by scene ghosts, DXF export,
    Mirror (bake), Temple Copy, and draw-tool preview ghosts. The result is
    plain geometry (mirrored=False); callers decide its role.
    """
    def mp(x: float, y: float) -> Tuple[float, float]:
        if horizontal:
            return x, -y
        return 2.0 * axis_x - x, y

    if curve.kind == "circle":
        cx, cy = mp(curve.nodes[0].x, curve.nodes[0].y)
        return Curve(kind="circle", layer=curve.layer,
                     nodes=[SplineNode(x=cx, y=cy)], closed=curve.closed,
                     radius=curve.radius, line_weight=curve.line_weight)

    if curve.kind == "arc":
        cx, cy = mp(curve.nodes[0].x, curve.nodes[0].y)
        # Reflection reverses the sweep direction, so start/end swap.
        sa, ea = curve.start_angle, curve.end_angle
        if horizontal:   # y-flip: angle θ → −θ
            new_start = (-ea) % 360 if ea is not None else None
            new_end   = (-sa) % 360 if sa is not None else None
        else:            # x-flip: angle θ → 180 − θ
            new_start = (180.0 - ea) % 360 if ea is not None else None
            new_end   = (180.0 - sa) % 360 if sa is not None else None
        return Curve(kind="arc", layer=curve.layer,
                     nodes=[SplineNode(x=cx, y=cy)], closed=curve.closed,
                     radius=curve.radius,
                     start_angle=new_start, end_angle=new_end,
                     line_weight=curve.line_weight)

    mirrored: List[SplineNode] = []
    for n in curve.nodes:
        x, y = mp(n.x, n.y)
        mn = SplineNode(x=x, y=y)
        if n.cp_in:
            ix, iy = mp(n.cp_in.x, n.cp_in.y)
            mn.cp_in = ControlPoint(ix, iy)
        if n.cp_out:
            ox, oy = mp(n.cp_out.x, n.cp_out.y)
            mn.cp_out = ControlPoint(ox, oy)
        mirrored.append(mn)
    return Curve(kind=curve.kind, layer=curve.layer, nodes=mirrored,
                 closed=curve.closed, line_weight=curve.line_weight)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def sample_curve(curve: Curve,
                 n_per_seg: int = _SAMPLES_PER_SEG
                 ) -> List[Tuple[float, float, float]]:
    """
    Return [(x, y, t), ...] with t in [0, 1] uniformly along the curve.
    Includes both endpoints for open curves.
    """
    result: List[Tuple[float, float, float]] = []
    nodes = curve.nodes

    if curve.kind == "circle":
        cx, cy, r = nodes[0].x, nodes[0].y, curve.radius or 0.0
        n = n_per_seg * 8
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            result.append((cx + r*math.cos(a), cy + r*math.sin(a), i / n))
        return result

    if curve.kind == "arc":
        cx, cy, r = nodes[0].x, nodes[0].y, curve.radius or 0.0
        sa  = math.radians(curve.start_angle or 0.0)
        sw  = math.radians((curve.end_angle - curve.start_angle) % 360)
        n   = max(n_per_seg, int(math.degrees(abs(sw)) / 5))
        for i in range(n + 1):
            a = sa + sw * i / n
            result.append((cx + r*math.cos(a), cy + r*math.sin(a), i / n))
        return result

    if not nodes or len(nodes) < 2:
        if nodes:
            result.append((nodes[0].x, nodes[0].y, 0.0))
        return result

    ns = _n_segs(curve)
    if ns == 0:
        return result

    for seg_i in range(ns):
        a, b = _seg_nodes(curve, seg_i)
        is_last = (seg_i == ns - 1)
        n_pts   = n_per_seg   # same density for both spline and line
        count   = n_pts + (1 if is_last else 0)
        for j in range(count):
            local_t  = j / n_pts
            global_t = (seg_i + local_t) / ns
            if curve.kind == "spline":
                p0, p1, p2, p3 = _seg_pts(a, b)
                x, y = _bezier_eval(p0, p1, p2, p3, local_t)
            else:
                x = a.x + (b.x - a.x) * local_t
                y = a.y + (b.y - a.y) * local_t
            result.append((x, y, global_t))

    return result


def t_nearest(curve: Curve, px: float, py: float) -> float:
    """Return the t in [0, 1] of the sample point nearest to (px, py)."""
    best_t  = 0.0
    best_d2 = float("inf")
    for x, y, t in sample_curve(curve, n_per_seg=_SAMPLES_PER_SEG * 2):
        d2 = (x - px)**2 + (y - py)**2
        if d2 < best_d2:
            best_d2 = d2
            best_t  = t
    return best_t


# ---------------------------------------------------------------------------
# Shapely conversion + intersection
# ---------------------------------------------------------------------------

def curve_to_shapely(curve: Curve):
    """Convert curve to a Shapely geometry for intersection queries, or None."""
    pts = [(x, y) for x, y, _ in sample_curve(curve, _SAMPLES_PER_SEG)]
    if len(pts) < 2:
        return None
    try:
        if curve.kind == "circle" or curve.closed:
            return _sg.LinearRing(pts)
        return _sg.LineString(pts)
    except Exception:
        return None


def _iter_shapely_pts(geom):
    """Yield shapely Points from any Shapely geometry."""
    if geom is None or geom.is_empty:
        return
    gtype = geom.geom_type
    if gtype == "Point":
        yield geom
    elif gtype in ("MultiPoint", "GeometryCollection",
                   "MultiLineString", "MultiPolygon"):
        for g in geom.geoms:
            yield from _iter_shapely_pts(g)
    elif gtype == "LineString":
        # Overlapping collinear segment — sample a few midpoints
        coords = list(geom.coords)
        step = max(1, len(coords) // 4)
        for x, y in coords[::step]:
            yield _sg.Point(x, y)


def intersect_curve_params(target: Curve, other: Curve,
                           end_tol_mm: float = _END_TOL_MM) -> List[float]:
    """
    Return t values on `target` where it intersects `other`.

    For open curves, intersections within end_tol_mm (scene mm) of either
    endpoint are dropped — they are trivial endpoint touches, not crossings.
    Closed curves keep all intersections (t≈0/1 is the seam, a real point).
    """
    ga = curve_to_shapely(target)
    gb = curve_to_shapely(other)
    if ga is None or gb is None:
        return []
    try:
        inter = ga.intersection(gb)
    except Exception:
        return []

    is_closed = target.closed or target.kind == "circle"
    if not is_closed:
        sx, sy = point_at_t(target, 0.0)
        ex, ey = point_at_t(target, 1.0)

    ts = []
    for pt in _iter_shapely_pts(inter):
        if not is_closed:
            if (math.hypot(pt.x - sx, pt.y - sy) <= end_tol_mm
                    or math.hypot(pt.x - ex, pt.y - ey) <= end_tol_mm):
                continue
        ts.append(t_nearest(target, pt.x, pt.y))
    return ts


def dedup_ts_mm(curve: Curve, ts: List[float],
                tol_mm: float = _DEDUP_TOL_MM) -> List[float]:
    """Merge t values whose points on *curve* are within tol_mm (scene mm).

    Distance is measured in mm rather than t-space so the tolerance does not
    grow with the number of segments in the curve.  For closed curves the
    first and last survivors are also compared across the t=0/1 seam.
    """
    if not ts:
        return []
    ts  = sorted(ts)
    out = [ts[0]]
    for t in ts[1:]:
        x0, y0 = point_at_t(curve, out[-1])
        x1, y1 = point_at_t(curve, t)
        if math.hypot(x1 - x0, y1 - y0) > tol_mm:
            out.append(t)
    if (curve.closed or curve.kind == "circle") and len(out) > 1:
        x0, y0 = point_at_t(curve, out[0])
        x1, y1 = point_at_t(curve, out[-1])
        if math.hypot(x1 - x0, y1 - y0) <= tol_mm:
            out.pop()
    return out


# ---------------------------------------------------------------------------
# Segment extraction — spline
# ---------------------------------------------------------------------------

def _extract_spline_segment(curve: Curve,
                             t_start: float,
                             t_end: float) -> Curve:
    """
    Extract [t_start, t_end] from an open or closed spline as a new open spline.
    Assumes t_start < t_end and both are in [0, 1].
    """
    ns = _n_segs(curve)

    def _seg_local(t):
        scaled = t * ns
        seg    = min(int(scaled), ns - 1)
        return seg, scaled - seg

    seg_s, local_s = _seg_local(t_start)
    seg_e, local_e = _seg_local(t_end)
    # Force t_end == 1.0 exactly to the final segment end
    if t_end >= 1.0 - 1e-9:
        seg_e, local_e = ns - 1, 1.0

    result: List[SplineNode] = []

    if seg_s == seg_e:
        a, b = _seg_nodes(curve, seg_s)
        p0, p1, p2, p3 = _seg_pts(a, b)
        if local_s < 1e-9 and local_e > 1 - 1e-9:
            result = [_copy_node(a), _copy_node(b)]
        elif local_s < 1e-9:
            left, _ = split_bezier_at_t(p0, p1, p2, p3, local_e)
            sn = SplineNode(x=left[0][0], y=left[0][1]); sn.cp_out = ControlPoint(*left[1])
            en = SplineNode(x=left[3][0], y=left[3][1]); en.cp_in  = ControlPoint(*left[2])
            result = [sn, en]
        elif local_e > 1 - 1e-9:
            _, rgt = split_bezier_at_t(p0, p1, p2, p3, local_s)
            sn = SplineNode(x=rgt[0][0], y=rgt[0][1]); sn.cp_out = ControlPoint(*rgt[1])
            en = SplineNode(x=rgt[3][0], y=rgt[3][1]); en.cp_in  = ControlPoint(*rgt[2])
            result = [sn, en]
        else:
            _, rgt  = split_bezier_at_t(p0, p1, p2, p3, local_s)
            adj_e   = (local_e - local_s) / (1.0 - local_s)
            left2, _ = split_bezier_at_t(rgt[0], rgt[1], rgt[2], rgt[3], adj_e)
            sn = SplineNode(x=left2[0][0], y=left2[0][1]); sn.cp_out = ControlPoint(*left2[1])
            en = SplineNode(x=left2[3][0], y=left2[3][1]); en.cp_in  = ControlPoint(*left2[2])
            result = [sn, en]
    else:
        # ---- start node (right half of segment seg_s) ----
        a_s, b_s = _seg_nodes(curve, seg_s)
        p0s, p1s, p2s, p3s = _seg_pts(a_s, b_s)
        if local_s < 1e-9:
            sn = _copy_node(a_s)
            adj_b_cp_in = b_s.cp_in  # unchanged
        else:
            _, rgt = split_bezier_at_t(p0s, p1s, p2s, p3s, local_s)
            sn = SplineNode(x=rgt[0][0], y=rgt[0][1])
            sn.cp_out    = ControlPoint(*rgt[1])
            adj_b_cp_in  = ControlPoint(*rgt[2])
        result.append(sn)

        # adjusted copy of b_s (= nodes[seg_s+1])
        n_s1 = SplineNode(x=b_s.x, y=b_s.y)
        n_s1.cp_in  = (ControlPoint(adj_b_cp_in.x, adj_b_cp_in.y)
                       if adj_b_cp_in else None)
        n_s1.cp_out = (ControlPoint(b_s.cp_out.x, b_s.cp_out.y)
                       if b_s.cp_out else None)
        result.append(n_s1)

        # ---- middle nodes: the B-end of each fully-contained segment ----
        for i in range(seg_s + 1, seg_e):
            _, nb = _seg_nodes(curve, i)
            result.append(_copy_node(nb))

        # ---- end node (left half of segment seg_e) ----
        a_e, b_e = _seg_nodes(curve, seg_e)
        p0e, p1e, p2e, p3e = _seg_pts(a_e, b_e)
        if local_e > 1 - 1e-9:
            result.append(_copy_node(b_e))
        elif local_e < 1e-9:
            # End exactly at the start of segment seg_e = result[-1] is already
            # that node; just clear its outgoing handle (it's now an endpoint)
            result[-1].cp_out = None
        else:
            left_e, _ = split_bezier_at_t(p0e, p1e, p2e, p3e, local_e)
            result[-1].cp_out = ControlPoint(*left_e[1])
            en = SplineNode(x=left_e[3][0], y=left_e[3][1])
            en.cp_in = ControlPoint(*left_e[2])
            result.append(en)

    return Curve(kind="spline", layer=curve.layer, nodes=result,
                 closed=False, line_weight=curve.line_weight)


# ---------------------------------------------------------------------------
# Segment extraction — line
# ---------------------------------------------------------------------------

def _extract_line_segment(curve: Curve,
                           t_start: float,
                           t_end: float) -> Curve:
    nodes = curve.nodes
    ns    = _n_segs(curve)

    def _pt(t):
        scaled = t * ns
        seg    = min(int(scaled), ns - 1)
        local  = scaled - seg
        a, b   = _seg_nodes(curve, seg)
        return SplineNode(x=a.x + (b.x-a.x)*local, y=a.y + (b.y-a.y)*local)

    new_nodes = [_pt(t_start)]
    for i, n in enumerate(nodes):
        t_i = i / ns if ns > 0 else 0.0
        if t_start + 1e-9 < t_i < t_end - 1e-9:
            new_nodes.append(_copy_node(n))
    new_nodes.append(_pt(t_end))

    return Curve(kind="line", layer=curve.layer, nodes=new_nodes,
                 closed=False, line_weight=curve.line_weight)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_open_segment(curve: Curve,
                          t_start: float,
                          t_end: float) -> Curve:
    """
    Extract an open sub-curve spanning [t_start, t_end].

    For circles and arcs the angle formula handles wrapping automatically
    (the stored sweep formula uses modulo), so passing t_start > t_end is
    valid and produces the arc that wraps around the 0/360 boundary.

    For spline/line, t_start must be <= t_end; use extract_wrapping_segment
    for the crossing case.
    """
    t_start = max(0.0, min(1.0, t_start))
    t_end   = max(0.0, min(1.0, t_end))

    if curve.kind == "circle":
        cx, cy = curve.nodes[0].x, curve.nodes[0].y
        return Curve(kind="arc", layer=curve.layer,
                     nodes=[SplineNode(x=cx, y=cy)], closed=False,
                     radius=curve.radius,
                     start_angle=t_start * 360.0,
                     end_angle=t_end * 360.0,
                     line_weight=curve.line_weight)

    if curve.kind == "arc":
        sweep = (curve.end_angle - curve.start_angle) % 360
        sa = curve.start_angle + t_start * sweep
        ea = curve.start_angle + t_end   * sweep
        cx, cy = curve.nodes[0].x, curve.nodes[0].y
        return Curve(kind="arc", layer=curve.layer,
                     nodes=[SplineNode(x=cx, y=cy)], closed=False,
                     radius=curve.radius,
                     start_angle=sa, end_angle=ea,
                     line_weight=curve.line_weight)

    if curve.kind == "line":
        return _extract_line_segment(curve, t_start, t_end)

    return _extract_spline_segment(curve, t_start, t_end)


def extract_wrapping_segment(curve: Curve,
                              t_start: float,
                              t_end: float) -> Curve:
    """
    Extract the segment that crosses the t=0/t=1 seam on a closed curve.
    t_start > t_end: the arc runs [t_start, 1] then [0, t_end].

    For circles/arcs, delegate to extract_open_segment (modulo handles it).
    For spline/line, concatenate the two pieces and merge at the seam node.
    """
    if curve.kind in ("circle", "arc"):
        return extract_open_segment(curve, t_start, t_end)

    seg_hi = extract_open_segment(curve, t_start, 1.0)
    seg_lo = extract_open_segment(curve, 0.0,     t_end)

    if curve.kind == "line":
        combined = seg_hi.nodes[:-1] + seg_lo.nodes
        return Curve(kind="line", layer=curve.layer, nodes=combined,
                     closed=False, line_weight=curve.line_weight)

    # spline: merge seam at the original nodes[0] position
    hi_end   = seg_hi.nodes[-1]
    lo_start = seg_lo.nodes[0]
    seam     = SplineNode(x=hi_end.x, y=hi_end.y)
    seam.cp_in  = hi_end.cp_in
    seam.cp_out = lo_start.cp_out
    combined    = seg_hi.nodes[:-1] + [seam] + seg_lo.nodes[1:]
    return Curve(kind="spline", layer=curve.layer, nodes=combined,
                 closed=False, line_weight=curve.line_weight)


def split_curve_at_t(curve: Curve,
                     t: float,
                     end_tol_mm: float = _END_TOL_MM):
    """
    Split curve at t in (0, 1) into (left, right) open curves.
    Returns (curve, None) if the split point is within end_tol_mm (scene mm)
    of either endpoint — a split there would create a degenerate sliver.
    """
    if t <= 0.0 or t >= 1.0:
        return curve, None
    px, py = point_at_t(curve, t)
    sx, sy = point_at_t(curve, 0.0)
    ex, ey = point_at_t(curve, 1.0)
    if (math.hypot(px - sx, py - sy) <= end_tol_mm
            or math.hypot(px - ex, py - ey) <= end_tol_mm):
        return curve, None
    left  = extract_open_segment(curve, 0.0, t)
    right = extract_open_segment(curve, t,   1.0)
    return left, right


# ---------------------------------------------------------------------------
# Offset
# ---------------------------------------------------------------------------

def offset_curve(curve: Curve, d_mm: float) -> Curve:
    """Create a new curve parallel to *curve* at *d_mm* offset.

    Positive d = left-hand normal (outward for CCW shapes).
    Negative d = right-hand normal (inward).
    Result has the same kind, layer, and node count as the input.
    Circles and arcs are offset analytically (radius ± d).
    """
    import copy as _copy

    if d_mm == 0.0:
        return _copy.deepcopy(curve)

    if curve.kind == "circle":
        c = _copy.deepcopy(curve)
        c.radius = max(0.0, (c.radius or 0.0) + d_mm)
        return c

    if curve.kind == "arc":
        c = _copy.deepcopy(curve)
        c.radius = max(0.0, (c.radius or 0.0) + d_mm)
        return c

    nodes = curve.nodes
    n = len(nodes)
    if n < 2:
        return _copy.deepcopy(curve)

    closed = curve.closed

    def _seg_normal(ax: float, ay: float, bx: float, by: float):
        """Left-hand unit normal of segment a→b."""
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-9:
            return (0.0, 0.0)
        return (-dy / L, dx / L)

    if curve.kind == "line":
        new_nodes: List[SplineNode] = []
        for i in range(n):
            nd = nodes[i]
            if closed:
                n1 = _seg_normal(nodes[(i - 1) % n].x, nodes[(i - 1) % n].y, nd.x, nd.y)
                n2 = _seg_normal(nd.x, nd.y, nodes[(i + 1) % n].x, nodes[(i + 1) % n].y)
            elif i == 0:
                n1 = n2 = _seg_normal(nd.x, nd.y, nodes[1].x, nodes[1].y)
            elif i == n - 1:
                n1 = n2 = _seg_normal(nodes[n - 2].x, nodes[n - 2].y, nd.x, nd.y)
            else:
                n1 = _seg_normal(nodes[i - 1].x, nodes[i - 1].y, nd.x, nd.y)
                n2 = _seg_normal(nd.x, nd.y, nodes[i + 1].x, nodes[i + 1].y)
            # Miter join: solve for point equidistant from both adjacent offset lines.
            mx, my = n1[0] + n2[0], n1[1] + n2[1]
            dot = n1[0] * mx + n1[1] * my  # n1 · (n1+n2); denominator for miter
            if abs(dot) < 0.05:            # near-antiparallel (tight U-turn) → bevel
                ox = nd.x + n1[0] * d_mm
                oy = nd.y + n1[1] * d_mm
            else:
                s = d_mm / dot
                ox = nd.x + mx * s
                oy = nd.y + my * s
            new_nodes.append(SplineNode(x=ox, y=oy))
        return Curve(kind="line", layer=curve.layer, nodes=new_nodes,
                     closed=closed, line_weight=curve.line_weight)

    # spline: offset nodes along averaged normal, recompute Catmull-Rom handles
    new_nodes = []
    for i in range(n):
        nd = nodes[i]
        if closed:
            prev = nodes[(i - 1) % n]
            nxt  = nodes[(i + 1) % n]
        else:
            prev = nodes[max(0, i - 1)]
            nxt  = nodes[min(n - 1, i + 1)]
        n1 = _seg_normal(prev.x, prev.y, nd.x, nd.y)
        n2 = _seg_normal(nd.x, nd.y, nxt.x, nxt.y)
        if i == 0 and not closed:
            nx, ny = n2
        elif i == n - 1 and not closed:
            nx, ny = n1
        else:
            nx = n1[0] + n2[0]
            ny = n1[1] + n2[1]
            L = math.hypot(nx, ny)
            if L < 1e-9:
                nx, ny = n1
            else:
                nx /= L
                ny /= L
        new_nodes.append(SplineNode(x=nd.x + nx * d_mm, y=nd.y + ny * d_mm))

    # Centripetal Catmull-Rom handles (mirrors compute_catmull_handles in tools/draw.py)
    def _p(i: int) -> SplineNode:
        return new_nodes[i % n] if closed else new_nodes[max(0, min(i, n - 1))]

    for i, node in enumerate(new_nodes):
        prv, nxt = _p(i - 1), _p(i + 1)
        tx = (nxt.x - prv.x) / 6
        ty = (nxt.y - prv.y) / 6
        node.cp_out = ControlPoint(node.x + tx, node.y + ty)
        node.cp_in  = ControlPoint(node.x - tx, node.y - ty)

    return Curve(kind="spline", layer=curve.layer, nodes=new_nodes,
                 closed=closed, line_weight=curve.line_weight)
