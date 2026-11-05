"""The forming module (BUILDPLAN *Road to 2.3*), Qt-free: GuildModel's map
ported, the shop's setup, the readouts, Unform and the temple's tip bend, held to the research
document's worked numbers (`RESEARCH-forming-preview-and-draft-view.md`,
§2.3 and §5.3)."""
import math

import numpy as np
import pytest

from framedraft import forming
from framedraft.document import ControlPoint, Curve, Layer, SplineNode
from framedraft.forming import (
    DEFAULT_DROP_MM, DIOPTER_MM, GROOVE_APEX_MM, FormingSetup, FrontForming, PRESS_ROWS,
    ThermoformParams, TipBend, TipBendParams, front_readout, lens_readout, press_row, radius_for,
    unform_curve, unform_points,
)
from helpers import circle, closed_diamond, spline


def ellipse(cx, cy, a, b, n=360):
    t = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    return [(cx + a * math.cos(x), cy + b * math.sin(x)) for x in t]


def front_50x40(dbl=18.0):
    """Two 50 × 40 ellipses, DBL 18, as the research's worked example."""
    cx = 25.0 + 0.5 * dbl
    return ellipse(-cx, 0.0, 25.0, 20.0), ellipse(cx, 0.0, 25.0, 20.0)


def params(base, wrap=10.0, **kw):
    p = ThermoformParams(face_form_wrap_deg=wrap, **kw).with_base_curve(base)
    return p


# ── the stored block ───────────────────────────────────────────────────────

def test_a_base_curve_names_a_radius_by_the_rule_and_a_row_by_its_die():
    assert radius_for(4.0) == pytest.approx(132.5)
    assert radius_for(4.0, 523.0) == pytest.approx(130.75)
    assert radius_for(0.0) == 0.0
    p = ThermoformParams().with_base_curve(4.0)
    assert p.base_radius_mm == pytest.approx(132.5) and not p.is_flat
    row = press_row("SBT base 4 / lens 4")
    assert row is not None and row.radius_mm == 144.0
    on_row = ThermoformParams.from_row(row)
    assert (on_row.base_curve, on_row.base_radius_mm, on_row.press_preset) == (
        4.0, 144.0, row.label)
    assert on_row.face_form_deg == pytest.approx(163.97)
    assert on_row.face_form_per_side_deg == pytest.approx(8.015)
    # Off the row's base curve, the rule's radius comes back.
    off = on_row.with_base_curve(6.0)
    assert off.base_radius_mm == pytest.approx(530.0 / 6.0)
    assert {r.label for r in PRESS_ROWS} == {
        "SBT base 2 / lens 4", "SBT base 3 / lens 4", "SBT base 4 / lens 4",
        "SBT base 2 / lens 2"}


def test_the_default_setup_is_the_historical_standard():
    setup = FormingSetup()
    assert setup.tooling_index == 1.53 and setup.radius_rule == DIOPTER_MM == 530.0
    # GuildDraw's defaults and the stored block's are the same values, so a
    # design that never set its forming saves what it always did.
    assert ThermoformParams().with_setup(setup) == ThermoformParams()
    assert FormingSetup(tooling_index=1.523).radius_rule == 523.0


def test_the_setup_reads_prefs_within_the_fields_bounds():
    assert FormingSetup.from_prefs(None) == FormingSetup()
    assert FormingSetup.from_prefs({}) == FormingSetup()
    wild = FormingSetup.from_prefs({"tooling_index": 9, "sheet_thickness_mm": 0,
                                    "neutral_fraction": -1})
    assert (wild.tooling_index, wild.sheet_thickness_mm, wild.neutral_fraction) == (
        2.0, 1.0, 0.0)


