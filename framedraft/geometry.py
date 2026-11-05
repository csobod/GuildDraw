"""
Shared, Qt-free geometry: curve parameterization, segment extraction for
Trim/Split, intersections, mirroring, Catmull-Rom handles, circle/arc
conversion, fillets and the offset engine.

Curve parameterization: t in [0.0, 1.0].
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
import bisect
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
# Parameterization helpers
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
    build_path and arc_bbox use — so every parameterization helper agrees with
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
                 line_weight=curve.line_weight, group_id=curve.group_id,
                 component_kind=curve.component_kind)


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
                 line_weight=curve.line_weight, group_id=curve.group_id,
                 component_kind=curve.component_kind)


def compute_catmull_handles(nodes: list, closed: bool) -> None:
    """Set cp_in / cp_out on every node using uniform Catmull-Rom
    (handles at ±(P[i+1] − P[i−1]) / 6).

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

    horizontal=False: vertical axis at x = axis_x (front / component workspaces).
    horizontal=True : horizontal axis at y = 0 (temple workspaces); axis_x unused.

    Single source of truth for mirror math — used by scene ghosts, the validator,
    Mirror (bake), Temple Copy, and draw-tool preview ghosts. The result is
    plain geometry (mirrored=False); callers decide its role. A component's
    kind goes with it: the twin of a hinge is a hinge.
    """
    def mp(x: float, y: float) -> Tuple[float, float]:
        if horizontal:
            return x, -y
        return 2.0 * axis_x - x, y

    if curve.kind == "circle":
        cx, cy = mp(curve.nodes[0].x, curve.nodes[0].y)
        return Curve(kind="circle", layer=curve.layer,
                     nodes=[SplineNode(x=cx, y=cy)], closed=curve.closed,
                     radius=curve.radius, line_weight=curve.line_weight,
                     component_kind=curve.component_kind)

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
                     line_weight=curve.line_weight,
                     component_kind=curve.component_kind)

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
                 closed=curve.closed, line_weight=curve.line_weight,
                 component_kind=curve.component_kind)


def curve_is_finite(curve: Curve) -> bool:
    """Every number *curve* holds is finite. An importer's NaN, or an overflow
    such as SVG's scale(1e200), drew nothing, raised in every paint, and the
    saved tab read back empty (the 2.0 bug hunt)."""
    def ok(v) -> bool:
        return v is None or math.isfinite(v)
    for n in curve.nodes:
        if not (math.isfinite(n.x) and math.isfinite(n.y)):
            return False
        for cp in (n.cp_in, n.cp_out):
            if cp is not None and not (math.isfinite(cp.x) and math.isfinite(cp.y)):
                return False
    return ok(curve.radius) and ok(curve.start_angle) and ok(curve.end_angle)


def drop_end_handles(curve: Curve) -> Curve:
    """Clear the handles past an open curve's ends, the first node's cp_in
    and the last node's cp_out: nothing draws with them, yet they showed as
    handle dots, and Smooth tied them to the real ones. Returns *curve*."""
    if not curve.closed and curve.kind in ("spline", "line") and curve.nodes:
        curve.nodes[0].cp_in = None
        curve.nodes[-1].cp_out = None
    return curve


def open_ends(curve: Curve) -> list:
    """The free ends of an open curve, as ``(x, y, node)``: a line's or a
    spline's first and last node, or an arc's two rim points at its start and
    end angles (*node* None: an arc's one node is its center, which E and the
    node-drag magnet took for an end). A closed curve has none."""
    if curve.closed or not curve.nodes:
        return []
    if curve.kind == "arc":
        if (not curve.radius or curve.start_angle is None
                or curve.end_angle is None):
            return []
        c, r = curve.nodes[0], curve.radius
        return [(c.x + r * math.cos(math.radians(a)),
                 c.y + r * math.sin(math.radians(a)), None)
                for a in (curve.start_angle, curve.end_angle)]
    if curve.kind == "circle":
        return []
    first, last = curve.nodes[0], curve.nodes[-1]
    return [(first.x, first.y, first), (last.x, last.y, last)]


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

    if curve.kind in ("circle", "arc") and not nodes:
        return result                 # no center: nothing to draw

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


def flatten_curve(curve: Curve, tol_mm: float = 0.01) -> List[Tuple[float, float]]:
    """The curve as a polyline within *tol_mm* of it, with as few points as
    that takes: a straight run is its two ends, a Bézier is cut by its flatness
    (the bound on a cubic's second difference), an arc by its sagitta. The
    fills stitched 16 samples a segment of every spline, and a dense imported
    spline froze the canvas for two seconds a mouse move (the 2.0 bug hunt).
    A closed curve's polyline ends where it starts."""
    nodes = curve.nodes
    if curve.kind in ("circle", "arc"):
        if not nodes:
            return []
        cx, cy, r = nodes[0].x, nodes[0].y, curve.radius or 0.0
        if r <= 0.0:
            return [(cx, cy)]
        step = 2.0 * math.acos(max(-1.0, 1.0 - tol_mm / r)) if tol_mm < r else math.pi / 2
        step = max(step, 1e-3)
        if curve.kind == "circle":
            n = max(8, math.ceil(2 * math.pi / step))
            pts = [(cx + r * math.cos(2 * math.pi * i / n),
                    cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
            return pts + pts[:1]
        sa = math.radians(curve.start_angle or 0.0)
        sw = math.radians(_arc_sweep_deg(curve))
        n = max(2, math.ceil(abs(sw) / step))
        return [(cx + r * math.cos(sa + sw * i / n), cy + r * math.sin(sa + sw * i / n))
                for i in range(n + 1)]
    if len(nodes) < 2:
        return [(n.x, n.y) for n in nodes]
    if curve.kind == "line":
        pts = [(n.x, n.y) for n in nodes]
        return pts + pts[:1] if curve.closed else pts
    out = [(nodes[0].x, nodes[0].y)]
    for seg_i in range(_n_segs(curve)):
        a, b = _seg_nodes(curve, seg_i)
        p0, p1, p2, p3 = _seg_pts(a, b)
        if a.cp_out is None and b.cp_in is None:
            out.append(p3)                     # a straight run
            continue
        d = max(math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1]),
                math.hypot(p1[0] - 2 * p2[0] + p3[0], p1[1] - 2 * p2[1] + p3[1]))
        n = max(1, min(64, math.ceil(math.sqrt(0.75 * d / tol_mm))))
        for j in range(1, n + 1):
            out.append(_bezier_eval(p0, p1, p2, p3, j / n))
    return out


def _refine_t(curve: Curve, px: float, py: float,
              t_lo: float, t_hi: float, iters: int = 40) -> float:
    """Ternary search for the t in [t_lo, t_hi] nearest (px, py) — the
    distance is unimodal between two adjacent samples. (2/3)^40 of the
    bracket is far below any machining tolerance."""
    lo, hi = max(0.0, t_lo), min(1.0, t_hi)

    def d2(t):
        x, y = point_at_t(curve, t)
        return (x - px) ** 2 + (y - py) ** 2
    for _ in range(iters):
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        if d2(m1) < d2(m2):
            hi = m2
        else:
            lo = m1
    return (lo + hi) / 2.0


def _seg_ctrl(curve: Curve):
    """Every segment's four control points as an (ns, 4, 2) array, built in
    one pass over the nodes (a line's handles sit on its nodes)."""
    import numpy as np
    nodes = curve.nodes
    ia = np.arange(_n_segs(curve))
    ib = (ia + 1) % len(nodes)
    if curve.kind != "spline":
        xy = np.array([(nd.x, nd.y) for nd in nodes], dtype=float)
        return np.stack([xy[ia], xy[ia], xy[ib], xy[ib]], axis=1)
    # Per node: itself, its out handle, its in handle (a missing one on it).
    pts = np.array([v for nd in nodes for v in (
        nd.x, nd.y,
        *((nd.cp_out.x, nd.cp_out.y) if nd.cp_out else (nd.x, nd.y)),
        *((nd.cp_in.x, nd.cp_in.y) if nd.cp_in else (nd.x, nd.y)))],
        dtype=float).reshape(-1, 3, 2)
    return np.stack([pts[ia, 0], pts[ia, 1], pts[ib, 2], pts[ib, 0]], axis=1)


def _bezier_np(c, t):
    """_bezier_eval for arrays: control points *c* (..., 4, 2) at *t* (...)."""
    t = t[..., None]
    u = 1.0 - t
    return (u**3*c[..., 0, :] + 3*u**2*t*c[..., 1, :]
            + 3*u*t**2*c[..., 2, :] + t**3*c[..., 3, :])


def _sample_grid(curve: Curve, n_per_seg: int, exact: bool = True):
    """sample_curve's samples as arrays (xs, ys, ts), or None: the same grid,
    evaluated at once. Point by point, t_nearest's grid of 32 a segment cost
    half a second a click on an 8000-node trace (2.0.1).

    *exact* evaluates every point by sample_curve's own formula, so the
    samples and every t found among them are the ones it gave, to the bit;
    without it, a spline's grid is one product with the Bernstein basis,
    fifteen times faster, for a hover that only ranks."""
    import numpy as np
    nodes = curve.nodes
    if curve.kind in ("circle", "arc"):
        if not nodes:
            return None
        cx, cy, r = nodes[0].x, nodes[0].y, curve.radius or 0.0
        if curve.kind == "circle":
            n = n_per_seg * 8
            i = np.arange(n + 1)
            a = 2 * math.pi * i / n
        else:
            sa = math.radians(curve.start_angle or 0.0)
            sw = math.radians(_arc_sweep_deg(curve))
            n = max(n_per_seg, int(math.degrees(abs(sw)) / 5))
            i = np.arange(n + 1)
            a = sa + sw * i / n
        return cx + r * np.cos(a), cy + r * np.sin(a), i / n
    if len(nodes) < 2:
        if not nodes:
            return None
        return np.array([nodes[0].x]), np.array([nodes[0].y]), np.array([0.0])
    ns = _n_segs(curve)
    c = _seg_ctrl(curve)
    local = np.arange(n_per_seg) / n_per_seg
    ts = np.append(((np.arange(ns)[:, None] + local[None, :]) / ns).ravel(), 1.0)
    if curve.kind == "spline" and not exact:
        u = 1.0 - local
        basis = np.stack([u**3, 3*u**2*local, 3*u*local**2, local**3], axis=1)
        pts = np.matmul(basis[None], c).reshape(-1, 2)
        end = c[-1, 3]
    elif curve.kind == "spline":
        pts = _bezier_np(c[:, None], np.broadcast_to(local, (ns, n_per_seg))).reshape(-1, 2)
        end = c[-1, 3]
    else:
        a, b = c[:, 0], c[:, 3]
        pts = (a[:, None] + (b - a)[:, None] * local[None, :, None]).reshape(-1, 2)
        end = a[-1] + (b[-1] - a[-1]) * 1.0
    pts = np.vstack([pts, end])
    return pts[:, 0], pts[:, 1], ts


def _nearest_sample_t(samples, px: float, py: float) -> tuple:
    """(t_best, t_prev, t_next) around the nearest sample (the first, on a tie)."""
    import numpy as np
    xs, ys, ts = samples
    i = int(np.argmin((xs - px) ** 2 + (ys - py) ** 2))
    t_best = float(ts[i])
    t_prev = float(ts[i - 1]) if i > 0 else t_best
    t_next = float(ts[i + 1]) if i + 1 < len(ts) else t_best
    return t_best, t_prev, t_next


def _nearest_refined_t(curve: Curve, samples, px: float, py: float,
                       iters: int = 40) -> float:
    """The sample nearest (px, py), refined between its neighbors — and on a
    closed curve whose nearest sample is the seam, refined on both sides of
    it. The first and last samples are the same point there, and the first
    won the tie, so a point on the closing segment resolved to t = 0 (a Split
    opened 0.9 mm from the click; a Trim cut the wrong side). *samples* are
    _sample_grid's arrays."""
    ts = samples[2]
    _t, t_prev, t_next = _nearest_sample_t(samples, px, py)
    t = _refine_t(curve, px, py, t_prev, t_next, iters)
    closed = curve.closed or curve.kind == "circle"
    if closed and len(ts) > 2 and (_t <= ts[0] or _t >= ts[-1]):
        options = [t,
                   _refine_t(curve, px, py, 0.0, float(ts[1]), iters),
                   _refine_t(curve, px, py, float(ts[-2]), 1.0, iters)]

        def d2(tt):
            x, y = point_at_t(curve, tt)
            return (x - px) ** 2 + (y - py) ** 2
        t = min(options, key=d2)
    return t


def t_nearest_coarse(curve: Curve, px: float, py: float, n_per_seg: int = 8) -> float:
    """`t_nearest` on a coarser grid, refined the same way: for a hover that
    only ranks candidates, 8 samples a segment instead of 64 (a 500-node
    DXF spline cost 37 ms a mouse move in Trim and Split). 24 steps of the
    refinement leave 6e-5 of a bracket two samples wide, enough to rank."""
    samples = _sample_grid(curve, n_per_seg, exact=False)
    if samples is None:
        return 0.0
    return _nearest_refined_t(curve, samples, px, py, iters=24)


def t_nearest(curve: Curve, px: float, py: float) -> float:
    """Return the t in [0, 1] of the point on *curve* nearest to (px, py).

    Nearest of the samples, then refined between its neighbors: the raw
    sample grid is 1/64 of a segment, which left a trim end up to 0.7 mm
    short of the cutting edge on a 100 mm line."""
    samples = _sample_grid(curve, _SAMPLES_PER_SEG * 2)
    if samples is None:
        return 0.0
    return _nearest_refined_t(curve, samples, px, py)


# ---------------------------------------------------------------------------
# Shapely conversion + intersection
# ---------------------------------------------------------------------------
#
# Two curves are met as polylines flattened within _ISECT_FLAT_MM, and each
# place the polylines cross is then settled on the curves themselves, by
# Newton on both parameters. They were met as polylines of 16 chords a
# segment, which lie inside a curve by their sagitta (0.08 mm on a library
# lens): a line ending on a curve from outside went unseen, and a shallow
# crossing landed off by the sagitta over the sine of its angle, up to 2 mm on
# the Frame Library. Sampled again for every pair and placed by a Python scan,
# one Trim click on a 2000-node trace among 100 curves took 7 s (2.0.1).

_ISECT_FLAT_MM = 0.002   # the polylines' flattening; every meeting is refined after

# A free end of an open curve this near another curve meets it. It is the
# closure tolerance (the validator's _CLOSURE_TOL_MM, GuildModel's auto-close)
# and the Frame Fill's stitch: both already join a gap that small, and Trim,
# Split and the Intersection snap now agree with them. The snaps put an end
# on a curve to within a few µm; the old Trim and Intersection snap left ends
# inside a curve by its chords' sagitta, up to 0.08 mm on a library lens,
# which this still meets. Less than a pixel at 1:1, no such gap is drawn to
# stay open.
_TOUCH_MM = 0.1

# Two curves this near each other along this long lie one on the other: a
# copy, a datum along a straight edge, a curve rebuilt over its original. They
# meet once at each end of that run, not every 1 to 2.5 mm along it (Trim
# removed a sliver of a copied lens). The Frame Library's shallowest real
# crossings, REF curves traced over a lens or an outline at 1 to 2°, stay
# this near for 2.5 mm at most, and a single crossing is never a run.
_OVERLAP_MM     = 0.01
_OVERLAP_MIN_MM = 3.0
_GRAZE_SIN      = 0.02   # crossings shallower than this are weighed for a run


class _Flat:
    """A curve flattened for the crossing search: the polyline's vertices
    (xy, n × 2), the curve's parameter at each (ts) and their bounds. The
    index of its segments is built when first asked for."""

    __slots__ = ("curve", "closed", "xy", "ts", "box", "_tree", "_pts")

    def __init__(self, curve: Curve, xy, ts):
        self.curve = curve
        self.closed = curve.closed or curve.kind == "circle"
        self.xy, self.ts = xy, ts
        self.box = (float(xy[:, 0].min()), float(xy[:, 1].min()),
                    float(xy[:, 0].max()), float(xy[:, 1].max()))
        self._tree = None
        self._pts = None

    def pts(self) -> list:
        """The vertices as a list of (x, y) floats, for the per-pair math."""
        if self._pts is None:
            self._pts = self.xy.tolist()
        return self._pts

    def tree(self):
        if self._tree is None:
            import numpy as np
            import shapely
            self._tree = shapely.STRtree(
                shapely.linestrings(np.stack([self.xy[:-1], self.xy[1:]], axis=1)))
        return self._tree

    def t_at(self, i: int, s: float) -> float:
        """The parameter at fraction *s* along polyline segment *i*."""
        return float(self.ts[i] + s * (self.ts[i + 1] - self.ts[i]))


def _flat(curve: Curve, tol: float = _ISECT_FLAT_MM):
    """*curve* as a _Flat within *tol* of it (flatten_curve's rule, with the
    parameter kept at every vertex), or None when it draws no line."""
    import numpy as np
    nodes = curve.nodes
    if curve.kind in ("circle", "arc"):
        r = curve.radius or 0.0
        if not nodes or not r > 0.0:
            return None
        cx, cy = nodes[0].x, nodes[0].y
        step = max(2.0 * math.acos(1.0 - tol / r) if tol < r else math.pi / 2,
                   2 * math.pi / 4096)
        if curve.kind == "circle":
            a0, sw = 0.0, 2 * math.pi
        else:
            a0 = math.radians(curve.start_angle or 0.0)
            sw = math.radians(_arc_sweep_deg(curve))
        n = max(8 if curve.kind == "circle" else 2, math.ceil(sw / step))
        ts = np.arange(n + 1) / n
        a = a0 + sw * ts
        xy = np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])
        if curve.kind == "circle":
            xy[-1] = xy[0]
    elif len(nodes) < 2:
        return None
    elif curve.kind == "line":
        ns = _n_segs(curve)
        pts = [(nd.x, nd.y) for nd in nodes]
        xy = np.array(pts + pts[:1] if curve.closed else pts, dtype=float)
        ts = np.arange(ns + 1) / ns
    else:
        ns = _n_segs(curve)
        c = _seg_ctrl(curve)
        d = np.maximum(np.hypot(*(c[:, 0] - 2 * c[:, 1] + c[:, 2]).T),
                       np.hypot(*(c[:, 1] - 2 * c[:, 2] + c[:, 3]).T))
        k = np.clip(np.ceil(np.sqrt(0.75 * d / tol)), 1, 256).astype(int)
        # Both handles retracted: a straight run, one chord (its control
        # points' second difference is the run's length, not a bend).
        k[(c[:, 1] == c[:, 0]).all(axis=1) & (c[:, 2] == c[:, 3]).all(axis=1)] = 1
        seg = np.repeat(np.arange(ns), k)
        u = (np.arange(len(seg)) - np.repeat(np.cumsum(k) - k, k)) / np.repeat(k, k)
        xy = np.vstack([_bezier_np(c[seg], u), c[-1, 3]])
        ts = np.append((seg + u) / ns, 1.0)
    if not np.isfinite(xy).all():
        return None
    return _Flat(curve, xy, ts)


