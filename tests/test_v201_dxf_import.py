"""DXF import in 2.0.1 (the offset's cousins, items 12 and 13): the fit
tolerances in millimeters whatever the file's units, a size window that fits
eyewear and holds for files stamped millimeters too, and block expansion
bounded by the work done, with MINSERT arrays expanded."""
import math
import re

import ezdxf
import numpy as np
import pytest
import shapely
from ezdxf.math import (BSpline, ConstructionEllipse, closed_uniform_bspline,
                        rational_bspline_from_ellipse)
from shapely.geometry import LineString

import framedraft.export.dxf_import as dxf_import
from framedraft.document import Layer
from framedraft.export.dxf_import import import_dxf
from framedraft.geometry import sample_curve

# $INSUNITS code and the file units in one millimeter.
_UNITS = {"inches": (1, 1 / 25.4), "centimeters": (5, 0.1),
          "meters": (6, 1e-3), "microns": (13, 1000.0)}


def _dxf(tmp_path, build, units=4, name="in.dxf"):
    doc = ezdxf.new("R2000")
    doc.units = units
    build(doc.modelspace(), doc)
    p = tmp_path / name
    doc.saveas(str(p))
    return str(p)


def _ring(rx, ry, n, k=1.0):
    return [(rx * k * math.cos(2 * math.pi * i / n),
             ry * k * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _lens_shapes(k):
    """A 50 x 40 mm lens five ways, in a unit with *k* of it to the mm: a
    NURBS ellipse and a periodic spline (both fitted), an open clamped cubic
    whose ends are 0.5 mm apart (exact, and open), an ELLIPSE, and a closed
    polyline whose last vertex sits 0.05 mm from its first (both kept)."""
    def build(msp, _doc):
        e = ConstructionEllipse(center=(0, 0), major_axis=(25 * k, 0), ratio=0.8)
        msp.add_spline(dxfattribs={"layer": "LENS"}).apply_construction_tool(
            rational_bspline_from_ellipse(e, segments=4))
        msp.add_spline(dxfattribs={"layer": "LENS"}).apply_construction_tool(
            closed_uniform_bspline(_ring(25, 20, 16, k), order=4))
        gap = 0.25 / 25                                   # 0.5 mm apart at the ends
        arc = [(25 * k * math.cos(gap + (2 * math.pi - 2 * gap) * i / 30),
                20 * k * math.sin(gap + (2 * math.pi - 2 * gap) * i / 30))
               for i in range(31)]
        msp.add_spline(dxfattribs={"layer": "REF"}).apply_construction_tool(
            BSpline(arc, order=4))
        msp.add_ellipse((0, 0), (25 * k, 0), 0.8, dxfattribs={"layer": "LENS"})
        ring = _ring(25, 20, 24, k) + [(25 * k, 0.05 * k)]
        msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "LENS"})
    return build


def _truths(k):
    """The same five shapes' true points, in mm (DXF y-up)."""
    e = ConstructionEllipse(center=(0, 0), major_axis=(25, 0), ratio=0.8)
    rat = rational_bspline_from_ellipse(e, segments=4)
    per = closed_uniform_bspline(_ring(25, 20, 16), order=4)
    out = []
    for bs in (rat, per):
        t0, t1 = bs.knots()[bs.degree], bs.knots()[bs.count]
        out.append(np.array([tuple(bs.point(t0 + (t1 - t0) * i / 800))[:2]
                             for i in range(801)]))
    return out


def _deviation(curve, truth) -> float:
    """Largest distance either way between the closed import (scene y-down)
    and the closed *truth* (DXF y-up, mm), each a fine polyline."""
    got = [(x, -y) for x, y, _t in sample_curve(curve, 64)]
    return float(max(
        shapely.distance(shapely.points(got), LineString(truth)).max(),
        shapely.distance(shapely.points(truth), LineString(got + got[:1])).max()))


# ── Tolerances in millimeters, whatever the file's units ──────────────────

