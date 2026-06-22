"""
DXF import — bring foreign DXF geometry into a GuildDraw workspace.

This is the inverse of ``export/dxf.py``.  Where the exporter negates Y
(scene Y-down -> DXF Y-up) and swaps+negates arc angles, the importer undoes
both so imported geometry sits upright in the scene.

Layer policy (the migration on-ramp): a DXF entity whose layer name matches a
GuildDraw layer that is *valid for the target workspace* keeps that layer;
every other entity is dropped onto ``active_layer`` and reported in the returned
notes, so the maker can re-file it by dragging rows in the Layers panel.

Coordinates are read 1:1 as millimetres (GuildDraw's scene unit).  Foreign files
authored in inches/cm are not auto-scaled — that is a known limitation.

Supported entities: LINE, LWPOLYLINE, POLYLINE (2D), SPLINE, CIRCLE, ARC,
ELLIPSE.  Bulged polylines are expanded into their line/arc segments via ezdxf's
``virtual_entities``.  Unsupported entity types are counted and reported, never
silently dropped.
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
from ..geometry import compute_catmull_handles

# Sampling distance (mm) for non-cubic / rational splines and ellipses, and the
# node cap after decimation so an imported curve stays editable.
_FLATTEN_MM = 0.05
_DECIMATE_MAX_NODES = 64


def _sn(x: float, y: float) -> SplineNode:
    """SplineNode at a DXF point, negating Y (DXF Y-up -> scene Y-down)."""
    return SplineNode(x=float(x), y=-float(y))


# ---------------------------------------------------------------------------
# Per-entity handlers — each returns list[Curve] (possibly empty)
# ---------------------------------------------------------------------------

def _line_to_curve(e, layer: Layer) -> list[Curve]:
    s, t = e.dxf.start, e.dxf.end
    return [Curve(kind="line", layer=layer,
                  nodes=[_sn(s.x, s.y), _sn(t.x, t.y)], closed=False)]


def _circle_to_curve(e, layer: Layer) -> list[Curve]:
    c = e.dxf.center
    return [Curve(kind="circle", layer=layer, nodes=[_sn(c.x, c.y)],
                  radius=float(e.dxf.radius), closed=True)]


def _arc_to_curve(e, layer: Layer) -> list[Curve]:
    # Inverse of export: export wrote start_dxf=(-end_scene)%360,
    # end_dxf=(-start_scene)%360, so undo with the same swap+negate.
    c = e.dxf.center
    start_scene = (-float(e.dxf.end_angle)) % 360
    end_scene = (-float(e.dxf.start_angle)) % 360
    return [Curve(kind="arc", layer=layer, nodes=[_sn(c.x, c.y)],
                  radius=float(e.dxf.radius),
                  start_angle=start_scene, end_angle=end_scene, closed=False)]


def _nodes_from_bezier_segments(segs: list, closed: bool) -> list[SplineNode]:
    """Build spline nodes from cubic Bézier segments (exact inverse of
    ``bezier_to_bspline`` used on export).  Consecutive segments share an
    endpoint, so each appended end-node becomes the next segment's start."""
    nodes: list[SplineNode] = []
    for i, seg in enumerate(segs):
        p0, p1, p2, p3 = list(seg)
        if i == 0:
            n0 = _sn(p0.x, p0.y)
            n0.cp_out = ControlPoint(float(p1.x), -float(p1.y))
            nodes.append(n0)
        else:
            nodes[-1].cp_out = ControlPoint(float(p1.x), -float(p1.y))
        n_end = _sn(p3.x, p3.y)
        n_end.cp_in = ControlPoint(float(p2.x), -float(p2.y))
        nodes.append(n_end)

    # A closed spline's final wrap segment ends back at the first node; fold the
    # duplicate away and hand its incoming handle to the first node.
    if closed and len(nodes) >= 2:
        first, last = nodes[0], nodes[-1]
        if math.hypot(last.x - first.x, last.y - first.y) < 1e-6:
            first.cp_in = last.cp_in
            nodes.pop()
    return nodes


def _decimate(pts: list, max_nodes: int) -> list:
    if len(pts) <= max_nodes:
        return list(pts)
    stride = (len(pts) - 1) / (max_nodes - 1)
    return [pts[round(i * stride)] for i in range(max_nodes)]


def _spline_from_points(pts: list, layer: Layer, closed: bool) -> list[Curve]:
    if closed and len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]
    pts = _decimate(pts, _DECIMATE_MAX_NODES)
    if len(pts) < 2:
        return []
    nodes = [_sn(x, y) for (x, y) in pts]
    compute_catmull_handles(nodes, closed)
    return [Curve(kind="spline", layer=layer, nodes=nodes, closed=closed)]


