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


def _arc_sweep_deg(curve: Curve) -> float:
    """Positive sweep of an arc in degrees, None-safe.

    A zero sweep (equal start/end angles) means a full circle — the same rule
    build_path and arc_bbox use — so every parameterisation helper agrees with
    what is drawn on screen.
    """
    sweep = ((curve.end_angle or 0.0) - (curve.start_angle or 0.0)) % 360
    if sweep < 1e-9:
        sweep = 360.0
    return sweep


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
        sw = math.radians(_arc_sweep_deg(curve))
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


def compute_catmull_handles(nodes: list, closed: bool) -> None:
    """Set cp_in / cp_out on every node using centripetal Catmull-Rom.

    Single source of truth for smooth-spline handle generation — used by the
    draw tool, OMA trace import, and offset reconstruction. (Moved here from
    tools/draw.py in M7 so Qt-free modules can build splines.)
    """
    n = len(nodes)
    if n < 2:
        return

    def p(i):
        return nodes[i % n] if closed else nodes[max(0, min(i, n - 1))]

    for i, node in enumerate(nodes):
        prev, nxt = p(i - 1), p(i + 1)
        tx = (nxt.x - prev.x) / 6
        ty = (nxt.y - prev.y) / 6
        node.cp_out = ControlPoint(node.x + tx, node.y + ty)
        node.cp_in  = ControlPoint(node.x - tx, node.y - ty)


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
        sw  = math.radians(_arc_sweep_deg(curve))
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


def curve_intersections(a: Curve, b: Curve) -> List[Tuple[float, float]]:
    """Intersection points (x, y) of two curves' sampled shapely geometry.

    Used by the intersection snap; returns [] for disjoint/degenerate input.
    """
    ga = curve_to_shapely(a)
    gb = curve_to_shapely(b)
    if ga is None or gb is None:
        return []
    try:
        inter = ga.intersection(gb)
    except Exception:
        return []
    return [(p.x, p.y) for p in _iter_shapely_pts(inter)]


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

    # Sample the target once; t_nearest would re-sample it per point.
    samples = sample_curve(target, n_per_seg=_SAMPLES_PER_SEG * 2)

    def nearest_t(px: float, py: float) -> float:
        best_t, best_d2 = 0.0, float("inf")
        for x, y, t in samples:
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < best_d2:
                best_d2, best_t = d2, t
        return best_t

    ts = []
    for pt in _iter_shapely_pts(inter):
        if not is_closed:
            if (math.hypot(pt.x - sx, pt.y - sy) <= end_tol_mm
                    or math.hypot(pt.x - ex, pt.y - ey) <= end_tol_mm):
                continue
        ts.append(nearest_t(pt.x, pt.y))
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
        sweep = _arc_sweep_deg(curve)
        sa = (curve.start_angle or 0.0) + t_start * sweep
        ea = (curve.start_angle or 0.0) + t_end   * sweep
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

_OFFSET_TOL_MM    = 0.02  # max deviation of the offset from true parallel (mm)
_OFFSET_MAX_DEPTH = 8     # bezier subdivision limit per source segment
_OFFSET_JOIN_TOL  = 0.02  # adjacent segment offsets closer than this merge (mm)


def _abs_polygon_area(nodes) -> float:
    """|shoelace area| of the node polygon — winding-independent size proxy
    used to normalize offset direction on closed polylines."""
    n = len(nodes)
    s = 0.0
    for i in range(n):
        a, b = nodes[i], nodes[(i + 1) % n]
        s += a.x * b.y - b.x * a.y
    return abs(s) / 2.0


def _signed_area_pts(pts) -> float:
    """Shoelace signed area of an (x, y) point loop."""
    n = len(pts)
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i][0], pts[i][1]
        x1, y1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _unit(dx: float, dy: float):
    """Unit vector (dx, dy)/|·|, or None for a (near-)zero vector."""
    L = math.hypot(dx, dy)
    if L < 1e-12:
        return None
    return (dx / L, dy / L)


