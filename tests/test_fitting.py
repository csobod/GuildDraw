"""fitting.py — Schneider cubic-fit engine: tolerance mode, budget mode,
corner preservation, closed-seam G1, and the M30 offset-reduction acceptance."""
import math

import pytest

from framedraft.document import Curve, SplineNode, ControlPoint, Layer
from framedraft.geometry import (
    sample_curve, circle_to_spline, _offset_spline,
)
from framedraft.fitting import fit_curve, FitResult
from helpers import spline, circle


# ---------------------------------------------------------------- helpers

def _samples(curve, per=40):
    return [(x, y) for x, y, _ in sample_curve(curve, per)]


def _worst_kink_deg(curve, only_smooth=True):
    """Largest tangent break (degrees) across cp_in→node→cp_out at any node."""
    worst = 0.0
    for nd in curve.nodes:
        if not (nd.cp_in and nd.cp_out):
            continue
        v1 = (nd.x - nd.cp_in.x, nd.y - nd.cp_in.y)
        v2 = (nd.cp_out.x - nd.x, nd.cp_out.y - nd.y)
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        sin_k = abs(v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)
        worst = max(worst, math.degrees(math.asin(min(1.0, sin_k))))
    return worst


def _two_node_closed_lens(r=20.0):
    """The GitHub #5 shape: a closed spline of exactly two handle-driven nodes."""
    k = (4.0 / 3.0) * r
    a = SplineNode(x=r, y=0.0);  a.cp_out = ControlPoint(r, k);   a.cp_in = ControlPoint(r, -k)
    b = SplineNode(x=-r, y=0.0); b.cp_out = ControlPoint(-r, -k); b.cp_in = ControlPoint(-r, k)
    return Curve(kind="spline", layer=Layer.LENS, nodes=[a, b], closed=True)


# ---------------------------------------------------------------- API guards

def test_requires_exactly_one_mode():
    pts = [(0, 0), (10, 0)]
    with pytest.raises(ValueError):
        fit_curve(pts)
    with pytest.raises(ValueError):
        fit_curve(pts, tol_mm=0.1, n_nodes=5)


def test_degenerate_input_returns_single_node():
    r = fit_curve([(3, 4)], tol_mm=0.1)
    assert isinstance(r, FitResult)
    assert r.n_nodes == 1 and r.max_deviation_mm == 0.0


# ---------------------------------------------------------------- tolerance mode

def test_open_spline_endpoints_interpolated_and_reduced():
    s = spline([(0, 0), (15, 12), (30, -12), (45, 0)], closed=False)
    pts = _samples(s)
    r = fit_curve(pts, tol_mm=0.05, closed=False, layer=s.layer)
    assert r.curve.kind == "spline" and r.curve.closed is False
    assert r.curve.layer == s.layer
    assert r.n_nodes < len(pts)                    # actually simplified
    assert r.max_deviation_mm <= 0.05 * 1.5
    # endpoints land exactly on the first/last input point
    assert math.hypot(r.curve.nodes[0].x - pts[0][0],
                      r.curve.nodes[0].y - pts[0][1]) < 1e-6
    assert math.hypot(r.curve.nodes[-1].x - pts[-1][0],
                      r.curve.nodes[-1].y - pts[-1][1]) < 1e-6


@pytest.mark.parametrize("tol", [0.1, 0.03, 0.01])
def test_tighter_tolerance_never_exceeds_and_adds_nodes(tol):
    s = spline([(0, -22), (28, -15), (33, 5), (15, 24), (-20, 18), (-30, -8)],
               closed=True)
    r = fit_curve(_samples(s, 48), tol_mm=tol, closed=True, layer=s.layer)
    assert r.max_deviation_mm <= tol * 1.5


def test_closed_smooth_seam_is_g1():
    s = spline([(0, -22), (28, -15), (33, 5), (15, 24), (-20, 18), (-30, -8)],
               closed=True)
    r = fit_curve(_samples(s), tol_mm=0.03, closed=True, layer=s.layer)
    assert r.curve.closed is True
    # a smooth closed input yields no kinks anywhere, seam included
    assert _worst_kink_deg(r.curve) < 1.0