def _ctrl_box(curve: Curve):
    """Bounds that hold all of *curve* (a Bézier lies within its handles),
    cheap enough to skip a far curve before it is flattened; None if empty."""
    nodes = curve.nodes
    if not nodes:
        return None
    if curve.kind in ("circle", "arc"):
        cx, cy, r = nodes[0].x, nodes[0].y, abs(curve.radius or 0.0)
        return (cx - r, cy - r, cx + r, cy + r)
    xs = [n.x for n in nodes]
    ys = [n.y for n in nodes]
    if curve.kind == "spline":
        for n in nodes:
            for cp in (n.cp_in, n.cp_out):
                if cp is not None:
                    xs.append(cp.x)
                    ys.append(cp.y)
    return (min(xs), min(ys), max(xs), max(ys))


def _boxes_meet(p, q, pad: float) -> bool:
    return (p[0] - pad <= q[2] and q[0] - pad <= p[2]
            and p[1] - pad <= q[3] and q[1] - pad <= p[3])


def _point_deriv(curve: Curve, t: float):
    """(x, y, dx/dt, dy/dt) of *curve* at t in [0, 1], as point_at_t has it."""
    nodes = curve.nodes
    if curve.kind in ("circle", "arc"):
        cx, cy, r = nodes[0].x, nodes[0].y, curve.radius or 0.0
        if curve.kind == "circle":
            a, sw = 2 * math.pi * t, 2 * math.pi
        else:
            sw = math.radians(_arc_sweep_deg(curve))
            a = math.radians(curve.start_angle or 0.0) + sw * t
        c, s = math.cos(a), math.sin(a)
        return cx + r * c, cy + r * s, -sw * r * s, sw * r * c
    ns = _n_segs(curve)
    scaled = t * ns
    seg = min(int(scaled), ns - 1)
    local = scaled - seg
    a, b = _seg_nodes(curve, seg)
    if curve.kind == "spline":
        p0, p1, p2, p3 = _seg_pts(a, b)
        x, y = _bezier_eval(p0, p1, p2, p3, local)
        u = 1.0 - local
        dx = 3*u*u*(p1[0]-p0[0]) + 6*u*local*(p2[0]-p1[0]) + 3*local*local*(p3[0]-p2[0])
        dy = 3*u*u*(p1[1]-p0[1]) + 6*u*local*(p2[1]-p1[1]) + 3*local*local*(p3[1]-p2[1])
        return x, y, dx * ns, dy * ns
    return (a.x + (b.x - a.x) * local, a.y + (b.y - a.y) * local,
            (b.x - a.x) * ns, (b.y - a.y) * ns)