def _cubic_tangent(p0, p1, p2, p3, t: float):
    """Unit tangent of a cubic at t, falling back to the chord when the
    derivative degenerates (coincident control points)."""
    u = 1.0 - t
    dx = 3*u*u*(p1[0]-p0[0]) + 6*u*t*(p2[0]-p1[0]) + 3*t*t*(p3[0]-p2[0])
    dy = 3*u*u*(p1[1]-p0[1]) + 6*u*t*(p2[1]-p1[1]) + 3*t*t*(p3[1]-p2[1])
    return _unit(dx, dy) or _unit(p3[0]-p0[0], p3[1]-p0[1]) or (1.0, 0.0)


def _end_tangents(p0, p1, p2, p3):
    """Unit tangents at t=0 and t=1 with the standard degenerate fallbacks
    (a retracted handle falls through to the next control point)."""
    t0 = (_unit(p1[0]-p0[0], p1[1]-p0[1])
          or _unit(p2[0]-p0[0], p2[1]-p0[1])
          or _unit(p3[0]-p0[0], p3[1]-p0[1]) or (1.0, 0.0))
    t1 = (_unit(p3[0]-p2[0], p3[1]-p2[1])
          or _unit(p3[0]-p1[0], p3[1]-p1[1])
          or _unit(p3[0]-p0[0], p3[1]-p0[1]) or (1.0, 0.0))
    return t0, t1


def _line_intersect(a, ad, b, bd):
    """Intersection of lines a + s·ad and b + u·bd, or None if near-parallel."""
    det = ad[0] * bd[1] - ad[1] * bd[0]
    if abs(det) < 1e-9:
        return None
    s = ((b[0] - a[0]) * bd[1] - (b[1] - a[1]) * bd[0]) / det
    return (a[0] + ad[0] * s, a[1] + ad[1] * s)


def _offset_cubic_th(p0, p1, p2, p3, d: float):
    """Tiller–Hanson offset candidate for one cubic.

    Endpoints are displaced exactly d along the curve normal; the interior
    control points come from intersecting the translated control-polygon legs,
    so tangent directions are preserved (G1 with the neighbours). Accuracy is
    enforced by the caller's error check + subdivision, not here.
    """
    t0, t1 = _end_tangents(p0, p1, p2, p3)
    q0 = (p0[0] - t0[1] * d, p0[1] + t0[0] * d)
    q3 = (p3[0] - t1[1] * d, p3[1] + t1[0] * d)

    mid = _unit(p2[0] - p1[0], p2[1] - p1[1])
    if mid is None:
        # No interior leg — carry the handle vectors over unchanged.
        q1 = (q0[0] + (p1[0] - p0[0]), q0[1] + (p1[1] - p0[1]))
        q2 = (q3[0] + (p2[0] - p3[0]), q3[1] + (p2[1] - p3[1]))
        return [q0, q1, q2, q3]

    m0 = (p1[0] - mid[1] * d, p1[1] + mid[0] * d)   # translated middle leg
    q1 = _line_intersect(q0, t0, m0, mid)
    q2 = _line_intersect(q3, t1, m0, mid)
    # Miter blow-up guard: a wild intersection (near-parallel legs) only wastes
    # subdivisions — replace it with the plain translated control point.
    lim = 4.0 * abs(d)
    if q1 is None or math.hypot(q1[0]-p1[0], q1[1]-p1[1]) > lim + math.hypot(p1[0]-p0[0], p1[1]-p0[1]):
        q1 = (p1[0] - t0[1] * d, p1[1] + t0[0] * d)
    if q2 is None or math.hypot(q2[0]-p2[0], q2[1]-p2[1]) > lim + math.hypot(p3[0]-p2[0], p3[1]-p2[1]):
        q2 = (p2[0] - t1[1] * d, p2[1] + t1[0] * d)
    return [q0, q1, q2, q3]


