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


def test_mirror_doubles_lens_count():
    # One drawn lens + mirror ghost = the required two at export time
    curves = [outline(), circle(15, 0, 10)]
    errors, _ = validate(curves, mirror_on=True)
    assert errors == []
    errors, _ = validate(curves, mirror_on=False)
    assert any("LENS" in e for e in errors)


def test_missing_outline_is_an_error():
    curves = [circle(-15, 0, 10), circle(15, 0, 10)]
    errors, _ = validate(curves, mirror_on=False)
    assert any("OUTLINE" in e for e in errors)


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
    ghost = circle(15, 0, 10)
    ghost.mirrored = True
    curves = [outline(), circle(-15, 0, 10), ghost]
    errors, _ = validate(curves, mirror_on=False)
    assert any("LENS" in e for e in errors)   # ghost doesn't count
