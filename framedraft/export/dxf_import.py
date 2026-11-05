"""
DXF import — bring foreign DXF geometry into a GuildDraw workspace.

This is the inverse of ``export/dxf.py``.  Where the exporter negates Y
(scene Y-down -> DXF Y-up) and swaps+negates arc angles, the importer undoes
both so imported geometry sits upright in the scene.

Layer policy (the migration on-ramp): a DXF entity whose layer name matches a
GuildDraw layer that is *valid for the target workspace* keeps that layer;
every other entity is dropped onto ``active_layer`` and reported in the returned
notes, so the maker can re-file it by dragging rows in the Layers panel. Inside
a block, an entity keeps its own layer; one on layer 0 takes the INSERT's, as
in CAD. Entities on a layer that is off or frozen are left out, with a note.

Units: coordinates are read as millimeters (GuildDraw's scene unit) unless the
file's $INSUNITS names another unit and the drawing comes out a plausible size
in it (see _unit_scale): ezdxf and several exporters stamp "meters" on drawings
made in millimeters, and an eyewear part a thousand times too big helps no one.
Every unit decision is reported in the notes, as is a drawing read as
millimeters that comes out no size an eyewear part comes in. The unit is
settled before any curve is made, so every tolerance below is a length in
millimeters whatever the file's units (until 2.0.1 they were taken in the
file's units: a lens drawn in meters came in 0.6 mm off).

Supported entities: LINE, LWPOLYLINE, POLYLINE (2D), SPLINE, CIRCLE, ARC,
ELLIPSE, and INSERT (block references, expanded with their transform; a
MINSERT array cell by cell).  Curves convert exactly where an exact cubic
form exists (a clamped spline of degree 1 to 3, a straight or bulged
polyline, an ellipse to within a micron); a
rational, periodic or higher-degree spline is fitted to within 0.01 mm, with
as many nodes as that takes (a 64-node cap put a temple 1.4 to 2.7 mm off).
Entities written in a mirrored OCS (extrusion 0,0,-1 — what AutoCAD's MIRROR
command produces, and what a mirrored INSERT hands back) are first converted to
WCS so they land where the CAD file shows them.  Unsupported entity types (3D
polylines, meshes, text, hatches…) are counted and reported, never silently
dropped.
"""
from __future__ import annotations

import math

import ezdxf

from ..document import (
    ALL_LAYER_NAMES,
    Curve,
    ControlPoint,
    Layer,
    SplineNode,
    WORKSPACE_LAYERS,
)
from ..geometry import curve_is_finite

# A curve with no exact cubic form is fitted to this tolerance (mm), through
# points sampled this finely (the chord error of the sampling, mm). Each
# length here is in millimeters and is turned into the file's units (see
# _unit_scale) wherever it is held against the file's coordinates.
_FIT_TOL_MM = 0.005
_SAMPLE_MM = 0.002
_CLOSE_MM = 1e-3     # a curve whose ends are this close is closed
_SEAM_MM = 1e-4      # a closed polyline's repeated first vertex is folded within this
_ROUND_MM = 1e-3     # a closed spline this near one circle is that circle
_PERIODIC_STEP_MM = 0.2   # the sample spacing on a periodic spline
# Block expansion limits: an 18 KB file of nested blocks expanded to 10,000
# curves, and a block that inserts itself ran into Python's recursion limit.
# Curves alone bound nothing when the blocks hold text, or entities on a
# layer that is off: a 21 KB file of them read for 9 s, and one a level
# deeper never finished. Every entity read counts, each copy a block
# reference makes of its block's entities included.
_MAX_CURVES = 20000
_MAX_DEPTH = 16
_MAX_VISITS = 200_000
# The size range (mm, the larger side) a drawing must land in for its stated
# unit to be believed: anything from a small component to a front with its
# temples laid out beside it. Until 2.0.1 it ran from 1 mm to 2 m, and a
# 50 mm lens in a file stamped inches came in 1.27 m across.
_PLAUSIBLE_MM = (3.0, 300.0)


def _sn(x: float, y: float) -> SplineNode:
    """SplineNode at a DXF point, negating Y (DXF Y-up -> scene Y-down)."""
    return SplineNode(x=float(x), y=-float(y))


