from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsPathItem
from PySide6.QtCore import QRectF, Qt, QPointF, QTimer
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QPainterPath

from ..document import Curve, Layer
from . import items as _items
from .mirror import MirrorAxis

_DEFAULT_RECT = QRectF(-150, -100, 300, 200)   # mm

_TEXT_DRAG_THRESHOLD_PX = 4   # screen px of travel before a text drag begins


class TextItem(QGraphicsPathItem):
    """Rendered TextObject — selectable, draggable, double-click to re-edit.

    The glyph path is built relative to the anchor (anchor at item origin)
    and the item is positioned AT the anchor, so Qt's move machinery maps
    directly onto anchor_x / anchor_y.
    """

    def __init__(self, text_obj, on_drag_start=None, on_double_click=None):
        super().__init__()
        self.text_obj = text_obj
        self._on_drag_start   = on_drag_start
        self._on_double_click = on_double_click
        self._press_screen    = None
        self._drag_started    = False
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.refresh()

    def refresh(self):
        from dataclasses import replace
        from ..textpath import text_outline_path
        from .items import _layer_pen
        t = self.text_obj
        # Build glyphs about the origin; the item itself sits at the anchor.
        self.setPath(text_outline_path(replace(t, anchor_x=0.0, anchor_y=0.0)))
        pen = _layer_pen(t.layer, t.line_weight)
        self.setPen(pen)
        fill = QColor(pen.color())
        fill.setAlpha(70)
        self.setBrush(QBrush(fill))
        self.setPos(t.anchor_x, t.anchor_y)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            self.text_obj.anchor_x = self.pos().x()
            self.text_obj.anchor_y = self.pos().y()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        self._press_screen = event.screenPos()
        self._drag_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Push the undo snapshot once, just before the first real movement
        # (a plain click-to-select must not create an undo step).
        if (not self._drag_started and self._press_screen is not None
                and (event.screenPos() - self._press_screen).manhattanLength()
                    > _TEXT_DRAG_THRESHOLD_PX):
            self._drag_started = True
            if self._on_drag_start:
                self._on_drag_start()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_screen = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._on_double_click:
            self._on_double_click(self.text_obj)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

# Layers whose curves cast a live mirror ghost
_GHOST_LAYERS = {Layer.LENS, Layer.HINGE, Layer.OUTLINE, Layer.SCULPT}

# Default display size for an uncalibrated face image (mm).
# The image is scaled to fit inside this box while preserving aspect ratio.
_DEFAULT_IMG_WIDTH_MM  = 200.0
_DEFAULT_IMG_HEIGHT_MM = 150.0


def _cross_color() -> QColor:
    from .. import theme
    return QColor(theme.color("canvas.cross"))


def _mirror_path(curve: Curve, mirror) -> QPainterPath:
    """Build a QPainterPath reflecting curve through *mirror* (a MirrorAxis)."""
    from .items import build_path
    from ..geometry import mirror_curve
    return build_path(mirror_curve(curve, mirror.x,
                                   horizontal=getattr(mirror, "_horizontal", False)))


class FrameScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        # Linear item lookup instead of the default BSP tree. GuildDraw scenes
        # hold at most a few hundred items, so O(n) hit-testing is free — and it
        # removes an entire class of crash: an item whose Python boundingRect()
        # changes with zoom (DimItem's screen-sized label) mutates its geometry
        # without the prepareGeometryChange() the BSP tree needs to stay
        # consistent, so deleting it left a dangling pointer in the index that
        # segfaulted on the next repaint ("delete a dimension → app closes").
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.setSceneRect(_DEFAULT_RECT)
        self._face_items:        list[QGraphicsPixmapItem] = []
        self._face_drag_offsets: list[QPointF]            = []
        self._canvas_locked:     list[bool]               = []
        self._cross_items: list = []
        self._curve_items: dict = {}   # id(Curve) -> CurveItem
        self._ghost_items: dict = {}   # id(Curve) -> QGraphicsPathItem
        self._dim_items:   dict = {}   # id(DimLine) -> DimItem
        self._text_items:  dict = {}   # id(TextObject) -> TextItem
        self._text_edit_cb = None      # (TextObject) -> None; double-click re-edit
        self._mirror_display = True
        self._dim_drag_cb = None   # () -> None; pushed-undo hook for DimItem drags
        self.geometry_changed = None   # (Curve) -> None; live-follow hook (M12)
        self._layer_visible: dict = {}   # Layer -> bool (default True)
        self._layer_locked:  dict = {}   # Layer -> bool (default False)
        # Monotonic geometry revision — bumped on every curve add/remove/edit
        # so caches keyed on document state (intersection snap) can invalidate
        # without watching individual curves.
        self.revision: int = 0
        # Frame fill overlay (display-only; never exported)
        self._fill_visible: bool = False
        self._fill_color = QColor("#2a6099")
        self._fill_opacity: float = 0.50
        self._fill_item: QGraphicsPathItem | None = None
        # Coalesces hot-path fill rebuilds (add/remove/refresh fire per mouse
        # move during drags) into one boolean-ops pass per event-loop tick.
        # Child timer so a pending tick dies with the scene.
        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.setInterval(0)
        self._fill_timer.timeout.connect(self.rebuild_fill)
        # Store the cross extents so set_dark_mode can redraw them correctly
        self._cross_hw: float = 150.0
        self._cross_hh: float = 100.0
        self._draw_cross(0.0, 0.0, self._cross_hw, self._cross_hh)
        self.mirror: MirrorAxis | None = None

    def init_mirror(self, horizontal: bool = False):
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
        for item in self._text_items.values():
            item.refresh()
        self._update_ghosts()
        self._clear_cross()
        self._draw_cross(0.0, 0.0, self._cross_hw, self._cross_hh)
        if self.mirror:
            self.mirror.refresh_theme(dark)

    # ------------------------------------------------------------------
    # Layer visibility / locking
    # ------------------------------------------------------------------

    def is_layer_visible(self, layer) -> bool:
        return self._layer_visible.get(layer, True)

    def is_layer_locked(self, layer) -> bool:
        return self._layer_locked.get(layer, False)

    def _apply_layer_state_to_item(self, item):
        """Push the item's layer visibility/lock onto the item itself."""
        layer   = item.curve.layer
        visible = self.is_layer_visible(layer)
        item.setVisible(visible)
        selectable = visible and not self.is_layer_locked(layer)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, selectable)
        if not selectable:
            item.setSelected(False)

    def set_layer_visible(self, layer, on: bool):
        self._layer_visible[layer] = on
        for item in self._curve_items.values():
            if item.curve.layer == layer:
                self._apply_layer_state_to_item(item)
        for cid, ghost in self._ghost_items.items():
            ci = self._curve_items.get(cid)
            if ci is not None and ci.curve.layer == layer:
                ghost.setVisible(on)
        for item in self._text_items.values():
            if item.text_obj.layer == layer:
                self._apply_layer_state_to_text(item)
        self.rebuild_fill()

    def set_layer_locked(self, layer, locked: bool):
        self._layer_locked[layer] = locked
        for item in self._curve_items.values():
            if item.curve.layer == layer:
                self._apply_layer_state_to_item(item)
        for item in self._text_items.values():
            if item.text_obj.layer == layer:
                self._apply_layer_state_to_text(item)

    def reset_layer_states(self):
        """All layers visible and unlocked (File > New / before a load)."""
        self._layer_visible.clear()
        self._layer_locked.clear()
        for item in self._curve_items.values():
            self._apply_layer_state_to_item(item)
        for item in self._text_items.values():
            self._apply_layer_state_to_text(item)

    # ------------------------------------------------------------------
    # Frame fill overlay (display-only — never exported)
    # ------------------------------------------------------------------

    def set_fill_visible(self, on: bool):
        self._fill_visible = bool(on)
        self.rebuild_fill()

    def set_fill_color(self, color):
        """color: QColor or '#rrggbb' string."""
        self._fill_color = QColor(color)
        self.rebuild_fill()

    def set_fill_opacity(self, opacity: float):
        self._fill_opacity = max(0.0, min(1.0, opacity))
        self.rebuild_fill()

    def fill_state(self) -> dict:
        return {"visible": self._fill_visible,
                "color":   self._fill_color.name(),
                "opacity": self._fill_opacity}

    def _schedule_fill_rebuild(self):
        """Deferred rebuild_fill for the hot paths (curve add/remove/refresh)."""
        if self._fill_visible:
            self._fill_timer.start()

    def rebuild_fill(self):
        """Recompute the frame interior: union of OUTLINE (real + ghost)
        minus LENS apertures (real + ghost). No-op while hidden so the
        boolean path ops never run during normal editing."""
        if not self._fill_visible:
            if self._fill_item is not None:
                self._fill_item.setVisible(False)
            return
        from .items import build_path

        def _vis(layer):
            return self.is_layer_visible(layer)

        combined = QPainterPath()
        lens     = QPainterPath()
        for item in self._curve_items.values():
            c = item.curve
            if c.layer == Layer.OUTLINE and _vis(c.layer):
                combined = combined.united(build_path(c))
            elif c.layer == Layer.LENS and _vis(c.layer):
                lens = lens.united(build_path(c))
        for cid, ghost in self._ghost_items.items():
            ci = self._curve_items.get(cid)
            if ci is None or not ghost.isVisible():
                continue
            if ci.curve.layer == Layer.OUTLINE:
                combined = combined.united(ghost.path())
            elif ci.curve.layer == Layer.LENS:
                lens = lens.united(ghost.path())
        combined = combined.subtracted(lens)

        if self._fill_item is None:
            it = QGraphicsPathItem()
            # Above face photos (z=-1000…), below the origin cross (z=0)
            # and all geometry (z=10).
            it.setZValue(-500)
            it.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, False)
            self.addItem(it)
            self._fill_item = it
        color = QColor(self._fill_color)
        color.setAlphaF(self._fill_opacity)
        self._fill_item.setBrush(QBrush(color))
        self._fill_item.setPen(QPen(Qt.PenStyle.NoPen))
        self._fill_item.setPath(combined)
        self._fill_item.setVisible(True)

    # ------------------------------------------------------------------
    # Curve management
    # ------------------------------------------------------------------

    def add_curve(self, curve: Curve):
        from .items import CurveItem
        item = CurveItem(curve)
        self.addItem(item)
        self._curve_items[id(curve)] = item
        self.revision += 1
        self._apply_layer_state_to_item(item)
        self._update_ghost_for(curve)
        self._schedule_fill_rebuild()
        return item

    def refresh_curve(self, curve: Curve):
        self.revision += 1
        item = self._curve_items.get(id(curve))
        if item:
            item.refresh()
        self._update_ghost_for(curve)
        self._schedule_fill_rebuild()
        # Live-follow hook: fires on node/handle edits and drag-moves (both route
        # through refresh_curve) so observers like the snapped boxing guide can
        # track geometry without a full document-change notification.
        if self.geometry_changed:
            self.geometry_changed(curve)

    def remove_curve(self, curve: Curve):
        self.revision += 1
        item = self._curve_items.pop(id(curve), None)
        if item:
            self.removeItem(item)
        ghost = self._ghost_items.pop(id(curve), None)
        if ghost:
            self.removeItem(ghost)
        self._schedule_fill_rebuild()

    # ------------------------------------------------------------------
    # Mirror ghost display
    # ------------------------------------------------------------------

    def set_mirror_display(self, on: bool):
        self._mirror_display = on
        self._update_ghosts()
        self.rebuild_fill()

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
        ghost.setVisible(self.is_layer_visible(curve.layer))

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
    # Text objects (ENGRAVING)
    # ------------------------------------------------------------------

    def set_text_edit_callback(self, cb):
        """cb(text_obj) is invoked when a TextItem is double-clicked."""
        self._text_edit_cb = cb

    def add_text(self, text_obj):
        item = TextItem(text_obj,
                        on_drag_start=self._dim_drag_cb,
                        on_double_click=self._text_edit_cb)
        self.addItem(item)
        self._text_items[id(text_obj)] = item
        self._apply_layer_state_to_text(item)
        return item

    def remove_text(self, text_obj):
        item = self._text_items.pop(id(text_obj), None)
        if item:
            self.removeItem(item)

    def refresh_text(self, text_obj):
        item = self._text_items.get(id(text_obj))
        if item:
            item.refresh()

    def _apply_layer_state_to_text(self, item):
        layer   = item.text_obj.layer
        visible = self.is_layer_visible(layer)
        item.setVisible(visible)
        interactable = visible and not self.is_layer_locked(layer)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, interactable)
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable,    interactable)
        if not interactable:
            item.setSelected(False)

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

    # ------------------------------------------------------------------
    # Printing support (M8 — 1:1 print / PDF)
    # ------------------------------------------------------------------

    def geometry_rect(self) -> QRectF:
        """Scene-mm bbox of visible curves, mirror ghosts, and texts.
        Excludes guides, face photos, and the origin cross — this is the
        extent that matters for a 1:1 paper test fit."""
        rect = QRectF()
        for items in (self._curve_items, self._ghost_items, self._text_items):
            for it in items.values():
                if it.isVisible():
                    rect = rect.united(it.sceneBoundingRect())
        return rect

    def begin_print(self) -> list:
        """Hide screen-only chrome (face photos, origin cross) for a print
        render. Returns the hidden items for end_print."""
        hidden = [it for it in (self._face_items + self._cross_items)
                  if it.isVisible()]
        for it in hidden:
            it.setVisible(False)
        return hidden

    def end_print(self, hidden: list):
        for it in hidden:
            it.setVisible(True)

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
