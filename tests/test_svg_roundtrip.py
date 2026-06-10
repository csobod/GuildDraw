"""SVG native format — save_svg → load_svg must round-trip every field."""
import math

import pytest

from framedraft.document import (
    Calibration, MirrorAxis, FormingMetadata, MachinedBridge, DimLine, Layer,
)
from framedraft.export.svg import save_svg, load_svg
from helpers import line, spline, circle, arc


def nodes_equal(a, b, tol=1e-9):
    if len(a.nodes) != len(b.nodes):
        return False
    for na, nb in zip(a.nodes, b.nodes, strict=True):
        if math.hypot(na.x - nb.x, na.y - nb.y) > tol:
            return False
        for which in ("cp_in", "cp_out"):
            ca, cb = getattr(na, which), getattr(nb, which)
            if (ca is None) != (cb is None):
                return False
            if ca is not None and math.hypot(ca.x - cb.x, ca.y - cb.y) > tol:
                return False
    return True


@pytest.fixture
def saved(tmp_path):
    curves = [
        line([(0, 0), (10, 0), (10, 10)], layer=Layer.REF),
        line([(0, 0), (20, 0), (20, 20), (0, 20)], closed=True, layer=Layer.HINGE),
        spline([(0, -20), (25, 0), (0, 20), (-25, 0)], closed=True, layer=Layer.OUTLINE),
        circle(30, 0, 12, layer=Layer.LENS),
        arc(0, 0, 8, 30, 200),
    ]
    curves[0].line_weight = 0.75
    curves[1].group_id = "abcd1234"   # grouped curve round-trips its group
    dims = [DimLine(x0=0, y0=0, x1=10, y1=0, offset=5.5)]
    bookmarks = [{
        "name": "rev one", "timestamp": "12:00:00",
        "snapshot": {"curves": [circle(1, 2, 3)], "dims": []},
    }]
    path = tmp_path / "roundtrip.svg"
    save_svg(
        curves=curves, path=str(path),
        calibration=Calibration(px_per_mm=4.2),
        mirror=MirrorAxis(enabled=False, x=1.5),
        forming=FormingMetadata(bridge_angle_deg=15.0, apical_radius_mm=8.0),
        machined_bridge=MachinedBridge(depth_mm=4.5, width_mm=6.0),
        bookmarks=bookmarks, dims=dims,
        layers={"OUTLINE": {"visible": True, "locked": True},
                "REF":     {"visible": False, "locked": False}},
    )
    return curves, load_svg(str(path))


def test_curve_count_and_kinds(saved):
    orig, data = saved
    assert [c.kind for c in data["curves"]] == [c.kind for c in orig]
    assert [c.layer for c in data["curves"]] == [c.layer for c in orig]
    assert [c.closed for c in data["curves"]] == [c.closed for c in orig]


def test_node_geometry_roundtrips(saved):
    orig, data = saved
    for a, b in zip(orig, data["curves"], strict=True):
        assert nodes_equal(a, b), f"{a.kind} nodes drifted"


def test_circle_arc_fields(saved):
    orig, data = saved
    circ = data["curves"][3]
    assert circ.radius == 12
    a = data["curves"][4]
    assert (a.radius, a.start_angle, a.end_angle) == (8, 30, 200)


def test_line_weight_roundtrips(saved):
    _, data = saved
    assert data["curves"][0].line_weight == 0.75


def test_metadata_roundtrips(saved):
    _, data = saved
    assert data["calibration"].px_per_mm == 4.2
    assert data["mirror"].enabled is False and data["mirror"].x == 1.5
    assert data["forming"].bridge_angle_deg == 15.0
    assert data["forming"].apical_radius_mm == 8.0
    assert data["machined_bridge"].depth_mm == 4.5


def test_dims_roundtrip(saved):
    _, data = saved
    d = data["dims"][0]
    assert (d.x0, d.y0, d.x1, d.y1, d.offset) == (0, 0, 10, 0, 5.5)


def test_group_id_roundtrips(saved):
    _, data = saved
    assert data["curves"][1].group_id == "abcd1234"
    assert data["curves"][0].group_id is None


def test_layer_states_roundtrip(saved):
    _, data = saved
    layers = data["layers"]
    assert layers["OUTLINE"] == {"visible": True, "locked": True}
    assert layers["REF"]["visible"] is False


def test_bookmarks_roundtrip(saved):
    _, data = saved
    bm = data["bookmarks"][0]
    assert bm["name"] == "rev one"
    snap = bm["snapshot"]["curves"]
    assert len(snap) == 1 and snap[0].kind == "circle" and snap[0].radius == 3


def test_mirrored_curves_are_not_saved(tmp_path):
    c = circle(0, 0, 5)
    ghost = circle(10, 0, 5)
    ghost.mirrored = True
    path = tmp_path / "m.svg"
    save_svg(curves=[c, ghost], path=str(path),
             calibration=Calibration(), mirror=MirrorAxis(),
             forming=FormingMetadata(), machined_bridge=MachinedBridge())
    data = load_svg(str(path))
    assert len(data["curves"]) == 1
