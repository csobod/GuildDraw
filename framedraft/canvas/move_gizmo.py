"""
framedraft/canvas/move_gizmo.py

Move Gizmo — four cardinal arrow handles for translating selected geometry.

Arrow drag  → constrained move along that axis  (on_move(dx_mm, dy_mm))
Arrow click → _MoveHud overlay for exact distance input
"""
import math
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QFont
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsEllipseItem,
    QWidget, QHBoxLayout, QLabel, QLineEdit,
)

_ARROW_LEN  = 30   # px, shaft from gap-start to tip
_ARROW_GAP  = 8    # px, gap from center to shaft start
_ARROW_HEAD = 8    # px, arrowhead length
_ARROW_W    = 4    # px, arrowhead half-width
_CENTER_R   = 4    # px, center dot radius
_DRAG_THRESHOLD_PX = 4.0

_COL_X_NORMAL = "#e74c3c"   # red for ±X arrows
_COL_Y_NORMAL = "#27ae60"   # green for ±Y arrows
_COL_HOVER    = "#ffd580"   # amber hover (both axes)


def _arrow_path(dx: int, dy: int) -> QPainterPath:
    """Shaft + open arrowhead for direction (dx, dy), each ±1 or 0."""
    path = QPainterPath()
    x0, y0 = dx * _ARROW_GAP,               dy * _ARROW_GAP
    xt, yt = dx * (_ARROW_GAP + _ARROW_LEN), dy * (_ARROW_GAP + _ARROW_LEN)
    path.moveTo(x0, y0)
    path.lineTo(xt, yt)
    if dx != 0:   # horizontal
        path.moveTo(xt, yt)
        path.lineTo(xt - dx * _ARROW_HEAD, yt - _ARROW_W)
        path.moveTo(xt, yt)
        path.lineTo(xt - dx * _ARROW_HEAD, yt + _ARROW_W)
    else:         # vertical
        path.moveTo(xt, yt)
        path.lineTo(xt - _ARROW_W, yt - dy * _ARROW_HEAD)
        path.moveTo(xt, yt)
        path.lineTo(xt + _ARROW_W, yt - dy * _ARROW_HEAD)
    return path


# ---------------------------------------------------------------------------
# Arrow item
# ---------------------------------------------------------------------------

