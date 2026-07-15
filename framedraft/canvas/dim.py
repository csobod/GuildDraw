"""DimItem — snap-aware dimension annotation with draggable offset.

Layout when dim.offset == 0:
    Tick──────────────────────Tick     ← dimension line at anchors
    P0                              P1

Layout when dim.offset != 0 (dragged away from geometry):
    P0 ─────────────────────────── P1   ← anchor points (small dots)
    |                               |   ← extension lines
    Tick───────── label ────────Tick    ← offset dimension line
    A                               B

The designer clicks anywhere on the item and drags perpendicular to the
measurement direction to extend/retract the extension lines.
"""

import math

from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem
from PySide6.QtCore import QRectF, QPointF, Qt, QTimer
from PySide6.QtGui import (
    QPen, QColor, QPainter, QFont, QFontMetrics, QPainterPath,
    QPainterPathStroker, QPolygonF,
)

from ..document import DimLine

_OVERSHOOT_MM = 1.5   # mm: extension line extends this far past the dim line
_ARROW_PX     = 10.0  # screen-pixel arrowhead length
_ARROW_W_PX   = 3.5   # screen-pixel arrowhead half-width
_LABEL_PX     = 11    # label font size (screen pixels)
_LABEL_GAP_PX = 3     # screen pixels between the dim line and the label
_ANCHOR_R_PX  = 2.5   # screen-pixel radius of anchor dots
_HIT_TOL_MM   = 3.0   # mm: click-tolerance for contains()


def _seg_dist(pt: QPointF, p0: QPointF, p1: QPointF) -> float:
    """Shortest distance from pt to the finite segment p0→p1."""
    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        return math.hypot(pt.x() - p0.x(), pt.y() - p0.y())
    t = max(0.0, min(1.0, ((pt.x() - p0.x()) * dx + (pt.y() - p0.y()) * dy) / len2))
    return math.hypot(pt.x() - (p0.x() + t * dx), pt.y() - (p0.y() + t * dy))


def _dim_color(selected: bool = False) -> QColor:
    from .. import theme
    return QColor(theme.color("guide.dim_selected" if selected else "guide.dim"))


_DRAG_THRESHOLD_PX = 4   # screen pixels of travel before an offset-drag starts


