"""
Cubic-spline fitting engine (M30) — one Qt-free place to turn a dense point
sequence into a compact, editable cubic-Bézier ``Curve``.

Two consumers share this (M31): the Offset tool wants the accurate-but-node-
heavy parallel curve refit down to a handful of nodes, and the Rebuild Spline
tool wants an imported dense polyline (a DXF from another CAD app) rebuilt as a
few editable nodes. Both reduce to "fit cubics through points."

Core algorithm: Philip J. Schneider, *An Algorithm for Automatically Fitting
Digitized Curves* (Graphics Gems, 1990) — chord-length parameterisation,
least-squares control-point solve with prescribed end tangents, Newton–Raphson
reparameterisation, recursive split at the point of maximum error. The same
engine as Inkscape / paper.js ``simplify()``.

Two modes:

* **Tolerance** (``tol_mm``): the minimum nodes whose maximum deviation from
  the input stays within ``tol_mm``. Corners (tangent-angle jumps) are detected
  and preserved as sharp nodes; every other join is G1-smooth, including the
  seam of a closed curve.
* **Budget** (``n_nodes``): *exactly* ``n_nodes`` nodes, placed by a blended
  arc-length / curvature measure so curvy regions get more of them. The
  achieved maximum deviation is *reported* (never silently exceeded), so the
  UI can show the maker what a lower node count costs. Budget mode does not do
  corner detection — the maker chooses the node count.

All distances are millimetres (scene units). Endpoints are interpolated
exactly (a fit always passes through the first and last input point).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .document import Curve, SplineNode, ControlPoint, Layer

Pt = Tuple[float, float]

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_DEDUP_EPS_MM      = 1e-7   # consecutive points closer than this merge
_MAX_SPLIT_DEPTH   = 48     # recursion guard for the tolerance fit
_REPARAM_ITERS     = 8      # Newton–Raphson passes per fit attempt
_REPARAM_FACTOR    = 20.0   # only iterate when the first fit is within tol·this
_DEV_SAMPLES_SEG   = 24     # per-segment samples when measuring deviation
_CORNER_DEG        = 30.0   # default tangent-angle jump that marks a corner


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class FitResult:
    curve: Curve
    max_deviation_mm: float

    @property
    def n_nodes(self) -> int:
        return len(self.curve.nodes)


# ---------------------------------------------------------------------------
# Tiny 2-vector helpers ((x, y) tuples — no numpy dependency, interactive use)
# ---------------------------------------------------------------------------

def _add(a: Pt, b: Pt) -> Pt:   return (a[0] + b[0], a[1] + b[1])
def _sub(a: Pt, b: Pt) -> Pt:   return (a[0] - b[0], a[1] - b[1])
def _scale(a: Pt, s: float) -> Pt: return (a[0] * s, a[1] * s)
def _dot(a: Pt, b: Pt) -> float:   return a[0] * b[0] + a[1] * b[1]
def _norm(a: Pt) -> float:      return math.hypot(a[0], a[1])
def _dist(a: Pt, b: Pt) -> float:  return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(a: Pt) -> Pt:
    L = math.hypot(a[0], a[1])
    if L < 1e-12:
        return (0.0, 0.0)
    return (a[0] / L, a[1] / L)


def _angle_between(v1: Pt, v2: Pt) -> float:
    """Unsigned turn angle (radians) from v1 to v2."""
    return abs(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], _dot(v1, v2)))


# ---------------------------------------------------------------------------
# Bézier evaluation (control points as 4/3/2-tuples of Pt)
# ---------------------------------------------------------------------------

def _bez3(b: Sequence[Pt], u: float) -> Pt:
    v = 1.0 - u
    b0, b1, b2, b3 = v*v*v, 3*v*v*u, 3*v*u*u, u*u*u
    return (b0*b[0][0] + b1*b[1][0] + b2*b[2][0] + b3*b[3][0],
            b0*b[0][1] + b1*b[1][1] + b2*b[2][1] + b3*b[3][1])


def _bez2(b: Sequence[Pt], u: float) -> Pt:
    v = 1.0 - u
    b0, b1, b2 = v*v, 2*v*u, u*u
    return (b0*b[0][0] + b1*b[1][0] + b2*b[2][0],
            b0*b[0][1] + b1*b[1][1] + b2*b[2][1])


def _bez1(b: Sequence[Pt], u: float) -> Pt:
    v = 1.0 - u
    return (v*b[0][0] + u*b[1][0], v*b[0][1] + u*b[1][1])


# ---------------------------------------------------------------------------
# Schneider primitives
# ---------------------------------------------------------------------------

def _chord_param(pts: List[Pt]) -> List[float]:
    """Chord-length parameter values in [0, 1] for the point sequence."""
    u = [0.0]
    for i in range(1, len(pts)):
        u.append(u[-1] + _dist(pts[i], pts[i - 1]))
    total = u[-1]
    if total <= 0.0:
        n = len(pts)
        return [i / (n - 1) for i in range(n)] if n > 1 else [0.0]
    return [x / total for x in u]


def _two_point_cubic(p0: Pt, p1: Pt, t1: Pt, t2: Pt) -> List[Pt]:
    """Wu/Barsky heuristic: with only two samples, put handles one third of
    the chord along the prescribed tangents."""
    d = _dist(p0, p1) / 3.0
    return [p0, _add(p0, _scale(t1, d)), _add(p1, _scale(t2, d)), p1]


def _generate_bezier(pts: List[Pt], u: List[float], t1: Pt, t2: Pt) -> List[Pt]:
    """Least-squares fit of one cubic to *pts* at parameters *u*, with the
    endpoints pinned to pts[0]/pts[-1] and the handle directions fixed to the
    unit tangents t1 (from the start) and t2 (into the end)."""
    p0, p3 = pts[0], pts[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for i, ui in enumerate(u):
        v = 1.0 - ui
        b1 = 3 * ui * v * v
        b2 = 3 * ui * ui * v
        a0 = _scale(t1, b1)
        a1 = _scale(t2, b2)
        c00 += _dot(a0, a0)
        c01 += _dot(a0, a1)
        c11 += _dot(a1, a1)
        b0 = v * v * v
        b3 = ui * ui * ui
        base = (p0[0] * (b0 + b1) + p3[0] * (b2 + b3),
                p0[1] * (b0 + b1) + p3[1] * (b2 + b3))
        tmp = _sub(pts[i], base)
        x0 += _dot(a0, tmp)
        x1 += _dot(a1, tmp)

    det = c00 * c11 - c01 * c01
    seg_len = _dist(p0, p3)
    if abs(det) < 1e-12:
        alpha_l = alpha_r = seg_len / 3.0
    else:
        alpha_l = (x0 * c11 - x1 * c01) / det
        alpha_r = (c00 * x1 - c01 * x0) / det

    eps = 1e-6 * (seg_len if seg_len > 0 else 1.0)
    if alpha_l < eps or alpha_r < eps:
        # Degenerate least-squares solution — fall back to the chord/3 heuristic.
        alpha_l = alpha_r = seg_len / 3.0
    return [p0, _add(p0, _scale(t1, alpha_l)),
            _add(p3, _scale(t2, alpha_r)), p3]


def _newton(bez: List[Pt], p: Pt, u: float) -> float:
    """One Newton–Raphson step toward the parameter whose curve point is
    nearest to *p*."""
    q1 = [_scale(_sub(bez[i + 1], bez[i]), 3.0) for i in range(3)]
    q2 = [_scale(_sub(q1[i + 1], q1[i]), 2.0) for i in range(2)]
    qu = _bez3(bez, u)
    d = _sub(qu, p)
    q1u = _bez2(q1, u)
    q2u = _bez1(q2, u)
    num = _dot(d, q1u)
    den = _dot(q1u, q1u) + _dot(d, q2u)
    if abs(den) < 1e-12:
        return u
    return u - num / den


def _reparameterize(bez: List[Pt], pts: List[Pt], u: List[float]) -> List[float]:
    return [_newton(bez, pts[i], u[i]) for i in range(len(pts))]


def _max_error(pts: List[Pt], bez: List[Pt], u: List[float]) -> Tuple[float, int]:
    """Maximum distance (mm) from a sample to the fitted cubic, and the index
    of that worst sample (clamped to a strictly interior split point)."""
    worst = 0.0
    split = len(pts) // 2
    for i in range(len(pts)):
        d = _dist(_bez3(bez, u[i]), pts[i])
        if d > worst:
            worst, split = d, i
    split = max(1, min(len(pts) - 2, split))
    return worst, split


def _fit_span(pts: List[Pt], t1: Pt, t2: Pt, tol: float) -> List[List[Pt]]:
    """Schneider recursive fit of one span with prescribed end tangents.

    Internal splits reuse a shared centre tangent, so every join created here
    is G1-smooth. Returns an ordered list of cubics."""
    out: List[List[Pt]] = []

    def rec(span: List[Pt], a: Pt, b: Pt, depth: int) -> None:
        if len(span) < 2:
            return
        if len(span) == 2:
            out.append(_two_point_cubic(span[0], span[1], a, b))
            return
        u = _chord_param(span)
        bez = _generate_bezier(span, u, a, b)
        err, split = _max_error(span, bez, u)
        if err <= tol:
            out.append(bez)
            return
        if err <= tol * _REPARAM_FACTOR:
            for _ in range(_REPARAM_ITERS):
                u = _reparameterize(bez, span, u)
                bez = _generate_bezier(span, u, a, b)
                err, split = _max_error(span, bez, u)
                if err <= tol:
                    out.append(bez)
                    return
        if depth >= _MAX_SPLIT_DEPTH:
            out.append(bez)   # best effort — stop runaway recursion
            return
        centre = _unit(_sub(span[split - 1], span[split + 1]))
        if centre == (0.0, 0.0):
            centre = _unit(_sub(span[split], span[split + 1]))
        rec(span[:split + 1], a, centre, depth + 1)
        rec(span[split:], _scale(centre, -1.0), b, depth + 1)

    rec(pts, t1, t2, 0)
    return out


def _fit_single_cubic(span: List[Pt], t1: Pt, t2: Pt) -> List[Pt]:
    """Fit exactly one cubic (no splitting) — the budget-mode primitive."""
    if len(span) <= 2:
        return _two_point_cubic(span[0], span[-1], t1, t2)
    u = _chord_param(span)
    bez = _generate_bezier(span, u, t1, t2)
    for _ in range(_REPARAM_ITERS):
        u = _reparameterize(bez, span, u)
        bez = _generate_bezier(span, u, t1, t2)
    return bez


# ---------------------------------------------------------------------------
# Cubics → Curve
# ---------------------------------------------------------------------------

def _cubics_to_curve(cubics: List[List[Pt]], closed: bool,
                     layer: Layer, line_weight: float) -> Curve:
    """Assemble an ordered cubic chain (consecutive cubics share an endpoint)
    into a spline Curve. Smooth joins keep collinear handles; corners keep the
    independent handles they were fitted with."""
    nodes: List[SplineNode] = []
    first = SplineNode(x=cubics[0][0][0], y=cubics[0][0][1])
    first.cp_out = ControlPoint(*cubics[0][1])
    nodes.append(first)

    for prev, nxt in zip(cubics, cubics[1:], strict=False):
        nd = SplineNode(x=(prev[3][0] + nxt[0][0]) / 2.0,
                        y=(prev[3][1] + nxt[0][1]) / 2.0)
        nd.cp_in  = ControlPoint(*prev[2])
        nd.cp_out = ControlPoint(*nxt[1])
        nodes.append(nd)

    last = cubics[-1]
    if closed:
        # last cubic returns to the first node — fold its incoming handle in.
        nodes[0].cp_in = ControlPoint(*last[2])
    else:
        end = SplineNode(x=last[3][0], y=last[3][1])
        end.cp_in = ControlPoint(*last[2])
        nodes.append(end)

    return Curve(kind="spline", layer=layer, nodes=nodes,
                 closed=closed, line_weight=line_weight)


# ---------------------------------------------------------------------------
# Deviation measurement (honest — vs the ORIGINAL input points)
# ---------------------------------------------------------------------------

def _sample_fitted(curve: Curve) -> List[Pt]:
    """Dense polyline of the fitted spline for deviation checks."""
    nodes = curve.nodes
    if len(nodes) < 2:
        return [(nodes[0].x, nodes[0].y)] if nodes else []
    segs = []
    for i in range(len(nodes) - 1):
        segs.append((nodes[i], nodes[i + 1]))
    if curve.closed:
        segs.append((nodes[-1], nodes[0]))
    poly: List[Pt] = []
    for a, b in segs:
        p0 = (a.x, a.y)
        p1 = (a.cp_out.x, a.cp_out.y) if a.cp_out else p0
        p3 = (b.x, b.y)
        p2 = (b.cp_in.x, b.cp_in.y) if b.cp_in else p3
        bez = [p0, p1, p2, p3]
        for s in range(_DEV_SAMPLES_SEG):
            poly.append(_bez3(bez, s / _DEV_SAMPLES_SEG))
    poly.append((nodes[0].x, nodes[0].y) if curve.closed
                else (nodes[-1].x, nodes[-1].y))
    return poly


def _dist_to_polyline(p: Pt, poly: List[Pt]) -> float:
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


def _max_deviation(curve: Curve, points: List[Pt]) -> float:
    poly = _sample_fitted(curve)
    if len(poly) < 2:
        return 0.0
    return max(_dist_to_polyline(p, poly) for p in points)


# ---------------------------------------------------------------------------
# Corner detection + tangents at boundaries
# ---------------------------------------------------------------------------

def _detect_corners(pts: List[Pt], closed: bool, angle_deg: float) -> List[int]:
    n = len(pts)
    if n < 3:
        return []
    thresh = math.radians(angle_deg)
    corners: List[int] = []
    idxs = range(n) if closed else range(1, n - 1)
    for i in idxs:
        prev = pts[(i - 1) % n]
        cur  = pts[i]
        nxt  = pts[(i + 1) % n]
        v1, v2 = _sub(cur, prev), _sub(nxt, cur)
        if _norm(v1) < 1e-9 or _norm(v2) < 1e-9:
            continue
        if _angle_between(v1, v2) > thresh:
            corners.append(i)
    return corners


def _boundary_tangent(pts: List[Pt], i: int, closed: bool) -> Pt:
    """Unit tangent at boundary index *i*, pointing in the increasing-index
    direction. Interior/seam points use a central difference (→ G1); open
    endpoints use the one-sided chord (→ a corner if the neighbour spans meet
    at an angle)."""
    n = len(pts)
    if closed:
        if i == 0 or i == n - 1:
            return _unit(_sub(pts[1 % n], pts[(n - 2) % n]))
        return _unit(_sub(pts[i + 1], pts[i - 1]))
    if i <= 0:
        return _unit(_sub(pts[1], pts[0]))
    if i >= n - 1:
        return _unit(_sub(pts[n - 1], pts[n - 2]))
    return _unit(_sub(pts[i + 1], pts[i - 1]))


def _fit_between_corners(pts: List[Pt], boundaries: List[int],
                         tol: float) -> List[List[Pt]]:
    """Fit each span between consecutive boundary indices. At a corner
    boundary the two adjoining spans take independent one-sided tangents
    (sharp); the tolerance recursion keeps every within-span join G1."""
    cubics: List[List[Pt]] = []
    for a, b in zip(boundaries, boundaries[1:], strict=False):
        span = pts[a:b + 1]
        if len(span) < 2:
            continue
        t1 = _unit(_sub(span[1], span[0]))
        t2 = _unit(_sub(span[-2], span[-1]))
        cubics += _fit_span(span, t1, t2, tol)
    return cubics


# ---------------------------------------------------------------------------
# Budget-mode boundary placement
# ---------------------------------------------------------------------------

def _cumulative_measure(pts: List[Pt], blend: float = 0.6) -> List[float]:
    """Cumulative arc length blended with cumulative turning, so knots placed
    at equal increments cluster where the curve bends."""
    n = len(pts)
    arc = [0.0]
    for i in range(1, n):
        arc.append(arc[-1] + _dist(pts[i], pts[i - 1]))
    turn = [0.0] * n
    total_turn = 0.0
    for i in range(1, n - 1):
        v1, v2 = _sub(pts[i], pts[i - 1]), _sub(pts[i + 1], pts[i])
        a = (_angle_between(v1, v2)
             if _norm(v1) > 1e-9 and _norm(v2) > 1e-9 else 0.0)
        total_turn += a
        turn[i] = turn[i - 1] + a
    if n >= 2:
        turn[n - 1] = turn[n - 2]
    total_arc = arc[-1]
    if total_turn <= 1e-9 or total_arc <= 0.0:
        return arc
    k = blend * total_arc / total_turn
    return [arc[i] + k * turn[i] for i in range(n)]


def _equal_measure_indices(measure: List[float], count: int) -> List[int]:
    """*count* strictly increasing indices into *measure*, spaced at equal
    measure increments, always including the first and last index."""
    L = len(measure)
    total = measure[-1]
    res = [0]
    if total <= 0.0:
        # Degenerate — evenly spaced by index.
        for k in range(1, count - 1):
            res.append(round(k * (L - 1) / (count - 1)))
        res.append(L - 1)
        return res
    for k in range(1, count - 1):
        tgt = k * total / (count - 1)
        j = res[-1] + 1
        while j < L - 1 and measure[j] < tgt:
            j += 1
        # Leave at least one index per remaining boundary.
        j = min(j, L - 1 - (count - 1 - k))
        j = max(j, res[-1] + 1)
        res.append(j)
    res.append(L - 1)
    return res


def _ensure_min_points(pts: List[Pt], min_count: int) -> List[Pt]:
    """Linearly up-sample the polyline so it has at least *min_count* points —
    guarantees budget mode can always carve the requested segment count."""
    if len(pts) >= min_count:
        return pts
    seg = len(pts) - 1
    if seg <= 0:
        return pts
    per = math.ceil((min_count - 1) / seg)
    out: List[Pt] = [pts[0]]
    for i in range(seg):
        a, b = pts[i], pts[i + 1]
        for s in range(1, per + 1):
            t = s / per
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _fit_budget(pts: List[Pt], n_nodes: int, closed: bool,
                layer: Layer, line_weight: float) -> FitResult:
    n_seg = (n_nodes if closed else n_nodes - 1)
    n_seg = max(1, n_seg)

    work = pts + [pts[0]] if closed else list(pts)
    work = _ensure_min_points(work, n_seg + 1)
    boundaries = _equal_measure_indices(_cumulative_measure(work), n_seg + 1)

    cubics: List[List[Pt]] = []
    for a, b in zip(boundaries, boundaries[1:], strict=False):
        span = work[a:b + 1]
        if len(span) < 2:
            span = [work[a], work[min(a + 1, len(work) - 1)]]
        t1 = _boundary_tangent(work, a, closed)
        t2 = _scale(_boundary_tangent(work, b, closed), -1.0)
        cubics.append(_fit_single_cubic(span, t1, t2))

    curve = _cubics_to_curve(cubics, closed, layer, line_weight)
    return FitResult(curve, _max_deviation(curve, list(pts)))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _prep(points: Sequence[Pt], closed: bool) -> List[Pt]:
    pts = [(float(p[0]), float(p[1])) for p in points]
    out = [pts[0]] if pts else []
    for p in pts[1:]:
        if _dist(p, out[-1]) > _DEDUP_EPS_MM:
            out.append(p)
    if closed and len(out) >= 2 and _dist(out[0], out[-1]) <= _DEDUP_EPS_MM:
        out.pop()   # drop a duplicated seam point; closure is implicit
    return out


def fit_curve(points: Sequence[Pt], *,
              tol_mm: float | None = None,
              n_nodes: int | None = None,
              closed: bool = False,
              corner_angle_deg: float = _CORNER_DEG,
              layer: Layer = Layer.OUTLINE,
              line_weight: float = 1.5) -> FitResult:
    """Fit a compact cubic spline through *points*.

    Provide exactly one of ``tol_mm`` (tolerance mode) or ``n_nodes`` (budget
    mode, exact node count). Returns a :class:`FitResult` carrying the fitted
    ``Curve`` and the maximum deviation (mm) of the input points from it.
    """
    if (tol_mm is None) == (n_nodes is None):
        raise ValueError("fit_curve: pass exactly one of tol_mm or n_nodes")

    pts = _prep(points, closed)
    if len(pts) < 2:
        node = SplineNode(x=pts[0][0], y=pts[0][1]) if pts else SplineNode(x=0.0, y=0.0)
        return FitResult(Curve(kind="spline", layer=layer, nodes=[node],
                               closed=False, line_weight=line_weight), 0.0)

    if n_nodes is not None:
        n = max(2, int(n_nodes))
        return _fit_budget(pts, n, closed, layer, line_weight)

    tol = max(1e-6, float(tol_mm))

    if closed:
        corners = _detect_corners(pts, True, corner_angle_deg)
        if not corners:
            seam = _unit(_sub(pts[1], pts[-1]))
            cubics = _fit_span(pts + [pts[0]], seam, _scale(seam, -1.0), tol)
        else:
            c0 = corners[0]
            rot = pts[c0:] + pts[:c0]
            n = len(pts)
            rot_corners = sorted({(c - c0) % n for c in corners})   # includes 0
            aug = rot + [rot[0]]
            boundaries = rot_corners + [len(aug) - 1]
            cubics = _fit_between_corners(aug, boundaries, tol)
    else:
        corners = _detect_corners(pts, False, corner_angle_deg)
        boundaries = [0] + corners + [len(pts) - 1]
        cubics = _fit_between_corners(pts, boundaries, tol)

    if not cubics:
        seam = _unit(_sub(pts[1], pts[0]))
        cubics = [_two_point_cubic(pts[0], pts[-1], seam, _scale(seam, -1.0))]

    curve = _cubics_to_curve(cubics, closed, layer, line_weight)
    return FitResult(curve, _max_deviation(curve, pts))
