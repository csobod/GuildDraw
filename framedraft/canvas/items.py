import math
import os

from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsEllipseItem, QStyleOptionGraphicsItem
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QPainterPathStroker
from PySide6.QtCore import Qt

from ..document import Curve, Layer, ControlPoint
from .. import theme


# ---------- drag flight recorder (M32.3) ----------
# Ships DISABLED. Set GUILDDRAW_DRAG_LOG=1 to log every node/handle drag step
# and dump context on any anomalous single-event jump (> ~40 screen px), so a
# residual "fly-away" report becomes diagnosable instead of "can't reproduce".
_DRAG_LOG = os.environ.get("GUILDDRAW_DRAG_LOG", "") not in ("", "0", "false", "False")


def _record_drag_step(kind: str, layer, prev, target, event) -> None:
    import sys
    dx, dy = target[0] - prev[0], target[1] - prev[1]
    jump_mm = math.hypot(dx, dy)
    view = None
    w = event.widget()
    if w is not None:
        view = w.parentWidget()
    scale = 1.0
    if view is not None and hasattr(view, "transform"):
        m = abs(view.transform().m11())
        if m > 1e-9:
            scale = m
    jump_px = jump_mm * scale
    sp = event.scenePos()
    print(f"[draglog] {kind} layer={getattr(layer, 'value', layer)} "
          f"step={jump_mm:.3f}mm ({jump_px:.1f}px) "
          f"scenePos=({sp.x():.2f},{sp.y():.2f})", file=sys.stderr)
    if jump_px > 40.0:
        hb = view.horizontalScrollBar().value() if view is not None else "?"
        vb = view.verticalScrollBar().value() if view is not None else "?"
        print(f"[draglog] !! JUMP >40px scale={scale:.4f} "
              f"hbar={hb} vbar={vb} prev={prev} target={target}", file=sys.stderr)

# ---------- theme colour functions ----------
# All colors resolve through framedraft.theme (the single palette source);
# these wrappers just add the QColor and keep call sites short.


def set_dark_mode(dark: bool) -> None:
    theme.set_dark(dark)


def _geometry_color() -> QColor:
    return QColor(theme.color("geometry.ink"))

def _handle_color() -> QColor:
    return QColor(theme.color("geometry.handle"))

def _handle_fill() -> QColor:
    return QColor(theme.color("geometry.handle_fill"))

def _handle_hover() -> QColor:
    return QColor(theme.color("geometry.handle"))

def _node_fill() -> QColor:
    return QColor(theme.color("geometry.node_fill"))

def _node_hover() -> QColor:
    return QColor(theme.color("geometry.node_hover"))

def _selection_halo_color() -> QColor:
    # Bright, semi-transparent glow drawn behind a selected curve (#AARRGGBB).
    return QColor(theme.color("canvas.selection_halo"))


# ---------- per-layer pen factory ----------
# All pens are cosmetic (constant screen width regardless of zoom).


def _layer_pen(layer: Layer, line_weight: float | None = None) -> QPen:
    pen = QPen(QColor(theme.layer_color(layer)))
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

def _node_selected() -> QColor:
    return QColor(theme.color("geometry.node_selected"))


