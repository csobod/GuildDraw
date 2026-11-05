"""
Pre-export validator — mirrors GuildModel's strict intake rules so the maker
catches problems in-app rather than at DXF import time.

Scene units are mm (1 scene unit = 1 mm), so all coordinates are used
directly without any px_per_mm conversion.

Each curve is traced once per validate() call (a straight line at its
vertices, anything else sampled), and cheap bounds tests come before every
costly comparison: the Ghost checks compared every pair of curves at 16
points a segment, and a dense drawing took seconds per edit (the 2.0 bug
hunt). The bounds are searched, not scanned: each rule still compared every
pair of curves or contours on a layer, and a large import froze the window
for seconds to minutes after every edit (2.0.1; see _Boxes).
"""
import contextvars
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon

from ..document import Curve, Layer, MACHINED_LAYERS


_CLOSURE_TOL_MM = 0.1   # GuildModel auto-closes within 0.1 mm
_STOCK_TOL_MM   = 0.05  # an OUTLINE this far past the stock guide is on it
_AREA_TOL_MM2   = 1e-3  # an overlap or an overrun smaller than this is touching
_HELD_TOL_MM    = 0.05  # a lens is held when its body, grown by this, contains it
_COPY_TOL_MM    = 0.05  # two curves this close everywhere lie one on the other
_TWIN_TOL_MM    = 2.0   # a drawn line this close to a Ghost twin stands for it
_MIN_HOLE_MM2   = 0.01  # GuildModel's least decorative opening

# The least area GuildModel reads a closed curve as, mm²; below it the curve
# is no lens, no pocket, no seat at all. Other layers take any area.
_MIN_AREA_MM2 = {Layer.LENS: 1.0, Layer.COMPONENT: 0.5, Layer.INLAY: 0.5}

# The layers the Ghost previews that GuildModel reads, per workspace. The
# Ghost is a drawing aid, and GuildModel reads only the curves drawn
# (2026-10-16), so a twin with no drawn counterpart is shown and never cut.
# DRILL ghosts too, but GuildModel reads no DRILL layer (the holes go to the
# OMA trace, which pairs them); a temple's SCULPT lines GuildModel does not
# read either (it partitions only a front). The OUTLINE's twin is a front's
# other separated rim.
_GHOST_CHECKED = {
    "front":     {Layer.LENS, Layer.COMPONENT, Layer.SCULPT, Layer.OUTLINE},
    "temple_r":  {Layer.COMPONENT},
    "temple_l":  {Layer.COMPONENT},
    "component": {Layer.COMPONENT},
}

# The traces of one validate() call, by curve id; each entry keeps its curve,
# so no id is reused while the call runs.
_TRACES: contextvars.ContextVar = contextvars.ContextVar("_TRACES", default=None)

# The rings of open pieces of one validate() call (_closed_chains), by the
# ids of the pieces asked about: the check per layer and the OUTLINE's
# contours ask for the OUTLINE's alike, two or three times a call.
_CHAINS: contextvars.ContextVar = contextvars.ContextVar("_CHAINS", default=None)


class _Trace:
    """One curve as drawn: its points, its bounds, and (lazily) its line and
    the area it encloses."""
    __slots__ = ("curve", "pts", "bounds", "_line", "_poly", "_poly_done")

    def __init__(self, curve: Curve, pts: list):
        self.curve = curve
        self.pts = pts
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            self.bounds = (min(xs), min(ys), max(xs), max(ys))
        else:
            self.bounds = None
        self._line = None
        self._poly = None
        self._poly_done = False

    @property
    def line(self):
        if self._line is None and len(self.pts) >= 2:
            self._line = LineString(self.pts)
        return self._line

    @property
    def poly(self):
        if not self._poly_done:
            self._poly = _ring_poly(self.pts)
            self._poly_done = True
        return self._poly


# How closely a trace follows its curve (mm): far finer than any rule here
# (the 0.1 mm closure, the 0.05 mm hold), and a dense imported spline is a
# few points a segment, not sixteen.
_TRACE_TOL_MM = 0.02


def _sample_pts(curve: Curve) -> list:
    """*curve*'s points as drawn: a straight line's vertices (and its first
    again when closed), anything else flattened to _TRACE_TOL_MM."""
    if curve.kind == "line":
        pts = [(n.x, n.y) for n in curve.nodes]
        return pts + pts[:1] if curve.closed and len(pts) > 1 else pts
    from ..geometry import flatten_curve
    return flatten_curve(curve, _TRACE_TOL_MM)


def _trace(curve: Curve) -> _Trace:
    cache = _TRACES.get()
    if cache is None:
        return _Trace(curve, _sample_pts(curve))
    t = cache.get(id(curve))
    if t is None:
        t = cache[id(curve)] = _Trace(curve, _sample_pts(curve))
    return t


def _pts(curve: Curve) -> list:
    return _trace(curve).pts


def _grown(bounds, by: float):
    return (bounds[0] - by, bounds[1] - by, bounds[2] + by, bounds[3] + by)


