"""
OffsetTool — create a parallel curve at a fixed offset distance.

Workflow:
  1. Select exactly one curve in Select mode.
  2. Activate the Offset tool (toolbar button or O key).
  3. A floating HUD appears near the curve: "Offset: __ mm"
     Type a numeric distance (digits, minus sign, decimal point).
  4. The offset preview (amber) updates live as you type.
  5. Press Enter to confirm; Esc to cancel.

Positive d = left-hand normal (outward for CCW shapes).
Negative d = inward.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal, QPointF, Qt, QRect
from PySide6.QtGui  import QPen, QColor, QFont
from PySide6.QtWidgets import QLabel

from ..canvas.items import CurveItem


_PREVIEW_COLOR = "#ffd580"   # amber — same as hover/lock color used elsewhere
_PREVIEW_WIDTH = 2.0


class _OffsetHud(QLabel):
    """Floating label near the source curve that shows the typed offset distance."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFont(QFont("Segoe UI", 10))
        self.hide()

    def refresh(self, input_str: str, valid: bool) -> None:
        display = input_str if input_str else "—"
        self.setText(f"Offset: {display} mm")
        if valid:
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

    def position_near(self, vp_x: int, vp_y: int) -> None:
        if not self.parent():
            return
        pr = self.parent().rect()
        x = min(vp_x + 20, pr.width()  - self.width()  - 4)
        y = min(vp_y + 20, pr.height() - self.height() - 4)
        self.move(max(0, x), max(0, y))


class OffsetTool(QObject):
    """One-shot tool: type a distance, get a parallel curve."""

    offset_applied = Signal(object, object)   # (source_curve, offset_curve)
    status_message = Signal(str)
    cancelled      = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene         = None
        self._view          = None
        self._source_curve  = None   # Curve to offset
        self._preview_item: CurveItem | None = None
        self._input_str: str = ""
        self._hud: _OffsetHud | None = None

    # ------------------------------------------------------------------
    # Public interface (matches CanvasView draw-tool dispatch shape)
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._scene is not None

    def activate(self, scene, view, source_curve) -> None:
        """
        scene        : FrameScene
        view         : CanvasView
        source_curve : Curve to offset, or None (user must click one)
        """
        self._clear_preview()
        self._scene        = scene
        self._view         = view
        self._source_curve = source_curve
        self._input_str    = ""

        if self._hud is None:
            self._hud = _OffsetHud(view)

        if source_curve is not None:
            self._update_hud()
            self.status_message.emit(
                "Offset: type distance (mm) and press Enter  |  − for inward  |  Esc to cancel"
            )
        else:
            self._hud.hide()
            self.status_message.emit(
                "Offset: click a curve to select as offset source  |  Esc to cancel"
            )

    def deactivate(self) -> None:
        self._clear_preview()
        if self._hud:
            self._hud.hide()
        self._scene        = None
        self._view         = None
        self._source_curve = None
        self._input_str    = ""

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_press(self, pos: QPointF,
                     use_snap: bool = True,
                     constrain: bool = False) -> bool:
        if not self.active:
            return False
        if self._source_curve is None:
            item = self._item_at(pos)
            if item and not item.curve.mirrored:
                self._source_curve = item.curve
                self._update_hud()
                self.status_message.emit(
                    "Offset: type distance (mm) and press Enter  |  Esc to cancel"
                )
        return True

    def handle_move(self, pos: QPointF,
                    use_snap: bool = True,
                    constrain: bool = False) -> None:
        return

    def handle_dbl_click(self, pos: QPointF,
                          use_snap: bool = True,
                          constrain: bool = False) -> bool:
        return self.handle_press(pos, use_snap, constrain)

    def handle_key(self, key: int, text: str = "") -> bool:
        if not self.active:
            return False

        if key == Qt.Key.Key_Escape:
            if self._input_str:
                self._input_str = ""
                self._update_hud()
                self._clear_preview_item()
                return True
            self._clear_preview()
            self.status_message.emit("Offset cancelled")
            self.cancelled.emit()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._apply_offset()
            return True

        if key == Qt.Key.Key_Backspace:
            self._input_str = self._input_str[:-1]
            self._update_hud()
            self._update_preview()
            return True

        if text and text in "0123456789.-":
            # Guard against multiple dots or misplaced minus
            if text == "." and "." in self._input_str:
                return True
            if text == "-" and self._input_str:
                return True
            self._input_str += text
            self._update_hud()
            self._update_preview()
            return True

        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_d(self) -> float | None:
        try:
            v = float(self._input_str)
            return v
        except (ValueError, TypeError):
            return None

    def _update_hud(self) -> None:
        if not self._hud or not self._view or not self._source_curve:
            return
        d = self._parse_d()
        self._hud.refresh(self._input_str, d is not None and d != 0.0)

        # Position HUD near curve centroid
        c = self._source_curve
        if c.nodes:
            cx = sum(n.x for n in c.nodes) / len(c.nodes)
            cy = sum(n.y for n in c.nodes) / len(c.nodes)
            vp = self._view.mapFromScene(QPointF(cx, cy))
            self._hud.position_near(vp.x(), vp.y())
        self._hud.show()
        self._hud.raise_()

    def _update_preview(self) -> None:
        self._clear_preview_item()
        if not self._source_curve:
            return
        d = self._parse_d()
        if d is None or d == 0.0:
            return
        from ..geometry import offset_curve
        try:
            off_c = offset_curve(self._source_curve, d)
        except Exception:
            return
        item = CurveItem(off_c)
        pen = QPen(QColor(_PREVIEW_COLOR), 0)
        pen.setCosmetic(True)
        pen.setWidthF(_PREVIEW_WIDTH)
        item.setPen(pen)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, False)
        self._scene.addItem(item)
        self._preview_item = item

    def _clear_preview_item(self) -> None:
        if self._preview_item is not None:
            if self._scene:
                self._scene.removeItem(self._preview_item)
            self._preview_item = None

    def _clear_preview(self) -> None:
        self._clear_preview_item()

    def _apply_offset(self) -> None:
        if not self._source_curve:
            self.status_message.emit("Offset: no source curve — click one first")
            return
        d = self._parse_d()
        if d is None:
            self.status_message.emit("Offset: enter a valid distance (mm)")
            return
        if d == 0.0:
            self.status_message.emit("Offset: distance is zero — nothing to do")
            return
        from ..geometry import offset_curve
        try:
            off_c = offset_curve(self._source_curve, d)
        except Exception as exc:
            self.status_message.emit(f"Offset failed: {exc}")
            return
        self._clear_preview_item()
        self.offset_applied.emit(self._source_curve, off_c)

    def _item_at(self, scene_pos: QPointF) -> CurveItem | None:
        if self._view is None:
            return None
        vp = self._view.mapFromScene(scene_pos)
        t  = 8
        candidates = self._view.items(QRect(vp.x() - t, vp.y() - t, 2 * t, 2 * t))
        return next((i for i in candidates if isinstance(i, CurveItem)), None)
