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
    # Drill-mount holes (DRILL circles) are optional, recognised, and closed —
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
    curves = [near_closed, circle(-15, 10, 8), circle(15, 10, 8)]
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