def _settle(fa: _Flat, ta: float, fb: _Flat, tb: float):
    """Newton on a(ta) = b(tb), from where the two polylines cross. Returns
    (ta, tb, x, y, sin), sin that of the angle the curves cross at, or None
    when it does not settle: the curves run together there, or touch."""
    a, b = fa.curve, fb.curve
    for _ in range(20):
        ax, ay, adx, ady = _point_deriv(a, ta)
        bx, by, bdx, bdy = _point_deriv(b, tb)
        fx, fy = ax - bx, ay - by
        la, lb = math.hypot(adx, ady), math.hypot(bdx, bdy)
        if la == 0.0 or lb == 0.0:
            return None
        cross = adx * bdy - ady * bdx
        if math.hypot(fx, fy) <= 1e-10 * (1.0 + abs(ax) + abs(ay)):
            return ta, tb, ax, ay, abs(cross) / (la * lb)
        if abs(cross) <= 1e-12 * la * lb:
            return None
        ta += (fy * bdx - fx * bdy) / cross
        tb += (fy * adx - fx * ady) / cross
        ta = ta % 1.0 if fa.closed else min(max(ta, 0.0), 1.0)
        tb = tb % 1.0 if fb.closed else min(max(tb, 0.0), 1.0)
    return None


def _foot(f: _Flat, x: float, y: float, reach: float = _TOUCH_MM):
    """(t, fx, fy, d): the point of f's curve nearest (x, y), found on its
    polyline and refined on the curve; None when that is beyond *reach*."""
    import numpy as np
    import shapely
    if len(f.xy) <= 65:
        cand = np.arange(len(f.xy) - 1)         # a few segments: no index
    else:
        cand = f.tree().query(shapely.Point(x, y), predicate="dwithin",
                              distance=reach + 2 * _ISECT_FLAT_MM)
    if not len(cand):
        return None
    p = f.xy[cand]
    r = f.xy[cand + 1] - p
    l2 = (r * r).sum(axis=1)
    w = np.column_stack([x - p[:, 0], y - p[:, 1]])
    s = np.clip(np.divide((w * r).sum(axis=1), l2, out=np.zeros_like(l2), where=l2 > 0),
                0.0, 1.0)
    d2 = ((p + r * s[:, None] - (x, y)) ** 2).sum(axis=1)
    k = int(np.argmin(d2))
    i = int(cand[k])
    if d2[k] == 0.0 and s[k] in (0.0, 1.0):
        # On a vertex of the polyline, which lies on the curve: an end
        # drawn to a node, often a corner the steps below cannot settle at.
        v = i + int(s[k])
        return float(f.ts[v]), float(f.xy[v, 0]), float(f.xy[v, 1]), 0.0
    # Gauss-Newton from the polyline's foot: a few steps, where the ternary
    # search below takes 140 evaluations. It does not settle at a corner, or
    # where the curve stalls (a retracted handle); the search takes those.
    t = f.t_at(i, float(s[k]))
    for _ in range(12):
        cx, cy, dx, dy = _point_deriv(f.curve, t)
        dd = dx * dx + dy * dy
        if dd == 0.0:
            break
        step = ((x - cx) * dx + (y - cy) * dy) / dd
        t1 = (t + step) % 1.0 if f.closed else min(max(t + step, 0.0), 1.0)
        settled = abs(t1 - t) <= 1e-13
        t = t1
        if settled:
            px, py = point_at_t(f.curve, t)
            d = math.hypot(px - x, py - y)
            if d <= math.sqrt(d2[k]) + 2 * _ISECT_FLAT_MM:
                return (t, px, py, d) if d <= reach else None
            break
    ts, last = f.ts, len(f.ts) - 1
    brackets = [(ts[max(i - 1, 0)], ts[min(i + 2, last)])]
    if f.closed and i == 0:
        brackets.append((ts[max(last - 2, 0)], 1.0))
    elif f.closed and i >= last - 1:
        brackets.append((0.0, ts[min(2, last)]))
    best = None
    for lo, hi in brackets:
        t = _refine_t(f.curve, x, y, float(lo), float(hi), iters=70)
        px, py = point_at_t(f.curve, t)
        d = math.hypot(px - x, py - y)
        if best is None or d < best[3]:
            best = (t, px, py, d)
    return best if best[3] <= reach else None


