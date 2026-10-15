"""
Pre-export validator — mirrors GuildModel's strict intake rules so the maker
catches problems in-app rather than at DXF import time.

Scene units are mm (1 scene unit = 1 mm), so all coordinates are used
directly without any px_per_mm conversion.
"""
import math
from ..document import Curve, Layer, MACHINED_LAYERS


_CLOSURE_TOL_MM = 0.1   # GuildModel auto-closes within 0.1 mm
_STOCK_TOL_MM   = 0.05  # an OUTLINE this far past the stock guide is on it


def _endpoint_gap_mm(curve: Curve) -> float:
    """Distance in mm between first and last node of an open curve."""
    if not curve.nodes or len(curve.nodes) < 2:
        return 0.0
    n0, n1 = curve.nodes[0], curve.nodes[-1]
    return math.hypot(n1.x - n0.x, n1.y - n0.y)


def _classify_extra_outlines(outlines: list) -> tuple[int, int]:
    """Classify a multi-curve OUTLINE layer the way GuildModel's intake does
    (``io_import/normalize.assemble_outline``): the largest-area contour is
    the profile; every other curve whose interior falls inside it is a
    decorative opening (Hole1…), and one outside it is a stray.

    Returns ``(n_holes, n_stray)``. Degenerate contours (fewer than 3 sample
    points or zero area) count as neither — GuildModel drops slivers too.
    """
    from shapely.geometry import Polygon
    from ..geometry import sample_curve

    polys = []
    for c in outlines:
        pts = [(x, y) for x, y, _t in sample_curve(c)]
        if len(pts) < 3:
            continue
        try:
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda g: g.area)
        except Exception:
            continue
        if poly.area > 0:
            polys.append(poly)
    if len(polys) < 2:
        return 0, 0

    shell = max(polys, key=lambda p: p.area)
    holes = stray = 0
    for p in polys:
        if p is shell:
            continue
        # representative_point() is guaranteed inside p, so this is a true
        # containment test even when the curves share a tangent point.
        if shell.contains(p.representative_point()):
            holes += 1
        else:
            stray += 1
    return holes, stray


def _outline_bounds(outlines: list):
    """Bounding box ``(minx, miny, maxx, maxy)`` in mm of the sampled OUTLINE
    curves, or None when nothing samples."""
    from ..geometry import sample_curve
    xs: list[float] = []
    ys: list[float] = []
    for c in outlines:
        for x, y, _t in sample_curve(c):
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _origin_checks(outlines: list, workspace_type: str,
                   stock_mm, warnings: list) -> None:
    """The placement GuildModel 1.8.2 assumes, checked where the maker draws
    (BUILDPLAN *Road to 1.4*, item 1). GuildModel centers the blank on the
    drawing's origin and places a front as drawn; a temple's y = 0 is the core
    line, and its hinge end is snapped to the blank's end, so along the blank
    only the temple's length counts. Warnings, never errors: the maker may mean
    it, and GuildModel offers the old centered placement as a checkbox.

    ``stock_mm`` is ``(width, height)`` of the workspace's stock guide, or
    None to skip the fit check.
    """
    bb = _outline_bounds(outlines)
    if bb is None:
        return
    minx, miny, maxx, maxy = bb
    is_temple = workspace_type in ("temple_r", "temple_l")

    if is_temple and not (miny < 0.0 < maxy):
        gap = miny if miny >= 0.0 else -maxy
        warnings.append(
            f"Temple OUTLINE is drawn off the core line (y = 0) by {gap:.1f} mm; "
            "GuildModel keeps the drawing's zero on the blank's center line."
        )

    if stock_mm is None:
        return
    w, h = float(stock_mm[0]), float(stock_mm[1])
    if is_temple:
        over = (maxx - minx) - w
        if over > _STOCK_TOL_MM:
            warnings.append(
                f"Temple OUTLINE is {over:.1f} mm longer than the {w:g} mm "
                "stock guide."
            )
        over = max(-h / 2.0 - miny, maxy - h / 2.0)
        if over > _STOCK_TOL_MM:
            warnings.append(
                f"Temple OUTLINE runs {over:.1f} mm past the {h:g} mm stock "
                "guide across the core line."
            )
    else:
        over = max(-w / 2.0 - minx, maxx - w / 2.0,
                   -h / 2.0 - miny, maxy - h / 2.0)
        if over > _STOCK_TOL_MM:
            warnings.append(
                f"OUTLINE runs {over:.1f} mm past the {w:g} × {h:g} mm stock "
                "guide, which GuildModel centers on the origin."
            )


