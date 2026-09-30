import math
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPen, QColor, QPainterPath

from .. import theme
from ..geometry import sample_curve, curve_intersections

_SNAP_RADIUS_PX = 10   # default screen-pixel snap radius (view space)
_INDICATOR_R    = 6    # screen-pixel indicator radius (view space)

# Snap-type registry — drives the engine's gating AND the snap palette UI.
# (key, palette label, tooltip). Keys are also theme tokens (snap.<key>).
SNAP_TYPES: list[tuple[str, str, str]] = [
    ("endpoint",      "Endpoint",      "Open-curve ends and arc endpoints"),
    ("node",          "Node",          "Interior and closed-curve nodes"),
    ("midpoint",      "Midpoint",      "Line-segment midpoints"),
    ("center",        "Center",        "Circle and arc centers"),
    ("quadrant",      "Quadrant",      "Circle/arc 0°/90°/180°/270° points"),
    ("intersection",  "Intersection",  "Where two curves cross"),
    ("tangent",       "Tangent",       "Tangent to a circle/arc from the point being drawn"),
    ("perpendicular", "Perpendicular", "Perpendicular to a line/curve from the point being drawn"),
    ("handle",        "Handle",        "Bézier control-point handles"),
    ("curve",         "On-curve",      "Nearest point along a curve"),
    ("grid",          "Grid",          "Nearest grid intersection (in empty space)"),
    ("mirror",        "Mirror axis",   "Project onto the mirror axis"),
    ("axis",          "Origin",        "The scene origin (0, 0)"),
]

SNAP_TYPE_KEYS = [k for k, _l, _t in SNAP_TYPES]

# Context snaps only produce a target relative to the point currently being
# drawn (the last placed node); they do nothing outside a line/spline draw.
CONTEXT_SNAP_KEYS = ("tangent", "perpendicular")


def _angle_in_arc(angle_deg: float, start_deg: float, end_deg: float) -> bool:
    """True if angle_deg is covered by the arc sweeping from start_deg to end_deg
    in the positive (CW-on-screen) direction."""
    sweep = (end_deg - start_deg) % 360
    if sweep < 0.001:
        sweep = 360.0     # equal angles draw a full circle (build_path agrees)
    return ((angle_deg - start_deg) % 360) <= sweep