class DimItem(QGraphicsItem):
    """Scene item representing one DimLine annotation.

    on_drag_start: optional callable invoked once when an offset-drag actually
    begins (after the movement threshold) — used to push an undo snapshot.
    """

    def __init__(self, dim: DimLine, on_drag_start=None):
        super().__init__()
        self.dim = dim
        self._on_drag_start = on_drag_start
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, False)
        self.setAcceptHoverEvents(True)
        self.setZValue(15)
        self._dragging    = False
        self._maybe_drag  = False
        self._press_screen = None
        # Screen-sized decorations (label, arrows) live outside the scene-mm
        # geometry, so boundingRect needs the current view scale to cover
        # them. paint() caches it here and queues a geometry refresh when the
        # zoom moves far enough that the old pad no longer covers the label.
        self._br_scale   = 1.0
        self._label_w_px = 90.0
        # Deferred bounds-sync timer. It MUST be owned (not a fire-and-forget
        # QTimer.singleShot on this non-QObject item): a pending singleShot
        # could fire on a DELETED item and crash — PySide marshals the call
        # into freed C++ memory before any Python guard runs. That was the
        # "delete a dimension → app closes" segfault. The item↔timer connection
        # keeps the wrapper alive while a sync is pending, and itemChange()
        # stops it the instant the item leaves the scene.
        self._bounds_timer = QTimer()
        self._bounds_timer.setSingleShot(True)
        self._bounds_timer.setInterval(0)
        self._bounds_timer.timeout.connect(self._sync_bounds)

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _perp(self):
        """Return (nx, ny) — unit vector perpendicular (CCW) to measurement axis."""
        dx = self.dim.x1 - self.dim.x0
        dy = self.dim.y1 - self.dim.y0
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return 0.0, 1.0
        return -dy / length, dx / length

    def _key_points(self):
        """Return P0, P1, A, B in scene mm.

        P0, P1 = anchor points (original measurement endpoints)
        A,  B  = offset dimension line endpoints
        """
        nx, ny = self._perp()
        off    = self.dim.offset
        P0 = QPointF(self.dim.x0, self.dim.y0)
        P1 = QPointF(self.dim.x1, self.dim.y1)
        A  = QPointF(self.dim.x0 + nx * off, self.dim.y0 + ny * off)
        B  = QPointF(self.dim.x1 + nx * off, self.dim.y1 + ny * off)
        return P0, P1, A, B

    def _offset_from_scene(self, scene_pos: QPointF) -> float:
        """Signed perpendicular distance from scene_pos to the measurement axis."""
        nx, ny = self._perp()
        return ((scene_pos.x() - self.dim.x0) * nx
                + (scene_pos.y() - self.dim.y0) * ny)

    # ------------------------------------------------------------------
    # QGraphicsItem interface
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        P0, P1, A, B = self._key_points()
        nx, ny = self._perp()
        off    = self.dim.offset

        # Extend in the signed overshoot direction past the dim line ends
        if abs(off) > 0.1:
            sign = math.copysign(1.0, off)
            ov   = _OVERSHOOT_MM * sign
            extra_pts = [
                (A.x() + nx * ov, A.y() + ny * ov),
                (B.x() + nx * ov, B.y() + ny * ov),
            ]
        else:
            extra_pts = []

        pts = [
            (P0.x(), P0.y()),
            (P1.x(), P1.y()),
            (A.x(), A.y()),
            (B.x(), B.y()),
        ] + extra_pts

        xs  = [p[0] for p in pts]
        ys  = [p[1] for p in pts]
        # Pad must cover the hit tolerance in ALL directions, plus the
        # screen-sized decorations (label half-width, arrowheads) converted
        # to mm at the last painted scale.
        deco_px = max(2.0 * _ARROW_PX,
                      self._label_w_px / 2.0 + 8.0,
                      _LABEL_GAP_PX + _LABEL_PX + 8.0)
        pad = max(6.0, _HIT_TOL_MM + 1.0,
                  deco_px / max(self._br_scale, 1e-6))
        return QRectF(min(xs) - pad, min(ys) - pad,
                      max(xs) - min(xs) + 2 * pad,
                      max(ys) - min(ys) + 2 * pad)

    def contains(self, point: QPointF) -> bool:
        """Distance-based hit-test — bypasses QPainterPath.contains() unreliability."""
        P0, P1, A, B = self._key_points()
        if _seg_dist(point, A, B) <= _HIT_TOL_MM:
            return True
        if abs(self.dim.offset) > 0.5:
            return (_seg_dist(point, P0, A) <= _HIT_TOL_MM or
                    _seg_dist(point, P1, B) <= _HIT_TOL_MM)
        return False

    def shape(self):
        """Stroked hit area around the dim line and extension lines.
        Used for rubber-band selection; single-click uses contains() instead."""
        P0, P1, A, B = self._key_points()
        path = QPainterPath()
        path.moveTo(A)
        path.lineTo(B)
        if abs(self.dim.offset) > 0.5:
            path.moveTo(P0)
            path.lineTo(A)
            path.moveTo(P1)
            path.lineTo(B)
        stroker = QPainterPathStroker()
        stroker.setWidth(_HIT_TOL_MM * 2)
        stroker.setCapStyle(Qt.PenCapStyle.FlatCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        hit = stroker.createStroke(path)
        hit.setFillRule(Qt.FillRule.WindingFill)
        return hit

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None):
        selected = bool(option.state & option.state.State_Selected)
        color    = _dim_color(selected)
        pen      = QPen(color, 0)
        pen.setCosmetic(True)
        painter.setPen(pen)

        P0, P1, A, B = self._key_points()
        nx, ny = self._perp()
        off    = self.dim.offset

        # ── extension lines (only when there is a meaningful offset) ──
        if abs(off) > 0.5:
            sign = math.copysign(1.0, off)
            ov   = _OVERSHOOT_MM * sign
            # Extension lines: anchor → (dim-line end + overshoot)
            painter.drawLine(P0, QPointF(A.x() + nx * ov, A.y() + ny * ov))
            painter.drawLine(P1, QPointF(B.x() + nx * ov, B.y() + ny * ov))
        elif abs(off) > 0.01:
            # Tiny offset: draw extension lines without overshoot
            painter.drawLine(P0, A)
            painter.drawLine(P1, B)

        # ── dimension line (A → B) ──
        painter.drawLine(A, B)

        # ── arrowheads at A and B (filled, constant screen size) ──
        t_painter = painter.transform()
        scale_x   = math.hypot(t_painter.m11(), t_painter.m21())
        scale_y   = math.hypot(t_painter.m12(), t_painter.m22())
        scale     = (scale_x + scale_y) / 2.0 or 1.0

        dx_m = self.dim.x1 - self.dim.x0
        dy_m = self.dim.y1 - self.dim.y0
        mlen  = math.hypot(dx_m, dy_m) or 1.0
        tx_m  = dx_m / mlen   # unit along measurement (A → B)
        ty_m  = dy_m / mlen

        arrow_mm = _ARROW_PX / scale
        half_mm  = _ARROW_W_PX / scale
        # Tips sit exactly on A/B, bodies inside; too tight for two heads →
        # flip the bodies outside (classic CAD short-dimension form).
        inward = 1.0 if mlen * scale >= 4.0 * _ARROW_PX else -1.0

        def draw_arrow(tip: QPointF, bdx: float, bdy: float):
            bx = tip.x() + bdx * arrow_mm
            by = tip.y() + bdy * arrow_mm
            painter.setBrush(QColor(color))
            painter.drawPolygon(QPolygonF([
                tip,
                QPointF(bx - bdy * half_mm, by + bdx * half_mm),
                QPointF(bx + bdy * half_mm, by - bdx * half_mm),
            ]))
            painter.setBrush(Qt.BrushStyle.NoBrush)

        draw_arrow(A,  inward * tx_m,  inward * ty_m)
        draw_arrow(B, -inward * tx_m, -inward * ty_m)

        # ── anchor dots (visible when offset is large enough) ──
        if abs(off) > 2.0:
            r_mm = _ANCHOR_R_PX / scale
            for pt in (P0, P1):
                painter.setBrush(QColor(color))
                painter.drawEllipse(pt, r_mm, r_mm)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # ── label: parallel to the dim line, on the side AWAY from the
        # measured geometry (the direction the dim line was offset toward), so
        # the number never sits crammed between the object and its dim line. ──
        dist_mm = math.hypot(dx_m, dy_m)
        label   = f"{dist_mm:.2f} mm"
        A_s = t_painter.map(A)
        B_s = t_painter.map(B)
        P0_s = t_painter.map(P0)                      # a geometry anchor (screen)
        mid = QPointF((A_s.x() + B_s.x()) / 2, (A_s.y() + B_s.y()) / 2)
        lx, ly = B_s.x() - A_s.x(), B_s.y() - A_s.y()
        L = math.hypot(lx, ly) or 1.0
        ux, uy = lx / L, ly / L                       # unit along the dim line
        px, py = -uy, ux                              # screen perpendicular
        # Flip the perpendicular so it points away from the geometry: the
        # geometry sits on the −offset side, so mid→P0 has a component toward it.
        if px * (P0_s.x() - mid.x()) + py * (P0_s.y() - mid.y()) > 0:
            px, py = -px, -py

        ang = math.degrees(math.atan2(uy, ux))
        if ang > 90.0 or ang <= -90.0:
            ang += 180.0                              # keep the text upright

        font = QFont("Segoe UI")   # no point size — pixel-sized below
        font.setPixelSize(_LABEL_PX)
        fm = QFontMetrics(font)
        self._label_w_px = float(fm.horizontalAdvance(label))
        text_h = fm.ascent() + fm.descent()
        # Push the label centre off the line by the gap + half its height, on
        # the away side, then draw it centred and upright.
        gap = _LABEL_GAP_PX + text_h / 2.0
        cx, cy = mid.x() + px * gap, mid.y() + py * gap

        painter.save()
        painter.resetTransform()
        painter.translate(cx, cy)
        painter.rotate(ang)
        painter.setFont(font)
        painter.setPen(QPen(color))
        painter.drawText(
            QPointF(-self._label_w_px / 2.0, fm.ascent() - text_h / 2.0), label)
        painter.restore()

        # Screen-sized decorations moved relative to scene mm — refresh the
        # cached scale (and the bounding rect derived from it) off-paint.
        if abs(scale - self._br_scale) > 0.2 * self._br_scale:
            self._br_scale = scale
            self._bounds_timer.start()   # owned + cancelled on removal

    def _sync_bounds(self):
        # Only ever fires while the item is in a scene (the timer is stopped in
        # itemChange the moment it is removed), so this runs on a live item.
        if self.scene() is not None:
            self.prepareGeometryChange()
            self.update()

    def itemChange(self, change, value):
        # Leaving the scene (removed or deleted): cancel any pending bounds
        # sync so its timer can never fire on a dead item.
        if (change == self.GraphicsItemChange.ItemSceneChange
                and value is None):
            self._bounds_timer.stop()
        return super().itemChange(change, value)

    # ------------------------------------------------------------------
    # Drag interaction — updates dim.offset on mouse move
    # ------------------------------------------------------------------

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)   # handles selection
        if event.button() == Qt.MouseButton.LeftButton:
            self._maybe_drag   = True
            self._dragging     = False
            self._press_screen = event.screenPos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._maybe_drag and not self._dragging:
            moved = (event.screenPos() - self._press_screen).manhattanLength()
            if moved > _DRAG_THRESHOLD_PX:
                self._dragging = True
                if self._on_drag_start:
                    self._on_drag_start()
        if self._dragging:
            new_off = self._offset_from_scene(event.scenePos())
            if new_off != self.dim.offset:
                self.prepareGeometryChange()
                self.dim.offset = new_off
                self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._maybe_drag and event.button() == Qt.MouseButton.LeftButton:
            self._maybe_drag = False
            self._dragging   = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)
