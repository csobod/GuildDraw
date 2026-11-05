"""
OffsetTool — create a parallel curve at a fixed offset distance.

Workflow:
  1. Select exactly one curve in Select mode.
  2. Activate the Offset tool (toolbar button or O key).
  3. A floating HUD appears near the curve: "Offset: __ mm"
     Type a numeric distance (digits, minus sign, decimal point).
  4. The offset preview (amber) follows the typing, once it pauses.
  5. Press Enter to confirm; Esc to cancel.

On a closed shape positive d always grows it and negative shrinks it,
whichever way it was drawn; on an open curve positive is the left-hand
normal of the drawing direction.

A distance out of range for the curve (nothing of the shape left, or an
offset folding over itself too often to untangle) turns the HUD red with the
reason in the status bar, and Enter refuses it.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QObject, Signal, QPointF, Qt, QTimer
from PySide6.QtGui  import QPen, QColor, QFont
from PySide6.QtWidgets import QLabel

from ..canvas.items import CurveItem
from .trim import curve_item_at
from ..typed import typed_char


_PREVIEW_COLOR = "#ffd580"   # amber — same as hover/lock color used elsewhere
_PREVIEW_WIDTH = 2.0
# The preview waits for a pause in the typing: a large outline takes most of
# a second to offset, and "-12.5" was four offsets, the window frozen for each.
_PREVIEW_DELAY_MS = 150
_DENSE_NODES = 200            # the library's curves have 64 nodes at most
_FOLDS = "folds over itself"
_PROMPT = "Offset: type distance (mm) and press Enter  |  − for inward  |  Esc to cancel"


class _OffsetHud(QLabel):
    """Floating label near the source curve that shows the typed offset distance."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFont(QFont("Segoe UI", 10))
        self.hide()

    def refresh(self, input_str: str, valid: bool, out_of_range: bool = False) -> None:
        display = input_str if input_str else "—"
        self.setText(f"Offset: {display} mm" + ("  out of range" if out_of_range else ""))
        if out_of_range:
            self.setStyleSheet(
                "QLabel { background: rgba(170,40,40,215); color: #ffffff; "
                "border: 1px solid #ff8a8a; border-radius: 4px; padding: 2px 8px; }"
            )
        elif valid:
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
    canceled      = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene         = None
        self._view          = None
        self._source_curve  = None   # Curve to offset
        self._preview_item: CurveItem | None = None
        self._input_str: str = ""
        self._hud: _OffsetHud | None = None
        # The offset at one distance: (curve, why not, out of range).
        self._result_d: float | None = None
        self._result: tuple = (None, None, False)
        self._refusal_shown = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._update_preview)

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
        self._forget_result()

        if self._hud is None:
            self._hud = _OffsetHud(view)

        if source_curve is not None:
            self._update_hud()
            self.status_message.emit(_PROMPT)
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
        self._forget_result()

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
                self._forget_result()
                self._update_hud()
                self.status_message.emit(_PROMPT)
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
                self._clear_preview()
                self._update_hud()
                self._show_prompt_again()
                return True
            self._clear_preview()
            self.status_message.emit("Offset canceled")
            self.canceled.emit()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._apply_offset()
            return True

        if key == Qt.Key.Key_Backspace:
            self._input_str = self._input_str[:-1]
            self._typed()
            return True

        ch = typed_char(text)
        if ch and ch in "0123456789.-":
            # Guard against multiple dots or misplaced minus
            if ch == "." and "." in self._input_str:
                return True
            if ch == "-" and self._input_str:
                return True
            self._input_str += ch
            self._typed()
            return True

        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_d(self) -> float | None:
        """The typed distance, or None: through the shared parser, so a
        distance past ten meters is refused as every other typed length is
        (float() took 1e11 and added a curve that far away)."""
        from ..typed import parse_typed
        return parse_typed(self._input_str)

    def _typed(self) -> None:
        """The distance changed: the old preview goes at once, the new one
        comes when the typing pauses."""
        self._clear_preview_item()
        self._update_hud()
        self._preview_timer.start()

    def _forget_result(self) -> None:
        self._preview_timer.stop()
        self._result_d, self._result = None, (None, None, False)

    def _offset_for(self, d: float) -> tuple:
        """(offset, None, False), or (None, why not, out of range); worked
        out once a distance, so Enter adds what the preview showed."""
        if self._result_d == d:
            return self._result
        src = self._source_curve
        if src.kind in ("circle", "arc") and (src.radius or 0.0) + d <= 0.0:
            result = (None, f"Offset: {-d:g} mm inward is more than the "
                            f"{src.radius:g} mm radius — nothing would be left", True)
        else:
            from ..geometry import OffsetOutOfRange, offset_curve
            try:
                result = (offset_curve(src, d), None, False)
            except OffsetOutOfRange as exc:
                # A dense import (a trace, a scan) folds at every wiggle of
                # its noise; Rebuild with a tolerance takes the noise out.
                hint = ("; Rebuild it with fewer nodes first"
                        if len(src.nodes) > _DENSE_NODES
                        and _FOLDS in str(exc) else "")
                result = (None, f"Offset: {d:g} mm is out of range for this "
                                f"curve: {exc}{hint}", True)
            except Exception as exc:
                result = (None, f"Offset failed: {exc}", False)
        self._result_d, self._result = d, result
        return result

    def _show_prompt_again(self) -> None:
        """Put the prompt back over a refusal once the distance changes."""
        if self._refusal_shown:
            self._refusal_shown = False
            self.status_message.emit(_PROMPT)

    def _update_hud(self) -> None:
        if not self._hud or not self._view or not self._source_curve:
            return
        d = self._parse_d()
        out_of_range = d is not None and d == self._result_d and self._result[2]
        self._hud.refresh(self._input_str, d is not None and d != 0.0, out_of_range)

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
        if not self._source_curve or self._scene is None:
            return
        d = self._parse_d()
        if d is None or d == 0.0:
            self._show_prompt_again()
            return
        off_c, why_not, _out_of_range = self._offset_for(d)
        self._update_hud()
        if why_not:
            self.status_message.emit(why_not)
            self._refusal_shown = True
            return
        self._show_prompt_again()
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
        self._preview_timer.stop()
        self._clear_preview_item()

    def _apply_offset(self) -> None:
        self._preview_timer.stop()
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
        off_c, why_not, _out_of_range = self._offset_for(d)
        self._update_hud()
        if why_not:
            self.status_message.emit(why_not)
            self._refusal_shown = True
            return
        self._clear_preview_item()
        # A copy: the preview's item drew this one.
        self.offset_applied.emit(self._source_curve, copy.deepcopy(off_c))

    def _item_at(self, scene_pos: QPointF) -> CurveItem | None:
        return curve_item_at(self._view, scene_pos,
                             accept=lambda c: not c.mirrored)
