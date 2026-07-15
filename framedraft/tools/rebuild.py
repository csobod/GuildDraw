"""
RebuildSplineTool — rebuild a spline or polyline as a compact, editable curve.

Workflow (same shape as OffsetTool):
  1. Select exactly one spline/line curve in Select mode.
  2. Activate the Rebuild tool (toolbar button or R key).
  3. A floating HUD appears near the curve.
     • Node-count mode (default): type a target node count.
     • Tolerance mode (Tab to switch): type a max deviation in mm.
  4. The rebuilt preview (amber) updates live, and the HUD shows the achieved
     maximum deviation from the original in mm — so the maker sees exactly what
     a lower node count costs.
  5. Press Enter to confirm; Esc to cancel.

Powered by the M31 cubic-fitting engine (framedraft.fitting). The headline use
is turning a dense imported DXF polyline into a few editable nodes; it also
re-simplifies any hand-drawn or offset-heavy spline.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, QPointF, Qt, QRect
from PySide6.QtGui  import QPen, QColor, QFont
from PySide6.QtWidgets import QLabel

from ..canvas.items import CurveItem, curve_layer_locked


_PREVIEW_COLOR = "#ffd580"   # amber — matches the Offset preview
_PREVIEW_WIDTH = 2.0

MODE_COUNT = "count"
MODE_TOL   = "tol"


class _RebuildHud(QLabel):
    """Floating label showing the target + achieved deviation."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFont(QFont("Segoe UI", 10))
        self.hide()

    def refresh(self, text: str, valid: bool) -> None:
        self.setText(text)
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