def _cp(p) -> ControlPoint:
    return ControlPoint(float(p[0]), -float(p[1]))


# ---------------------------------------------------------------------------
# Per-entity handlers — each returns list[Curve] (possibly empty), or None to
# decline the entity variant (reported as unsupported). Curves come back in
# the file's units, for import_dxf to scale once; *unit* is the millimeters in
# one of them, for the handlers whose tolerances are lengths.
# ---------------------------------------------------------------------------

def _line_to_curve(e, layer: Layer, unit: float = 1.0) -> list[Curve]:
    s, t = e.dxf.start, e.dxf.end
    return [Curve(kind="line", layer=layer,
                  nodes=[_sn(s.x, s.y), _sn(t.x, t.y)], closed=False)]


def _circle_to_curve(e, layer: Layer, unit: float = 1.0) -> list[Curve]:
    c = e.dxf.center
    return [Curve(kind="circle", layer=layer, nodes=[_sn(c.x, c.y)],
                  radius=float(e.dxf.radius), closed=True)]


def _arc_to_curve(e, layer: Layer, unit: float = 1.0) -> list[Curve]:
    # Inverse of export: export wrote start_dxf=(-end_scene)%360,
    # end_dxf=(-start_scene)%360, so undo with the same swap+negate.
    c = e.dxf.center
    start_scene = (-float(e.dxf.end_angle)) % 360
    end_scene = (-float(e.dxf.start_angle)) % 360
    return [Curve(kind="arc", layer=layer, nodes=[_sn(c.x, c.y)],
                  radius=float(e.dxf.radius),
                  start_angle=start_scene, end_angle=end_scene, closed=False)]


def _nodes_from_bezier_segments(segs: list, closed: bool,
                                unit: float = 1.0) -> list[SplineNode]:
    """Build spline nodes from cubic Bézier segments (exact inverse of
    ``bezier_to_bspline`` used on export).  Consecutive segments share an
    endpoint, so each appended end-node becomes the next segment's start."""
    nodes: list[SplineNode] = []
    for i, seg in enumerate(segs):
        p0, p1, p2, p3 = list(seg)
        if i == 0:
            n0 = _sn(p0[0], p0[1])
            n0.cp_out = _cp(p1)
            nodes.append(n0)
        else:
            nodes[-1].cp_out = _cp(p1)
        n_end = _sn(p3[0], p3[1])
        n_end.cp_in = _cp(p2)
        nodes.append(n_end)

    # A closed spline's final wrap segment ends back at the first node; fold the
    # duplicate away and hand its incoming handle to the first node.
    if closed and len(nodes) >= 2:
        first, last = nodes[0], nodes[-1]
        if math.hypot(last.x - first.x, last.y - first.y) < _CLOSE_MM / unit:
            first.cp_in = last.cp_in
            nodes.pop()
    return nodes


def _ends_meet(pts: list, unit: float = 1.0) -> bool:
    return len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < _CLOSE_MM / unit


def _as_circle(pts: list, unit: float = 1.0) -> tuple[float, float, float] | None:
    """(cx, cy, r) when the closed sample *pts* lie on one circle to within a
    micron — a NURBS circle, which is how several CAD programs write a round
    lens; it imported as an open 64-node spline 0.06 mm off."""
    import numpy as np
    a = np.array([(x, y) for x, y in pts], dtype=float)
    if len(a) < 8:
        return None
    m = np.column_stack([2 * a[:, 0], 2 * a[:, 1], np.ones(len(a))])
    rhs = (a ** 2).sum(axis=1)
    (cx, cy, c), *_ = np.linalg.lstsq(m, rhs, rcond=None)
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    dev = np.abs(np.hypot(a[:, 0] - cx, a[:, 1] - cy) - r).max()
    return (float(cx), float(cy), r) if dev < _ROUND_MM / unit else None


