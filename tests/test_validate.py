"""Pre-export validator — layer counts, closure, mirror doubling."""
from framedraft.document import Layer
from framedraft.export.validate import validate
from helpers import line, circle, closed_diamond


def outline():
    return closed_diamond(0, 0, 40, layer=Layer.OUTLINE)


def test_valid_document_passes():
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10)]
    errors, warnings = validate(curves, mirror_on=False)
    assert errors == [] and warnings == []


def test_drill_holes_on_front_are_accepted():
    # Drill-mount holes (DRILL circles) are optional, recognized, and closed —
    # they must not produce errors or warnings on a valid front.
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10),
              circle(-20, 5, 0.7, layer=Layer.DRILL),
              circle(20, 5, 0.7, layer=Layer.DRILL)]
    errors, warnings = validate(curves, mirror_on=False)
    assert errors == [] and warnings == []


def test_mirror_doubles_lens_count():
    # One drawn lens + mirror ghost = a pair at export time; both the mirrored
    # and un-mirrored forms are valid now that any positive LENS count passes.
    curves = [outline(), circle(15, 0, 10)]
    errors, _ = validate(curves, mirror_on=True)
    assert errors == []
    errors, _ = validate(curves, mirror_on=False)
    assert errors == []


def test_lens_count_is_flexible():
    # Aviators (bridge opening) and shapes like peace-sign glasses carry more
    # than the classic pair — any positive LENS count is accepted; only a total
    # absence of LENS geometry is flagged.
    four = [outline(),
            circle(-20, 0, 8), circle(20, 0, 8),
            circle(-8, 12, 5), circle(8, 12, 5)]
    assert validate(four, mirror_on=False)[0] == []

    one = [outline(), circle(0, 0, 10)]
    assert validate(one, mirror_on=False)[0] == []

    none = [outline()]
    assert any("LENS" in e for e in validate(none, mirror_on=False)[0])


def test_missing_outline_is_an_error():
    curves = [circle(-15, 0, 10), circle(15, 0, 10)]
    errors, _ = validate(curves, mirror_on=False)
    assert any("OUTLINE" in e for e in errors)


def test_outline_hole_inside_profile_is_accepted():
    # Aviator bridge keyhole: a second closed OUTLINE curve inside the profile
    # is a decorative opening (Hole1) — GuildModel cuts it, so the document is
    # ready; the classification is surfaced as a warning, not an error.
    keyhole = closed_diamond(0, 10, 6, layer=Layer.OUTLINE)
    curves = [outline(), keyhole, circle(-15, 0, 10), circle(15, 0, 10)]
    errors, warnings = validate(curves, mirror_on=False)
    assert errors == []
    assert any("opening" in w for w in warnings)


def test_outline_stray_outside_profile_warns():
    # A closed OUTLINE curve outside the profile is an authoring mistake that
    # GuildModel ignores (largest curve wins) — mirror that: warn, don't error.
    stray = closed_diamond(120, 0, 10, layer=Layer.OUTLINE)
    curves = [outline(), stray, circle(-15, 0, 10), circle(15, 0, 10)]
    errors, warnings = validate(curves, mirror_on=False)
    assert errors == []
    assert any("outside the profile" in w for w in warnings)


def test_temple_cutout_outline_is_accepted():
    # Cut-out temples carry an opening inside the arm's OUTLINE profile.
    arm    = closed_diamond(60, 0, 50, layer=Layer.OUTLINE)
    cutout = closed_diamond(60, 0, 8, layer=Layer.OUTLINE)
    errors, warnings = validate([arm, cutout], mirror_on=False,
                                workspace_type="temple_r")
    assert errors == []
    assert any("opening" in w for w in warnings)


def test_open_machined_contour_with_gap_is_error():
    open_outline = line([(0, 0), (40, 0), (40, 30), (0, 29)],
                        layer=Layer.OUTLINE)          # 29 mm gap to start
    curves = [open_outline, circle(-15, 10, 8), circle(15, 10, 8)]
    errors, _ = validate(curves, mirror_on=False)
    assert any("not closed" in e for e in errors)


def test_open_contour_within_tolerance_is_warning():
    near_closed = line([(0, 0), (40, 0), (40, 30), (0, 30), (0, 0.05)],
                       layer=Layer.OUTLINE)           # 0.05 mm gap
    curves = [near_closed, circle(10, 15, 6), circle(30, 15, 6)]
    errors, warnings = validate(curves, mirror_on=False)
    assert errors == []
    assert any("auto-close" in w for w in warnings)