class SnapEngine:
    """
    Finds the nearest snap target within the snap radius (screen px) of the
    cursor and shows a colored indicator dot.

    Each target carries a type from SNAP_TYPES; the palette toggles types on
    and off per user preference (set_enabled_types), the master toggle
    (set_enabled) and Ctrl-suspend still silence everything at once.

    Point-target priority is purely nearest-wins among enabled types;
    the mirror-axis projection, on-curve and grid are fallbacks when no
    point target hits (a projection is a zero-distance hit and would
    otherwise steal an endpoint sitting on the axis, leaving a gap the
    perimeter can't close), and the origin overrides everything inside
    its radius.
    """

    def __init__(self, scene):
        self._scene = scene
        self._doc_curves: list = []
        self._mirror_x:   float | None = None
        self._mirror_on:  bool = False
        self._mirror_horizontal: bool = False
        self._enabled:    bool = True
        self._indicator         = None
        self._indicator_key     = None   # (type, color) the indicator was built for
        self._radius_px: float  = _SNAP_RADIUS_PX
        self._grid_spacing: float = 0.0   # mm; 0 disables grid snap
        self._enabled_types: set[str] = set(SNAP_TYPE_KEYS)
        # Intersection cache: (id(a), id(b)) -> [(x, y), ...]; wholesale-
        # invalidated whenever the scene's geometry revision moves (ids are
        # stable between revisions because add/remove bumps the revision).
        self._isect_cache: dict = {}
        self._isect_rev: int = -1
        # Per-curve control extents, id(curve) -> (curve, extent), dropped on
        # the same revision bump. Holding the curve keeps its id from being
        # reused by a new curve while the entry lives.
        self._extent_cache: dict = {}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_doc_curves(self, curves: list):
        self._doc_curves = curves

    def set_mirror(self, axis: float, enabled: bool, horizontal: bool = False):
        self._mirror_x          = axis
        self._mirror_on         = enabled
        self._mirror_horizontal = horizontal

    def set_enabled(self, on: bool):
        self._enabled = on
        if not on:
            self._hide()

    def set_radius_px(self, px: float):
        self._radius_px = max(2.0, float(px))

    def set_grid_spacing(self, mm: float):
        """Grid-snap cell size (mm); should match the viewport grid overlay."""
        self._grid_spacing = max(0.0, float(mm))

    def set_enabled_types(self, types):
        """types: {key: bool} mapping or iterable of enabled keys."""
        if isinstance(types, dict):
            self._enabled_types = {k for k, on in types.items() if on}
        else:
            self._enabled_types = set(types)

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def snap(
        self,
        scene_pos:     QPointF,
        drawing_nodes: list,
        view,
        use_snap:      bool = True,
    ) -> QPointF:
        """Return the snapped position (or scene_pos if nothing nearby)."""
        if not self._enabled or not use_snap:
            self._hide()
            return scene_pos

        best      = scene_pos
        best_dist = float("inf")
        best_type: str | None = None
        enabled   = self._enabled_types
        radius    = self._radius_px
        self._sync_revision()

        # Read the view transform once per call. Every candidate used to
        # re-read it and map two points through it, which was most of the
        # 15–30 ms a mouse move cost over a few dense imported outlines. The
        # translation cancels in a difference, so the linear part alone gives
        # the same screen distance _px_dist does.
        xf = view.transform()
        m11, m12, m21, m22 = xf.m11(), xf.m12(), xf.m21(), xf.m22()
        sx, sy = scene_pos.x(), scene_pos.y()
        # The snap radius in mm, taken at the transform's weakest stretch (and
        # a hair over, so rounding never drops a target on the rim).
        r_mm = radius / max(_min_stretch(m11, m12, m21, m22), 1e-9) * (1.0 + 1e-9)

        def far(curve) -> bool:
            """True when nothing on *curve* can lie within the radius. Every
            node, handle, midpoint and on-curve foot sits inside the control
            extent (the center's, padded by the radius, for circles/arcs), so
            a cursor that far from that box skips the vertex walk."""
            (x0, x1), (y0, y1) = self._extent(curve)
            pad = r_mm + (curve.radius or 0.0)
            return sx < x0 - pad or sx > x1 + pad or sy < y0 - pad or sy > y1 + pad

        def candidate_xy(x: float, y: float, t: str):
            # Plain floats: the vertex walk below offers thousands of points
            # per move on a dense import, and only a winner needs a QPointF.
            nonlocal best, best_dist, best_type
            if t not in enabled:
                return
            dx, dy = x - sx, y - sy
            d = math.hypot(m11 * dx + m21 * dy, m12 * dx + m22 * dy)
            if d < radius and d < best_dist:
                best_dist = d
                best      = QPointF(x, y)
                best_type = t

        def candidate(target: QPointF, t: str):
            candidate_xy(target.x(), target.y(), t)

        is_visible = getattr(self._scene, "is_layer_visible", None)
        for curve in self._doc_curves:
            # Hidden layers offer no snap targets (locked layers still do —
            # locked geometry remains a positioning reference).
            if is_visible is not None and not is_visible(curve.layer):
                continue
            if curve.kind in ("circle", "arc") and curve.radius and curve.nodes:
                cx, cy, r = curve.nodes[0].x, curve.nodes[0].y, curve.radius
                candidate(QPointF(cx, cy), "center")
                # Four cardinal quadrant points
                quadrants = ((0, cx + r, cy), (90, cx, cy + r),
                             (180, cx - r, cy), (270, cx, cy - r))
                sa, ea = curve.start_angle, curve.end_angle
                for q_deg, qx, qy in quadrants:
                    if curve.kind == "circle":
                        candidate(QPointF(qx, qy), "quadrant")
                    elif sa is not None and ea is not None:
                        if _angle_in_arc(q_deg, sa, ea):
                            candidate(QPointF(qx, qy), "quadrant")
                # Arc endpoints
                if curve.kind == "arc" and sa is not None and ea is not None:
                    sa_r, ea_r = math.radians(sa), math.radians(ea)
                    candidate(QPointF(cx + r * math.cos(sa_r), cy + r * math.sin(sa_r)), "endpoint")
                    candidate(QPointF(cx + r * math.cos(ea_r), cy + r * math.sin(ea_r)), "endpoint")
            else:
                if not curve.nodes or far(curve):
                    continue
                last = len(curve.nodes) - 1
                for i, node in enumerate(curve.nodes):
                    tag = ("endpoint" if not curve.closed and i in (0, last)
                           else "node")
                    candidate_xy(node.x, node.y, tag)
                    for cp in (node.cp_in, node.cp_out):
                        if cp is not None:
                            candidate_xy(cp.x, cp.y, "handle")
                # Midpoints of line segments
                if curve.kind == "line":
                    nodes = curve.nodes
                    n = len(nodes)
                    count = n if curve.closed else n - 1
                    for i in range(count):
                        j = (i + 1) % n
                        candidate_xy((nodes[i].x + nodes[j].x) / 2,
                                     (nodes[i].y + nodes[j].y) / 2,
                                     "midpoint")

        for node in drawing_nodes:
            candidate(QPointF(node.x, node.y), "node")

        if "intersection" in enabled:
            self._intersection_candidates(scene_pos, view, candidate, is_visible)

        # Context snaps: tangent / perpendicular are measured FROM the point
        # being drawn (the last placed node), so they only exist mid-draw.
        anchor = drawing_nodes[-1] if drawing_nodes else None
        if anchor is not None:
            want_t = "tangent" in enabled
            want_p = "perpendicular" in enabled
            if want_t or want_p:
                self._context_candidates(anchor.x, anchor.y, candidate,
                                         is_visible, want_t, want_p, far)

        # Mirror-axis projection — a line target, so only when no point
        # target claimed the cursor (see the class docstring).
        if best_type is None and self._mirror_on and self._mirror_x is not None:
            if self._mirror_horizontal:
                candidate(QPointF(scene_pos.x(), self._mirror_x), "mirror")
            else:
                candidate(QPointF(self._mirror_x, scene_pos.y()), "mirror")

        # On-curve snap (nearest point anywhere along a curve) — LOWEST
        # priority: only when no point target was found, because every node
        # lies on its curve and would otherwise be shadowed. Needed for
        # drawing OUTLINE→LENS connectors (scallop / extrusion work).
        if best_type is None and "curve" in enabled:
            on_curve = self._nearest_on_curve(scene_pos, view, is_visible)
            if on_curve is not None:
                best, best_type = on_curve, "curve"

        # Grid snap — the nearest grid intersection, but only as a fallback in
        # empty space (object snaps above always win) so it's a coarse-position
        # aid, not a cursor jail.
        if best_type is None and "grid" in enabled and self._grid_spacing > 0:
            sp = self._grid_spacing
            gx = round(scene_pos.x() / sp) * sp
            gy = round(scene_pos.y() / sp) * sp
            gpt = QPointF(gx, gy)
            if _px_dist(view, scene_pos, gpt) < self._radius_px:
                best, best_type = gpt, "grid"

        # Origin snap — single point (0, 0).
        # Checked after all other candidates so it can override them: the mirror
        # snap projects the cursor onto x=0 with zero distance, which would always
        # beat a point-snap via the normal < comparison.
        if "axis" in enabled:
            _d_orig = _px_dist(view, scene_pos, QPointF(0.0, 0.0))
            if _d_orig < self._radius_px:
                best      = QPointF(0.0, 0.0)
                best_type = "axis"

        if best_type:
            self._show(best, best_type)
        else:
            self._hide()

        return best

    def _nearest_on_curve(self, scene_pos: QPointF, view,
                          is_visible) -> QPointF | None:
        """Nearest sampled point on any visible curve within the snap radius."""
        scale = max(abs(view.transform().m11()), 1e-6)
        r_mm  = self._radius_px / scale
        px, py = scene_pos.x(), scene_pos.y()
        best = None
        best_d = r_mm
        for curve in self._doc_curves:
            if not curve.nodes:
                continue
            if is_visible is not None and not is_visible(curve.layer):
                continue
            # Cheap bbox reject before sampling (the control polygon bounds
            # the curve, so handles must be in the box)
            xs, ys = self._extent(curve)
            pad = (curve.radius or 0.0) + best_d + 1.0
            if not (xs[0] - pad <= px <= xs[1] + pad
                    and ys[0] - pad <= py <= ys[1] + pad):
                continue
            for x, y, _t in sample_curve(curve, 24):
                d = math.hypot(x - px, y - py)
                if d < best_d:
                    best_d = d
                    best = (x, y)
        return QPointF(*best) if best is not None else None

    def _intersection_candidates(self, scene_pos: QPointF, view,
                                 candidate, is_visible) -> None:
        """Feed cached curve-pair intersection points near the cursor."""
        self._sync_revision()
        scale = max(abs(view.transform().m11()), 1e-6)
        r_mm  = self._radius_px / scale
        px, py = scene_pos.x(), scene_pos.y()

        near: list = []
        for curve in self._doc_curves:
            if not curve.nodes:
                continue
            if is_visible is not None and not is_visible(curve.layer):
                continue
            xs, ys = self._extent(curve)
            pad = (curve.radius or 0.0) + r_mm + 1.0
            if (xs[0] - pad <= px <= xs[1] + pad
                    and ys[0] - pad <= py <= ys[1] + pad):
                near.append(curve)
        if len(near) < 2:
            return

        for i, a in enumerate(near):
            for b in near[i + 1:]:
                key = (id(a), id(b))
                pts = self._isect_cache.get(key)
                if pts is None:
                    pts = curve_intersections(a, b)
                    self._isect_cache[key] = pts
                for x, y in pts:
                    candidate(QPointF(x, y), "intersection")

    def _context_candidates(self, ax: float, ay: float, candidate,
                            is_visible, want_tangent: bool,
                            want_perp: bool, far=None) -> None:
        """Tangent + perpendicular targets measured from the anchor (ax, ay) —
        the point currently being drawn. candidate() still filters by nearness
        to the cursor, so the maker steers toward the target they want; *far*
        skips a curve too distant from the cursor to hold one."""
        for curve in self._doc_curves:
            if not curve.nodes:
                continue
            if is_visible is not None and not is_visible(curve.layer):
                continue
            if far is not None and far(curve):
                continue

            if curve.kind in ("circle", "arc") and curve.radius:
                cx, cy, r = curve.nodes[0].x, curve.nodes[0].y, curve.radius
                sa, ea = curve.start_angle, curve.end_angle
                is_arc = curve.kind == "arc"
                dx, dy = ax - cx, ay - cy
                d = math.hypot(dx, dy)
                base = math.atan2(dy, dx)

                # Tangent: touch points where the line anchor→T grazes the
                # circle (two of them; none when the anchor is inside).
                if want_tangent and d > r + 1e-9:
                    alpha = math.acos(max(-1.0, min(1.0, r / d)))
                    for s in (1.0, -1.0):
                        a = base + s * alpha
                        if _angle_on_arc(is_arc, a, sa, ea):
                            candidate(QPointF(cx + r * math.cos(a),
                                              cy + r * math.sin(a)), "tangent")
                # Perpendicular to a circle = the radial points (the normal at
                # T points straight back at the anchor along the radius).
                if want_perp and d > 1e-9:
                    ux, uy = dx / d, dy / d
                    for s in (1.0, -1.0):
                        px, py = cx + s * r * ux, cy + s * r * uy
                        a = math.atan2(py - cy, px - cx)
                        if _angle_on_arc(is_arc, a, sa, ea):
                            candidate(QPointF(px, py), "perpendicular")

            elif want_perp and curve.kind == "line":
                nodes = curve.nodes
                n = len(nodes)
                count = n if curve.closed else n - 1
                for i in range(count):
                    p0, p1 = nodes[i], nodes[(i + 1) % n]
                    foot = _project_to_segment(ax, ay, p0.x, p0.y, p1.x, p1.y)
                    if foot is not None:
                        candidate(QPointF(*foot), "perpendicular")

            elif want_perp:   # spline: feet where the tangent is ⟂ to anchor→S
                samples = [(x, y) for x, y, _t in sample_curve(curve, 24)]
                m = len(samples)
                if m < 3:
                    continue
                prev = _perp_dot(samples, 0, ax, ay)
                for i in range(1, m):
                    val = _perp_dot(samples, i, ax, ay)
                    if prev == 0.0 or (prev < 0.0) != (val < 0.0):
                        u = prev / (prev - val) if val != prev else 0.5
                        x0, y0 = samples[i - 1]
                        x1, y1 = samples[i]
                        candidate(QPointF(x0 + (x1 - x0) * u,
                                          y0 + (y1 - y0) * u), "perpendicular")
                    prev = val

    def _sync_revision(self) -> None:
        """Drop the geometry caches when the scene's revision has moved."""
        rev = getattr(self._scene, "revision", 0)
        if rev != self._isect_rev:
            self._isect_cache.clear()
            self._extent_cache.clear()
            self._isect_rev = rev

    def _extent(self, curve) -> tuple:
        """_control_extent, cached until the next revision bump. A scene
        without a revision counter cannot say when a curve moved, so there
        it is recomputed every time."""
        if not hasattr(self._scene, "revision"):
            return _control_extent(curve)
        hit = self._extent_cache.get(id(curve))
        if hit is not None and hit[0] is curve:
            return hit[1]
        ext = _control_extent(curve)
        self._extent_cache[id(curve)] = (curve, ext)
        return ext

    def hide(self):
        self._hide()

    # ------------------------------------------------------------------
    # Indicator — ItemIgnoresTransformations keeps it constant screen size
    # ------------------------------------------------------------------

    def _indicator_color(self, snap_type: str) -> QColor:
        """Per-type indicator color from the theme (snap.<type> tokens)."""
        try:
            return QColor(theme.color(f"snap.{snap_type}"))
        except KeyError:
            return QColor(theme.color("snap.node"))

    def _show(self, pos: QPointF, snap_type: str):
        color = self._indicator_color(snap_type)
        key = (snap_type, color.name())
        if self._indicator is not None and self._indicator_key == key:
            # Same glyph as last time: just move it (this runs per mouse move).
            self._indicator.setPos(pos)
            self._indicator.setVisible(True)
            return
        self._hide()
        R   = _INDICATOR_R
        pen = QPen(color, 1.5)
        pen.setCosmetic(True)
        if snap_type == "curve":
            # Hollow diamond distinguishes "somewhere on the curve" from
            # exact point targets (circles).
            path = QPainterPath()
            path.moveTo(0, -R)
            path.lineTo(R, 0)
            path.lineTo(0, R)
            path.lineTo(-R, 0)
            path.closeSubpath()
            item = self._scene.addPath(path, pen)
        elif snap_type == "intersection":
            # "×" glyph — the crossing itself.
            path = QPainterPath()
            path.moveTo(-R, -R)
            path.lineTo(R, R)
            path.moveTo(-R, R)
            path.lineTo(R, -R)
            item = self._scene.addPath(path, pen)
        elif snap_type == "tangent":
            # A small circle with a tangent line grazing its top.
            path = QPainterPath()
            rr = R * 0.6
            path.addEllipse(-rr, -rr + R * 0.4, 2 * rr, 2 * rr)
            path.moveTo(-R, -R)
            path.lineTo(R, -R)
            item = self._scene.addPath(path, pen)
        elif snap_type == "perpendicular":
            # The ⊥ right-angle mark: an upright leg meeting a base with a
            # small square at the corner.
            path = QPainterPath()
            path.moveTo(-R, R)
            path.lineTo(R, R)
            path.moveTo(-R, R)
            path.lineTo(-R, -R)
            path.addRect(-R, R - R * 0.5, R * 0.5, R * 0.5)
            item = self._scene.addPath(path, pen)
        elif snap_type == "grid":
            # A small "+" at the grid intersection.
            path = QPainterPath()
            path.moveTo(-R, 0); path.lineTo(R, 0)
            path.moveTo(0, -R); path.lineTo(0, R)
            item = self._scene.addPath(path, pen)
        else:
            item = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, pen)
        item.setPos(pos)
        item.setFlag(item.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(200)
        self._indicator = item
        self._indicator_key = key

    def _hide(self):
        if self._indicator is not None:
            self._scene.removeItem(self._indicator)
            self._indicator = None
            self._indicator_key = None


# ---------- helpers ----------

def _angle_on_arc(is_arc: bool, a_rad: float,
                  sa: float | None, ea: float | None) -> bool:
    """True if angle a_rad (radians) lies on the curve — always for a full
    circle, within the sweep for an arc."""
    if not is_arc or sa is None or ea is None:
        return True
    return _angle_in_arc(math.degrees(a_rad) % 360, sa, ea)


def _perp_dot(samples: list, i: int, ax: float, ay: float) -> float:
    """(sample_i − anchor) · local tangent; a sign change between consecutive
    samples brackets a point where the curve is perpendicular to the anchor."""
    m = len(samples)
    x, y = samples[i]
    xp, yp = samples[max(0, i - 1)]
    xn, yn = samples[min(m - 1, i + 1)]
    return (x - ax) * (xn - xp) + (y - ay) * (yn - yp)


def _project_to_segment(px: float, py: float,
                        x0: float, y0: float,
                        x1: float, y1: float):
    """Perpendicular foot of (px, py) on segment (x0,y0)-(x1,y1), clamped to
    the segment. None if the segment is degenerate."""
    dx, dy = x1 - x0, y1 - y0
    seg2 = dx * dx + dy * dy
    if seg2 < 1e-12:
        return None
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / seg2))
    return (x0 + t * dx, y0 + t * dy)


