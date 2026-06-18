"""
DXF R2000 export using ezdxf.

Scene units are mm (1 scene unit = 1 mm), so coordinates are written
directly into the DXF with no unit conversion.

Contract (confirmed against GuildCAM Session 5):
  - R2000 (AC1015) with SPLINE entities (exact cubic Bézier → cubic B-spline).
  - $INSUNITS = 4 (mm) as a convention signal; GuildCAM ignores it.
  - One closed entity per outline; endpoints within 0.1 mm for closure.
  - Strict layer vocabulary: OUTLINE (×1), LENS (>=1), BRIDGE, HINGE, REF.
  - Do NOT flatten splines to polylines.

Y-axis convention:
  Qt scene uses Y-down (positive Y goes toward the bottom of the screen).
  DXF uses Y-up (standard math convention).  All Y values are negated on
  export so the geometry appears upright in standard CAD viewers.

Arc angles:
  GuildDraw stores arc angles as atan2 in Qt Y-down space (0°=right,
  90°=down-screen).  DXF ARC entities use CCW-positive in Y-up space.
  Converting requires BOTH negating the angles AND swapping start/end
  (because the Y-flip reverses the sweep direction).
"""

import ezdxf
from ezdxf.math import Bezier4P, bezier_to_bspline, Vec3

from ..document import Curve, Layer, ControlPoint
from ..geometry import mirror_curve


def _spline_segments(nodes: list, closed: bool) -> list:
    """Build a list of Bezier4P from curve nodes, with Y negated for DXF."""
    n = len(nodes)
    segs = []
    for i in range(n - 1):
        p0 = nodes[i]
        p3 = nodes[i + 1]
        cp1 = p0.cp_out or ControlPoint(p0.x, p0.y)
        cp2 = p3.cp_in  or ControlPoint(p3.x, p3.y)
        segs.append(Bezier4P([
            Vec3(p0.x,   -p0.y,   0),
            Vec3(cp1.x,  -cp1.y,  0),
            Vec3(cp2.x,  -cp2.y,  0),
            Vec3(p3.x,   -p3.y,   0),
        ]))
    if closed and n > 1:
        p0 = nodes[-1]
        p3 = nodes[0]
        cp1 = p0.cp_out or ControlPoint(p0.x, p0.y)
        cp2 = p3.cp_in  or ControlPoint(p3.x, p3.y)
        segs.append(Bezier4P([
            Vec3(p0.x,   -p0.y,   0),
            Vec3(cp1.x,  -cp1.y,  0),
            Vec3(cp2.x,  -cp2.y,  0),
            Vec3(p3.x,   -p3.y,   0),
        ]))
    return segs


def _add_curve(msp, curve: Curve):
    """Add one curve (already in mm) to the ezdxf modelspace."""
    layer = curve.layer.value
    nodes = curve.nodes

    if curve.kind == "circle" and curve.radius and nodes:
        cx, cy = nodes[0].x, nodes[0].y
        msp.add_circle(center=(cx, -cy, 0), radius=curve.radius,
                       dxfattribs={"layer": layer})
        return

    if (curve.kind == "arc" and curve.radius and nodes
            and curve.start_angle is not None and curve.end_angle is not None):
        cx, cy = nodes[0].x, nodes[0].y
        # Negate Y of center; swap+negate angles to convert from Qt Y-down CW
        # convention to DXF Y-up CCW convention.
        start_dxf = (-curve.end_angle)   % 360
        end_dxf   = (-curve.start_angle) % 360
        msp.add_arc(center=(cx, -cy, 0), radius=curve.radius,
                    start_angle=start_dxf, end_angle=end_dxf,
                    dxfattribs={"layer": layer})
        return

    if curve.kind == "line":
        pts = [(n.x, -n.y) for n in nodes]
        msp.add_lwpolyline(pts, dxfattribs={"layer": layer}, close=curve.closed)
    else:
        segs = _spline_segments(nodes, curve.closed)
        if not segs:
            return
        bsp = bezier_to_bspline(segs)
        sp  = msp.add_spline(dxfattribs={"layer": layer})
        sp.apply_construction_tool(bsp)
        if curve.closed:
            sp.dxf.flags = sp.dxf.flags | 1   # CLOSED flag


# Layers that get a mirrored OS copy when mirror is on.
# OUTLINE and BRIDGE span the full frame (drawn symmetric) — never mirrored.
# SCULPT is back-surface geometry, symmetric like LENS — gets mirrored.
_MIRROR_LAYERS = {Layer.LENS, Layer.HINGE, Layer.SCULPT}


def export_dxf(
    curves:     list,        # Curve objects, coordinates in mm
    path:       str,
    mirror_on:  bool,
    axis_x:     float = 0.0,   # mirror axis in mm (vertical mirror)
    horizontal: bool = False,  # temple workspaces mirror across y=0
) -> None:
    doc = ezdxf.new("R2000")
    doc.units = ezdxf.units.MM   # $INSUNITS = 4 (signal only)
    msp = doc.modelspace()

    for curve in curves:
        if curve.mirrored:
            continue
        _add_curve(msp, curve)
        if mirror_on and curve.layer in _MIRROR_LAYERS:
            _add_curve(msp, mirror_curve(curve, axis_x, horizontal=horizontal))

    doc.saveas(path)