class NodeDot(QGraphicsEllipseItem):
    """Movable on-curve node shown when a CurveItem is selected.

    Uses ItemIgnoresTransformations so it stays a constant screen size
    regardless of zoom level. Size comes from theme.dot_radius() at
    construction (dots rebuild on selection, so a changed preference
    applies the next time a curve is selected).
    """

    def __init__(self, curve: Curve, index: int, on_moved,
                 on_drag_start=None, on_clicked=None,
                 on_snap=None, on_drag_end=None):
        R = theme.dot_radius()
        super().__init__(-R, -R, 2 * R, 2 * R)
        self._curve          = curve
        self._index          = index
        self._on_moved       = on_moved
        self._on_drag_start  = on_drag_start
        self._on_clicked     = on_clicked
        self._on_snap        = on_snap    # (QPointF) -> QPointF; called during drag
        self._on_drag_end    = on_drag_end
        self._node_selected  = False
        # Explicit scene-coordinate drag state (see mousePressEvent). We do NOT
        # use ItemIsMovable: Qt's built-in movable drag re-derives the step
        # through the view's CURRENT device transform, so a mid-drag zoom/pan
        # (a grazed wheel tick, touchpad inertia, middle-button pan) poisoned
        # the reference and sent the dot flying toward the anchor — the M32
        # "fly-away" report. scenePos()-based dragging is transform-independent.
        self._drag_active = False
        self._grab_dx     = 0.0
        self._grab_dy     = 0.0
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(20)
        self.setPen(QPen(_geometry_color(), 1))
        self.setBrush(QBrush(_node_fill()))
        node = curve.nodes[index]
        self.setPos(node.x, node.y)
        # Enable geometry-change notifications only AFTER the initial placement.
        # Otherwise this constructor setPos fires itemChange(ItemPositionChange)
        # → the endpoint-snap callback, which would yank the freshly-shown node
        # onto a nearby endpoint the moment the curve is selected (and off the
        # undo stack, since no drag began). Snap must only run during a real drag.
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)

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
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._on_clicked:
            self._on_clicked(self)
        if self._on_drag_start:
            self._on_drag_start()
        # Grab offset in SCENE coords: the node keeps its position relative to
        # the cursor for the whole drag, whatever the view transform does.
        gp = event.scenePos()
        self._grab_dx = self.pos().x() - gp.x()
        self._grab_dy = self.pos().y() - gp.y()
        self._drag_active = True
        event.accept()   # become the mouse grabber (no ItemIsMovable to do it)

    def mouseMoveEvent(self, event):
        if not self._drag_active:
            event.ignore()
            return
        gp = event.scenePos()
        tx, ty = gp.x() + self._grab_dx, gp.y() + self._grab_dy
        if _DRAG_LOG:
            _record_drag_step("node", self._curve.layer,
                              (self.pos().x(), self.pos().y()), (tx, ty), event)
        # setPos fires itemChange → snap adjustment + model commit (below).
        self.setPos(tx, ty)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        if self._on_drag_end:
            self._on_drag_end()
        event.accept()

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


class HandleDot(QGraphicsEllipseItem):
    """Movable Bézier control-point handle shown when a spline is selected.

    smooth=True (default): moving this handle also moves the sibling handle
    symmetrically through the node — Fusion 360 "tangent lock" behaviour.
    Uses ItemIgnoresTransformations so it stays a constant screen size;
    drawn one px smaller than node dots so the two read differently.
    """

    def __init__(self, curve: Curve, node_index: int, which: str, on_moved,
                 on_drag_start=None):
        HR = max(2, theme.dot_radius() - 1)
        super().__init__(-HR, -HR, 2 * HR, 2 * HR)
        self._curve         = curve
        self._node_index    = node_index
        self._which         = which        # "cp_in" or "cp_out"
        self._on_moved      = on_moved
        self._on_drag_start = on_drag_start
        self._updating      = False        # re-entrant guard for set_pos_silent
        self._sibling: "HandleDot | None" = None
        self._smooth        = True         # symmetric mode by default
        # Explicit scene-coordinate drag state (mirrors NodeDot — no
        # ItemIsMovable, so a mid-drag zoom/pan can't send the handle flying).
        self._drag_active = False
        self._grab_dx     = 0.0
        self._grab_dy     = 0.0
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(19)
        self.setPen(QPen(_handle_color(), 1))
        self.setBrush(QBrush(_handle_fill()))
        cp = getattr(curve.nodes[node_index], which)
        if cp:
            self.setPos(cp.x, cp.y)
        # Enable change notifications only after the initial placement so this
        # constructor setPos doesn't fire itemChange → a redundant model write
        # and refresh at selection time (mirrors NodeDot above).
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)

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
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._on_drag_start:
            self._on_drag_start()
        gp = event.scenePos()
        self._grab_dx = self.pos().x() - gp.x()
        self._grab_dy = self.pos().y() - gp.y()
        self._drag_active = True
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._drag_active:
            event.ignore()
            return
        gp = event.scenePos()
        tx, ty = gp.x() + self._grab_dx, gp.y() + self._grab_dy
        if _DRAG_LOG:
            _record_drag_step("handle", self._curve.layer,
                              (self.pos().x(), self.pos().y()), (tx, ty), event)
        self.setPos(tx, ty)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        event.accept()

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