def _polyline_crossings(fa: _Flat, fb: _Flat):
    """Where the two polylines meet: (crossings, runs). A crossing is
    (ta, tb, x, y), a point where a segment of A crosses one of B; a run is
    (ta, x, y) at each end of a stretch where segments of each lie on the
    same line, one after another."""
    import numpy as np
    import shapely
    x0, y0, x1, y1 = fa.box
    p, q = fb.xy[:-1], fb.xy[1:]
    near = np.nonzero((np.maximum(p[:, 0], q[:, 0]) >= x0) & (np.minimum(p[:, 0], q[:, 0]) <= x1)
                      & (np.maximum(p[:, 1], q[:, 1]) >= y0) & (np.minimum(p[:, 1], q[:, 1]) <= y1))[0]
    if not len(near):
        return [], []
    na = len(fa.xy) - 1
    if na * len(near) <= 64:
        # A few segments: every pair is weighed, cheaper than an index (120
        # REF lines met pairwise by the Intersection snap).
        pairs = [(i, j) for j in near.tolist() for i in range(na)]
    else:
        qi, ia = fa.tree().query(shapely.linestrings(np.stack([p[near], q[near]], axis=1)),
                                 predicate="intersects")
        pairs = zip(ia.tolist(), near[qi].tolist(), strict=True)
    A, B = fa.pts(), fb.pts()
    seen = set()
    crossings, spans = [], []
    for i, j in pairs:
        (px, py), (ux, uy) = A[i], A[i + 1]
        (qx, qy), (vx, vy) = B[j], B[j + 1]
        rx, ry, sx, sy = ux - px, uy - py, vx - qx, vy - qy
        lr, ls = math.hypot(rx, ry), math.hypot(sx, sy)
        if lr == 0.0 or ls == 0.0:
            continue
        wx, wy = qx - px, qy - py
        den = rx * sy - ry * sx
        if abs(den) > 1e-12 * lr * ls:
            sig = (wx * sy - wy * sx) / den
            tau = (wx * ry - wy * rx) / den
            if not (-1e-12 <= sig <= 1 + 1e-12 and -1e-12 <= tau <= 1 + 1e-12):
                continue
            sig, tau = min(max(sig, 0.0), 1.0), min(max(tau, 0.0), 1.0)
            x, y = px + rx * sig, py + ry * sig
            key = (round(x, 9), round(y, 9))
            if key in seen:             # a crossing at a vertex, found twice
                continue
            seen.add(key)
            crossings.append((fa.t_at(i, sig), fb.t_at(j, tau), x, y))
            continue
        # Parallel: on one line, and overlapping along it?
        if abs(wx * ry - wy * rx) > 1e-12 * lr * (lr + math.hypot(wx, wy)):
            continue
        s0 = (wx * rx + wy * ry) / (lr * lr)
        s1 = ((wx + sx) * rx + (wy + sy) * ry) / (lr * lr)
        if max(s0, s1) < -1e-12 or min(s0, s1) > 1 + 1e-12:
            continue
        lo, hi = min(max(min(s0, s1), 0.0), 1.0), min(max(max(s0, s1), 0.0), 1.0)
        spans.append((fa.t_at(i, lo), fa.t_at(i, hi),
                      (px + rx * lo, py + ry * lo), (px + rx * hi, py + ry * hi)))
    # Segments on one line one after another are one stretch: only its two
    # ends are meetings, not every vertex along it.
    spans.sort(key=lambda sp: (sp[0], sp[1]))
    merged: list = []
    for t0, t1, p0, p1 in spans:
        if merged and t0 <= merged[-1][1] + 1e-12:
            if t1 > merged[-1][1]:
                merged[-1][1], merged[-1][3] = t1, p1
        else:
            merged.append([t0, t1, p0, p1])
    if fa.closed and len(merged) > 1 and merged[0][0] <= 1e-12 and merged[-1][1] >= 1 - 1e-12:
        merged[0][0], merged[0][2] = merged[-1][0], merged[-1][2]   # through the seam
        merged.pop()
    runs = []
    for t0, t1, p0, p1 in merged:
        runs.append((t0, *p0))
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 1e-12:
            runs.append((t1, *p1))
    return crossings, runs


def _overlaps(fa: _Flat, fb: _Flat, marks: list) -> list:
    """The stretches of A that lie on B: within _OVERLAP_MM of it along
    _OVERLAP_MIN_MM or more, and holding marks (x, y, weight) that weigh 2
    or more: 2 where the polylines run together or no crossing settles, 1
    where they cross at a graze. Each is a shapely LineString along A's
    polyline."""
    import numpy as np
    import shapely
    from shapely.geometry import LineString
    if not marks:
        return []
    # Only B's stretch within A's bounds can lie on A: buffered whole, a long
    # outline cost a click its millisecond for a datum along one edge.
    x0, y0, x1, y1 = fa.box
    m = 2 * _OVERLAP_MM
    lb = shapely.clip_by_rect(LineString(fb.xy), x0 - m, y0 - m, x1 + m, y1 + m)
    if lb.is_empty:
        return []
    near = LineString(fa.xy).intersection(lb.buffer(_OVERLAP_MM, quad_segs=4))
    parts = [g for g in shapely.get_parts(near) if g.geom_type == "LineString"]
    if not parts:
        return []
    runs = []
    pts = shapely.points(np.array([(x, y) for x, y, _w in marks], dtype=float))
    weights = np.array([w for _x, _y, w in marks], dtype=float)
    for run in shapely.get_parts(shapely.line_merge(shapely.multilinestrings(parts))):
        if run.length < _OVERLAP_MIN_MM:
            continue
        inside = shapely.distance(run, pts) <= _OVERLAP_MM + 2 * _ISECT_FLAT_MM
        if weights[inside].sum() >= 2:
            runs.append(run)
    return runs


def _run_end(fa: _Flat, x: float, y: float, snaps):
    """(t, x, y) on A at the end of an overlap run found at (x, y): at the
    nearest node, free end or crossing within a few _OVERLAP_MM of it (a
    corner the run leaves by is where it ends), else at (x, y)."""
    import numpy as np
    if len(snaps):
        d = np.hypot(snaps[:, 0] - x, snaps[:, 1] - y)
        i = int(np.argmin(d))
        if d[i] <= 4 * _OVERLAP_MM:
            x, y = float(snaps[i, 0]), float(snaps[i, 1])
    hit = _foot(fa, x, y, reach=8 * _OVERLAP_MM)
    if hit is None:
        return None
    return hit[0], hit[1], hit[2]


def _on_curve_points(curve: Curve) -> list:
    """The points a curve's shape turns on: its nodes and free ends."""
    if curve.kind in ("circle", "arc"):
        return [(x, y) for x, y, _n in open_ends(curve)]
    return [(n.x, n.y) for n in curve.nodes]


def _meet(fa: _Flat, fb: _Flat, a_ends: bool = False):
    """Where curve B meets curve A: ([(ta, x, y), ...], covered), sorted by
    ta, with (x, y) on A. The meetings are the curves' crossings, settled on
    both; each free end of B within _TOUCH_MM of A (with *a_ends*, also A's
    free ends within _TOUCH_MM of B, at their foot on B); and the two ends of
    every run where they lie one on the other. *covered* is True when such a
    run is all of A."""
    import numpy as np
    if not _boxes_meet(fa.box, fb.box, _TOUCH_MM + 2 * _ISECT_FLAT_MM):
        return [], False
    crossings, collinear = _polyline_crossings(fa, fb)
    # loose: where the polylines meet but no crossing settles, kept at the
    # polyline's point and put on A at the end (along a flat segment the
    # parameter is only interpolated, and a straight run with its handles
    # retracted is not uniform in it).
    settled, loose, grazes = [], [], []
    for ta0, tb0, sx, sy in crossings:
        got = _settle(fa, ta0, fb, tb0)
        if got is not None:
            ta, tb, x, y, sin = got
            # Settled far from where the polylines crossed, it found another crossing.
            if math.hypot(x - sx, y - sy) <= 0.01 + 4 * _ISECT_FLAT_MM / max(sin, 1e-9):
                settled.append((ta, x, y))
                if sin < _GRAZE_SIN:
                    grazes.append((x, y, 1))
                continue
        loose.append((ta0, sx, sy))
    loose += collinear

    # Free ends that stop on the other curve (or a hair short of it, or past
    # it by less than the polylines can show): no crossing settles there.
    touches = []
    for f, g, own in ((fb, fa, False), (fa, fb, True)) if a_ends else ((fb, fa, False),):
        x0, y0, x1, y1 = g.box
        pad = _TOUCH_MM + 2 * _ISECT_FLAT_MM
        for k, (ex, ey, _n) in enumerate(open_ends(f.curve)):
            if not (x0 - pad <= ex <= x1 + pad and y0 - pad <= ey <= y1 + pad):
                continue
            hit = _foot(g, ex, ey)
            if hit is None:
                continue
            # A crossing found by its end already is the meeting.
            if any(math.hypot(x - ex, y - ey) <= _DEDUP_TOL_MM for _t, x, y in settled):
                continue
            t, x, y, _d = hit
            loose = [h for h in loose if math.hypot(h[1] - x, h[2] - y) > _DEDUP_TOL_MM]
            touches.append((float(k) if own else t, x, y))   # A's own end: t 0 or 1

    hits = settled + loose + touches
    covered = False
    if loose or len(grazes) >= 2:
        runs = _overlaps(fa, fb, [(x, y, 2) for _t, x, y in loose] + grazes)
        if runs:
            import shapely
            snaps = np.array(_on_curve_points(fa.curve) + _on_curve_points(fb.curve)
                             + [(x, y) for _t, x, y in hits], dtype=float).reshape(-1, 2)
            pts = shapely.points(np.array([(x, y) for _t, x, y in hits], dtype=float).reshape(-1, 2))
            keep = np.ones(len(hits), dtype=bool)
            ends = []
            length = float(np.hypot(*np.diff(fa.xy, axis=0).T).sum())
            for run in runs:
                keep &= shapely.distance(run, pts) > _OVERLAP_MM + 2 * _ISECT_FLAT_MM
                (x0, y0), (x1, y1) = run.coords[0], run.coords[-1]
                if fa.closed and run.length >= length - 4 * _OVERLAP_MM and \
                        math.hypot(x1 - x0, y1 - y0) <= 4 * _OVERLAP_MM:
                    covered = True              # all of a closed curve: no ends
                    continue
                for x, y in ((x0, y0), (x1, y1)):
                    end = _run_end(fa, x, y, snaps)
                    if end is not None:
                        ends.append(end)
                if not fa.closed and run.length >= length - 4 * _OVERLAP_MM:
                    covered = True
            hits = [h for h, k in zip(hits, keep.tolist(), strict=True) if k] + ends

    placed = set(map(id, loose))
    for n, h in enumerate(hits):
        if id(h) in placed:
            hit = _foot(fa, h[1], h[2], reach=4 * _ISECT_FLAT_MM)
            hits[n] = hit[:3] if hit is not None else (h[0], *point_at_t(fa.curve, h[0]))
    hits.sort(key=lambda h: h[0])
    out = []
    for h in hits:
        if out and math.hypot(h[1] - out[-1][1], h[2] - out[-1][2]) <= 1e-7:
            continue
        out.append(h)
    if fa.closed and len(out) > 1 and \
            math.hypot(out[0][1] - out[-1][1], out[0][2] - out[-1][2]) <= 1e-7:
        out.pop()
    return out, covered


