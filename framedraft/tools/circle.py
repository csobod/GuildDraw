"""
CircleTool — handles circle and arc drawing.

Circle interaction:
  click 1 = place center
  click 2 = set radius (any point on the circle edge)
  → curve_added emitted; tool returns to idle

Arc interaction:
  click 1 = place center
  click 2 = set start point (also sets radius)
  click 3 = set end point (sweep from start to end, CW on screen)
  → curve_added emitted; tool returns to idle

Angle convention (stored in Curve.start_angle / end_angle):
  Computed as math.degrees(math.atan2(dy, dx)) in Qt scene space (Y-down).
  0° = right, 90° = visually down, 180° = left, 270° = visually up.
  build_path converts these to Qt arcTo convention by negating both angles.
"""

import math

from PySide6.QtCore import QObject, Signal, QPointF, Qt
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QFont
from PySide6.QtWidgets import QLabel

from ..document import Curve, Layer, SplineNode


class _RadiusHud(QLabel):
    """Floating HUD near the cursor showing live or typed radius."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFont(QFont("Segoe UI", 10))
        self.hide()

    def update_at(self, text: str, locked: bool, vp_x: int, vp_y: int):
        self.setText(text)
        if locked:
            self.setStyleSheet(
                "QLabel { background: rgba(30,100,220,210); color: #ffffff; "
                "border: 1px solid #6aacff; border-radius: 4px; padding: 2px 8px; }"
            )
        else:
            self.setStyleSheet(
                "QLabel { background: rgba(30,30,30,175); color: #e0e0e0; "
                "border: 1px solid #555; border-radius: 4px; padding: 2px 8px; }"
            )
        self.adjustSize()
        pr = self.parent().rect()
        x = min(vp_x + 18, pr.width()  - self.width()  - 4)
        y = min(vp_y + 18, pr.height() - self.height() - 4)
        self.move(max(0, x), max(0, y))
        self.show()
        self.raise_()


class CircleTool(QObject):
    """Handles circle and arc drawing, one primitive at a time."""

    curve_added    = Signal(object)   # Curve
    status_message = Signal(str)

    _MIN_RADIUS = 0.5   # mm — ignore radius attempts smaller than this

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kind:        str   = "circle"
        self._layer:       Layer = Layer.OUTLINE
        self._state:       int   = 0        # 0=idle, 1=center placed, 2=arc start placed
        self._center:      tuple | None = None   # (x, y) mm
        self._radius:      float = 0.0
        self._start_angle: float = 0.0
        self._scene  = None
        self._view   = None
        self._snap   = None
        self._preview: list = []
        self._measure_bar  = None   # MeasureBar overlay (set in activate)
        self._locked_radius: float | None = None   # numeric radius lock
        self._radius_input: str = ""               # live keyboard input buffer
        self._last_cursor: QPointF = QPointF()
        self._hud: _RadiusHud | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._scene is not None

    # ------------------------------------------------------------------
    # Activation / deactivation
    # ------------------------------------------------------------------

    def set_layer(self, layer: Layer):
        self._layer = layer

    def activate(self, kind: str, layer: Layer, scene, view,
                 snap=None, all_curves=None, measure_bar=None):
        self._clear_preview()
        if self._hud:
            self._hud.deleteLater()
            self._hud = None
        self._kind  = kind
        self._layer = layer
        self._state = 0
        self._center = None
        self._measure_bar   = measure_bar
        self._locked_radius = None
        self._radius_input  = ""
        self._last_cursor   = QPointF()
        self._scene = scene
        self._view  = view
        self._snap  = snap
        if snap is not None:
            snap.set_doc_curves(all_curves or [])
        if view is not None:
            self._hud = _RadiusHud(view)
        if kind == "circle":
            self.status_message.emit(
                "Circle: click to place center  |  Esc to cancel"
            )
        else:
            self.status_message.emit(
                "Arc: click to place center  |  Esc to cancel"
            )

    def deactivate(self):
        self._clear_preview()
        self._state  = 0
        self._center = None
        if self._snap:
            self._snap.hide()
        if self._measure_bar:
            self._measure_bar.hide_bar()
            self._measure_bar = None
        if self._hud:
            self._hud.deleteLater()
            self._hud = None
        self._locked_radius = None
        self._radius_input  = ""
        self._scene = None
        self._view  = None
        self._snap  = None

    # ------------------------------------------------------------------
    # Event handlers — same interface as DrawTool so CanvasView can reuse
    # ------------------------------------------------------------------

    def handle_press(self, pos: QPointF, use_snap: bool = True,
                     constrain: bool = False) -> bool:
        if not self.active:
            return False
        if self._snap:
            pos = self._snap.snap(pos, [], self._view, use_snap)

        if self._state == 0:
            self._center = (pos.x(), pos.y())
            self._state  = 1
            if self._measure_bar:
                self._measure_bar.show_radius()
            if self._kind == "circle":
                self.status_message.emit(
                    "Circle: click on the edge to set radius  |  type radius (mm) + Enter  |  Esc to cancel"
                )
            else:
                self.status_message.emit(
                    "Arc: click start point (sets radius)  |  type radius (mm) + Enter  |  Esc to cancel"
                )
            return True

        if self._state == 1:
            cx, cy = self._center
            r = self._locked_radius if self._locked_radius is not None \
                else math.hypot(pos.x() - cx, pos.y() - cy)
            self._locked_radius = None
            self._radius_input  = ""
            if r < self._MIN_RADIUS:
                self.status_message.emit(
                    f"Radius too small (< {self._MIN_RADIUS} mm) — try again"
                )
                return True
            if self._kind == "circle":
                if self._measure_bar:
                    self._measure_bar.hide_bar()
                    self._measure_bar = None
                self._emit_circle(r)
            else:
                self._radius      = r
                self._start_angle = math.degrees(math.atan2(pos.y() - cy, pos.x() - cx))
                self._state       = 2
                if self._measure_bar:
                    self._measure_bar.hide_bar()
                    self._measure_bar = None
                if self._hud:
                    self._hud.hide()
                self.status_message.emit(
                    "Arc: click end point to set sweep  |  Esc to cancel"
                )
            return True

        if self._state == 2:
            cx, cy    = self._center
            end_angle = math.degrees(math.atan2(pos.y() - cy, pos.x() - cx))
            sweep     = (end_angle - self._start_angle) % 360
            if sweep < 1.0:
                self.status_message.emit("Arc too small — try clicking further away")
                return True
            self._emit_arc(self._radius, self._start_angle, end_angle)
            return True

        return False

    def handle_move(self, pos: QPointF, use_snap: bool = True,
                    constrain: bool = False):
        if not self.active:
            return
        if self._snap:
            pos = self._snap.snap(pos, [], self._view, use_snap)
        self._last_cursor = pos
        if self._center is not None:
            self._repaint(pos)

    def handle_dbl_click(self, pos: QPointF, use_snap: bool = True,
                         constrain: bool = False) -> bool:
        # The single-click from the preceding mousePressEvent already advanced
        # state; handle_dbl_click arrives after the fact, so just treat it like
        # a regular press (it's a no-op if already finished).
        return self.handle_press(pos, use_snap, constrain)

    def handle_key(self, key, text: str = "") -> bool:
        if not self.active:
            return False

        # Radius input when center is placed (state 1)
        if self._state == 1:
            if text and (text.isdigit() or text == '.'):
                if text == '.' and '.' in self._radius_input:
                    return True
                self._radius_input += text
                self._update_locked_radius()
                self._repaint(self._last_cursor)
                return True
            if key == Qt.Key.Key_Backspace:
                if self._radius_input:
                    self._radius_input = self._radius_input[:-1]
                    self._update_locked_radius()
                    self._repaint(self._last_cursor)
                    return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._locked_radius is not None:
                    self.set_radius_and_advance(self._locked_radius)
                return True

        if key == Qt.Key.Key_Escape:
            if self._state == 1 and self._radius_input:
                self._radius_input  = ""
                self._locked_radius = None
                self._repaint(self._last_cursor)
                return True
            if self._state > 0:
                self._state -= 1
                if self._state == 0:
                    self._center = None
                    self._clear_preview()
                    label = "Circle" if self._kind == "circle" else "Arc"
                    self.status_message.emit(f"{label} cancelled")
                    self.deactivate()
                elif self._state == 1:
                    # Arc: went back from end-click to start-click; clear preview
                    self._clear_preview()
                    self.status_message.emit(
                        "Arc: click start point (sets radius)  |  Esc to cancel"
                    )
                return True
        return False

    # ------------------------------------------------------------------
    # Radius numeric input
    # ------------------------------------------------------------------

    def _update_locked_radius(self):
        try:
            v = float(self._radius_input) if self._radius_input else None
            self._locked_radius = v if (v is not None and v >= self._MIN_RADIUS) else None
        except ValueError:
            self._locked_radius = None

    def set_radius_and_advance(self, radius_mm: float):
        """
        Called by MainWindow when the MeasureBar emits commit_radius.

        Circle  — emits the circle immediately at the given radius.
        Arc     — locks the radius; the next click sets the start angle.
        """
        if self._state != 1 or not self._center:
            return
        if radius_mm < self._MIN_RADIUS:
            return
        if self._kind == "circle":
            if self._measure_bar:
                self._measure_bar.hide_bar()
                self._measure_bar = None
            self._emit_circle(radius_mm)
        else:
            self._locked_radius = radius_mm
            self.status_message.emit(
                f"Arc: radius locked at {radius_mm:.2f} mm — click start point  |  Esc to cancel"
            )
            if self._measure_bar:
                self._measure_bar.hide_bar()
                self._measure_bar = None

    # ------------------------------------------------------------------
    # Finish helpers
    # ------------------------------------------------------------------

    def _emit_circle(self, radius: float):
        cx, cy = self._center
        curve  = Curve(
            kind        = "circle",
            layer       = self._layer,
            nodes       = [SplineNode(x=cx, y=cy)],
            closed      = True,
            radius      = radius,
        )
        self._clear_preview()
        self._state  = 0
        self._center = None
        self._scene  = None
        self.curve_added.emit(curve)

    def _emit_arc(self, radius: float, start_angle: float, end_angle: float):
        cx, cy = self._center
        curve  = Curve(
            kind        = "arc",
            layer       = self._layer,
            nodes       = [SplineNode(x=cx, y=cy)],
            closed      = False,
            radius      = radius,
            start_angle = start_angle,
            end_angle   = end_angle,
        )
        self._clear_preview()
        self._state  = 0
        self._center = None
        self._scene  = None
        self.curve_added.emit(curve)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _repaint(self, cursor: QPointF):
        self._clear_preview()
        if not self._scene or not self._center:
            return

        cx, cy = self._center

        # Center dot
        R        = 4
        dot_pen  = QPen(QColor("#2e8b57"), 1)
        dot_pen.setCosmetic(True)
        dot_brush = QBrush(QColor("#ffd580"))
        c_dot = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, dot_pen, dot_brush)
        c_dot.setPos(cx, cy)
        c_dot.setFlag(c_dot.GraphicsItemFlag.ItemIgnoresTransformations, True)
        c_dot.setZValue(101)
        self._preview.append(c_dot)

        ghost_pen = QPen(QColor("#888888"), 0, Qt.PenStyle.DashLine)
        ghost_pen.setCosmetic(True)

        if self._state == 1:
            # Preview circle/arc at live radius (or locked/typed radius)
            live_r = math.hypot(cursor.x() - cx, cursor.y() - cy)
            r = self._locked_radius if self._locked_radius is not None else live_r
            if self._measure_bar:
                self._measure_bar.update_radius(r if r >= self._MIN_RADIUS else live_r)
            if self._hud and self._view:
                locked = self._radius_input != ""
                hud_text = (self._radius_input + "_") if locked else f"{live_r:.2f}"
                hud_text += " mm"
                vp = self._view.mapFromScene(cursor)
                self._hud.update_at(hud_text, locked=locked, vp_x=vp.x(), vp_y=vp.y())
            if r < self._MIN_RADIUS:
                return
            path = QPainterPath()
            path.addEllipse(cx - r, cy - r, 2 * r, 2 * r)
            item = self._scene.addPath(path, ghost_pen)
            item.setZValue(100)
            self._preview.append(item)

        elif self._state == 2:
            # Fixed radius; preview the arc to the current mouse position
            r         = self._radius
            end_angle = math.degrees(math.atan2(cursor.y() - cy, cursor.x() - cx))
            sweep     = (end_angle - self._start_angle) % 360
            if sweep < 0.001:
                sweep = 360

            # Full circle ghost (thin, very transparent)
            full_pen = QPen(QColor("#aaaaaa"), 0, Qt.PenStyle.DotLine)
            full_pen.setCosmetic(True)
            full_path = QPainterPath()
            full_path.addEllipse(cx - r, cy - r, 2 * r, 2 * r)
            full_item = self._scene.addPath(full_path, full_pen)
            full_item.setZValue(99)
            self._preview.append(full_item)

            # Arc preview
            sa_rad = math.radians(self._start_angle)
            arc_path = QPainterPath()
            arc_path.moveTo(cx + r * math.cos(sa_rad), cy + r * math.sin(sa_rad))
            arc_path.arcTo(cx - r, cy - r, 2 * r, 2 * r, -self._start_angle, -sweep)
            arc_item = self._scene.addPath(arc_path, ghost_pen)
            arc_item.setZValue(100)
            self._preview.append(arc_item)

            # Start-point dot
            sx, sy  = cx + r * math.cos(sa_rad), cy + r * math.sin(sa_rad)
            sp_dot  = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, dot_pen, dot_brush)
            sp_dot.setPos(sx, sy)
            sp_dot.setFlag(sp_dot.GraphicsItemFlag.ItemIgnoresTransformations, True)
            sp_dot.setZValue(101)
            self._preview.append(sp_dot)

    def _clear_preview(self):
        if self._scene:
            for item in self._preview:
                try:
                    self._scene.removeItem(item)
                except Exception:
                    pass
        self._preview.clear()