class _ArrowItem(QGraphicsPathItem):
    """One gizmo arrow. Constant screen-size via ItemIgnoresTransformations."""

    def __init__(self, dx: int, dy: int, view, color_normal: str,
                 on_pre_move, on_move, on_click):
        super().__init__(_arrow_path(dx, dy))
        self._dx          = dx
        self._dy          = dy
        self._view        = view
        self._on_pre_move = on_pre_move    # () -> None, once per drag session
        self._on_move     = on_move        # (dx_mm, dy_mm) -> None
        self._on_click    = on_click       # (dx_dir, dy_dir) -> None

        self._dragging     = False
        self._drag_started = False
        self._press_scene  = QPointF()
        self._last_scene   = QPointF()

        self._pen_n = QPen(QColor(color_normal), 2.0)
        self._pen_n.setCosmetic(True)
        self._pen_n.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._pen_h = QPen(QColor(_COL_HOVER), 2.5)
        self._pen_h.setCosmetic(True)
        self._pen_h.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(self._pen_n)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

        self.setFlag(self.GraphicsItemFlag.ItemIsMovable,    False)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(200)

    def hoverEnterEvent(self, event):
        self.setPen(self._pen_h)
        self.setCursor(Qt.CursorShape.SizeHorCursor if self._dy == 0
                       else Qt.CursorShape.SizeVerCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(self._pen_n)
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self._dragging     = False
        self._drag_started = False
        self._press_scene  = event.scenePos()
        self._last_scene   = event.scenePos()
        event.accept()

    def mouseMoveEvent(self, event):
        cur = event.scenePos()
        if not self._dragging:
            vp_press = self._view.mapFromScene(self._press_scene)
            vp_cur   = self._view.mapFromScene(cur)
            dist = math.hypot(vp_cur.x() - vp_press.x(),
                              vp_cur.y() - vp_press.y())
            if dist < _DRAG_THRESHOLD_PX:
                event.accept()
                return
            self._dragging = True
        if not self._drag_started:
            self._drag_started = True
            self._on_pre_move()
        dx_mm = (cur.x() - self._last_scene.x()) if self._dx != 0 else 0.0
        dy_mm = (cur.y() - self._last_scene.y()) if self._dy != 0 else 0.0
        self._last_scene = cur
        self._on_move(dx_mm, dy_mm)
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self._dragging:
            self._on_click(self._dx, self._dy)
        self._dragging     = False
        self._drag_started = False
        event.accept()


# ---------------------------------------------------------------------------
# Distance-input HUD
# ---------------------------------------------------------------------------

class _MoveHud(QWidget):
    """Distance-entry overlay parented to CanvasView, shown on arrow click."""

    _STYLE = (
        "_MoveHud { background: rgba(20,20,20,220); border: 1px solid #e67e22; "
        "border-radius: 4px; }"
        "QLabel { color: #e0e0e0; }"
        "QLineEdit { background: rgba(45,45,45,230); color: #f0f0f0; "
        "border: 1px solid #606060; border-radius: 3px; padding: 2px 5px; }"
        "QLineEdit:focus { border-color: #ffd580; color: #ffffff; }"
    )

    def __init__(self, view):
        super().__init__(view)
        self._view     = view
        self._dx_dir   = 0
        self._dy_dir   = 0
        self._on_commit = None
        self._on_cancel = None

        self.setStyleSheet(self._STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(5)

        self._label = QLabel("Move:")
        self._label.setFont(QFont("Segoe UI", 10))
        self._edit = QLineEdit()
        self._edit.setFixedWidth(72)
        self._edit.setFont(QFont("Segoe UI", 10))
        self._edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._edit.setPlaceholderText("mm")
        hint = QLabel("mm  ↵ confirm  Esc cancel")
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet("color: #888888;")
        layout.addWidget(self._label)
        layout.addWidget(self._edit)
        layout.addWidget(hint)

        self._edit.returnPressed.connect(self._commit)
        self.hide()

    def show_for(self, dx_dir: int, dy_dir: int, vp_x: int, vp_y: int,
                 on_commit, on_cancel):
        self._dx_dir    = dx_dir
        self._dy_dir    = dy_dir
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        axis = "X" if dy_dir == 0 else "Y"
        self._label.setText(f"Move {axis}:")
        self._edit.clear()
        self.adjustSize()
        pr = self._view.rect()
        x  = min(vp_x + 14, pr.width()  - self.width()  - 4)
        y  = max(4, vp_y - self.height() - 10)
        self.move(x, y)
        self.show()
        self.raise_()
        self._edit.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            if self._on_cancel:
                self._on_cancel()
            self._view.setFocus()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _commit(self):
        try:
            dist = float(self._edit.text().strip())
        except (ValueError, TypeError):
            return
        if self._on_commit:
            self._on_commit(dist * self._dx_dir, dist * self._dy_dir)
        self.hide()
        self._view.setFocus()


# ---------------------------------------------------------------------------
# MoveGizmo
# ---------------------------------------------------------------------------

class MoveGizmo:
    """Four-arrow move gizmo in the scene.

    Arrow drag  → on_pre_move() then on_move(dx, dy) per frame
    Arrow click → _MoveHud for exact distance; on_pre_move() + on_move() on confirm
    """

    def __init__(self, scene, view, center: QPointF, on_pre_move, on_move):
        self._scene       = scene
        self._view        = view
        self._center      = QPointF(center)
        self._on_pre_move = on_pre_move
        self._on_move     = on_move
        self._arrows: list[_ArrowItem] = []
        self._center_item = None

        for dx, dy in ((1, 0), (-1, 0), (0, -1), (0, 1)):
            color = _COL_X_NORMAL if dy == 0 else _COL_Y_NORMAL
            arrow = _ArrowItem(dx, dy, view, color,
                               on_pre_move = on_pre_move,
                               on_move     = on_move,
                               on_click    = self._on_arrow_click)
            scene.addItem(arrow)
            self._arrows.append(arrow)

        R   = _CENTER_R
        dot = QGraphicsEllipseItem(-R, -R, 2 * R, 2 * R)
        dot.setFlag(dot.GraphicsItemFlag.ItemIgnoresTransformations, True)
        dot.setFlag(dot.GraphicsItemFlag.ItemIsSelectable, False)
        pen = QPen(QColor("#e67e22"), 1.5)
        pen.setCosmetic(True)
        dot.setPen(pen)
        dot.setBrush(QBrush(QColor("#ffd580")))
        dot.setZValue(200)
        scene.addItem(dot)
        self._center_item = dot

        self._hud = _MoveHud(view)
        self.set_center(center)

    def set_center(self, pos: QPointF):
        self._center = QPointF(pos)
        for arrow in self._arrows:
            arrow.setPos(pos)
        if self._center_item:
            self._center_item.setPos(pos)

    def _on_arrow_click(self, dx_dir: int, dy_dir: int):
        vp = self._view.mapFromScene(self._center)
        self._hud.show_for(
            dx_dir, dy_dir, vp.x(), vp.y(),
            on_commit = self._hud_commit,
            on_cancel = lambda: None,
        )

    def _hud_commit(self, dx_mm: float, dy_mm: float):
        self._on_pre_move()
        self._on_move(dx_mm, dy_mm)

    def remove(self):
        if hasattr(self, "_hud") and self._hud:
            self._hud.hide()
            self._hud.deleteLater()
            self._hud = None
        for arrow in self._arrows:
            self._scene.removeItem(arrow)
        if self._center_item:
            self._scene.removeItem(self._center_item)
        self._arrows.clear()
        self._center_item = None
