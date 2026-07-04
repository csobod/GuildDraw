import math
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPen, QColor, QPainterPath

from ..geometry import sample_curve

_SNAP_RADIUS_PX = 10   # default screen-pixel snap radius (view space)
_INDICATOR_R    = 6    # screen-pixel indicator radius (view space)

# Snap-type registry — drives the engine's gating AND the snap palette UI.
# (key, palette label, tooltip). Keys are also theme tokens (snap.<key>).
SNAP_TYPES: list[tuple[str, str, str]] = [
    ("endpoint",      "Endpoint",      "Open-curve ends and arc endpoints"),
    ("node",          "Node",          "Interior and closed-curve nodes"),
    ("midpoint",      "Midpoint",      "Line-segment midpoints"),
    ("center",        "Center",        "Circle and arc centres"),
    ("quadrant",      "Quadrant",      "Circle/arc 0°/90°/180°/270° points"),
    ("intersection",  "Intersection",  "Where two curves cross"),
    ("tangent",       "Tangent",       "Tangent to a circle/arc from the point being drawn"),
    ("perpendicular", "Perpendicular", "Perpendicular to a line/curve from the point being drawn"),
    ("handle",        "Handle",        "Bézier control-point handles"),
    ("curve",         "On-curve",      "Nearest point along a curve"),
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
    return ((angle_deg - start_deg) % 360) <= sweep


class SnapEngine:
    """
    Finds the nearest snap target within the snap radius (screen px) of the
    cursor and shows a coloured indicator dot.

    Each target carries a type from SNAP_TYPES; the palette toggles types on
    and off per user preference (set_enabled_types), the master toggle
    (set_enabled) and Ctrl-suspend still silence everything at once.

    Point-target priority is purely nearest-wins among enabled types;
    on-curve is a fallback when no point target hits, and the origin
    overrides everything inside its radius (the mirror projection would
    otherwise always shadow it with a zero-distance hit).
    """

    def __init__(self, scene):
        self._scene = scene
        self._doc_curves: list = []
        self._mirror_x:   float | None = None
        self._mirror_on:  bool = False
        self._enabled:    bool = True
        self._indicator         = None
        self._radius_px: float  = _SNAP_RADIUS_PX
        self._enabled_types: set[str] = set(SNAP_TYPE_KEYS)
        # Intersection cache: (id(a), id(b)) -> [(x, y), ...]; wholesale-
        # invalidated whenever the scene's geometry revision moves (ids are
        # stable between revisions because add/remove bumps the revision).
        self._isect_cache: dict = {}
        self._isect_rev: int = -1

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

    def radius_px(self) -> float:
        return self._radius_px

    def set_type_enabled(self, key: str, on: bool):
        if on:
            self._enabled_types.add(key)
        else:
            self._enabled_types.discard(key)

    def set_enabled_types(self, types):
        """types: {key: bool} mapping or iterable of enabled keys."""
        if isinstance(types, dict):
            self._enabled_types = {k for k, on in types.items() if on}
        else:
            self._enabled_types = set(types)

    def type_enabled(self, key: str) -> bool:
        return key in self._enabled_types

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

        def candidate(target: QPointF, t: str):
            nonlocal best, best_dist, best_type
            if t not in enabled:
                return
            d = _px_dist(view, scene_pos, target)
            if d < self._radius_px and d < best_dist:
                best_dist = d
                best      = target
                best_type = t

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
                last = len(curve.nodes) - 1
                for i, node in enumerate(curve.nodes):
                    tag = ("endpoint" if not curve.closed and i in (0, last)
                           else "node")
                    candidate(QPointF(node.x, node.y), tag)
                    for cp in (node.cp_in, node.cp_out):
                        if cp is not None:
                            candidate(QPointF(cp.x, cp.y), "handle")
                # Midpoints of line segments
                if curve.kind == "line":
                    nodes = curve.nodes
                    n = len(nodes)
                    count = n if curve.closed else n - 1
                    for i in range(count):
                        j = (i + 1) % n
                        candidate(QPointF((nodes[i].x + nodes[j].x) / 2,
                                         (nodes[i].y + nodes[j].y) / 2),
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
                                         is_visible, want_t, want_p)

        if self._mirror_on and self._mirror_x is not None:
            if getattr(self, '_mirror_horizontal', False):
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
            # Cheap bbox reject before sampling (pad covers radius + handles)
            xs = [n.x for n in curve.nodes]
            ys = [n.y for n in curve.nodes]
            pad = (curve.radius or 0.0) + best_d + 5.0
            if not (min(xs) - pad <= px <= max(xs) + pad
                    and min(ys) - pad <= py <= max(ys) + pad):
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
        rev = getattr(self._scene, "revision", 0)
        if rev != self._isect_rev:
            self._isect_cache.clear()
            self._isect_rev = rev

        scale = max(abs(view.transform().m11()), 1e-6)
        r_mm  = self._radius_px / scale
        px, py = scene_pos.x(), scene_pos.y()

        near: list = []
        for curve in self._doc_curves:
            if not curve.nodes:
                continue
            if is_visible is not None and not is_visible(curve.layer):
                continue
            xs = [n.x for n in curve.nodes]
            ys = [n.y for n in curve.nodes]
            pad = (curve.radius or 0.0) + r_mm + 5.0
            if (min(xs) - pad <= px <= max(xs) + pad
                    and min(ys) - pad <= py <= max(ys) + pad):
                near.append(curve)
        if len(near) < 2:
            return

        from ..geometry import curve_intersections
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
                            want_perp: bool) -> None:
        """Tangent + perpendicular targets measured from the anchor (ax, ay) —
        the point currently being drawn. candidate() still filters by nearness
        to the cursor, so the maker steers toward the target they want."""
        for curve in self._doc_curves:
            if not curve.nodes:
                continue
            if is_visible is not None and not is_visible(curve.layer):
                continue

            if curve.kind in ("circle", "arc") and curve.radius:
                cx, cy, r = curve.nodes[0].x, curve.nodes[0].y, curve.radius
                sa, ea = curve.start_angle, curve.end_angle
                is_arc = curve.kind == "arc"

                def on_arc(a_rad: float) -> bool:
                    if not is_arc:
                        return True
                    if sa is None or ea is None:
                        return True
                    return _angle_in_arc(math.degrees(a_rad) % 360, sa, ea)

                dx, dy = ax - cx, ay - cy
                d = math.hypot(dx, dy)
                base = math.atan2(dy, dx)

                # Tangent: touch points where the line anchor→T grazes the
                # circle (two of them; none when the anchor is inside).
                if want_tangent and d > r + 1e-9:
                    alpha = math.acos(max(-1.0, min(1.0, r / d)))
                    for s in (1.0, -1.0):
                        a = base + s * alpha
                        if on_arc(a):
                            candidate(QPointF(cx + r * math.cos(a),
                                              cy + r * math.sin(a)), "tangent")
                # Perpendicular to a circle = the radial points (the normal at
                # T points straight back at the anchor along the radius).
                if want_perp and d > 1e-9:
                    ux, uy = dx / d, dy / d
                    for s in (1.0, -1.0):
                        px, py = cx + s * r * ux, cy + s * r * uy
                        a = math.atan2(py - cy, px - cx)
                        if on_arc(a):
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

                def perp_dot(i: int) -> float:
                    x, y = samples[i]
                    xp, yp = samples[max(0, i - 1)]
                    xn, yn = samples[min(m - 1, i + 1)]
                    return (x - ax) * (xn - xp) + (y - ay) * (yn - yp)

                prev = perp_dot(0)
                for i in range(1, m):
                    val = perp_dot(i)
                    if prev == 0.0 or (prev < 0.0) != (val < 0.0):
                        u = prev / (prev - val) if val != prev else 0.5
                        x0, y0 = samples[i - 1]
                        x1, y1 = samples[i]
                        candidate(QPointF(x0 + (x1 - x0) * u,
                                          y0 + (y1 - y0) * u), "perpendicular")
                    prev = val

    def hide(self):
        self._hide()

    # ------------------------------------------------------------------
    # Indicator — ItemIgnoresTransformations keeps it constant screen size
    # ------------------------------------------------------------------

    def _indicator_color(self, snap_type: str) -> QColor:
        """Per-type indicator color from the theme (snap.<type> tokens)."""
        from .. import theme
        try:
            return QColor(theme.color(f"snap.{snap_type}"))
        except KeyError:
            return QColor(theme.color("snap.node"))

    def _show(self, pos: QPointF, snap_type: str):
        self._hide()
        R   = _INDICATOR_R
        pen = QPen(self._indicator_color(snap_type), 1.5)
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
        else:
            item = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, pen)
        item.setPos(pos)
        item.setFlag(item.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(200)
        self._indicator = item

    def _hide(self):
        if self._indicator is not None:
            self._scene.removeItem(self._indicator)
            self._indicator = None


# ---------- helpers ----------

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


def _px_dist(view, sp: QPointF, tp: QPointF) -> float:
    a = view.mapFromScene(sp)
    b = view.mapFromScene(tp)
    return math.hypot(b.x() - a.x(), b.y() - a.y())


def px_dist(view, sp: QPointF, tp: QPointF) -> float:
    """Public: screen-pixel distance between two scene points."""
    return _px_dist(view, sp, tp)