class RebuildSplineTool(QObject):
    """One-shot tool: pick a spline/polyline, rebuild it with fewer nodes."""

    rebuild_applied = Signal(object, object)   # (source_curve, rebuilt_curve)
    status_message  = Signal(str)
    cancelled       = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene        = None
        self._view         = None
        self._source_curve = None
        self._preview_item: CurveItem | None = None
        self._input_str: str = ""
        self._mode: str = MODE_COUNT
        self._hud: _RebuildHud | None = None
        self._last_fit = None   # cached FitResult for the current input

    # ------------------------------------------------------------------
    # Public interface (matches CanvasView draw-tool dispatch shape)
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._scene is not None

    def activate(self, scene, view, source_curve) -> None:
        self._clear_preview()
        self._scene        = scene
        self._view         = view
        self._input_str    = ""
        self._mode         = MODE_COUNT
        self._last_fit     = None

        if self._hud is None:
            self._hud = _RebuildHud(view)

        # Only splines/polylines can be rebuilt — circles/arcs are already
        # minimal analytic primitives.
        if source_curve is not None and source_curve.kind in ("spline", "line"):
            self._source_curve = source_curve
        else:
            self._source_curve = None

        if self._source_curve is not None:
            self._update_hud()
            self.status_message.emit(
                "Rebuild: type a node count and press Enter  |  Tab = tolerance "
                "mode  |  Esc to cancel"
            )
        else:
            self._hud.hide()
            self.status_message.emit(
                "Rebuild: click a spline or polyline to rebuild  |  Esc to cancel"
            )

    def deactivate(self) -> None:
        self._clear_preview()
        if self._hud:
            self._hud.hide()
        self._scene        = None
        self._view         = None
        self._source_curve = None
        self._input_str    = ""
        self._last_fit     = None

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
            if (item and not item.curve.mirrored
                    and item.curve.kind in ("spline", "line")):
                self._source_curve = item.curve
                self._update_hud()
                self._update_preview()
                self.status_message.emit(
                    "Rebuild: type a node count and press Enter  |  Tab = "
                    "tolerance mode  |  Esc to cancel"
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
            self.status_message.emit("Rebuild cancelled")
            self.cancelled.emit()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._apply()
            return True

        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self._mode = MODE_TOL if self._mode == MODE_COUNT else MODE_COUNT
            self._input_str = ""
            self._update_hud()
            self._clear_preview_item()
            hint = ("tolerance in mm" if self._mode == MODE_TOL
                    else "a node count")
            self.status_message.emit(f"Rebuild: type {hint} and press Enter")
            return True

        if key == Qt.Key.Key_Backspace:
            self._input_str = self._input_str[:-1]
            self._update_hud()
            self._update_preview()
            return True

        # Count mode accepts digits only; tolerance mode adds "." for decimals.
        allowed = "0123456789" + ("." if self._mode == MODE_TOL else "")
        if text and text in allowed:
            if text == "." and "." in self._input_str:
                return True
            self._input_str += text
            self._update_hud()
            self._update_preview()
            return True

        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_target(self):
        """Return the parsed target value for the current mode, or None."""
        if not self._input_str:
            return None
        try:
            if self._mode == MODE_COUNT:
                n = int(self._input_str)
                return n if n >= 2 else None
            v = float(self._input_str)
            return v if v > 0.0 else None
        except (ValueError, TypeError):
            return None

    def _compute_fit(self):
        """Fit the source at the current target; cache and return FitResult."""
        self._last_fit = None
        if not self._source_curve:
            return None
        target = self._parse_target()
        if target is None:
            return None
        from ..geometry import sample_curve
        from ..fitting import fit_curve
        src = self._source_curve
        pts = [(x, y) for x, y, _ in sample_curve(src, 24)]
        if len(pts) < 2:
            return None
        try:
            if self._mode == MODE_COUNT:
                fr = fit_curve(pts, n_nodes=int(target), closed=bool(src.closed),
                               layer=src.layer, line_weight=src.line_weight)
            else:
                fr = fit_curve(pts, tol_mm=float(target), closed=bool(src.closed),
                               layer=src.layer, line_weight=src.line_weight)
        except Exception:
            return None
        self._last_fit = fr
        return fr

    def _hud_text(self, fit) -> tuple[str, bool]:
        if not self._input_str:
            if self._mode == MODE_COUNT:
                return "Rebuild: __ nodes   [Tab: tolerance]", False
            return "Rebuild: __ mm tol   [Tab: node count]", False
        if fit is None:
            if self._mode == MODE_COUNT:
                return f"Rebuild: {self._input_str} nodes   [Tab: tolerance]", False
            return f"Rebuild: {self._input_str} mm tol   [Tab: node count]", False
        dev = fit.max_deviation_mm
        if self._mode == MODE_COUNT:
            return (f"Rebuild: {fit.n_nodes} nodes   Δ {dev:.3f} mm   "
                    f"[Tab: tolerance]"), True
        return (f"Rebuild: {self._input_str} mm  →  {fit.n_nodes} nodes   "
                f"Δ {dev:.3f} mm   [Tab: node count]"), True

    def _update_hud(self) -> None:
        if not self._hud or not self._view or not self._source_curve:
            return
        fit = self._compute_fit()
        text, valid = self._hud_text(fit)
        self._hud.refresh(text, valid)

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
        fit = self._last_fit
        if fit is None:
            return
        item = CurveItem(fit.curve)
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

    def _apply(self) -> None:
        if not self._source_curve:
            self.status_message.emit("Rebuild: no source curve — click one first")
            return
        fit = self._compute_fit()
        if fit is None:
            hint = ("a node count (≥2)" if self._mode == MODE_COUNT
                    else "a tolerance in mm")
            self.status_message.emit(f"Rebuild: enter {hint}")
            return
        self._clear_preview_item()
        self.rebuild_applied.emit(self._source_curve, fit.curve)

    def _item_at(self, scene_pos: QPointF) -> CurveItem | None:
        if self._view is None:
            return None
        vp = self._view.mapFromScene(scene_pos)
        t  = 8
        candidates = self._view.items(QRect(vp.x() - t, vp.y() - t, 2 * t, 2 * t))
        return next((i for i in candidates
                     if isinstance(i, CurveItem) and not curve_layer_locked(i)),
                    None)