def test_with_setup_moves_the_radius_only_when_the_index_changes():
    # A radius off the rule's, as a hand-edited file holds it, survives a read
    # under the same index; a new index names a new radius, but not on a die.
    hand = ThermoformParams(base_curve=4.0, base_radius_mm=140.0)
    assert hand.with_setup(FormingSetup()).base_radius_mm == 140.0
    moved = hand.with_setup(FormingSetup(tooling_index=1.523))
    assert moved.base_radius_mm == pytest.approx(523.0 / 4.0) and moved.radius_rule == 523.0
    die = ThermoformParams.from_row(press_row("SBT base 4 / lens 4"))
    assert die.with_setup(FormingSetup(tooling_index=1.523)).base_radius_mm == 144.0
    # Sheet and surface are replaced, the design's own values kept.
    p = params(4.0).with_setup(FormingSetup(sheet_thickness_mm=8.0, neutral_fraction=0.5))
    assert (p.sheet_thickness_mm, p.neutral_fraction, p.base_curve) == (8.0, 0.5, 4.0)
    assert p.base_radius_mm == pytest.approx(132.5)


def test_the_block_reads_tolerantly_and_round_trips():
    assert ThermoformParams.from_dict(None).is_flat
    assert ThermoformParams.from_dict({"base_curve": "x"}).is_flat
    p = ThermoformParams.from_dict({"base_curve": 4, "press_preset": "no such row",
                                    "neutral_fraction": 7, "radius_rule": float("nan")})
    assert p.base_curve == 4.0 and p.press_preset == ""
    assert p.base_radius_mm == pytest.approx(132.5)       # the rule, no radius stored
    assert p.neutral_fraction == 1.0 and p.radius_rule == 530.0
    # The fields' bounds: a file past them reads clamped.
    wide = ThermoformParams.from_dict({"base_curve": 20, "face_form_wrap_deg": 50,
                                       "bridge_projection_mm": 15, "radius_rule": 5000,
                                       "sheet_thickness_mm": 20})
    assert (wide.base_curve, wide.face_form_wrap_deg, wide.bridge_projection_mm,
            wide.radius_rule, wide.sheet_thickness_mm) == (16.0, 30.0, 8.0, 1000.0, 12.0)
    assert ThermoformParams.from_dict({"radius_rule": 523}).radius_rule == 523.0
    d = params(4.0, press_preset="SBT base 4 / lens 4").to_dict()
    assert set(d) == set(ThermoformParams.KEYS)
    assert ThermoformParams.from_dict(d) == ThermoformParams.from_dict(d)
    assert TipBendParams.from_dict({"drop_angle_deg": 200}).drop_angle_deg == 90.0
    assert TipBendParams.from_dict("junk") == TipBendParams()


# ── the map and the readouts ────────────────────────────────────────────────

@pytest.mark.parametrize("base, a_plane, a_head, b_plane", [
    (2.0, 49.93, 49.74, 39.96),
    (4.0, 49.70, 49.51, 39.85),
    (6.0, 49.34, 49.15, 39.66),
    (8.0, 48.82, 48.64, 39.40),
])
def test_the_three_widths_of_the_research_table(base, a_plane, a_head, b_plane):
    """Research §2.3: A = 50, B = 40, R = 530 / D, 5° of face form a side.
    Measured at the anterior face, as the table was."""
    od, os_ = front_50x40()
    ff = FrontForming.build(params(base), [od, os_])
    r = lens_readout(ff, od, depth_mm=0.0)
    assert r.a_flat == pytest.approx(50.0) and r.b_flat == pytest.approx(40.0)
    assert r.a_lens_plane == pytest.approx(a_plane, abs=0.01)
    assert r.a_head_on == pytest.approx(a_head, abs=0.01)
    assert r.b_lens_plane == pytest.approx(b_plane, abs=0.01)
    assert r.tilt_deg == pytest.approx(5.0, abs=0.01)
    # The sag of the formed lens: R (1 − cos(A / 2R)).
    R = 530.0 / base
    assert r.edge_sag_mm == pytest.approx(R * (1 - math.cos(25.0 / R)), abs=0.02)


def test_a_flat_front_is_the_identity_and_reads_flat():
    od, os_ = front_50x40()
    ff = FrontForming.build(ThermoformParams(), [od, os_])
    assert ff.is_flat
    assert np.allclose(ff.head_on(od), np.asarray(od))
    r = lens_readout(ff, od)
    assert r.a_lens_plane == r.a_flat == r.a_head_on and r.tilt_deg == 0.0


