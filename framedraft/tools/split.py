"""
SplitTool — click anywhere on a curve to split it into two open curves at
that point (nearest-point split).

Workflow:
  1. Activate the tool.
  2. Hover over a curve — it highlights in amber.
  3. Click.  The curve is split at the nearest point to the click; both halves
     remain as independent open curves.
  4. The tool stays active for further splits.  Esc exits.

Special case: if the click is near the *intersection* of two curves, both
curves are split simultaneously at the shared intersection point, producing
four fragments.  The proximity threshold for detecting "near intersection" is
_ISECT_SNAP_MM scene-millimetres.
"""

from __future__ import annotations

import math
from PySide6.QtCore import QObject, Signal, QPointF, Qt, QRect
from PySide6.QtGui  import QPen, QColor

from ..canvas.items import CurveItem, curve_layer_locked
from ..geometry import (
    intersect_curve_params, dedup_ts_mm, t_nearest,
    split_curve_at_t, point_at_t,
)
from .trim import _visible_curves


_HOVER_COLOR    = "#ffd580"
_HOVER_WIDTH    = 2.5
_HIT_TOL_PX     = 8
_ISECT_SNAP_MM  = 1.5    # within this many mm of an intersection → snap to it


class SplitTool(QObject):
    """Persistent cursor tool that splits a curve at the clicked point."""

    # One emission per user click: [(original_curve, [left, right]), ...].
    # An intersection split breaks several curves at once — batching them into
    # a single signal lets the app record ONE undo step for the whole click.
    split_applied  = Signal(list)
    status_message = Signal(str)
    cancelled      = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene      = None
        self._view       = None
        self._curves_fn  = None
        self._hover_item: CurveItem | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._scene is not None

    def activate(self, scene, view, curves_fn):
        self._clear_hover()
        self._scene     = scene
        self._view      = view
        self._curves_fn = curves_fn
        self.status_message.emit(
            "Split: click a curve to split it at that point  |  Esc to exit"
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
                "Split: no curve found at click — try clicking closer to a curve"
            )
            return True

        target     = target_item.curve
        all_curves = _visible_curves(self._scene, self._curves_fn())
        px, py     = pos.x(), pos.y()

        # Find the split t, snapping to a nearby intersection if one exists
        split_t = self._snap_to_intersection(target, all_curves, px, py)
        if split_t is None:
            split_t = t_nearest(target, px, py)

        left, right = split_curve_at_t(target, split_t)
        if right is None:
            self.status_message.emit(
                "Split: click point is too close to an endpoint — "
                "click somewhere in the middle of the curve"
            )
            return True

        results = [left, right]

        # Intersection-split: also split any other curve near the same point
        split_x, split_y = point_at_t(target, split_t)
        extra_pairs: list[tuple] = []
        for other in all_curves:
            if other is target:
                continue
            o_t = t_nearest(other, split_x, split_y)
            ox, oy = point_at_t(other, o_t)
            if math.hypot(ox - split_x, oy - split_y) <= _ISECT_SNAP_MM:
                ol, orr = split_curve_at_t(other, o_t)
                if orr is not None:
                    extra_pairs.append((other, [ol, orr]))

        self._clear_hover()

        # All splits from this click in ONE emission = one undo step.
        self.split_applied.emit([(target, results)] + extra_pairs)

        n_extra = len(extra_pairs)
        msg = "Split → 2 curves"
        if n_extra:
            msg += f"  (+{n_extra} intersecting curve{'s' if n_extra>1 else ''} also split)"
        msg += "  |  click to split more  |  Esc to exit"
        self.status_message.emit(msg)
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
            self.status_message.emit("Split cancelled")
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

    def _snap_to_intersection(self, target, all_curves, px, py) -> float | None:
        """
        If the click (px, py) is within _ISECT_SNAP_MM of an intersection on
        target, return the intersection's t value; otherwise return None.
        """
        for other in all_curves:
            if other is target:
                continue
            ts = dedup_ts_mm(target, intersect_curve_params(target, other))
            for t in ts:
                ix, iy = point_at_t(target, t)
                if math.hypot(ix - px, iy - py) <= _ISECT_SNAP_MM:
                    return t
        return None
