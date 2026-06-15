import math

from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsEllipseItem, QStyleOptionGraphicsItem
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QPainterPathStroker
from PySide6.QtCore import Qt

from ..document import Curve, Layer, ControlPoint

# ---------- theme flag + colour functions ----------

_DARK: bool = False


def set_dark_mode(dark: bool) -> None:
    global _DARK
    _DARK = dark


def _geometry_color() -> QColor:
    return QColor("#d4cfc0") if _DARK else QColor("#1f1f1f")

def _handle_color() -> QColor:
    return QColor("#4ab8d8") if _DARK else QColor("#2a7f9e")

def _handle_fill() -> QColor:
    return QColor("#1a3040") if _DARK else QColor("#dff0f7")

def _handle_hover() -> QColor:
    return QColor("#4ab8d8") if _DARK else QColor("#2a7f9e")

def _node_fill() -> QColor:
    return QColor("#3a3020") if _DARK else QColor("#fce9c2")

def _node_hover() -> QColor:
    return QColor("#4aca7a") if _DARK else QColor("#2e8b57")

def _selection_halo_color() -> QColor:
    # Bright, semi-transparent amber glow drawn behind a selected curve.
    return QColor(255, 170, 60, 150) if _DARK else QColor(255, 140, 0, 130)


# ---------- per-layer pen factory ----------
# All pens are cosmetic (constant screen width regardless of zoom).

_LAYER_COLORS_LIGHT = {
    Layer.SCULPT:    QColor("#8e44ad"),  # purple  — back-surface geometry
    Layer.ENGRAVING: QColor("#16a085"),  # teal    — engraving marks
}
_LAYER_COLORS_DARK = {
    Layer.SCULPT:    QColor("#c39bd3"),  # light purple
    Layer.ENGRAVING: QColor("#48c9b0"),  # light teal
}


def _layer_pen(layer: Layer, line_weight: float | None = None) -> QPen:
    palette = _LAYER_COLORS_DARK if _DARK else _LAYER_COLORS_LIGHT
    color   = palette.get(layer, _geometry_color())
    pen = QPen(color)
    pen.setCosmetic(True)
    w = line_weight if line_weight is not None else (
        1.5 if layer in (Layer.OUTLINE, Layer.LENS) else
        0.8 if layer == Layer.REF else
        1.0
    )
    pen.setWidthF(w)
    if layer == Layer.REF:
        pen.setStyle(Qt.PenStyle.DashLine)
    return pen


def make_handle_line_pen() -> QPen:
    """Cosmetic dotted pen for handle–node connector lines."""
    pen = QPen(_handle_color(), 0, Qt.PenStyle.DotLine)
    pen.setCosmetic(True)
    return pen


def curve_layer_locked(item) -> bool:
    """True if a CurveItem's layer is locked in its FrameScene.

    Used by cursor tools (trim/split/offset) so locked geometry can't be
    modified by a click even though it remains visible.
    """
    sc = item.scene()
    fn = getattr(sc, "is_layer_locked", None)
    return bool(fn and fn(item.curve.layer))


# ---------- path builder ----------