def curve_to_shapely(curve: Curve):
    """The curve as a Shapely geometry, flattened within _ISECT_FLAT_MM, or
    None."""
    f = _flat(curve)
    if f is None:
        return None
    try:
        if f.closed:
            return _sg.LinearRing(f.xy)
        return _sg.LineString(f.xy)
    except Exception:
        return None


def _iter_shapely_pts(geom):
    """Yield shapely Points from any Shapely geometry. A line, where two
    geometries overlap, gives its two ends: an overlap meets there."""
    if geom is None or geom.is_empty:
        return
    gtype = geom.geom_type
    if gtype == "Point":
        yield geom
    elif gtype in ("MultiPoint", "GeometryCollection",
                   "MultiLineString", "MultiPolygon"):
        for g in geom.geoms:
            yield from _iter_shapely_pts(g)
    elif gtype in ("LineString", "LinearRing"):
        coords = list(geom.coords)
        yield _sg.Point(coords[0])
        if coords[-1] != coords[0]:
            yield _sg.Point(coords[-1])


def curve_intersections(a: Curve, b: Curve) -> List[Tuple[float, float]]:
    """Points (x, y) where curves *a* and *b* meet: their crossings, settled
    on both curves; a free end of either that stops on the other (within
    _TOUCH_MM); the two ends of a run where they lie one on the other.

    Used by the intersection snap; returns [] for disjoint/degenerate input.
    """
    pa, pb = _ctrl_box(a), _ctrl_box(b)
    if pa is None or pb is None or not _boxes_meet(pa, pb, _TOUCH_MM + 2 * _ISECT_FLAT_MM):
        return []
    fa, fb = _flat(a), _flat(b)
    if fa is None or fb is None:
        return []
    hits, _covered = _meet(fa, fb, a_ends=True)
    out: List[Tuple[float, float]] = []
    seen = set()
    for _t, x, y in hits:
        key = (round(x, 7), round(y, 7))
        if key not in seen:
            seen.add(key)
            out.append((x, y))
    return out


def intersect_curve_params(target: Curve, other: Curve,
                           end_tol_mm: float = _END_TOL_MM) -> List[float]:
    """
    Return t values on `target` where it intersects `other`: where they
    cross, where a free end of `other` stops on it, and at each end of a run
    where the two lie one on the other.

    For open curves, intersections within end_tol_mm (scene mm) of either
    endpoint are dropped — they are trivial endpoint touches, not crossings.
    Closed curves keep all intersections (t≈0/1 is the seam, a real point).
    """
    return [t for t, _o in target_crossings(target, [other], end_tol_mm)]


def target_crossings(target: Curve, others: list,
                     end_tol_mm: float = _END_TOL_MM,
                     near: tuple | None = None,
                     along: list | None = None) -> list:
    """[(t, other), ...]: intersect_curve_params for every curve of *others*
    at once (one Trim or Split click). The target is flattened and indexed
    once, and a curve whose bounds cannot reach it is never flattened.

    *near* = (x, y, r) keeps the meetings within r mm of (x, y), and skips
    every curve that cannot hold one (Split's snap). The others that
    *target* lies on along its whole length are appended to *along*, when
    given (a copy: they meet nowhere)."""
    fa = _flat(target)
    if fa is None:
        return []
    pad = _TOUCH_MM + 2 * _ISECT_FLAT_MM
    if near is not None:
        nx, ny, nr = near
        reach = (nx - nr, ny - nr, nx + nr, ny + nr)
        if not _boxes_meet(fa.box, reach, pad):
            return []
    is_closed = fa.closed
    if not is_closed:
        sx, sy = point_at_t(target, 0.0)
        ex, ey = point_at_t(target, 1.0)
        end_tol_mm = _small_tol(target, end_tol_mm)
    out = []
    for other in others:
        if other is target:
            continue
        box = _ctrl_box(other)
        if box is None or not _boxes_meet(fa.box, box, pad):
            continue
        if near is not None and not _boxes_meet(box, reach, pad):
            continue
        fb = _flat(other)
        if fb is None:
            continue
        hits, covered = _meet(fa, fb)
        if covered and along is not None:
            along.append(other)
        for t, x, y in hits:
            if near is not None and math.hypot(x - nx, y - ny) > nr:
                continue
            if not is_closed:
                if (math.hypot(x - sx, y - sy) <= end_tol_mm
                        or math.hypot(x - ex, y - ey) <= end_tol_mm):
                    continue
            out.append((t, other))
    return out


def _small_tol(curve: Curve, tol_mm: float) -> float:
    """*tol_mm*, but no more than a quarter of the curve's size. Absolute,
    the 0.5 mm merge and the 0.25 mm end tolerance swallowed a feature under
    a millimeter: a 0.4 mm line could not be cut or split, and a 0.2 mm
    circle's two crossings were one (2.0.1). No Frame Library curve is small
    enough to feel it."""
    b = _ctrl_box(curve)
    if b is None:
        return tol_mm
    return min(tol_mm, 0.25 * math.hypot(b[2] - b[0], b[3] - b[1]))


def _along_mm(curve: Curve, t0: float, t1: float, n: int = 16) -> float:
    """Length of *curve* from t0 to t1 (t0 <= t1), on n chords."""
    pts = [point_at_t(curve, t0 + (t1 - t0) * k / n) for k in range(n + 1)]
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:], strict=False))


def dedup_ts_mm(curve: Curve, ts: List[float],
                tol_mm: float = _DEDUP_TOL_MM) -> List[float]:
    """Merge t values whose points on *curve* are within tol_mm (scene mm).

    Distance is measured in mm rather than t-space so the tolerance does not
    grow with the number of segments in the curve.  For closed curves the
    first and last survivors are also compared across the t=0/1 seam.

    Two points merge only when they are near along the curve as well: a
    line across both arms of a hairpin, or both walls of a narrow slot, made
    two crossings that were taken for one. On a curve under four times
    tol_mm across, the tolerance is a quarter of its size (_small_tol).
    """
    if not ts:
        return []
    tol_mm = _small_tol(curve, tol_mm)
    ts  = sorted(ts)
    out = [ts[0]]
    for t in ts[1:]:
        x0, y0 = point_at_t(curve, out[-1])
        x1, y1 = point_at_t(curve, t)
        if (math.hypot(x1 - x0, y1 - y0) > tol_mm
                or _along_mm(curve, out[-1], t) > 2 * tol_mm):
            out.append(t)
    if (curve.closed or curve.kind == "circle") and len(out) > 1:
        x0, y0 = point_at_t(curve, out[0])
        x1, y1 = point_at_t(curve, out[-1])
        if (math.hypot(x1 - x0, y1 - y0) <= tol_mm
                and _along_mm(curve, out[-1], 1.0) + _along_mm(curve, 0.0, out[0])
                <= 2 * tol_mm):
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
        local  = scaled - seg
        # A t a hair below a node (t_nearest at a node can land there) is
        # the node: read as the end of the segment before, the piece after
        # began with a second node 4e-9 mm from it, a hook when dragged.
        if local > 1 - 1e-9 and seg < ns - 1:
            seg, local = seg + 1, 0.0
        return seg, local

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

    # An open piece has no handle on the outside of its two ends (a copied
    # node kept the source's, which showed as a stray handle dot).
    if result:
        result[0].cp_in   = None
        result[-1].cp_out = None
    return Curve(kind="spline", layer=curve.layer, nodes=result,
                 closed=False, line_weight=curve.line_weight,
                 component_kind=curve.component_kind)


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
                 closed=False, line_weight=curve.line_weight,
                 component_kind=curve.component_kind)


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
                     line_weight=curve.line_weight,
                     component_kind=curve.component_kind)

    if curve.kind == "arc":
        sweep = _arc_sweep_deg(curve)
        sa = (curve.start_angle or 0.0) + t_start * sweep
        ea = (curve.start_angle or 0.0) + t_end   * sweep
        cx, cy = curve.nodes[0].x, curve.nodes[0].y
        return Curve(kind="arc", layer=curve.layer,
                     nodes=[SplineNode(x=cx, y=cy)], closed=False,
                     radius=curve.radius,
                     start_angle=sa, end_angle=ea,
                     line_weight=curve.line_weight,
                     component_kind=curve.component_kind)

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

    # A piece that starts or ends on the seam itself has no length: joined
    # anyway, it left two coincident nodes with degenerate handles.
    seam_x, seam_y = point_at_t(curve, 0.0)

    def at_seam(t: float) -> bool:
        x, y = point_at_t(curve, t)
        return math.hypot(x - seam_x, y - seam_y) < 1e-3
    if at_seam(t_start) and t_start > 0.5:
        return extract_open_segment(curve, 0.0, t_end)
    if at_seam(t_end) and t_end < 0.5:
        return extract_open_segment(curve, t_start, 1.0)

    seg_hi = extract_open_segment(curve, t_start, 1.0)
    seg_lo = extract_open_segment(curve, 0.0,     t_end)

    if curve.kind == "line":
        combined = seg_hi.nodes[:-1] + seg_lo.nodes
        return Curve(kind="line", layer=curve.layer, nodes=combined,
                     closed=False, line_weight=curve.line_weight,
                     component_kind=curve.component_kind)

    # spline: merge seam at the original nodes[0] position
    hi_end   = seg_hi.nodes[-1]
    lo_start = seg_lo.nodes[0]
    seam     = SplineNode(x=hi_end.x, y=hi_end.y)
    seam.cp_in  = hi_end.cp_in
    seam.cp_out = lo_start.cp_out
    combined    = seg_hi.nodes[:-1] + [seam] + seg_lo.nodes[1:]
    return Curve(kind="spline", layer=curve.layer, nodes=combined,
                 closed=False, line_weight=curve.line_weight,
                 component_kind=curve.component_kind)


