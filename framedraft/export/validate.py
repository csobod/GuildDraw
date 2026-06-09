"""
Pre-export validator — mirrors GuildCAM's strict intake rules so the maker
catches problems in-app rather than at DXF import time.

Scene units are mm (1 scene unit = 1 mm), so all coordinates are used
directly without any px_per_mm conversion.
"""
import math
from ..document import Curve, Layer, MACHINED_LAYERS


_CLOSURE_TOL_MM = 0.1   # GuildCAM auto-closes within 0.1 mm


def _endpoint_gap_mm(curve: Curve) -> float:
    """Distance in mm between first and last node of an open curve."""
    if not curve.nodes or len(curve.nodes) < 2:
        return 0.0
    n0, n1 = curve.nodes[0], curve.nodes[-1]
    return math.hypot(n1.x - n0.x, n1.y - n0.y)


def validate(
    curves:    list,   # original (non-mirrored) Curve objects
    mirror_on: bool,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings).  Export is blocked if errors is non-empty."""
    errors:   list[str] = []
    warnings: list[str] = []

    from ..export.dxf import _MIRROR_LAYERS
    export: list[Curve] = [c for c in curves if not c.mirrored]
    if mirror_on:
        export += [c for c in curves if not c.mirrored and c.layer in _MIRROR_LAYERS]

    by_layer: dict[Layer, int] = {l: 0 for l in Layer}
    for c in export:
        by_layer[c.layer] += 1

    if by_layer[Layer.OUTLINE] != 1:
        errors.append(
            f"Need exactly 1 OUTLINE contour, found {by_layer[Layer.OUTLINE]}."
        )
    if by_layer[Layer.LENS] != 2:
        errors.append(
            f"Need exactly 2 LENS contours, found {by_layer[Layer.LENS]}."
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
                    f"within {_CLOSURE_TOL_MM} mm — GuildCAM will auto-close."
                )

    known = {l.value for l in Layer}
    used = {c.layer.value for c in export}
    unknown = used - known
    if unknown:
        warnings.append(
            f"Curves on unrecognised layers {unknown} will be ignored by GuildCAM."
        )

    return errors, warnings
