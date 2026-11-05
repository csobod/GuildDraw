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
  - Circles / arcs: fully supported via angle parameterization.
  - A curve that ends on the target (within the 0.1 mm closure tolerance)
    cuts it there, as a crossing does. Two curves lying one on the other
    (a copy, a datum along a straight edge) meet only at the two ends of
    that stretch; a target that lies on another all along is refused.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal, QPointF, Qt, QRect
from PySide6.QtGui  import QPen, QColor

from ..canvas.items import CurveItem, curve_layer_locked
from ..geometry import (
    target_crossings, dedup_ts_mm, t_nearest, t_nearest_coarse, point_at_t,
    extract_open_segment, extract_wrapping_segment, flatten_curve,
    _point_polyline_dist,
)


_HOVER_COLOR  = "#ffd580"
_HOVER_WIDTH  = 2.5
_HIT_TOL_PX   = 8         # viewport-pixel tolerance for curve hit-testing
_KEEP_MIN_MM  = 1e-3      # a piece shorter than this has no length to keep


def _length_mm(curve) -> float:
    """Length of *curve* in scene mm, along its flattened polyline."""
    pts = flatten_curve(curve, 0.01)
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:], strict=False))


def _visible_curves(scene, curves: list) -> list:
    """Drop curves on hidden layers — invisible geometry must not act as a
    cutting edge (locked layers still cut: they remain a visible reference)."""
    is_visible = getattr(scene, "is_layer_visible", None)
    if is_visible is None:
        return curves
    return [c for c in curves if is_visible(c.layer)]


#: The hit box is a square: its corner is this much farther than its side,
#: and the coarse distance of a spline is a little long.
_PICK_REACH = 1.5


def _curve_dist_mm(curve, x: float, y: float) -> float:
    """Distance in scene mm from (x, y) to the nearest point on *curve*."""
    if curve.kind == "line" and len(curve.nodes) >= 2:
        # A polyline is exact per segment. t_nearest samples every segment
        # 32 times, which costs ~20 ms on a dense DXF import — too slow for
        # a hover that runs on every mouse move.
        pts = [(n.x, n.y) for n in curve.nodes]
        if curve.closed:
            pts.append(pts[0])
        return _point_polyline_dist((x, y), pts)
    if curve.kind == "circle" and curve.nodes:
        c = curve.nodes[0]
        return abs(math.hypot(x - c.x, y - c.y) - (curve.radius or 0.0))
    # A spline on the coarse grid: this only ranks the candidates in the hit
    # box, and the fine grid cost tens of ms a move on a dense import.
    px, py = point_at_t(curve, t_nearest_coarse(curve, x, y))
    return math.hypot(px - x, py - y)


# Said by every operation that would break a group apart. The tools check
# before they report success: the app's own refusal was overwritten at once
# by "Trim → 1 segment kept" while nothing had changed (2.0.1).
GROUPED_REFUSAL = ("the curve belongs to a group (a placed component); "
                   "ungroup it first (Ctrl+Shift+G)")


def curve_item_at(view, scene_pos: QPointF, tol_px: int = _HIT_TOL_PX,
                  accept=None) -> CurveItem | None:
    """The unlocked CurveItem nearest *scene_pos* within *tol_px* screen px.

    The cursor tools used to take the topmost item in the hit box, so a
    curve drawn later a few px away won over the one actually under the
    cursor (at 400 % a click on a line trimmed its neighbor instead). Ties
    keep the topmost. *accept* narrows the candidates further (curve kind,
    mirrored) before the nearest is chosen.
    """
    if view is None:
        return None
    vp = view.mapFromScene(scene_pos)
    t  = tol_px
    candidates = [i for i in view.items(QRect(vp.x() - t, vp.y() - t, 2 * t, 2 * t))
                  if isinstance(i, CurveItem) and not curve_layer_locked(i)
                  and (accept is None or accept(i.curve))]
    if not candidates:
        return None
    # A curve's hit stroke is 2 mm wide whatever the zoom, so the hit box
    # alone let a click 27 px beside a line at 30 px/mm trim it, 60 px at
    # 80 (Select has stopped at 7 px since the 2.3 hunt): the nearest
    # curve, and only within the tolerance on screen.
    x, y = scene_pos.x(), scene_pos.y()
    best = min(candidates, key=lambda i: _curve_dist_mm(i.curve, x, y))
    scale = abs(view.transform().m11())
    if _curve_dist_mm(best.curve, x, y) * scale > tol_px * _PICK_REACH:
        return None
    return best


class TrimTool(QObject):
    """Persistent cursor tool that trims curves at their intersections."""

    trim_applied   = Signal(object, list)   # (original_curve, [remaining_curves])
    status_message = Signal(str)
    canceled      = Signal()

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
            "  |  Esc to cancel"
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

        # Gather all intersection t-values on target with every other curve,
        # the target flattened once for them all (it was sampled twice per
        # curve: 7 s a click on a 2000-node trace among 100 curves).
        along: list = []
        hits = target_crossings(target, all_curves, along=along)
        ts = dedup_ts_mm(target, [t for t, _other in hits])

        is_closed = target.closed or target.kind == "circle"
        n_inter   = len(ts)

        if along and (n_inter == 0 or (is_closed and n_inter < 2)):
            self.status_message.emit(
                "Trim: this curve lies on another along its whole length "
                "(a copy?) — delete one of the two instead"
            )
            return True

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

            # A piece is kept by its length, not its share of t: on a dense
            # polyline a head 20 mm long held t < 1e-3 and went with the
            # clicked piece (2.0.1).
            for lo, hi in ((0.0, t_lo), (t_hi, 1.0)):
                if hi > lo:
                    piece = extract_open_segment(target, lo, hi)
                    if _length_mm(piece) > _KEEP_MIN_MM:
                        remaining.append(piece)

        self._clear_hover()
        if target.group_id:
            self.status_message.emit(f"Trim: {GROUPED_REFUSAL}")
            return True
        self.trim_applied.emit(target, remaining)

        n = len(remaining)
        self.status_message.emit(
            f"Trim → {n} segment{'s' if n != 1 else ''} kept"
            "  |  click to trim more  |  Esc to cancel"
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
        # The press already trimmed here. Taken as a second press, the
        # double-click trimmed the piece left beside it too.
        return True

    def handle_key(self, key, text: str = "") -> bool:
        if not self.active:
            return False
        if key == Qt.Key.Key_Escape:
            self._clear_hover()
            self.status_message.emit("Trim canceled")
            self.canceled.emit()
            return True
        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _item_at(self, scene_pos: QPointF) -> CurveItem | None:
        return curve_item_at(self._view, scene_pos)

    def _clear_hover(self):
        if self._hover_item is not None:
            self._hover_item.refresh()
            self._hover_item = None