def split_curve_at_t(curve: Curve,
                     t: float,
                     end_tol_mm: float = _END_TOL_MM):
    """
    Split curve at t in (0, 1) into (left, right) open curves.
    Returns (curve, None) if the split point is within end_tol_mm (scene mm)
    of either endpoint — a split there would create a degenerate sliver.

    A CLOSED spline/line has no ends: one cut opens it into a single open
    curve running from t all the way round back to t, returned as
    (opened, None). (Two pieces would have hidden a second cut at the seam
    node.) Circles keep the two-arc result — an arc from t round to t is
    not a valid entity.
    """
    if curve.kind in ("spline", "line") and curve.closed and len(curve.nodes) >= 2:
        px, py = point_at_t(curve, t)
        sx, sy = point_at_t(curve, 0.0)
        if math.hypot(px - sx, py - sy) <= end_tol_mm:
            # At the seam: open it there, at the node, rather than cut a
            # sliver off (an OMA lens's seam sits on the datum line, so a
            # Split snapped to that crossing lands here every time).
            return extract_open_segment(curve, 0.0, 1.0), None
        return extract_wrapping_segment(curve, t, t), None
    if curve.kind == "circle":
        t = t % 1.0
        px, py = point_at_t(curve, t)
        sx, sy = point_at_t(curve, 0.0)
        if math.hypot(px - sx, py - sy) <= end_tol_mm:
            # A circle's 0° point is where its two arcs are usually cut
            # apart, not an end: there the second cut goes opposite the first.
            # (A datum line through a lens or hole center hit it and the
            # circle stayed whole.)
            u = (t + 0.5) % 1.0
            return extract_open_segment(curve, t, u), extract_open_segment(curve, u, t)
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


class OffsetOutOfRange(ValueError):
    """The distance is out of range for the curve: an inward offset that
    leaves nothing of a closed shape, or one that folds over itself too often
    to untangle. The message says which, worded to follow "−10 mm is out of
    range for this curve: ". The Offset tool shows it instead of a preview."""


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
    """Unit tangent of a cubic at t. When the derivative degenerates (a
    retracted handle) the limiting tangent at an end is towards the NEXT
    control point (p2 − p0 at t=0, p3 − p1 at t=1), the same ladder
    _end_tangents uses — the chord is only the last resort. Using the chord
    first displaced the offset's endpoint along the wrong normal, so the
    reduced refit always failed and the node-heavy backstop shipped."""
    u = 1.0 - t
    dx = 3*u*u*(p1[0]-p0[0]) + 6*u*t*(p2[0]-p1[0]) + 3*t*t*(p3[0]-p2[0])
    dy = 3*u*u*(p1[1]-p0[1]) + 6*u*t*(p2[1]-p1[1]) + 3*t*t*(p3[1]-p2[1])
    tangent = _unit(dx, dy)
    if tangent:
        return tangent
    if t < 0.5:
        return (_unit(p2[0]-p0[0], p2[1]-p0[1])
                or _unit(p3[0]-p0[0], p3[1]-p0[1]) or (1.0, 0.0))
    return (_unit(p3[0]-p1[0], p3[1]-p1[1])
            or _unit(p3[0]-p0[0], p3[1]-p0[1]) or (1.0, 0.0))


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
    so tangent directions are preserved (G1 with the neighbors). Accuracy is
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
    i — handles when present, neighbor nodes otherwise. Large ⇒ a source
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
    on an inward offset past the curvature limit — there we keep TH instead.
    Vectorized (2.0.1): point by point in Python it was nine tenths of an
    outline's offset, three to eight seconds of the tool's live preview. Each
    line is prepared, so the test of every point is indexed: unprepared, an
    offset far past its bends (a TH of thousands of cubics) took four seconds."""
    import numpy as np
    import shapely

    tol = max(_OFFSET_TOL_MM * 5.0, 0.08)
    pa = np.asarray([(x, y) for x, y, _ in sample_curve(reduced, _OFFSET_FIT_PER_SEG)])
    pb = np.asarray([(x, y) for x, y, _ in sample_curve(reference, _OFFSET_FIT_PER_SEG)])
    if len(pa) < 2 or len(pb) < 2:
        return False
    la, lb = shapely.linestrings(pa), shapely.linestrings(pb)
    shapely.prepare(la)
    shapely.prepare(lb)
    # The prepared line first: the other way round GEOS does not use it.
    if not shapely.dwithin(lb, shapely.points(pa), tol).all():
        return False
    return bool(shapely.dwithin(la, shapely.points(pb), tol).all())


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


# ---- Offset loops (2.0.1) -------------------------------------------------
#
# At a corner the offset pieces of the two sides either leave a gap (the
# outside, bridged by a bevel) or run past each other (the inside), and the
# bevel joining their ends then makes a small loop; an inward offset past the
# curvature of a tight bend loops the same way. Every shipped hinge pocket at
# −0.3 mm, and most library outlines at −1 mm, crossed themselves so.

_LOOP_FLAT_TOL_MM = 0.0005   # flattening tolerance of the crossing search
_LOOP_MAX_CUTS    = 500
# The search's work, its flattened points summed over the passes that found a
# crossing; each costs 4-7 µs. The Frame Library's 425 splines peak at 25 000
# at ±1 mm, 145 000 at ±3 mm and 355 000 at +5 mm; an offset far past its
# bends ran 980 000 and more, minutes for some, with the GUI frozen. The
# segment pairs it weighs are counted too, apart: the library peaks at 47 000
# at ±3 mm and 245 000 at +5 mm, and a lens trace with tracer noise weighs
# 80 000 a pass, where points alone let it run 40 passes (17 s).
_LOOP_MAX_WORK    = 400_000
_LOOP_MAX_PAIRS   = 300_000
_FOLDS_TOO_OFTEN  = "it folds over itself too often to untangle"
_NOTHING_LEFT     = "nothing of the shape would be left"
_SPLITS_SHAPE     = "the shape would come apart into separate pieces"


def _cubic_straight(c) -> bool:
    """Both handles retracted: a straight run, which the loop search
    parameterizes by its chord so a cut lands where it was found."""
    return (abs(c[1][0] - c[0][0]) + abs(c[1][1] - c[0][1]) < 1e-12
            and abs(c[2][0] - c[3][0]) + abs(c[2][1] - c[3][1]) < 1e-12)


def _cubic_tiny(c) -> bool:
    return all(abs(p[0] - c[0][0]) + abs(p[1] - c[0][1]) < 1e-9 for p in c[1:])


def _cubic_at(c, t: float):
    if _cubic_straight(c):
        return (c[0][0] + (c[3][0] - c[0][0]) * t, c[0][1] + (c[3][1] - c[0][1]) * t)
    return _bezier_eval(c[0], c[1], c[2], c[3], t)


def _cubic_deriv(c, t: float):
    p0, p1, p2, p3 = c
    if _cubic_straight(c):
        return (p3[0] - p0[0], p3[1] - p0[1])
    u = 1.0 - t
    return (3*u*u*(p1[0]-p0[0]) + 6*u*t*(p2[0]-p1[0]) + 3*t*t*(p3[0]-p2[0]),
            3*u*u*(p1[1]-p0[1]) + 6*u*t*(p2[1]-p1[1]) + 3*t*t*(p3[1]-p2[1]))


def _cubic_cut(c, t: float, at):
    """(left, right) of cubic *c* cut at *t*, the cut end of each pinned to
    the point *at* (its handle moved with it)."""
    if _cubic_straight(c):
        return [c[0], c[0], at, at], [at, at, c[3], c[3]]
    left, right = split_bezier_at_t(c[0], c[1], c[2], c[3], t)
    dx, dy = at[0] - left[3][0], at[1] - left[3][1]
    return ([left[0], left[1], (left[2][0] + dx, left[2][1] + dy), at],
            [at, (right[1][0] + dx, right[1][1] + dy), right[2], right[3]])


def _flatten_cubics(cubics: list):
    """The chain of cubics as a polyline: its vertices, and per segment the
    cubic it lies on with the parameters at its ends. Zero-length segments
    are left out, so two segments that touch are neighbors."""
    verts = [cubics[0][0]]
    segs: list = []
    for k, c in enumerate(cubics):
        if _cubic_straight(c):
            n = 1
        else:
            p0, p1, p2, p3 = c
            d = max(math.hypot(p0[0] - 2*p1[0] + p2[0], p0[1] - 2*p1[1] + p2[1]),
                    math.hypot(p1[0] - 2*p2[0] + p3[0], p1[1] - 2*p2[1] + p3[1]))
            n = max(1, min(256, math.ceil(math.sqrt(0.75 * d / _LOOP_FLAT_TOL_MM))))
        t0 = 0.0
        for j in range(1, n + 1):
            t = j / n
            p = _cubic_at(c, t)
            if abs(p[0] - verts[-1][0]) + abs(p[1] - verts[-1][1]) >= 1e-12:
                verts.append(p)
                segs.append((k, t0, t))
            t0 = t
    return verts, segs


def _point_on_seg(p, a, b):
    """(distance, parameter, foot) of point p's nearest point on segment ab."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-24 else min(max(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2, 0.0), 1.0)
    foot = (a[0] + dx * t, a[1] + dy * t)
    return math.hypot(p[0] - foot[0], p[1] - foot[1]), t, foot


