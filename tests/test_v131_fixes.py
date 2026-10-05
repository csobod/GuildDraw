"""v1.3.1 fixes — the hidden seam in a closed shape from another program.

Found 2026-10-05 on a temple logo: a DXF converter had written the closed
polyline with its first vertex repeated as its last, and the final vertex
before that a few microns short of the start. DXF import kept the repeat as a
zero-length closing segment; Rebuild (tolerance mode) read the hairline as a
corner and fitted a hairline cubic, leaving a closed spline whose last node
sat on its first — a ring that crosses itself at the seam, which GuildModel's
engraving fill could not use. Each door now closes the hairline.
"""
import math

import ezdxf

from framedraft.document import Layer
from framedraft.export.dxf_import import import_dxf
from framedraft.fitting import fit_curve


def _ring(n=48, r=10.0):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def _gaps(curve):
    ns = curve.nodes
    return [math.hypot(ns[i].x - ns[i - 1].x, ns[i].y - ns[i - 1].y) for i in range(1, len(ns))]


def _seam(curve):
    a, b = curve.nodes[0], curve.nodes[-1]
    return math.hypot(a.x - b.x, a.y - b.y)


# ---------------------------------------------------------------------------
# DXF import: a closed polyline that repeats its first vertex
# ---------------------------------------------------------------------------

def _write_closed_polyline(path, pts, *, lightweight: bool):
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    if lightweight:
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "OUTLINE"})
    else:
        msp.add_polyline2d(pts, close=True, dxfattribs={"layer": "OUTLINE"})
    doc.saveas(path)


def test_lwpolyline_repeated_first_vertex_is_folded(tmp_path):
    pts = _ring(12) + [_ring(12)[0]]                   # closed, first repeated as last
    p = tmp_path / "lw.dxf"
    _write_closed_polyline(p, pts, lightweight=True)
    curves, _ = import_dxf(str(p), Layer.REF, "front")
    c = curves[0]
    assert c.kind == "line" and c.closed and len(c.nodes) == 12
    assert min(_gaps(c)) > 1.0 and _seam(c) > 1.0


def test_polyline_repeated_first_vertex_is_folded(tmp_path):
    pts = _ring(12) + [_ring(12)[0]]
    p = tmp_path / "pl.dxf"
    _write_closed_polyline(p, pts, lightweight=False)
    curves, _ = import_dxf(str(p), Layer.REF, "front")
    c = curves[0]
    assert c.kind == "line" and c.closed and len(c.nodes) == 12


def test_polyline_without_the_repeat_is_unchanged(tmp_path):
    p = tmp_path / "plain.dxf"
    _write_closed_polyline(p, _ring(12), lightweight=True)
    curves, _ = import_dxf(str(p), Layer.REF, "front")
    assert len(curves[0].nodes) == 12 and curves[0].closed


def test_open_polyline_that_happens_to_end_at_its_start_keeps_both(tmp_path):
    doc = ezdxf.new("R2000")
    pts = [(0, 0), (10, 0), (10, 10), (0, 0)]
    doc.modelspace().add_lwpolyline(pts, close=False, dxfattribs={"layer": "REF"})
    p = tmp_path / "open.dxf"
    doc.saveas(p)
    curves, _ = import_dxf(str(p), Layer.REF, "front")
    assert not curves[0].closed and len(curves[0].nodes) == 4


# ---------------------------------------------------------------------------
# Rebuild's fitter: a hairline at the seam
# ---------------------------------------------------------------------------

def _logo_with_hairline_seam():
    """A closed outline with corners, whose last point is 4 µm from its first."""
    pts = []
    for k in range(6):                                 # a six-armed star, as a polygon
        a0 = 2 * math.pi * k / 6
        a1 = 2 * math.pi * (k + 1) / 6
        pts.append((8 * math.cos(a0), 8 * math.sin(a0)))
        pts.append((3 * math.cos((a0 + a1) / 2), 3 * math.sin((a0 + a1) / 2)))
    dense = []
    for a, b in zip(pts, pts[1:] + pts[:1], strict=True):
        for i in range(10):
            t = i / 10
            dense.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    dense.append((pts[0][0] + 0.004, pts[0][1] - 0.002))   # the converter's hairline
    return dense


def test_tolerance_fit_of_a_hairline_seam_has_no_node_on_its_neighbor():
    fr = fit_curve(_logo_with_hairline_seam(), tol_mm=0.05, closed=True)
    c = fr.curve
    assert c.closed and len(c.nodes) >= 12
    assert min(_gaps(c)) > 0.01 and _seam(c) > 0.01
    assert fr.max_deviation_mm < 0.1


def test_budget_fit_of_a_hairline_seam_has_no_node_on_its_neighbor():
    c = fit_curve(_logo_with_hairline_seam(), n_nodes=24, closed=True).curve
    assert min(_gaps(c)) > 0.01 and _seam(c) > 0.01


def test_an_honest_tight_corner_is_not_merged():
    # two points 0.5 mm apart at a corner are geometry, not a hairline
    pts = [(0, 0), (10, 0), (10, 0.5), (0, 0.5)]
    dense = []
    for a, b in zip(pts, pts[1:] + pts[:1], strict=True):
        for i in range(20):
            t = i / 20
            dense.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    c = fit_curve(dense, tol_mm=0.02, closed=True).curve
    assert min(_gaps(c)) >= 0.5 - 1e-6
