"""Boxing-system math: sampled finished box / bevel outline / measurements."""
import pytest

from framedraft.boxing import (
    bevel_outline_points,
    finished_ab,
    finished_box,
    finished_dbl,
    lens_bbox,
)
from framedraft.document import BevelSpec, BEVEL_PRESETS
from helpers import circle, closed_diamond


def _pts_bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _area(bb):
    return (bb[2] - bb[0]) * (bb[3] - bb[1])


def test_bevel_presets_map_to_expected_depths():
    assert BEVEL_PRESETS["flat"] == 0.0
    assert BEVEL_PRESETS["horn_metal"] == 0.5
    assert BEVEL_PRESETS["acetate"] == 1.0
    assert BevelSpec.from_preset("acetate").depth_mm == 1.0
    assert BevelSpec.from_preset("flat").depth_mm == 0.0
    assert BevelSpec.from_preset("custom").preset == "custom"


def test_lens_bbox_hugs_sampled_circle():
    # 256 samples land exactly on the cardinal points, so the bbox is exact.
    bb = lens_bbox(circle(5, 7, 10))
    assert bb == pytest.approx((-5, -3, 15, 17), abs=0.02)


def test_finished_box_grows_by_depth_each_side():
    x0, y0, x1, y1 = finished_box(circle(0, 0, 10), 1.0)
    assert (x1 - x0) == pytest.approx(22, abs=0.05)   # +2*depth
    assert (y1 - y0) == pytest.approx(22, abs=0.05)
    assert (x0, y0, x1, y1) == pytest.approx((-11, -11, 11, 11), abs=0.05)


def test_finished_box_zero_depth_is_bare_bbox():
    c = circle(0, 0, 10)
    assert finished_box(c, 0.0) == pytest.approx(lens_bbox(c), abs=0.02)


def test_bevel_outline_none_without_bevel():
    assert bevel_outline_points(circle(0, 0, 10), 0.0) is None


def test_bevel_outline_enlarges_and_is_closed():
    pts = bevel_outline_points(circle(0, 0, 10), 1.5)
    assert pts and pts[0] == pytest.approx(pts[-1])   # closed ring
    bb = _pts_bbox(pts)
    assert bb == pytest.approx((-11.5, -11.5, 11.5, 11.5), abs=0.1)


def test_bevel_outline_enlarges_regardless_of_winding():
    # Shapely buffer with a positive distance always expands outward, whatever
    # the node order — a complex lens offsets cleanly either way.
    cw = closed_diamond(0, 0, 20)
    ccw = closed_diamond(0, 0, 20)
    ccw.nodes = list(reversed(ccw.nodes))
    for c in (cw, ccw):
        bb = _pts_bbox(bevel_outline_points(c, 1.0))
        assert _area(bb) > _area(lens_bbox(c))


def test_finished_measurements():
    a, b = finished_ab(50.0, 30.0, 1.0)
    assert a == pytest.approx(52.0) and b == pytest.approx(32.0)
    assert finished_dbl(18.0, 1.0) == pytest.approx(16.0)
    assert finished_ab(50.0, 30.0, 0.0) == (50.0, 30.0)
    assert finished_dbl(18.0, 0.0) == 18.0