def test_the_groove_behind_the_length_keeping_surface_is_compressed_further():
    """Research §2.6: a layer z behind the surface that keeps its length
    loses about z·A/R more; the neutral fraction moves that surface."""
    od, os_ = front_50x40()
    ff0 = FrontForming.build(params(4.0, wrap=0.0), [od, os_])
    face = lens_readout(ff0, od, depth_mm=0.0).a_lens_plane
    groove = lens_readout(ff0, od, depth_mm=GROOVE_APEX_MM).a_lens_plane
    assert face - groove == pytest.approx(GROOVE_APEX_MM * 50.0 / 132.5, abs=0.02)
    # Mid-thickness keeping its length on a 6 mm sheet: the groove, 1.5 mm
    # behind the face, now lies 1.5 mm in front of that surface and reads
    # larger than the face did.
    ff5 = FrontForming.build(params(4.0, wrap=0.0, sheet_thickness_mm=6.0,
                                    neutral_fraction=0.5), [od, os_])
    assert lens_readout(ff5, od, depth_mm=GROOVE_APEX_MM).a_lens_plane > face


def test_the_front_readout_flags_iso_and_the_bridge_band():
    od, os_ = front_50x40()
    r = front_readout(FrontForming.build(params(4.0), [od, os_]), od, os_, [od + os_],
                      depth_mm=0.0)
    assert r.dbl_flat == pytest.approx(18.0)
    assert r.dbl_head_on < r.dbl_flat and r.centers_head_on < r.centers_flat
    assert r.width_head_on < r.width_flat
    assert not r.flags
    # Base 8: more than ISO's half millimeter gone in the lens plane.
    r8 = front_readout(FrontForming.build(params(8.0), [od, os_]), od, os_, [od + os_],
                       depth_mm=0.0)
    assert r8.od.a_off_iso and r8.os.a_off_iso
    assert any("ISO" in f and f.startswith("OD") for f in r8.flags)
    # The band is half the gap between the lenses, so a lens edge sits on
    # its edge and never inside it, whatever the DBL; two lenses that
    # overlap in x (a goggle, a drawing error) leave no gap, the band is the
    # default 9 mm, and both lenses reach into it.
    od8, os8 = front_50x40(dbl=8.0)
    rb = front_readout(FrontForming.build(params(4.0), [od8, os8]), od8, os8, [])
    assert not rb.od.in_band and rb.width_head_on is None and rb.endpiece_set_mm is None
    odx, osx = front_50x40(dbl=-4.0)
    rx = front_readout(FrontForming.build(params(4.0), [odx, osx]), odx, osx, [])
    assert rx.od.in_band and any("bridge band" in f for f in rx.flags)


def test_a_monocle_takes_no_face_form():
    od, _ = front_50x40()
    ff = FrontForming.build(params(4.0, wrap=20.0), [od])
    assert not ff.bridge.wraps and ff.fmap.face_form_deg == 180.0
    r = lens_readout(ff, od, depth_mm=0.0)
    assert r.tilt_deg == pytest.approx(0.0, abs=1e-6)


def test_the_endpieces_turn_toward_the_face():
    """Research §2.8: forming carries the rim curve out to the endpiece."""
    od, os_ = front_50x40()
    outline = ellipse(0.0, 0.0, 70.0, 25.0)
    r = front_readout(FrontForming.build(params(4.0), [od, os_]), od, os_, [outline])
    assert r.endpiece_set_mm > 5.0 and r.depth_mm > r.endpiece_set_mm - 1.0
    assert r.width_head_on < 140.0


def test_a_sheet_thicker_than_the_bend_is_flagged():
    # A 30° wrap bent over a 2 mm band (DBL 4) turns on a 5 mm radius; a
    # 12 mm sheet cannot follow it. (With a base curve the rims' own bend,
    # apexed on the lens centers, turns the other way across the band and
    # takes most of it out: the two nearly cancel at the press's pairings.)
    od, os_ = front_50x40(dbl=4.0)
    p = ThermoformParams(face_form_wrap_deg=30.0, sheet_thickness_mm=12.0)
    r = front_readout(FrontForming.build(p, [od, os_]), od, os_, [])
    assert any(f.startswith("The sheet folds") for f in r.flags)
    ok = front_readout(FrontForming.build(params(4.0), [od, os_]), od, os_, [])
    assert not any(f.startswith("The sheet folds") for f in ok.flags)