def _fitted(pts: list, layer: Layer, closed: bool, unit: float = 1.0) -> list[Curve]:
    """A cubic spline fitted to the DXF-space samples *pts* within
    _FIT_TOL_MM, with as many nodes as that takes. The fit runs in
    millimeters, since fit_curve's own lengths are millimeters too (its
    0.01 mm hairline merge would have been a centimeter in meters), and the
    curve goes back in the file's units, as every handler's does."""
    from ..fitting import fit_curve
    pts = [(float(x) * unit, -float(y) * unit) for x, y in pts]
    if closed and _ends_meet(pts):
        pts = pts[:-1]
    if len(pts) < 2:
        return []
    fit = fit_curve(pts, tol_mm=_FIT_TOL_MM, closed=closed, layer=layer)
    if len(fit.curve.nodes) < 2:
        return []
    if unit != 1.0:
        _scale(fit.curve, 1.0 / unit)
    return [fit.curve]


def _unclamped_points(ct, unit: float = 1.0) -> list:
    """Sample an UNCLAMPED (periodic) B-spline over its valid parameter
    domain [knots[degree], knots[count]]. ezdxf's flattening runs the whole
    knot range, and outside the domain the curve shoots off to nowhere."""
    knots = list(ct.knots())
    p, n = ct.degree, ct.count
    t0, t1 = knots[p], knots[n]
    cps = list(ct.control_points)
    length = sum(math.dist((a.x, a.y), (b.x, b.y))
                 for a, b in zip(cps, cps[1:] + cps[:1], strict=True))
    # 0.2 mm apart: the fit's time grows with the samples, and closer ones
    # bought no accuracy on a smooth curve.
    steps = max(256, min(4000, int(length * unit / _PERIODIC_STEP_MM)))
    return [(q.x, q.y) for q in
            ct.points([t0 + (t1 - t0) * i / steps for i in range(steps + 1)])]


def _spline_to_curve(e, layer: Layer, unit: float = 1.0) -> list[Curve]:
    ct = e.construction_tool()
    closed = bool(getattr(e, "closed", False)) or bool(e.dxf.flags & 1)
    if ct.is_clamped and not ct.is_rational and 1 <= ct.degree <= 3:
        # Exact: a lower degree is raised to cubic without changing the
        # curve, and a clamped cubic is a run of Bézier segments.
        if ct.degree < 3:
            ct = ct.degree_elevation(3 - ct.degree)
        try:
            segs = [[(p.x, p.y) for p in seg] for seg in ct.bezier_decomposition()]
        except (TypeError, ValueError):
            segs = None
        if segs:
            closed = closed or math.dist(segs[0][0], segs[-1][-1]) < _CLOSE_MM / unit
            nodes = _nodes_from_bezier_segments(segs, closed, unit)
            if len(nodes) < 2:
                return []
            return [Curve(kind="spline", layer=layer, nodes=nodes, closed=closed)]
    # No exact cubic form: a periodic spline (how Rhino and AutoCAD write a
    # closed one; bezier_decomposition raised and aborted the whole import), a
    # rational one (a NURBS circle or conic) or one above cubic. Fit it.
    if not ct.is_clamped:
        pts = _unclamped_points(ct, unit)
    else:
        pts = [(p.x, p.y) for p in ct.flattening(_SAMPLE_MM / unit)]
    closed = closed or _ends_meet(pts, unit)
    if closed:
        round_ = _as_circle(pts[:-1] if _ends_meet(pts, unit) else pts, unit)
        if round_ is not None:
            cx, cy, r = round_
            return [Curve(kind="circle", layer=layer, nodes=[_sn(cx, cy)],
                          radius=r, closed=True)]
    return _fitted(pts, layer, closed, unit)


def _ellipse_to_curve(e, layer: Layer, unit: float = 1.0) -> list[Curve]:
    """Cubic arcs, two to a quarter: within a micron of the ellipse on any
    eyewear part (it was sampled and cut to 64 nodes)."""
    from ezdxf.math import cubic_bezier_from_ellipse
    ce = e.construction_tool()
    span = (e.dxf.end_param - e.dxf.start_param) % (2 * math.pi) or 2 * math.pi
    closed = abs(span - 2 * math.pi) < 1e-6
    n = max(1, math.ceil(8 * span / (2 * math.pi)))
    segs = [[(p.x, p.y) for p in bz.control_points]
            for bz in cubic_bezier_from_ellipse(ce, segments=n)]
    nodes = _nodes_from_bezier_segments(segs, closed, unit)
    if len(nodes) < 2:
        return []
    return [Curve(kind="spline", layer=layer, nodes=nodes, closed=closed)]