def _meet(a, b) -> bool:
    """True when two bounds overlap."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


# Below this many bounds a scan costs less than building a tree.
_TREE_MIN = 48


class _Boxes:
    """Bounds to search: which of them meet a box. Every rule compared each
    curve or contour with every other on its layer, and an import of 2000
    small closed curves onto OUTLINE froze the window for 21 s after every
    edit (2.0.1). An STRtree finds the few that can meet; a handful are
    scanned. Bounds that are None meet nothing, and ones that are not finite
    are always looked at, as the scan looked at them."""
    __slots__ = ("boxes", "tree", "where", "loose")

    def __init__(self, boxes: list):
        self.boxes = boxes
        self.tree = None
        if len(boxes) < _TREE_MIN:
            return
        where, self.loose = [], []
        for i, b in enumerate(boxes):
            if b is not None:
                (where if all(map(math.isfinite, b)) else self.loose).append(i)
        self.where = np.asarray(where, dtype=np.intp)
        b = np.asarray([boxes[i] for i in where], dtype=float).reshape(-1, 4)
        self.tree = shapely.STRtree(shapely.box(b[:, 0], b[:, 1], b[:, 2], b[:, 3]))

    def meeting(self, box) -> list:
        """The indices of the bounds that meet *box*, in order."""
        if self.tree is None or not all(map(math.isfinite, box)):
            hits = range(len(self.boxes))
        else:
            hits = self.where[self.tree.query(shapely.box(*box))].tolist()
            hits = sorted(hits + self.loose)
        return [i for i in hits
                if self.boxes[i] is not None and _meet(box, self.boxes[i])]


def _endpoint_gap_mm(curve: Curve) -> float:
    """Distance in mm between the ends of an open curve as drawn (an arc's
    from its angles; its single node is the center)."""
    ends = _curve_ends(curve)
    if ends is None:
        return 0.0
    (x0, y0), (x1, y1) = ends
    return math.hypot(x1 - x0, y1 - y0)


def _outline_bodies(polys: list, lenses: list = ()) -> tuple[list, list, list]:
    """The OUTLINE contours (polygons) sorted into ``(bodies, holes, strays)``,
    as GuildModel's ``normalize.assemble_outline`` sorts them.

    Of the contours inside no other, the largest is a body (the profile), and
    so is any that holds a lens (*lenses*, polygons): a separated rim of a
    combination frame, whose two rims are both drawn, the mirror baked (Road
    to 2.0, item 9). A contour inside a body is a decorative opening (Hole1…),
    cut through. Every other contour is a stray, which GuildModel ignores: one
    inside a stray was counted an opening here, and GuildModel never cut it.
    Degenerate contours never get here (see _area_polys).

    A contour is tested only against those whose bounds hold its point, with
    the areas and the points worked out once: each was tested against every
    other, its area recomputed each time (2.0.1, see _Boxes)."""
    areas = [p.area for p in polys]
    points = [p.representative_point() for p in polys]
    spots = [(pt.x, pt.y) * 2 for pt in points]       # each point as bounds
    boxes = _Boxes([p.bounds for p in polys])

    def inside_another(i: int) -> bool:
        p = polys[i]
        return any(polys[j] is not p and areas[j] > areas[i]
                   and polys[j].contains(points[i]) for j in boxes.meeting(spots[i]))

    tops = [i for i in range(len(polys)) if not inside_another(i)]
    if not tops:
        return [], [], list(polys)
    largest = polys[max(tops, key=areas.__getitem__)]
    lens_spots = [(lp, (lp.x, lp.y) * 2)
                  for lp in (lens.representative_point() for lens in lenses)]
    held = [i for i in tops if polys[i] is largest or any(
        _meet(boxes.boxes[i], s) and polys[i].contains(lp) for lp, s in lens_spots)]
    bodies = [polys[i] for i in held]
    holes, strays = [], []
    for i, p in enumerate(polys):
        if any(p is b for b in bodies):
            continue
        inside_body = any(_meet(boxes.boxes[k], spots[i])
                          and polys[k].contains(points[i]) for k in held)
        if inside_body and areas[i] >= _MIN_HOLE_MM2:
            holes.append(p)
        elif not inside_body:
            strays.append(p)
    return bodies, holes, strays


def _curve_ends(curve: Curve):
    """The first and last points of *curve* as drawn (an arc's from its
    angles, which its single node, the center, does not give)."""
    pts = _pts(curve)
    if not pts:
        return None
    return pts[0], pts[-1]


def _closed_chains(curves: list) -> list[list]:
    """Open curves that meet end to end, within the closure tolerance, into
    closed rings: a rim drawn as a spline and a straight line, say. Each ring
    is the list of its pieces (two or more), in order; a curve in no ring is
    left out.

    A walk starts at each piece in turn and steps on to the lowest-numbered
    piece with an end at its tip, until it comes back to its start or stops.
    Every piece started a walk, and each step measured the tip against every
    end: an outline exploded into 899 pieces with one deleted took 297 s a
    check, rerun after every edit (2.0.1). Now each end is measured once
    against the ends around it on a grid, and a piece no ring can pass
    through starts no walk and ends any walk that steps onto it (_bridges):
    every piece of an outline with a gap is one. The rings found are the
    same, in the same order."""
    cache = _CHAINS.get()
    key = tuple(map(id, curves))
    if cache is not None and key in cache:
        return cache[key]
    idx, pts = [], []           # piece k: curves[idx[k]], ends pts[2k], pts[2k + 1]
    for i, c in enumerate(curves):
        e = _curve_ends(c)
        if e is not None:
            idx.append(i)
            pts += e

    def near(a, b) -> bool:
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= _CLOSURE_TOL_MM

    # The ends within the tolerance of each end, in order: an end is an
    # even number for a piece's first, odd for its last, so a piece's first
    # comes before its last, as the walk tried them. In cells twice the
    # tolerance wide, every such end is in the 3 × 3 cells around.
    size = 2.0 * _CLOSURE_TOL_MM
    cells: dict = {}
    for e, (x, y) in enumerate(pts):
        if math.isfinite(x) and math.isfinite(y):   # a NaN or an inf meets nothing
            cells.setdefault((math.floor(x / size), math.floor(y / size)), []).append(e)
    meets: list = [()] * len(pts)
    for (cx, cy), here in cells.items():
        around = [f for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                  for f in cells.get((cx + dx, cy + dy), ())]
        for e in here:
            meets[e] = sorted(f for f in around if f != e and near(pts[e], pts[f]))

    # Ends that meet, directly or through others, are one place, and each
    # piece runs between two places; a ring runs place to place and back.
    place = list(range(len(pts)))

    def find(e: int) -> int:
        while place[e] != e:
            place[e] = place[place[e]]
            e = place[e]
        return e

    for e, fs in enumerate(meets):
        for f in fs:
            place[find(e)] = find(f)
    bridges = _bridges([(find(2 * k), find(2 * k + 1)) for k in range(len(idx))])

    used: set = set()
    chains = []
    for k in range(len(idx)):
        if k in used or k in bridges:
            continue
        start, tip = pts[2 * k], 2 * k + 1
        chain, walked = [k], {k}
        while not near(pts[tip], start):
            step = next((f for f in meets[tip]
                         if f >> 1 not in used and f >> 1 not in walked), None)
            if step is None or step >> 1 in bridges:
                break               # a dead end, or a bridge: no way back
            tip = step ^ 1          # on to the piece's other end
            chain.append(step >> 1)
            walked.add(step >> 1)
        if len(chain) >= 2 and near(pts[tip], start):
            used.update(chain)
            chains.append([curves[idx[j]] for j in chain])
    if cache is not None:
        cache[key] = chains
    return chains


def _bridges(edges: list) -> set:
    """The edges no cycle passes through (bridges), by index, of a graph
    given as *edges*, pairs of vertices; two edges may join the same pair,
    and an edge from a vertex to itself is a cycle of its own. A ring of
    pieces is a cycle of places, so a piece that is a bridge lies on none.
    Tarjan's bridge-finding, without recursion."""
    adj: dict = {}
    for k, (u, v) in enumerate(edges):
        adj.setdefault(u, []).append((v, k))
        adj.setdefault(v, []).append((u, k))
    order: dict = {}
    low: dict = {}
    out = set()
    for root in adj:
        if root in order:
            continue
        order[root] = low[root] = len(order)
        stack = [(root, -1, iter(adj[root]))]
        while stack:
            v, via, todo = stack[-1]
            for w, k in todo:
                if k == via:
                    continue        # the edge in, not a way back
                if w in order:
                    low[v] = min(low[v], order[w])
                else:
                    order[w] = low[w] = len(order)
                    stack.append((w, k, iter(adj[w])))
                    break
            else:
                stack.pop()
                if stack:
                    u = stack[-1][0]
                    low[u] = min(low[u], low[v])
                    if low[v] > order[u]:
                        out.add(via)
    return out


