"""FilletTool — round the corner where two connected lines meet with a tangent arc.

Workflow:
  1. Activate the tool.
  2. Click the first line, then the second line. They must meet (or nearly
     meet) at a shared corner.
  3. Type a radius (mm) and press Enter. The corner is replaced by a tangent
     arc and both line legs are trimmed back to the tangent points.
  4. The tool returns to idle so you can fillet another corner. Esc backs out.

Only straight ``line`` curves are filletable (endpieces and lug corners are the
target use). The tangent-arc math lives in ``geometry.fillet_lines`` (Qt-free,
tested).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal, QPointF, Qt, QRect
from PySide6.QtGui import QPen, QColor, QPainterPath

from ..canvas.items import CurveItem, curve_layer_locked
from ..document import Curve, SplineNode
from ..geometry import fillet_lines
from .circle import _RadiusHud


_HOVER_COLOR = "#ffd580"
_HOVER_WIDTH = 2.5
_HIT_TOL_PX  = 8
_CORNER_TOL_MM = 2.0    # how close the two picked line ends must be to be a corner


class FilletTool(QObject):
    """Persistent tool that fillets the corner between two connected lines."""

    fillet_applied = Signal(object, object, list)   # (line1, line2, [new_curves])
    status_message = Signal(str)
    cancelled      = Signal()

    _MIN_RADIUS = 0.1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = None
        self._view  = None
        self._curves_fn = None
        self._hover_item: CurveItem | None = None
        self._line1: Curve | None = None
        self._line2: Curve | None = None
        self._radius_input = ""
        self._hud: _RadiusHud | None = None
        self._preview: list = []
        self._last_cursor = QPointF()

    @property
    def active(self) -> bool:
        return self._scene is not None

    # ------------------------------------------------------------------

    def activate(self, scene, view, curves_fn):
        self._clear_hover()
        self._clear_preview()
        self._scene = scene
        self._view  = view
        self._curves_fn = curves_fn
        self._line1 = None
        self._line2 = None
        self._radius_input = ""
        if self._hud:
            self._hud.deleteLater()
        self._hud = _RadiusHud(view) if view is not None else None
        self.status_message.emit(
            "Fillet: click the first line  |  Esc to exit")

    def deactivate(self):
        self._clear_hover()
        self._clear_preview()
        if self._hud:
            self._hud.deleteLater()
            self._hud = None
        self._scene = None
        self._view  = None
        self._curves_fn = None
        self._line1 = None
        self._line2 = None
        self._radius_input = ""

    # ------------------------------------------------------------------
    # Event handlers (DrawTool-shaped for CanvasView dispatch)
    # ------------------------------------------------------------------

    def handle_press(self, pos: QPointF, use_snap: bool = True,
                     constrain: bool = False) -> bool:
        if not self.active:
            return False
        if self._line1 is None or self._line2 is None:
            item = self._item_at(pos)
            if item is None or item.curve.kind != "line":
                self.status_message.emit("Fillet: click a straight line")
                return True
            if self._line1 is None:
                self._line1 = item.curve
                self.status_message.emit(
                    "Fillet: click the second line  |  Esc to exit")
            elif item.curve is self._line1:
                self.status_message.emit("Fillet: pick a different second line")
            else:
                self._line2 = item.curve
                if self._corner() is None:
                    self.status_message.emit(
                        "Fillet: those lines don't share a corner "
                        f"(ends must be within {_CORNER_TOL_MM} mm) — start over")
                    self._line1 = self._line2 = None
                    return True
                self.status_message.emit(
                    "Fillet: type a radius (mm) and press Enter  |  Esc to cancel")
            self._clear_hover()
            return True
        return True

    def handle_move(self, pos: QPointF, use_snap: bool = True,
                    constrain: bool = False):
        if not self.active:
            return
        self._last_cursor = pos
        if self._line1 is None or self._line2 is None:
            item = self._item_at(pos)
            if item is not self._hover_item:
                self._clear_hover()
                self._hover_item = item
                if item and item.curve.kind == "line":
                    pen = QPen(QColor(_HOVER_COLOR), 0)
                    pen.setCosmetic(True)
                    pen.setWidthF(_HOVER_WIDTH)
                    item.setPen(pen)
            return
        self._repaint_preview()

    def handle_dbl_click(self, pos: QPointF, use_snap: bool = True,
                         constrain: bool = False) -> bool:
        return self.handle_press(pos, use_snap, constrain)

    def handle_key(self, key, text: str = "") -> bool:
        if not self.active:
            return False
        if key == Qt.Key.Key_Escape:
            if self._line2 is not None or self._line1 is not None:
                self._line1 = self._line2 = None
                self._radius_input = ""
                self._clear_preview()
                if self._hud:
                    self._hud.hide()
                self.status_message.emit(
                    "Fillet: click the first line  |  Esc to exit")
            else:
                self.status_message.emit("Fillet cancelled")
                self.cancelled.emit()
            return True

        if self._line1 is not None and self._line2 is not None:
            if text and (text.isdigit() or text == '.'):
                if text == '.' and '.' in self._radius_input:
                    return True
                self._radius_input += text
                self._repaint_preview()
                return True
            if key == Qt.Key.Key_Backspace:
                self._radius_input = self._radius_input[:-1]
                self._repaint_preview()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._commit()
                return True
        return False

    # ------------------------------------------------------------------
    # Fillet geometry
    # ------------------------------------------------------------------

    def _corner(self):
        """Return (corner_pt, far1, far2, i1, i2) or None.

        i1/i2 are the corner-end indices (0 or last) on line1/line2.
        far1/far2 are the adjacent nodes giving each leg's direction.
        """
        l1, l2 = self._line1, self._line2
        if l1 is None or l2 is None or len(l1.nodes) < 2 or len(l2.nodes) < 2:
            return None
        best = None
        for i1 in (0, len(l1.nodes) - 1):
            for i2 in (0, len(l2.nodes) - 1):
                a, b = l1.nodes[i1], l2.nodes[i2]
                d = math.hypot(a.x - b.x, a.y - b.y)
                if best is None or d < best[0]:
                    best = (d, i1, i2)
        d, i1, i2 = best
        if d > _CORNER_TOL_MM:
            return None
        a = l1.nodes[i1]
        b = l2.nodes[i2]
        corner = ((a.x + b.x) / 2, (a.y + b.y) / 2)
        far1 = l1.nodes[1] if i1 == 0 else l1.nodes[-2]
        far2 = l2.nodes[1] if i2 == 0 else l2.nodes[-2]
        return corner, (far1.x, far1.y), (far2.x, far2.y), i1, i2

    def _current_radius(self):
        try:
            r = float(self._radius_input) if self._radius_input else None
        except ValueError:
            return None
        if r is None or r < self._MIN_RADIUS:
            return None
        return r

    def _build_result(self, r: float):
        """Return [trimmed_line1, trimmed_line2, arc] or None."""
        info = self._corner()
        if info is None:
            return None
        corner, far1, far2, i1, i2 = info
        res = fillet_lines(corner, far1, far2, r)
        if res is None:
            return None
        t1, t2 = res["t1"], res["t2"]
        cx, cy = res["center"]

        new1 = self._trim_line(self._line1, i1, t1)
        new2 = self._trim_line(self._line2, i2, t2)
        arc = Curve(kind="arc", layer=self._line1.layer,
                    nodes=[SplineNode(x=cx, y=cy)], closed=False,
                    radius=r, start_angle=res["start_deg"],
                    end_angle=res["end_deg"],
                    line_weight=self._line1.line_weight)
        return [new1, new2, arc]

    @staticmethod
    def _trim_line(line: Curve, corner_idx: int, tangent: tuple) -> Curve:
        nodes = [SplineNode(x=n.x, y=n.y) for n in line.nodes]
        ci = corner_idx if corner_idx == 0 else len(nodes) - 1
        nodes[ci] = SplineNode(x=tangent[0], y=tangent[1])
        return Curve(kind="line", layer=line.layer, nodes=nodes,
                     closed=False, line_weight=line.line_weight)

    def _commit(self):
        r = self._current_radius()
        if r is None:
            self.status_message.emit("Fillet: enter a radius ≥ "
                                     f"{self._MIN_RADIUS} mm")
            return
        result = self._build_result(r)
        if result is None:
            self.status_message.emit(
                "Fillet: radius too large for these legs — try a smaller value")
            return
        l1, l2 = self._line1, self._line2
        self._clear_preview()
        if self._hud:
            self._hud.hide()
        self._line1 = self._line2 = None
        self._radius_input = ""
        self.fillet_applied.emit(l1, l2, result)
        self.status_message.emit(
            "Fillet applied  |  click two lines to fillet another  |  Esc to exit")

    # ------------------------------------------------------------------
    # Preview / hover
    # ------------------------------------------------------------------

    def _repaint_preview(self):
        self._clear_preview()
        if self._line1 is None or self._line2 is None or not self._scene:
            return
        r = self._current_radius()
        if self._hud and self._view:
            locked = bool(self._radius_input)
            txt = (self._radius_input + "_") if locked else "radius?"
            vp = self._view.mapFromScene(self._last_cursor)
            self._hud.update_at(txt + (" mm" if locked else ""),
                                locked=locked, vp_x=vp.x(), vp_y=vp.y())
        if r is None:
            return
        result = self._build_result(r)
        if result is None:
            return
        ghost = QPen(QColor("#2e8b57"), 0)
        ghost.setCosmetic(True)
        ghost.setWidthF(2.0)
        for c in result:
            path = QPainterPath()
            if c.kind == "line":
                path.moveTo(c.nodes[0].x, c.nodes[0].y)
                for n in c.nodes[1:]:
                    path.lineTo(n.x, n.y)
            else:
                cx, cy = c.nodes[0].x, c.nodes[0].y
                rr = c.radius
                sweep = (c.end_angle - c.start_angle) % 360
                if sweep < 0.001:
                    sweep = 360
                sa = math.radians(c.start_angle)
                path.moveTo(cx + rr * math.cos(sa), cy + rr * math.sin(sa))
                path.arcTo(cx - rr, cy - rr, 2 * rr, 2 * rr,
                           -c.start_angle, -sweep)
            item = self._scene.addPath(path, ghost)
            item.setZValue(100)
            self._preview.append(item)

    def _item_at(self, scene_pos: QPointF) -> CurveItem | None:
        if self._view is None:
            return None
        vp = self._view.mapFromScene(scene_pos)
        t = _HIT_TOL_PX
        candidates = self._view.items(QRect(vp.x() - t, vp.y() - t, 2 * t, 2 * t))
        return next((i for i in candidates
                     if isinstance(i, CurveItem) and not curve_layer_locked(i)),
                    None)

    def _clear_hover(self):
        if self._hover_item is not None:
            self._hover_item.refresh()
            self._hover_item = None

    def _clear_preview(self):
        if self._scene:
            for item in self._preview:
                try:
                    self._scene.removeItem(item)
                except Exception:
                    pass
        self._preview.clear()