def _chain_crossings(verts: list, closed: bool, pairs: list | None = None) -> list:
    """(i, σ, j, τ, point) for every point where segment i, at σ, crosses a
    later segment j, at τ, that is not its neighbor. The number of segment
    pairs weighed is appended to *pairs*, when given.

    A hairpin counts as a crossing too: two segments within the offset's
    accuracy (_OFFSET_TOL_MM) whose way round along the chain is ten times
    their gap. Past a bend tighter than the offset distance the exact offset
    loops; the approximation, held only to that accuracy, can lose the
    crossing and leave a hair-thin spike in its place (two library outlines
    at ±1 mm). The point is then midway across the gap."""
    import numpy as np
    import shapely

    n = len(verts) - 1
    if n < 3:
        return []
    a = np.asarray(verts, dtype=float)
    lines = shapely.linestrings(np.stack([a[:-1], a[1:]], axis=1))
    ii, jj = shapely.STRtree(lines).query(lines, predicate="dwithin",
                                          distance=_OFFSET_TOL_MM)
    keep = jj > ii + 1
    if closed:
        keep &= ~((ii == 0) & (jj == n - 1))
    ii, jj = ii[keep], jj[keep]
    if pairs is not None:
        pairs.append(len(ii))
    if not len(ii):
        return []
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*(a[1:] - a[:-1]).T))])
    gap = shapely.distance(lines[ii], lines[jj])
    way = cum[jj + 1] - cum[ii]           # the most the way round can be
    if closed:
        way = np.minimum(way, cum[-1] - cum[jj] + cum[ii + 1])
    near = (gap <= 1e-12) | ((way > 10.0 * gap) & (way > 2.0 * _OFFSET_TOL_MM))
    out = []
    for i, j in zip(ii[near].tolist(), jj[near].tolist(), strict=True):
        p, q = verts[i], verts[i + 1]
        r, s = verts[j], verts[j + 1]
        rx, ry = q[0] - p[0], q[1] - p[1]
        sx, sy = s[0] - r[0], s[1] - r[1]
        den = rx * sy - ry * sx
        if abs(den) > 1e-12 * math.hypot(rx, ry) * math.hypot(sx, sy):
            wx, wy = r[0] - p[0], r[1] - p[1]
            sig = (wx * sy - wy * sx) / den
            tau = (wx * ry - wy * rx) / den
            if -1e-9 <= sig <= 1 + 1e-9 and -1e-9 <= tau <= 1 + 1e-9:
                sig, tau = min(max(sig, 0.0), 1.0), min(max(tau, 0.0), 1.0)
                out.append((i, sig, j, tau, (p[0] + rx * sig, p[1] + ry * sig)))
                continue
        # No crossing: the nearest pair of points, a hairpin's if the way
        # round between them is long enough.
        d0, t0, f0 = _point_on_seg(p, r, s)
        d1, t1, f1 = _point_on_seg(q, r, s)
        d2, t2, f2 = _point_on_seg(r, p, q)
        d3, t3, f3 = _point_on_seg(s, p, q)
        dist, sig, tau, u, v = min((d0, 0.0, t0, p, f0), (d1, 1.0, t1, q, f1),
                                   (d2, t2, 0.0, f2, r), (d3, t3, 1.0, f3, s))
        if dist > _OFFSET_TOL_MM:
            continue
        ai = cum[i] + sig * (cum[i + 1] - cum[i])
        aj = cum[j] + tau * (cum[j + 1] - cum[j])
        way_ij = aj - ai if not closed else min(aj - ai, cum[-1] - aj + ai)
        if way_ij > 10.0 * dist and way_ij > 2.0 * _OFFSET_TOL_MM:
            out.append((i, sig, j, tau, ((u[0] + v[0]) / 2.0, (u[1] + v[1]) / 2.0)))
    return out


def _refine_crossing(ca, s: float, cb, u: float):
    """Newton on ca(s) = cb(u) from the polyline's estimate. Returns
    (s, u, point), or None when it does not settle."""
    best = None
    for _ in range(30):
        pa, pb = _cubic_at(ca, s), _cubic_at(cb, u)
        fx, fy = pa[0] - pb[0], pa[1] - pb[1]
        err = math.hypot(fx, fy)
        if best is None or err < best[0]:
            best = (err, s, u, ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0))
        if err < 1e-12:
            break
        da, db = _cubic_deriv(ca, s), _cubic_deriv(cb, u)
        det = db[0] * da[1] - da[0] * db[1]
        if abs(det) < 1e-18:
            break
        s = min(max(s + (fx * db[1] - fy * db[0]) / det, 0.0), 1.0)
        u = min(max(u + (fx * da[1] - fy * da[0]) / det, 0.0), 1.0)
    if best[0] > 1e-6:
        return None
    return best[1], best[2], best[3]


def _cut_loop(cubics: list, closed: bool, ka: int, ta: float,
              kb: int, tb: float, at, inner: bool) -> list:
    """The chain with the stretch from (ka, ta) to (kb, tb) cut out, the two
    ends meeting at *at* (inner); or, for a closed chain, that stretch alone,
    closed at *at*."""
    if inner:
        left = _cubic_cut(cubics[ka], ta, at)[0]
        right = _cubic_cut(cubics[kb], tb, at)[1]
        pieces = cubics[:ka] + [left, right] + cubics[kb + 1:]
    elif ka == kb:
        rest = _cubic_cut(cubics[ka], ta, at)[1]
        pieces = [_cubic_cut(rest, (tb - ta) / (1.0 - ta), at)[0]]
    else:
        pieces = ([_cubic_cut(cubics[ka], ta, at)[1]] + cubics[ka + 1:kb]
                  + [_cubic_cut(cubics[kb], tb, at)[0]])
    return [c for c in pieces if not _cubic_tiny(c)]


def _cubics_curve(cubics: list, like: Curve) -> Curve:
    """A spline Curve through *cubics*, with *like*'s layer and weight; a
    retracted handle is no handle, as _curve_cubics reads it."""
    import dataclasses

    def _handle(p, base):
        same = abs(p[0] - base[0]) + abs(p[1] - base[1]) < 1e-12
        return None if same else ControlPoint(*p)

    nodes: List[SplineNode] = []
    for k, c in enumerate(cubics):
        nd = SplineNode(x=c[0][0], y=c[0][1])
        nd.cp_out = _handle(c[1], c[0])
        if k:
            nd.cp_in = _handle(cubics[k - 1][2], cubics[k - 1][3])
        nodes.append(nd)
    last = cubics[-1]
    if like.closed:
        nodes[0].cp_in = _handle(last[2], last[3])
    else:
        end = SplineNode(x=last[3][0], y=last[3][1])
        end.cp_in = _handle(last[2], last[3])
        nodes.append(end)
    return dataclasses.replace(like, nodes=nodes)