# ---------------------------------------------------------------------------
# Polylines (LWPOLYLINE / 2D POLYLINE): one curve per polyline. A straight one
# is a line curve; one with bulges a spline whose straight runs carry no
# handles and whose bulges are cubic arcs of at most 90°. Expanded into its
# lines and arcs, a rounded-rectangle lens (the commonest closed CAD shape)
# arrived as 8 open pieces to join by hand.
# ---------------------------------------------------------------------------

def _straight_polyline(coords: list, layer: Layer, closed: bool,
                       unit: float = 1.0) -> list[Curve]:
    """A bulge-free polyline as one line Curve.

    A closed polyline that repeats its first vertex as its last — how most
    converters write one, the DXF flag notwithstanding — would otherwise carry
    a zero-length closing segment: a node sitting on its neighbor, which
    Rebuild fitted as a hairline cubic and left as a self-intersecting seam
    that GuildModel could not fill (2026-10-05). Fold it; the closure is implicit."""
    pts = [(x, y) for (x, y, _b) in coords]
    if closed and len(pts) > 2 and math.dist(pts[0], pts[-1]) < _SEAM_MM / unit:
        pts = pts[:-1]
    nodes = [_sn(x, y) for (x, y) in pts]
    if len(nodes) < 2:
        return []
    return [Curve(kind="line", layer=layer, nodes=nodes, closed=closed)]


def _bulge_arc(p, q, bulge: float) -> list:
    """The arc from *p* to *q* with DXF *bulge* (tan of a quarter of the
    included angle, counter-clockwise positive) as cubic Bézier segments
    [(p0, p1, p2, p3), ...] of at most 90° each, in DXF coordinates."""
    (px, py), (qx, qy) = p, q
    dx, dy = qx - px, qy - py
    chord = math.hypot(dx, dy)
    theta = 4.0 * math.atan(bulge)
    # The center sits on the chord's perpendicular bisector, to the left of
    # p→q for a counter-clockwise minor arc.
    k = (1.0 - bulge * bulge) / (4.0 * bulge)
    cx, cy = (px + qx) / 2 - k * dy, (py + qy) / 2 + k * dx
    r = math.hypot(px - cx, py - cy)
    a0 = math.atan2(py - cy, px - cx)
    n = max(1, math.ceil(abs(theta) / (math.pi / 2) - 1e-9))
    step = theta / n
    h = 4.0 / 3.0 * math.tan(step / 4.0) * r
    out = []
    for i in range(n):
        a, b = a0 + i * step, a0 + (i + 1) * step
        p0 = (cx + r * math.cos(a), cy + r * math.sin(a))
        p3 = (cx + r * math.cos(b), cy + r * math.sin(b))
        if i == n - 1:
            p3 = (qx, qy)                  # land exactly on the next vertex
        p1 = (p0[0] - h * math.sin(a), p0[1] + h * math.cos(a))
        p2 = (p3[0] + h * math.sin(b), p3[1] - h * math.cos(b))
        out.append((p0, p1, p2, p3))
    return out if chord > 1e-12 else []


def _bulged_polyline(coords: list, layer: Layer, closed: bool,
                     unit: float = 1.0) -> list[Curve]:
    pts = list(coords)
    if closed and len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < _SEAM_MM / unit:
        pts[-1:] = []                      # the repeat; its bulge is on the one before
    if len(pts) < 2:
        return []
    nodes = [_sn(pts[0][0], pts[0][1])]
    count = len(pts) if closed else len(pts) - 1
    for i in range(count):
        x0, y0, b = pts[i]
        x1, y1, _b = pts[(i + 1) % len(pts)]
        wraps = closed and i == len(pts) - 1
        if abs(b) < 1e-9:
            if not wraps:
                nodes.append(_sn(x1, y1))
            continue
        for _p0, p1, p2, p3 in _bulge_arc((x0, y0), (x1, y1), b):
            nodes[-1].cp_out = _cp(p1)
            end = nodes[0] if (wraps and (p3[0], p3[1]) == (x1, y1)) else _sn(*p3)
            end.cp_in = _cp(p2)
            if end is not nodes[0]:
                nodes.append(end)
    return [Curve(kind="spline", layer=layer, nodes=nodes, closed=closed)]


