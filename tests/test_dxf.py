"""DXF export — entity types, layers, closure, Y-flip and angle conventions."""
import ezdxf

from framedraft.document import Layer
from framedraft.export.dxf import export_dxf
from helpers import line, circle, arc, closed_diamond


def export_and_read(tmp_path, curves):
    path = tmp_path / "out.dxf"
    export_dxf(curves=curves, path=str(path))
    return ezdxf.readfile(str(path)).modelspace()


def test_entity_types_and_layers(tmp_path):
    curves = [
        closed_diamond(0, 0, 40, layer=Layer.OUTLINE),   # spline
        circle(-15, 0, 10), circle(15, 0, 10),           # LENS circles
        line([(0, 0), (10, 0), (10, 10)], layer=Layer.REF),
    ]
    msp = export_and_read(tmp_path, curves)
    kinds = sorted(e.dxftype() for e in msp)
    assert kinds == ["CIRCLE", "CIRCLE", "LWPOLYLINE", "SPLINE"]
    layers = {e.dxftype(): e.dxf.layer for e in msp}
    assert layers["SPLINE"] == "OUTLINE"
    assert layers["CIRCLE"] == "LENS"
    assert layers["LWPOLYLINE"] == "REF"


def test_closed_spline_has_closed_flag(tmp_path):
    msp = export_and_read(tmp_path, [closed_diamond(layer=Layer.OUTLINE)])
    sp = next(e for e in msp if e.dxftype() == "SPLINE")
    assert sp.closed


def test_y_axis_is_negated(tmp_path):
    msp = export_and_read(tmp_path, [circle(5, 7, 3)])
    c = next(e for e in msp if e.dxftype() == "CIRCLE")
    assert c.dxf.center.x == 5 and c.dxf.center.y == -7


def test_arc_angles_swap_and_negate(tmp_path):
    # Scene arc 0..90 (Y-down CW) must become DXF arc 270..0 (Y-up CCW)
    msp = export_and_read(tmp_path, [arc(0, 0, 10, 0, 90)])
    a = next(e for e in msp if e.dxftype() == "ARC")
    assert a.dxf.start_angle == 270.0
    assert a.dxf.end_angle == 0.0


def test_the_ghost_is_never_written(tmp_path):
    # GuildModel never applies the Ghost, and the .gdraw carries the curves
    # drawn; the DXF writes the same curves (2.0), on the front and on a
    # temple alike.
    curves = [
        closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
        circle(15, 0, 10),
        circle(15, 10, 4, layer=Layer.COMPONENT),
    ]
    msp = export_and_read(tmp_path, curves)
    circles = [e for e in msp if e.dxftype() == "CIRCLE"]
    splines = [e for e in msp if e.dxftype() == "SPLINE"]
    assert len(circles) == 2 and len(splines) == 1
    assert sorted((c.dxf.center.x, c.dxf.center.y) for c in circles) == [
        (15, -10), (15, 0)]


def test_mirrored_flag_curves_are_skipped(tmp_path):
    ghost = circle(15, 0, 10)
    ghost.mirrored = True
    msp = export_and_read(tmp_path, [circle(-15, 0, 10), ghost])
    assert len([e for e in msp if e.dxftype() == "CIRCLE"]) == 1