def test_temple_workspace_rules():
    temple_arm = closed_diamond(60, 0, 50, layer=Layer.OUTLINE)
    errors, _ = validate([temple_arm], mirror_on=False, workspace_type="temple_r")
    assert errors == []
    errors, _ = validate([temple_arm, circle(0, 0, 10)],   # stray LENS
                         mirror_on=False, workspace_type="temple_r")
    assert any("LENS" in e for e in errors)


def test_hinge_workspace_rules():
    pocket = circle(0, 0, 2, layer=Layer.HINGE)
    errors, _ = validate([pocket], mirror_on=False, workspace_type="hinge")
    assert errors == []
    errors, _ = validate([], mirror_on=False, workspace_type="hinge")
    assert any("HINGE" in e for e in errors)
    errors, _ = validate([pocket, outline()], mirror_on=False,
                         workspace_type="hinge")
    assert any("OUTLINE" in e for e in errors)


def test_mirrored_flag_curves_are_ignored():
    # A `.mirrored` ghost must not satisfy the LENS requirement on its own:
    # with only a ghost lens present the validator still sees zero real lenses.
    ghost = circle(15, 0, 10)
    ghost.mirrored = True
    curves = [outline(), ghost]
    errors, _ = validate(curves, mirror_on=False)
    assert any("LENS" in e for e in errors)   # ghost doesn't count → 0 lenses


# ── The origin rule (BUILDPLAN *Road to 1.4*, item 1) ───────────────────────
# GuildModel 1.8.2 centers the blank on the drawing's origin, places a front
# as drawn, and runs a temple's core along y = 0 with the hinge end snapped to
# the blank's end. Warnings only: the dot stays green "with warnings".

def temple_arm(cy=0.0, length=120.0, width=10.0):
    """A closed temple OUTLINE: a length × width rectangle from x = 0, centered
    on y = cy."""
    hw = width / 2
    return line([(0, cy - hw), (length, cy - hw), (length, cy + hw), (0, cy + hw)],
                closed=True, layer=Layer.OUTLINE)


def test_temple_on_the_core_line_is_quiet():
    errors, warnings = validate([temple_arm()], mirror_on=False,
                                workspace_type="temple_r", stock_mm=(170.0, 30.0))
    assert errors == [] and warnings == []


def test_temple_off_the_core_line_warns_with_the_gap():
    arm = temple_arm(cy=12.0)                      # y 7..17: all to one side
    errors, warnings = validate([arm], False, "temple_r")
    assert errors == []
    assert any("core line" in w and "7.0 mm" in w for w in warnings)
    arm = temple_arm(cy=-12.0)                     # the other side
    _, warnings = validate([arm], False, "temple_l")
    assert any("core line" in w and "7.0 mm" in w for w in warnings)


def test_temple_edge_on_the_core_line_counts_as_off_it():
    arm = temple_arm(cy=5.0, width=10.0)           # y 0..10: the wire on the edge
    _, warnings = validate([arm], False, "temple_r")
    assert any("core line" in w and "0.0 mm" in w for w in warnings)


def test_front_is_never_asked_to_straddle_zero():
    curves = [closed_diamond(0, 30, 20, layer=Layer.OUTLINE),
              circle(-8, 30, 5), circle(8, 30, 5)]
    errors, warnings = validate(curves, False, "front")
    assert errors == [] and warnings == []


def test_outline_inside_the_stock_guide_is_quiet():
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10)]    # ±40 mm
    _, warnings = validate(curves, False, "front", stock_mm=(80.0, 80.0))
    assert warnings == []


def test_front_outline_past_the_stock_guide_warns_with_the_overrun():
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10)]    # ±40 mm
    _, warnings = validate(curves, False, "front", stock_mm=(60.0, 85.0))
    assert any("10.0 mm past the 60 × 85 mm stock guide" in w for w in warnings)
    _, warnings = validate(curves, False, "front", stock_mm=(60.0, 50.0))
    assert any("15.0 mm past the 60 × 50 mm stock guide" in w for w in warnings)


def test_no_stock_guide_means_no_fit_check():
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10)]
    _, warnings = validate(curves, False, "front")
    assert warnings == []


def test_temple_longer_than_the_blank_warns_by_length_not_position():
    # GuildModel snaps the hinge end to the blank's end, so where the temple
    # sits along x is irrelevant: only its length counts.
    arm = temple_arm(length=150.0)                 # x 0..150 on a centered 170 guide
    _, warnings = validate([arm], False, "temple_r", stock_mm=(170.0, 30.0))
    assert warnings == []
    arm = temple_arm(length=180.0)
    _, warnings = validate([arm], False, "temple_r", stock_mm=(170.0, 30.0))
    assert any("10.0 mm longer than the 170 mm stock guide" in w for w in warnings)