def _untangle_offset(source: Curve, off: Curve, d: float) -> Curve:
    """*off* with the loops its corners and tight bends make cut out, each
    pair of pieces trimmed where they cross into one sharp node.

    Such a loop turns against the offset side (*d*, signed along the
    left-hand normal), and one with no other crossing on it is cut first.
    A closed offset then keeps its main loop: an inward one also cuts a
    loop of the other side of a crossing (its corner loops turn against the
    shape, its main loop and any lobe with it); after that the smaller side
    of each crossing goes, a lobe pinched off or an outward offset's loop
    inside its main one. An open offset cuts corner and bend loops only,
    never a crossing of two far parts. *off* is returned unchanged when it
    does not cross itself, when *source* does, or when the result is not
    one clean loop. OffsetOutOfRange when the loops are more than the
    search's budget, or a closed offset turns inside out (an inward one past
    the shape's width)."""
    try:
        if off.kind != "spline" or len(off.nodes) < 2:
            return off
        closed = off.closed
        cubics = [c for c in _curve_cubics(off) if not _cubic_tiny(c)]
        if len(cubics) < 2:
            return off
        cut = False
        src_area = 0.0
        work = weighed = 0
        for _ in range(_LOOP_MAX_CUTS):
            verts, segs = _flatten_cubics(cubics)
            pairs: list = []
            hits = _chain_crossings(verts, closed, pairs)
            if not hits:
                break
            if not cut:
                src = flatten_curve(source, 0.01)
                ring = (_sg.LinearRing(src) if source.closed and len(src) >= 4
                        else _sg.LineString(src))
                if not ring.is_simple:
                    return off        # the source crosses itself: so may this
                if closed:
                    src_area = _signed_area_pts(
                        [(x, y) for x, y, _ in sample_curve(source)])
            work += len(verts)
            weighed += sum(pairs)
            if work > _LOOP_MAX_WORK or weighed > _LOOP_MAX_PAIRS:
                raise OffsetOutOfRange(_FOLDS_TOO_OFTEN)
            inward = closed and d * src_area > 0.0
            # The loop between two crossing segments, by its signed area: a
            # running shoelace sum, closed at the crossing point.
            run = [0.0]
            for g in range(len(verts) - 1):
                run.append(run[-1] + verts[g][0] * verts[g + 1][1]
                           - verts[g + 1][0] * verts[g][1])
            total = run[-1] / 2.0
            spans = [(i + sig, j + tau) for i, sig, j, tau, _x in hits]
            # Another crossing on a loop, by bisection: a crossing's own ends
            # never fall strictly inside or outside its span, so all of them
            # are counted (one by one this was the square of the crossings, a
            # minute and more when an offset far past its bends made thousands).
            ends = sorted(p for span in spans for p in span)
            best = None
            for k, (i, sig, j, tau, x) in enumerate(hits):
                vi, vj = verts[i + 1], verts[j]
                area = (x[0] * vi[1] - vi[0] * x[1] + run[j] - run[i + 1]
                        + vj[0] * x[1] - x[0] * vj[1]) / 2.0
                lo, hi = spans[k]
                bare_in = (bisect.bisect_left(ends, hi - 1e-9)
                           <= bisect.bisect_right(ends, lo + 1e-9))
                bare_out = (bisect.bisect_left(ends, lo - 1e-9) == 0
                            and bisect.bisect_right(ends, hi + 1e-9) == len(ends))
                sides = [(area, True, bare_in)]
                if closed:
                    sides.append((total - area, False, bare_out))
                for a, inner, bare in sides:
                    against = a * d < 0.0 or abs(a) < 1e-9
                    if bare and against and (inward or not closed):
                        cand = (0, abs(a), inner)
                        if best is None or cand < best[0]:
                            best = (cand, i, sig, j, tau, x)
                if closed:
                    inner = abs(area) <= abs(total - area)
                    cand = (1, min(abs(area), abs(total - area)), inner)
                    if best is None or cand < best[0]:
                        best = (cand, i, sig, j, tau, x)
            if best is None:
                break                 # an open curve's far parts crossing
            (_rank, _size, inner), i, sig, j, tau, x = best
            ka, a0, a1 = segs[i]
            kb, b0, b1 = segs[j]
            ta, tb = a0 + (a1 - a0) * sig, b0 + (b1 - b0) * tau
            exact = _refine_crossing(cubics[ka], ta, cubics[kb], tb)
            if (exact is not None and (ka != kb or exact[0] < exact[1])
                    and math.hypot(exact[2][0] - x[0], exact[2][1] - x[1])
                    < 20 * _LOOP_FLAT_TOL_MM):
                ta, tb, x = exact
            cubics = _cut_loop(cubics, closed, ka, ta, kb, tb, x, inner)
            cut = True
            if len(cubics) < (2 if closed else 1):
                if closed:
                    raise OffsetOutOfRange(_NOTHING_LEFT)
                return off
        else:
            raise OffsetOutOfRange(_FOLDS_TOO_OFTEN)
        if not cut:
            return off
        if closed:
            verts, _segs = _flatten_cubics(cubics)
            if _chain_crossings(verts, True):
                return off
            src_area = _signed_area_pts([(x, y) for x, y, _ in sample_curve(source)])
            if _signed_area_pts(verts) * src_area <= 0.0:
                raise OffsetOutOfRange(_NOTHING_LEFT)   # inward past the width
        return _cubics_curve(cubics, off)
    except OffsetOutOfRange:
        raise
    except Exception:
        return off


def _offset_leaves_nothing(curve: Curve, d_mm: float) -> bool:
    """An inward offset of a closed curve past its width, told before any
    offset is built: the drawn shape, shrunk by |d| (shapely's buffer), is
    empty. A shape that crosses itself is not judged."""
    if not curve.closed or d_mm >= 0.0:
        return False
    pts = flatten_curve(curve, 0.01)
    if len(pts) < 4:
        return False
    shape = _sg.Polygon(pts)
    return shape.is_valid and shape.buffer(d_mm).is_empty


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

    Raises OffsetOutOfRange when nothing of a closed spline or polyline would
    be left, or a spline's offset folds over itself too often to untangle
    (2.0.1: −10 mm on an open outline froze the window for minutes).
    """
    import copy as _copy

    if d_mm == 0.0:
        return _copy.deepcopy(curve)

    if curve.kind in ("circle", "arc"):
        c = _copy.deepcopy(curve)
        c.radius = max(0.0, (c.radius or 0.0) + d_mm)
        c.group_id = None      # the offset is its own curve, like a spline's
        return c

    nodes = curve.nodes
    n = len(nodes)
    if n < 2:
        return _copy.deepcopy(curve)

    closed = curve.closed
    if _offset_leaves_nothing(curve, d_mm):
        raise OffsetOutOfRange(_NOTHING_LEFT)

    if curve.kind != "line":
        th = _offset_spline(curve, d_mm)
        reduced = _reduce_offset_nodes(curve, d_mm, th)
        return _untangle_offset(curve, reduced if reduced is not None else th,
                                _offset_winding_d(curve, d_mm))

    # A repeated node is a zero-length segment with no normal: the node
    # beside it was left where it was, so that corner kept no clearance
    # (DXF import folds only a closing duplicate).
    nodes = [nd for i, nd in enumerate(nodes)
             if i == 0 or math.hypot(nd.x - nodes[i - 1].x,
                                     nd.y - nodes[i - 1].y) >= 1e-9]
    if closed and len(nodes) > 1 and math.hypot(
            nodes[-1].x - nodes[0].x, nodes[-1].y - nodes[0].y) < 1e-9:
        nodes = nodes[:-1]
    n = len(nodes)
    if n < 2:
        return _copy.deepcopy(curve)

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
        # +d must grow the shape whatever the winding: the side is the
        # winding's. It was chosen by which result had the larger area, and
        # past half a shape's size the inside-out inward one has: a 3.5 × 2
        # mm slot offset +3 came back 2.5 × 4, on one winding of the two
        # (the 2.3 sweep; one of a library front's two hinge slots).
        src = [(nd.x, nd.y) for nd in nodes]
        new_nodes = _line_nodes(-d_mm if _signed_area_pts(src) > 0 else d_mm)
        # A corner that passes another side (a lug narrower than twice the
        # distance) leaves the mitered polygon crossing itself, or turned
        # inside out: then the shape itself is grown or shrunk (shapely's
        # mitered buffer), which drops what the distance swallows. Nothing
        # is said to be in range that is not one clean outline.
        shape = _sg.Polygon(src)
        got = _sg.Polygon([(nd.x, nd.y) for nd in new_nodes])
        if shape.is_valid and not (got.is_valid and got.area > 0.0 and (
                _signed_area_pts([(nd.x, nd.y) for nd in new_nodes]) > 0)
                == (_signed_area_pts(src) > 0)):
            grown = shape.buffer(d_mm, join_style=2, mitre_limit=6.0)
            if grown.is_empty:
                raise OffsetOutOfRange(_NOTHING_LEFT)
            if grown.geom_type != "Polygon" or len(grown.interiors):
                raise OffsetOutOfRange(_SPLITS_SHAPE)
            ring = list(grown.exterior.coords)[:-1]
            if (_signed_area_pts(ring) > 0) != (_signed_area_pts(src) > 0):
                ring.reverse()                      # the source's own winding
            new_nodes = [SplineNode(x=float(x), y=float(y)) for x, y in ring]

    return Curve(kind="line", layer=curve.layer, nodes=new_nodes,
                 closed=closed, line_weight=curve.line_weight,
                 component_kind=curve.component_kind)


# ---------------------------------------------------------------------------
# Arc construction helpers
# ---------------------------------------------------------------------------

def arc_start_end_center(sx: float, sy: float,
                         ex: float, ey: float,
                         cx: float, cy: float):
    """Build a true circular arc from two endpoints and an approximate center.

    The clicked center is snapped onto the perpendicular bisector of the
    chord S→E so both endpoints lie on the circle (equal radii). The *minor*
    arc between the endpoints is always returned, so placing the center on
    one side of the chord vs. the other flips which way the arc bulges — an
    intuitive, predictable control.

    Returns ``(cx2, cy2, radius, start_deg, end_deg)`` in the scene angle
    convention (degrees; 0=right, 90=down-screen; sweep runs positive from
    start to end, matching :func:`point_at_t` / build_path), or ``None`` when
    the construction is degenerate (coincident endpoints, or a center that
    lands on the chord).
    """
    mx, my = (sx + ex) / 2.0, (sy + ey) / 2.0
    chord_dx, chord_dy = ex - sx, ey - sy
    chord_len2 = chord_dx * chord_dx + chord_dy * chord_dy
    if chord_len2 < 1e-12:
        return None   # endpoints coincide

    # Perpendicular bisector direction (unit), then project the clicked center
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
        center      arc center
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

    # Center lies along the angle bisector at distance r / sin(half).
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
    if (end_deg - start_deg) % 360 < 1e-6:
        return None                   # legs all but straight: a sweep this thin
                                      # was stored as 0 and read as a full circle
    return {
        "t1": t1, "t2": t2, "center": center, "radius": r,
        "start_deg": start_deg, "end_deg": end_deg, "tan_len": tan_len,
    }