def _lwpolyline_to_curves(e, layer: Layer, unit: float = 1.0) -> list[Curve]:
    pts = list(e.get_points("xyb"))   # (x, y, bulge)
    if all(abs(b) < 1e-9 for (_x, _y, b) in pts):
        return _straight_polyline(pts, layer, bool(e.closed), unit)
    return _bulged_polyline(pts, layer, bool(e.closed), unit)


def _polyline_to_curves(e, layer: Layer, unit: float = 1.0):
    if e.get_mode() != "AcDb2dPolyline":
        return None   # 3D polylines / polymeshes: reported as unsupported
    coords = [(v.dxf.location.x, v.dxf.location.y, v.dxf.bulge or 0.0)
              for v in e.vertices]
    if all(abs(b) < 1e-9 for (_x, _y, b) in coords):
        return _straight_polyline(coords, layer, bool(e.is_closed), unit)
    return _bulged_polyline(coords, layer, bool(e.is_closed), unit)


_DISPATCH = {
    "LINE": _line_to_curve,
    "CIRCLE": _circle_to_curve,
    "ARC": _arc_to_curve,
    "SPLINE": _spline_to_curve,
    "ELLIPSE": _ellipse_to_curve,
    "LWPOLYLINE": _lwpolyline_to_curves,
    "POLYLINE": _polyline_to_curves,
}


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def _outline_points(e) -> list:
    """Points whose bounding box is near enough *e*'s for the unit check, in
    the file's units: a line's ends, the square about a circle or an arc, 17
    points along an ellipse, a spline's control points (its fit points when
    it has none), a polyline's vertices. The unit is settled from these
    before any curve is made, since it sets the tolerances curves are made to."""
    t = e.dxftype()
    if t == "LINE":
        return [e.dxf.start, e.dxf.end]
    if t in ("CIRCLE", "ARC"):
        c, r = e.dxf.center, float(e.dxf.radius)
        return [(c.x - r, c.y - r), (c.x + r, c.y + r)]
    if t == "ELLIPSE":
        return list(e.vertices(e.params(17)))
    if t == "SPLINE":
        return list(e.control_points) or list(e.fit_points)
    if t == "LWPOLYLINE":
        return list(e.get_points("xy"))
    if t == "POLYLINE" and e.get_mode() == "AcDb2dPolyline":
        return [v.dxf.location for v in e.vertices]
    return []


def _size(entities) -> float | None:
    """The drawing's larger side in the file's units, None when there is
    nothing to measure. A point that is not a number is passed over: its
    curve is left out, with a note of its own."""
    xs, ys = [], []
    for e in entities:
        try:
            pts = _outline_points(e)
        except Exception:
            continue                       # a degenerate entity: its handler reports it
        for p in pts:
            x, y = float(p[0]), float(p[1])
            if math.isfinite(x) and math.isfinite(y):
                xs.append(x)
                ys.append(y)
    return max(max(xs) - min(xs), max(ys) - min(ys)) if xs else None


_UNIT_NAMES = {1: "inches", 2: "feet", 3: "miles", 5: "centimeters",
               6: "meters", 7: "kilometers", 8: "microinches", 9: "mils",
               10: "yards", 13: "microns", 14: "decimeters"}


def _across(mm: float) -> str:
    """A size for a note: in meters from a meter up, else in millimeters."""
    return f"{mm / 1000:.4g} m" if mm >= 1000 else f"{mm:.4g} mm"


def _outside(mm: float) -> str:
    lo, hi = _PLAUSIBLE_MM
    return f"{_across(mm)} across, outside the {lo:g} to {hi:g} mm of an eyewear drawing"


def _doubt(mm: float) -> str:
    """What a note adds when a drawing read as millimeters is no plausible
    size either, else ''."""
    lo, hi = _PLAUSIBLE_MM
    if lo <= mm <= hi:
        return ""
    return f" As millimeters the drawing is {_outside(mm)}. Check the units it was drawn in."


