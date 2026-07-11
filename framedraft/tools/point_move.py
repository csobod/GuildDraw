"""
PointMoveTool — translate selection by picking a "grab" point then a destination.

Workflow:
  1. With curves selected, press G (or toolbar button).
  2. Click the grab point — snaps to any snap target in the scene.
  3. Either:
     a. Click the destination (also snapped), or
     b. Edit the X / Y fields in the HUD and press Enter.
  4. Selection moves so that the grab point lands on the destination.
  Esc at any stage cancels.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, QPointF, Qt
from PySide6.QtGui  import QPen, QColor, QFont, QBrush
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QLineEdit

from .. import theme


_AMBER = "#ffd580"


class _PointMoveHud(QWidget):
    """Floating overlay shown in PICK_TO stage with X/Y destination fields."""

    def __init__(self, view):
        super().__init__(view)
        self._view      = view
        self._on_commit = None
        self._on_cancel = None

        self.setObjectName("pointMoveHud")
        self.setStyleSheet(theme.build_hud_qss("#pointMoveHud"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(4)

        lay.addWidget(QLabel("To:"))
        lay.addWidget(QLabel("X"))
        self._x = QLineEdit()
        self._x.setFixedWidth(68)
        self._x.setFont(QFont("Segoe UI", 10))
        self._x.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._x.setPlaceholderText("mm")
        lay.addWidget(self._x)
        lay.addWidget(QLabel("Y"))
        self._y = QLineEdit()
        self._y.setFixedWidth(68)
        self._y.setFont(QFont("Segoe UI", 10))
        self._y.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._y.setPlaceholderText("mm")
        lay.addWidget(self._y)
        hint = QLabel("↵ confirm  Tab switch  Esc cancel")
        hint.setFont(QFont("Segoe UI", 9))
        hint.setProperty("hudRole", "hint")
        lay.addWidget(hint)

        self._x.returnPressed.connect(self._commit)
        self._y.returnPressed.connect(self._commit)
        self.hide()

    def show_for(self, vp_x: int, vp_y: int, from_x: float, from_y: float,
                 on_commit, on_cancel) -> None:
        self.setStyleSheet(theme.build_hud_qss("#pointMoveHud"))
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self._x.setText(f"{from_x:.3f}")
        self._y.setText(f"{from_y:.3f}")
        self.adjustSize()
        pr = self._view.rect()
        x  = min(vp_x + 14, pr.width()  - self.width()  - 4)
        y  = max(4, vp_y - self.height() - 10)
        self.move(max(0, x), y)
        self.show()
        self.raise_()
        self._x.setFocus()
        self._x.selectAll()

    def update_hover(self, to_pt: QPointF) -> None:
        """Reflect hovered snap position in fields (only when neither field has focus)."""
        if not self._x.hasFocus() and not self._y.hasFocus():
            self._x.setText(f"{to_pt.x():.3f}")
            self._y.setText(f"{to_pt.y():.3f}")

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
            x = float(self._x.text().strip())
            y = float(self._y.text().strip())
        except (ValueError, TypeError):
            return
        if self._on_commit:
            self._on_commit(QPointF(x, y))
        self.hide()
        self._view.setFocus()


class PointMoveTool(QObject):
    """Two-click precise move: grab point → destination point (or typed coords)."""

    moved          = Signal(float, float)   # (dx_mm, dy_mm)
    status_message = Signal(str)
    cancelled      = Signal()

    _IDLE      = 0
    _PICK_FROM = 1
    _PICK_TO   = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene     = None
        self._view      = None
        self._snap      = None
        self._state     = self._IDLE
        self._from_pt:  QPointF | None = None
        self._grab_dot  = None   # amber dot at grab point
        self._rubber    = None   # dashed line from grab to cursor
        self._hud: _PointMoveHud | None = None

    # ------------------------------------------------------------------
    # Public interface (matches CanvasView draw-tool dispatch shape)
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._state != self._IDLE

    def activate(self, scene, view, snap_engine) -> None:
        self._clear_scene_items()
        self._scene    = scene
        self._view     = view
        self._snap     = snap_engine
        self._state    = self._PICK_FROM
        self._from_pt  = None
        if self._hud is None:
            self._hud = _PointMoveHud(view)
        self._hud.hide()
        self.status_message.emit(
            "Point Move: click the grab point on the selection  |  Esc to cancel"
        )

    def deactivate(self) -> None:
        self._clear_scene_items()
        if self._hud:
            self._hud.hide()
        # Hide the snap indicator — the last handle_press/handle_move left it
        # showing at the snapped point, and nothing else clears it (the "green
        # endpoint circle persists after a point-to-point move" bug).
        if self._snap:
            self._snap.hide()
        self._scene   = None
        self._view    = None
        self._snap    = None
        self._state   = self._IDLE
        self._from_pt = None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_press(self, pos: QPointF,
                     use_snap: bool = True,
                     constrain: bool = False) -> bool:
        if not self.active:
            return False
        if self._snap:
            pos = self._snap.snap(pos, [], self._view, use_snap)

        if self._state == self._PICK_FROM:
            self._from_pt = QPointF(pos)
            self._add_grab_dot(pos)
            self._state = self._PICK_TO
            vp = self._view.mapFromScene(pos)
            self._hud.show_for(
                vp.x(), vp.y(), pos.x(), pos.y(),
                on_commit = self._hud_commit,
                on_cancel = self._cancel,
            )
            self.status_message.emit(
                "Point Move: click destination or type X Y  |  Esc to cancel"
            )
            return True

        if self._state == self._PICK_TO:
            if self._hud:
                self._hud.hide()
            self._apply_move(pos)
            return True

        return False

    def handle_move(self, pos: QPointF,
                    use_snap: bool = True,
                    constrain: bool = False) -> None:
        if not self.active or self._snap is None:
            return
        snapped = self._snap.snap(pos, [], self._view, use_snap)
        if self._state == self._PICK_TO:
            self._update_rubber(snapped)
            if self._hud and self._hud.isVisible():
                self._hud.update_hover(snapped)

    def handle_dbl_click(self, pos: QPointF,
                          use_snap: bool = True,
                          constrain: bool = False) -> bool:
        return self.handle_press(pos, use_snap, constrain)

    def handle_key(self, key: int, text: str = "") -> bool:
        if not self.active:
            return False
        if key == Qt.Key.Key_Escape:
            self._cancel()
            return True
        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _hud_commit(self, to_pt: QPointF) -> None:
        self._apply_move(to_pt)

    def _apply_move(self, to_pt: QPointF) -> None:
        if self._from_pt is None:
            return
        dx = to_pt.x() - self._from_pt.x()
        dy = to_pt.y() - self._from_pt.y()
        self._clear_scene_items()
        self.moved.emit(dx, dy)

    def _cancel(self) -> None:
        self._clear_scene_items()
        if self._hud:
            self._hud.hide()
        self.status_message.emit("Point Move cancelled")
        self.cancelled.emit()

    def _add_grab_dot(self, pos: QPointF) -> None:
        R   = 5
        col = QColor(_AMBER)
        pen = QPen(col, 1.5)
        pen.setCosmetic(True)
        dot = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, pen, QBrush(col))
        dot.setPos(pos)
        dot.setFlag(dot.GraphicsItemFlag.ItemIgnoresTransformations, True)
        dot.setFlag(dot.GraphicsItemFlag.ItemIsSelectable, False)
        dot.setZValue(210)
        self._grab_dot = dot

    def _update_rubber(self, to_pt: QPointF) -> None:
        if self._from_pt is None:
            return
        if self._rubber is not None:
            self._scene.removeItem(self._rubber)
            self._rubber = None
        pen = QPen(QColor(_AMBER), 0)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        line = self._scene.addLine(
            self._from_pt.x(), self._from_pt.y(),
            to_pt.x(), to_pt.y(), pen,
        )
        line.setFlag(line.GraphicsItemFlag.ItemIsSelectable, False)
        line.setZValue(205)
        self._rubber = line

    def _clear_scene_items(self) -> None:
        for attr in ("_grab_dot", "_rubber"):
            item = getattr(self, attr, None)
            if item is not None:
                if self._scene:
                    try:
                        self._scene.removeItem(item)
                    except RuntimeError:
                        pass
                setattr(self, attr, None)
