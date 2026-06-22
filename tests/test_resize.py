"""Auto-resize: scale-about-pivot, finished-A/B targeting, DBL preservation."""
import pytest

from framedraft.boxing import finished_box, lens_bbox
from framedraft.resize import scale_curve_about, size_to_finished_ab
from helpers import circle, closed_diamond


def _fin(c, depth):
    return finished_box(c, depth)


def test_scale_uniform_keeps_circle_analytic():
    out = scale_curve_about(circle(0, 0, 10), 0, 0, 2.0, 2.0)
    assert out.kind == "circle"
    assert out.radius == pytest.approx(20)


def test_scale_nonuniform_circle_becomes_spline():
    out = scale_curve_about(circle(0, 0, 10), 0, 0, 2.0, 1.0)
    assert out.kind == "spline"
    bb = lens_bbox(out)
    assert (bb[2] - bb[0]) == pytest.approx(40, abs=0.3)   # x doubled
    assert (bb[3] - bb[1]) == pytest.approx(20, abs=0.3)   # y unchanged


def test_size_to_finished_ab_hits_targets_including_bevel():
    # bare circle 40x40; with depth 1 finished target 52x44 -> resize.
    lens = circle(-30, 0, 20)        # OD side (centre x < axis 0)
    out = size_to_finished_ab(lens, target_a=52.0, target_b=44.0,
                              bevel_depth=1.0, axis_x=0.0)
    fb = _fin(out, 1.0)
    assert (fb[2] - fb[0]) == pytest.approx(52.0, abs=0.1)
    assert (fb[3] - fb[1]) == pytest.approx(44.0, abs=0.1)


def test_resize_preserves_nasal_edge_so_dbl_is_kept():
    # Lens on the +x (OS) side: nasal edge = its left (min-x) edge nearest axis 0.
    lens = closed_diamond(40, 0, 20)
    nasal_before = lens_bbox(lens)[0]
    out = size_to_finished_ab(lens, target_a=60.0, target_b=40.0,
                              bevel_depth=0.0, axis_x=0.0)
    nasal_after = lens_bbox(out)[0]
    assert nasal_after == pytest.approx(nasal_before, abs=0.05)
    # and it actually got wider
    assert (lens_bbox(out)[2] - lens_bbox(out)[0]) > (40 - nasal_before) + 1


def test_resize_a_only_leaves_b_untouched():
    # Changing A with target_b=None must not perturb B at all (no drift).
    lens = closed_diamond(0, 0, 20)
    b_before = lens_bbox(lens)[3] - lens_bbox(lens)[1]
    out = size_to_finished_ab(lens, target_a=50.0, target_b=None, bevel_depth=0.0)
    bb = lens_bbox(out)
    assert (bb[2] - bb[0]) == pytest.approx(50.0, abs=0.1)   # A hits target
    assert (bb[3] - bb[1]) == pytest.approx(b_before, abs=1e-6)  # B exactly unchanged


def test_resize_noop_returns_none():
    lens = closed_diamond(0, 0, 20)
    assert size_to_finished_ab(lens, None, None, 0.0) is None
    # asking for the current size is also a no-op
    a = lens_bbox(lens)[2] - lens_bbox(lens)[0]
    assert size_to_finished_ab(lens, target_a=a, target_b=None, bevel_depth=0.0) is None


def test_scale_preserves_flats_and_corners():
    # Outline co-resize must keep straight runs straight and sharp corners sharp
    # (affine scale, never an offset). Build a flat seg 0->1 meeting a curved seg
    # at node1 with a CORNER (cp_in/cp_out not collinear).
    from framedraft.document import Curve, SplineNode, ControlPoint, Layer
    n0 = SplineNode(0, 0,  cp_out=ControlPoint(3, 0))
    n1 = SplineNode(10, 0, cp_in=ControlPoint(7, 0), cp_out=ControlPoint(12, 5))
    n2 = SplineNode(15, 15, cp_in=ControlPoint(13, 12))
    c = Curve(kind="spline", layer=Layer.OUTLINE, nodes=[n0, n1, n2], closed=False)

    out = scale_curve_about(c, 0.0, 0.0, 2.0, 1.5)
    o0, o1, _o2 = out.nodes
    # Flat (y=0) run preserved through the whole straight segment.
    assert o0.y == 0 and o0.cp_out.y == 0 and o1.cp_in.y == 0 and o1.y == 0
    # Corner preserved: incoming vs outgoing tangents stay non-parallel.
    vin = (o1.x - o1.cp_in.x, o1.y - o1.cp_in.y)
    vout = (o1.cp_out.x - o1.x, o1.cp_out.y - o1.y)
    assert abs(vin[0] * vout[1] - vin[1] * vout[0]) > 1e-6


def test_resize_target_matches_reported_basis():
    # The resizer and the boxing read-out share lens_bbox, so the achieved
    # finished width equals the typed target exactly.
    lens = closed_diamond(-30, 0, 18)
    out = size_to_finished_ab(lens, target_a=52.0, target_b=None, bevel_depth=1.0)
    fb = finished_box(out, 1.0)
    assert (fb[2] - fb[0]) == pytest.approx(52.0, abs=0.05)
    assert (lens_bbox(out)[2] - lens_bbox(out)[0]) == pytest.approx(50.0, abs=0.05)
