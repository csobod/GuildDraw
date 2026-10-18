"""Generate a demo frame-front DXF exactly as GuildDraw exports it.

Produces a wayfarer-ish front: two superellipse lenses (LENS, the right one
drawn and the left one its mirror, baked as Mirror does: since 2.0 the DXF
carries the curves drawn, never the Ghost) and an outline derived by
offsetting the lens pair 4.5 mm and bridging the nose (OUTLINE). Used to feed
GuildModel's DXF → mesh pipeline with representative GuildDraw output.

Run:  .venv\\Scripts\\python scripts\\make_demo_front.py [out.dxf]
"""
import math
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from shapely.geometry import Polygon
from shapely.ops import unary_union

from framedraft.document import Curve, SplineNode, Layer
from framedraft.geometry import compute_catmull_handles, mirror_curve, sample_curve
from framedraft.export.dxf import export_dxf

# Boxing dimensions (mm) — GuildDraw defaults: A=50, DBL=18; B chosen for a
# classic acetate front. Scene is Y-down; export negates Y.
A, B, DBL = 50.0, 38.0, 18.0
LENS_CX = DBL / 2 + A / 2          # 34.0 — boxing center of the right-half lens
OUTLINE_OFFSET = 4.5               # rim width around the lenses
BROW_LIFT = 2.0                    # extra material along the brow


def closed_spline(pts, layer):
    nodes = [SplineNode(x=x, y=y) for x, y in pts]
    compute_catmull_handles(nodes, closed=True)
    return Curve(kind="spline", layer=layer, nodes=nodes, closed=True)


def lens_points(cx, n=14, exp=2.5):
    """Superellipse lens around (cx, 0): |x/a|^exp + |y/b|^exp = 1."""
    a, b = A / 2, B / 2
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        c, s = math.cos(t), math.sin(t)
        x = a * math.copysign(abs(c) ** (2 / exp), c)
        y = b * math.copysign(abs(s) ** (2 / exp), s)
        pts.append((cx + x, y))
    return pts


def outline_points(lens_curve):
    """Offset the mirrored lens pair and bridge the nose → frame outline."""
    samples = [(x, y) for x, y, _ in sample_curve(lens_curve, n_per_seg=12)]
    right = Polygon(samples)
    left  = Polygon([(-x, y) for x, y in samples])
    # Bridge bar: spans the DBL between the lens rims, sitting high (Y-down:
    # negative y is up-screen toward the brow).
    bridge = Polygon([(-DBL / 2 - 4, -B / 2 + 1), (DBL / 2 + 4, -B / 2 + 1),
                      (DBL / 2 + 4, -2.0),        (-DBL / 2 - 4, -2.0)])
    body = unary_union([
        right.buffer(OUTLINE_OFFSET, quad_segs=8),
        left.buffer(OUTLINE_OFFSET,  quad_segs=8),
        bridge.buffer(2.0, quad_segs=8),
    ])
    # Brow lift: thicken the top edge (negative y) slightly.
    brow = Polygon([(-2 * LENS_CX, -B / 2 - OUTLINE_OFFSET - BROW_LIFT),
                    ( 2 * LENS_CX, -B / 2 - OUTLINE_OFFSET - BROW_LIFT),
                    ( 2 * LENS_CX, -B / 2 + 4), (-2 * LENS_CX, -B / 2 + 4)])
    body = unary_union([body, brow.intersection(body.buffer(BROW_LIFT))])
    return list(body.exterior.coords)[:-1]


def main(out_path):
    from framedraft.fitting import fit_curve
    lens = closed_spline(lens_points(LENS_CX), Layer.LENS)
    # Fitted within 0.05 mm, as Rebuild fits: a Catmull-Rom spline through
    # every 72nd point overshot at the bridge and crossed itself.
    outline = fit_curve(outline_points(lens), tol_mm=0.05, closed=True,
                        layer=Layer.OUTLINE).curve
    # The left lens baked across x = 0, as Mirror does: the export writes the
    # curves drawn only (it took mirror_on/axis_x/horizontal before 2.0, and
    # this script raised a TypeError).
    export_dxf(curves=[outline, lens, mirror_curve(lens, 0.0)], path=str(out_path))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "demo_front.dxf"
    main(out)
