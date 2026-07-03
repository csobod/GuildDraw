"""
TrimTool — click a curve to remove the portion between its two nearest
intersections with all other curves (AutoCAD-style trim).

Workflow:
  1. Activate the tool (toolbar button or keyboard shortcut).
  2. Hover over a curve — it highlights in amber.
  3. Click a curve.  The segment of that curve between the two nearest
     intersection points (with any other curve) is deleted; the remaining
     pieces are kept as new open curves.
  4. The tool stays active so you can trim more curves.  Esc exits.

Rules:
  - Open curves   : need >=1 intersection to trim (trims to/from an endpoint
                    when only one cutting edge exists).
  - Closed curves : need >=2 intersections (otherwise the geometry is
                    ambiguous and nothing happens).
  - Circles / arcs: fully supported via angle parameterisation.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, QPointF, Qt, QRect
from PySide6.QtGui  import QPen, QColor

from ..canvas.items import CurveItem, curve_layer_locked
from ..geometry import (
    intersect_curve_params, dedup_ts_mm, t_nearest,
    extract_open_segment, extract_wrapping_segment,
)


_HOVER_COLOR  = "#ffd580"
_HOVER_WIDTH  = 2.5
_HIT_TOL_PX   = 8         # viewport-pixel tolerance for curve hit-testing


def _visible_curves(scene, curves: list) -> list:
    """Drop curves on hidden layers — invisible geometry must not act as a
    cutting edge (locked layers still cut: they remain a visible reference)."""
    is_visible = getattr(scene, "is_layer_visible", None)
    if is_visible is None:
        return curves
    return [c for c in curves if is_visible(c.layer)]


class TrimTool(QObject):
    """Persistent cursor tool that trims curves at their intersections."""

    trim_applied   = Signal(object, list)   # (original_curve, [remaining_curves])
    status_message = Signal(str)
    cancelled      = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene      = None
        self._view       = None
        self._curves_fn  = None        # callable -> list[Curve]
        self._hover_item: CurveItem | None = None

    # ------------------------------------------------------------------
    # Public interface (same shape as DrawTool for CanvasView dispatch)
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._scene is not None

    def activate(self, scene, view, curves_fn):
        """
        scene     : FrameScene
        view      : CanvasView
        curves_fn : callable that returns the current list of Curve objects
        """
        self._clear_hover()
        self._scene     = scene
        self._view      = view
        self._curves_fn = curves_fn
        self.status_message.emit(
            "Trim: click a curve to remove the segment between its intersections"
            "  |  Esc to exit"
        )

    def deactivate(self):
        self._clear_hover()
        self._scene     = None
        self._view      = None
        self._curves_fn = None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_press(self, pos: QPointF,
                     use_snap: bool = True,
                     constrain: bool = False) -> bool:
        if not self.active:
            return False

        target_item = self._item_at(pos)
        if target_item is None:
            self.status_message.emit(
                "Trim: no curve found at click — try clicking closer to a curve"
            )
            return True

        target     = target_item.curve
        all_curves = _visible_curves(self._scene, self._curves_fn())

        # Gather all intersection t-values on target with every other curve
        raw_ts: list[float] = []
        for other in all_curves:
            if other is target:
                continue
            raw_ts.extend(intersect_curve_params(target, other))

        ts = dedup_ts_mm(target, raw_ts)

        is_closed = target.closed or target.kind == "circle"
        n_inter   = len(ts)

        if n_inter == 0:
            self.status_message.emit(
                "Trim: no intersections found — this curve does not cross any other"
            )
            return True

        if is_closed and n_inter < 2:
            self.status_message.emit(
                "Trim: closed curve needs ≥2 intersections to trim "
                "(use Split or Split-at-Node to open it)"
            )
            return True

        click_t = t_nearest(target, pos.x(), pos.y())

        # Determine which sub-segment the click falls in and compute remaining
        remaining: list = []

        if is_closed:
            ts_s = sorted(ts)
            n    = len(ts_s)
            t_lo = t_hi = None

            for i in range(n):
                ta = ts_s[i]
                tb = ts_s[(i + 1) % n]
                if i == n - 1:                       # wrapping interval
                    if click_t >= ta or click_t <= tb:
                        t_lo, t_hi = ta, tb
                        break
                else:
                    if ta <= click_t <= tb:
                        t_lo, t_hi = ta, tb
                        break

            if t_lo is None:                         # fallback
                t_lo, t_hi = ts_s[-1], ts_s[0]

            if t_lo < t_hi:
                # Removing [t_lo, t_hi]; keep the wrapping arc [t_hi, t_lo]
                remaining = [extract_wrapping_segment(target, t_hi, t_lo)]
            else:
                # Removing wrapping arc; keep [t_hi, t_lo]
                remaining = [extract_open_segment(target, t_hi, t_lo)]

        else:
            boundaries = [0.0] + sorted(ts) + [1.0]
            t_lo = t_hi = None
            for i in range(len(boundaries) - 1):
                if boundaries[i] <= click_t <= boundaries[i + 1]:
                    t_lo, t_hi = boundaries[i], boundaries[i + 1]
                    break
            if t_lo is None:
                t_lo, t_hi = 0.0, 1.0

            if t_lo > 1e-3:
                remaining.append(extract_open_segment(target, 0.0, t_lo))
            if t_hi < 1 - 1e-3:
                remaining.append(extract_open_segment(target, t_hi, 1.0))

        self._clear_hover()
        self.trim_applied.emit(target, remaining)

        n = len(remaining)
        self.status_message.emit(
            f"Trim → {n} segment{'s' if n != 1 else ''} kept"
            "  |  click to trim more  |  Esc to exit"
        )
        return True

    def handle_move(self, pos: QPointF,
                    use_snap: bool = True,
                    constrain: bool = False):
        if not self.active:
            return
        item = self._item_at(pos)
        if item is self._hover_item:
            return
        self._clear_hover()
        self._hover_item = item
        if item:
            pen = QPen(QColor(_HOVER_COLOR), 0)
            pen.setCosmetic(True)
            pen.setWidthF(_HOVER_WIDTH)
            item.setPen(pen)

    def handle_dbl_click(self, pos: QPointF,
                          use_snap: bool = True,
                          constrain: bool = False) -> bool:
        return self.handle_press(pos, use_snap, constrain)

    def handle_key(self, key, text: str = "") -> bool:
        if not self.active:
            return False
        if key == Qt.Key.Key_Escape:
            self._clear_hover()
            self.status_message.emit("Trim cancelled")
            self.cancelled.emit()
            return True
        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _item_at(self, scene_pos: QPointF) -> CurveItem | None:
        if self._view is None:
            return None
        vp = self._view.mapFromScene(scene_pos)
        t  = _HIT_TOL_PX
        candidates = self._view.items(QRect(vp.x()-t, vp.y()-t, 2*t, 2*t))
        return next((i for i in candidates
                     if isinstance(i, CurveItem) and not curve_layer_locked(i)),
                    None)

    def _clear_hover(self):
        if self._hover_item is not None:
            self._hover_item.refresh()
            self._hover_item = None