def _outline_layer_check(outlines: list, errors: list, warnings: list,
                         label: str) -> None:
    """Shared OUTLINE rule: at least one contour; extra contours are fine and
    classified as openings (inside the profile) or strays (outside)."""
    if not outlines:
        errors.append(f"{label} 1 OUTLINE contour, found 0.")
        return
    if len(outlines) == 1:
        return
    holes, stray = _classify_extra_outlines(outlines)
    if holes:
        warnings.append(
            f"{holes} closed OUTLINE curve(s) inside the profile — "
            "GuildModel cuts them as decorative openings (Hole1…)."
        )
    if stray:
        warnings.append(
            f"{stray} OUTLINE curve(s) fall outside the profile — "
            "GuildModel ignores them; the largest curve is the profile."
        )


def validate(
    curves:    list,   # original (non-mirrored) Curve objects
    mirror_on: bool,
    workspace_type: str = "front",
    stock_mm=None,     # (width, height) of the stock guide in mm, or None
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings).  Errors mean "not GuildModel-ready" and drive
    the readiness dot, but they no longer block DXF export — the maker decides
    when geometry is complete and GuildModel's intake is the final gate.

    ``stock_mm`` is the workspace's stock guide, centered on the origin like
    GuildModel's blank; an OUTLINE that leaves it is warned about with the
    overrun. A temple drawn off the core line (y = 0) is warned about whether
    or not a guide is given. The OUTLINE is never mirrored, so the checks see
    it as drawn.

    Layer-count rules depend on the workspace:
      front    — OUTLINE ≥1 (the largest contour is the profile; closed curves
                 inside it are decorative openings Hole1… — an aviator's bridge
                 keyhole — and ones outside it are strays, both warned about
                 the way GuildModel's intake does), LENS ≥1 (any count:
                 aviators and other unusual shapes carry more than the classic
                 pair; mirror doubling counts)
      temple_* — OUTLINE ≥1 (same profile/opening rule — cut-out temples),
                 no LENS allowed
      hinge    — HINGE ≥1, no OUTLINE/LENS allowed
    """
    errors:   list[str] = []
    warnings: list[str] = []

    from ..export.dxf import _MIRROR_LAYERS
    export: list[Curve] = [c for c in curves if not c.mirrored]
    if mirror_on:
        export += [c for c in curves if not c.mirrored and c.layer in _MIRROR_LAYERS]

    by_layer: dict[Layer, int] = {l: 0 for l in Layer}
    for c in export:
        by_layer[c.layer] += 1

    outlines = [c for c in export if c.layer == Layer.OUTLINE]
    if workspace_type == "front":
        _outline_layer_check(outlines, errors, warnings, "Need at least")
        if by_layer[Layer.LENS] < 1:
            errors.append(
                f"Need at least 1 LENS contour, found {by_layer[Layer.LENS]}."
            )
        _origin_checks(outlines, workspace_type, stock_mm, warnings)
    elif workspace_type in ("temple_r", "temple_l"):
        _outline_layer_check(outlines, errors, warnings, "Temple needs at least")
        if by_layer[Layer.LENS]:
            errors.append(
                f"LENS does not belong in a temple workspace "
                f"(found {by_layer[Layer.LENS]})."
            )
        _origin_checks(outlines, workspace_type, stock_mm, warnings)
    elif workspace_type == "hinge":
        if by_layer[Layer.HINGE] < 1:
            errors.append("Hinge pocket needs at least 1 HINGE contour.")
        for bad in (Layer.OUTLINE, Layer.LENS):
            if by_layer[bad]:
                errors.append(
                    f"{bad.value} does not belong in the hinge workspace "
                    f"(found {by_layer[bad]})."
                )

    for c in export:
        if c.layer not in MACHINED_LAYERS:
            continue
        if not c.closed:
            gap = _endpoint_gap_mm(c)
            if gap > _CLOSURE_TOL_MM:
                errors.append(
                    f"{c.layer.value} contour is not closed "
                    f"(endpoint gap {gap:.3f} mm > {_CLOSURE_TOL_MM} mm)."
                )
            else:
                warnings.append(
                    f"{c.layer.value} contour marked open but endpoints are "
                    f"within {_CLOSURE_TOL_MM} mm — GuildModel will auto-close."
                )

    return errors, warnings