def _chain_points(chain: list) -> list:
    """One ring's points from its pieces, each turned to run on from the last."""
    out: list = []
    for c in chain:
        pts = list(_pts(c))
        if out and pts and (math.hypot(pts[-1][0] - out[-1][0], pts[-1][1] - out[-1][1])
                            < math.hypot(pts[0][0] - out[-1][0], pts[0][1] - out[-1][1])):
            pts.reverse()
        out.extend(pts)
    return out


def _outline_polys(curves: list) -> list:
    """Polygons for the OUTLINE: one per closed curve, and one per ring of
    pieces that meet end to end (see _closed_chains), so a rim drawn in
    pieces reads as the rim it is. A piece in no ring is read on its own, as
    _area_polys reads any curve."""
    chains = _closed_chains([c for c in curves if not c.closed])
    in_chain = {id(c) for chain in chains for c in chain}
    polys = _area_polys([c for c in curves if id(c) not in in_chain])
    for chain in chains:
        poly = _ring_poly(_chain_points(chain))
        if poly is not None:
            polys.append(poly)
    return polys


def _ring_poly(pts: list):
    """The area a ring of points encloses, as GuildModel reads it: a ring that
    crosses itself is repaired to the largest piece of what it encloses
    (``normalize.points_to_polygon``). None for fewer than three points or no
    area."""
    if len(pts) < 3:
        return None
    try:
        poly = Polygon(pts)
        if not poly.is_valid:
            fixed = shapely.make_valid(poly)
            parts = [g for g in getattr(fixed, "geoms", [fixed])
                     for g in getattr(g, "geoms", [g])
                     if g.geom_type == "Polygon" and g.area > 0]
            poly = max(parts, key=lambda g: g.area) if parts else None
    except Exception:
        return None
    return poly if poly is not None and poly.area > 0 else None


def _area_polys(curves: list) -> list:
    """Shapely polygons for the curves that enclose an area, in draw order.
    An invalid ring is repaired and the largest piece kept; degenerate curves
    (fewer than 3 sample points, or zero area) yield nothing, as GuildModel
    drops slivers too. _shape_checks reports both."""
    return [p for p in (_trace(c).poly for c in curves) if p is not None]


def _outline_bounds(outlines: list):
    """Bounding box ``(minx, miny, maxx, maxy)`` in mm of the sampled OUTLINE
    curves, or None when nothing samples."""
    boxes = [b for b in (_trace(c).bounds for c in outlines) if b is not None]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


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


def _inside(p, q) -> bool:
    return p.difference(q).area <= _AREA_TOL_MM2


def _crosses(p, q) -> bool:
    """Partial overlap: the two share area and neither holds the other."""
    return (p.intersection(q).area > _AREA_TOL_MM2
            and not _inside(p, q) and not _inside(q, p))