def _offset_ok(src, cand, d: float, tol: float = _OFFSET_TOL_MM) -> bool:
    """True when *cand* tracks the exact offset of *src* (point + normal·d)
    within tol at several interior parameters."""
    p0, p1, p2, p3 = src
    for t in (0.2, 0.35, 0.5, 0.65, 0.8):
        sx, sy = _bezier_eval(p0, p1, p2, p3, t)
        tx, ty = _cubic_tangent(p0, p1, p2, p3, t)
        cx, cy = _bezier_eval(cand[0], cand[1], cand[2], cand[3], t)
        if math.hypot(cx - (sx - ty * d), cy - (sy + tx * d)) > tol:
            return False
    return True


def _offset_segment(p0, p1, p2, p3, d: float, out: list, depth: int = 0) -> None:
    """Append cubic(s) approximating the offset of p0..p3, subdividing the
    source until the Tiller–Hanson candidate is within tolerance."""
    cand = _offset_cubic_th(p0, p1, p2, p3, d)
    if depth >= _OFFSET_MAX_DEPTH or _offset_ok((p0, p1, p2, p3), cand, d):
        out.append(cand)
        return
    left, right = split_bezier_at_t(p0, p1, p2, p3, 0.5)
    _offset_segment(left[0],  left[1],  left[2],  left[3],  d, out, depth + 1)
    _offset_segment(right[0], right[1], right[2], right[3], d, out, depth + 1)


def _offset_winding_d(curve: Curve, d_mm: float) -> float:
    """Winding-corrected offset distance: +d must grow a closed shape whatever
    the node winding. The signed area of the SAMPLED curve (not the node
    polygon, which is degenerate for the two-node closed spline of GitHub issue
    #5) gives the true winding — positive area ⇒ the left-hand normal points
    inward, so flip d."""
    if curve.closed:
        area = _signed_area_pts([(x, y) for x, y, _ in sample_curve(curve)])
        if area > 0:
            return -d_mm
    return d_mm


def _assemble_offset_cubics(cubics: list, closed: bool,
                            layer, line_weight: float) -> Curve:
    """Build an offset Curve from an ordered cubic list. Consecutive cubics
    that meet (gap ≤ _OFFSET_JOIN_TOL) share a smooth node; a real gap — a
    source corner — is bridged with a straight bevel (two handle-less nodes)."""
    nodes: List[SplineNode] = []
    first = SplineNode(x=cubics[0][0][0], y=cubics[0][0][1])
    first.cp_out = ControlPoint(*cubics[0][1])
    nodes.append(first)
    for prev, nxt in zip(cubics, cubics[1:], strict=False):
        gap = math.hypot(nxt[0][0] - prev[3][0], nxt[0][1] - prev[3][1])
        if gap <= _OFFSET_JOIN_TOL:
            nd = SplineNode(x=(prev[3][0] + nxt[0][0]) / 2.0,
                            y=(prev[3][1] + nxt[0][1]) / 2.0)
            nd.cp_in  = ControlPoint(*prev[2])
            nd.cp_out = ControlPoint(*nxt[1])
            nodes.append(nd)
        else:
            e = SplineNode(x=prev[3][0], y=prev[3][1])
            e.cp_in = ControlPoint(*prev[2])
            s = SplineNode(x=nxt[0][0], y=nxt[0][1])
            s.cp_out = ControlPoint(*nxt[1])
            nodes.append(e)
            nodes.append(s)
    last = cubics[-1]
    if closed:
        gap = math.hypot(last[3][0] - nodes[0].x, last[3][1] - nodes[0].y)
        if gap <= _OFFSET_JOIN_TOL:
            nodes[0].cp_in = ControlPoint(*last[2])
        else:
            e = SplineNode(x=last[3][0], y=last[3][1])
            e.cp_in = ControlPoint(*last[2])
            nodes.append(e)   # bevel across the seam back to nodes[0]
    else:
        e = SplineNode(x=last[3][0], y=last[3][1])
        e.cp_in = ControlPoint(*last[2])
        nodes.append(e)

    return Curve(kind="spline", layer=layer, nodes=nodes,
                 closed=closed, line_weight=line_weight)


