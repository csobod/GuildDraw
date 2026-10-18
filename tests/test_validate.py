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


def test_the_ghost_is_never_counted():
    # GuildModel reads only the curves drawn (2026-10-16): one lens with the
    # Ghost on is one lens, and in an outline drawn for two the other eye
    # would be cut solid. With the Ghost on, the twin is named as the gap.
    curves = [outline(), circle(15, 0, 10)]
    errors, _ = validate(curves, mirror_on=True)
    assert errors == ["The other lens is the Ghost's only, and GuildModel reads "
                      "only the curves drawn: select the lens and Mirror (bake) it, "
                      "or turn the Ghost off for a monocle."]
    errors, _ = validate(curves, mirror_on=False)
    assert errors == ["One lens in an outline drawn for two: GuildModel would cut "
                      "the other eye solid. Draw the second lens, or Mirror "
                      "(bake) this one."]
    both = curves + [circle(-15, 0, 10)]
    assert validate(both, mirror_on=True)[0] == []
    assert validate(both, mirror_on=False)[0] == []


def test_a_front_holds_two_lenses_or_one():
    # GuildModel refuses a third lens rather than guess which two are the
    # eyes; one lens is a monocle when the outline is one rim around it.
    four = [outline(),
            circle(-20, 0, 8), circle(20, 0, 8),
            circle(-8, 12, 5), circle(8, 12, 5)]
    assert any("found 4" in e for e in validate(four, mirror_on=False)[0])

    monocle = [outline(), circle(0, 0, 10)]
    assert validate(monocle, mirror_on=False)[0] == []
    assert validate(monocle, mirror_on=True)[0] == []

    none = [outline()]
    assert any("LENS" in e for e in validate(none, mirror_on=False)[0])


def test_a_monocle_beside_the_axis_with_the_ghost_on_asks_for_a_choice():
    rim = closed_diamond(-30, 0, 20, layer=Layer.OUTLINE)
    curves = [rim, circle(-30, 0, 10)]
    assert validate(curves, mirror_on=False)[0] == []
    errors, _ = validate(curves, mirror_on=True)
    assert errors and "turn the Ghost off for a monocle" in errors[0]


def test_a_front_component_on_one_end_only_is_the_ghosts_twin():
    pocket = closed_diamond(35, 0, 3, layer=Layer.COMPONENT)
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10), pocket]
    errors, _ = validate(curves, mirror_on=True)
    assert errors == ["1 COMPONENT curve has a twin that is the Ghost's only, and "
                      "GuildModel reads only the curves drawn: Mirror (bake) it, "
                      "or turn the Ghost off."]
    assert validate(curves, mirror_on=False)[0] == []
    twin = closed_diamond(-35, 0, 3, layer=Layer.COMPONENT)
    assert validate(curves + [twin], mirror_on=True)[0] == []


def test_a_curve_across_the_axis_is_its_own_twin():
    # A temple's pocket across the core line, a front's bridge mount across
    # the bridge: the Ghost overlaps the curve itself.
    arm = closed_diamond(60, 0, 50, layer=Layer.OUTLINE)
    pocket = line([(95, -4), (99, 3), (91, 2), (95, -4)], layer=Layer.COMPONENT)
    pocket.closed = True
    assert validate([arm, pocket], True, "temple_r")[0] == []
    bridge = line([(-3, -30), (4, -29), (4, -25), (-3, -26), (-3, -30)],
                  layer=Layer.COMPONENT)
    bridge.closed = True
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10), bridge]
    assert validate(curves, mirror_on=True)[0] == []


def test_a_lens_crossing_its_rims_edge_is_an_error():
    # Out past the rim's edge at x = 40 by 3 mm (at x = 30 it touches the edge
    # from inside, which a coarse trace read as a crossing).
    curves = [outline(), circle(-15, 0, 10), circle(33, 0, 10)]
    errors, _ = validate(curves, mirror_on=False)
    assert any("LENS 2 crosses the edge of its rim" in e for e in errors)


def test_a_curve_lying_on_another_is_an_error():
    # A Mirror baked over an outline already whole reads as separated rims.
    curves = [outline(), outline(), circle(-15, 0, 10), circle(15, 0, 10)]
    errors, _ = validate(curves, mirror_on=False)
    assert errors == ["1 OUTLINE curve lies on top of another OUTLINE curve, and "
                      "GuildModel reads each: delete the copy."]