# ── Unform ─────────────────────────────────────────────────────────────────

def test_unform_gives_the_flat_lens_that_forms_to_the_drawn_one():
    od, os_ = front_50x40()
    ff = FrontForming.build(params(4.0), [od, os_])
    flat = unform_points(ff, od, -34.0, depth_mm=0.0)
    back = ff.lens_plane(flat, -34.0, 0.0)
    assert np.abs(back - np.asarray(od)).max() < 1e-6
    # Research §2.3: the flat cut that forms to A′ = 50 at base 4 is 50.30
    # (one sphere a rim); the face form's band moves it a little.
    assert flat[:, 0].max() - flat[:, 0].min() == pytest.approx(50.30, abs=0.05)
    # A flat front: nothing to do.
    ff0 = FrontForming.build(ThermoformParams(), [od, os_])
    assert np.allclose(unform_points(ff0, od, -34.0), np.asarray(od))


def test_unform_curve_keeps_the_kind_but_a_circle_becomes_a_spline():
    od, os_ = front_50x40()
    ff = FrontForming.build(params(6.0), [od, os_])
    c = circle(-34.0, 0.0, 24.0)
    out = unform_curve(c, ff)
    assert out.kind == "spline" and out.closed and out.layer == Layer.LENS
    assert c.kind == "circle"                       # the original untouched
    xs = [n.x for n in out.nodes]
    assert max(xs) - min(xs) > 48.0
    s = closed_diamond(34.0, 0.0, 22.0, layer=Layer.LENS)
    out = unform_curve(s, ff)
    assert out.kind == "spline" and len(out.nodes) >= 4
    assert all(n.cp_in is not None and n.cp_out is not None for n in out.nodes)
    assert len(s.nodes) == 4                        # the original untouched


def _along(curve, n=400):
    """Points along a spline by its own cubics, not by `flatten_curve`,
    whose 64 points a span leave a long span's chords a millimeter long."""
    from framedraft.geometry import _curve_cubics
    t = np.linspace(0.0, 1.0, n)
    return np.vstack([forming._bezier_points(c, t) for c in _curve_cubics(curve)])


def _formed_miss(ff, drawn, flat_curve):
    """How far the flattened curve, formed again, lies from the drawn one,
    and its lens-plane A less the drawn A."""
    from shapely import points
    from shapely.geometry import LineString
    from framedraft.geometry import _curve_cubics
    a = _along(drawn)
    cx = forming._cubics_center_x(_curve_cubics(drawn))
    assert cx == pytest.approx(0.5 * (a[:, 0].min() + a[:, 0].max()), abs=1e-3)
    back = ff.lens_plane(_along(flat_curve), cx, GROOVE_APEX_MM)
    d = LineString(np.vstack([a, a[:1]])).distance(points(back))
    return float(d.max()), float(np.ptp(back[:, 0]) - np.ptp(a[:, 0]))


def _two_node_lens(cx):
    """A lens of two nodes with long handles, as one of the library's is:
    the handles sit far outside the lens, where the map is another."""
    return Curve(kind="spline", layer=Layer.LENS, closed=True, nodes=[
        SplineNode(cx - 2.0, -19.0, cp_in=ControlPoint(cx - 32.0, -19.5),
                   cp_out=ControlPoint(cx + 28.0, -18.5)),
        SplineNode(cx + 1.0, 20.0, cp_in=ControlPoint(cx + 31.0, 20.5),
                   cp_out=ControlPoint(cx - 29.0, 19.5))])