def _offset_spline(curve: Curve, d_mm: float) -> Curve:
    """Accurate Tiller–Hanson spline offset: every bezier segment is offset
    against the drawn curve itself (handles included), not the node polygon, so
    the result is parallel within _OFFSET_TOL_MM and G1-smooth wherever the
    source is. Node-heavy by nature (one node per subdivision) — offset_curve
    refits it down via the M31 engine, keeping this as the backstop."""
    import copy as _copy

    ns = _n_segs(curve)
    d = _offset_winding_d(curve, d_mm)

    cubics: list = []
    for i in range(ns):
        a, b = _seg_nodes(curve, i)
        p0, p1, p2, p3 = _seg_pts(a, b)
        if max(abs(px - p0[0]) + abs(py - p0[1])
               for px, py in (p1, p2, p3)) < 1e-9:
            continue   # zero-length segment (coincident nodes) — skip
        _offset_segment(p0, p1, p2, p3, d, cubics)
    if not cubics:
        return _copy.deepcopy(curve)

    return _assemble_offset_cubics(cubics, curve.closed,
                                   curve.layer, curve.line_weight)


# ---- Offset node reduction (M31.1) ----------------------------------------

_OFFSET_CORNER_RAD  = math.radians(1.0)   # tangent break above this = a corner
_OFFSET_FIT_PER_SEG = 24                   # exact-offset samples per source seg


def _tangent_break(curve: Curve, i: int) -> float:
    """Turn angle (radians) between the incoming and outgoing tangents at node
    i — handles when present, neighbour nodes otherwise. Large ⇒ a source
    corner where the offset breaks (and gets a bevel)."""
    nodes = curve.nodes
    n = len(nodes)
    node = nodes[i]
    vin = (_unit(node.x - node.cp_in.x, node.y - node.cp_in.y)
           if node.cp_in is not None else None)
    if vin is None:
        prev = nodes[(i - 1) % n]
        vin = _unit(node.x - prev.x, node.y - prev.y)
    vout = (_unit(node.cp_out.x - node.x, node.cp_out.y - node.y)
            if node.cp_out is not None else None)
    if vout is None:
        nxt = nodes[(i + 1) % n]
        vout = _unit(nxt.x - node.x, nxt.y - node.y)
    if vin is None or vout is None:
        return 0.0
    return abs(math.atan2(vin[0] * vout[1] - vin[1] * vout[0],
                          vin[0] * vout[0] + vin[1] * vout[1]))


def _smooth_runs(curve: Curve):
    """Partition the source segments into maximal runs with no corner between
    them. Returns (runs, has_corner); each run is an ordered segment-index
    list. For a closed source with corners the runs wrap, starting after a
    corner so every run is a clean open span."""
    ns = _n_segs(curve)
    n = len(curve.nodes)
    if curve.closed:
        corner = [_tangent_break(curve, i) > _OFFSET_CORNER_RAD for i in range(n)]
        if not any(corner):
            return [list(range(ns))], False
        start = next(i for i in range(n) if corner[i])
        runs, run = [], []
        for k in range(ns):
            si = (start + k) % ns
            run.append(si)
            if corner[(si + 1) % n]:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        return runs, True

    corner = [False] * n
    for i in range(1, n - 1):
        corner[i] = _tangent_break(curve, i) > _OFFSET_CORNER_RAD
    runs, run = [], []
    for si in range(ns):
        run.append(si)
        if corner[si + 1]:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs, any(corner)


