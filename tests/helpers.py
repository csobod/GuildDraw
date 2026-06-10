"""Shared builders for GuildDraw tests."""
from framedraft.document import Curve, SplineNode, ControlPoint, Layer


def line(pts, closed=False, layer=Layer.REF):
    return Curve(kind="line", layer=layer,
                 nodes=[SplineNode(x=x, y=y) for x, y in pts], closed=closed)


def spline(pts, closed=False, layer=Layer.OUTLINE):
    """Spline through pts with centripetal Catmull-Rom handles
    (same formula as tools.draw.compute_catmull_handles, Qt-free)."""
    nodes = [SplineNode(x=x, y=y) for x, y in pts]
    n = len(nodes)

    def p(i):
        return nodes[i % n] if closed else nodes[max(0, min(i, n - 1))]

    for i, node in enumerate(nodes):
        prev, nxt = p(i - 1), p(i + 1)
        tx = (nxt.x - prev.x) / 6
        ty = (nxt.y - prev.y) / 6
        node.cp_out = ControlPoint(node.x + tx, node.y + ty)
        node.cp_in  = ControlPoint(node.x - tx, node.y - ty)
    return Curve(kind="spline", layer=layer, nodes=nodes, closed=closed)


def circle(cx, cy, r, layer=Layer.LENS):
    return Curve(kind="circle", layer=layer, nodes=[SplineNode(x=cx, y=cy)],
                 closed=True, radius=r)


def arc(cx, cy, r, start, end, layer=Layer.REF):
    return Curve(kind="arc", layer=layer, nodes=[SplineNode(x=cx, y=cy)],
                 closed=False, radius=r, start_angle=start, end_angle=end)


def closed_diamond(cx=0.0, cy=0.0, r=20.0, layer=Layer.OUTLINE):
    """A closed 4-node spline roughly the shape of a lens."""
    return spline([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                  closed=True, layer=layer)
