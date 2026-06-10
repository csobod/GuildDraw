import math
from PySide6.QtCore import QObject, Signal, QPointF, Qt
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QFont
from PySide6.QtWidgets import QLabel

from ..document import Curve, Layer, SplineNode
from ..canvas.items import build_path
from ..geometry import mirror_curve, compute_catmull_handles  # noqa: F401 — re-exported for app.py

# Layers that show a live mirror ghost while drawing
_MIRROR_GHOST_LAYERS = {Layer.LENS, Layer.HINGE, Layer.OUTLINE}


class _LengthHud(QLabel):
    """Floating HUD near the cursor — shows length and angle with cursor indicator."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFont(QFont("Segoe UI", 10))
        self.hide()

    def update_at(self, text: str, any_locked: bool, vp_x: int, vp_y: int):
        self.setText(text)
        if any_locked:
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


class DrawTool(QObject):
    """Handles line and spline drawing, one curve at a time."""

    curve_added    = Signal(object)   # Curve
    status_message = Signal(str)

    _CLOSE_PX = 12  # screen-pixel radius to snap-close a path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kind  = "line"
        self._layer = Layer.OUTLINE
        self._nodes: list[SplineNode] = []
        self._preview: list = []
        self._scene = None
        self._view  = None
        self._snap  = None
        self._locked_len:   float | None = None
        self._len_input:    str = ""
        self._locked_angle: float | None = None
        self._angle_input:  str = ""
        self._active_field: str = "length"   # "length" | "angle"
        self._last_cursor:  QPointF = QPointF()
        self._hud: _LengthHud | None = None

    @property
    def active(self) -> bool:
        return self._scene is not None

    def set_layer(self, layer: Layer):
        self._layer = layer

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate(self, kind: str, layer: Layer, scene, view, snap=None,
                all_curves=None, measure_bar=None):
        self._clear_preview()
        if self._hud:
            self._hud.deleteLater()
            self._hud = None
        self._kind  = kind
        self._layer = layer
        self._nodes.clear()
        self._scene = scene
        self._view  = view
        self._snap  = snap
        self._locked_len   = None
        self._len_input    = ""
        self._locked_angle = None
        self._angle_input  = ""
        self._active_field = "length"
        if snap is not None:
            snap.set_doc_curves(all_curves or [])
        if view is not None:
            self._hud = _LengthHud(view)
        self.status_message.emit(
            f"Draw {kind}:  click to place nodes  |  "
            f"type length  →  Tab for angle  |  Shift=45° snap  |  "
            f"double-click or Enter to finish  |  Esc to cancel"
        )

    def deactivate(self):
        self._clear_preview()
        self._nodes.clear()
        if self._snap:
            self._snap.hide()
        if self._hud:
            self._hud.deleteLater()
            self._hud = None
        self._locked_len   = None
        self._len_input    = ""
        self._locked_angle = None
        self._angle_input  = ""
        self._active_field = "length"
        self._scene = None
        self._view  = None
        self._snap  = None

    # ------------------------------------------------------------------
    # Event handlers (called by CanvasView)
    # ------------------------------------------------------------------

    def handle_press(self, pos: QPointF, use_snap: bool = True,
                     constrain: bool = False) -> bool:
        if not self.active:
            return False
        if self._snap:
            pos = self._snap.snap(pos, self._nodes, self._view, use_snap)
        if constrain and self._nodes:
            pos = self._constrain_cardinal(pos, self._nodes[-1])
        if self._nodes and (self._locked_len is not None or self._locked_angle is not None):
            pos = self._apply_polar_constraints(pos, self._nodes[-1])
        if len(self._nodes) >= 2 and self._near_first(pos):
            self._finish(closed=True)
        else:
            self._nodes.append(SplineNode(x=pos.x(), y=pos.y()))
            self._clear_constraints()
            self._repaint(pos)
        return True

    def handle_move(self, pos: QPointF, use_snap: bool = True,
                    constrain: bool = False):
        if not self.active:
            return
        if self._snap:
            pos = self._snap.snap(pos, self._nodes, self._view, use_snap)
        if constrain and self._nodes:
            pos = self._constrain_cardinal(pos, self._nodes[-1])
        if self._nodes and (self._locked_len is not None or self._locked_angle is not None):
            pos = self._apply_polar_constraints(pos, self._nodes[-1])
        self._last_cursor = pos
        if self._nodes:
            self._repaint(pos)

    def handle_dbl_click(self, pos: QPointF, use_snap: bool = True,
                         constrain: bool = False) -> bool:
        if not self.active:
            return False
        if self._snap:
            pos = self._snap.snap(pos, self._nodes, self._view, use_snap)
        if constrain and self._nodes:
            pos = self._constrain_cardinal(pos, self._nodes[-1])
        if self._nodes:
            self._nodes.pop()   # undo the node placed by the preceding single-click
        self._finish(closed=False)
        return True

    def handle_key(self, key, text: str = "") -> bool:
        if not self.active:
            return False

        # Tab: toggle active field (length ↔ angle); only useful once a node is placed
        if key == Qt.Key.Key_Tab and self._nodes:
            self._active_field = "angle" if self._active_field == "length" else "length"
            self._repaint(self._last_cursor)
            return True

        # Digit / decimal → active input field
        if self._nodes and text and (text.isdigit() or text == '.'):
            if self._active_field == "length":
                if text == '.' and '.' in self._len_input:
                    return True
                self._len_input += text
                self._update_locked_len()
            else:
                if text == '.' and '.' in self._angle_input:
                    return True
                self._angle_input += text
                self._update_locked_angle()
            self._repaint(self._last_cursor)
            return True

        # Backspace: delete from active field; undo last node if field is empty
        if key == Qt.Key.Key_Backspace and self._nodes:
            if self._active_field == "length" and self._len_input:
                self._len_input = self._len_input[:-1]
                self._update_locked_len()
                self._repaint(self._last_cursor)
                return True
            if self._active_field == "angle" and self._angle_input:
                self._angle_input = self._angle_input[:-1]
                self._update_locked_angle()
                self._repaint(self._last_cursor)
                return True
            return self.undo_last_point()

        # Enter: place constrained node when locked; finish curve when nothing locked
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._nodes and (self._locked_len is not None or self._locked_angle is not None):
                pos = self._apply_polar_constraints(self._last_cursor, self._nodes[-1])
                self._nodes.append(SplineNode(x=pos.x(), y=pos.y()))
                self._clear_constraints()
                self._repaint(self._last_cursor)
            elif self._nodes:
                self._finish(closed=False)
            return True

        # Escape: clear active field → other field → cancel drawing
        if key == Qt.Key.Key_Escape:
            if self._active_field == "length" and self._len_input:
                self._len_input = ""
                self._locked_len = None
                self._repaint(self._last_cursor)
                return True
            if self._active_field == "angle" and self._angle_input:
                self._angle_input = ""
                self._locked_angle = None
                self._repaint(self._last_cursor)
                return True
            if self._len_input or self._angle_input:
                self._clear_constraints()
                self._repaint(self._last_cursor)
                return True
            self.deactivate()
            self.status_message.emit("Draw cancelled")
            return True

        return False

    def undo_last_point(self) -> bool:
        """Remove the last placed node during an in-progress draw operation."""
        if not self.active or not self._nodes:
            return False
        self._nodes.pop()
        self._clear_preview()
        if self._nodes:
            last = self._nodes[-1]
            self._repaint(QPointF(last.x, last.y))
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _clear_constraints(self):
        self._locked_len   = None
        self._len_input    = ""
        self._locked_angle = None
        self._angle_input  = ""
        self._active_field = "length"

    def _update_locked_len(self):
        try:
            v = float(self._len_input) if self._len_input else None
            self._locked_len = v if (v is not None and v > 0) else None
        except ValueError:
            self._locked_len = None

    def _update_locked_angle(self):
        try:
            v = float(self._angle_input) if self._angle_input else None
            self._locked_angle = v   # any angle is valid, including 0°
        except ValueError:
            self._locked_angle = None

    def _apply_polar_constraints(self, pos: QPointF, from_node: SplineNode) -> QPointF:
        """Constrain pos to the active length and/or angle locks relative to from_node."""
        dx = pos.x() - from_node.x
        dy = pos.y() - from_node.y
        dist  = math.hypot(dx, dy)
        angle = math.atan2(dy, dx)

        if self._locked_angle is not None:
            angle = math.radians(self._locked_angle)
            ray_dx, ray_dy = math.cos(angle), math.sin(angle)
            # Project cursor onto the angle ray; clamp to prevent negative distances
            dist = max(0.001, dx * ray_dx + dy * ray_dy)

        if self._locked_len is not None:
            dist = self._locked_len

        dist = max(0.001, dist)
        return QPointF(from_node.x + dist * math.cos(angle),
                       from_node.y + dist * math.sin(angle))

    def _constrain_cardinal(self, pos: QPointF, from_node: SplineNode) -> QPointF:
        """Snap pos to the nearest 45° increment from from_node."""
        dx   = pos.x() - from_node.x
        dy   = pos.y() - from_node.y
        dist = math.hypot(dx, dy)
        if dist < 0.001:
            return pos
        angle         = math.atan2(dy, dx)
        snapped_angle = round(angle / (math.pi / 4)) * (math.pi / 4)
        return QPointF(
            from_node.x + dist * math.cos(snapped_angle),
            from_node.y + dist * math.sin(snapped_angle),
        )

    def _near_first(self, pos: QPointF) -> bool:
        if not self._view:
            return False
        first = self._nodes[0]
        sp = self._view.mapFromScene(QPointF(first.x, first.y))
        cp = self._view.mapFromScene(pos)
        return math.hypot(cp.x() - sp.x(), cp.y() - sp.y()) < self._CLOSE_PX

    def _finish(self, closed: bool):
        if len(self._nodes) < 2:
            self.deactivate()
            self.status_message.emit("Need at least 2 points — cancelled")
            return
        curve = Curve(
            kind=self._kind,
            layer=self._layer,
            nodes=list(self._nodes),
            closed=closed,
        )
        if self._kind == "spline":
            compute_catmull_handles(curve.nodes, closed=closed)
        self._clear_preview()
        self._nodes.clear()
        self._scene = None
        self._view  = None
        self.curve_added.emit(curve)

    def _clear_preview(self):
        if self._scene:
            for item in self._preview:
                try:
                    self._scene.removeItem(item)
                except Exception:
                    pass
        self._preview.clear()

    def _repaint(self, cursor: QPointF):
        self._clear_preview()
        if not self._scene or not self._nodes:
            return

        R         = 4   # screen-pixel radius for preview dots
        dot_pen   = QPen(QColor("#2e8b57"), 1)
        dot_brush = QBrush(QColor("#ffd580"))
        dot_pen.setCosmetic(True)

        # Node dots — ItemIgnoresTransformations keeps them constant screen size
        for nd in self._nodes:
            dot = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, dot_pen, dot_brush)
            dot.setPos(nd.x, nd.y)
            dot.setFlag(dot.GraphicsItemFlag.ItemIgnoresTransformations, True)
            dot.setZValue(101)
            self._preview.append(dot)

        # Close-snap ring on first node
        if len(self._nodes) >= 2 and self._near_first(cursor):
            fn       = self._nodes[0]
            ring_pen = QPen(QColor("#c0392b"), 1)
            ring_pen.setCosmetic(True)
            ring = self._scene.addEllipse(-R * 2, -R * 2, R * 4, R * 4, ring_pen)
            ring.setPos(fn.x, fn.y)
            ring.setFlag(ring.GraphicsItemFlag.ItemIgnoresTransformations, True)
            ring.setZValue(102)
            self._preview.append(ring)

        # Path preview (placed nodes + rubber-band to cursor)
        all_pts = list(self._nodes) + [SplineNode(x=cursor.x(), y=cursor.y())]

        if self._kind == "line":
            path = QPainterPath()
            path.moveTo(all_pts[0].x, all_pts[0].y)
            for pt in all_pts[1:]:
                path.lineTo(pt.x, pt.y)
            pen = QPen(QColor("#888888"), 0)
            pen.setStyle(Qt.PenStyle.DashLine)
            item = self._scene.addPath(path, pen)
        else:
            compute_catmull_handles(all_pts, closed=False)
            tmp  = Curve(kind="spline", layer=self._layer, nodes=all_pts, closed=False)
            pen  = QPen(QColor("#888888"), 0)
            item = self._scene.addPath(build_path(tmp), pen)

        item.setZValue(100)
        self._preview.append(item)

        # Mirror ghost (LENS / HINGE / OUTLINE layers, open curves only)
        mirror = getattr(self._scene, "mirror", None)
        if mirror and mirror.enabled and self._layer in _MIRROR_GHOST_LAYERS:
            tmp_src = Curve(kind=self._kind, layer=self._layer,
                            nodes=all_pts, closed=False)
            mpath = build_path(mirror_curve(
                tmp_src, mirror.x,
                horizontal=getattr(mirror, "_horizontal", False)))

            ghost_pen = QPen(QColor("#888888"), 0, Qt.PenStyle.DotLine)
            ghost     = self._scene.addPath(mpath, ghost_pen)
            ghost.setZValue(100)
            self._preview.append(ghost)

        self._update_hud(cursor)

    def _update_hud(self, cursor: QPointF):
        if not self._hud or not self._view or not self._nodes:
            if self._hud:
                self._hud.hide()
            return
        last = self._nodes[-1]
        dx = cursor.x() - last.x
        dy = cursor.y() - last.y
        dist      = math.hypot(dx, dy)
        angle_deg = math.degrees(math.atan2(dy, dx))
        any_locked = self._locked_len is not None or self._locked_angle is not None

        # Length field: input buffer with cursor when active; brackets when locked from other field
        if self._active_field == "length":
            len_text = (self._len_input + "_") if self._len_input else f"{dist:.2f}"
        elif self._locked_len is not None:
            len_text = f"[{self._locked_len:.2f}]"
        else:
            len_text = f"{dist:.2f}"

        # Angle field: input buffer with cursor when active; brackets when locked from other field
        if self._active_field == "angle":
            ang_text = (self._angle_input + "_") if self._angle_input else f"{angle_deg:.1f}"
        elif self._locked_angle is not None:
            ang_text = f"[{self._locked_angle:.1f}]"
        else:
            ang_text = f"{angle_deg:.1f}"

        text = f"{len_text} mm   {ang_text}°"
        vp = self._view.mapFromScene(cursor)
        self._hud.update_at(text, any_locked=any_locked, vp_x=vp.x(), vp_y=vp.y())