def test_a_self_crossing_or_flat_lens_is_an_error_and_no_lens():
    # A fishtail at a corner: the ring crosses itself.
    fish = line([(-25, -8), (-5, -8), (-5, 8), (-27, 6), (-23, 10),
                 (-25, -8)], layer=Layer.LENS)
    fish.closed = True
    curves = [outline(), fish, circle(15, 0, 10)]
    errors, _ = validate(curves, mirror_on=False)
    assert any("LENS curve crosses itself" in e for e in errors)
    # A closed two-node lens folded flat encloses nothing and is not counted.
    flat = line([(-25, 0), (-5, 0)], layer=Layer.LENS)
    flat.closed = True
    errors, _ = validate([outline(), flat, circle(15, 0, 10)], mirror_on=False)
    assert any("LENS curve encloses no area" in e for e in errors)
    assert any("One lens in an outline drawn for two" in e for e in errors)


def test_degenerate_curves_are_errors():
    one_node = line([(0, 0)], layer=Layer.LENS)
    no_radius = circle(-20, 5, 0.7, layer=Layer.DRILL)
    no_radius.radius = None
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10), one_node, no_radius]
    errors, _ = validate(curves, mirror_on=False)
    assert any("single node" in e for e in errors)
    assert any("DRILL circle has no radius" in e for e in errors)


def test_an_open_arc_on_a_machined_layer_is_not_closed():
    from helpers import arc
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10),
              arc(-25, 20, 3, 0, 180, layer=Layer.COMPONENT)]
    errors, _ = validate(curves, mirror_on=False)
    assert any("COMPONENT contour is not closed" in e for e in errors)


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


def test_component_workspace_rules():
    pocket = circle(0, 0, 2, layer=Layer.COMPONENT)
    errors, _ = validate([pocket], mirror_on=False, workspace_type="component")
    assert errors == []
    errors, _ = validate([], mirror_on=False, workspace_type="component")
    assert any("COMPONENT" in e for e in errors)
    errors, _ = validate([pocket, outline()], mirror_on=False,
                         workspace_type="component")
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


def test_the_component_tab_has_no_stock_or_origin_rule():
    pocket = circle(30, 30, 2, layer=Layer.COMPONENT)
    errors, warnings = validate([pocket], False, "component", stock_mm=(10.0, 20.0))
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


def test_the_ghost_lens_is_never_cut():
    # One lens drawn on the right with the Ghost on: GuildModel never cuts the
    # Ghost's lens, so a seat where it would be crosses nothing.
    curves = [outline(), circle(15, 0, 10), seat(-15, 0)]
    for mirror_on in (True, False):
        errors, _ = validate(curves, mirror_on=mirror_on)
        assert not any("crosses a LENS" in e for e in errors)


def test_nested_inlays_are_a_step_and_overlapping_ones_an_error():
    errors, _ = validate(front_with(seat(0, -28, 6), seat(0, -28, 2)), mirror_on=False)
    assert errors == []
    errors, _ = validate(front_with(seat(0, -28, 5), seat(4, -28, 5)), mirror_on=False)
    assert any("INLAY 1 and INLAY 2 overlap without nesting" in e for e in errors)


def test_an_inlay_inside_a_component_curve_is_a_step_and_across_it_an_error():
    arm = closed_diamond(60, 0, 50, layer=Layer.OUTLINE)
    hinge = closed_diamond(95, 0, 8, layer=Layer.COMPONENT)
    errors, _ = validate([arm, hinge, seat(95, 0, 3)], False, "temple_r")
    assert errors == []
    errors, _ = validate([arm, hinge, seat(89, 0, 4)], False, "temple_r")
    assert any("INLAY 1 crosses a COMPONENT curve" in e for e in errors)


def test_an_open_inlay_is_not_closed():
    open_seat = line([(0, -34), (4, -30), (0, -26)], layer=Layer.INLAY)
    errors, _ = validate(front_with(open_seat), mirror_on=False)
    assert any("INLAY contour is not closed" in e for e in errors)


# ── The 2.0 polish round: the Ghost rules made exact, and fast ─────────────

