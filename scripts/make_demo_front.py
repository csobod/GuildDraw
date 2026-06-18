"""Generate a demo frame-front DXF exactly as GuildDraw exports it.

Produces a wayfarer-ish front: two superellipse lenses (LENS, mirror-doubled
at export like the app does) and an outline derived by offsetting the lens
pair 4.5 mm and bridging the nose (OUTLINE). Used to feed GuildCAM's
DXF → mesh pipeline with representative GuildDraw output.

Run:  .venv\\Scripts\\python scripts\\make_demo_front.py [out.dxf]
"""
import math
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from shapely.geometry import Polygon
from shapely.ops import unary_union

from framedraft.document import Curve, SplineNode, Layer
from framedraft.geometry import compute_catmull_handles, sample_curve
from framedraft.export.dxf import export_dxf

# Boxing dimensions (mm) — GuildDraw defaults: A=50, DBL=18; B chosen for a
# classic acetate front. Scene is Y-down; export negates Y.
A, B, DBL = 50.0, 38.0, 18.0
LENS_CX = DBL / 2 + A / 2          # 34.0 — boxing centre of the right-half lens
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
    ext = body.exterior.simplify(0.15)
    coords = list(ext.coords)[:-1]
    # Decimate to a drafting-plausible node count, keeping shape fidelity.
    step = max(1, len(coords) // 72)
    return coords[::step]


def main(out_path):
    lens = closed_spline(lens_points(LENS_CX), Layer.LENS)
    outline = closed_spline(outline_points(lens), Layer.OUTLINE)
    # mirror_on=True doubles LENS across x=0 at export — same as the app
    # with the Ghost toggle on.
    export_dxf(curves=[outline, lens], path=str(out_path),
               mirror_on=True, axis_x=0.0, horizontal=False)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "demo_front.dxf"
    main(out)