def _inlay_checks(drawn: list, errors: list) -> None:
    """INLAY (2.0): a closed seat for a plaque, a laminate or a plate, which
    GuildModel cuts to a depth and on a face it keeps per inlay. The drawing
    carries the geometry only, and these rules keep it cuttable: a seat meets
    the part, and where it runs off a body's edge it is a step open there, as
    a COMPONENT pocket is (a front-mounted bridge's seat, spanning the gap between
    separated rims; Road to 2.0, item 9); it never crosses a LENS aperture, a DRILL hole or a
    decorative opening (a closed OUTLINE curve inside the profile), all cut
    through; it never crosses a COMPONENT curve, though inside one it is a
    step in the component pocket's floor; and two inlays nest (a step) or
    stay apart,
    since a partial overlap has no cut order. Errors, since GuildModel cannot
    cut them as drawn. Only the curves drawn count: the Ghost is never cut.
    Areas share nothing where their bounds do not meet, so only those that
    meet are intersected: every seat was intersected with every other, and
    with every aperture (2.0.1, see _Boxes)."""
    inlays = [c for c in drawn if c.layer == Layer.INLAY]
    if not inlays:
        return

    def layer_polys(layer: Layer) -> list:
        return _area_polys([c for c in drawn if c.layer == layer])

    seats = _area_polys(inlays)
    lenses = layer_polys(Layer.LENS)
    bodies, holes, _strays = _outline_bodies(
        _outline_polys([c for c in drawn if c.layer == Layer.OUTLINE]), lenses)
    apertures = [("a LENS curve", p) for p in lenses]
    apertures += [("a DRILL curve", p) for p in layer_polys(Layer.DRILL)]
    apertures += [("a decorative opening (a closed OUTLINE curve inside "
                   "the profile)", p) for p in holes]
    components = layer_polys(Layer.COMPONENT)
    at_seats = _Boxes([p.bounds for p in seats])
    at_bodies = [(b, b.bounds) for b in bodies]
    at_cuts = _Boxes([cut.bounds for _what, cut in apertures])
    at_components = _Boxes([p.bounds for p in components])

    for i, seat in enumerate(seats, 1):
        box = at_seats.boxes[i - 1]
        if bodies and not any(_meet(box, bb)
                              and seat.intersection(b).area > _AREA_TOL_MM2
                              for b, bb in at_bodies):
            errors.append(
                f"INLAY {i} lies off the part; a seat cuts only where it meets "
                "an OUTLINE body.")
        for k in at_cuts.meeting(box):
            what, cut = apertures[k]
            if seat.intersection(cut).area > _AREA_TOL_MM2:
                errors.append(f"INLAY {i} crosses {what}.")
                break
        if any(_crosses(seat, components[k]) for k in at_components.meeting(box)):
            errors.append(
                f"INLAY {i} crosses a COMPONENT curve; draw it inside the "
                "component's outline for a step in the pocket's floor, or "
                "beside it.")
    for i in range(len(seats)):
        for j in at_seats.meeting(at_seats.boxes[i]):
            if j > i and _crosses(seats[i], seats[j]):
                errors.append(
                    f"INLAY {i + 1} and INLAY {j + 1} overlap without nesting; "
                    "nest one inside the other for a step, or move them apart.")


def _outline_layer_check(outlines: list, errors: list, warnings: list,
                         label: str, lenses: list = ()) -> tuple[list, list, list]:
    """Shared OUTLINE rule: at least one contour; extra contours are fine and
    classified as openings (inside a body), rims (holding a lens) or strays.
    Returns ``(bodies, holes, strays)``, for the checks that follow."""
    if not outlines:
        errors.append(f"{label} 1 OUTLINE contour, found 0.")
        return [], [], []
    bodies, holes, strays = _outline_bodies(_outline_polys(outlines), lenses)
    if holes:
        warnings.append(
            f"{len(holes)} closed OUTLINE curve(s) inside the profile — "
            "GuildModel cuts them as decorative openings (Hole1…)."
        )
    if strays:
        warnings.append(
            f"{len(strays)} OUTLINE curve(s) fall outside the profile — "
            "GuildModel ignores them; the largest curve is the profile."
        )
    return bodies, holes, strays


def _half_drawn(bodies: list, lens, others: list = ()) -> bool:
    """A lens with no partner in an outline drawn for two, GuildModel's
    ``regions.half_drawn_front``: the lens mirrored across the body's vertical
    center line lands inside the body, clear of the lens and of every other
    lens (*others*). A monocle's rim surrounds its lens, and the mirror image
    falls on the lens itself; a pair's mirror images fall on each other. Two
    lenses on one eye (a redrawn lens left behind) leave the other eye with
    none, and GuildModel cuts it solid (2.0.1)."""
    from shapely.affinity import scale
    if len(bodies) != 1:
        return False                      # separated rims: each holds its own lens
    x0, _y0, x1, _y1 = bodies[0].bounds
    twin = scale(lens, xfact=-1.0, yfact=1.0, origin=(0.5 * (x0 + x1), 0.0))
    if twin.intersection(lens).area > 0.5 * lens.area:
        return False
    if any(twin.intersection(o).area > 0.1 * lens.area for o in others):
        return False
    return twin.difference(bodies[0]).area < 0.1 * lens.area


def _lens_checks(bodies: list, holes: list, lenses: list, ghost_lens: bool,
                 errors: list, strays: list = ()) -> None:
    """A front's lenses against its bodies, as GuildModel's intake reads them
    (the 2.0 bug hunt): two lenses, or one for a monocle; a third is refused,
    not guessed at. One lens in an outline drawn for two is refused, since
    the other eye would be cut solid; *ghost_lens* says the Ghost check has
    already said so. A rim drawn without its lens is refused, whether it is
    a body or one of the *strays*. And a lens lies whole in a body and clear
    of its decorative openings (*holes*), since only a lens the frame holds
    is cut: GuildModel tests the body with its openings punched out."""
    if len(lenses) > 2:
        errors.append(
            f"A front holds two lenses, or one for a monocle; found "
            f"{len(lenses)}, and GuildModel cuts nothing until the extra ones "
            "are deleted.")
    if not bodies:
        return
    if len(lenses) == 1 and not ghost_lens and _half_drawn(bodies, lenses[0]):
        errors.append(
            "One lens in an outline drawn for two: GuildModel would cut the "
            "other eye solid. Draw the second lens, or Mirror (bake) this one.")
    elif len(lenses) == 2 and not ghost_lens and any(
            _half_drawn(bodies, lens, [o for o in lenses if o is not lens])
            for lens in lenses):
        errors.append(
            "Both lenses are on one eye: GuildModel would cut the other eye "
            "solid. Delete the extra lens, then draw the other eye's or Mirror "
            "(bake) it.")
    held = [b for b in bodies
            if any(b.contains(lens.representative_point()) for lens in lenses)]
    if held and len(lenses) <= 2 and not ghost_lens:
        # Separated rims: each holds its own lens. A rim drawn without one
        # was read green (2.0.1). It is a body when it is the larger of the
        # two, and a stray when the two tie and it comes second, so both are
        # counted: any contour as large as half a rim with a lens.
        least = min(b.area for b in held)
        empty = sum(1 for p in list(bodies) + list(strays)
                    if p.area >= 0.5 * least and not any(
                        p.contains(lens.representative_point()) for lens in lenses))
        if empty:
            errors.append(
                f"{empty} rim{'s hold' if empty > 1 else ' holds'} no lens: "
                "GuildModel would build the front without "
                f"{'them' if empty > 1 else 'it'}, or not at all. Draw the "
                "lens, or Mirror (bake) the other rim's.")
    from shapely.ops import unary_union
    held = unary_union(bodies).buffer(_HELD_TOL_MM)
    for i, lens in enumerate(lenses, 1):
        if not held.contains(lens):
            if any(b.intersection(lens).area > _AREA_TOL_MM2 for b in bodies):
                errors.append(
                    f"LENS {i} crosses the edge of its rim; GuildModel cuts a lens "
                    "only where the frame holds it whole.")
            else:
                errors.append(
                    f"LENS {i} lies outside every OUTLINE body; GuildModel cuts a "
                    "lens only inside the frame.")
        elif any(h.intersection(lens).area > _AREA_TOL_MM2 for h in holes):
            errors.append(
                f"LENS {i} overlaps a decorative opening (a closed OUTLINE curve "
                "inside the profile, an OUTLINE copy of the lens perhaps); "
                "GuildModel cuts a lens only where the frame holds it whole.")


