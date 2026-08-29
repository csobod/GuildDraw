import math

from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsPathItem
from PySide6.QtCore import QRectF, Qt, QPointF, QTimer
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPen, QPixmap,
                          QPainterPath, QTransform)

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


# Endpoint-stitch tolerance for the frame fill (mm). Two curve ends this close
# are treated as joined, so a snapped-but-not-merged perimeter still encloses a
# region. Matches the export validator's closure tolerance / GuildModel's
# auto-close, so the fill's idea of "closed" agrees with the handoff contract.
_FILL_STITCH_TOL_MM = 0.1

# Frame Fill from a material swatch. The image is scaled to span the stock
# blank's width and centred on the origin — the blank guide's own anchor — so
# the frame shows the piece of sheet it would really be cut from. Used until
# the app tells the scene the workspace's actual blank width.
DEFAULT_FILL_BLANK_W_MM = 170.0

# Long-side cap for a loaded swatch (px). A 170 mm blank at 300 dpi is ~2000 px,
# so this still oversamples the largest PNG export while keeping a 6000-px
# catalogue photo from pinning ~100 MB in the scene for the session.
FILL_IMAGE_MAX_PX = 4096

# Lens Fill shipped defaults. A pale-over-deep blue reads as a gradient tint at
# a glance without being mistaken for real geometry; 65% keeps the lens shape's
# own stroke and any face photo behind it legible through the tint.
DEFAULT_LENS_FILL_TOP     = "#cbeafc"
DEFAULT_LENS_FILL_BOTTOM  = "#4a9fd8"
DEFAULT_LENS_FILL_OPACITY = 0.65

# Tint intensity — how deeply the dye reads, independent of how much the
# overlay covers what is behind it (that is opacity). Reference swatches,
# BPI's included, show a dye at one modest depth over white, so a colour
# picked from one is usually too pale to represent the lens a maker means.
# 1.0 is the colour exactly as picked.
DEFAULT_LENS_FILL_INTENSITY = 1.0
LENS_FILL_INTENSITY_MIN     = 0.5
LENS_FILL_INTENSITY_MAX     = 8.0


def deepen_tint(color, intensity: float) -> QColor:
    """A tint at *intensity* times its dyed depth.

    Beer–Lambert: a dye's transmission falls off exponentially with depth, so
    doubling the depth squares the transmission. Working per channel on
    transmission (the colour over white) rather than on the colour itself has
    two properties that matter here — it can never leave the 0…1 range, so no
    channel clamps and skews the hue the way scaling distance-from-white does,
    and it converges on the dye's own colour rather than on black.

    intensity < 1 thins the tint, 1.0 is the colour as picked, > 1 deepens it.
    Alpha is carried through untouched.
    """
    c = QColor(color)
    k = max(LENS_FILL_INTENSITY_MIN, min(LENS_FILL_INTENSITY_MAX, float(intensity)))
    if abs(k - 1.0) < 1e-9:
        return c
    out = QColor.fromRgbF(c.redF() ** k, c.greenF() ** k, c.blueF() ** k)
    out.setAlphaF(c.alphaF())
    return out


def intensity_from_slider(pos: int) -> float:
    """Slider position (0–100) -> intensity. Geometric, so each step is a
    constant *ratio* of depth: the pale end needs a much larger exponent than
    the deep end for the same visible change, which a linear scale spends most
    of its travel failing to reach. Position 25 lands exactly on 1.0."""
    span = LENS_FILL_INTENSITY_MAX / LENS_FILL_INTENSITY_MIN
    return LENS_FILL_INTENSITY_MIN * (span ** (max(0, min(100, pos)) / 100.0))


def slider_from_intensity(intensity: float) -> int:
    """Inverse of intensity_from_slider, rounded to the nearest position."""
    k = max(LENS_FILL_INTENSITY_MIN,
            min(LENS_FILL_INTENSITY_MAX, float(intensity)))
    span = LENS_FILL_INTENSITY_MAX / LENS_FILL_INTENSITY_MIN
    return round(100.0 * math.log(k / LENS_FILL_INTENSITY_MIN) / math.log(span))