def _unit_scale(doc, size: float | None) -> tuple[float, str | None]:
    """(millimeters in one of the file's units, note) for the file's
    $INSUNITS and *size*, the drawing's larger side in those units.

    A stated unit is used when the drawing comes out a plausible size in it;
    otherwise the drawing is read as millimeters. A drawing read as
    millimeters that comes out no plausible size either keeps its numbers,
    since nothing is rescaled on a guess, and the note asks for its units to
    be checked: until 2.0.1 a file stamped millimeters went unchecked, and a
    lens drawn in meters came in 0.05 mm across without a word."""
    from ezdxf import units
    if size is None:
        return 1.0, None
    lo, hi = _PLAUSIBLE_MM
    code = doc.units
    if code == units.MM:
        if lo <= size <= hi:
            return 1.0, None
        return 1.0, (f"The DXF is drawn in millimeters, but the drawing is "
                     f"{_outside(size)}; it was imported as drawn. Check the "
                     "units it was drawn in.")
    name = _UNIT_NAMES.get(code) or (units.decode(code) if code else None)
    if not code or not name:
        return 1.0, ("The DXF states no drawing units; it was read as millimeters."
                     + _doubt(size))
    try:
        factor = units.conversion_factor(code, units.MM)
    except Exception:
        return 1.0, (f"The DXF's units ({name}) were not understood; it was read "
                     "as millimeters." + _doubt(size))
    if lo <= size * factor <= hi:
        return factor, (f"The DXF is drawn in {name}: it was scaled to millimeters "
                        f"(×{factor:g}).")
    return 1.0, (f"The DXF says it is drawn in {name}, but at that scale the drawing "
                 f"would be {_across(size * factor)} across; it was read as "
                 "millimeters." + _doubt(size))


def _scale(c: Curve, f: float) -> None:
    for n in c.nodes:
        n.x, n.y = n.x * f, n.y * f
        if n.cp_in:
            n.cp_in = ControlPoint(n.cp_in.x * f, n.cp_in.y * f)
        if n.cp_out:
            n.cp_out = ControlPoint(n.cp_out.x * f, n.cp_out.y * f)
    if c.radius is not None:
        c.radius *= f


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def _cells(e):
    """The INSERTs a MINSERT array places, one to a cell, as ezdxf's
    multi_insert() yields them. A zero spacing stacks a row or a column on
    one spot, which multi_insert() places once but still walks cell by cell
    (32767 x 32767 of them in a hostile file): its count is cut to one first."""
    grid = e.copy()
    if not grid.dxf.row_spacing:
        grid.dxf.row_count = 1
    if not grid.dxf.column_spacing:
        grid.dxf.column_count = 1
    return grid.multi_insert()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _read_doc(path: str):
    """Read a DXF, falling back to ezdxf's recover mode for damaged files."""
    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        from ezdxf import recover
        doc, _auditor = recover.readfile(path)
        return doc