def _is_area(curve: Curve) -> bool:
    return curve.closed or curve.kind == "circle"


def _mirror_pts(pts: list, horizontal: bool) -> list:
    """*pts* mirrored as the Ghost mirrors them: across x = 0, or a temple's
    y = 0."""
    if horizontal:
        return [(x, -y) for x, y in pts]
    return [(-x, y) for x, y in pts]


def _mirror_bounds(b, horizontal: bool):
    if horizontal:
        return (b[0], -b[3], b[2], -b[1])
    return (-b[2], b[1], -b[0], b[3])


def _beside_axis(bounds, horizontal: bool) -> bool:
    """True when the bounds lie to one side of the mirror axis (x = 0, or a
    temple's y = 0), clear of it by the closure tolerance: the scene's rule
    for a separated rim (``scene._rim_beside_axis``)."""
    lo, hi = (bounds[1], bounds[3]) if horizontal else (bounds[0], bounds[2])
    return hi < -_CLOSURE_TOL_MM or lo > _CLOSURE_TOL_MM


def _hull_beside_axis(curve: Curve) -> bool:
    """The scene's test for a closed OUTLINE it ghosts
    (``scene._rim_beside_axis``): its nodes and handles, or a circle's or an
    arc's disc, wholly to one side of x = 0, clear of it by the closure
    tolerance. The traced bounds disagreed when a handle reached past the
    axis and the curve did not: the canvas cast no ghost, and the validator
    asked for a twin to be baked (2.0.1)."""
    if curve.kind in ("circle", "arc") and curve.radius and curve.nodes:
        cx = curve.nodes[0].x
        xs = [cx - curve.radius, cx + curve.radius]
    else:
        xs = [n.x for n in curve.nodes]
        xs += [h.x for n in curve.nodes for h in (n.cp_in, n.cp_out)
               if h is not None]
    return bool(xs) and (max(xs) < -_CLOSURE_TOL_MM or min(xs) > _CLOSURE_TOL_MM)


def _same_area(a, b) -> bool:
    """True when two areas are one shape near enough: sizes within a factor
    of two, sharing more than a quarter of the smaller. The size test makes
    it mutual: the profile around a decorative opening's twin covers the
    twin, and stood for it."""
    small, big = sorted((a.area, b.area))
    return (big <= 2.0 * small
            and a.intersection(b).area > 0.25 * small)


def _stands_for(twin_pts: list, twin_poly, trace: _Trace) -> bool:
    """True when a drawn curve (*trace*) stands for a Ghost twin: two areas
    that are one shape near enough (_same_area), or two lines within
    _TWIN_TOL_MM of each other everywhere. Loose on purpose: a second lens
    drawn by hand is the maker's own, and GuildModel cuts it."""
    poly = trace.poly if twin_poly is not None else None
    if twin_poly is not None and poly is not None:
        return _same_area(twin_poly, poly)
    if len(twin_pts) < 2 or trace.line is None:
        return False
    twin = LineString(twin_pts)
    return (_all_within(twin_pts, trace.line, _TWIN_TOL_MM)
            and _all_within(trace.pts, twin, _TWIN_TOL_MM))


def _all_within(pts: list, line, tol: float) -> bool:
    """Whether every point of the polyline *pts* lies within *tol* of *line*,
    measured at most 600 places along it, never more than a fifth of *tol*
    apart (an exact Hausdorff distance between two dense traces took a
    second and a half per pair, and the fill paid it on every edit)."""
    a = np.asarray(pts, dtype=float)
    if len(a) == 0:
        return True
    steps = np.hypot(*np.diff(a, axis=0).T) if len(a) > 1 else np.zeros(0)
    length = float(steps.sum())
    n = int(min(600, max(len(a), math.ceil(length / (tol / 5.0)) + 1)))
    if n < len(a):
        idx = np.linspace(0, len(a) - 1, n).round().astype(int)
        probe = a[idx]
    elif n > len(a) and len(a) > 1:
        # Points along the runs too, so a long straight run is measured
        # between its ends, not only at them.
        s = np.concatenate([[0.0], np.cumsum(steps)])
        at = np.linspace(0.0, length, n)
        probe = np.column_stack([np.interp(at, s, a[:, 0]), np.interp(at, s, a[:, 1])])
    else:
        probe = a
    d = shapely.distance(shapely.points(probe), line)
    return bool(np.all(d <= tol))