def build_path(curve: Curve) -> QPainterPath:
    path = QPainterPath()
    nodes = curve.nodes
    if not nodes:
        return path

    if curve.kind == "circle":
        if curve.radius:
            cx, cy, r = nodes[0].x, nodes[0].y, curve.radius
            path.addEllipse(cx - r, cy - r, 2 * r, 2 * r)
        return path

    if curve.kind == "arc":
        if (curve.radius and curve.start_angle is not None
                and curve.end_angle is not None):
            cx, cy, r = nodes[0].x, nodes[0].y, curve.radius
            sa_rad = math.radians(curve.start_angle)
            path.moveTo(cx + r * math.cos(sa_rad), cy + r * math.sin(sa_rad))
            sweep = (curve.end_angle - curve.start_angle) % 360
            if sweep < 0.001:
                sweep = 360
            # arcTo uses Qt convention: angles CCW in Qt-space (CW on screen since Y-down).
            # Our stored angles are from atan2 in Qt scene (Y-down), so negate both to
            # convert to Qt's arcTo convention; the sweep negates to preserve direction.
            path.arcTo(cx - r, cy - r, 2 * r, 2 * r, -curve.start_angle, -sweep)
        return path

    path.moveTo(nodes[0].x, nodes[0].y)
    if curve.kind == "line":
        for n in nodes[1:]:
            path.lineTo(n.x, n.y)
        if curve.closed:
            path.closeSubpath()
    else:
        for i in range(1, len(nodes)):
            p, c = nodes[i - 1], nodes[i]
            cp1 = p.cp_out or ControlPoint(p.x, p.y)
            cp2 = c.cp_in  or ControlPoint(c.x, c.y)
            path.cubicTo(cp1.x, cp1.y, cp2.x, cp2.y, c.x, c.y)
        if curve.closed and len(nodes) > 1:
            last, first = nodes[-1], nodes[0]
            cp1 = last.cp_out  or ControlPoint(last.x, last.y)
            cp2 = first.cp_in  or ControlPoint(first.x, first.y)
            path.cubicTo(cp1.x, cp1.y, cp2.x, cp2.y, first.x, first.y)
            path.closeSubpath()
    return path


# ---------- CurveItem ----------

