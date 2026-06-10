import math
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPen, QColor, QPainterPath

from ..geometry import sample_curve

_SNAP_RADIUS_PX = 10   # screen-pixel snap radius (view space)
_INDICATOR_R    = 6    # screen-pixel indicator radius (view space)


def _angle_in_arc(angle_deg: float, start_deg: float, end_deg: float) -> bool:
    """True if angle_deg is covered by the arc sweeping from start_deg to end_deg
    in the positive (CW-on-screen) direction."""
    sweep = (end_deg - start_deg) % 360
    return ((angle_deg - start_deg) % 360) <= sweep


class SnapEngine:
    """
    Finds the nearest snap target within _SNAP_RADIUS_PX screen pixels of the
    cursor and shows a coloured indicator dot.

    Snap targets (in priority order):
      1. Existing curve on-curve nodes
      2. Existing curve control-point handles
      3. In-progress drawing nodes
      4. Mirror axis (vertical line x = axis_x)

    Ctrl held → suspend snap for that event (caller passes use_snap=False).
    """

    def __init__(self, scene):
        self._scene = scene
        self._doc_curves: list = []
        self._mirror_x:   float | None = None
        self._mirror_on:  bool = False
        self._enabled:    bool = True
        self._indicator         = None

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

        def candidate(target: QPointF, t: str):
            nonlocal best, best_dist, best_type
            d = _px_dist(view, scene_pos, target)
            if d < _SNAP_RADIUS_PX and d < best_dist:
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
                candidate(QPointF(cx, cy), "node")          # center
                # Four cardinal quadrant points
                quadrants = ((0, cx + r, cy), (90, cx, cy + r),
                             (180, cx - r, cy), (270, cx, cy - r))
                sa, ea = curve.start_angle, curve.end_angle
                for q_deg, qx, qy in quadrants:
                    if curve.kind == "circle":
                        candidate(QPointF(qx, qy), "node")
                    elif sa is not None and ea is not None:
                        if _angle_in_arc(q_deg, sa, ea):
                            candidate(QPointF(qx, qy), "node")
                # Arc endpoints
                if curve.kind == "arc" and sa is not None and ea is not None:
                    sa_r, ea_r = math.radians(sa), math.radians(ea)
                    candidate(QPointF(cx + r * math.cos(sa_r), cy + r * math.sin(sa_r)), "node")
                    candidate(QPointF(cx + r * math.cos(ea_r), cy + r * math.sin(ea_r)), "node")
            else:
                for node in curve.nodes:
                    candidate(QPointF(node.x, node.y), "node")
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

        if self._mirror_on and self._mirror_x is not None:
            if getattr(self, '_mirror_horizontal', False):
                candidate(QPointF(scene_pos.x(), self._mirror_x), "mirror")
            else:
                candidate(QPointF(self._mirror_x, scene_pos.y()), "mirror")

        # On-curve snap (nearest point anywhere along a curve) — LOWEST
        # priority: only when no point target was found, because every node
        # lies on its curve and would otherwise be shadowed. Needed for
        # drawing OUTLINE→LENS connectors (scallop / extrusion work).
        if best_type is None:
            on_curve = self._nearest_on_curve(scene_pos, view, is_visible)
            if on_curve is not None:
                best, best_type = on_curve, "curve"

        # Origin snap — single point (0, 0).
        # Checked after all other candidates so it can override them: the mirror
        # snap projects the cursor onto x=0 with zero distance, which would always
        # beat a point-snap via the normal < comparison.
        _d_orig = _px_dist(view, scene_pos, QPointF(0.0, 0.0))
        if _d_orig < _SNAP_RADIUS_PX:
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
        r_mm  = _SNAP_RADIUS_PX / scale
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

    def hide(self):
        self._hide()

    # ------------------------------------------------------------------
    # Indicator — ItemIgnoresTransformations keeps it constant screen size
    # ------------------------------------------------------------------

    _COLORS = {
        "node":     "#2e8b57",  # green
        "handle":   "#2a7f9e",  # blue
        "mirror":   "#c0392b",  # red
        "axis":     "#7b5ea7",  # purple — scene origin (0, 0)
        "midpoint": "#e67e22",  # orange — segment midpoint
        "curve":    "#5d8aa8",  # steel blue — nearest point on curve (diamond)
    }

    def _show(self, pos: QPointF, snap_type: str):
        self._hide()
        R   = _INDICATOR_R
        pen = QPen(QColor(self._COLORS.get(snap_type, "#2e8b57")), 1.5)
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

def _px_dist(view, sp: QPointF, tp: QPointF) -> float:
    a = view.mapFromScene(sp)
    b = view.mapFromScene(tp)
    return math.hypot(b.x() - a.x(), b.y() - a.y())


def px_dist(view, sp: QPointF, tp: QPointF) -> float:
    """Public: screen-pixel distance between two scene points."""
    return _px_dist(view, sp, tp)