@pytest.mark.parametrize("p", [
    ThermoformParams.from_row(press_row("SBT base 4 / lens 4")),
    params(6.0),
    params(8.0, wrap=16.0),
])
@pytest.mark.parametrize("make", [
    lambda: closed_diamond(-34.0, 0.0, 24.0, layer=Layer.LENS),
    lambda: _two_node_lens(-33.0),
    lambda: spline([(-58, -4), (-44, -19), (-22, -17), (-10, -2), (-18, 15), (-40, 20)],
                   closed=True, layer=Layer.LENS),
])
def test_flatten_matches_the_drawn_lens_all_along_it_not_only_at_its_nodes(p, make):
    """The 2.3 sweep: the handles went through the map as if they lay on the
    lens, so the nodes landed to 1e-8 mm and the curve between them did not
    (0.03 to 0.26 mm on the library's lenses at SBT base 4, the two-node
    lens 0.4 mm wide; a millimeter and more at base 8)."""
    from framedraft.geometry import mirror_curve
    drawn = make()
    ff = FrontForming.build(p, [forming.flatten_for_view(drawn),
                                forming.flatten_for_view(mirror_curve(drawn, 0.0))])
    out = unform_curve(drawn, ff)
    miss, d_a = _formed_miss(ff, drawn, out)
    assert miss <= forming.UNFORM_TOL_MM + 1e-3, miss
    assert abs(d_a) < 0.02, d_a
    # The drawn nodes are kept, each at its own flat place, in their order.
    from framedraft.geometry import _curve_cubics
    cx = forming._cubics_center_x(_curve_cubics(drawn))
    want = unform_points(ff, [(n.x, n.y) for n in drawn.nodes], cx, iters=60, stop_mm=1e-10)
    got = np.array([(n.x, n.y) for n in out.nodes])
    at = [int(np.argmin(np.hypot(*(got - w).T))) for w in want]
    assert at == sorted(at) and len(set(at)) == len(at)
    assert max(float(np.hypot(*(got[i] - w))) for i, w in zip(at, want, strict=True)) < 1e-7
    # No more nodes than the forming asks for, and a smooth node stays one.
    assert len(out.nodes) <= 4 * len(drawn.nodes)
    for n in out.nodes:
        vin = (n.x - n.cp_in.x, n.y - n.cp_in.y)
        vout = (n.cp_out.x - n.x, n.cp_out.y - n.y)
        turn = abs(vin[0] * vout[1] - vin[1] * vout[0]) / (math.hypot(*vin) * math.hypot(*vout))
        assert turn < 1e-9, turn


def test_the_old_flatten_would_fail_the_whole_curve_check():
    """The check above is not vacuous: handles mapped as points miss it."""
    import copy
    drawn = _two_node_lens(-33.0)
    from framedraft.geometry import mirror_curve
    ff = FrontForming.build(ThermoformParams.from_row(press_row("SBT base 4 / lens 4")),
                            [forming.flatten_for_view(drawn),
                             forming.flatten_for_view(mirror_curve(drawn, 0.0))])
    old = copy.deepcopy(drawn)
    from framedraft.geometry import _curve_cubics
    cx = forming._cubics_center_x(_curve_cubics(drawn))
    for n in old.nodes:
        for obj in (n, n.cp_in, n.cp_out):
            obj.x, obj.y = map(float, unform_points(ff, [(obj.x, obj.y)], cx)[0])
    assert _formed_miss(ff, drawn, old)[0] > 0.1


def test_a_polygon_lens_flattens_to_a_spline_with_its_corners():
    """Formed, a straight side bows; flat, it must bow the other way."""
    from helpers import line
    drawn = line([(-58, -18), (-10, -18), (-10, 18), (-58, 18)], closed=True, layer=Layer.LENS)
    twin = line([(58, -18), (10, -18), (10, 18), (58, 18)], closed=True, layer=Layer.LENS)
    ff = FrontForming.build(params(6.0), [forming.flatten_for_view(drawn),
                                          forming.flatten_for_view(twin)])
    out = unform_curve(drawn, ff)
    assert out.kind == "spline" and out.closed and len(out.nodes) >= 4
    assert drawn.kind == "line" and len(drawn.nodes) == 4
    # Formed again, every point of it lies on the drawn rectangle.
    from shapely import points
    from shapely.geometry import LinearRing
    back = ff.lens_plane(_along(out), -34.0, GROOVE_APEX_MM)
    ring = LinearRing([(n.x, n.y) for n in drawn.nodes])
    assert float(ring.distance(points(back)).max()) <= forming.UNFORM_TOL_MM + 1e-3
    # A side that only moved its corners would form 0.2 mm short of the line.
    crude = line([tuple(q) for q in unform_points(ff, [(n.x, n.y) for n in drawn.nodes], -34.0)],
                 closed=True, layer=Layer.LENS)
    back = ff.lens_plane(forming.densify([(n.x, n.y) for n in crude.nodes]
                                         + [(crude.nodes[0].x, crude.nodes[0].y)]),
                         -34.0, GROOVE_APEX_MM)
    assert float(ring.distance(points(back)).max()) > 0.05