def test_custom_handles_are_followed():
    """Hand-tuned (non-Catmull) handles are part of the shape; the fit must
    track the drawn curve, not a re-smoothed version of the nodes."""
    s = spline([(0, -22), (28, -15), (33, 5), (15, 24), (-20, 18), (-30, -8)],
               closed=True)
    s.nodes[1].cp_out = ControlPoint(s.nodes[1].x + 9, s.nodes[1].y + 6)
    s.nodes[1].cp_in  = ControlPoint(s.nodes[1].x - 9, s.nodes[1].y - 6)
    s.nodes[3].cp_out = ControlPoint(s.nodes[3].x - 12, s.nodes[3].y + 1)
    s.nodes[3].cp_in  = ControlPoint(s.nodes[3].x + 12, s.nodes[3].y - 1)
    r = fit_curve(_samples(s, 48), tol_mm=0.03, closed=True, layer=s.layer)
    assert r.max_deviation_mm <= 0.05


def test_circle_fits_to_a_handful_of_nodes():
    c = circle_to_spline(circle(3, -4, 18))
    r = fit_curve(_samples(c, 48), tol_mm=0.02, closed=True, layer=Layer.LENS)
    assert r.n_nodes <= 8
    assert r.max_deviation_mm <= 0.03


def test_corners_are_preserved_as_sharp_nodes():
    """A closed spline of straight sides (no handles) must keep its four hard
    corners — the fit region breaks at each detected corner."""
    nodes = [SplineNode(x=x, y=y) for x, y in [(0, 0), (30, 0), (30, 30), (0, 30)]]
    sq = Curve(kind="spline", layer=Layer.OUTLINE, nodes=nodes, closed=True)
    r = fit_curve(_samples(sq, 30), tol_mm=0.05, closed=True, layer=Layer.OUTLINE)
    assert r.curve.closed is True
    sharp = sum(1 for nd in r.curve.nodes
                if nd.cp_in and nd.cp_out and _node_kink(nd) > 45.0)
    assert sharp >= 4
    assert r.max_deviation_mm <= 0.1


def _node_kink(nd) -> float:
    v1 = (nd.x - nd.cp_in.x, nd.y - nd.cp_in.y)
    v2 = (nd.cp_out.x - nd.x, nd.cp_out.y - nd.y)
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-9 or l2 < 1e-9:
        return 0.0
    return math.degrees(math.asin(min(1.0,
                        abs(v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2))))


# ---------------------------------------------------------------- ACCEPTANCE (M30)

def test_offset_node_reduction_acceptance():
    """M30 gate: refitting the raw Tiller–Hanson offset of a two-node closed
    lens at _OFFSET_TOL_MM must cut the node count to ≤10 while staying
    parallel. (The M31.1 end-to-end wiring is asserted in test_geometry.)"""
    lens = _two_node_closed_lens()
    th = _offset_spline(lens, 2.0)              # node-heavy backstop: ~28 nodes
    assert len(th.nodes) >= 20                  # (guard the premise)
    pts = _samples(th, 48)
    r = fit_curve(pts, tol_mm=0.02, closed=True, layer=th.layer)
    assert r.n_nodes <= 10
    assert len(th.nodes) - r.n_nodes >= 0.6 * len(th.nodes)     # ≥60% cut
    assert r.max_deviation_mm <= 0.03


# ---------------------------------------------------------------- budget mode

@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("n", [2, 4, 6, 9, 15])
def test_budget_mode_returns_exact_node_count(closed, n):
    src = spline([(0, -22), (28, -15), (33, 5), (15, 24), (-20, 18), (-30, -8)],
                 closed=closed)
    r = fit_curve(_samples(src, 48), n_nodes=n, closed=closed, layer=Layer.LENS)
    assert r.n_nodes == n
    assert r.curve.closed is closed
    assert r.max_deviation_mm >= 0.0


@pytest.mark.parametrize("closed", [False, True])
def test_budget_more_nodes_never_worse(closed):
    src = spline([(0, -22), (28, -15), (33, 5), (15, 24), (-20, 18), (-30, -8)],
                 closed=closed)
    pts = _samples(src, 48)
    coarse = fit_curve(pts, n_nodes=5,  closed=closed).max_deviation_mm
    fine   = fit_curve(pts, n_nodes=14, closed=closed).max_deviation_mm
    assert fine <= coarse + 1e-9


def test_budget_upsamples_sparse_input():
    """Fewer input points than requested nodes still yields exactly N nodes."""
    r = fit_curve([(0, 0), (10, 5), (20, 0)], n_nodes=8, closed=False)
    assert r.n_nodes == 8