class CurveItem(QGraphicsPathItem):
    """Rendered geometry for one Curve. Selectable in Select mode."""

    def __init__(self, curve: Curve):
        super().__init__()
        self.curve = curve
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(10)
        self.refresh()

    def refresh(self):
        self.setPath(build_path(self.curve))
        self.setPen(_layer_pen(self.curve.layer, self.curve.line_weight))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def shape(self) -> QPainterPath:
        # Use only the stroked outline as the hit area. The default
        # QGraphicsPathItem.shape() returns the filled interior for closed paths,
        # which makes clicks anywhere inside a closed outline hit it instead of
        # curves underneath (e.g., lens inside outline). A 2mm stroke gives
        # ~8–12px hit tolerance at typical zoom without claiming the interior.
        stroker = QPainterPathStroker()
        stroker.setWidth(2.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        selected = bool(option.state & option.state.State_Selected)
        # Prominent selection feedback: a wide, semi-transparent highlight
        # halo drawn UNDER the normal stroke, so every selected curve is
        # obviously highlighted whether one or many are picked (node-editing
        # dots only appear for a single selection, so the halo is the primary
        # multi-select cue).
        if selected:
            halo = QPen(_selection_halo_color(), self.curve.line_weight + 3.0)
            halo.setCosmetic(True)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(halo)
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.drawPath(self.path())
        plain = QStyleOptionGraphicsItem(option)
        plain.state &= ~plain.state.State_Selected
        super().paint(painter, plain, widget)


# ---------- NodeDot ----------

_R = 4

def _node_selected() -> QColor:
    return QColor("#e74c3c")


class NodeDot(QGraphicsEllipseItem):
    """Movable on-curve node shown when a CurveItem is selected.

    Uses ItemIgnoresTransformations so it stays a constant screen size
    regardless of zoom level.
    """

    def __init__(self, curve: Curve, index: int, on_moved,
                 on_drag_start=None, on_clicked=None,
                 on_snap=None, on_drag_end=None):
        super().__init__(-_R, -_R, 2 * _R, 2 * _R)
        self._curve          = curve
        self._index          = index
        self._on_moved       = on_moved
        self._on_drag_start  = on_drag_start
        self._on_clicked     = on_clicked
        self._on_snap        = on_snap    # (QPointF) -> QPointF; called during drag
        self._on_drag_end    = on_drag_end
        self._node_selected  = False
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(20)
        self.setPen(QPen(_geometry_color(), 1))
        self.setBrush(QBrush(_node_fill()))
        node = curve.nodes[index]
        self.setPos(node.x, node.y)

    @property
    def node_index(self) -> int:
        return self._index

    def set_node_selected(self, selected: bool):
        self._node_selected = selected
        self._apply_fill()

    def refresh_theme(self):
        self.setPen(QPen(_geometry_color(), 1))
        self._apply_fill()

    def _apply_fill(self):
        if self._node_selected:
            self.setBrush(QBrush(_node_selected()))
        else:
            self.setBrush(QBrush(_node_fill()))

    def hoverEnterEvent(self, event):
        if not self._node_selected:
            self.setBrush(QBrush(_node_hover()))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._apply_fill()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if self._on_clicked:
            self._on_clicked(self)
        if self._on_drag_start:
            self._on_drag_start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._on_drag_end:
            self._on_drag_end()
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionChange:
            if self._on_snap:
                return self._on_snap(value)
            return value
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            pos  = self.pos()
            node = self._curve.nodes[self._index]
            dx, dy = pos.x() - node.x, pos.y() - node.y
            if node.cp_in:
                node.cp_in  = ControlPoint(node.cp_in.x  + dx, node.cp_in.y  + dy)
            if node.cp_out:
                node.cp_out = ControlPoint(node.cp_out.x + dx, node.cp_out.y + dy)
            node.x, node.y = pos.x(), pos.y()
            self._on_moved(self._curve)
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        plain = QStyleOptionGraphicsItem(option)
        plain.state &= ~plain.state.State_Selected
        super().paint(painter, plain, widget)


# ---------- HandleDot ----------

_HR = 3


class HandleDot(QGraphicsEllipseItem):
    """Movable Bézier control-point handle shown when a spline is selected.

    smooth=True (default): moving this handle also moves the sibling handle
    symmetrically through the node — Fusion 360 "tangent lock" behaviour.
    Uses ItemIgnoresTransformations so it stays a constant screen size.
    """

    def __init__(self, curve: Curve, node_index: int, which: str, on_moved,
                 on_drag_start=None):
        super().__init__(-_HR, -_HR, 2 * _HR, 2 * _HR)
        self._curve         = curve
        self._node_index    = node_index
        self._which         = which        # "cp_in" or "cp_out"
        self._on_moved      = on_moved
        self._on_drag_start = on_drag_start
        self._updating      = False        # re-entrant guard for set_pos_silent
        self._sibling: "HandleDot | None" = None
        self._smooth        = True         # symmetric mode by default
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(19)
        self.setPen(QPen(_handle_color(), 1))
        self.setBrush(QBrush(_handle_fill()))
        cp = getattr(curve.nodes[node_index], which)
        if cp:
            self.setPos(cp.x, cp.y)

    def refresh_theme(self):
        self.setPen(QPen(_handle_color(), 1))
        self.setBrush(QBrush(_handle_fill()))

    def set_sibling(self, sibling: "HandleDot"):
        self._sibling = sibling

    def set_smooth(self, smooth: bool):
        self._smooth = smooth

    def set_pos_silent(self, x: float, y: float):
        """Reposition without triggering the data-model callback."""
        self._updating = True
        self.setPos(x, y)
        self._updating = False

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(_handle_hover()))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(_handle_fill()))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if self._on_drag_start:
            self._on_drag_start()
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if (change == self.GraphicsItemChange.ItemPositionHasChanged
                and not self._updating):
            pos  = self.pos()
            node = self._curve.nodes[self._node_index]
            setattr(node, self._which, ControlPoint(pos.x(), pos.y()))

            if self._smooth and self._sibling is not None:
                opp_x     = 2.0 * node.x - pos.x()
                opp_y     = 2.0 * node.y - pos.y()
                opp_which = "cp_in" if self._which == "cp_out" else "cp_out"
                setattr(node, opp_which, ControlPoint(opp_x, opp_y))
                self._sibling.set_pos_silent(opp_x, opp_y)

            self._on_moved(self._curve)
        return super().itemChange(change, value)