def _control_extent(curve) -> tuple:
    """((min_x, max_x), (min_y, max_y)) over nodes AND handles — the control
    polygon bounds a Bézier, so this box never misses the curve's bulge."""
    xs, ys = [], []
    for n in curve.nodes:
        xs.append(n.x); ys.append(n.y)
        for cp in (n.cp_in, n.cp_out):
            if cp is not None:
                xs.append(cp.x); ys.append(cp.y)
    return (min(xs), max(xs)), (min(ys), max(ys))


def _min_stretch(m11: float, m12: float, m21: float, m22: float) -> float:
    """Smallest factor by which the 2×2 linear map stretches any direction
    (its smaller singular value); the uniform view scale for a plain zoom."""
    s = m11 * m11 + m12 * m12 + m21 * m21 + m22 * m22
    det = m11 * m22 - m12 * m21
    return math.sqrt(max(0.0, (s - math.sqrt(max(0.0, s * s - 4.0 * det * det))) / 2.0))


def _px_dist(view, sp: QPointF, tp: QPointF) -> float:
    # The view transform alone (no scroll offset) keeps sub-pixel precision;
    # mapFromScene rounds to whole pixels, which made near-ties resolve by
    # registration order and the radius test off by up to a pixel.
    xf = view.transform()
    a = xf.map(sp)
    b = xf.map(tp)
    return math.hypot(b.x() - a.x(), b.y() - a.y())


def px_dist(view, sp: QPointF, tp: QPointF) -> float:
    """Public: screen-pixel distance between two scene points."""
    return _px_dist(view, sp, tp)
