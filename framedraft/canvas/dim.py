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
from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QPen, QColor, QPainter, QFont, QFontMetrics, QPainterPath, QPainterPathStroker

from ..document import DimLine

_OVERSHOOT_MM = 1.5   # mm: extension line extends this far past the dim line
_TICK_PX      = 8     # screen-pixel half-length of end ticks
_LABEL_PX     = 11    # label font size (screen pixels)
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
    return QColor("#e67e22") if selected else QColor("#7a5c2e")


class DimItem(QGraphicsItem):
    """Scene item representing one DimLine annotation."""

    def __init__(self, dim: DimLine):
        super().__init__()
        self.dim = dim
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, False)
        self.setAcceptHoverEvents(True)
        self.setZValue(15)
        self._dragging       = False
        self._drag_offset_start = 0.0

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
        # Pad must cover the hit tolerance in ALL directions, including perpendicular
        pad = max(6.0, _HIT_TOL_MM + 1.0)
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

        # ── tick marks at A and B ──
        # Ticks are perpendicular to the dim line direction → along measurement axis
        # Compute in screen space so they stay constant pixel size
        t_painter = painter.transform()
        scale_x   = math.hypot(t_painter.m11(), t_painter.m21())
        scale_y   = math.hypot(t_painter.m12(), t_painter.m22())
        scale     = (scale_x + scale_y) / 2.0 or 1.0

        dx_m = self.dim.x1 - self.dim.x0
        dy_m = self.dim.y1 - self.dim.y0
        mlen  = math.hypot(dx_m, dy_m) or 1.0
        tx_m  = dx_m / mlen   # unit along measurement (for ticks)
        ty_m  = dy_m / mlen

        tick_mm = _TICK_PX / scale

        def draw_tick(pt: QPointF):
            painter.drawLine(
                QPointF(pt.x() + tx_m * tick_mm, pt.y() + ty_m * tick_mm),
                QPointF(pt.x() - tx_m * tick_mm, pt.y() - ty_m * tick_mm),
            )

        draw_tick(A)
        draw_tick(B)

        # ── anchor dots (visible when offset is large enough) ──
        if abs(off) > 2.0:
            r_mm = _ANCHOR_R_PX / scale
            for pt in (P0, P1):
                painter.setBrush(QColor(color))
                painter.drawEllipse(pt, r_mm, r_mm)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # ── label (rendered at constant screen size) ──
        dist_mm = math.hypot(self.dim.x1 - self.dim.x0,
                             self.dim.y1 - self.dim.y0)
        label   = f"{dist_mm:.2f} mm"
        mid_scene  = QPointF((A.x() + B.x()) / 2, (A.y() + B.y()) / 2)
        mid_screen = t_painter.map(mid_scene)

        # Perpendicular screen vector (for nudging label off the dim line)
        sp_nx = nx * scale_x
        sp_ny = ny * scale_y
        sp_len = math.hypot(sp_nx, sp_ny) or 1.0

        painter.save()
        painter.resetTransform()

        font = QFont("Segoe UI", -1)
        font.setPixelSize(_LABEL_PX)
        painter.setFont(font)
        painter.setPen(QPen(color))

        fm     = QFontMetrics(font)
        text_w = fm.horizontalAdvance(label)
        text_h = fm.height()
        nudge  = 4   # screen pixels above the dim line

        lx = mid_screen.x() + (sp_nx / sp_len) * nudge - text_w / 2
        ly = mid_screen.y() + (sp_ny / sp_len) * nudge - text_h / 4

        painter.drawText(QPointF(lx, ly), label)
        painter.restore()

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
            self._dragging          = True
            self._drag_offset_start = self.dim.offset
            event.accept()

    def mouseMoveEvent(self, event):
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
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)