def import_dxf(
    path: str,
    active_layer: Layer,
    workspace_type: str = "front",
) -> tuple[list[Curve], list[str]]:
    """Read *path* and return (curves, notes).

    Recognized layer names valid for *workspace_type* are kept; everything else
    lands on *active_layer*.  *notes* are human-readable status strings about
    re-filing, units, and anything left out.
    """
    from ezdxf import upright as _upright
    doc = _read_doc(path)
    msp = doc.modelspace()
    # Entities in a mirrored OCS (extrusion 0,0,-1) would otherwise be read as
    # if their OCS coordinates were WCS and land x-mirrored.
    try:
        _upright.upright_all(msp)
    except Exception:
        pass
    allowed = set(WORKSPACE_LAYERS.get(workspace_type, list(Layer)))
    hidden = {lay.dxf.name.upper() for lay in doc.layers
              if lay.is_off() or lay.is_frozen()}

    leaves: list = []                  # (entity, layer name) for a handler, blocks expanded
    dumped: dict[str, int] = {}        # original layer name -> count placed on active
    unsupported: dict[str, int] = {}   # dxftype -> count
    left_out = {"hidden": 0, "nonfinite": 0}
    stopped: set[str] = set()          # "depth" / "count" / "work"
    visits = 0

    def full() -> bool:
        return "count" in stopped or "work" in stopped

    def visit(e, parent_layer: str | None, depth: int) -> None:
        nonlocal visits
        if len(leaves) >= _MAX_CURVES:
            stopped.add("count")
            return
        visits += 1
        if visits > _MAX_VISITS:
            stopped.add("work")
            return
        name = (e.dxf.layer or "0").upper()
        if name == "0" and parent_layer is not None:
            name = parent_layer            # layer 0 in a block takes the INSERT's
        if name in hidden:
            left_out["hidden"] += 1
            return
        dxftype = e.dxftype()
        if dxftype == "INSERT":
            if depth >= _MAX_DEPTH:
                stopped.add("depth")
                return
            # One part at a time, so the count above stops a block's copies
            # as they are made, not after the whole block is copied.
            try:
                if e.mcount > 1:
                    # A MINSERT array: virtual_entities() reads its first cell
                    # only, and a 2 x 5 drill grid came in as one hole.
                    for cell in _cells(e):
                        visit(cell, parent_layer, depth)
                        if full():
                            break
                    return
                for ve in e.virtual_entities():
                    try:
                        _upright.upright(ve)   # a mirrored INSERT's arcs and circles
                    except Exception:
                        pass
                    visit(ve, name, depth + 1)
                    if full():
                        break
            except Exception:
                unsupported[dxftype] = unsupported.get(dxftype, 0) + 1
            return
        if dxftype not in _DISPATCH:
            unsupported[dxftype] = unsupported.get(dxftype, 0) + 1
            return
        leaves.append((e, name))

    for e in msp:
        if full():
            break
        visit(e, None, 0)

    # The unit first, from the entities, so the curves are made to tolerances
    # in millimeters; then one scale to millimeters.
    unit, unit_note = _unit_scale(doc, _size(e for e, _name in leaves))
    curves: list[Curve] = []
    for e, name in leaves:
        dxftype = e.dxftype()
        kept = name in ALL_LAYER_NAMES and Layer(name) in allowed
        target = Layer(name) if kept else active_layer
        try:
            new = _DISPATCH[dxftype](e, target, unit)
        except Exception:
            new = None                     # a degenerate entity: reported
        if new is None:                    # handler declined the entity variant
            unsupported[dxftype] = unsupported.get(dxftype, 0) + 1
            continue
        good = [c for c in new if curve_is_finite(c)]
        left_out["nonfinite"] += len(new) - len(good)
        curves.extend(good)
        if good and not kept:
            key = name or "0"
            dumped[key] = dumped.get(key, 0) + len(good)
    if unit != 1.0:
        for c in curves:
            _scale(c, unit)

    notes: list[str] = []
    if unit_note:
        notes.append(unit_note)
    if dumped:
        total = sum(dumped.values())
        names = ", ".join(sorted(dumped))
        notes.append(
            f"{total} curve(s) from layer(s) {names} placed on "
            f"{active_layer.value} — re-file via the Layers panel."
        )
    if left_out["hidden"]:
        notes.append(f"{left_out['hidden']} entit{'y' if left_out['hidden'] == 1 else 'ies'} "
                     "on layers that are off or frozen were left out.")
    if left_out["nonfinite"]:
        notes.append(f"{left_out['nonfinite']} curve(s) whose numbers are not finite "
                     "(NaN or infinite) were left out.")
    if "depth" in stopped:
        notes.append(f"Blocks nested more than {_MAX_DEPTH} deep (a block that "
                     "inserts itself?) were not expanded further.")
    if "count" in stopped:
        notes.append(f"The import stopped at {_MAX_CURVES} curves; the rest of the "
                     "file was left out.")
    if "work" in stopped:
        notes.append(f"The import stopped after {_MAX_VISITS} entities (blocks "
                     "inside blocks multiply them); the rest of the file was left out.")
    if unsupported:
        notes.append(
            "Skipped unsupported entities: "
            + ", ".join(f"{k}×{v}" for k, v in sorted(unsupported.items()))
        )
    return curves, notes