def _ghost_checks(drawn: list, workspace_type: str, bodies: list, holes: list,
                  parts: list, errors: list) -> bool:
    """With the Ghost on, the canvas shows a twin of each curve on a ghosted
    layer, and GuildModel reads only the curves drawn. A twin no drawn curve
    stands for is shown and never cut: an error, with the fix. A curve whose
    twin lies on itself (a symmetric curve across the axis) is fine; one that
    only reaches the axis is not, since its twin is the other half. A twin of
    a LENS, COMPONENT or SCULPT curve that lands off every OUTLINE contour
    (*parts*: the bodies and the strays, since a second rim drawn without its
    lens is a stray) would cut nothing anyway, as a monocle's lens, so it is
    let be. A closed OUTLINE beside a front's axis is ghosted too: a body's
    twin is the other separated rim, previewed until it is baked, and a
    decorative opening's (*holes*) is the other opening, which the fill
    punches and GuildModel never cuts; a stray is neither. Returns True when
    a lens was reported, so the half-drawn rule does not say it again.

    Each twin is compared only with the curves within its reach, the
    openings and the parts its bounds meet: every twin was compared with
    every curve on its layer, and 1000 SCULPT lines took 1.4 s a check with
    the Ghost on (2.0.1, see _Boxes)."""
    from shapely.affinity import scale
    checked = _GHOST_CHECKED.get(workspace_type, set())
    horizontal = workspace_type in ("temple_r", "temple_l")
    by_layer: dict = {}
    for c in drawn:
        if c.layer in checked:
            by_layer.setdefault(c.layer, []).append(_trace(c))
    at_holes = _Boxes([h.bounds for h in holes]) if Layer.OUTLINE in by_layer else None
    at_parts = _Boxes([p.bounds for p in parts])

    lonely: dict[Layer, int] = {}
    for layer, traces in by_layer.items():
        at_traces = _Boxes([d.bounds for d in traces])
        for t in traces:
            c = t.curve
            if t.bounds is None or len(t.pts) < 2:
                continue
            kind = layer
            if layer == Layer.OUTLINE:
                # The scene ghosts a closed OUTLINE beside a front's axis: a
                # rim, or an opening; a stray is no part of the frame. A rim
                # drawn open with its ends within the closure tolerance is
                # closed as GuildModel reads it, and the canvas ghosts it as
                # well: skipped here, it was green with one rim in the file.
                closed = c.closed or _endpoint_gap_mm(c) <= _CLOSURE_TOL_MM
                if horizontal or not closed:
                    continue
                # A closed one by the scene's own test, so this never asks to
                # bake a twin the canvas does not show; an open one the scene
                # ghosts whatever it is, and it is read as traced.
                if not (_hull_beside_axis(c) if c.closed
                        else _beside_axis(t.bounds, False)):
                    continue

                def same(p, poly=t.poly):
                    return (abs(p.area - poly.area) < 1e-6
                            and p.contains(poly.representative_point()))
                if t.poly is None:
                    continue
                spot = t.poly.representative_point()
                if any(same(b) for b in bodies):
                    kind = "rim"
                elif any(same(holes[k])
                         for k in at_holes.meeting((spot.x, spot.y) * 2)):
                    kind = "opening"
                else:
                    continue
            twin_pts = _mirror_pts(t.pts, horizontal)
            twin_poly = None
            if _is_area(c) and t.poly is not None:
                twin_poly = (scale(t.poly, 1.0, -1.0, origin=(0, 0)) if horizontal
                             else scale(t.poly, -1.0, 1.0, origin=(0, 0)))
            twin_bounds = _mirror_bounds(t.bounds, horizontal)
            reach = _grown(twin_bounds, _TWIN_TOL_MM)
            if any(_stands_for(twin_pts, twin_poly, traces[k])
                   for k in at_traces.meeting(reach)):
                continue                  # drawn already (itself, when symmetric)
            if layer != Layer.OUTLINE and parts:
                where = twin_poly if twin_poly is not None else LineString(twin_pts)
                if not any(parts[k].intersects(where)
                           for k in at_parts.meeting(twin_bounds)):
                    continue
            lonely[kind] = lonely.get(kind, 0) + 1

    if lonely.get("rim"):
        errors.append(
            "The other rim is the Ghost's only, and GuildModel reads only the "
            "curves drawn: select the rim and its lens and Mirror (bake) them, "
            "or turn the Ghost off for a monocle.")
    n = lonely.get("opening", 0)
    if n:
        errors.append(
            f"{n} decorative opening{'s have' if n > 1 else ' has'} a twin that "
            "is the Ghost's only, and GuildModel reads only the curves drawn: "
            f"Mirror (bake) {'them' if n > 1 else 'it'}, or turn the Ghost off.")
    n = lonely.get(Layer.LENS, 0)
    if n:
        errors.append(
            "The other lens is the Ghost's only, and GuildModel reads only the "
            "curves drawn: select the lens and Mirror (bake) it, or turn the "
            "Ghost off for a monocle." if n == 1 else
            f"{n} lenses have a twin that is the Ghost's only, and GuildModel "
            "reads only the curves drawn: select them and Mirror (bake) them, "
            "or turn the Ghost off.")
    for layer in (Layer.COMPONENT, Layer.SCULPT):
        n = lonely.get(layer, 0)
        if n:
            errors.append(
                f"{n} {layer.value} curve{'s have' if n > 1 else ' has'} a twin "
                "that is the Ghost's only, and GuildModel reads only the curves "
                f"drawn: Mirror (bake) {'them' if n > 1 else 'it'}, or turn the "
                "Ghost off.")
    return bool(lonely.get(Layer.LENS))


def _traces_coincide(a: _Trace, b_pts: list, b_bounds) -> bool:
    """True when a trace and a point list lie one on the other, within
    _COPY_TOL_MM everywhere: a copy, whichever way it runs. Its imports were
    made at each call, which PySide's import hook made a cost of its own
    over the half million pairs of a dense layer (2.0.1)."""
    p, q = a.bounds, b_bounds
    if p is None or q is None or len(b_pts) < 2 or a.line is None:
        return False
    return (max(abs(p[k] - q[k]) for k in range(4)) <= _COPY_TOL_MM
            and shapely.hausdorff_distance(a.line, LineString(b_pts), densify=0.25)
            <= _COPY_TOL_MM)