@pytest.mark.parametrize("unit", sorted(_UNITS))
def test_a_lens_comes_in_the_same_in_any_unit(tmp_path, unit):
    """The fit's tolerances were applied in the file's units: a lens spline
    drawn in inches came in 0.05 to 0.12 mm off, in meters 0.4 to 0.6 mm off
    with 2 nodes, in microns with 96 nodes; ends 1 mm apart in meters counted
    as closed, and a polyline's seam 0.1 mm wide was folded."""
    code, k = _UNITS[unit]
    mm, _ = import_dxf(_dxf(tmp_path, _lens_shapes(1.0), name="mm.dxf"), Layer.REF)
    got, notes = import_dxf(_dxf(tmp_path, _lens_shapes(k), units=code), Layer.REF)
    assert any(f"drawn in {unit}" in n for n in notes)
    assert [(c.kind, c.closed) for c in got] == [(c.kind, c.closed) for c in mm]
    assert [c.closed for c in got] == [True, True, False, True, True]
    for c in got[:2]:
        assert len(c.nodes) <= 16                         # 10 and 12 in mm
    for c, truth in zip(got[:2], _truths(k), strict=True):
        assert _deviation(c, truth) < 0.01
    for a, b in zip(got[2:], mm[2:], strict=True):        # exact: the same nodes
        assert len(a.nodes) == len(b.nodes)
        assert all(math.hypot(p.x - q.x, p.y - q.y) < 1e-6
                   for p, q in zip(a.nodes, b.nodes, strict=True))


def test_a_near_circle_in_meters_stays_an_ellipse(tmp_path):
    """The circle test's micron was a millimeter in meters: an ellipse
    25 x 24.9 mm came in as a circle of radius 24.95."""
    def build(msp, _doc):
        e = ConstructionEllipse(center=(0, 0), major_axis=(0.025, 0), ratio=24.9 / 25)
        msp.add_spline(dxfattribs={"layer": "LENS"}).apply_construction_tool(
            rational_bspline_from_ellipse(e, segments=4))
    [c], _notes = import_dxf(_dxf(tmp_path, build, units=6), Layer.REF)
    assert c.kind == "spline" and c.closed


# ── The size window ───────────────────────────────────────────────────────

def test_a_lens_drawn_in_mm_but_stamped_inches_is_read_as_mm(tmp_path):
    """The window ran to 2 m: a 50 mm lens in a file stamped inches came in
    1.27 m across."""
    def build(msp, _doc):
        msp.add_circle((0, 0), 25.0, dxfattribs={"layer": "LENS"})
    [c], notes = import_dxf(_dxf(tmp_path, build, units=1), Layer.REF)
    assert c.radius == pytest.approx(25.0)
    assert any("inches" in n and "read as millimeters" in n for n in notes)


def test_a_front_drawn_in_mm_but_stamped_centimeters_is_read_as_mm(tmp_path):
    def build(msp, _doc):
        msp.add_line((0, 0), (140, 0), dxfattribs={"layer": "OUTLINE"})
        msp.add_circle((35, 0), 25.0, dxfattribs={"layer": "LENS"})
    curves, notes = import_dxf(_dxf(tmp_path, build, units=5), Layer.REF)
    assert [c.radius for c in curves if c.kind == "circle"] == [pytest.approx(25.0)]
    assert any("centimeters" in n and "read as millimeters" in n for n in notes)


@pytest.mark.parametrize("r, across", [(0.025, "0.05 mm"), (635.0, "1.27 m")])
def test_a_mm_drawing_out_of_size_is_kept_with_a_note(tmp_path, r, across):
    """Files stamped millimeters skipped the window: a lens drawn in meters
    or inches came in a few hundredths or a meter across with no word. The
    stamp is kept (nothing is rescaled on a guess) and the note says so."""
    def build(msp, _doc):
        msp.add_circle((0, 0), r, dxfattribs={"layer": "LENS"})
    [c], notes = import_dxf(_dxf(tmp_path, build, units=4), Layer.REF)
    assert c.radius == pytest.approx(r)
    [note] = notes
    assert "drawn in millimeters" in note and "imported as drawn" in note
    assert f"{across} across, outside the 3 to 300 mm" in note


def test_a_unitless_drawing_out_of_size_says_so(tmp_path):
    def build(msp, _doc):
        msp.add_circle((0, 0), 1.0, dxfattribs={"layer": "LENS"})   # 2 in, unstamped
    [c], [note] = import_dxf(_dxf(tmp_path, build, units=0), Layer.REF)
    assert c.radius == pytest.approx(1.0)
    assert "no drawing units" in note and "2 mm across, outside" in note


def test_a_plausible_drawing_is_never_rescaled(tmp_path):
    def build_in(msp, _doc):
        msp.add_circle((0, 0), 1.0, dxfattribs={"layer": "LENS"})   # 2 in across
    [c], notes = import_dxf(_dxf(tmp_path, build_in, units=1), Layer.REF)
    assert c.radius == pytest.approx(25.4) and len(notes) == 1

    def build_mm(msp, _doc):
        msp.add_circle((0, 0), 25.0, dxfattribs={"layer": "LENS"})
    [c], notes = import_dxf(_dxf(tmp_path, build_mm, units=4), Layer.REF)
    assert c.radius == 25.0 and notes == []