def test_a_decorative_openings_twin_is_not_stood_for_by_the_profile():
    # The canvas ghosts an opening beside the axis, and the fill punches both;
    # GuildModel cuts the one drawn. The profile around the twin covered it,
    # and passed it (the 2.0 polish round).
    opening = closed_diamond(10, -25, 4, layer=Layer.OUTLINE)
    curves = [outline(), opening, circle(-15, 0, 10), circle(15, 0, 10)]
    assert validate(curves, mirror_on=False)[0] == []
    errors, _ = validate(curves, mirror_on=True)
    assert errors == ["1 decorative opening has a twin that is the Ghost's only, "
                      "and GuildModel reads only the curves drawn: Mirror (bake) "
                      "it, or turn the Ghost off."]
    twin = closed_diamond(-10, -25, 4, layer=Layer.OUTLINE)
    assert validate(curves + [twin], mirror_on=True)[0] == []
    # A small pocket's twin is not stood for by a big pocket around it.
    pocket = closed_diamond(25, -20, 2, layer=Layer.COMPONENT)
    big = closed_diamond(-25, -20, 9, layer=Layer.COMPONENT)
    errors, _ = validate([outline(), circle(-15, 0, 10), circle(15, 0, 10),
                          pocket, big], mirror_on=True)
    assert any("COMPONENT curve" in e for e in errors)


def test_a_curve_reaching_the_axis_is_not_its_own_twin():
    line_to_axis = line([(-20, -30), (0, -30)], layer=Layer.SCULPT)
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10), line_to_axis]
    errors, _ = validate(curves, mirror_on=True)
    assert any("SCULPT curve has a twin" in e for e in errors)
    symmetric = line([(-20, -30), (20, -30)], layer=Layer.SCULPT)
    curves[-1] = symmetric
    assert validate(curves, mirror_on=True)[0] == []


def test_a_lens_overlapping_a_decorative_opening_is_not_held():
    slip = circle(15, 0, 10, layer=Layer.OUTLINE)       # an OUTLINE copy of a lens
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10), slip]
    errors, _ = validate(curves, mirror_on=False)
    assert any("LENS 2 overlaps a decorative opening" in e for e in errors)


def test_a_contour_inside_a_stray_is_a_stray():
    stray = closed_diamond(120, 0, 10, layer=Layer.OUTLINE)
    inner = closed_diamond(120, 0, 3, layer=Layer.OUTLINE)
    curves = [outline(), stray, inner, circle(-15, 0, 10), circle(15, 0, 10)]
    _errors, warnings = validate(curves, mirror_on=False)
    assert any("2 OUTLINE curve(s) fall outside" in w for w in warnings)
    assert not any("opening" in w for w in warnings)


def test_a_tiny_seat_is_too_small_for_guildmodel():
    tiny = closed_diamond(0, -25, 0.4, layer=Layer.INLAY)   # 0.32 mm²
    errors, _ = validate([outline(), circle(-15, 0, 10), circle(15, 0, 10), tiny],
                         mirror_on=False)
    assert any("INLAY curve encloses no area" in e for e in errors)


def test_temple_sculpt_lines_and_the_component_tab():
    arm = closed_diamond(60, 0, 50, layer=Layer.OUTLINE)
    sculpt = line([(40, 5), (60, 8)], layer=Layer.SCULPT)   # GuildModel ignores it
    assert validate([arm, sculpt], True, "temple_r")[0] == []
    half = line([(0, -3), (5, -3), (5, 3), (0, 3)], layer=Layer.COMPONENT)
    half.closed = True
    errors, _ = validate([half], True, "component")
    assert any("COMPONENT curve has a twin" in e for e in errors)
    assert validate([half], False, "component")[0] == []


def test_the_ghost_checks_stay_fast_on_a_dense_drawing():
    import time
    curves = [outline(), circle(-15, 0, 10), circle(15, 0, 10)]
    for i in range(150):
        y = -38 + 0.5 * i
        curves.append(line([(-30, y), (-10, y + 1)], layer=Layer.SCULPT))
        curves.append(line([(10, y + 1), (30, y)], layer=Layer.SCULPT))
    start = time.perf_counter()
    validate(curves, mirror_on=True)
    assert time.perf_counter() - start < 2.0      # 160 s before the rework
