from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsPathItem
from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import QColor, QPen, QPixmap, QPainterPath

from ..document import Curve, Layer, SplineNode, ControlPoint
from . import items as _items

_DEFAULT_RECT = QRectF(-150, -100, 300, 200)   # mm

# Layers whose curves cast a live mirror ghost
_GHOST_LAYERS = {Layer.LENS, Layer.HINGE, Layer.OUTLINE, Layer.SCULPT}

# Default display size for an uncalibrated face image (mm).
# The image is scaled to fit inside this box while preserving aspect ratio.
_DEFAULT_IMG_WIDTH_MM  = 200.0
_DEFAULT_IMG_HEIGHT_MM = 150.0


def _cross_color() -> QColor:
    return QColor("#554433") if _items._DARK else QColor("#ccbbaa")


def _mirror_path(curve: Curve, mirror) -> QPainterPath:
    """Build a QPainterPath reflecting curve through *mirror* (a MirrorAxis)."""
    from .items import build_path

    horizontal = getattr(mirror, '_horizontal', False)

    def mp(x: float, y: float) -> tuple:
        if horizontal:
            return x, -y
        return 2.0 * mirror.x - x, y

    if curve.kind == "circle":
        new_cx, new_cy = mp(curve.nodes[0].x, curve.nodes[0].y)
        tmp = Curve(kind="circle", layer=curve.layer,
                    nodes=[SplineNode(x=new_cx, y=new_cy)],
                    closed=curve.closed, radius=curve.radius)
        return build_path(tmp)

    if curve.kind == "arc":
        new_cx, new_cy = mp(curve.nodes[0].x, curve.nodes[0].y)
        if horizontal:
            # y-flip: angle θ → −θ, swap start/end
            new_start = (-curve.end_angle)   % 360 if curve.end_angle   is not None else None
            new_end   = (-curve.start_angle) % 360 if curve.start_angle is not None else None
        else:
            # x-flip: angle θ → 180−θ, swap start/end
            new_start = 180.0 - curve.end_angle   if curve.end_angle   is not None else None
            new_end   = 180.0 - curve.start_angle if curve.start_angle is not None else None
        tmp = Curve(kind="arc", layer=curve.layer,
                    nodes=[SplineNode(x=new_cx, y=new_cy)],
                    closed=curve.closed, radius=curve.radius,
                    start_angle=new_start, end_angle=new_end)
        return build_path(tmp)

    mirrored = []
    for n in curve.nodes:
        nx, ny = mp(n.x, n.y)
        mn = SplineNode(x=nx, y=ny)
        if n.cp_in:
            cpx, cpy = mp(n.cp_in.x, n.cp_in.y)
            mn.cp_in  = ControlPoint(cpx, cpy)
        if n.cp_out:
            cpx, cpy = mp(n.cp_out.x, n.cp_out.y)
            mn.cp_out = ControlPoint(cpx, cpy)
        mirrored.append(mn)

    tmp = Curve(kind=curve.kind, layer=curve.layer, nodes=mirrored, closed=curve.closed)
    return build_path(tmp)


class FrameScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.setSceneRect(_DEFAULT_RECT)
        self._face_items:        list[QGraphicsPixmapItem] = []
        self._face_drag_offsets: list[QPointF]            = []
        self._canvas_locked:     list[bool]               = []
        self._cross_items: list = []
        self._curve_items: dict = {}   # id(Curve) -> CurveItem
        self._ghost_items: dict = {}   # id(Curve) -> QGraphicsPathItem
        self._dim_items:   dict = {}   # id(DimLine) -> DimItem
        self._mirror_display = True
        self._dim_drag_cb = None   # () -> None; pushed-undo hook for DimItem drags
        # Store the cross extents so set_dark_mode can redraw them correctly
        self._cross_hw: float = 150.0
        self._cross_hh: float = 100.0
        self._draw_cross(0.0, 0.0, self._cross_hw, self._cross_hh)
        self.mirror: "MirrorAxis | None" = None

    def init_mirror(self, horizontal: bool = False):
        from .mirror import MirrorAxis
        self.mirror = MirrorAxis(self, horizontal=horizontal)

    # ------------------------------------------------------------------
    # Face / reference images  (multiple supported)
    # ------------------------------------------------------------------

    def add_face(self, path: str) -> int | None:
        """Load an image as a background reference layer. Returns its index, or None on failure."""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None

        idx  = len(self._face_items)
        item = QGraphicsPixmapItem(pixmap)
        item.setZValue(-1000 + idx)   # later additions sit on top
        item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable, False)
        item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable,    False)
        item.setOpacity(0.7)
        self.addItem(item)

        self._face_items.append(item)
        self._face_drag_offsets.append(QPointF(0.0, 0.0))
        self._canvas_locked.append(True)

        w, h = float(pixmap.width()), float(pixmap.height())
        default_scale = min(_DEFAULT_IMG_WIDTH_MM / w, _DEFAULT_IMG_HEIGHT_MM / h)
        self._apply_one_face_scale(idx, default_scale)

        if idx == 0:
            self._update_scene_rect_for_face()
        return idx

    def load_face(self, path: str) -> bool:
        """Replace all images with a single new one (backward-compat wrapper)."""
        self.clear_faces()
        return self.add_face(path) is not None

    def clear_faces(self):
        for item in self._face_items:
            self.removeItem(item)
        self._face_items.clear()
        self._face_drag_offsets.clear()
        self._canvas_locked.clear()

    def remove_face(self, index: int):
        if not (0 <= index < len(self._face_items)):
            return
        self.removeItem(self._face_items[index])
        del self._face_items[index]
        del self._face_drag_offsets[index]
        del self._canvas_locked[index]
        for i, it in enumerate(self._face_items):
            it.setZValue(-1000 + i)
        self._update_scene_rect_for_face()

    def face_count(self) -> int:
        return len(self._face_items)

    def get_face_item(self, index: int) -> QGraphicsPixmapItem | None:
        if 0 <= index < len(self._face_items):
            return self._face_items[index]
        return None

    def has_face(self) -> bool:
        return bool(self._face_items)

    # --- calibration (applies uniformly to all images) ---

    def set_face_calibration(self, px_per_mm: float):
        """Rescale all reference images to the given calibration."""
        if px_per_mm <= 0 or not self._face_items:
            return
        mm_per_px = 1.0 / px_per_mm
        for idx, item in enumerate(self._face_items):
            p = item.pixmap()
            w, h = float(p.width()), float(p.height())
            cur = item.pos()
            # Preserve any drag offset the user applied before recalibrating
            self._face_drag_offsets[idx] = QPointF(cur.x() - (-w / 2),
                                                    cur.y() - (-h / 2))
            self._apply_one_face_scale(idx, mm_per_px)
        self._update_scene_rect_for_face()

    def _apply_one_face_scale(self, index: int, mm_per_px: float):
        """Scale one image, keeping its drag offset relative to scene origin."""
        item   = self._face_items[index]
        offset = self._face_drag_offsets[index]
        p      = item.pixmap()
        w, h   = float(p.width()), float(p.height())
        item.setScale(mm_per_px)
        # pos uses pixel units so (1−scale)×origin cancels correctly, centering
        # the image at scene origin when offset is (0,0).
        item.setTransformOriginPoint(w / 2, h / 2)
        item.setPos(-w / 2 + offset.x(), -h / 2 + offset.y())

    def _update_scene_rect_for_face(self):
        """Resize sceneRect and crosshair based on the primary (index 0) image."""
        if not self._face_items:
            self.setSceneRect(_DEFAULT_RECT)
            self._cross_hw = 150.0
            self._cross_hh = 100.0
            self._clear_cross()
            self._draw_cross(0.0, 0.0, self._cross_hw, self._cross_hh)
            if self.mirror:
                self.mirror.scene_rect_changed()
            return
        item = self._face_items[0]
        p    = item.pixmap()
        w, h = float(p.width()), float(p.height())
        s    = item.scale()
        w_mm = w * s
        h_mm = h * s
        margin = max(w_mm, h_mm) * 0.05
        self.setSceneRect(-w_mm / 2 - margin, -h_mm / 2 - margin,
                          w_mm + 2 * margin,  h_mm + 2 * margin)
        self._cross_hw = w_mm / 2
        self._cross_hh = h_mm / 2
        self._clear_cross()
        self._draw_cross(0.0, 0.0, self._cross_hw, self._cross_hh)
        if self.mirror:
            self.mirror.scene_rect_changed()

    # --- per-image controls ---

    def set_face_opacity(self, index: int, opacity: float):
        item = self.get_face_item(index)
        if item is not None:
            item.setOpacity(max(0.0, min(1.0, opacity)))

    def face_opacity(self, index: int) -> float:
        item = self.get_face_item(index)
        return item.opacity() if item is not None else 0.7

    def set_face_rotation(self, index: int, degrees: float):
        item = self.get_face_item(index)
        if item is not None:
            item.setRotation(degrees)

    def face_rotation(self, index: int) -> float:
        item = self.get_face_item(index)
        return item.rotation() if item is not None else 0.0

    def set_canvas_locked(self, index: int, locked: bool):
        if not (0 <= index < len(self._face_items)):
            return
        self._canvas_locked[index] = locked
        item = self._face_items[index]
        item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, not locked)
        if locked:
            item.unsetCursor()
        else:
            item.setCursor(Qt.CursorShape.SizeAllCursor)

    def face_is_locked(self, index: int) -> bool:
        if 0 <= index < len(self._canvas_locked):
            return self._canvas_locked[index]
        return True

    def face_scene_pos(self, index: int) -> tuple[float, float]:
        item = self.get_face_item(index)
        if item is None:
            return (0.0, 0.0)
        p = item.pos()
        return (p.x(), p.y())

    # ------------------------------------------------------------------
    # Dark mode
    # ------------------------------------------------------------------

    def set_dark_mode(self, dark: bool):
        _items.set_dark_mode(dark)
        for item in self._curve_items.values():
            item.refresh()
        self._update_ghosts()
        self._clear_cross()
        self._draw_cross(0.0, 0.0, self._cross_hw, self._cross_hh)
        if self.mirror:
            self.mirror.refresh_theme(dark)

    # ------------------------------------------------------------------
    # Curve management
    # ------------------------------------------------------------------

    def add_curve(self, curve: Curve):
        from .items import CurveItem
        item = CurveItem(curve)
        self.addItem(item)
        self._curve_items[id(curve)] = item
        self._update_ghost_for(curve)
        return item

    def refresh_curve(self, curve: Curve):
        item = self._curve_items.get(id(curve))
        if item:
            item.refresh()
        self._update_ghost_for(curve)

    def remove_curve(self, curve: Curve):
        item = self._curve_items.pop(id(curve), None)
        if item:
            self.removeItem(item)
        ghost = self._ghost_items.pop(id(curve), None)
        if ghost:
            self.removeItem(ghost)

    # ------------------------------------------------------------------
    # Mirror ghost display
    # ------------------------------------------------------------------

    def set_mirror_display(self, on: bool):
        self._mirror_display = on
        self._update_ghosts()

    def _ghost_eligible(self, curve: Curve) -> bool:
        if not self._mirror_display or self.mirror is None:
            return False
        if curve.mirrored or curve.layer not in _GHOST_LAYERS:
            return False
        if curve.layer == Layer.OUTLINE and curve.closed:
            return False
        return True

    def _update_ghost_for(self, curve: Curve):
        """Create, update, or remove the ghost for one curve in place.

        Called per mouse-move during node drags — must not touch other
        curves' ghost items (destroy/recreate-all caused visible churn).
        """
        key = id(curve)
        if not self._ghost_eligible(curve):
            ghost = self._ghost_items.pop(key, None)
            if ghost:
                self.removeItem(ghost)
            return

        from .items import _layer_pen
        path = _mirror_path(curve, self.mirror)
        pen  = _layer_pen(curve.layer, curve.line_weight)
        pen.setStyle(Qt.PenStyle.DotLine)

        ghost = self._ghost_items.get(key)
        if ghost is None:
            ghost = self.addPath(path, pen)
            ghost.setZValue(9)
            self._ghost_items[key] = ghost
        else:
            ghost.setPath(path)
            ghost.setPen(pen)

    def _update_ghosts(self):
        """Full rebuild — used on mirror toggle, theme change, layer change."""
        for ghost in self._ghost_items.values():
            self.removeItem(ghost)
        self._ghost_items.clear()
        if not self._mirror_display or self.mirror is None:
            return
        for curve_item in self._curve_items.values():
            self._update_ghost_for(curve_item.curve)

    # ------------------------------------------------------------------
    # Dimension annotations
    # ------------------------------------------------------------------

    def set_dim_drag_callback(self, cb):
        """cb is invoked once when a DimItem offset-drag begins (undo hook)."""
        self._dim_drag_cb = cb

    def add_dim(self, dim):
        from .dim import DimItem
        item = DimItem(dim, on_drag_start=self._dim_drag_cb)
        self.addItem(item)
        self._dim_items[id(dim)] = item
        return item

    def remove_dim(self, dim):
        item = self._dim_items.pop(id(dim), None)
        if item:
            self.removeItem(item)

    def dim_for_item(self, scene_item):
        """Return the DimLine whose DimItem is *scene_item*, or None."""
        for dim_id, it in self._dim_items.items():
            if it is scene_item:
                # find the DimLine by id — caller passes dim list; we just
                # return the item's .dim attribute
                return it.dim
        return None

    # ------------------------------------------------------------------
    # Origin cross
    # ------------------------------------------------------------------

    def _clear_cross(self):
        for item in self._cross_items:
            self.removeItem(item)
        self._cross_items.clear()

    def _draw_cross(self, cx: float, cy: float, hw: float, hh: float):
        pen = QPen(_cross_color(), 0)
        pen.setStyle(Qt.PenStyle.DotLine)
        self._cross_items.append(self.addLine(cx - hw, cy, cx + hw, cy, pen))
        self._cross_items.append(self.addLine(cx, cy - hh, cx, cy + hh, pen))