def _exact_offset_points(curve: Curve, seg_indices: list, d: float,
                         closed_loop: bool) -> List[Tuple[float, float]]:
    """Dense EXACT offset points (source point + left-normal·d) along the given
    contiguous source segments. closed_loop omits the final endpoint so the
    points form a seam-free loop for a closed fit."""
    pts: List[Tuple[float, float]] = []
    m = len(seg_indices)
    for k, si in enumerate(seg_indices):
        a, b = _seg_nodes(curve, si)
        p0, p1, p2, p3 = _seg_pts(a, b)
        last = (k == m - 1)
        count = _OFFSET_FIT_PER_SEG + (1 if (last and not closed_loop) else 0)
        for j in range(count):
            t = j / _OFFSET_FIT_PER_SEG
            x, y = _bezier_eval(p0, p1, p2, p3, t)
            tx, ty = _cubic_tangent(p0, p1, p2, p3, t)
            pts.append((x - ty * d, y + tx * d))
    return pts


def _curve_cubics(c: Curve) -> list:
    """Extract the cubic control-point list from a fitted spline Curve."""
    nodes = c.nodes
    cubics = []
    segs = list(range(len(nodes) - 1))
    if c.closed and len(nodes) >= 2:
        segs.append(len(nodes) - 1)   # wrap seam
    for i in segs:
        a, b = nodes[i], nodes[(i + 1) % len(nodes)]
        p0 = (a.x, a.y)
        p1 = (a.cp_out.x, a.cp_out.y) if a.cp_out else p0
        p3 = (b.x, b.y)
        p2 = (b.cp_in.x, b.cp_in.y) if b.cp_in else p3
        cubics.append([p0, p1, p2, p3])
    return cubics