def _spline_to_curve(e, layer: Layer) -> list[Curve]:
    ct = e.construction_tool()
    closed = bool(getattr(e, "closed", False)) or bool(e.dxf.flags & 1)
    if ct.degree == 3 and not ct.is_rational:
        nodes = _nodes_from_bezier_segments(list(ct.bezier_decomposition()), closed)
        if len(nodes) < 2:
            return []
        return [Curve(kind="spline", layer=layer, nodes=nodes, closed=closed)]
    pts = [(p.x, p.y) for p in ct.flattening(_FLATTEN_MM)]
    return _spline_from_points(pts, layer, closed)


def _ellipse_to_curve(e, layer: Layer) -> list[Curve]:
    closed = abs((e.dxf.end_param - e.dxf.start_param) - 2 * math.pi) < 1e-6
    pts = [(p.x, p.y) for p in e.flattening(_FLATTEN_MM)]
    return _spline_from_points(pts, layer, closed)


# ---------------------------------------------------------------------------
# Polylines (LWPOLYLINE / 2D POLYLINE) — straight runs kept as one contour;
# bulged ones expanded into line/arc segments by ezdxf.
# ---------------------------------------------------------------------------

def _lwpolyline_to_curves(e, layer: Layer) -> list[Curve]:
    pts = list(e.get_points("xyb"))   # (x, y, bulge)
    if all(abs(b) < 1e-9 for (_x, _y, b) in pts):
        nodes = [_sn(x, y) for (x, y, _b) in pts]
        if len(nodes) < 2:
            return []
        return [Curve(kind="line", layer=layer, nodes=nodes, closed=bool(e.closed))]
    return _expand_virtual(e, layer)


def _polyline_to_curves(e, layer: Layer) -> list[Curve]:
    if e.get_mode() != "AcDb2dPolyline":
        return []   # 3D polylines / polymeshes are unsupported
    coords = [(v.dxf.location.x, v.dxf.location.y, v.dxf.bulge or 0.0)
              for v in e.vertices]
    if all(abs(b) < 1e-9 for (_x, _y, b) in coords):
        nodes = [_sn(x, y) for (x, y, _b) in coords]
        if len(nodes) < 2:
            return []
        return [Curve(kind="line", layer=layer, nodes=nodes, closed=bool(e.is_closed))]
    return _expand_virtual(e, layer)


def _expand_virtual(e, layer: Layer) -> list[Curve]:
    out: list[Curve] = []
    for ve in e.virtual_entities():
        h = _LEAF.get(ve.dxftype())
        if h:
            out.extend(h(ve, layer))
    return out


_LEAF = {
    "LINE": _line_to_curve,
    "CIRCLE": _circle_to_curve,
    "ARC": _arc_to_curve,
    "SPLINE": _spline_to_curve,
    "ELLIPSE": _ellipse_to_curve,
}
_DISPATCH = dict(_LEAF)
_DISPATCH["LWPOLYLINE"] = _lwpolyline_to_curves
_DISPATCH["POLYLINE"] = _polyline_to_curves


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

    Recognised layer names valid for *workspace_type* are kept; everything else
    lands on *active_layer*.  *notes* are human-readable status strings about
    re-filing and any skipped entity types.
    """
    doc = _read_doc(path)
    msp = doc.modelspace()
    allowed = set(WORKSPACE_LAYERS.get(workspace_type, list(Layer)))

    curves: list[Curve] = []
    dumped: dict[str, int] = {}        # original layer name -> count placed on active
    unsupported: dict[str, int] = {}   # dxftype -> count

    for e in msp:
        dxftype = e.dxftype()
        handler = _DISPATCH.get(dxftype)
        if handler is None:
            unsupported[dxftype] = unsupported.get(dxftype, 0) + 1
            continue

        layer_name = (e.dxf.layer or "").upper()
        kept = layer_name in ALL_LAYER_NAMES and Layer(layer_name) in allowed
        target = Layer(layer_name) if kept else active_layer

        new = handler(e, target)
        if not new:
            continue
        curves.extend(new)
        if not kept:
            key = layer_name or "0"
            dumped[key] = dumped.get(key, 0) + len(new)

    notes: list[str] = []
    if dumped:
        total = sum(dumped.values())
        names = ", ".join(sorted(dumped))
        notes.append(
            f"{total} curve(s) from layer(s) {names} placed on "
            f"{active_layer.value} — re-file via the Layers panel."
        )
    if unsupported:
        notes.append(
            "Skipped unsupported entities: "
            + ", ".join(f"{k}×{v}" for k, v in sorted(unsupported.items()))
        )
    return curves, notes