def test_a_forming_too_deep_to_flatten_says_so():
    """Base 16 with the deepest face form: the search for the flat shape
    does not settle, and its last guess (48 mm off) was taken as the answer."""
    drawn = closed_diamond(-40.0, 0.0, 30.0, layer=Layer.LENS)
    twin = closed_diamond(40.0, 0.0, 30.0, layer=Layer.LENS)
    ff = FrontForming.build(params(16.0, wrap=30.0), [forming.flatten_for_view(drawn),
                                                      forming.flatten_for_view(twin)])
    with pytest.raises(forming.UnformDiverged):
        unform_curve(drawn, ff)
    assert drawn.nodes[0].y == -30.0                # the drawn lens untouched


# ── straight sides under the map ───────────────────────────────────────────

def test_a_formed_polyline_has_no_long_chords():
    """A straight side is its two ends when flat; the press and the bend
    move its middle too (the 2.3 sweep: a temple drawn with the Line tool
    showed bent as a skewed quadrilateral, 22 mm off)."""
    from helpers import line
    pts = forming.densify([(0, 0), (10, 0), (10, 0.4), (0, 0)])
    assert np.hypot(*(pts[1:] - pts[:-1]).T).max() <= forming.MAX_CHORD_MM + 1e-12
    assert tuple(pts[0]) == (0.0, 0.0) and tuple(pts[-1]) == (0.0, 0.0)
    assert any(tuple(q) == (10.0, 0.0) for q in pts)      # the corners stay
    assert len(forming.densify([(0, 0), (0.5, 0)])) == 2 and len(forming.densify([(1, 1)])) == 1
    temple = line([(0, -4), (140, -4), (140, 4), (0, 4)], closed=True, layer=Layer.OUTLINE)
    flat = np.asarray(forming.flatten_for_view(temple))
    assert len(flat) > 280 and tuple(flat[0]) == tuple(flat[-1])
    tb = TipBend.resolve(TipBendParams(), 0.0, 140.0)
    bent = tb.map_points(flat)
    # Every point of the bent top edge stays 4 mm off the bent core.
    core = tb.map_points(np.column_stack([np.linspace(0.0, 140.0, 5601), np.zeros(5601)]))
    from shapely import points
    from shapely.geometry import LineString
    off = LineString(core).distance(points(bent[1:140]))
    assert np.abs(off - 4.0).max() < 0.02


def test_a_polygon_lens_reads_as_wide_as_its_dense_twin():
    """50 × 36 at base 6: four corners read a millimeter narrow."""
    from helpers import line
    od = [(-59, -18), (-9, -18), (-9, 18), (-59, 18)]
    os_ = [(-x, y) for x, y in od]
    ff = FrontForming.build(params(6.0), [od, os_])
    corners = lens_readout(ff, od + od[:1], depth_mm=0.0)
    dense = lens_readout(ff, forming.densify(od + od[:1], 0.2), depth_mm=0.0)
    assert corners.a_lens_plane == pytest.approx(dense.a_lens_plane, abs=0.005)
    assert corners.circ_3d == pytest.approx(dense.circ_3d, abs=0.01)
    assert corners.a_flat == pytest.approx(50.0) and corners.circ_flat == pytest.approx(172.0)
    del line


# ── the band and the apex ──────────────────────────────────────────────────