# ── Block expansion ───────────────────────────────────────────────────────

def _nested(fanout, depth, leaf="TEXT"):
    """Blocks B0..B(depth-1), each inserting the next *fanout* times; the
    last holds one *leaf*: fanout**(depth-1) leaves from a file of a few KB."""
    def build(msp, doc):
        for i in reversed(range(depth)):
            blk = doc.blocks.new(name=f"B{i}")
            if i == depth - 1:
                if leaf == "TEXT":
                    blk.add_text("x")
                else:
                    blk.add_line((0, 0), (0.5, 0), dxfattribs={"layer": "OFF"})
            else:
                for k in range(fanout):
                    blk.add_blockref(f"B{i + 1}", (k, 0))
        doc.layers.add("OFF").off()
        msp.add_blockref("B0", (0, 0))
    return build


@pytest.mark.parametrize("leaf", ["TEXT", "hidden LINE"])
def test_block_expansion_stops_at_a_count_of_entities_with_a_note(
        tmp_path, monkeypatch, leaf):
    """Expansion was bounded by the curves it made, and leaves that make
    none (text, entities on a layer that is off) never reach that bound: a
    21 KB file ran 9 s, a deeper one never ended."""
    monkeypatch.setattr(dxf_import, "_MAX_VISITS", 500, raising=False)
    curves, notes = import_dxf(_dxf(tmp_path, _nested(10, 5, leaf)), Layer.REF)
    assert curves == []
    assert any("500" in n and "left out" in n for n in notes)
    told = " ".join(notes)
    seen = (sum(int(n) for n in re.findall(r"TEXT×(\d+)", told))
            + sum(int(n) for n in re.findall(r"(\d+) entit(?:y|ies) on layers", told)))
    assert 0 < seen < 500                     # of the 10,000 leaves


def test_a_minsert_array_imports_every_cell(tmp_path):
    """A MINSERT's rows and columns were dropped: a 2 x 5 drill grid came in
    as one hole, with no note."""
    def build(msp, doc):
        doc.blocks.new("HOLE").add_circle((0, 0), 0.6)
        msp.add_blockref("HOLE", (10, 20), dxfattribs={"layer": "DRILL"}).grid(
            size=(2, 5), spacing=(4, 3))
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.REF)
    assert notes == []
    assert all(c.kind == "circle" and c.layer is Layer.DRILL for c in curves)
    got = sorted((round(c.nodes[0].x, 9), round(-c.nodes[0].y, 9)) for c in curves)
    assert got == sorted((10 + 3 * col, 20 + 4 * row)
                         for row in range(2) for col in range(5))


def test_a_rotated_minsert_inside_a_block_turns_its_grid(tmp_path):
    def build(msp, doc):
        doc.blocks.new("HOLE").add_circle((0, 0), 0.6)
        doc.blocks.new("PLATE").add_blockref(
            "HOLE", (0, 0), dxfattribs={"rotation": 90}).grid(size=(1, 3), spacing=(1, 5))
        msp.add_blockref("PLATE", (2, 0))
    curves, _notes = import_dxf(_dxf(tmp_path, build), Layer.REF)
    got = sorted((round(c.nodes[0].x, 9), round(-c.nodes[0].y, 9)) for c in curves)
    assert got == [(2, 0), (2, 5), (2, 10)]


def test_a_minsert_of_zero_spacing_is_one_cell_a_row(tmp_path):
    """A zero spacing stacks its row or column on one spot: one hole for
    each, without a walk through every stacked cell."""
    def build(msp, doc):
        doc.blocks.new("HOLE").add_circle((0, 0), 0.6)
        msp.add_blockref("HOLE", (0, 0)).grid(size=(32767, 3), spacing=(0, 5))
    curves, _notes = import_dxf(_dxf(tmp_path, build), Layer.REF)
    assert sorted(round(c.nodes[0].x, 9) for c in curves) == [0, 5, 10]


def test_a_huge_minsert_stops_at_the_count_with_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(dxf_import, "_MAX_VISITS", 400, raising=False)

    def build(msp, doc):
        doc.blocks.new("HOLE").add_circle((0, 0), 0.6)
        msp.add_blockref("HOLE", (0, 0)).grid(size=(1000, 1000), spacing=(2, 2))
    curves, notes = import_dxf(_dxf(tmp_path, build), Layer.REF)
    assert 0 < len(curves) < 400
    assert any("400" in n and "left out" in n for n in notes)