def _point_polyline_dist(p, poly) -> float:
    best = float("inf")
    for a, b in zip(poly, poly[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        if L2 < 1e-18:
            d2 = (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2
        else:
            t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
            d2 = (p[0] - a[0] - dx * t) ** 2 + (p[1] - a[1] - dy * t) ** 2
        if d2 < best:
            best = d2
    return math.sqrt(best)


def _offset_matches(reduced: Curve, reference: Curve) -> bool:
    """True when the reduced offset stays within a small band of the Tiller–
    Hanson reference everywhere (two-sided). Catches a fit that self-intersected
    on an inward offset past the curvature limit — there we keep TH instead."""
    tol = max(_OFFSET_TOL_MM * 5.0, 0.08)
    pa = [(x, y) for x, y, _ in sample_curve(reduced, _OFFSET_FIT_PER_SEG)]
    pb = [(x, y) for x, y, _ in sample_curve(reference, _OFFSET_FIT_PER_SEG)]
    if len(pa) < 2 or len(pb) < 2:
        return False
    if max(_point_polyline_dist(p, pb) for p in pa) > tol:
        return False
    if max(_point_polyline_dist(p, pa) for p in pb) > tol:
        return False
    return True


def _reduce_offset_nodes(curve: Curve, d_mm: float, th: Curve):
    """Reproduce the Tiller–Hanson offset *th* with far fewer nodes by fitting
    the EXACT offset (source point + normal·d — never the TH output, so the
    error budgets don't stack). Returns a reduced Curve, or None to keep TH
    (a fit that saved nothing, or drifted — e.g. a self-intersecting inward
    offset past the curvature limit)."""
    try:
        from .fitting import fit_curve

        d = _offset_winding_d(curve, d_mm)
        runs, has_corner = _smooth_runs(curve)

        if curve.closed and not has_corner:
            pts = _exact_offset_points(curve, runs[0], d, closed_loop=True)
            if len(pts) < 4:
                return None
            reduced = fit_curve(pts, tol_mm=_OFFSET_TOL_MM, closed=True,
                                layer=curve.layer,
                                line_weight=curve.line_weight).curve
        else:
            cubics: list = []
            for run in runs:
                pts = _exact_offset_points(curve, run, d, closed_loop=False)
                if len(pts) < 2:
                    continue
                cubics += _curve_cubics(
                    fit_curve(pts, tol_mm=_OFFSET_TOL_MM, closed=False,
                              layer=curve.layer,
                              line_weight=curve.line_weight).curve)
            if not cubics:
                return None
            reduced = _assemble_offset_cubics(cubics, curve.closed,
                                              curve.layer, curve.line_weight)

        if len(reduced.nodes) >= len(th.nodes):
            return None   # no saving — keep the backstop
        if _offset_matches(reduced, th):
            return reduced
        return None
    except Exception:
        return None


def offset_curve(curve: Curve, d_mm: float) -> Curve:
    """Create a new curve parallel to *curve* at *d_mm* offset.

    Closed curves: positive d always grows the shape (outward), negative
    shrinks it — independent of node winding (GitHub issue #1: the old
    left-normal rule sent +d inward on screen-clockwise shapes).
    Open curves: positive d = left-hand normal of the node order.

    Splines are offset against the true drawn curve — each bezier segment is
    offset with adaptive subdivision until it is parallel within
    _OFFSET_TOL_MM (GitHub issues #5/#6: the old node-polygon offset discarded
    the handles, collapsing two-node closed splines to a line and drifting off
    the curve between nodes). That Tiller–Hanson result is then refit through
    the M31 cubic-fitting engine — sampling the EXACT offset, not the TH output,
    so the error budgets don't stack — to return a compact, editable curve
    (M31.1); if the refit saves nothing or drifts (a self-intersecting inward
    offset past the curvature limit) the TH result is returned unchanged.
    Corners (broken handles) get a straight bevel join and stay sharp across the
    refit. Circles and arcs are offset analytically (radius ± d).
    """
    import copy as _copy

    if d_mm == 0.0:
        return _copy.deepcopy(curve)

    if curve.kind in ("circle", "arc"):
        c = _copy.deepcopy(curve)
        c.radius = max(0.0, (c.radius or 0.0) + d_mm)
        return c

    nodes = curve.nodes
    n = len(nodes)
    if n < 2:
        return _copy.deepcopy(curve)

    closed = curve.closed

    if curve.kind != "line":
        th = _offset_spline(curve, d_mm)
        reduced = _reduce_offset_nodes(curve, d_mm, th)
        return reduced if reduced is not None else th

    def _seg_normal(ax: float, ay: float, bx: float, by: float):
        """Left-hand unit normal of segment a→b."""
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-9:
            return (0.0, 0.0)
        return (-dy / L, dx / L)

    def _line_nodes(d: float) -> List[SplineNode]:
        out: List[SplineNode] = []
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
                ox = nd.x + n1[0] * d
                oy = nd.y + n1[1] * d
            else:
                s = d / dot
                ox = nd.x + mx * s
                oy = nd.y + my * s
            out.append(SplineNode(x=ox, y=oy))
        return out

    new_nodes = _line_nodes(d_mm)
    if closed and n >= 3:
        # Normalize direction: +d must grow the shape whatever the winding.
        grew = _abs_polygon_area(new_nodes) > _abs_polygon_area(nodes)
        if grew != (d_mm > 0):
            new_nodes = _line_nodes(-d_mm)

    return Curve(kind="line", layer=curve.layer, nodes=new_nodes,
                 closed=closed, line_weight=curve.line_weight)


# ---------------------------------------------------------------------------
# Arc construction helpers
# ---------------------------------------------------------------------------

def arc_start_end_center(sx: float, sy: float,
                         ex: float, ey: float,
                         cx: float, cy: float):
    """Build a true circular arc from two endpoints and an approximate centre.

    The clicked centre is snapped onto the perpendicular bisector of the
    chord S→E so both endpoints lie on the circle (equal radii). The *minor*
    arc between the endpoints is always returned, so placing the centre on
    one side of the chord vs. the other flips which way the arc bulges — an
    intuitive, predictable control.

    Returns ``(cx2, cy2, radius, start_deg, end_deg)`` in the scene angle
    convention (degrees; 0=right, 90=down-screen; sweep runs positive from
    start to end, matching :func:`point_at_t` / build_path), or ``None`` when
    the construction is degenerate (coincident endpoints, or a centre that
    lands on the chord).
    """
    mx, my = (sx + ex) / 2.0, (sy + ey) / 2.0
    chord_dx, chord_dy = ex - sx, ey - sy
    chord_len2 = chord_dx * chord_dx + chord_dy * chord_dy
    if chord_len2 < 1e-12:
        return None   # endpoints coincide

    # Perpendicular bisector direction (unit), then project the clicked centre
    # onto the bisector line through the chord midpoint.
    bx, by = -chord_dy, chord_dx
    bL = math.hypot(bx, by)
    bx, by = bx / bL, by / bL
    proj = (cx - mx) * bx + (cy - my) * by
    cx2, cy2 = mx + bx * proj, my + by * proj

    r = math.hypot(sx - cx2, sy - cy2)
    if r < 1e-9:
        return None

    start_deg = math.degrees(math.atan2(sy - cy2, sx - cx2))
    end_deg   = math.degrees(math.atan2(ey - cy2, ex - cx2))
    sweep     = (end_deg - start_deg) % 360
    if sweep < 1e-6 or abs(sweep - 360) < 1e-6:
        return None
    # Keep the minor arc: if the positive sweep S→E is the major one, swap.
    if sweep > 180.0:
        start_deg, end_deg = end_deg, start_deg
    return (cx2, cy2, r, start_deg, end_deg)


def fillet_lines(corner: tuple, far1: tuple, far2: tuple, r: float):
    """Compute the tangent fillet arc blending two line legs at a shared corner.

    ``corner`` is the shared vertex; ``far1``/``far2`` are the opposite
    endpoints of the two legs (they only define the leg *directions*). ``r`` is
    the fillet radius in mm.

    Returns a dict with::

        t1, t2      tangent points on leg 1 / leg 2 (the legs are trimmed here)
        center      arc centre
        radius      r
        start_deg   arc start angle (scene convention, minor arc t1→t2)
        end_deg     arc end angle
        tan_len     distance from corner to each tangent point

    or ``None`` when the legs are collinear, ``r`` is non-positive, or the
    tangent length exceeds either leg (radius too large to fit the corner).
    """
    if r <= 0.0:
        return None
    cxv, cyv = corner
    d1x, d1y = far1[0] - cxv, far1[1] - cyv
    d2x, d2y = far2[0] - cxv, far2[1] - cyv
    L1 = math.hypot(d1x, d1y)
    L2 = math.hypot(d2x, d2y)
    if L1 < 1e-9 or L2 < 1e-9:
        return None
    d1x, d1y = d1x / L1, d1y / L1
    d2x, d2y = d2x / L2, d2y / L2

    cos_t = max(-1.0, min(1.0, d1x * d2x + d1y * d2y))
    theta = math.acos(cos_t)          # interior angle between the legs
    half  = theta / 2.0
    if math.sin(half) < 1e-6 or math.tan(half) < 1e-6:
        return None                   # collinear legs — no corner to fillet

    tan_len = r / math.tan(half)
    if tan_len > L1 + 1e-9 or tan_len > L2 + 1e-9:
        return None                   # radius too large to fit on a leg

    t1 = (cxv + d1x * tan_len, cyv + d1y * tan_len)
    t2 = (cxv + d2x * tan_len, cyv + d2y * tan_len)

    # Centre lies along the angle bisector at distance r / sin(half).
    bx, by = d1x + d2x, d1y + d2y
    bL = math.hypot(bx, by)
    if bL < 1e-9:
        return None
    bx, by = bx / bL, by / bL
    dist_c = r / math.sin(half)
    center = (cxv + bx * dist_c, cyv + by * dist_c)

    start_deg = math.degrees(math.atan2(t1[1] - center[1], t1[0] - center[0]))
    end_deg   = math.degrees(math.atan2(t2[1] - center[1], t2[0] - center[0]))
    if (end_deg - start_deg) % 360 > 180.0:   # always the minor (fillet) arc
        start_deg, end_deg = end_deg, start_deg
    return {
        "t1": t1, "t2": t2, "center": center, "radius": r,
        "start_deg": start_deg, "end_deg": end_deg, "tan_len": tan_len,
    }
