"""DXF import — round-trips against export, layer policy, foreign-layer dump."""
import math

import ezdxf
import pytest

from framedraft.document import Layer
from framedraft.export.dxf import export_dxf
from framedraft.export.dxf_import import import_dxf
from framedraft.geometry import point_at_t
from helpers import line, circle, arc, closed_diamond


def export_and_import(tmp_path, curves, active_layer=Layer.OUTLINE,
                      workspace_type="front"):
    path = tmp_path / "rt.dxf"
    export_dxf(curves=curves, path=str(path), mirror_on=False)
    return import_dxf(str(path), active_layer, workspace_type)


def _pts(c):
    return [(round(n.x, 6), round(n.y, 6)) for n in c.nodes]


def _sample_bbox(c, n=80):
    xs, ys = [], []
    for i in range(n):
        x, y = point_at_t(c, i / (n - 1))
        xs.append(x)
        ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Per-kind round-trips (export negates Y / swaps arc angles; import undoes both)
# ---------------------------------------------------------------------------

def test_line_roundtrips_points_and_layer(tmp_path):
    curves, notes = export_and_import(tmp_path, [line([(0, 0), (10, 0), (10, 10)],
                                                      layer=Layer.REF)])
    assert notes == []
    assert len(curves) == 1
    g = curves[0]
    assert g.kind == "line" and g.layer is Layer.REF and not g.closed
    assert _pts(g) == [(0, 0), (10, 0), (10, 10)]


def test_closed_line_preserves_closed_flag(tmp_path):
    curves, _ = export_and_import(
        tmp_path, [line([(0, 0), (10, 0), (10, 10), (0, 10)], closed=True,
                        layer=Layer.OUTLINE)])
    assert curves[0].kind == "line" and curves[0].closed is True


def test_circle_roundtrips_center_and_radius(tmp_path):
    curves, _ = export_and_import(tmp_path, [circle(5, 7, 3)])
    g = curves[0]
    assert g.kind == "circle"
    assert g.nodes[0].x == pytest.approx(5) and g.nodes[0].y == pytest.approx(7)
    assert g.radius == pytest.approx(3)


def test_arc_roundtrips_scene_angles(tmp_path):
    curves, _ = export_and_import(tmp_path, [arc(3, 7, 10, 30, 120)])
    g = curves[0]
    assert g.kind == "arc"
    assert g.nodes[0].x == pytest.approx(3) and g.nodes[0].y == pytest.approx(7)
    assert g.start_angle == pytest.approx(30)
    assert g.end_angle == pytest.approx(120)


def test_closed_spline_roundtrips_within_tolerance(tmp_path):
    src = closed_diamond(0, 0, 20, layer=Layer.OUTLINE)
    curves, _ = export_and_import(tmp_path, [src])
    assert len(curves) == 1
    g = curves[0]
    assert g.kind == "spline" and g.closed is True
    # Cubic bezier_decomposition is the exact inverse of bezier_to_bspline.
    for i in range(60):
        t = i / 59
        sx, sy = point_at_t(src, t)
        gx, gy = point_at_t(g, t)
        assert math.hypot(gx - sx, gy - sy) < 1e-3


# ---------------------------------------------------------------------------
# Layer policy
# ---------------------------------------------------------------------------

def test_recognised_valid_layer_is_kept(tmp_path):
    # LENS is valid in the front workspace -> kept, no dump note.
    curves, notes = export_and_import(tmp_path, [circle(-15, 0, 10)],
                                      active_layer=Layer.OUTLINE,
                                      workspace_type="front")
    assert curves[0].layer is Layer.LENS
    assert notes == []


def test_unknown_layer_dumps_to_active_layer(tmp_path):
    path = tmp_path / "foreign.dxf"
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    msp.add_circle((5, -7, 0), radius=3, dxfattribs={"layer": "RANDOM"})
    doc.saveas(str(path))

    curves, notes = import_dxf(str(path), Layer.OUTLINE, "front")
    assert len(curves) == 1 and curves[0].layer is Layer.OUTLINE
    assert any("RANDOM" in n and "OUTLINE" in n for n in notes)


def test_recognised_but_invalid_for_workspace_dumps(tmp_path):
    # LENS is forbidden in a temple workspace -> dumped onto the active layer.
    path = tmp_path / "lens.dxf"
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    msp.add_circle((0, 0, 0), radius=8, dxfattribs={"layer": "LENS"})
    doc.saveas(str(path))

    curves, notes = import_dxf(str(path), Layer.OUTLINE, "temple_r")
    assert curves[0].layer is Layer.OUTLINE
    assert any("LENS" in n for n in notes)


# ---------------------------------------------------------------------------
# Extra entity kinds
# ---------------------------------------------------------------------------

def test_bulged_polyline_expands_to_line_and_arc(tmp_path):
    path = tmp_path / "bulge.dxf"
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    # square-ish path with one bulged (arc) segment
    msp.add_lwpolyline(
        [(0, 0, 0.0), (10, 0, 1.0), (10, 10, 0.0), (0, 10, 0.0)],
        format="xyb", dxfattribs={"layer": "OUTLINE"}, close=True)
    doc.saveas(str(path))

    curves, _ = import_dxf(str(path), Layer.OUTLINE, "front")
    kinds = sorted(c.kind for c in curves)
    assert "arc" in kinds and "line" in kinds


def test_ellipse_imports_as_closed_spline(tmp_path):
    path = tmp_path / "ellipse.dxf"
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    msp.add_ellipse(center=(0, 0, 0), major_axis=(20, 0, 0), ratio=0.5,
                    dxfattribs={"layer": "LENS"})
    doc.saveas(str(path))

    curves, _ = import_dxf(str(path), Layer.OUTLINE, "front")
    assert len(curves) == 1 and curves[0].kind == "spline" and curves[0].closed
    x0, y0, x1, y1 = _sample_bbox(curves[0])
    assert (x1 - x0) == pytest.approx(40, abs=1.0)   # major axis 2*20
    assert (y1 - y0) == pytest.approx(20, abs=1.0)   # minor axis 2*10


def test_unsupported_entity_is_reported_not_dropped_silently(tmp_path):
    path = tmp_path / "text.dxf"
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    msp.add_text("hello", dxfattribs={"layer": "REF"})
    doc.saveas(str(path))

    curves, notes = import_dxf(str(path), Layer.REF, "front")
    assert curves == []
    assert any("TEXT" in n for n in notes)
