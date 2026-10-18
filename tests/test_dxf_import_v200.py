"""DXF import in the 2.0 bug hunt: exact or fitted splines with no node cap,
one curve per polyline, mirrored and layered blocks, units, hidden layers,
block limits and numbers that are not numbers."""
import math

import ezdxf
import pytest
from ezdxf.math import BSpline, closed_uniform_bspline

from framedraft.document import Layer
from framedraft.export.dxf_import import import_dxf
from framedraft.geometry import sample_curve


def _dxf(tmp_path, build, units=4):
    doc = ezdxf.new("R2000")
    doc.units = units
    build(doc.modelspace(), doc)
    p = tmp_path / "in.dxf"
    doc.saveas(str(p))
    return str(p)


def _max_dev(curve, truth: BSpline, n=400) -> float:
    """Largest distance from the true B-spline (DXF y-up) to the import."""
    import numpy as np
    pts = np.array([(x, -y) for x, y, _t in sample_curve(curve, 4000)])
    t0 = truth.knots()[truth.degree]
    t1 = truth.knots()[truth.count]
    qs = np.array([tuple(truth.point(t0 + (t1 - t0) * i / n))[:2] for i in range(n + 1)])
    d = np.hypot(qs[:, None, 0] - pts[None, :, 0], qs[:, None, 1] - pts[None, :, 1])
    return float(d.min(axis=1).max())


def _temple_points(n):
    return [(i * 150 / (n - 1), 6 * math.sin(i / (n - 1) * 3 * math.pi)
             + (i / (n - 1)) ** 3 * 20) for i in range(n)]


@pytest.mark.parametrize("degree", [1, 2, 3])
def test_a_clamped_spline_of_any_low_degree_is_exact(tmp_path, degree):
    truth = BSpline(_temple_points(120), order=degree + 1)

    def build(msp, _doc):
        msp.add_spline(dxfattribs={"layer": "OUTLINE"}).apply_construction_tool(truth)
    [c] = import_dxf(_dxf(tmp_path, build), Layer.REF)[0]
    assert c.kind == "spline" and len(c.nodes) > 64          # no node cap
    assert _max_dev(c, truth) < 1e-3


def test_a_periodic_or_rational_spline_is_fitted_within_a_hundredth(tmp_path):
    truth = closed_uniform_bspline(_temple_points(120)[::4] + [(75, 60)], order=4)

    def build(msp, _doc):
        msp.add_spline(dxfattribs={"layer": "OUTLINE"}).apply_construction_tool(truth)
    [c] = import_dxf(_dxf(tmp_path, build), Layer.REF)[0]
    assert c.closed
    assert _max_dev(c, truth) < 0.01


def test_a_nurbs_circle_imports_as_a_circle(tmp_path):
    def build(msp, _doc):
        msp.add_spline(dxfattribs={"layer": "LENS"}).apply_construction_tool(
            BSpline.from_arc(ezdxf.math.ConstructionArc((5, 2), 22, 0, 360)))
    [c] = import_dxf(_dxf(tmp_path, build), Layer.REF)[0]
    assert c.kind == "circle" and c.closed
    assert c.radius == pytest.approx(22, abs=1e-6)
    assert (c.nodes[0].x, c.nodes[0].y) == pytest.approx((5, -2), abs=1e-6)


def test_a_mirrored_block_lands_where_cad_shows_it(tmp_path):
    def build(msp, doc):
        blk = doc.blocks.new("H")
        blk.add_circle((20, 0), 2)
        blk.add_arc((20, 0), 5, 0, 90)
        msp.add_blockref("H", (0, 0), dxfattribs={"xscale": -1})
    curves = import_dxf(_dxf(tmp_path, build), Layer.REF)[0]
    circle = next(c for c in curves if c.kind == "circle")
    assert circle.nodes[0].x == pytest.approx(-20)
    arc = next(c for c in curves if c.kind == "arc")
    ends = [(arc.nodes[0].x + 5 * math.cos(math.radians(a)),
             arc.nodes[0].y + 5 * math.sin(math.radians(a)))
            for a in (arc.start_angle, arc.end_angle)]
    assert sorted((round(x, 6), round(y, 6)) for x, y in ends) == [(-25, 0), (-20, -5)]


def test_block_entities_keep_their_own_layers(tmp_path):
    def build(msp, doc):
        blk = doc.blocks.new("FRAME")
        blk.add_circle((0, 0), 20, dxfattribs={"layer": "OUTLINE"})
        blk.add_circle((0, 0), 15, dxfattribs={"layer": "LENS"})
        blk.add_line((0, 0), (5, 0))                        # layer 0: the INSERT's
        msp.add_blockref("FRAME", (0, 0), dxfattribs={"layer": "REF"})
    curves = import_dxf(_dxf(tmp_path, build), Layer.OUTLINE)[0]
    by_kind = sorted((c.kind, c.layer.value, round(c.radius or 0)) for c in curves)
    assert by_kind == [("circle", "LENS", 15), ("circle", "OUTLINE", 20),
                       ("line", "REF", 0)]


def test_units_are_honored_when_the_drawing_comes_out_plausible(tmp_path):
    def build(msp, _doc):
        msp.add_circle((0, 0), 1.0, dxfattribs={"layer": "LENS"})   # 2 in across
    curves, notes = import_dxf(_dxf(tmp_path, build, units=1), Layer.REF)
    assert curves[0].radius == pytest.approx(25.4)
    assert any("inches" in n for n in notes)

    def build_mm(msp, _doc):
        msp.add_circle((0, 0), 25.0, dxfattribs={"layer": "LENS"})  # mm, says meters
    curves, notes = import_dxf(_dxf(tmp_path, build_mm, units=6), Layer.REF)
    assert curves[0].radius == pytest.approx(25.0)
    assert any("read as millimeters" in n for n in notes)


def test_entities_on_an_off_or_frozen_layer_are_left_out(tmp_path):
    def build(msp, doc):
        doc.layers.add("CONSTRUCTION").off()
        msp.add_line((0, 0), (5, 0), dxfattribs={"layer": "CONSTRUCTION"})
        msp.add_line((0, 0), (0, 5), dxfattribs={"layer": "REF"})
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.REF)
    assert len(curves) == 1
    assert any("off or frozen" in n for n in notes)


def test_a_block_that_inserts_itself_stops_with_a_note(tmp_path):
    def build(msp, doc):
        blk = doc.blocks.new("LOOP")
        blk.add_line((0, 0), (1, 0))
        blk.add_blockref("LOOP", (1, 0))
        msp.add_blockref("LOOP", (0, 0))
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.REF)
    assert curves and any("nested more than" in n for n in notes)


def test_a_curve_whose_numbers_are_not_numbers_is_left_out(tmp_path):
    def build(msp, _doc):
        msp.add_line((0, 0), (5, 0))
        msp.add_circle((0, 0), float("nan"))
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.REF)
    assert [c.kind for c in curves] == ["line"]
    assert any("not finite" in n for n in notes)