def test_the_band_flag_allows_for_the_bevel_and_a_pair_a_hair_off_the_axis():
    """The band is measured from the drawn lenses and the readout from the
    finished ones, a bevel's depth larger: every front with a bevel read
    "reaches into the bridge band" (the 2.3 sweep: all eight library
    designs, in red)."""
    from shapely.geometry import Polygon
    od, os_ = front_50x40()
    ff = FrontForming.build(params(4.0), [od, os_])
    grown = [list(Polygon(pts).buffer(1.0).exterior.coords) for pts in (od, os_)]
    assert front_readout(ff, *grown).od.in_band     # read without the bevel: a millimeter in
    r = front_readout(ff, *grown, outset_mm=1.0)
    assert not r.od.in_band and not r.os.in_band
    assert not any("bridge band" in f for f in r.flags)
    # A pair drawn 0.2 mm off the axis: one lens a hair inside, unflagged.
    od2 = [(x + 0.2, y) for x, y in od]
    os2 = [(x + 0.2, y) for x, y in os_]
    r2 = front_readout(FrontForming.build(params(4.0), [od2, os2]), od2, os2)
    assert not any("bridge band" in f for f in r2.flags)
    # A pair 2 mm off: OD reaches 2 mm into the band, and says so.
    od3 = [(x + 2.0, y) for x, y in od]
    os3 = [(x + 2.0, y) for x, y in os_]
    r3 = front_readout(FrontForming.build(params(4.0), [od3, os3]), od3, os3)
    assert r3.od.in_band and not r3.os.in_band
    assert [f for f in r3.flags if "bridge band" in f][0].startswith("OD")


def test_a_third_curve_on_the_lens_layer_does_not_move_the_rims_apex():
    od, os_ = front_50x40()
    mark = ellipse(0.0, 0.0, 3.0, 3.0, 60)
    two = forming.bridge_from_lenses([od, os_])
    three = forming.bridge_from_lenses([od, mark, os_])
    assert three.apex_x == pytest.approx(two.apex_x) and three.apex_y == pytest.approx(two.apex_y)
    assert three.band_half == pytest.approx(two.band_half)


def test_a_radius_without_a_base_curve_reads_flat():
    """A hand-edited block: the field read Flat over a front formed at
    R 144, and GuildModel read the same file flat."""
    p = ThermoformParams.from_dict({"base_curve": 0, "base_radius_mm": 144.0})
    assert p.base_radius_mm == 0.0 and p.is_flat
    q = ThermoformParams.from_dict({"base_curve": 0, "base_radius_mm": 144.0,
                                    "face_form_wrap_deg": 10.0})
    assert q.base_radius_mm == 0.0 and not q.is_flat


# ── the temple's tip bend ──────────────────────────────────────────────────

def test_the_bend_keeps_the_core_length_and_lands_the_tip_where_the_research_says():
    """Research §5.3: x = s₁ + r sin δ + s₂ cos δ, y = r(1 − cos δ) + s₂ sin δ."""
    tb = TipBend.resolve(TipBendParams(), 0.0, 140.0)
    assert tb.length_to_bend_mm == pytest.approx(140.0 - DEFAULT_DROP_MM)
    assert tb.drop_mm == pytest.approx(DEFAULT_DROP_MM)
    r, d = 15.0, math.radians(50.0)
    s1 = tb.length_to_bend_mm - 0.5 * r * d
    s2 = 140.0 - tb.length_to_bend_mm - 0.5 * r * d
    assert tb.straight_mm == pytest.approx(s1) and tb.tail_mm == pytest.approx(s2)
    x, y = tb.tip()
    assert x == pytest.approx(s1 + r * math.sin(d) + s2 * math.cos(d))
    assert y == pytest.approx(r * (1 - math.cos(d)) + s2 * math.sin(d))
    assert tb.reach_mm == pytest.approx(x) and tb.tip_drop_mm == pytest.approx(y)
    core = np.column_stack([np.linspace(0.0, 140.0, 2801), np.zeros(2801)])
    bent = tb.map_points(core)
    length = np.sqrt((np.diff(bent, axis=0) ** 2).sum(axis=1)).sum()
    assert length == pytest.approx(140.0, abs=1e-3)
    # Before the bend nothing moves; an offset from the core stays an offset.
    assert np.allclose(tb.map_points([[10.0, -3.0], [s1, 2.0]]), [[10.0, -3.0], [s1, 2.0]])
    above, below = tb.map_points([[140.0, -3.0], [140.0, 3.0]])
    assert math.hypot(*(above - below)) == pytest.approx(6.0)