def bake_skips(curve: Curve, twin: Curve, others: list,
               horizontal: bool = False, cache: dict | None = None) -> str | None:
    """Why Mirror (bake) should not add *twin*, *curve*'s mirror image, or
    None when it should: "overlaps itself" for a closed curve whose twin
    covers it (a whole outline baked over itself read as separated rims),
    "on itself" for a curve whose twin lies on it (a symmetric line across
    the axis), "drawn already" for a twin lying on one of *others* (curves
    drawn, or baked in the same step). A half reaching the axis is baked,
    for the Join that follows. *cache* keeps the traces between calls of one
    bake (a dict, by curve id)."""
    token = _TRACES.set(cache if cache is not None else {})
    try:
        own = _trace(curve)
        tw = _trace(twin)
        if tw.bounds is None:
            return None
        if (_is_area(curve) and own.poly is not None and tw.poly is not None
                and _same_area(own.poly, tw.poly)):
            return "overlaps itself"
        if _traces_coincide(own, tw.pts, tw.bounds):
            return "on itself"
        for o in others:
            if o.layer != twin.layer:
                continue
            t = _trace(o)
            if t.bounds is not None and _meet(_grown(tw.bounds, _COPY_TOL_MM), t.bounds) \
                    and _traces_coincide(t, tw.pts, tw.bounds):
                return "drawn already"
        return None
    finally:
        _TRACES.reset(token)


def _copy_checks(drawn: list, errors: list) -> None:
    """Two drawn curves of one layer that lie one on the other (a Mirror
    baked over a curve already there, a paste in place). GuildModel reads
    each: two OUTLINEs read as separated rims, two pockets cut twice.

    A copy's bounds lie within _COPY_TOL_MM of the curve's, so its center
    does too, and the curves seen are kept by their centers on a grid of
    cells twice that wide: each curve is compared with those in the 3 × 3
    cells around its own. Every pair was compared, and 1000 SCULPT lines
    took 1.3 s a check (2.0.1)."""
    layers = MACHINED_LAYERS | {Layer.SCULPT}
    size = 2.0 * _COPY_TOL_MM
    seen: dict[Layer, list] = {}        # every curve kept, by layer
    cells: dict[Layer, dict] = {}       # the same, by the cell of its center
    loose: dict[Layer, list] = {}       # those with bounds not finite
    copies: dict[Layer, int] = {}
    for c in drawn:
        if c.layer not in layers:
            continue
        t = _trace(c)
        if t.line is None:
            continue
        kept = seen.setdefault(c.layer, [])
        grid = cells.setdefault(c.layer, {})
        odd = loose.setdefault(c.layer, [])
        x0, y0, x1, y1 = t.bounds
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        if math.isfinite(cx) and math.isfinite(cy):
            cell = (math.floor(cx / size), math.floor(cy / size))
            near = [o for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    for o in grid.get((cell[0] + dx, cell[1] + dy), ())] + odd
        else:
            cell, near = None, kept
        if any(_traces_coincide(other, t.pts, t.bounds) for other in near):
            copies[c.layer] = copies.get(c.layer, 0) + 1
        else:
            kept.append(t)
            if cell is None:
                odd.append(t)
            else:
                grid.setdefault(cell, []).append(t)
    for layer, n in copies.items():
        errors.append(
            f"{n} {layer.value} curve{'s lie' if n > 1 else ' lies'} on top of "
            f"another {layer.value} curve, and GuildModel reads each: delete "
            f"the cop{'ies' if n > 1 else 'y'}.")


def _shape_checks(drawn: list, errors: list) -> None:
    """Curves GuildModel cannot read as drawn. A curve the file describes
    wrongly (one node, a circle or an arc with no radius, an arc with no
    angles) is skipped there; a closed curve that crosses itself is repaired
    to the largest piece of what it encloses; one that encloses no area is
    dropped, and a lens, a pocket or a seat under GuildModel's least area
    with it."""
    layers = MACHINED_LAYERS | {Layer.SCULPT}
    for c in drawn:
        if c.layer not in layers:
            continue
        name = c.layer.value
        if c.kind in ("circle", "arc"):
            if not c.nodes or not c.radius or c.radius <= 0:
                errors.append(f"A {name} {c.kind} has no radius, and GuildModel "
                              "skips it: delete it or redraw it.")
                continue
            if c.kind == "arc" and (c.start_angle is None or c.end_angle is None):
                errors.append(f"A {name} arc has no angles, and GuildModel skips "
                              "it: delete it or redraw it.")
                continue
        elif len(c.nodes) < 2:
            errors.append(f"A {name} curve has a single node and draws nothing: "
                          "delete it.")
            continue
        if not _is_area(c) and _endpoint_gap_mm(c) > _CLOSURE_TOL_MM:
            continue                  # an open curve; the closure rule reports it
        if c.layer == Layer.SCULPT and not c.closed:
            continue                  # a scallop line, read as a line
        t = _trace(c)
        try:
            raw = Polygon(t.pts) if len(t.pts) >= 3 else None
        except Exception:
            raw = None
        poly = t.poly
        least = _MIN_AREA_MM2.get(c.layer, _AREA_TOL_MM2)
        if poly is None or poly.area < least:
            errors.append(f"A {name} curve encloses no area, and GuildModel "
                          "drops it: delete it or redraw it.")
        elif raw is not None and not raw.is_valid:
            errors.append(f"A {name} curve crosses itself, and GuildModel keeps "
                          "only the largest piece of what it encloses: untangle "
                          "it.")