def test_temple_past_the_blank_across_the_core_line_warns():
    arm = temple_arm(width=40.0)                   # y ±20 on a 30 mm blank
    _, warnings = validate([arm], False, "temple_r", stock_mm=(170.0, 30.0))
    assert any("5.0 mm past the 30 mm stock guide across the core line" in w
               for w in warnings)
    assert not any("drawn off the core line" in w for w in warnings)


def test_hinge_pocket_has_no_stock_or_origin_rule():
    pocket = circle(30, 30, 2, layer=Layer.HINGE)
    errors, warnings = validate([pocket], False, "hinge", stock_mm=(10.0, 20.0))
    assert errors == [] and warnings == []


def test_the_origin_warnings_never_make_an_error():
    arm = temple_arm(cy=10.0, length=200.0, width=8.0)   # y 6..14: off the
    errors, warnings = validate([arm], False, "temple_r",  # line, and too long
                                stock_mm=(170.0, 30.0))
    assert errors == []
    assert len(warnings) == 2


# ── INLAY (Road to 2.0, item 1): a seat GuildModel cuts to a depth it owns ──

def seat(cx, cy, r=4.0):
    return closed_diamond(cx, cy, r, layer=Layer.INLAY)


def front_with(*extra):
    return [outline(), circle(-15, 0, 10), circle(15, 0, 10), *extra]


def test_an_inlay_inside_the_profile_is_quiet():
    errors, warnings = validate(front_with(seat(0, -30)), mirror_on=False)
    assert errors == [] and warnings == []


def test_an_inlay_outside_the_profile_is_an_error():
    errors, _ = validate(front_with(seat(60, 0)), mirror_on=False)
    assert any("INLAY 1 lies off the part" in e for e in errors)


def test_an_inlay_never_crosses_a_lens_or_a_drill_hole():
    errors, _ = validate(front_with(seat(10, 0)), mirror_on=False)   # into the lens
    assert any("INLAY 1 crosses a LENS curve" in e for e in errors)
    drill = circle(0, -28, 0.7, layer=Layer.DRILL)
    errors, _ = validate(front_with(drill, seat(0, -30)), mirror_on=False)
    assert any("INLAY 1 crosses a DRILL curve" in e for e in errors)


def test_an_inlay_never_crosses_a_decorative_opening():
    # A closed OUTLINE curve inside the profile is cut through, like a lens:
    # a seat inside it sits in air, and one across it has no floor.
    opening = closed_diamond(0, -25, 6, layer=Layer.OUTLINE)
    for inside_or_across in (seat(0, -25, 3), seat(0, -31, 3)):
        errors, _ = validate(front_with(opening, inside_or_across), mirror_on=False)
        assert any("INLAY 1 crosses a decorative opening" in e for e in errors)
    errors, _ = validate(front_with(opening, seat(0, 30, 3)), mirror_on=False)
    assert errors == []


def test_the_ghost_lens_counts_as_cut():
    # One lens drawn on the right with the Ghost on: the seat on the left
    # sits in the mirrored aperture.
    curves = [outline(), circle(15, 0, 10), seat(-15, 0)]
    errors, _ = validate(curves, mirror_on=True)
    assert any("crosses a LENS" in e for e in errors)
    errors, _ = validate(curves, mirror_on=False)
    assert not any("crosses a LENS" in e for e in errors)


def test_nested_inlays_are_a_step_and_overlapping_ones_an_error():
    errors, _ = validate(front_with(seat(0, -28, 6), seat(0, -28, 2)), mirror_on=False)
    assert errors == []
    errors, _ = validate(front_with(seat(0, -28, 5), seat(4, -28, 5)), mirror_on=False)
    assert any("INLAY 1 and INLAY 2 overlap without nesting" in e for e in errors)


def test_an_inlay_inside_the_hinge_curve_is_a_step_and_across_it_an_error():
    arm = closed_diamond(60, 0, 50, layer=Layer.OUTLINE)
    hinge = closed_diamond(95, 0, 8, layer=Layer.HINGE)
    errors, _ = validate([arm, hinge, seat(95, 0, 3)], False, "temple_r")
    assert errors == []
    errors, _ = validate([arm, hinge, seat(89, 0, 4)], False, "temple_r")
    assert any("INLAY 1 crosses a HINGE curve" in e for e in errors)


def test_an_open_inlay_is_not_closed():
    open_seat = line([(0, -34), (4, -30), (0, -26)], layer=Layer.INLAY)
    errors, _ = validate(front_with(open_seat), mirror_on=False)
    assert any("INLAY contour is not closed" in e for e in errors)