def test_a_straight_or_out_of_range_bend_leaves_the_temple_as_drawn():
    pts = [[0.0, 0.0], [70.0, 1.0], [140.0, -2.0]]
    straight = TipBend.resolve(TipBendParams(drop_angle_deg=0.0), 0.0, 140.0)
    assert straight.is_straight and straight.out_of_range() is None
    assert np.allclose(straight.map_points(pts), pts)
    whole = TipBend.resolve(TipBendParams(length_to_bend_mm=140.0), 0.0, 140.0)
    assert "nothing is left to drop" in whole.out_of_range()
    # Straight, but with more length to bend than temple: still out of range
    # (the drop read negative, unremarked).
    assert "nothing is left" in TipBend.resolve(
        TipBendParams(length_to_bend_mm=300.0, drop_angle_deg=0.0), 0.0, 140.0).out_of_range()
    early = TipBend.resolve(TipBendParams(length_to_bend_mm=3.0), 0.0, 140.0)
    assert "before the hinge" in early.out_of_range()
    late = TipBend.resolve(TipBendParams(length_to_bend_mm=138.0), 0.0, 140.0)
    assert "past the tip" in late.out_of_range()
    assert np.allclose(late.map_points(pts), pts)
    # The hinge end need not sit at the origin.
    moved = TipBend.resolve(TipBendParams(length_to_bend_mm=100.0), -20.0, 140.0)
    assert moved.tip()[0] - (-20.0) == pytest.approx(
        TipBend.resolve(TipBendParams(length_to_bend_mm=100.0), 0.0, 140.0).tip()[0])


def test_flatten_for_view_closes_a_closed_curve():
    pts = forming.flatten_for_view(closed_diamond(0, 0, 10))
    assert pts[0] == pytest.approx(pts[-1])
    pts = forming.flatten_for_view(spline([(0, 0), (10, 2), (20, 0)]))
    assert pts[0] != pytest.approx(pts[-1])


def test_the_left_temple_bends_toward_its_own_drop():
    """The left tab is the right's mirror about the core line, so its drop
    goes toward −y (GuildModel's hand-off, 2026-11-04: both tabs bent toward
    +y, the left against its drawn drop)."""
    right = TipBend.resolve(TipBendParams(), -80.0, 142.0)
    left = TipBend.resolve(TipBendParams(), -80.0, 142.0, down=-1.0)
    assert right.down == 1.0 and left.down == -1.0
    # A dropped-tip outline's points and their mirror: the two tabs' drawings.
    pts = np.array([[-80.0, -4.6], [-20.0, 3.0], [30.0, 7.8], [62.0, 6.0],
                    [62.0, -2.0], [40.0, 0.0]])
    mirrored = pts * [1.0, -1.0]
    bent_r, bent_l = right.map_points(pts), left.map_points(mirrored)
    assert np.allclose(bent_l, bent_r * [1.0, -1.0])
    assert bent_r[3, 1] > 20.0 and bent_l[3, 1] < -20.0     # each toward its drop
    # The readouts are the same part's: the same reach, the tip "down" on both.
    assert left.reach_mm == pytest.approx(right.reach_mm)
    assert left.tip_drop_mm == pytest.approx(right.tip_drop_mm) and left.tip_drop_mm > 0.0
    assert left.tip()[1] == pytest.approx(-right.tip()[1])
    # The core keeps its length on the left as on the right.
    core = np.column_stack([np.linspace(-80.0, 62.0, 2841), np.zeros(2841)])
    bent = left.map_points(core)
    assert np.sqrt((np.diff(bent, axis=0) ** 2).sum(axis=1)).sum() == pytest.approx(142.0, abs=1e-3)
    # Off the core line the mirror axis moves with it.
    off = TipBend.resolve(TipBendParams(), 0.0, 140.0, core_y=2.0, down=-1.0)
    assert off.tip()[1] < 2.0 and off.tip_drop_mm == pytest.approx(right.tip_drop_mm)