def _polygonize_lines(coord_lists: list) -> tuple[list, bool]:
    """Stitch flattened polylines into faces, tolerating snapped endpoints.

    Returns ``(faces, has_leak)``: ``faces`` are Shapely polygons formed by the
    linework (a nested opening comes back already punched into its enclosing
    face's interior); ``has_leak`` is True when some line fails to close into a
    ring (a dangling or half-drawn perimeter). This is what lets Frame Fill work
    on an unjoined half whose endpoints are snapped to the mirror line — the
    real half and its ghost share endpoints and polygonize into one face."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize_full, unary_union, snap

    # Round to 1e-6 mm before building rings: a sampled circle's closing point
    # lands ~1e-15 off its start, which leaves the ring technically un-closed
    # (is_ring False) so polygonize would drop it as an open edge. Rounding
    # kills that fp noise while staying far finer than the snap tolerance.
    lines = [LineString([(round(x, 6), round(y, 6)) for x, y in c])
             for c in coord_lists if len(c) >= 2]
    if not lines:
        return [], False
    merged = unary_union(lines)                       # node true crossings
    merged = unary_union(snap(merged, merged,         # then close snapped gaps
                              _FILL_STITCH_TOL_MM))
    polys, dangles, cuts, _invalid = polygonize_full(merged)
    faces = list(polys.geoms) if not polys.is_empty else []
    has_leak = (not dangles.is_empty) or (not cuts.is_empty)
    return faces, has_leak


def _shapely_to_qpath(geom) -> QPainterPath:
    """Convert a Shapely (Multi)Polygon to a QPainterPath, holes included.
    Interior rings are added as their own closed subpaths; the default
    odd-even fill rule punches them out."""
    from shapely.geometry import Polygon
    path = QPainterPath()
    if geom is None or geom.is_empty:
        return path
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for poly in polys:
        if not isinstance(poly, Polygon):
            continue
        for ring in (poly.exterior, *poly.interiors):
            pts = list(ring.coords)
            if len(pts) < 3:
                continue
            path.moveTo(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
    return path


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
        # Material swatch. When a pixmap is loaded the profile is painted with
        # it instead of the flat colour; the colour is kept so clearing the
        # swatch returns to exactly what the maker had picked.
        self._fill_image_path: str = ""
        self._fill_image_pixmap: QPixmap | None = None
        self._fill_blank_w: float = DEFAULT_FILL_BLANK_W_MM
        # (status) -> None; fired when a geometry edit breaks the perimeter so
        # the fill can no longer close, so the app can untick the box + notify.
        self.fill_auto_disabled = None
        # Lens fill overlay (display-only; never exported). One top→bottom
        # gradient definition, painted into every LENS aperture separately so a
        # pair reads as two matching tinted lenses rather than one gradient
        # smeared across the whole front.
        self._lens_fill_visible: bool = False
        self._lens_fill_top    = QColor(DEFAULT_LENS_FILL_TOP)
        self._lens_fill_bottom = QColor(DEFAULT_LENS_FILL_BOTTOM)
        self._lens_fill_opacity: float = DEFAULT_LENS_FILL_OPACITY
        self._lens_fill_intensity: float = DEFAULT_LENS_FILL_INTENSITY
        self._lens_fill_items: list[QGraphicsPathItem] = []
        # (status) -> None; same contract as fill_auto_disabled, for the lenses.
        self.lens_fill_auto_disabled = None
        # Coalesces hot-path fill rebuilds (add/remove/refresh fire per mouse
        # move during drags) into one boolean-ops pass per event-loop tick.
        # Child timer so a pending tick dies with the scene.
        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.setInterval(0)
        self._fill_timer.timeout.connect(self._rebuild_overlays)
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
        self._rebuild_overlays()

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

    def set_fill_visible(self, on: bool) -> str:
        """Show or hide the frame fill. Returns the readiness status the fill
        was resolved at: ``"ok"`` (shown), ``"leak"`` (an OUTLINE perimeter is
        present but doesn't close, so nothing is shown), or ``"empty"`` (no
        OUTLINE geometry yet). Callers turning the fill on can inspect the
        return to explain why it stayed off; hiding always returns ``"ok"``."""
        if not on:
            self._fill_visible = False
            if self._fill_item is not None:
                self._fill_item.setVisible(False)
            return "ok"
        path, status = self._compute_fill()
        if status != "ok":
            self._fill_visible = False
            if self._fill_item is not None:
                self._fill_item.setVisible(False)
            return status
        self._fill_visible = True
        self._apply_fill_path(path)
        return "ok"

    def set_fill_color(self, color):
        """color: QColor or '#rrggbb' string."""
        self._fill_color = QColor(color)
        self.rebuild_fill()

    def set_fill_opacity(self, opacity: float):
        self._fill_opacity = max(0.0, min(1.0, opacity))
        self.rebuild_fill()

    def set_fill_image(self, path: str) -> bool:
        """Paint the frame profile with a material swatch instead of a colour.

        *path* is any readable image — a supplier's acetate sample sheet is the
        case this exists for. Returns False when the file can't be read as an
        image, leaving the colour fill untouched; an empty path clears back to
        the colour."""
        if not path:
            self.clear_fill_image()
            return True
        pm = QPixmap(path)
        if pm.isNull():
            return False
        if max(pm.width(), pm.height()) > FILL_IMAGE_MAX_PX:
            pm = pm.scaled(FILL_IMAGE_MAX_PX, FILL_IMAGE_MAX_PX,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self._fill_image_path = path
        self._fill_image_pixmap = pm
        self.rebuild_fill()
        return True

    def clear_fill_image(self):
        """Back to the flat colour fill, keeping the colour as it was picked."""
        self._fill_image_path = ""
        self._fill_image_pixmap = None
        self.rebuild_fill()

    def has_fill_image(self) -> bool:
        return self._fill_image_pixmap is not None

    def fill_image_path(self) -> str:
        return self._fill_image_path

    def set_fill_blank_width(self, mm: float):
        """Width of the stock blank the swatch spans (mm) — the Stock Blank
        guide's width, whether or not that guide is being shown."""
        w = float(mm)
        if w <= 0.0 or w == self._fill_blank_w:
            return
        self._fill_blank_w = w
        self.rebuild_fill()

    def fill_blank_width(self) -> float:
        return self._fill_blank_w

    def fill_state(self) -> dict:
        return {"visible": self._fill_visible,
                "color":   self._fill_color.name(),
                "opacity": self._fill_opacity,
                "image":   self._fill_image_path}

    def outline_fill_status(self) -> str:
        """Readiness of the OUTLINE perimeter for filling, without drawing
        anything: ``"ok"`` / ``"leak"`` / ``"empty"`` (see set_fill_visible)."""
        return self._compute_fill()[1]

    def fill_paint_spec(self) -> dict | None:
        """What the frame fill would paint, for a painter that isn't this
        scene — the catalog PDF re-renders the overlay onto paper.

        ``{"path": QPainterPath (scene mm), "brush": QBrush, "opacity":
        float}``, or None while the fill is hidden or the perimeter can't
        close. The brush carries the material swatch and its scene-mm
        transform, so a caller drawing under the same coordinate system gets
        the swatch landing exactly where the canvas puts it."""
        if not self._fill_visible:
            return None
        path, status = self._compute_fill()
        if status != "ok" or path is None or path.isEmpty():
            return None
        return {"path":    path,
                "brush":   self._fill_brush(),
                # Mirrors _apply_fill_path: a texture brush has no alpha of
                # its own, so the fading is the painter's job for a swatch and
                # the brush's for a colour.
                "opacity": self._fill_opacity if self.has_fill_image() else 1.0}

    def lens_fill_paint_spec(self) -> list:
        """``[(QPainterPath, QBrush), ...]`` — one tinted aperture each, in
        scene mm — or ``[]`` while the lens fill is hidden or no aperture
        closes. Companion to fill_paint_spec for off-scene painters."""
        if not self._lens_fill_visible:
            return []
        paths, status = self._compute_lens_fill()
        if status != "ok" or not paths:
            return []
        return [(p, QBrush(self._lens_gradient(p.boundingRect())))
                for p in paths if not p.isEmpty()]

    def _schedule_fill_rebuild(self):
        """Deferred overlay rebuild for the hot paths (curve add/remove/refresh)."""
        if self._fill_visible or self._lens_fill_visible:
            self._fill_timer.start()

    def _rebuild_overlays(self):
        """Timer target: repaint whichever display-only fills are showing."""
        self.rebuild_fill()
        self.rebuild_lens_fill()

    def _fill_layer_lines(self, layer: Layer) -> list:
        """Flattened polylines for one layer's contribution to the fill: each
        visible real curve plus, for every ghost-eligible one, its live mirror
        image (so a half drawn against the mirror line contributes both sides).
        Returns [] when the layer is hidden."""
        from ..geometry import sample_curve, mirror_curve

        if not self.is_layer_visible(layer):
            return []
        horiz = getattr(self.mirror, "_horizontal", False) if self.mirror else False
        lines: list = []
        for item in self._curve_items.values():
            c = item.curve
            if c.layer != layer:
                continue
            lines.append([(x, y) for x, y, _t in sample_curve(c)])
            if self._ghost_eligible(c):
                gc = mirror_curve(c, self.mirror.x, horizontal=horiz)
                lines.append([(x, y) for x, y, _t in sample_curve(gc)])
        return lines

    def _compute_fill(self):
        """Resolve the fill region. Returns ``(QPainterPath | None, status)``
        where status is ``"ok"`` / ``"leak"`` / ``"empty"``.

        The OUTLINE layer (real curves + live mirror ghosts) is stitched into
        faces: the face with the largest outer ring is the frame profile, and
        because a nested opening comes back already punched into that face's
        interior, decorative holes — an aviator's bridge keyhole — fall out for
        free. Rings that don't close leave the perimeter leaking (status
        ``"leak"``) rather than filling something half-formed. LENS apertures
        (also real + ghost) are then subtracted."""
        from shapely.geometry import Polygon

        outline_lines = self._fill_layer_lines(Layer.OUTLINE)
        if not outline_lines:
            return None, "empty"
        faces, leak = _polygonize_lines(outline_lines)
        if leak or not faces:
            return None, "leak"

        fill = max(faces, key=lambda f: Polygon(f.exterior).area)
        lens_faces, _ = _polygonize_lines(self._fill_layer_lines(Layer.LENS))
        for lf in lens_faces:
            fill = fill.difference(lf)
        return _shapely_to_qpath(fill), "ok"

    def _apply_fill_path(self, path: QPainterPath):
        """Paint *path* into the (lazily created) fill item and show it."""
        if self._fill_item is None:
            it = QGraphicsPathItem()
            # Above face photos (z=-1000…), below the origin cross (z=0)
            # and all geometry (z=10).
            it.setZValue(-500)
            it.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, False)
            self.addItem(it)
            self._fill_item = it
        self._fill_item.setBrush(self._fill_brush())
        # A texture brush has no alpha of its own, so the item does the fading
        # for a swatch — the face photo reads through it exactly as it does
        # through a colour. Colour keeps its alpha in the brush (item opacity
        # 1.0) so the two paths can't compound.
        self._fill_item.setOpacity(
            self._fill_opacity if self.has_fill_image() else 1.0)
        self._fill_item.setPen(QPen(Qt.PenStyle.NoPen))
        self._fill_item.setPath(path)
        self._fill_item.setVisible(True)

    def _fill_brush(self) -> QBrush:
        """Brush for the frame profile: the material swatch when one is loaded,
        otherwise the flat colour at its own alpha.

        The swatch is scaled to span the blank's width and centred vertically on
        the origin, matching how the Stock Blank guide sits — so what fills the
        frame is the part of the sheet under it. Qt tiles a texture brush, so
        geometry drawn past the blank continues the pattern instead of falling
        to nothing; the maker sees the frame in the material either way, and the
        Stock guide is what tells them it no longer fits the sheet."""
        pm = self._fill_image_pixmap
        if pm is None or pm.width() <= 0:
            color = QColor(self._fill_color)
            color.setAlphaF(self._fill_opacity)
            return QBrush(color)
        scale  = self._fill_blank_w / float(pm.width())
        h_mm   = pm.height() * scale
        brush  = QBrush(pm)
        brush.setTransform(
            QTransform().translate(-self._fill_blank_w / 2.0,
                                   -h_mm / 2.0).scale(scale, scale))
        return brush

    def rebuild_fill(self):
        """Recompute and repaint the fill while it's visible. If a geometry
        edit has broken the OUTLINE perimeter so it no longer encloses a
        region, the fill can't be shown honestly — turn it off and let the app
        know (fill_auto_disabled) rather than paint something broken. No-op
        while hidden so the stitch never runs during normal editing."""
        if not self._fill_visible:
            if self._fill_item is not None:
                self._fill_item.setVisible(False)
            return
        path, status = self._compute_fill()
        if status != "ok":
            self._fill_visible = False
            if self._fill_item is not None:
                self._fill_item.setVisible(False)
            if self.fill_auto_disabled is not None:
                self.fill_auto_disabled(status)
            return
        self._apply_fill_path(path)

    # ------------------------------------------------------------------
    # Lens fill overlay (display-only — never exported)
    # ------------------------------------------------------------------

    def set_lens_fill_visible(self, on: bool) -> str:
        """Show or hide the lens fill. Returns the readiness status it was
        resolved at: ``"ok"`` (shown), ``"leak"`` (LENS geometry is present but
        no aperture closes, so nothing is shown), or ``"empty"`` (no LENS
        geometry yet). Hiding always returns ``"ok"``."""
        if not on:
            self._lens_fill_visible = False
            self._clear_lens_fill_items()
            return "ok"
        paths, status = self._compute_lens_fill()
        if status != "ok":
            self._lens_fill_visible = False
            self._clear_lens_fill_items()
            return status
        self._lens_fill_visible = True
        self._apply_lens_fill_paths(paths)
        return "ok"

    def set_lens_fill_colors(self, top, bottom):
        """top/bottom: QColor or '#rrggbb'. Bottom is the lower gradient stop."""
        self._lens_fill_top    = QColor(top)
        self._lens_fill_bottom = QColor(bottom)
        self.rebuild_lens_fill()

    def set_lens_fill_opacity(self, opacity: float):
        self._lens_fill_opacity = max(0.0, min(1.0, opacity))
        self.rebuild_lens_fill()

    def set_lens_fill_intensity(self, intensity: float):
        self._lens_fill_intensity = max(
            LENS_FILL_INTENSITY_MIN,
            min(LENS_FILL_INTENSITY_MAX, float(intensity)))
        self.rebuild_lens_fill()

    def lens_fill_state(self) -> dict:
        return {"visible":   self._lens_fill_visible,
                "top":       self._lens_fill_top.name(),
                "bottom":    self._lens_fill_bottom.name(),
                "opacity":   self._lens_fill_opacity,
                "intensity": self._lens_fill_intensity}

    def lens_fill_status(self) -> str:
        """Readiness of the LENS apertures for filling, without drawing
        anything: ``"ok"`` / ``"leak"`` / ``"empty"`` (see set_lens_fill_visible)."""
        return self._compute_lens_fill()[1]

    def _compute_lens_fill(self):
        """Resolve one fill region per lens. Returns ``(list[QPainterPath] |
        None, status)`` — one path per closed LENS aperture (real curves plus
        live mirror ghosts, so a single drawn lens tints both sides)."""
        lens_lines = self._fill_layer_lines(Layer.LENS)
        if not lens_lines:
            return None, "empty"
        faces, _leak = _polygonize_lines(lens_lines)
        if not faces:
            # Unlike the frame profile a stray dangle is common here (a lens
            # under construction next to a finished one), so only a total
            # absence of enclosed area counts as a leak.
            return None, "leak"
        return [_shapely_to_qpath(f) for f in faces], "ok"

    def _clear_lens_fill_items(self):
        for it in self._lens_fill_items:
            self.removeItem(it)
        self._lens_fill_items.clear()

    def _lens_gradient(self, rect) -> QLinearGradient:
        """Top→bottom gradient spanning *rect* (one lens's own extent), so both
        lenses of a pair show the same tint run rather than slices of one."""
        top    = deepen_tint(self._lens_fill_top,    self._lens_fill_intensity)
        bottom = deepen_tint(self._lens_fill_bottom, self._lens_fill_intensity)
        top.setAlphaF(self._lens_fill_opacity)
        bottom.setAlphaF(self._lens_fill_opacity)
        grad = QLinearGradient(rect.center().x(), rect.top(),
                               rect.center().x(), rect.bottom())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        return grad

    def _apply_lens_fill_paths(self, paths: list):
        """Paint one item per lens. The lens count changes as geometry is drawn
        and undone, so the items are rebuilt outright rather than diffed."""
        self._clear_lens_fill_items()
        for path in paths:
            if path.isEmpty():
                continue
            it = QGraphicsPathItem()
            # Just above the frame fill (-500) — the lens apertures are punched
            # out of it — and below the origin cross (0) and geometry (10).
            it.setZValue(-495)
            it.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, False)
            it.setBrush(QBrush(self._lens_gradient(path.boundingRect())))
            it.setPen(QPen(Qt.PenStyle.NoPen))
            it.setPath(path)
            self.addItem(it)
            self._lens_fill_items.append(it)

    def rebuild_lens_fill(self):
        """Recompute and repaint the lens fill while it's visible. If an edit
        has opened every aperture there is nothing honest to paint — turn the
        fill off and tell the app (lens_fill_auto_disabled). No-op while
        hidden so the stitch never runs during normal editing."""
        if not self._lens_fill_visible:
            self._clear_lens_fill_items()
            return
        paths, status = self._compute_lens_fill()
        if status != "ok":
            self._lens_fill_visible = False
            self._clear_lens_fill_items()
            if self.lens_fill_auto_disabled is not None:
                self.lens_fill_auto_disabled(status)
            return
        self._apply_lens_fill_paths(paths)

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
        self._rebuild_overlays()

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