def validate(
    curves:    list,   # the drawn Curve objects
    mirror_on: bool,
    workspace_type: str = "front",
    stock_mm=None,     # (width, height) of the stock guide in mm, or None
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings).  Errors mean "not GuildModel-ready" and drive
    the readiness dot, but they no longer block DXF export — the maker decides
    when geometry is complete and GuildModel's intake is the final gate.

    Only the curves drawn are validated, the curves the .gdraw and the DXF
    carry: GuildModel never applies the Ghost (2026-10-16), so a monocle can
    be made. With the Ghost on (*mirror_on*), a twin the canvas shows that no
    drawn curve stands for is an error (_ghost_checks).

    ``stock_mm`` is the workspace's stock guide, centered on the origin like
    GuildModel's blank; an OUTLINE that leaves it is warned about with the
    overrun. A temple drawn off the core line (y = 0) is warned about whether
    or not a guide is given.

    Layer-count rules depend on the workspace:
      front    — OUTLINE ≥1 (the largest contour is the profile; closed curves
                 inside it are decorative openings Hole1… — an aviator's bridge
                 keyhole — and ones outside it are strays, both warned about
                 the way GuildModel's intake does), LENS 1 or 2 (two for a
                 pair, one for a monocle whose outline is one rim), each held
                 whole by a body and clear of its openings
      temple_* — OUTLINE ≥1 (same profile/opening rule — cut-out temples),
                 no LENS allowed
      component — COMPONENT ≥1, no OUTLINE/LENS allowed
    """
    token = _TRACES.set({})
    rings = _CHAINS.set({})
    try:
        return _validate(curves, mirror_on, workspace_type, stock_mm)
    finally:
        _CHAINS.reset(rings)
        _TRACES.reset(token)


def _validate(curves, mirror_on, workspace_type, stock_mm):
    errors:   list[str] = []
    warnings: list[str] = []

    drawn: list[Curve] = [c for c in curves if not c.mirrored]

    by_layer: dict[Layer, int] = {l: 0 for l in Layer}
    for c in drawn:
        by_layer[c.layer] += 1

    # A contour drawn in pieces that meet end to end is one contour, but
    # GuildModel reads each piece alone: say so once, with the fix, instead of
    # a gap per piece. First, as it is the first fix: a rim is joined
    # before its mirror is baked, or the bake copies the pieces too.
    pieces: set = set()
    for layer in MACHINED_LAYERS:
        open_drawn = [c for c in drawn if c.layer == layer and not c.closed]
        for chain in _closed_chains(open_drawn):
            pieces.update(id(c) for c in chain)
            errors.append(
                f"{layer.value} contour is drawn in {len(chain)} pieces that "
                "meet end to end, and GuildModel reads each piece alone: "
                "select them and Join them into one closed curve.")

    _shape_checks([c for c in drawn if id(c) not in pieces], errors)
    _copy_checks(drawn, errors)

    outlines = [c for c in drawn if c.layer == Layer.OUTLINE]
    if workspace_type == "front":
        lenses = [p for p in _area_polys(
                      [c for c in drawn if c.layer == Layer.LENS])
                  if p.area >= _MIN_AREA_MM2[Layer.LENS]]
        bodies, holes, strays = _outline_layer_check(
            outlines, errors, warnings, "Need at least", lenses)
        if not lenses:
            errors.append(f"Need at least 1 LENS contour, found {len(lenses)}.")
        ghost_lens = (_ghost_checks(drawn, workspace_type, bodies, holes,
                                    bodies + strays, errors) if mirror_on else False)
        _lens_checks(bodies, holes, lenses, ghost_lens, errors, strays)
        _origin_checks(outlines, workspace_type, stock_mm, warnings)
        _inlay_checks(drawn, errors)
    elif workspace_type in ("temple_r", "temple_l"):
        bodies, holes, strays = _outline_layer_check(
            outlines, errors, warnings, "Temple needs at least")
        if by_layer[Layer.LENS]:
            errors.append(
                f"LENS does not belong in a temple workspace "
                f"(found {by_layer[Layer.LENS]})."
            )
        if mirror_on:
            _ghost_checks(drawn, workspace_type, bodies, holes, bodies + strays,
                          errors)
        _origin_checks(outlines, workspace_type, stock_mm, warnings)
        _inlay_checks(drawn, errors)
    elif workspace_type == "component":
        if by_layer[Layer.COMPONENT] < 1:
            errors.append("A component needs at least 1 COMPONENT contour.")
        for bad in (Layer.OUTLINE, Layer.LENS):
            if by_layer[bad]:
                errors.append(
                    f"{bad.value} does not belong in the component workspace "
                    f"(found {by_layer[bad]})."
                )
        # The tab's Ghost previews a half's twin, and the library would get
        # the half: the same check as on a part.
        if mirror_on:
            _ghost_checks(drawn, workspace_type, [], [], [], errors)

    for c in drawn:
        if c.layer not in MACHINED_LAYERS or id(c) in pieces or _is_area(c):
            continue
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


def ghost_twins(drawn: list, candidates: list, axis_x: float = 0.0,
                horizontal: bool = False) -> list:
    """The Ghost's twins of *candidates* that no curve of *drawn* stands for
    (a curve's own twin included, when it lies on itself): what the Ghost
    adds to a drawing, for the prints and the OMA trace. A twin a drawn
    curve stands for printed a second line beside it, and a drawn pair of
    lenses read as four in the trace. The caller passes the candidates the
    canvas ghosts (``FrameScene.ghost_eligible``)."""
    from ..geometry import mirror_curve
    token = _TRACES.set({})
    try:
        by_layer: dict = {}
        for d in drawn:
            by_layer.setdefault(d.layer, []).append(_trace(d))
        # The drawn curves a twin can meet, found by their bounds (_Boxes):
        # every twin was tried against every drawn curve of its layer, and
        # an outline of 20 000 pieces with the Ghost and the Frame Fill on
        # took 21 s to reopen and as long after each edit (the 2.3 sweep).
        at = {layer: _Boxes([d.bounds for d in ds]) for layer, ds in by_layer.items()}
        out = []
        for c in candidates:
            twin = mirror_curve(c, axis_x, horizontal=horizontal)
            t = _trace(twin)
            if t.bounds is None:
                continue
            twin_poly = t.poly if _is_area(c) else None
            reach = _grown(t.bounds, _TWIN_TOL_MM)
            ds = by_layer.get(c.layer, [])
            if any(_stands_for(t.pts, twin_poly, ds[i])
                   for i in (at[c.layer].meeting(reach) if ds else ())):
                continue
            out.append(twin)
        return out
    finally:
        _TRACES.reset(token)
