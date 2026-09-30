import copy
import datetime
import json
import math
import os
import re
import sys
import time
import uuid
from pathlib import Path
from . import __version__
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStatusBar,
    QGraphicsView, QDockWidget, QWidget, QVBoxLayout, QGridLayout,
    QFormLayout, QGroupBox, QPushButton, QSlider, QLabel, QToolButton,
    QDoubleSpinBox, QFileDialog, QComboBox, QMessageBox,
    QDialog, QCheckBox, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem,
    QScrollArea, QTabWidget, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QColorDialog, QAbstractItemView, QRubberBand, QDialogButtonBox,
    QSizePolicy,
)
from PySide6.QtCore import (
    Qt, QByteArray, QEvent, QObject, QPointF, QSize, QTimer, Signal, QRect, QRectF,
    QPoint,
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QBrush, QFontMetrics, QIcon, QPainter,
    QPen, QPixmap,
)

from . import theme
from .canvas.items import CurveItem
from .canvas.dim import DimItem
from .canvas.measure_bar import MeasureBar
from .canvas.readiness_dot import ReadinessDot, readiness_state
from .canvas.scene import (FrameScene, TextItem, DEFAULT_LENS_FILL_TOP,
                           DEFAULT_LENS_FILL_BOTTOM, DEFAULT_LENS_FILL_OPACITY,
                           DEFAULT_LENS_FILL_INTENSITY, deepen_tint,
                           intensity_from_slider, slider_from_intensity,
                           LENS_FILL_INTENSITY_MIN, LENS_FILL_INTENSITY_MAX,
                           _GHOST_LAYERS)
from .canvas.snapping import SnapEngine
from .calibration import CalibTool
from .construction import ConstructionGuides, BoxingGuide, RectGuide
from . import prefs as _prefs_mod
from . import bpi_tints as _bpi_tints
from .document import (
    Layer, Calibration, MirrorAxis, FormingMetadata, MachinedBridge, FaceImage,
    Curve, SplineNode, ControlPoint, DimLine, WORKSPACE_LAYERS,
    BevelSpec, BEVEL_PRESETS,
)
from .geometry import mirror_curve, circle_to_spline, arc_to_spline
from .tools.draw import DrawTool
from .tools.edit import EditTool
from .tools.dim import DimTool
from .tools.circle import CircleTool
from .tools.trim import TrimTool
from .tools.fillet import FilletTool
from .tools.split import SplitTool
from .tools.offset import OffsetTool
from .tools.rebuild import RebuildSplineTool
from .tools.point_move import PointMoveTool
from .tools.text import TextTool, TextDialog
from .pinnable_toolbar import PinnableToolBar
from .tooltips import TooltipFilter
from .icons import ICONS_DIR as _ICONS_DIR, make_icon as _make_icon


# Color-bar size (px) inside the Lens Fill stop buttons.
_LENS_SWATCH_PX = (64, 14)


# Saved documents are ordinary files a maker can edit, share, or damage, and
# _load_ws_data runs outside the open-time try/except — so a malformed value in
# the metadata took the app down on open rather than degrading to a default.
def _hex_or(value, fallback: str) -> str:
    """*value* if it is a color Qt can parse, else *fallback*."""
    if isinstance(value, str) and QColor(value).isValid():
        return QColor(value).name()
    return fallback


def _num_or(value, fallback: float, lo: float, hi: float) -> float:
    """*value* as a float clamped to [lo, hi], else *fallback*."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    if out != out or out in (float("inf"), float("-inf")):   # NaN / ±inf
        return fallback
    return max(lo, min(hi, out))


def _curves_bbox(curves, layers=None, x_lo=None, x_hi=None):
    """Return (min_x, min_y, max_x, max_y) over matched curves, or None if empty.

    layers: set of Layer values to include; None = all layers.
    x_lo / x_hi: filter curves by node-centroid x to isolate one side of the mirror.
    """
    matched = []
    for c in curves:
        if layers and c.layer not in layers:
            continue
        if c.nodes and (x_lo is not None or x_hi is not None):
            cx = sum(n.x for n in c.nodes) / len(c.nodes)
            if x_lo is not None and cx < x_lo:
                continue
            if x_hi is not None and cx > x_hi:
                continue
        matched.append(c)
    if not matched:
        return None
    # Exact drawn extents (path bounds), not the control polygon: handles
    # pushed a 150 mm temple to "200 mm" in the Measurements panel.
    from .canvas.items import build_path
    rect = QRectF()
    for c in matched:
        if c.nodes:
            rect = rect.united(build_path(c).boundingRect())
    if rect.isNull():
        return None
    return (rect.left(), rect.top(), rect.right(), rect.bottom())


# Application stylesheet + canvas colors come from framedraft.theme
# (single palette source; the old hardcoded QSS / QSS_DARK pair lives there
# as one token-driven template).

_DOCK_WIDTH = 270

# The toolbar's buttons in its own order and sections, as Preferences ▸
# Toolbar lists them. Tuple: (prefs_key, display_label, user_hideable).
_TOOLBAR_SECTIONS = [
    ("Drawing Tools", [
        ("select",       "Select",                  False),
        ("line",         "Line",                    True),
        ("spline",       "Spline",                  True),
        ("circle",       "Circle",                  True),
        ("arc",          "Arc",                     True),
        ("arc_sec",      "Arc (3-point)",           True),
        ("fillet",       "Fillet",                  True),
        ("dim",          "Dim",                     True),
        ("text",         "Text",                    True),
        ("trim",         "Trim",                    True),
        ("split_curve",  "Split Curve",             True),
        ("offset",       "Offset",                  True),
        ("rebuild",      "Rebuild Spline",          True),
        ("point_move",   "Point Move",              True),
    ]),
    ("Guides and Snapping", [
        ("ghost",        "Ghost (mirror toggle)",   True),
        ("guides",       "Guides",                  True),
        ("snap",         "Snap",                    True),
        ("snap_palette", "Snap Palette",            True),
        ("grid",         "Grid",                    True),
        ("smooth",       "Smooth Handles",          True),
        ("boxing",       "Boxing",                  True),
        ("stock",        "Stock",                   True),
        ("pad",          "Pad",                     True),
    ]),
    ("Operations", [
        ("mirror",       "Mirror (bake)",           True),
        ("mirror_close", "Mirror-Close",            True),
        ("copy_temple",  "Temple Copy",             True),
        ("join",         "Join",                    True),
        ("snap_node",    "Snap Node",               True),
        ("split",        "Split",                   True),
        ("explode",      "Explode",                 True),
        ("fit",          "Fit",                     True),
    ]),
]
_TOOLBAR_ACTION_DEFS = [e for _section, entries in _TOOLBAR_SECTIONS for e in entries]

# Toolbar buttons that only make sense in some workspaces — hidden elsewhere
# whatever the prefs say (MainWindow._apply_toolbar_visibility).
_WS_ONLY_ACTIONS = {
    "guides":      ("front",),
    "boxing":      ("front",),
    "pad":         ("front",),
    "copy_temple": ("temple_r", "temple_l"),
    # ENGRAVING only exists in temple workspaces (WORKSPACE_LAYERS)
    "text":        ("temple_r", "temple_l"),
}

# Shortcuts bound outside the hotkey table (menus and window QShortcuts).
# Preferences ▸ Hotkeys lists every one, and SettingsDialog._RESERVED_KEYS —
# which refuses them as hotkeys — is built from this list.
_FIXED_SHORTCUTS = [
    ("New",         ("Ctrl+N",)),
    ("Open",        ("Ctrl+O",)),
    ("Save",        ("Ctrl+S",)),
    ("Save As",     ("Ctrl+Shift+S",)),
    ("Undo",        ("Ctrl+Z",)),
    ("Redo",        ("Ctrl+Y", "Ctrl+Shift+Z")),
    ("Copy",        ("Ctrl+C",)),
    ("Paste",       ("Ctrl+V",)),
    ("Duplicate",   ("Ctrl+D",)),
    ("Select All",  ("Ctrl+A",)),
    ("Transform",   ("Ctrl+T",)),
    ("Group",       ("Ctrl+G",)),
    ("Ungroup",     ("Ctrl+Shift+G",)),
    ("Zoom In",     ("Ctrl++", "Ctrl+=")),
    ("Zoom Out",    ("Ctrl+-",)),
    ("Fit",         ("Ctrl+0",)),
    ("Preferences", ("Ctrl+,",)),
    ("Quit",        ("Ctrl+Q",)),
    ("Delete",      ("Del", "Backspace")),
    ("Cancel",      ("Esc",)),
]

# Keys the tools read while a value is being typed into the canvas (a Line
# length, a Fillet radius): a hotkey on one fired mid-number — bound to "1",
# typing a 15 mm length switched tools on the first digit.
_TYPING_KEYS = frozenset([*"0123456789", ".", ",", "-", "Return", "Enter",
                          "Tab", "Backtab"])

# Ordered hotkey action definitions used by SettingsDialog.
# Tuple: (prefs_key, display_label)
_HOTKEY_ACTION_DEFS = [
    ("line",         "Line tool"),
    ("spline",       "Spline tool"),
    ("circle",       "Circle tool"),
    ("arc",          "Arc tool"),
    ("arc_sec",      "Arc 3-point tool"),
    ("fillet",       "Fillet tool"),
    ("dim",          "Dim tool"),
    ("trim",         "Trim tool"),
    ("split_curve",  "Split Curve tool"),
    ("offset",       "Offset tool"),
    ("rebuild",      "Rebuild Spline tool"),
    ("point_move",   "Point Move tool"),
    ("text",         "Text tool"),
    ("snap_node_ep", "Snap Node to Endpoint"),
    ("move_gizmo",   "Move gizmo"),
    ("join",         "Join curves"),
    ("bookmark",     "Bookmark revision"),
    ("insert_square", "Insert □ (size notation)"),
]

# A hotkey as a tooltip names it, "(O)" or "(Ctrl+B)", after the tool's name.
_TIP_KEY = re.compile(r"\s*\((?:(?:Ctrl|Shift|Alt|Meta)\+)*[A-Z0-9][A-Za-z0-9]*\)\s*$")


def _tip_with_key(tip: str, key: str) -> str:
    """`tip` with the hotkey after the name that heads it ("Offset (O): …"),
    replacing any key written there before; no key, no parentheses. The keys
    were typed into the tooltips by hand, so a rebound tool kept naming its
    old one, and most tools named none."""
    head, sep, rest = tip.partition(":")
    if not sep:
        return tip
    head = _TIP_KEY.sub("", head)
    return f"{head} ({key}):{rest}" if key else f"{head}:{rest}"


# Hotkeys that INSERT INTO text fields. Unlike every other binding (which the
# _hotkey_dispatch guard silences while a text widget has focus), these only
# mean something while typing — they bypass the guard and use application
# scope so they reach modal dialogs (bookmark names, library saves, the
# engraving text dialog).
_TEXT_FIELD_HOTKEYS = {"insert_square"}


def _insert_text_into(widget, text: str) -> bool:
    """Type *text* at the cursor of a Qt text-entry widget; False if *widget*
    isn't one (the hotkey is then a silent no-op)."""
    from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
    if isinstance(widget, QLineEdit):
        widget.insert(text)
        return True
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        widget.insertPlainText(text)
        return True
    return False


def _matches_key_event(seq, event) -> bool:
    """True when a KeyPress *event* is exactly the bound sequence *seq*."""
    from PySide6.QtGui import QKeySequence
    if seq is None or seq.isEmpty():
        return False
    return (QKeySequence(event.keyCombination()).matches(seq)
            == QKeySequence.SequenceMatch.ExactMatch)


class CanvasView(QGraphicsView):
    """QGraphicsView: wheel-zoom, middle-click pan, tool event routing."""

    zoom_changed = Signal(int)  # current zoom as integer percent (100 = 100%)

    _MIN_ZOOM = 0.01    # 1%
    _MAX_ZOOM = 100.0   # 10,000%

    def __init__(self, scene: FrameScene, status_bar: QStatusBar):
        super().__init__(scene)
        self._status_bar = status_bar
        # The pointer's coordinates have a field of their own (MainWindow's
        # "coordsLabel"): written as the bar's message they replaced every
        # tool's prompt on the first mouse move.
        self._coords_label = status_bar.findChild(QLabel, "coordsLabel")
        self._calib_tool: CalibTool | None = None
        self._draw_tool:  DrawTool  | None = None
        self._dim_tool    = None
        self._pan_active = False
        self._pan_start = QPointF()
        self._delete_callback = None
        self._insert_node_callback = None
        self._snap_to_endpoint_callback = None
        self._move_pre_cb   = None   # () -> None, called once on drag-move start
        self._move_cb       = None   # (dx_mm, dy_mm) -> None
        self._move_end_cb   = None   # () -> None, called when drag-move ends
        self._escape_cb     = None   # () -> None, called on Esc with no active tool
        self._drag_move_start: QPointF | None = None
        self._drag_move_items: list = []   # pre-click selected items captured at press
        self._drag_moving      = False
        self._drag_pre_called  = False
        # Manual rubber-band selection (plain left-drag). Qt's built-in band is
        # suppressed once the press lands on an item, which made box-select
        # impossible over dense geometry; we drive our own band so a drag from
        # anywhere — empty space or on top of a curve — selects everything it
        # encloses/crosses.
        self._rb_origin: QPoint | None = None     # viewport press point
        self._rb_band:  QRubberBand | None = None
        self._rb_press_item = None                # CurveItem under press (click-select)
        self._rb_dragging   = False
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(theme.color("canvas.bg"))))
        # Vignette overlay (Preferences ▸ Appearance): 0 = off; the gradient
        # pixmap is cached per viewport size so painting is one blit.
        self._vignette: int = 0
        self._vignette_pm: QPixmap | None = None
        # Grid overlay (drawn in drawBackground, scene coords). Off by
        # default; fallbacks mirror prefs.DEFAULTS (2 mm, major every 10 mm).
        self._grid_visible: bool  = False
        self._grid_spacing: float = 2.0    # mm
        self._grid_major:   int   = 5      # every Nth line is heavier
        self._grid_minor_color: str | None = None   # None = theme token
        self._grid_major_color: str | None = None   # None = theme token
        self._grid_major_width: float = 1.0          # device px, cosmetic

        self.measure_bar = MeasureBar(self)
        # With `self` as context: a bare singleShot outlives the view and
        # fired into a deleted MeasureBar.
        QTimer.singleShot(0, self, self._reposition_measure_bar)

    # ------------------------------------------------------------------
    # Grid overlay (mm grid with major/minor divisions, drawn behind all)
    # ------------------------------------------------------------------

    def set_grid(self, visible: bool | None = None, spacing_mm: float | None = None,
                 major: int | None = None, minor_color: str | None = None,
                 major_color: str | None = None,
                 major_width: float | None = None):
        """Update grid config; color arguments use "" to fall back to the
        theme tokens (None leaves the current value untouched)."""
        if visible is not None:
            self._grid_visible = bool(visible)
        if spacing_mm is not None and spacing_mm > 0:
            self._grid_spacing = float(spacing_mm)
        if major is not None and major >= 1:
            self._grid_major = int(major)
        if minor_color is not None:
            self._grid_minor_color = minor_color or None
        if major_color is not None:
            self._grid_major_color = major_color or None
        if major_width is not None and major_width > 0:
            self._grid_major_width = float(major_width)
        self.viewport().update()

    _GRID_MIN_PX = 4.0   # hide a line level once its screen spacing drops below this

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)   # fills the canvas background
        if not self._grid_visible or self._grid_spacing <= 0:
            return
        sp    = self._grid_spacing
        major = max(1, self._grid_major)
        scale = abs(self.transform().m11())
        draw_minor = sp * scale >= self._GRID_MIN_PX
        draw_major = sp * major * scale >= self._GRID_MIN_PX
        if not draw_major:
            return   # too far zoomed out — even major lines would be a smear

        minor_col = self._grid_minor_color or theme.color("canvas.grid_minor")
        major_col = self._grid_major_color or theme.color("canvas.grid_major")
        minor_pen = QPen(QColor(minor_col), 0)
        minor_pen.setCosmetic(True)
        major_pen = QPen(QColor(major_col), self._grid_major_width)
        major_pen.setCosmetic(True)

        i0 = math.floor(rect.left()   / sp)
        i1 = math.ceil(rect.right()  / sp)
        j0 = math.floor(rect.top()    / sp)
        j1 = math.ceil(rect.bottom() / sp)
        top, bot, left, right = rect.top(), rect.bottom(), rect.left(), rect.right()

        for i in range(i0, i1 + 1):
            is_major = (i % major == 0)
            if is_major:
                painter.setPen(major_pen)
            elif draw_minor:
                painter.setPen(minor_pen)
            else:
                continue
            x = i * sp
            painter.drawLine(QPointF(x, top), QPointF(x, bot))
        for j in range(j0, j1 + 1):
            is_major = (j % major == 0)
            if is_major:
                painter.setPen(major_pen)
            elif draw_minor:
                painter.setPen(minor_pen)
            else:
                continue
            y = j * sp
            painter.drawLine(QPointF(left, y), QPointF(right, y))

    # ------------------------------------------------------------------
    # Vignette (viewport-space radial darkening, intensity 0–100)
    # ------------------------------------------------------------------

    def set_vignette(self, intensity: int):
        self._vignette = max(0, min(100, int(intensity)))
        self._vignette_pm = None
        self.viewport().update()

    def _render_vignette(self) -> QPixmap:
        from PySide6.QtGui import QRadialGradient
        size = self.viewport().size()
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        w, h = size.width(), size.height()
        g = QRadialGradient(w / 2.0, h / 2.0, math.hypot(w, h) / 2.0)
        g.setColorAt(0.0, QColor(0, 0, 0, 0))
        g.setColorAt(0.55, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 0, 0, round(self._vignette / 100.0 * 140)))
        p = QPainter(pm)
        p.fillRect(0, 0, w, h, QBrush(g))
        p.end()
        return pm

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self._vignette <= 0:
            return
        if (self._vignette_pm is None
                or self._vignette_pm.size() != self.viewport().size()):
            self._vignette_pm = self._render_vignette()
        painter.save()
        painter.resetTransform()
        painter.drawPixmap(0, 0, self._vignette_pm)
        painter.restore()

    def set_delete_callback(self, cb):
        self._delete_callback = cb

    def set_insert_node_callback(self, cb):
        self._insert_node_callback = cb

    def set_snap_to_endpoint_callback(self, cb):
        self._snap_to_endpoint_callback = cb

    def set_move_callbacks(self, pre_cb, move_cb, end_cb=None):
        self._move_pre_cb = pre_cb
        self._move_cb     = move_cb
        self._move_end_cb = end_cb

    def set_escape_callback(self, cb):
        self._escape_cb = cb

    def set_face_moved_callback(self, cb):
        """Called after a drag moved an unlocked reference photo: its place is
        saved with the design, and the drag left the design looking clean."""
        self._face_moved_cb = cb

    def _face_positions(self) -> list:
        return [it.pos() for it in getattr(self.scene(), "_face_items", [])]

    def set_calib_tool(self, tool: CalibTool):
        self._calib_tool = tool

    def set_draw_tool(self, tool: DrawTool | None):
        self._draw_tool = tool
        if tool is None and self._dim_tool is None:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        elif tool is not None:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        # Disable scene item selection while drawing; on return to Select,
        # re-enable only what layer visibility/locking allows.
        sc = self.scene()
        for item in sc.items():
            if isinstance(item, CurveItem):
                allowed = (tool is None
                           and sc.is_layer_visible(item.curve.layer)
                           and not sc.is_layer_locked(item.curve.layer))
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, allowed)
            elif isinstance(item, TextItem):
                allowed = (tool is None
                           and sc.is_layer_visible(item.text_obj.layer)
                           and not sc.is_layer_locked(item.text_obj.layer))
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, allowed)
                # Never ItemIsMovable: a text moves through the app's own drag
                # (snapshot, gizmo, measurements), as TextItem says. Setting it
                # here after any tool switch let Qt drag text on its own — a
                # jittery click moved it with no undo step and no star.

    def set_dim_tool(self, tool):
        self._dim_tool = tool
        if tool is not None:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif self._draw_tool is None:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def _reposition_measure_bar(self):
        self.measure_bar.reposition()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def focusNextPrevChild(self, next: bool) -> bool:
        # Suppress Tab focus traversal while a drawing tool is active so Tab can
        # be forwarded to the tool's handle_key for field switching.
        if self._draw_tool and self._draw_tool.active:
            return False
        return super().focusNextPrevChild(next)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_measure_bar()
        self._ensure_scroll_room()

    def _ensure_scroll_room(self):
        """Grow this view's sceneRect so panning always reaches the geometry.

        The FrameScene pins its own sceneRect to the face image / default
        extents; left alone, the scrollbars clamp to that rect and you can't
        pan out to geometry drawn beyond it once zoomed in (and AnchorUnderMouse
        zoom drifts off the cursor when it hits that clamp). We give the *view*
        a generous sceneRect = (content ∪ visible area ∪ scene rect) padded by
        one viewport on every side, leaving the scene's own rect untouched for
        face/PNG/print rendering.
        """
        sc = self.scene()
        if sc is None:
            return
        vis = self.mapToScene(self.viewport().rect()).boundingRect()
        rect = sc.itemsBoundingRect()
        if rect.isNull():
            rect = vis
        else:
            rect = rect.united(vis)
        rect = rect.united(sc.sceneRect())
        # One-viewport pad so the user can always drag a full screen past content.
        rect.adjust(-vis.width(), -vis.height(), vis.width(), vis.height())
        self.setSceneRect(rect)

    def zoom_by(self, factor: float):
        """Scale the view by *factor*, clamped to [_MIN_ZOOM, _MAX_ZOOM]."""
        current = self.transform().m11()
        target  = max(self._MIN_ZOOM, min(self._MAX_ZOOM, current * factor))
        f = target / current
        if abs(f - 1.0) > 1e-9:
            self.scale(f, f)
        self.zoom_changed.emit(round(self.transform().m11() * 100))

    def fit_view(self, rect):
        """fitInView, then re-clamp into the wheel-zoom bounds — a tiny (or
        huge) scene rect must not land outside [_MIN_ZOOM, _MAX_ZOOM]."""
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_by(1.0)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return   # horizontal wheel tilt — not a zoom request
        # Ensure scroll room first so the anchor restore below has scrollbar
        # range to work with instead of drifting when it hits the old clamp.
        self._ensure_scroll_room()
        # Anchor manually. AnchorUnderMouse trusts QGraphicsView's internally
        # tracked mouse position, which only updates in the base
        # mouseMoveEvent — while a tool consumes moves that position goes
        # stale and every wheel tick yanked the viewport toward it (issue #3).
        vp_pos       = event.position()
        anchor_scene = self.mapToScene(vp_pos.toPoint())
        self.zoom_by(1.15 if delta > 0 else 1 / 1.15)
        self._ensure_scroll_room()
        after = self.mapFromScene(anchor_scene)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + round(after.x() - vp_pos.x()))
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + round(after.y() - vp_pos.y()))
        event.accept()

    def mousePressEvent(self, event):
        self._faces_at_press = self._face_positions()
        # A release lost to a modal dialog (a hotkey mid-drag) must not leave
        # a band or a pan armed for the next press.
        if self._rb_origin is not None:
            if self._rb_band is not None:
                self._rb_band.hide()
            self._rb_origin = None
            self._rb_press_item = None
            self._rb_dragging = False
        if self._pan_active and event.button() != Qt.MouseButton.MiddleButton:
            self._pan_active = False
            self.unsetCursor()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = True
            self._pan_start = event.position()
            self._ensure_scroll_room()   # once per pan, not per mouse move
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif (event.button() != Qt.MouseButton.LeftButton
                and ((self._calib_tool and self._calib_tool.active)
                     or (self._dim_tool and self._dim_tool.active)
                     or (self._draw_tool and self._draw_tool.active))):
            # A tool answers the left button only: a right-click split or
            # trimmed the curve under it, or placed a node, like a left one.
            event.accept()
        elif self._calib_tool and self._calib_tool.active:
            pos = self.mapToScene(event.position().toPoint())
            self._calib_tool.handle_press(pos, self.scene())
            event.accept()
        elif self._dim_tool and self._dim_tool.active:
            pos      = self.mapToScene(event.position().toPoint())
            mods     = event.modifiers()
            use_snap = not (mods & Qt.KeyboardModifier.ControlModifier)
            self._dim_tool.handle_press(pos, use_snap)
            event.accept()
        elif self._draw_tool and self._draw_tool.active:
            pos       = self.mapToScene(event.position().toPoint())
            mods      = event.modifiers()
            use_snap  = not (mods & Qt.KeyboardModifier.ControlModifier)
            constrain = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self._draw_tool.handle_press(pos, use_snap, constrain)
            event.accept()
        else:
            # Alt+click: cycle through overlapping selectable items in Z-order.
            # self.items(QPoint) tests against item shapes, returns highest-Z first.
            if (event.button() == Qt.MouseButton.LeftButton
                    and event.modifiers() & Qt.KeyboardModifier.AltModifier):
                vp_pos = event.position().toPoint()
                candidates = [it for it in self._items_near(vp_pos)
                              if self._rb_selectable(it)]
                if len(candidates) >= 2:
                    selected_ids = {id(it) for it in self.scene().selectedItems()}
                    current_idx = next(
                        (i for i, it in enumerate(candidates) if id(it) in selected_ids),
                        -1,
                    )
                    next_idx = (current_idx + 1) % len(candidates)
                    self.scene().clearSelection()
                    candidates[next_idx].setSelected(True)
                    self._status_bar.showMessage(
                        f"Alt+click: item {next_idx + 1} of {len(candidates)} overlapping"
                    )
                    event.accept()
                    return
            # Track potential drag-to-move (plain left-click, no modifiers)
            mods = event.modifiers()
            if (event.button() == Qt.MouseButton.LeftButton
                    and not (mods & Qt.KeyboardModifier.ControlModifier)
                    and not (mods & Qt.KeyboardModifier.ShiftModifier)
                    and not (mods & Qt.KeyboardModifier.AltModifier)):
                vp_pos    = event.position().toPoint()
                scene_pos = self.mapToScene(vp_pos)
                # Dots, gizmo arrows and dims take the press themselves (a dim
                # runs its own offset-drag; intercepting it would translate
                # the anchors instead). Curves and texts are picked with a
                # screen-pixel tolerance so they stay clickable at any zoom.
                top_item = self._top_pick(vp_pos)
                hit_selected = any(it.isSelected() for it in self._items_near(vp_pos)
                                   if isinstance(it, (CurveItem, DimItem, TextItem)))
                self._drag_moving     = False
                self._drag_pre_called = False
                if isinstance(top_item, (CurveItem, TextItem)) and hit_selected:
                    # Press on an ALREADY-SELECTED item → drag to move it (a
                    # text rides the same path as curves and dims, so a mixed
                    # selection moves as one). Capture the pre-click selection
                    # now — super() may reselect only the topmost item.
                    self._drag_move_items = [
                        it for it in self.scene().selectedItems()
                        if isinstance(it, (CurveItem, DimItem, TextItem))
                    ]
                    self._drag_move_start = scene_pos
                    super().mousePressEvent(event)
                elif top_item is None or isinstance(top_item, (CurveItem, TextItem)):
                    # Empty space or an UNSELECTED curve/text → manual
                    # rubber-band (drag) or click-select (no drag). We take
                    # over selection so a box-drag works even when it starts
                    # on top of a curve.
                    self._drag_move_items = []
                    self._drag_move_start = None
                    self._rb_origin     = vp_pos
                    self._rb_press_item = top_item
                    self._rb_dragging   = False
                    event.accept()
                    return
                else:
                    # NodeDot, HandleDot, gizmo arrow, DimItem — default handling.
                    self._drag_move_items = []
                    self._drag_move_start = None
                    super().mousePressEvent(event)
            else:
                self._drag_move_items = []
                self._drag_move_start = None
                if (event.button() == Qt.MouseButton.LeftButton
                        and mods == Qt.KeyboardModifier.ControlModifier):
                    # Ctrl+click toggles with the same pixel tolerance as a
                    # plain click; Qt's own hit test wanted the pointer on
                    # the stroke itself, so it missed at low zoom.
                    top_item = self._top_pick(event.position().toPoint())
                    if top_item is not None and self._rb_selectable(top_item):
                        top_item.setSelected(not top_item.isSelected())
                        event.accept()
                        return
                super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            # A quick second pan stroke arrives as a double-click only.
            self.mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return
        if self._draw_tool and self._draw_tool.active:
            pos       = self.mapToScene(event.position().toPoint())
            mods      = event.modifiers()
            use_snap  = not (mods & Qt.KeyboardModifier.ControlModifier)
            constrain = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self._draw_tool.handle_dbl_click(pos, use_snap, constrain)
            event.accept()
        elif ((self._dim_tool and self._dim_tool.active)
                or (self._calib_tool and self._calib_tool.active)):
            # The press already placed a point; a double-click must not fall
            # through to select-mode node insertion on the curve underneath.
            event.accept()
        else:
            # Double-click on a CurveItem in select mode → insert node
            vp_pos    = event.position().toPoint()
            scene_pos = self.mapToScene(vp_pos)
            item = self._top_pick(vp_pos)
            # Selectable only: a curve on a locked (or hidden) layer took a
            # new node from a double-click, with an undo step and a star.
            if (isinstance(item, CurveItem) and self._rb_selectable(item)
                    and self._insert_node_callback):
                self._insert_node_callback(item.curve, scene_pos)
                event.accept()
                return
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        if self._coords_label is not None:
            self._coords_label.setText(self._fmt(scene_pos))
        else:
            self._status_bar.showMessage(self._fmt(scene_pos))
        if self._pan_active:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
        elif self._calib_tool and self._calib_tool.active:
            self._calib_tool.handle_move(scene_pos, self.scene())
        elif self._dim_tool and self._dim_tool.active:
            mods     = event.modifiers()
            use_snap = not (mods & Qt.KeyboardModifier.ControlModifier)
            self._dim_tool.handle_move(scene_pos, use_snap)
        elif self._draw_tool and self._draw_tool.active:
            mods      = event.modifiers()
            use_snap  = not (mods & Qt.KeyboardModifier.ControlModifier)
            constrain = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self._draw_tool.handle_move(scene_pos, use_snap, constrain)
        elif (self._rb_origin is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            # Manual rubber-band selection in progress.
            cur = event.position().toPoint()
            if not self._rb_dragging:
                if (cur - self._rb_origin).manhattanLength() > 4:
                    self._rb_dragging = True
                    if self._rb_band is None:
                        self._rb_band = QRubberBand(
                            QRubberBand.Shape.Rectangle, self.viewport())
            if self._rb_dragging:
                self._rb_band.setGeometry(
                    QRect(self._rb_origin, cur).normalized())
                self._rb_band.show()
                event.accept()
        else:
            # Drag-to-move selected items
            if (self._drag_move_start is not None
                    and event.buttons() & Qt.MouseButton.LeftButton):
                if not self._drag_moving:
                    vp_start = self.mapFromScene(self._drag_move_start)
                    vp_cur   = event.position().toPoint()
                    dist = math.hypot(vp_cur.x() - vp_start.x(),
                                      vp_cur.y() - vp_start.y())
                    if dist > 4:
                        self._drag_moving = True
                if self._drag_moving:
                    if not self._drag_pre_called and self._move_pre_cb:
                        self._drag_pre_called = True
                        self._move_pre_cb()
                    prev = self._drag_move_start
                    self._drag_move_start = scene_pos
                    if self._move_cb:
                        self._move_cb(scene_pos.x() - prev.x(),
                                      scene_pos.y() - prev.y())
                    event.accept()
                    return
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = False
            self.unsetCursor()
            event.accept()
            return
        if (self._rb_origin is not None
                and event.button() == Qt.MouseButton.LeftButton):
            self._finish_rubber_band()
            event.accept()
            return
        was_moving = self._drag_moving
        self._drag_move_start = None
        self._drag_moving     = False
        self._drag_pre_called = False
        if was_moving and self._move_end_cb:
            self._move_end_cb()
        super().mouseReleaseEvent(event)
        # Never let a press-time capture leak into a later operation —
        # stale captures made gizmo/point moves act on the wrong curves.
        self._drag_move_items = []
        cb = getattr(self, "_face_moved_cb", None)
        if cb is not None and getattr(self, "_faces_at_press", None) is not None \
                and self._face_positions() != self._faces_at_press:
            cb()
        self._faces_at_press = None

    @staticmethod
    def _rb_selectable(it) -> bool:
        if not isinstance(it, (CurveItem, DimItem, TextItem)):
            return False
        return bool(it.flags() & it.GraphicsItemFlag.ItemIsSelectable)

    _PICK_PX = 4   # half-size of the pick box, screen px (zoom-independent)

    def _items_near(self, vp_pos) -> list:
        """Curves, dims and texts under a small screen-pixel box around the
        cursor, topmost first. A curve's own hit stroke is 2 mm, which is
        half a pixel at 25 % zoom; the box keeps a hairline clickable at any
        zoom without claiming the interior of closed shapes."""
        r = self._PICK_PX
        rect = QRect(vp_pos.x() - r, vp_pos.y() - r, 2 * r + 1, 2 * r + 1)
        return [it for it in self.items(rect)
                if isinstance(it, (CurveItem, DimItem, TextItem))]

    def _top_pick(self, vp_pos):
        """What a press at *vp_pos* is aimed at: interactive chrome exactly
        under the cursor (node/handle dots, gizmo arrows, a dim) wins, then
        the topmost curve/text within the pick box, else None."""
        exact = self.itemAt(vp_pos)
        if exact is not None and not isinstance(exact, (CurveItem, TextItem)):
            flags = exact.flags()
            if (isinstance(exact, DimItem)
                    or flags & exact.GraphicsItemFlag.ItemIgnoresTransformations
                    or flags & exact.GraphicsItemFlag.ItemIsMovable):
                # Screen-sized chrome (node/handle dots, gizmo arrows), a dim,
                # or an unlocked face photo: each runs its own press handling.
                return exact
        for it in self._items_near(vp_pos):
            if isinstance(it, (CurveItem, TextItem)):
                return it
        return None

    def _finish_rubber_band(self):
        """Resolve a manual rubber-band press: box-select on drag, click-select
        (single item, or clear on empty) on a plain click."""
        dragging   = self._rb_dragging
        band       = self._rb_band
        press_item = self._rb_press_item
        self._rb_origin     = None
        self._rb_press_item = None
        self._rb_dragging   = False
        sc = self.scene()
        if dragging and band is not None:
            rect = band.geometry()
            band.hide()
            picked = [it for it in self.items(rect) if self._rb_selectable(it)]
            sc.select_items(picked)
            n = len(picked)
            self._status_bar.showMessage(
                f"Box selected {n} item{'s' if n != 1 else ''}")
        else:
            if band is not None:
                band.hide()
            # Plain click: select the pressed curve, or clear if empty.
            sc.clearSelection()
            if press_item is not None and self._rb_selectable(press_item):
                press_item.setSelected(True)

    def keyPressEvent(self, event):
        key = event.key()

        # Delete / Backspace: remove selected curves (select mode only)
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            tool_busy = ((self._draw_tool and self._draw_tool.active)
                         or (self._dim_tool and self._dim_tool.active)
                         or (self._calib_tool and self._calib_tool.active))
            if not tool_busy:
                if self._delete_callback:
                    self._delete_callback()
                event.accept()
                return

        if key == Qt.Key.Key_Escape:
            if self._calib_tool and self._calib_tool.active:
                self._calib_tool.cancel(self.scene())
                event.accept()
                return
            if self._dim_tool and self._dim_tool.active:
                self._dim_tool.handle_key(key)
                event.accept()
                return
            if self._draw_tool and self._draw_tool.active:
                self._draw_tool.handle_key(key, event.text())
                event.accept()
                return
            if self._escape_cb:
                self._escape_cb()
                event.accept()
                return
        elif self._dim_tool and self._dim_tool.active:
            if self._dim_tool.handle_key(key):
                event.accept()
                return
        elif self._draw_tool and self._draw_tool.active:
            if self._draw_tool.handle_key(key, event.text()):
                event.accept()
                return
        super().keyPressEvent(event)

    def _fmt(self, p: QPointF) -> str:
        return f"x: {p.x():.2f} mm  y: {p.y():.2f} mm"


class WorkspaceState:
    """All per-workspace runtime state: document, canvas, tools, and guides.

    One instance exists per workspace tab (front / temple / hinge).
    MainWindow holds a list[WorkspaceState] and exposes the active one via
    proxy properties so existing methods need no rewriting.
    """

    def __init__(self, workspace_type: str, status_bar, parent_win):
        self.workspace_type = workspace_type
        # Active drawing layer (what new curves are created on); driven by
        # the Layers panel in the Properties tab.
        self.active_layer: Layer = WORKSPACE_LAYERS[workspace_type][0]

        # ── Document state ────────────────────────────────────────────────
        self.doc_curves: list = []
        self.doc_dims:   list = []
        self.doc_texts:  list = []   # TextObject (ENGRAVING, M8)
        self.bookmarks:  list = []
        self.undo_stack: list = []
        self.redo_stack: list = []
        self.image_px_per_mm: float | None = None

        # ── Canvas ────────────────────────────────────────────────────────
        self.scene = FrameScene()
        self.scene.init_mirror(horizontal=(workspace_type in ("temple_r", "temple_l")))
        self.snap  = SnapEngine(self.scene)
        # Register the LIVE curve list once — in-place mutation keeps it
        # current forever. Previously only draw tools called set_doc_curves
        # on activation, so Point Move had zero snap targets until a draw
        # tool had been used in the workspace (the "can't place an imported
        # hinge point-to-point" bug).
        self.snap.set_doc_curves(self.doc_curves)
        self.view  = CanvasView(self.scene, status_bar)

        # ── Tools ─────────────────────────────────────────────────────────
        self.calib_tool  = CalibTool(parent_win)
        self.draw_tool   = DrawTool(parent_win)
        self.circle_tool = CircleTool(parent_win)
        self.edit_tool   = EditTool(self.scene, parent_win)
        self.dim_tool    = DimTool(parent_win)
        self.trim_tool   = TrimTool(parent_win)
        self.fillet_tool = FilletTool(parent_win)
        self.split_tool  = SplitTool(parent_win)
        self.offset_tool     = OffsetTool(parent_win)
        self.rebuild_tool    = RebuildSplineTool(parent_win)
        self.point_move_tool = PointMoveTool(parent_win)
        self.text_tool       = TextTool(parent_win)

        # ── Guides ────────────────────────────────────────────────────────
        self.const_guides = ConstructionGuides(self.scene)
        self.boxing_guide = BoxingGuide(self.scene)
        # Locked boxing derives its boxes from this workspace's live LENS curves.
        self.boxing_guide.set_lens_provider(
            lambda: [c for c in self.doc_curves if c.layer == Layer.LENS])
        self.stock_guide  = RectGuide(self.scene, "guide.stock")
        self.pad_guide    = RectGuide(self.scene, "guide.pad",
                                      width_mm=45.0, height_mm=45.0)

        # ── Move gizmo state ──────────────────────────────────────────────
        self.move_gizmo             = None
        self.move_gizmo_center      = QPointF(0, 0)
        self.drag_moving_curves:list = []
        self.drag_moving_dims:  list = []
        self.drag_moving_texts: list = []

        # ── Sidebar state saved/restored on tab switch ────────────────────
        _CG = ConstructionGuides
        self.mirror_enabled: bool  = True
        self.snap_enabled:   bool  = True
        self.smooth_handles: bool  = True
        self.guides_visible: bool  = True
        self.boxing_visible: bool  = False
        self.stock_visible:  bool  = False
        self.pad_visible:    bool  = False
        self.bridge_angle:   float = _CG.DEFAULT_BRIDGE_ANGLE_DEG
        self.apical_radius:  float = _CG.DEFAULT_APICAL_RADIUS_MM
        self.crest_height:   float = 0.0
        self.arm_spread:     float = 4.0
        self.arm_drop:       float = 0.0
        self.boxing_a:       float = 52.0
        self.boxing_b:       float = 30.0
        self.boxing_dbl:     float = 18.0
        self.boxing_snapped: bool  = False       # boxing guide snapped to lens (M11/M12)
        # Boxing visibility to restore when the snap is switched back off.
        # Snapping force-shows the guide (the bevel outline rides on it); a
        # maker who had it hidden should get it hidden back, not a default-sized
        # box parked over their drawing. None = nothing to restore.
        self.boxing_visible_pre_snap: bool | None = None
        self.shape_locked:   bool  = False       # lens spline frozen; resize via A/B (M12)
        self.boxing_chain:   bool  = False       # A/B resize proportionally (M12)
        self.outline_locked: bool  = False       # OUTLINE co-resizes with the lens (M12)
        self.bevel_preset:   str   = "acetate"   # flat|horn_metal|acetate|custom
        self.bevel_depth:    float = BEVEL_PRESETS["acetate"]
        self.stock_w:        float = 170.0
        self.stock_h:        float = 85.0
        self.pad_w:          float = 45.0
        self.pad_h:          float = 45.0
        self.fill_visible:   bool  = False        # frame fill overlay (M8)
        self.fill_color:     str   = "#2a6099"
        self.fill_opacity:   float = 0.50
        self.fill_style:     str   = "color"      # "color" | "image" (v1.2)
        self.fill_image:     str   = ""           # material swatch, kept even
                                                  # while the color is showing
        self.lens_fill_visible: bool  = False     # lens tint overlay (v1.2)
        self.lens_fill_top:     str   = DEFAULT_LENS_FILL_TOP
        self.lens_fill_bottom:  str   = DEFAULT_LENS_FILL_BOTTOM
        self.lens_fill_linked:  bool  = False     # both stops held equal (flat tint)
        self.lens_fill_opacity: float = DEFAULT_LENS_FILL_OPACITY
        self.lens_fill_intensity: float = DEFAULT_LENS_FILL_INTENSITY
        self.selected_face_idx: int       = -1
        self.face_image_paths:  list[str] = []
        self.fitted:            bool      = False   # True once fitInView has been called

        # Wire endpoint drag-snap using the workspace's own mutable list and view.
        # snap_enabled_fn is set by MainWindow after the toolbar is built.
        self.edit_tool.set_endpoint_snap_context(self.doc_curves, self.view)
        # 'Lock lens shape' freezes LENS spline editing (still selectable/movable).
        self.edit_tool.set_node_edit_blocked_fn(
            lambda c: self.shape_locked and c.layer == Layer.LENS)

    # ------------------------------------------------------------------
    # Document mutation primitives
    #
    # Single source of truth for the snapshot shape and for keeping
    # doc_curves/doc_dims in sync with the scene. MainWindow and any
    # cross-workspace operation (Temple Copy, file load) must go through
    # these — hand-rolled list+scene updates are how the Mirror Copy
    # undo-corruption bug happened.
    # ------------------------------------------------------------------

    MAX_UNDO = 100

    # Set by MainWindow; called after any curve/dim add/remove/clear so the
    # Layers panel (and any future observer) can refresh.
    on_document_changed = None
    on_mirror_restored = None     # fn(bool): an undo step brought a Ghost state back

    def _notify(self):
        if self.on_document_changed:
            self.on_document_changed()

    def take_snapshot(self) -> dict:
        return {
            "curves": copy.deepcopy(self.doc_curves),
            "dims":   copy.deepcopy(self.doc_dims),
            "texts":  copy.deepcopy(self.doc_texts),
        }

    def push_undo_snapshot(self):
        """Push current state; wipes the redo future. Call BEFORE mutating."""
        self.push_undo_state(self.take_snapshot())

    def push_undo_state(self, snapshot: dict):
        """Push a previously-taken snapshot; wipes the redo future.

        For operations that may turn out to be no-ops: take the snapshot,
        attempt the mutation, and push only on success — pushing eagerly and
        popping on failure would still have destroyed the redo stack."""
        self.undo_stack.append(snapshot)
        self.redo_stack.clear()
        if len(self.undo_stack) > self.MAX_UNDO:
            self.undo_stack.pop(0)

    def add_curve(self, curve):
        """Append to the document and the scene; returns the CurveItem."""
        self.doc_curves.append(curve)
        item = self.scene.add_curve(curve)
        self._notify()
        return item

    @staticmethod
    def _remove_identity(lst: list, obj) -> None:
        # Curves/dims/texts are dataclasses, so ``in`` / ``list.remove`` compare
        # by VALUE: deleting one of two identical curves (a double paste, a
        # duplicate DXF entity) removed the other from the document while the
        # scene dropped this one — the survivor on screen was no longer saved.
        for i, x in enumerate(lst):
            if x is obj:
                del lst[i]
                return

    def remove_curve(self, curve):
        self._remove_identity(self.doc_curves, curve)
        self.scene.remove_curve(curve)
        self._notify()

    def add_dim(self, dim):
        self.doc_dims.append(dim)
        item = self.scene.add_dim(dim)
        self._notify()
        return item

    def remove_dim(self, dim):
        self._remove_identity(self.doc_dims, dim)
        self.scene.remove_dim(dim)
        self._notify()

    def add_text(self, text_obj):
        self.doc_texts.append(text_obj)
        item = self.scene.add_text(text_obj)
        self._notify()
        return item

    def remove_text(self, text_obj):
        self._remove_identity(self.doc_texts, text_obj)
        self.scene.remove_text(text_obj)
        self._notify()

    def clear_geometry(self):
        """Remove every curve, dim, and text. Undo stacks are left untouched."""
        self.edit_tool.clear()
        self.scene.clearSelection()
        for c in list(self.doc_curves):
            self.scene.remove_curve(c)
        self.doc_curves.clear()
        for d in list(self.doc_dims):
            self.scene.remove_dim(d)
        self.doc_dims.clear()
        for t in list(self.doc_texts):
            self.scene.remove_text(t)
        self.doc_texts.clear()
        self._notify()

    def clear_document(self):
        """Clear geometry AND history — File > New / file load.
        Layer visibility/locks reset to defaults with the document."""
        self.clear_geometry()
        self.scene.reset_layer_states()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.reset_session_state()

    def reset_session_state(self):
        """Per-document session state that is NOT in the file and must not
        leak from the previous document into the next: the boxing snap and
        the lens/outline locks derive from geometry that is gone, the bevel
        and forming values are stored in the file (or default), and the
        active layer starts over. Called by clear_document, so File > New
        and every file load share it."""
        self.boxing_snapped = False
        self.shape_locked   = False
        self.outline_locked = False
        self.boxing_chain   = False
        self.boxing_visible_pre_snap = None
        self.boxing_guide.set_locked(False)
        self.bevel_preset = "acetate"
        self.bevel_depth  = BEVEL_PRESETS["acetate"]
        self.bridge_angle  = ConstructionGuides.DEFAULT_BRIDGE_ANGLE_DEG
        self.apical_radius = ConstructionGuides.DEFAULT_APICAL_RADIUS_MM
        self.active_layer  = WORKSPACE_LAYERS[self.workspace_type][0]

    def restore_snapshot(self, snapshot: dict):
        self.clear_geometry()
        for c in snapshot["curves"]:
            self.add_curve(c)
        for d in snapshot["dims"]:
            self.add_dim(d)
        for t in snapshot.get("texts", []):   # absent in pre-M8 bookmarks
            self.add_text(t)

    # A snapshot may carry "mirror": the Ghost state that belongs with it.
    # Mirror (bake) switches Ghost off as part of the operation, and only the
    # geometry came back on Undo — the design showed half a frame until Ghost
    # was switched on by hand. The step's counterpart on the other stack
    # records the state being left, so Redo switches it off again.

    def _step_across(self, source: list, target: list) -> None:
        snapshot = source.pop()
        current = self.take_snapshot()
        if "mirror" in snapshot:
            current["mirror"] = bool(getattr(self, "mirror_enabled", False))
        target.append(current)
        self.restore_snapshot(snapshot)
        if "mirror" in snapshot and self.on_mirror_restored:
            self.on_mirror_restored(bool(snapshot["mirror"]))

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self._step_across(self.undo_stack, self.redo_stack)
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self._step_across(self.redo_stack, self.undo_stack)
        return True


def _run_modal(dlg) -> int:
    """exec() a dialog built for one use, then let it go. Parented to the
    window and never deleted, every Preferences, Transform or Edit Text left a
    live dialog behind, and each stylesheet pass re-polished them all (four
    Preferences opens took an apply from 0.5 s to 1.4 s). deleteLater waits
    for this handler to return, so the dialog's values stay readable here."""
    result = dlg.exec()
    dlg.deleteLater()
    return result


class _WheelGuard(QObject):
    """Installed on the spin boxes, combos and sliders of a scrolling panel:
    the wheel changes one only once it has focus, and otherwise scrolls the
    panel. Scrolling the Guides tab with the pointer over A (width) resized a
    locked lens and pushed an undo step per notch; over Frontal angle it
    changed the saved design."""

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore()          # unaccepted, it goes on to the scroll area
            return True
        return False

    def guard(self, root: QWidget) -> None:
        from PySide6.QtWidgets import QAbstractSlider, QAbstractSpinBox, QScrollBar
        for w in root.findChildren(QWidget):
            # Never a scroll bar (a QAbstractSlider too): a scroll area hands
            # it the wheel by sendEvent, which does not propagate, so guarding
            # one stopped every panel and list from scrolling at all.
            if isinstance(w, QScrollBar):
                continue
            if isinstance(w, (QAbstractSpinBox, QComboBox, QAbstractSlider)):
                # Wheel focus would hand the widget focus on the first notch.
                w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                w.installEventFilter(self)


class KeyCaptureEdit(QLineEdit):
    """QLineEdit that records the next key press as a hotkey string instead of inserting text."""

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            event.accept()
            return
        from PySide6.QtGui import QKeySequence
        # keyCombination() carries modifiers+key as one value; int(modifiers())
        # raised TypeError on current PySide6 (flags enum isn't int()-able),
        # which broke hotkey recording with a console error per keypress.
        seq = QKeySequence(event.keyCombination())
        self.setText(seq.toString())
        event.accept()


class LayerTree(QTreeWidget):
    """Layer-panel tree with drag-and-drop reassignment.

    Object rows can be dragged onto a layer row (or among its children) to
    move those curves to that layer. Qt's default item relocation is
    suppressed: the drop is translated into a document edit via the
    curves_dropped signal and MainWindow rebuilds the panel afterwards.
    """

    curves_dropped   = Signal(list, object)   # ([id(curve), ...], Layer)
    delete_requested = Signal()               # Del/Backspace on object rows

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDropIndicatorShown(True)

    def has_object_rows_selected(self) -> bool:
        for it in self.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] in ("curve", "text"):
                return True
        return False

    def keyPressEvent(self, event):
        # Delete works from the panel too: the rows picked here are already
        # mirrored onto the canvas selection, so the same delete applies.
        # Focus sits in this tree after a row click, which is why the
        # canvas's own Delete handling never saw the key.
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.has_object_rows_selected():
                self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _drop_target_layer(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return None
        kind, payload = data
        if kind == "layer":
            return payload
        parent = item.parent()
        pdata = parent.data(0, Qt.ItemDataRole.UserRole) if parent else None
        return pdata[1] if pdata else None

    def dropEvent(self, event):
        layer = self._drop_target_layer(event.position().toPoint())
        curve_ids = []
        for it in self.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] in ("curve", "text"):
                curve_ids.append(data[1])
        # Never let the view move/delete rows itself; report IgnoreAction so
        # InternalMove's source-row cleanup is skipped, then apply the edit
        # after the drag machinery has fully unwound.
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if layer is not None and curve_ids:
            QTimer.singleShot(
                0, self, lambda: self.curves_dropped.emit(curve_ids, layer))


def _available_screen(widget):
    """The usable area of the screen `widget` (or its parent) will show on —
    what a pop-up's size is bounded by. Falls back to the primary screen, and
    to a plain rectangle when there is no screen at all (a headless import).
    GuildModel's, shared."""
    from PySide6.QtCore import QRect
    parent = widget.parentWidget() if widget is not None else None
    screen = None
    try:
        screen = ((parent.screen() if parent is not None else None)
                  or QApplication.primaryScreen())
    except Exception:
        screen = None
    return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)


class SettingsDialog(QDialog):
    """Application-wide preferences: General / Appearance / Layers / Toolbar /
    Hotkeys / Print & PDF.

    Laid out as GuildModel's PrefsDialog is: every tab scrolls, so no tab
    dictates the dialog's size; it opens at its content's size within the
    screen, or at the size the maker last left it (`prefs_dialog_size`); the
    guidance under a group is a short hint, and the rest is in tooltips."""

    def __init__(self, prefs: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(380)
        # Bounded by the screen: on a short panel with the OS scale up a fixed
        # floor would put the OK row under the screen's edge.
        self.setMinimumHeight(min(480, _available_screen(self).height()))
        self.setSizeGripEnabled(True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        tabs = QTabWidget()
        self._tabs = tabs
        root_layout.addWidget(tabs)

        # ── OK / Cancel buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 8, 16, 16)
        self._ok_btn   = QPushButton("OK")
        cancel_btn     = QPushButton("Cancel")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(cancel_btn)
        root_layout.addLayout(btn_row)

        # ── Helpers ───────────────────────────────────────────────────────
        def _spinbox(lo, hi, step, val, suffix=" mm", decimals=1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            s.setSuffix(suffix)
            s.setValue(val)
            return s

        def _page(title: str, spacing: int = 12) -> QVBoxLayout:
            inner = QWidget()
            lay = QVBoxLayout(inner)
            lay.setSpacing(spacing)
            lay.setContentsMargins(16, 16, 16, 12)
            tabs.addTab(self._scrolled(inner), title)
            return lay

        # ═══════════════════════════════════════════════════════════════════
        # General
        # ═══════════════════════════════════════════════════════════════════
        gen_lay = _page("General")

        draw_box  = QGroupBox("Drawing")
        draw_form = QFormLayout(draw_box)
        self._weight_spin = _spinbox(0.25, 10.0, 0.25, prefs["default_line_weight"],
                                     suffix=" px", decimals=2)
        self._weight_spin.setToolTip("Line weight of a new curve, in screen pixels.")
        draw_form.addRow("Default line weight:", self._weight_spin)
        gen_lay.addWidget(draw_box)

        # Two columns: the drawing aids, then the Frame Front's guides.
        start_box  = QGroupBox("On at Startup")
        start_grid = QGridLayout(start_box)
        start_grid.setHorizontalSpacing(24)
        self._mirror_chk = QCheckBox("Ghost axis")
        self._snap_chk   = QCheckBox("Snap")
        self._smooth_chk = QCheckBox("Smooth handles")
        self._guides_chk = QCheckBox("Construction guides")
        self._boxing_chk = QCheckBox("Boxing guide")
        self._stock_chk  = QCheckBox("Stock guide")
        self._pad_chk    = QCheckBox("Pad guide")
        for chk, key in ((self._mirror_chk, "mirror_on_startup"),
                         (self._snap_chk,   "snap_on_startup"),
                         (self._smooth_chk, "smooth_handles"),
                         (self._guides_chk, "guides_on_startup"),
                         (self._boxing_chk, "boxing_on_startup"),
                         (self._stock_chk,  "stock_on_startup"),
                         (self._pad_chk,    "pad_on_startup")):
            chk.setChecked(prefs[key])
        for chk in (self._guides_chk, self._boxing_chk, self._stock_chk,
                    self._pad_chk):
            chk.setToolTip("Frame Front only. The temples start with their "
                           "stock guide shown and the others hidden.")
        for row, chk in enumerate((self._mirror_chk, self._snap_chk,
                                   self._smooth_chk)):
            start_grid.addWidget(chk, row, 0)
        for row, chk in enumerate((self._guides_chk, self._boxing_chk,
                                   self._stock_chk, self._pad_chk)):
            start_grid.addWidget(chk, row, 1)
        start_grid.setColumnStretch(2, 1)
        gen_lay.addWidget(start_box)

        # The Frame Front's guide sizes, one row per guide (width × height).
        size_box  = QGroupBox("Frame Front Guides")
        size_grid = QGridLayout(size_box)
        size_grid.setHorizontalSpacing(6)
        self._box_a   = _spinbox(30.0, 80.0,  0.5, prefs["boxing_a_mm"])
        self._box_b   = _spinbox(15.0, 60.0,  0.5, prefs["boxing_b_mm"])
        self._box_dbl = _spinbox(8.0,  40.0,  0.5, prefs["boxing_dbl_mm"])
        self._stock_w = _spinbox(50.0, 400.0, 1.0, prefs["stock_width_mm"])
        self._stock_h = _spinbox(20.0, 200.0, 1.0, prefs["stock_height_mm"])
        self._pad_w   = _spinbox(10.0, 200.0, 0.5, prefs["pad_width_mm"])
        self._pad_h   = _spinbox(10.0, 200.0, 0.5, prefs["pad_height_mm"])
        boxing_tip = ("The dashed lens boxes: A is a box's width, B its height, "
                      "and DBL the distance between the two boxes.")
        for row, (label, first, second, tip) in enumerate((
                ("Boxing A × B:", self._box_a, self._box_b, boxing_tip),
                ("DBL:", self._box_dbl, None, boxing_tip),
                ("Stock blank:", self._stock_w, self._stock_h,
                 "The green dashed rectangle, centered at the origin: the "
                 "blank the front is cut from (width × height)."),
                ("Pad block:", self._pad_w, self._pad_h,
                 "The purple dashed rectangle, centered at the origin "
                 "(width × height)."))):
            lbl = QLabel(label)
            size_grid.addWidget(lbl, row, 0)
            size_grid.addWidget(first, row, 1)
            if second is not None:
                size_grid.addWidget(QLabel("×"), row, 2)
                size_grid.addWidget(second, row, 3)
            for w in (lbl, first, second):
                if w is not None:
                    w.setToolTip(tip)
        size_grid.setColumnStretch(1, 1)
        size_grid.setColumnStretch(3, 1)
        gen_lay.addWidget(size_box)

        lens_box  = QGroupBox("Lens Fill")
        lens_form = QFormLayout(lens_box)
        self._lens_opacity_spin = _spinbox(
            0, 100, 5, prefs.get("lens_fill_opacity_pct", 65),
            suffix=" %", decimals=0)
        self._lens_opacity_spin.setToolTip(
            "The opacity a lens tint starts at. The tint colors themselves "
            "are saved with each design.")
        lens_form.addRow("Default opacity:", self._lens_opacity_spin)
        self._lens_intensity_spin = _spinbox(
            0.5, 8.0, 0.25, prefs.get("lens_fill_intensity", 1.0),
            suffix=" ×", decimals=2)
        self._lens_intensity_spin.setToolTip(
            "The tint depth a lens fill starts at. 1.00 shows a color as "
            "picked; higher deepens it, as a longer dye time would.")
        lens_form.addRow("Default intensity:", self._lens_intensity_spin)
        gen_lay.addWidget(lens_box)

        gen_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Appearance (mode / viewport / editing dots / grid)
        # ═══════════════════════════════════════════════════════════════════
        ap_lay = _page("Appearance")

        mode_box  = QGroupBox("Mode")
        mode_form = QFormLayout(mode_box)
        self._dark_check = QCheckBox("Dark mode")
        self._dark_check.setChecked(prefs["dark_mode"])
        mode_form.addRow(self._dark_check)
        self._compact_check = QCheckBox("Compact toolbar")
        self._compact_check.setChecked(prefs.get("compact_toolbar", False))
        self._compact_check.setToolTip(
            "Less padding and slightly smaller icons on the toolbar, for "
            "more drawing room.")
        mode_form.addRow(self._compact_check)
        ap_lay.addWidget(mode_box)

        vp = prefs.get("viewport") or {}
        vp_box  = QGroupBox("Viewport")
        vp_form = QFormLayout(vp_box)

        # (key, label) — a preset overlays the canvas tokens in BOTH UI modes;
        # "auto" follows the UI theme as before.
        self._vp_choices = [
            ("auto",      "Follow UI theme"),
            ("parchment", "Parchment"),
            ("dimmed",    "Dimmed"),
            ("blueprint", "Blueprint"),
            ("matte",     "Matte Dark"),
            ("white",     "Plain White"),
            ("custom",    "Custom"),
        ]
        self._vp_combo = QComboBox()
        for _key, label in self._vp_choices:
            self._vp_combo.addItem(label)
        cur_preset = vp.get("preset", "auto")
        self._vp_combo.setCurrentIndex(next(
            (i for i, (k, _l) in enumerate(self._vp_choices) if k == cur_preset),
            0))
        self._vp_combo.setToolTip(
            "The canvas backdrop and drawing ink, independent of the UI mode. "
            "Follow UI theme is Parchment in light mode and Matte Dark in "
            "dark mode.")
        self._vp_combo.currentIndexChanged.connect(self._on_vp_preset_changed)

        # The custom color sits beside the preset it belongs to.
        self._vp_custom_color = vp.get("custom_bg", "#faf6ee")
        self._vp_color_btn = QPushButton("Color…")
        self._vp_color_btn.setToolTip(
            "The canvas color for the Custom preset; the drawing ink is "
            "derived from it.")
        self._vp_color_btn.clicked.connect(self._pick_vp_color)
        self._vp_color_btn.setEnabled(cur_preset == "custom")
        self._update_vp_swatch()
        canvas_row = QWidget()
        cr_lay = QHBoxLayout(canvas_row)
        cr_lay.setContentsMargins(0, 0, 0, 0)
        cr_lay.setSpacing(6)
        cr_lay.addWidget(self._vp_combo, 1)
        cr_lay.addWidget(self._vp_color_btn)
        vp_form.addRow("Canvas:", canvas_row)

        vig_row = QWidget()
        vig_lay = QHBoxLayout(vig_row)
        vig_lay.setContentsMargins(0, 0, 0, 0)
        vig_lay.setSpacing(8)
        self._vignette_slider = QSlider(Qt.Orientation.Horizontal)
        self._vignette_slider.setRange(0, 100)
        self._vignette_slider.setValue(int(vp.get("vignette", 0)))
        self._vignette_slider.setToolTip(
            "Darkens the edges of the canvas to focus the eye. Display only; "
            "never printed or exported.")
        self._vignette_lbl = QLabel(f"{self._vignette_slider.value()}%")
        self._vignette_lbl.setMinimumWidth(
            self._vignette_lbl.fontMetrics().horizontalAdvance("100%"))
        self._vignette_lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                                        | Qt.AlignmentFlag.AlignVCenter)
        self._vignette_slider.valueChanged.connect(
            lambda v: self._vignette_lbl.setText(f"{v}%"))
        vig_lay.addWidget(self._vignette_slider, 1)
        vig_lay.addWidget(self._vignette_lbl)
        vp_form.addRow("Vignette:", vig_row)
        ap_lay.addWidget(vp_box)

        dots_box  = QGroupBox("Editing Dots")
        dots_form = QFormLayout(dots_box)
        self._dot_spin = _spinbox(2, 10, 1, float(prefs.get("dot_radius_px", 4)),
                                  suffix=" px", decimals=0)
        self._dot_spin.setToolTip(
            "Radius of the node dots on a selected curve; handles draw one "
            "pixel smaller. Larger helps on a high-DPI display.")
        dots_form.addRow("Node dot radius:", self._dot_spin)
        ap_lay.addWidget(dots_box)

        grid_box  = QGroupBox("Grid")
        grid_form = QFormLayout(grid_box)
        self._grid_spacing_spin = _spinbox(
            0.5, 100.0, 0.5, float(prefs.get("grid_spacing_mm", 2.0)),
            suffix=" mm", decimals=1)
        self._grid_spacing_spin.setToolTip(
            "The distance between grid lines. The Grid button shows the grid; "
            "the Grid snap in the snap palette snaps to its intersections.")
        grid_form.addRow("Spacing:", self._grid_spacing_spin)
        from PySide6.QtWidgets import QSpinBox as _QSpinBox
        self._grid_major_spin = _QSpinBox()
        self._grid_major_spin.setRange(1, 20)
        self._grid_major_spin.setSuffix(" lines")
        self._grid_major_spin.setValue(int(prefs.get("grid_major", 5)))
        self._grid_major_spin.setToolTip(
            "Every Nth line is drawn heavier. At 2 mm spacing, 5 puts a major "
            "line every 10 mm.")
        grid_form.addRow("Major line every:", self._grid_major_spin)

        self._grid_width_spin = _spinbox(
            0.5, 4.0, 0.5, float(prefs.get("grid_major_width_px", 1.0)),
            suffix=" px", decimals=1)
        self._grid_width_spin.setToolTip(
            "Line weight of the major grid lines, in screen pixels.")
        grid_form.addRow("Major line width:", self._grid_width_spin)

        # Grid line colors: "" = follow the theme tokens. Swatch buttons
        # mirror the custom canvas color above.
        self._grid_minor_color = str(prefs.get("grid_minor_color", "") or "")
        self._grid_major_color = str(prefs.get("grid_major_color", "") or "")
        self._grid_minor_btn = QPushButton("Minor…")
        self._grid_minor_btn.setToolTip("Color of the minor grid lines.")
        self._grid_minor_btn.clicked.connect(lambda: self._pick_grid_color("minor"))
        self._grid_major_btn = QPushButton("Major…")
        self._grid_major_btn.setToolTip("Color of the major grid lines.")
        self._grid_major_btn.clicked.connect(lambda: self._pick_grid_color("major"))
        grid_reset = QPushButton("Reset")
        grid_reset.setToolTip("Clear both grid colors; the grid follows the "
                              "theme again.")
        grid_reset.clicked.connect(self._reset_grid_colors)
        grid_colors_row = QWidget()
        gc_lay = QHBoxLayout(grid_colors_row)
        gc_lay.setContentsMargins(0, 0, 0, 0)
        gc_lay.setSpacing(6)
        gc_lay.addWidget(self._grid_minor_btn)
        gc_lay.addWidget(self._grid_major_btn)
        gc_lay.addWidget(grid_reset)
        gc_lay.addStretch()
        grid_form.addRow("Colors:", grid_colors_row)
        self._update_grid_swatches()
        ap_lay.addWidget(grid_box)

        ap_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Layers (per-layer light/dark color overrides)
        # ═══════════════════════════════════════════════════════════════════
        lc_lay = _page("Layers", spacing=10)
        lc_lay.addWidget(self._hint(
            "Each layer's drawing color in light and dark mode. Most layers "
            "use the shared ink until you pick a color; SCULPT and ENGRAVING "
            "have their own."))

        # Only layer.* overrides are edited here; _collect_theme preserves
        # any other tokens already present in the prefs["theme"] dicts.
        base_theme = prefs.get("theme") or {}
        self._base_theme = {
            "light": dict(base_theme.get("light") or {}),
            "dark":  dict(base_theme.get("dark") or {}),
        }
        self._layer_over = {
            mode: {tok: v for tok, v in self._base_theme[mode].items()
                   if tok.startswith("layer.")}
            for mode in ("light", "dark")
        }

        lc_grid = QGridLayout()
        lc_grid.setHorizontalSpacing(8)
        lc_grid.setVerticalSpacing(6)
        for col, title in ((0, "Layer"), (1, "Light"), (2, "Dark")):
            hdr = QLabel(title)
            f = hdr.font()
            f.setBold(True)
            hdr.setFont(f)
            lc_grid.addWidget(hdr, 0, col)

        self._layer_btns: dict = {}   # (layer name, mode) -> QPushButton
        for row, layer in enumerate(Layer, start=1):
            name = layer.value
            lc_grid.addWidget(QLabel(name), row, 0)
            for col, mode in ((1, "light"), (2, "dark")):
                btn = QPushButton()
                btn.setFixedWidth(96)
                btn.clicked.connect(
                    lambda _=False, n=name, m=mode: self._pick_layer_color(n, m))
                self._layer_btns[(name, mode)] = btn
                lc_grid.addWidget(btn, row, col)
            rst = QToolButton()
            rst.setText("↺")
            rst.setToolTip(f"Reset {name} to its default colors.")
            rst.clicked.connect(
                lambda _=False, n=name: self._reset_layer_color(n))
            lc_grid.addWidget(rst, row, 3)
            self._refresh_layer_btn(name)
        lc_grid.setColumnStretch(4, 1)
        lc_lay.addLayout(lc_grid)

        lc_reset_all = QPushButton("Reset All Layer Colors")
        lc_reset_all.clicked.connect(self._reset_all_layer_colors)
        lc_reset_row = QHBoxLayout()
        lc_reset_row.addWidget(lc_reset_all)
        lc_reset_row.addStretch()
        lc_lay.addLayout(lc_reset_row)
        lc_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Toolbar (button visibility), grouped as the toolbar is
        # ═══════════════════════════════════════════════════════════════════
        tb_lay = _page("Toolbar")
        tb_lay.addWidget(self._hint(
            "Uncheck a button to hide it; a hidden tool still answers its "
            "hotkey."))

        toolbar_prefs = prefs.get("toolbar", {})
        self._tb_checks: dict[str, QCheckBox] = {}
        for section, entries in _TOOLBAR_SECTIONS:
            box  = QGroupBox(section)
            grid = QGridLayout(box)
            grid.setHorizontalSpacing(24)
            rows = (len(entries) + 1) // 2          # two columns, down then across
            for i, (key, label, hideable) in enumerate(entries):
                default_on = _prefs_mod.DEFAULTS["toolbar"].get(key, True)
                chk = QCheckBox(label)
                chk.setChecked(toolbar_prefs.get(key, default_on))
                if not hideable:
                    chk.setEnabled(False)
                    chk.setToolTip("Select is always shown.")
                elif key in _WS_ONLY_ACTIONS:
                    chk.setToolTip(
                        "Shown on the Frame Front only."
                        if _WS_ONLY_ACTIONS[key] == ("front",)
                        else "Shown on the temples only.")
                self._tb_checks[key] = chk
                grid.addWidget(chk, i % rows, i // rows)
            grid.setColumnStretch(2, 1)
            tb_lay.addWidget(box)
        tb_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Hotkeys
        # ═══════════════════════════════════════════════════════════════════
        hk_lay = _page("Hotkeys", spacing=10)
        hk_lay.addWidget(self._hint(
            "Click a field, then press the key or combination. Esc clears "
            "the field."))

        hk_form = QFormLayout()
        hk_form.setSpacing(6)
        hk_lay.addLayout(hk_form)

        hotkey_prefs = prefs.get("hotkeys", {})
        self._key_edits: list[KeyCaptureEdit] = []
        self._hk_keys:   list[str]            = []
        defaults = _prefs_mod.DEFAULTS["hotkeys"]
        for key, label in _HOTKEY_ACTION_DEFS:
            edit = KeyCaptureEdit()
            edit.setPlaceholderText("none")
            edit.setMaximumWidth(140)
            edit.setText(hotkey_prefs.get(key, defaults.get(key, "")))
            edit.textChanged.connect(self._check_conflicts)
            self._key_edits.append(edit)
            self._hk_keys.append(key)
            hk_form.addRow(label + ":", edit)

        self._conflict_label = QLabel()
        self._conflict_label.setWordWrap(True)
        # Dark red vanishes on the dark chrome — brighten it there.
        self._conflict_label.setStyleSheet(
            f"color: {'#ff6b6b' if theme.is_dark() else '#cc0000'};")
        self._conflict_label.hide()
        hk_lay.addWidget(self._conflict_label)

        # Every shortcut a hotkey may not take, listed in full — the conflict
        # check refuses all of them, so all of them are shown.
        fixed_box  = QGroupBox("Fixed Shortcuts")
        fixed_grid = QGridLayout(fixed_box)
        fixed_grid.setHorizontalSpacing(10)
        fixed_grid.setVerticalSpacing(3)
        half = (len(_FIXED_SHORTCUTS) + 1) // 2
        for i, (name, keys) in enumerate(_FIXED_SHORTCUTS):
            row, col = i % half, (i // half) * 3
            fixed_grid.addWidget(QLabel(name), row, col)
            k = QLabel(" / ".join(keys))
            k.setObjectName("hintLabel")
            fixed_grid.addWidget(k, row, col + 1)
        fixed_grid.setColumnMinimumWidth(2, 12)
        fixed_grid.setColumnStretch(5, 1)
        hk_lay.addWidget(fixed_box)
        hk_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Print & PDF — one group per export, saying which it drives
        # ═══════════════════════════════════════════════════════════════════
        from .fontpicker import FontFilterCombo
        from .document import WORKSPACE_LAYERS as _WS_LAYERS
        from .export.template_print import PAPER_SIZES as _TP_PAPER

        pdf_lay = _page("Print && PDF")

        cat_cfg = {**_prefs_mod.DEFAULTS["catalog_pdf"],
                   **(prefs.get("catalog_pdf") or {})}
        tp_cfg = {**_prefs_mod.DEFAULTS["template_print"],
                  **(prefs.get("template_print") or {})}

        # Print Front + Temples / PDF Front + Temples
        tp_box  = QGroupBox("Front + Temples (1:1 Templates)")
        tp_box.setToolTip("File ▸ Print Front + Temples and "
                          "Export ▸ PDF Front + Temples.")
        tp_form = QFormLayout(tp_box)

        self._tp_paper = QComboBox()
        for _k, (_lbl, _w, _h) in _TP_PAPER.items():
            self._tp_paper.addItem(_lbl, _k)
        self._tp_paper.setCurrentIndex(
            max(0, self._tp_paper.findData(tp_cfg["paper"])))
        self._tp_paper.setToolTip(
            "The paper the pieces are laid out on, at true size. Pieces that "
            "don't fit spill onto further pages; the print dialog can still "
            "change the size.")
        tp_form.addRow("Paper size:", self._tp_paper)

        self._tp_orient = QComboBox()
        for _k, _lbl in (("auto", "Automatic (fewest pages)"),
                         ("portrait", "Portrait"), ("landscape", "Landscape")):
            self._tp_orient.addItem(_lbl, _k)
        self._tp_orient.setCurrentIndex(
            max(0, self._tp_orient.findData(tp_cfg["orientation"])))
        tp_form.addRow("Orientation:", self._tp_orient)

        self._tp_lw = _spinbox(0.1, 3.0, 0.05, float(tp_cfg["line_weight_mm"]),
                               decimals=2)
        self._tp_lw.setToolTip(
            "Stroke width on paper. A fine line (0.25–0.35 mm) is easiest to "
            "saw to; a heavier one reads better through tracing paper.")
        tp_form.addRow("Line weight:", self._tp_lw)

        self._tp_labels_chk = QCheckBox("Label each piece")
        self._tp_labels_chk.setToolTip(
            "Print Frame Front, Temple R and Temple L beside the pieces.")
        self._tp_labels_chk.setChecked(bool(tp_cfg["labels"]))
        tp_form.addRow(self._tp_labels_chk)
        tp_form.addRow(self._hint(
            "Prints each workspace as it shows: visible layers, mirror ghost "
            "and engraving. Every page carries a ruler to check the scale."))
        pdf_lay.addWidget(tp_box)

        # Shared by the 1:1 print, the 1:1 PDF and the catalog sheet
        lw_box  = QGroupBox("1:1 Print, 1:1 PDF and Catalog")
        lw_form = QFormLayout(lw_box)
        self._cat_lw = _spinbox(0.1, 3.0, 0.1, float(cat_cfg["line_weight_mm"]),
                                decimals=2)
        self._cat_lw.setToolTip("Stroke width on paper.")
        lw_form.addRow("Line weight:", self._cat_lw)
        self._cat_offset = _spinbox(
            -100.0, 100.0, 1.0, float(cat_cfg.get("content_offset_mm", 0.0)))
        self._cat_offset.setToolTip(
            "Moves the drawing down (+) or up (−) on the page; the caption "
            "stays put. Clears a binding margin when pages are bound into a "
            "catalog. 0 = centered.")
        lw_form.addRow("Vertical offset:", self._cat_offset)
        pdf_lay.addWidget(lw_box)

        # PDF for Catalog only
        cat_box  = QGroupBox("Catalog PDF")
        cat_box.setToolTip("Export ▸ PDF for Catalog: the front and both "
                           "temples on one sheet.")
        cat_form = QFormLayout(cat_box)

        self._cat_paper = QComboBox()
        self._cat_paper_choices = [("a5", "A5 (landscape)"),
                                   ("half_letter", "Half-Letter (landscape)")]
        for _k, _lbl in self._cat_paper_choices:
            self._cat_paper.addItem(_lbl, _k)
        self._cat_paper.setCurrentIndex(
            next((i for i, (k, _l) in enumerate(self._cat_paper_choices)
                  if k == cat_cfg["paper"]), 0))
        cat_form.addRow("Paper size:", self._cat_paper)

        self._cat_font = FontFilterCombo(family=cat_cfg["caption_font"])
        self._cat_font.setToolTip(
            "Type to filter: the list narrows to the families that match. "
            "The arrow shows the current family's siblings.")
        cat_form.addRow("Caption font:", self._cat_font)

        self._cat_caption_chk = QCheckBox("Print the file name as a caption")
        self._cat_caption_chk.setChecked(bool(cat_cfg["caption"]))
        cat_form.addRow(self._cat_caption_chk)

        self._cat_scale_chk = QCheckBox("Print the scale")
        self._cat_scale_chk.setToolTip(
            "Prints “Scale 1:1” in a corner, or the reduction when the "
            "drawing had to shrink to fit the page.")
        self._cat_scale_chk.setChecked(bool(cat_cfg["show_scale"]))
        cat_form.addRow(self._cat_scale_chk)

        self._cat_fill_chk = QCheckBox("Print frame and lens fills")
        self._cat_fill_chk.setChecked(bool(cat_cfg.get("include_fill", False)))
        self._cat_fill_chk.setToolTip(
            "Lays the Frame Fill and Lens Fill under the line work, as each "
            "workspace shows them. A workspace with its fill off, or whose "
            "outline doesn't close, prints line work only.\n\n"
            "Off is the cutting-room sheet; on is the showroom page.")
        cat_form.addRow(self._cat_fill_chk)

        def _layer_checks(ws_key, selected) -> tuple[QWidget, dict]:
            row = QWidget()
            grid = QGridLayout(row)
            layer_grids.append(grid)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(2)
            checks = {}
            for i, layer in enumerate(_WS_LAYERS[ws_key]):
                cb = QCheckBox(layer.value)
                cb.setChecked(layer.value in selected)
                grid.addWidget(cb, i // 3, i % 3)
                checks[layer.value] = cb
            grid.setColumnStretch(3, 1)
            return row, checks

        layer_grids: list[QGridLayout] = []
        front_row, self._cat_front_layers = _layer_checks(
            "front", cat_cfg["front_layers"])
        cat_form.addRow("Front layers:", front_row)
        temple_row, self._cat_temple_layers = _layer_checks(
            "temple_r", cat_cfg["temple_layers"])
        cat_form.addRow("Temple layers:", temple_row)
        # Two grids, one set of columns: the widest name sets every column.
        col_w = max(cb.sizeHint().width() for cb in
                    (*self._cat_front_layers.values(),
                     *self._cat_temple_layers.values()))
        for grid in layer_grids:
            for col in range(3):
                grid.setColumnMinimumWidth(col, col_w)
        pdf_lay.addWidget(cat_box)
        pdf_lay.addStretch()

        self._check_conflicts()

        # A typed number settles when the typing is done, as in GuildModel;
        # and the wheel scrolls the tab unless a field has focus.
        from PySide6.QtWidgets import QAbstractSpinBox
        for box in self.findChildren(QAbstractSpinBox):
            box.setKeyboardTracking(False)
        self._wheel_guard = _WheelGuard(self)
        self._wheel_guard.guard(tabs)

        # Open at the size the maker left it, else at the content's own size,
        # within the screen (see _initial_size).
        self.resize(self._initial_size(prefs))

    @staticmethod
    def _scrolled(inner: QWidget) -> QScrollArea:
        """Wrap a tab's column so no tab dictates the dialog's minimum size."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    @staticmethod
    def _hint(text: str) -> QLabel:
        """A short line of guidance in the muted hint style (theme
        `QLabel#hintLabel`); anything longer belongs in a tooltip."""
        lbl = QLabel(text)
        lbl.setObjectName("hintLabel")
        lbl.setWordWrap(True)
        return lbl

    def _initial_size(self, prefs: dict) -> QSize:
        """The remembered size (`prefs_dialog_size`), else the widest and
        tallest tab content plus the scroll bar and the chrome; either way no
        more than 80 % of the screen the dialog will show on, and never under
        the minimums."""
        from PySide6.QtWidgets import QStyle
        avail = _available_screen(self)
        max_w, max_h = int(avail.width() * 0.8), int(avail.height() * 0.8)
        floor_w, floor_h = self.minimumWidth(), self.minimumHeight()
        saved = prefs.get("prefs_dialog_size")
        if (isinstance(saved, (list, tuple)) and len(saved) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) and v > 0 for v in saved)):
            return QSize(max(min(int(saved[0]), max_w), floor_w),
                         max(min(int(saved[1]), max_h), floor_h))
        w = h = 0
        for i in range(self._tabs.count()):
            page = self._tabs.widget(i)
            inner = page.widget() if isinstance(page, QScrollArea) else page
            hint = inner.sizeHint()
            w, h = max(w, hint.width()), max(h, hint.height())
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        chrome = self._tabs.tabBar().sizeHint().height() + 72     # tab bar + OK row
        return QSize(max(min(w + bar + 8, max_w), floor_w),
                     max(min(h + chrome, max_h), floor_h))

    # ------------------------------------------------------------------
    # Layers & Colors helpers
    # ------------------------------------------------------------------

    def _layer_resolved(self, name: str, mode: str) -> tuple[str, bool]:
        """(hex, is_override) for a layer's color in one mode."""
        ov = self._layer_over[mode].get(f"layer.{name}")
        if ov:
            return ov, True
        return theme.default_layer_color(name, mode == "dark"), False

    def _refresh_layer_btn(self, name: str):
        for mode in ("light", "dark"):
            hexv, overridden = self._layer_resolved(name, mode)
            btn = self._layer_btns[(name, mode)]
            pm = QPixmap(14, 14)
            pm.fill(QColor(hexv))
            btn.setIcon(QIcon(pm))
            btn.setText(hexv if overridden else "default")

    def _pick_layer_color(self, name: str, mode: str):
        cur, _ = self._layer_resolved(name, mode)
        c = QColorDialog.getColor(QColor(cur), self,
                                  f"{name} color ({mode} mode)")
        if c.isValid():
            self._layer_over[mode][f"layer.{name}"] = c.name()
            self._refresh_layer_btn(name)

    def _reset_layer_color(self, name: str):
        for mode in ("light", "dark"):
            self._layer_over[mode].pop(f"layer.{name}", None)
        self._refresh_layer_btn(name)

    def _reset_all_layer_colors(self):
        for mode in ("light", "dark"):
            self._layer_over[mode].clear()
        for layer in Layer:
            self._refresh_layer_btn(layer.value)

    def _collect_theme(self) -> dict:
        """prefs["theme"] value: non-layer tokens preserved from the incoming
        prefs, layer.* tokens replaced by this dialog's state."""
        out = {"light": {}, "dark": {}}
        for mode in ("light", "dark"):
            for tok, v in self._base_theme[mode].items():
                if not tok.startswith("layer."):
                    out[mode][tok] = v
            out[mode].update(self._layer_over[mode])
        return out

    # ------------------------------------------------------------------
    # Appearance-tab helpers
    # ------------------------------------------------------------------

    def _on_vp_preset_changed(self, idx: int):
        self._vp_color_btn.setEnabled(self._vp_choices[idx][0] == "custom")

    def _pick_vp_color(self):
        c = QColorDialog.getColor(QColor(self._vp_custom_color), self,
                                  "Canvas color")
        if c.isValid():
            self._vp_custom_color = c.name()
            self._update_vp_swatch()

    def _update_vp_swatch(self):
        pm = QPixmap(16, 16)
        pm.fill(QColor(self._vp_custom_color))
        self._vp_color_btn.setIcon(QIcon(pm))

    def _pick_grid_color(self, which: str):
        current = (self._grid_minor_color if which == "minor"
                   else self._grid_major_color)
        fallback = theme.color(f"canvas.grid_{which}")
        c = QColorDialog.getColor(QColor(current or fallback), self,
                                  f"Grid {which} line color")
        if c.isValid():
            if which == "minor":
                self._grid_minor_color = c.name()
            else:
                self._grid_major_color = c.name()
            self._update_grid_swatches()

    def _reset_grid_colors(self):
        self._grid_minor_color = ""
        self._grid_major_color = ""
        self._update_grid_swatches()

    def _update_grid_swatches(self):
        for value, which, btn in (
                (self._grid_minor_color, "minor", self._grid_minor_btn),
                (self._grid_major_color, "major", self._grid_major_btn)):
            pm = QPixmap(16, 16)
            pm.fill(QColor(value or theme.color(f"canvas.grid_{which}")))
            btn.setIcon(QIcon(pm))

    # ------------------------------------------------------------------

    # Bound elsewhere as fixed shortcuts; a hotkey on one of these makes Qt
    # treat the sequence as ambiguous and fire NEITHER — Undo simply died.
    # "Delete" / "Escape" are the long spellings of the same two keys.
    _RESERVED_KEYS = ({k for _name, keys in _FIXED_SHORTCUTS for k in keys}
                      | {"Delete", "Escape"})

    def _check_conflicts(self):
        texts = [e.text().strip() for e in self._key_edits]
        non_empty = [t for t in texts if t]
        conflict_keys = {t for t in non_empty if non_empty.count(t) > 1}
        reserved = {t for t in non_empty if t in self._RESERVED_KEYS}
        typing = {t for t in non_empty if t in _TYPING_KEYS}
        conflict_keys |= reserved | typing
        for edit in self._key_edits:
            txt = edit.text().strip()
            if txt and txt in conflict_keys:
                # Explicit ink: the theme's light-on-dark text is unreadable
                # on the pink highlight in dark mode.
                edit.setStyleSheet("background: #ffcccc; color: #1f1f1f;")
            else:
                edit.setStyleSheet("")
        has_conflict = bool(conflict_keys)
        self._ok_btn.setEnabled(not has_conflict)
        if has_conflict:
            parts = []
            dupes = sorted(conflict_keys - reserved - typing)
            if dupes:
                parts.append(f"{', '.join(dupes)} assigned to multiple actions")
            if reserved:
                parts.append(f"{', '.join(sorted(reserved))} reserved for a "
                             "fixed shortcut (listed below)")
            if typing:
                parts.append(f"{', '.join(sorted(typing))} reserved for typing "
                             "values in the tools")
            self._conflict_label.setText("Conflict: " + "; ".join(parts) + ".")
            self._conflict_label.show()
        else:
            self._conflict_label.hide()

    # ------------------------------------------------------------------

    def to_prefs(self) -> dict:
        """Return a prefs dict reflecting the current dialog state."""
        toolbar = {key: chk.isChecked() for key, chk in self._tb_checks.items()}
        hotkeys = {
            key: self._key_edits[i].text().strip()
            for i, key in enumerate(self._hk_keys)
        }
        return {
            "dark_mode":            self._dark_check.isChecked(),
            "theme":                self._collect_theme(),
            "viewport": {
                "preset":    self._vp_choices[self._vp_combo.currentIndex()][0],
                "custom_bg": self._vp_custom_color,
                "vignette":  self._vignette_slider.value(),
            },
            "dot_radius_px":        int(self._dot_spin.value()),
            "compact_toolbar":      self._compact_check.isChecked(),
            "grid_spacing_mm":      self._grid_spacing_spin.value(),
            "grid_major":           self._grid_major_spin.value(),
            "grid_minor_color":     self._grid_minor_color,
            "grid_major_color":     self._grid_major_color,
            "grid_major_width_px":  self._grid_width_spin.value(),
            "default_line_weight":  self._weight_spin.value(),
            "mirror_on_startup":    self._mirror_chk.isChecked(),
            "guides_on_startup":    self._guides_chk.isChecked(),
            "snap_on_startup":      self._snap_chk.isChecked(),
            "smooth_handles":       self._smooth_chk.isChecked(),
            "boxing_on_startup":    self._boxing_chk.isChecked(),
            "boxing_a_mm":          self._box_a.value(),
            "boxing_b_mm":          self._box_b.value(),
            "boxing_dbl_mm":        self._box_dbl.value(),
            "stock_on_startup":     self._stock_chk.isChecked(),
            "stock_width_mm":       self._stock_w.value(),
            "stock_height_mm":      self._stock_h.value(),
            "pad_on_startup":       self._pad_chk.isChecked(),
            "pad_width_mm":         self._pad_w.value(),
            "pad_height_mm":        self._pad_h.value(),
            "lens_fill_opacity_pct": int(self._lens_opacity_spin.value()),
            "lens_fill_intensity":   self._lens_intensity_spin.value(),
            "toolbar":              toolbar,
            "hotkeys":              hotkeys,
            "catalog_pdf": {
                "paper":          self._cat_paper.currentData(),
                "line_weight_mm": self._cat_lw.value(),
                "content_offset_mm": self._cat_offset.value(),
                "caption":        self._cat_caption_chk.isChecked(),
                "caption_font":   self._cat_font.current_family(),
                "show_scale":     self._cat_scale_chk.isChecked(),
                "include_fill":   self._cat_fill_chk.isChecked(),
                "front_layers":   [n for n, cb in self._cat_front_layers.items()
                                   if cb.isChecked()],
                "temple_layers":  [n for n, cb in self._cat_temple_layers.items()
                                   if cb.isChecked()],
            },
            "template_print": {
                "paper":          self._tp_paper.currentData(),
                "orientation":    self._tp_orient.currentData(),
                "line_weight_mm": self._tp_lw.value(),
                "labels":         self._tp_labels_chk.isChecked(),
            },
        }


class TransformDialog(QDialog):
    """Exact numeric Scale / Rotate for the current selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Transform Selection")
        form = QFormLayout(self)

        def _pct():
            s = QDoubleSpinBox()
            s.setRange(1.0, 10000.0)
            s.setDecimals(2)
            s.setSingleStep(5.0)
            s.setSuffix(" %")
            s.setValue(100.0)
            return s

        self._sx = _pct()
        self._sy = _pct()
        self._lock = QCheckBox("Lock aspect ratio")
        self._lock.setChecked(True)
        self._sy.setEnabled(False)
        self._lock.toggled.connect(
            lambda on: (self._sy.setEnabled(not on),
                        self._sy.setValue(self._sx.value()) if on else None))
        self._sx.valueChanged.connect(
            lambda v: self._sy.setValue(v) if self._lock.isChecked() else None)

        self._rot = QDoubleSpinBox()
        self._rot.setRange(-360.0, 360.0)
        self._rot.setDecimals(2)
        self._rot.setSingleStep(5.0)
        self._rot.setSuffix("°")
        self._rot.setValue(0.0)
        # The Text dialog's convention, and CAD's: until 1.3 a positive angle
        # here turned the selection clockwise while the Text dialog's turned
        # it counter-clockwise.
        self._rot.setToolTip("Positive rotates counter-clockwise.")

        self._pivot = QComboBox()
        self._pivot.addItems(["Selection center", "Scene origin (0, 0)"])

        form.addRow("Scale X:", self._sx)
        form.addRow("Scale Y:", self._sy)
        form.addRow(self._lock)
        form.addRow("Rotation:", self._rot)
        form.addRow("Pivot:", self._pivot)

        note = QLabel("Positive rotation is counter-clockwise. A non-uniform "
                      "scale turns circles and arcs into splines.")
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        form.addRow(note)

        btns = QHBoxLayout()
        ok = QPushButton("Apply")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        form.addRow(btns)

    def values(self):
        """(sx, sy, rotation_deg, pivot_is_origin)"""
        return (self._sx.value() / 100.0,
                self._sy.value() / 100.0,
                self._rot.value(),
                self._pivot.currentIndex() == 1)


class MainWindow(QMainWindow):
    # ── Phase 14: proxy properties — all delegate to the active WorkspaceState ──

    @property
    def _active_ws(self) -> "WorkspaceState":
        return self._workspaces[self._ws_tab_widget.currentIndex()]

    # Document
    @property
    def _doc_curves(self): return self._active_ws.doc_curves
    @_doc_curves.setter
    def _doc_curves(self, v): self._active_ws.doc_curves = v

    @property
    def _doc_dims(self): return self._active_ws.doc_dims
    @_doc_dims.setter
    def _doc_dims(self, v): self._active_ws.doc_dims = v

    @property
    def _bookmarks(self): return self._active_ws.bookmarks
    @_bookmarks.setter
    def _bookmarks(self, v): self._active_ws.bookmarks = v

    @property
    def _undo_stack(self): return self._active_ws.undo_stack
    @_undo_stack.setter
    def _undo_stack(self, v): self._active_ws.undo_stack = v

    @property
    def _redo_stack(self): return self._active_ws.redo_stack
    @_redo_stack.setter
    def _redo_stack(self, v): self._active_ws.redo_stack = v

    @property
    def _image_px_per_mm(self): return self._active_ws.image_px_per_mm
    @_image_px_per_mm.setter
    def _image_px_per_mm(self, v): self._active_ws.image_px_per_mm = v

    # Canvas
    @property
    def scene(self): return self._active_ws.scene
    @property
    def view(self): return self._active_ws.view
    @property
    def _snap(self): return self._active_ws.snap

    # Tools
    @property
    def _calib_tool(self): return self._active_ws.calib_tool
    @property
    def _draw_tool(self): return self._active_ws.draw_tool
    @property
    def _circle_tool(self): return self._active_ws.circle_tool
    @property
    def _edit_tool(self): return self._active_ws.edit_tool
    @property
    def _dim_tool(self): return self._active_ws.dim_tool
    @property
    def _trim_tool(self): return self._active_ws.trim_tool
    @property
    def _fillet_tool(self): return self._active_ws.fillet_tool
    @property
    def _split_tool(self): return self._active_ws.split_tool
    @property
    def _offset_tool(self): return self._active_ws.offset_tool
    @property
    def _rebuild_tool(self): return self._active_ws.rebuild_tool
    @property
    def _point_move_tool(self): return self._active_ws.point_move_tool
    @property
    def _text_tool(self): return self._active_ws.text_tool

    # Guides
    @property
    def _guides(self): return self._active_ws.const_guides
    @property
    def _boxing_guide(self): return self._active_ws.boxing_guide
    @property
    def _stock_guide(self): return self._active_ws.stock_guide
    @property
    def _pad_guide(self): return self._active_ws.pad_guide

    # Move gizmo
    @property
    def _move_gizmo(self): return self._active_ws.move_gizmo
    @_move_gizmo.setter
    def _move_gizmo(self, v): self._active_ws.move_gizmo = v

    @property
    def _move_gizmo_center(self): return self._active_ws.move_gizmo_center
    @_move_gizmo_center.setter
    def _move_gizmo_center(self, v): self._active_ws.move_gizmo_center = v

    @property
    def _drag_moving_curves(self): return self._active_ws.drag_moving_curves
    @_drag_moving_curves.setter
    def _drag_moving_curves(self, v): self._active_ws.drag_moving_curves = v

    @property
    def _drag_moving_dims(self): return self._active_ws.drag_moving_dims
    @_drag_moving_dims.setter
    def _drag_moving_dims(self, v): self._active_ws.drag_moving_dims = v
    @property
    def _drag_moving_texts(self): return self._active_ws.drag_moving_texts
    @_drag_moving_texts.setter
    def _drag_moving_texts(self, v): self._active_ws.drag_moving_texts = v

    # Sidebar face-image selection index
    @property
    def _selected_face_idx(self): return self._active_ws.selected_face_idx
    @_selected_face_idx.setter
    def _selected_face_idx(self, v): self._active_ws.selected_face_idx = v

    # ────────────────────────────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GuildDraw {__version__}")

        # Load persistent preferences first
        self._prefs = _prefs_mod.load()
        # The size and place the maker left the window at (GuildModel's key);
        # the first time, 1440×860 within the screen — on a 1366×768 laptop
        # the fixed size opened larger than the screen.
        _geo = self._prefs.get("main_window_geometry")
        _avail = _available_screen(self)
        if not (isinstance(_geo, str) and _geo
                and self.restoreGeometry(QByteArray.fromBase64(_geo.encode()))):
            self.resize(min(1440, int(_avail.width() * 0.95)),
                        min(860, int(_avail.height() * 0.95)))
        # Theme overrides + viewport preset must land before any workspace/
        # canvas is built so every painter resolves user colors from the
        # start; re-render the chrome in case saved overrides retint it
        # (main() styled defaults).
        theme.set_overrides(self._prefs.get("theme"))
        _vp_prefs = self._prefs.get("viewport") or {}
        theme.apply_viewport(_vp_prefs.get("preset", "auto"),
                             _vp_prefs.get("custom_bg"))
        theme.set_dot_radius(self._prefs.get("dot_radius_px", 4))
        theme.set_compact(self._prefs.get("compact_toolbar", False))
        QApplication.instance().setStyleSheet(theme.build_qss())
        # Tooltips: wrapped to a readable width app-wide, and off altogether
        # when the maker says so — the ? at the foot of the toolbar
        # (framedraft/tooltips.py; GuildModel's, shared).
        self._tooltip_filter = TooltipFilter(
            enabled=bool(self._prefs.get("tooltips", True)), parent=self)
        QApplication.instance().installEventFilter(self._tooltip_filter)

        # ── Global (non-workspace) state ──────────────────────────────────
        self._dark_mode            = self._prefs["dark_mode"]
        self._updating_weight_spin = False
        self._syncing_selection = False   # guards tree↔canvas selection sync
        self._default_line_weight: float = self._prefs["default_line_weight"]
        self._current_path: str | None = None   # .gdraw file path (or single SVG)
        self._dirty = False                     # unsaved changes (any workspace)
        self._pm_curves: list = []              # Point Move: captured selection
        self._pm_dims:   list = []
        self._layer_refresh_pending = False
        self._recent_files: list[str] = [
            p for p in self._prefs.get("recent_files", []) if isinstance(p, str)
        ]

        # Status bar must exist before WorkspaceState creates CanvasView instances
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._coords_label = QLabel()
        self._coords_label.setObjectName("coordsLabel")
        self._coords_label.setContentsMargins(0, 0, 8, 0)
        self._coords_label.setMinimumWidth(self._coords_label.fontMetrics()
                                           .horizontalAdvance("x: -000.00 mm  y: -000.00 mm"))
        self._status.addPermanentWidget(self._coords_label)
        self._info_label = QLabel()
        self._info_label.setContentsMargins(0, 0, 8, 0)
        self._status.addPermanentWidget(self._info_label)
        # "Ready for GuildModel" readiness dot (mirrors GuildModel's M5.2 traffic
        # light): green when the active workspace meets the export contract,
        # amber when it doesn't, gray when there's nothing to hand off.
        self._readiness_dot = ReadinessDot()
        self._status.addPermanentWidget(self._readiness_dot)

        # ── Phase 14: create per-workspace state containers ───────────────
        # _ws_tab_widget must be created before any proxy property access.
        self._ws_tab_widget = QTabWidget()
        self._ws_tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self._workspaces: list = []
        for ws_type, label in [
            ("front",    "Frame Front"),
            ("temple_r", "Temple R"),
            ("temple_l", "Temple L"),
            ("hinge",    "Hinge Pocket"),
        ]:
            ws = WorkspaceState(ws_type, self._status, self)
            self._workspaces.append(ws)
            self._ws_tab_widget.addTab(ws.view, label)

        self.setCentralWidget(self._ws_tab_widget)
        # Tab-change handler wired after toolbar+panel are built (needs toolbar actions).

        # From here on, proxy properties (self.scene, self.view, self._snap, …) all
        # resolve to _workspaces[0] (Frame Front) since the tab widget starts at 0.

        # Connect the calib tool for each workspace
        _vign = int(_vp_prefs.get("vignette", 0))
        for ws in self._workspaces:
            ws.view.set_vignette(_vign)
            ws.view.set_calib_tool(ws.calib_tool)
            ws.calib_tool.calibrated.connect(self._apply_calibration)
            ws.calib_tool.status_message.connect(self._status.showMessage)
            ws.draw_tool.curve_added.connect(self._on_curve_added)
            ws.draw_tool.status_message.connect(self._status.showMessage)
            ws.draw_tool.canceled.connect(self._on_draw_canceled)
            ws.circle_tool.curve_added.connect(self._on_curve_added)
            ws.circle_tool.status_message.connect(self._status.showMessage)
            ws.circle_tool.canceled.connect(self._on_draw_canceled)
            ws.dim_tool.dim_added.connect(self._on_dim_added)
            ws.dim_tool.status_message.connect(self._status.showMessage)
            ws.dim_tool.canceled.connect(self._on_draw_canceled)
            ws.trim_tool.trim_applied.connect(self._on_trim_applied)
            ws.trim_tool.status_message.connect(self._status.showMessage)
            ws.trim_tool.canceled.connect(self._on_trim_canceled)
            ws.fillet_tool.fillet_applied.connect(self._on_fillet_applied)
            ws.fillet_tool.status_message.connect(self._status.showMessage)
            ws.fillet_tool.canceled.connect(self._on_trim_canceled)
            ws.split_tool.split_applied.connect(self._on_split_applied)
            ws.split_tool.status_message.connect(self._status.showMessage)
            ws.split_tool.canceled.connect(self._on_split_canceled)
            ws.offset_tool.offset_applied.connect(self._on_offset_applied)
            ws.offset_tool.status_message.connect(self._status.showMessage)
            ws.offset_tool.canceled.connect(self._on_offset_canceled)
            ws.rebuild_tool.rebuild_applied.connect(self._on_rebuild_applied)
            ws.rebuild_tool.status_message.connect(self._status.showMessage)
            ws.rebuild_tool.canceled.connect(self._on_rebuild_canceled)
            ws.point_move_tool.moved.connect(self._on_point_moved)
            ws.point_move_tool.status_message.connect(self._status.showMessage)
            ws.text_tool.text_added.connect(self._on_text_added)
            ws.text_tool.canceled.connect(self._on_text_canceled)
            ws.text_tool.status_message.connect(self._status.showMessage)
            ws.point_move_tool.canceled.connect(self._on_point_move_canceled)

        self._build_toolbar()
        self._build_side_panel()
        _panel_act = self._prop_dock.toggleViewAction()
        _panel_act.setText("Panel")
        _panel_act.setToolTip("Show / hide the Properties panel")
        self._toolbar.addSeparator()
        self._toolbar.addAction(_panel_act)
        self._act_panel = _panel_act
        self._apply_toolbar_icons(False)
        self._build_menus()

        # ── Toolbar visibility and hotkey prefs ───────────────────────────
        _tb_defaults = _prefs_mod.DEFAULTS["toolbar"]
        _hk_defaults = _prefs_mod.DEFAULTS["hotkeys"]
        self._toolbar_prefs: dict = {**_tb_defaults, **self._prefs.get("toolbar", {})}
        self._hotkey_prefs:  dict = {**_hk_defaults, **self._prefs.get("hotkeys", {})}
        self._shortcuts:     dict = {}
        self._hotkey_targets: dict = {
            "line":         self._act_line.trigger,
            "spline":       self._act_spline.trigger,
            "circle":       self._act_circle.trigger,
            "arc":          self._act_arc.trigger,
            "arc_sec":      self._act_arc_sec.trigger,
            "fillet":       self._act_fillet.trigger,
            "dim":          self._act_dim.trigger,
            "trim":         self._act_trim.trigger,
            "split_curve":  self._act_split_curve.trigger,
            "offset":       self._act_offset.trigger,
            "rebuild":      self._act_rebuild.trigger,
            "point_move":   self._act_point_move.trigger,
            "text":         self._act_text.trigger,
            "snap_node_ep": self._snap_selected_node_to_endpoint,
            "move_gizmo":   self._toggle_move_gizmo,
            "join":         self._act_join.trigger,
            "bookmark":     self._add_bookmark,
            "insert_square": self._insert_square_char,
        }
        self._apply_toolbar_visibility(self._toolbar_prefs)
        self._apply_hotkeys(self._hotkey_prefs)
        # The insert-□ binding is matched by eventFilter, which must see key
        # presses in every window (modal dialogs included) — app-level filter.
        QApplication.instance().installEventFilter(self)

        # Pinned toolbar overflow pop-out (durable, global) — restore + persist.
        self._toolbar.set_pinned(
            bool(self._prefs.get("toolbar_pinned", False)), persist=False)
        self._toolbar.pin_changed.connect(self._on_toolbar_pin_changed)

        # ── Snap palette (per-type snap toggles + radius) ─────────────────
        from .snap_palette import SnapPalette
        from .canvas.snapping import SNAP_TYPE_KEYS
        # prefs.load() deep-merges DEFAULTS["snap_types"], so the dict is
        # complete; the all-True base only covers a hand-edited prefs file.
        snap_types = {k: True for k in SNAP_TYPE_KEYS}
        snap_types.update({k: bool(v) for k, v in
                           (self._prefs.get("snap_types") or {}).items()
                           if k in snap_types})
        snap_radius = int(self._prefs.get("snap_radius_px", 10))
        for ws in self._workspaces:
            ws.snap.set_enabled_types(snap_types)
            ws.snap.set_radius_px(snap_radius)
        self._snap_palette = SnapPalette(self)
        self._snap_palette.set_state(snap_types, snap_radius)
        self._snap_palette.types_changed.connect(self._on_snap_types_changed)
        self._snap_palette.radius_changed.connect(self._on_snap_radius_changed)
        self._act_snap_palette.toggled.connect(self._toggle_snap_palette)

        # ── Grid overlay (global) ─────────────────────────────────────────
        self._act_grid.blockSignals(True)
        self._act_grid.setChecked(bool(self._prefs.get("grid_visible", False)))
        self._act_grid.blockSignals(False)
        self._act_grid.toggled.connect(self._on_grid_toggled)
        self._apply_grid_config()

        # ── Per-workspace post-toolbar wiring ─────────────────────────────
        snap_fn = lambda: self._act_snap.isChecked()
        for ws in self._workspaces:
            ws.edit_tool.set_endpoint_snap_context(
                ws.doc_curves, ws.view, snap_enabled_fn=snap_fn
            )
            ws.edit_tool.about_to_modify.connect(self._pre_edit_snapshot)
            ws.edit_tool.node_selection_changed.connect(self._act_snap_ep.setEnabled)
            ws.edit_tool.node_selection_changed.connect(self._update_split_enabled)
            ws.scene.selectionChanged.connect(self._on_selection_changed)
            ws.scene.selectionChanged.connect(self._update_split_enabled)
            ws.scene.selectionChanged.connect(self._update_explode_enabled)
            ws.view.zoom_changed.connect(lambda _, _ws=ws: (
                self._update_info_label() if _ws is self._active_ws else None
            ))
            ws.view.set_delete_callback(self._delete_selected)
            ws.view.set_insert_node_callback(self._insert_node)
            ws.view.set_snap_to_endpoint_callback(self._snap_selected_node_to_endpoint)
            ws.view.set_move_callbacks(
                self._pre_move_selected,
                self._move_selected_by,
                self._end_move_selected,
            )
            ws.view.set_escape_callback(self._hide_move_gizmo)
            ws.view.set_face_moved_callback(self._mark_dirty)
            ws.view.measure_bar.commit_radius.connect(self._on_measure_commit_radius)
            ws.scene.set_dim_drag_callback(self._pre_edit_snapshot)
            ws.scene.set_text_edit_callback(self._edit_text_object)
            ws.on_document_changed = (
                lambda ws=ws: self._schedule_layer_panel_refresh(ws))
            ws.on_mirror_restored = (
                lambda on, ws=ws: self._act_mirror.setChecked(on)
                if ws is self._active_ws else setattr(ws, "mirror_enabled", on))
            ws.scene.geometry_changed = (
                lambda _curve=None, ws=ws: self._schedule_boxing_follow(ws))
            ws.scene.fill_auto_disabled = (
                lambda status, ws=ws: self._on_fill_auto_disabled(status, ws))
            ws.scene.lens_fill_auto_disabled = (
                lambda status, ws=ws: self._on_lens_fill_auto_disabled(status, ws))

        # ── Toggle actions wired to dispatch helpers (lambdas evaluate _active_ws) ─
        self._act_mirror.toggled.connect(self._on_mirror_toggled)
        self._act_guides.toggled.connect(lambda v: self._guides.set_visible(v))
        self._act_snap.toggled.connect(lambda v: self._snap.set_enabled(v))
        self._act_smooth.toggled.connect(lambda v: self._edit_tool.set_smooth_mode(v))
        self._act_boxing.toggled.connect(self._on_boxing_visible_toggled)
        self._act_stock.toggled.connect(lambda v: self._stock_guide.set_visible(v))
        self._act_pad.toggled.connect(lambda v: self._pad_guide.set_visible(v))

        # ── Apply prefs to toolbar / spinboxes (before connecting _save_prefs) ──
        p = self._prefs
        self._act_mirror.setChecked(p["mirror_on_startup"])
        self._act_guides.setChecked(p["guides_on_startup"])
        self._act_snap.setChecked(p["snap_on_startup"])
        self._act_smooth.setChecked(p["smooth_handles"])
        self._act_boxing.setChecked(p["boxing_on_startup"])
        self._act_stock.setChecked(p["stock_on_startup"])
        self._act_pad.setChecked(p["pad_on_startup"])
        self._boxing_a_spin.setValue(p["boxing_a_mm"])
        self._boxing_b_spin.setValue(p["boxing_b_mm"])
        self._boxing_dbl_spin.setValue(p["boxing_dbl_mm"])
        self._stock_w_spin.setValue(p["stock_width_mm"])
        self._stock_h_spin.setValue(p["stock_height_mm"])
        self._pad_w_spin.setValue(p["pad_width_mm"])
        self._pad_h_spin.setValue(p["pad_height_mm"])
        self._weight_spin.setValue(self._default_line_weight)

        # Sync initial mirror state + guide visibility for every workspace
        for ws in self._workspaces:
            horizontal = (ws.workspace_type in ("temple_r", "temple_l"))
            if ws.scene.mirror:
                ws.scene.mirror.set_enabled(p["mirror_on_startup"])
            ws.scene.set_mirror_display(p["mirror_on_startup"])
            ws.snap.set_mirror(0.0, p["mirror_on_startup"], horizontal=horizontal)
            ws.boxing_guide.set_mirror(p["mirror_on_startup"])
            ws.boxing_guide.set_visible(p["boxing_on_startup"])
            ws.stock_guide.set_visible(p["stock_on_startup"])
            ws.pad_guide.set_visible(p["pad_on_startup"])
            ws.const_guides.set_visible(p["guides_on_startup"])
            ws.snap.set_enabled(p["snap_on_startup"])
            ws.edit_tool.set_smooth_mode(p["smooth_handles"])

        # Save sidebar state into each workspace state so tab-switch restores correctly
        for ws in self._workspaces:
            ws.mirror_enabled = p["mirror_on_startup"]
            ws.snap_enabled   = p["snap_on_startup"]
            ws.smooth_handles = p["smooth_handles"]
            ws.guides_visible = p["guides_on_startup"]
            ws.boxing_visible = p["boxing_on_startup"]
            ws.stock_visible  = p["stock_on_startup"]
            ws.pad_visible    = p["pad_on_startup"]
            ws.boxing_a       = p["boxing_a_mm"]
            ws.boxing_b       = p["boxing_b_mm"]
            ws.boxing_dbl     = p["boxing_dbl_mm"]
            ws.stock_w        = p["stock_width_mm"]
            ws.stock_h        = p["stock_height_mm"]
            ws.pad_w          = p["pad_width_mm"]
            ws.pad_h          = p["pad_height_mm"]
            ws.lens_fill_opacity = self._default_lens_fill_opacity()
            ws.lens_fill_intensity = self._default_lens_fill_intensity()
            ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
            ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        front0 = self._workspaces[0]
        self._lens_fill_opacity_slider.blockSignals(True)
        self._lens_fill_opacity_slider.setValue(round(front0.lens_fill_opacity * 100))
        self._lens_fill_opacity_slider.blockSignals(False)
        self._lens_fill_intensity_slider.blockSignals(True)
        self._lens_fill_intensity_slider.setValue(
            slider_from_intensity(front0.lens_fill_intensity))
        self._lens_fill_intensity_slider.blockSignals(False)
        self._update_lens_fill_swatches(front0.lens_fill_top,
                                        front0.lens_fill_bottom,
                                        front0.lens_fill_intensity)

        # Workspace-specific default overrides (override prefs for non-front tabs)
        for temple in (self._workspaces[1], self._workspaces[2]):  # temple_r, temple_l
            temple.guides_visible = False
            temple.boxing_visible = False
            temple.pad_visible    = False
            temple.stock_visible  = True
            temple.stock_w        = 160.0
            temple.stock_h        = 30.0
            temple.const_guides.set_visible(False)
            temple.boxing_guide.set_visible(False)
            temple.pad_guide.set_visible(False)
            temple.stock_guide.set_visible(True)
            temple.stock_guide.set_width(160.0)
            temple.stock_guide.set_height(30.0)

        hinge = self._workspaces[3]
        hinge.guides_visible = False
        hinge.boxing_visible = False
        hinge.pad_visible    = False
        hinge.stock_visible  = True
        hinge.stock_w        = 10.0
        hinge.stock_h        = 20.0
        hinge.const_guides.set_visible(False)
        hinge.boxing_guide.set_visible(False)
        hinge.pad_guide.set_visible(False)
        hinge.stock_guide.set_visible(True)
        hinge.stock_guide.set_width(10.0)
        hinge.stock_guide.set_height(20.0)

        # Toolbar toggles and guide spinboxes are SESSION state (per-workspace,
        # saved/restored on tab switch). They deliberately do NOT write prefs:
        # startup defaults are only changed via Settings > Preferences.

        # Undo/redo keyboard shortcuts (window-scope)
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._handle_undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self._redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self._redo)
        QShortcut(QKeySequence("Ctrl+G"), self).activated.connect(self._group_selected)
        QShortcut(QKeySequence("Ctrl+Shift+G"), self).activated.connect(self._ungroup_selected)
        # Clipboard/select/transform shortcuts go through the focus guard so
        # they stay inert while a HUD text field has focus.
        for seq, target in [("Ctrl+C", self._copy_selected),
                            ("Ctrl+V", self._paste),
                            ("Ctrl+D", self._duplicate_selected),
                            ("Ctrl+A", self._select_all),
                            ("Ctrl+T", self._transform_selected)]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(
                lambda t=target: self._hotkey_dispatch(t))

        # Wire workspace tab-change now that all actions exist
        self._last_ws_idx = 0
        self._ws_tab_widget.currentChanged.connect(self._on_workspace_changed)
        self._show_guide_sections("front")
        self._apply_boxing_field_modes()
        self._refresh_library_panel()
        self._refresh_layer_panel()

        self._status.showMessage(
            "Ready  |  Middle-click drag to pan  |  Scroll to zoom"
        )
        self._update_info_label()

        # Apply dark mode from prefs (must be after all widgets are built)
        if self._dark_mode:
            self._act_dark.setChecked(True)
            self._toggle_dark_mode(True)

        # Defer fit until the window has its final painted size
        def _initial_fit():
            self._fit_view()
            self._workspaces[0].fitted = True
        QTimer.singleShot(0, self, _initial_fit)

        # ── Autosave + crash recovery ─────────────────────────────────────
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(self._AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._autosave_timer.start()
        QTimer.singleShot(400, self, self._offer_recovery)

        self._update_title()

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = PinnableToolBar("Tools")
        self._toolbar = tb
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        _tb_px = theme.toolbar_icon_px()
        tb.setIconSize(QSize(_tb_px, _tb_px))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)

        tool_group = QActionGroup(self)
        tool_group.setExclusive(True)

        self._act_select = QAction("Select", self, checkable=True, checked=True)
        self._act_select.setToolTip(
            "Select: click a curve to select it and show its nodes.\n"
            "Alt+click cycles through overlapping items at the same position."
        )
        self._act_line   = QAction("Line",   self, checkable=True)
        self._act_line.setToolTip(
            "Line: click to place nodes; double-click or Enter to finish.\n"
            "Type a length (mm) to lock radius; Tab to switch to angle lock."
        )
        self._act_spline = QAction("Spline", self, checkable=True)
        self._act_spline.setToolTip(
            "Spline: click to place nodes (Catmull-Rom smooth curve); double-click or Enter to finish.\n"
            "Type a length (mm) to lock radius; Tab to switch to angle lock."
        )
        self._act_circle = QAction("Circle", self, checkable=True)
        self._act_circle.setToolTip(
            "Circle: click to place center, click again to set radius.\n"
            "Snaps to existing nodes and quadrant points.")
        self._act_arc    = QAction("Arc",    self, checkable=True)
        self._act_arc.setToolTip(
            "Arc: click center, click start point (sets radius), click end point.\n"
            "Arc sweeps clockwise from start to end.")
        self._act_arc_sec = QAction("Arc\n3-pt", self, checkable=True)
        self._act_arc_sec.setToolTip(
            "Arc (start-end-center): click the start point, the end point, then\n"
            "the center. The center snaps to the chord's perpendicular bisector\n"
            "for a true circular arc; place it on either side to flip the bulge.")
        self._act_fillet = QAction("Fillet", self, checkable=True)
        self._act_fillet.setToolTip(
            "Fillet: click two connected lines, then type a radius (mm) + Enter\n"
            "to round the corner with a tangent arc (legs trimmed to the tangents).\n"
            "Esc to cancel.")
        self._act_dim    = QAction("Dim",    self, checkable=True)
        self._act_dim.setToolTip(
            "Dim: click two points to place a dimension annotation (mm).\n"
            "Snaps to curve nodes. Never exported.")

        self._act_trim = QAction("Trim", self, checkable=True)
        self._act_trim.setToolTip(
            "Trim: click a curve to remove the segment between its two nearest\n"
            "intersections with all other curves.  Stay in trim mode to trim more.\n"
            "Esc to cancel."
        )
        self._act_split_curve = QAction("Split\nCurve", self, checkable=True)
        self._act_split_curve.setToolTip(
            "Split Curve: click anywhere on a curve to split it into two open curves\n"
            "at that point.  Click near an intersection to split both curves at once.\n"
            "Esc to cancel."
        )

        self._act_offset = QAction("Offset", self, checkable=True)
        self._act_offset.setToolTip(
            "Offset (O): select a curve, then type a distance (mm) and press Enter\n"
            "to create a parallel curve at that offset.\n"
            "Closed shapes: positive = outward, negative = inward.\n"
            "Esc to cancel."
        )

        self._act_rebuild = QAction("Rebuild", self, checkable=True)
        self._act_rebuild.setToolTip(
            "Rebuild Spline (R): select a spline or polyline, then type a target\n"
            "node count (Tab switches to a tolerance in mm) and press Enter to\n"
            "rebuild it with fewer, cleaner nodes. The HUD shows the resulting\n"
            "max deviation live. Ideal for tidying imported DXF outlines.\n"
            "Esc to cancel."
        )

        self._act_point_move = QAction("Point\nMove", self, checkable=True)
        self._act_point_move.setToolTip(
            "Point Move (G): click a grab point on the selection, then click\n"
            "the destination (or type X Y coordinates) to move the selection\n"
            "so the grab point lands exactly on the destination.\n"
            "Esc to cancel."
        )

        self._act_text = QAction("Text", self, checkable=True)
        self._act_text.setToolTip(
            "Text (I): click an anchor point to place engraving text\n"
            "(any installed font, true mm cap height, rotatable).\n"
            "Lands on the ENGRAVING layer; converted to outlines at DXF export.\n"
            "Double-click placed text to edit it."
        )

        self._act_select.triggered.connect(self._set_tool_select)
        self._act_line.triggered.connect(self._set_tool_line)
        self._act_spline.triggered.connect(self._set_tool_spline)
        self._act_circle.triggered.connect(self._set_tool_circle)
        self._act_arc.triggered.connect(self._set_tool_arc)
        self._act_arc_sec.triggered.connect(self._set_tool_arc_sec)
        self._act_fillet.triggered.connect(self._set_tool_fillet)
        self._act_dim.triggered.connect(self._set_tool_dim)
        self._act_trim.triggered.connect(self._set_tool_trim)
        self._act_split_curve.triggered.connect(self._set_tool_split_curve)
        self._act_offset.triggered.connect(self._set_tool_offset)
        self._act_rebuild.triggered.connect(self._set_tool_rebuild)
        self._act_point_move.triggered.connect(self._set_tool_point_move)
        self._act_text.triggered.connect(self._set_tool_text)

        for act in (self._act_select, self._act_line, self._act_spline,
                    self._act_circle, self._act_arc, self._act_arc_sec,
                    self._act_fillet, self._act_dim,
                    self._act_text,
                    self._act_trim, self._act_split_curve, self._act_offset,
                    self._act_rebuild,
                    self._act_point_move):
            tool_group.addAction(act)
            tb.addAction(act)

        tb.addSeparator()

        self._act_mirror = QAction("Ghost", self, checkable=True, checked=True)
        self._act_mirror.setToolTip("Ghost: toggle the bridge mirror axis and ghost preview.")
        self._act_guides = QAction("Guides", self, checkable=True, checked=True)
        self._act_guides.setToolTip("Construction Guides: toggle bridge angle and apical radius guide lines.")
        self._act_snap   = QAction("Snap",   self, checkable=True, checked=True)
        self._act_snap.setToolTip("Snap: toggle node/handle snapping (hold Ctrl to suspend).")
        self._act_snap_palette = QAction("Snap\nTypes", self, checkable=True,
                                         checked=False)
        self._act_snap_palette.setToolTip(
            "Snap palette: choose WHICH targets snap (endpoint, midpoint,\n"
            "intersection, …) and set the snap radius. The Snap button stays\n"
            "the master on/off; holding Ctrl still suspends snapping.")
        self._act_grid = QAction("Grid", self, checkable=True, checked=False)
        self._act_grid.setToolTip(
            "Grid: show a millimeter grid overlay (spacing + divisions in\n"
            "Preferences ▸ Appearance). Enable the Grid snap in the snap\n"
            "palette to snap to its intersections.")
        self._act_smooth = QAction("Smooth\nHandles", self, checkable=True, checked=True)
        self._act_smooth.setToolTip(
            "Smooth Handles: when checked, moving one Bézier handle mirrors "
            "the opposite handle through the node (tangent-lock)."
        )
        self._act_boxing = QAction("Boxing", self, checkable=True, checked=True)
        self._act_boxing.setToolTip(
            "Boxing Guide: show A×B lens box with DBL separation as a dashed overlay.\n"
            "Set A, B, DBL in the Properties panel."
        )
        self._act_stock = QAction("Stock", self, checkable=True, checked=False)
        self._act_stock.setToolTip(
            "Stock Guide: show raw blank stock size as a dashed green rectangle centered at origin.\n"
            "Set dimensions in the Properties panel or Settings."
        )
        self._act_pad = QAction("Pad", self, checkable=True, checked=False)
        self._act_pad.setToolTip(
            "Pad Guide: show pad block size as a dashed purple rectangle centered at origin.\n"
            "Set dimensions in the Properties panel or Settings."
        )
        tb.addAction(self._act_mirror)
        tb.addAction(self._act_guides)
        tb.addAction(self._act_snap)
        tb.addAction(self._act_snap_palette)
        tb.addAction(self._act_grid)
        tb.addAction(self._act_smooth)
        tb.addAction(self._act_boxing)
        tb.addAction(self._act_stock)
        tb.addAction(self._act_pad)

        tb.addSeparator()

        self._act_mirror_close = QAction("Mirror\nClose", self)
        self._act_mirror_close.setToolTip(
            "Mirror-Close: combine selected open curve with its mirror to form "
            "a single closed shape.\nThe two endpoints are moved onto the mirror axis."
        )
        self._act_mirror_close.triggered.connect(self._copy_across_mirror)
        tb.addAction(self._act_mirror_close)

        self._act_dup_mirror = QAction("Mirror", self)
        self._act_dup_mirror.setToolTip(
            "Mirror: create real mirrored copies of the selected curves\n"
            "opposite the ghost axis, breaking live symmetry.\n"
            "Points on the axis are shared — use Join or Mirror-Close\n"
            "afterward to connect the halves into closed shapes."
        )
        self._act_dup_mirror.triggered.connect(self._on_duplicate_mirror)
        tb.addAction(self._act_dup_mirror)

        self._act_copy_temple = QAction("Temple\nCopy", self)
        self._act_copy_temple.setToolTip(
            "Temple Copy: send a mirrored copy of this temple's content into\n"
            "the other temple workspace (R → L or L → R).\n"
            "Asks for confirmation — it replaces everything in the target\n"
            "workspace (Ctrl+Z there restores it)."
        )
        self._act_copy_temple.setVisible(False)  # shown only in temple_r / temple_l
        self._act_copy_temple.triggered.connect(self._copy_temple_to_other)
        tb.addAction(self._act_copy_temple)

        self._act_join = QAction("Join", self)
        self._act_join.setToolTip(
            "Join: merge 2+ selected open curves into one curve by connecting "
            "their nearest endpoints (within 2 mm).\n"
            "Result is closed if the chain's ends also meet."
        )
        self._act_join.triggered.connect(self._join_selected_curves)
        tb.addAction(self._act_join)

        self._act_snap_ep = QAction("Snap\nNode", self)
        self._act_snap_ep.setEnabled(False)
        self._act_snap_ep.setToolTip(
            "Snap Node to Endpoint (E):\n"
            "Move the selected node (red) to the nearest endpoint of any other open curve.\n"
            "Select a curve, click a node to turn it red, then press this button."
        )
        self._act_snap_ep.triggered.connect(self._snap_selected_node_to_endpoint)
        tb.addAction(self._act_snap_ep)

        self._act_split = QAction("Split", self)
        self._act_split.setEnabled(False)
        self._act_split.setToolTip(
            "Split: break a curve at the selected node (red) into two open curves.\n"
            "For a closed curve, splitting produces one open curve.\n"
            "Select a curve, click a node to turn it red, then press Split."
        )
        self._act_split.triggered.connect(self._split_at_node)
        tb.addAction(self._act_split)

        self._act_explode = QAction("Explode", self)
        self._act_explode.setEnabled(False)
        self._act_explode.setToolTip(
            "Explode: break selected curve(s) into individual 2-node segments.\n"
            "Each segment preserves the original handles (spline shapes intact)."
        )
        self._act_explode.triggered.connect(self._explode_selected)
        tb.addAction(self._act_explode)

        self._act_fit = QAction("Fit", self)
        self._act_fit.setToolTip("Fit: zoom to fit all content in view.")
        self._act_fit.triggered.connect(self._fit_view)
        tb.addAction(self._act_fit)

        # The tooltip switch: a ? at the foot of the bar, outside the
        # customizable set and out of the ⋯ overflow's reach, as GuildModel's
        # sits at the end of its toolbar. Its own tooltip shows even when
        # tooltips are off, or nobody could find out what it does.
        self._act_tooltips = QAction("Tooltips", self, checkable=True)
        self._act_tooltips.setChecked(bool(self._prefs.get("tooltips", True)))
        self._act_tooltips.toggled.connect(self._on_tooltips_toggled)
        self._tooltip_filter.set_exempt([tb.set_trailing_action(self._act_tooltips)])
        self._on_tooltips_toggled(self._act_tooltips.isChecked(), announce=False)

        # Map prefs keys → QAction objects (used by visibility and hotkey systems)
        self._toolbar_actions: dict[str, QAction] = {
            "select":       self._act_select,
            "line":         self._act_line,
            "spline":       self._act_spline,
            "circle":       self._act_circle,
            "arc":          self._act_arc,
            "arc_sec":      self._act_arc_sec,
            "fillet":       self._act_fillet,
            "dim":          self._act_dim,
            "trim":         self._act_trim,
            "split_curve":  self._act_split_curve,
            "offset":       self._act_offset,
            "rebuild":      self._act_rebuild,
            "point_move":   self._act_point_move,
            "text":         self._act_text,
            "ghost":        self._act_mirror,
            "guides":       self._act_guides,
            "snap":         self._act_snap,
            "snap_palette": self._act_snap_palette,
            "grid":         self._act_grid,
            "smooth":       self._act_smooth,
            "boxing":       self._act_boxing,
            "stock":        self._act_stock,
            "pad":          self._act_pad,
            "mirror":       self._act_dup_mirror,
            "mirror_close": self._act_mirror_close,
            "copy_temple":  self._act_copy_temple,
            "join":         self._act_join,
            "snap_node":    self._act_snap_ep,
            "split":        self._act_split,
            "explode":      self._act_explode,
            "fit":          self._act_fit,
        }

    # ------------------------------------------------------------------
    # Side panel (dock)
    # ------------------------------------------------------------------

    def _build_side_panel(self):
        self._prop_dock = QDockWidget("Properties", self)
        self._prop_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self._prop_dock.setTitleBarWidget(QWidget())
        self._prop_dock.setMinimumWidth(_DOCK_WIDTH)

        tabs = QTabWidget()
        tabs.tabBar().setExpanding(False)

        # ── Tab 0: Curve ──────────────────────────────────────────────────
        curve_w = QWidget()
        curve_lay = QVBoxLayout(curve_w)
        curve_lay.setContentsMargins(8, 8, 8, 8)
        curve_lay.setSpacing(12)

        draw_box = QGroupBox("Drawing")
        draw_lay = QFormLayout(draw_box)
        draw_lay.setSpacing(6)

        self._weight_spin = QDoubleSpinBox()
        self._weight_spin.setRange(0.25, 10.0)
        self._weight_spin.setDecimals(2)
        self._weight_spin.setSingleStep(0.25)
        self._weight_spin.setValue(1.5)
        # Commit on Enter/blur, not per keystroke — each change pushes an
        # undo snapshot, so typing "2.5" must not create three undo steps.
        self._weight_spin.setKeyboardTracking(False)
        self._weight_spin.setToolTip(
            "Line weight (screen pixels, cosmetic).\n"
            "Applies to the selected curve(s). New curves take the default from "
            "Preferences ▸ General."
        )
        self._weight_spin.valueChanged.connect(self._on_weight_spin_changed)
        draw_lay.addRow("Line weight:", self._weight_spin)

        curve_lay.addWidget(draw_box)

        # ── Layers (the single home for everything layer-related) ─────────
        from PySide6.QtWidgets import QHeaderView
        layers_box = QGroupBox("Layers")
        layers_lay = QVBoxLayout(layers_box)
        layers_lay.setContentsMargins(4, 4, 4, 4)

        self._layer_tree = LayerTree()
        self._layer_tree.setHeaderHidden(True)
        self._layer_tree.setColumnCount(3)
        hdr = self._layer_tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._layer_tree.setColumnWidth(1, 28)
        self._layer_tree.setColumnWidth(2, 28)
        self._layer_tree.setMinimumHeight(170)
        self._layer_tree.setToolTip(
            "Layers and the objects on them.\n"
            "Click a layer name to make it the active drawing layer (bold).\n"
            "Click the eye to show/hide; hidden layers offer no snap targets.\n"
            "Click the padlock to lock/unlock; locked layers stay visible and\n"
            "snappable but cannot be selected or modified.\n"
            "Click an object to select it on the canvas; Ctrl/Shift-click\n"
            "for several, then Delete removes them.\n"
            "Drag an object onto another layer to move it there.\n"
            "Right-click for: select all on layer, move selection to layer."
        )
        self._layer_tree_expanded: dict = {}    # ws_type -> {Layer: bool}
        self._layer_tree.itemClicked.connect(self._on_layer_tree_clicked)
        self._layer_tree.itemExpanded.connect(
            lambda it: self._on_layer_row_expanded(it, True))
        self._layer_tree.itemCollapsed.connect(
            lambda it: self._on_layer_row_expanded(it, False))
        self._layer_tree.itemSelectionChanged.connect(
            self._on_layer_tree_selection_changed)
        self._layer_tree.curves_dropped.connect(self._on_layer_tree_drop)
        self._layer_tree.delete_requested.connect(self._delete_selected)
        self._layer_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._layer_tree.customContextMenuRequested.connect(
            self._on_layer_tree_menu)
        layers_lay.addWidget(self._layer_tree)
        curve_lay.addWidget(layers_box)

        # ── Measurements: Frame Front ──────────────────────────────────────
        meas_front_box = QGroupBox("Measurements")
        meas_front_lay = QFormLayout(meas_front_box)
        meas_front_lay.setSpacing(6)

        self._meas_frame_width_lbl = QLabel("—")
        meas_front_lay.addRow("Frame width:", self._meas_frame_width_lbl)

        self._meas_frame_height_lbl = QLabel("—")
        meas_front_lay.addRow("Frame height:", self._meas_frame_height_lbl)

        self._meas_dbl_lbl = QLabel("—")
        meas_front_lay.addRow("DBL:", self._meas_dbl_lbl)

        self._meas_od_a_lbl  = QLabel("—")
        self._meas_od_b_lbl  = QLabel("—")
        self._meas_od_ed_lbl = QLabel("—")
        meas_front_lay.addRow("OD  A:", self._meas_od_a_lbl)
        meas_front_lay.addRow("OD  B:", self._meas_od_b_lbl)
        meas_front_lay.addRow("OD  ED:", self._meas_od_ed_lbl)

        self._meas_os_a_lbl  = QLabel("—")
        self._meas_os_b_lbl  = QLabel("—")
        self._meas_os_ed_lbl = QLabel("—")
        meas_front_lay.addRow("OS  A:", self._meas_os_a_lbl)
        meas_front_lay.addRow("OS  B:", self._meas_os_b_lbl)
        meas_front_lay.addRow("OS  ED:", self._meas_os_ed_lbl)

        # No Refresh button: every document change, node drag and layer move
        # refreshes these (the 2026-09-29 review checked each path).

        curve_lay.addWidget(meas_front_box)
        self._meas_front_box = meas_front_box

        # ── Measurements: Temple ───────────────────────────────────────────
        meas_temple_box = QGroupBox("Measurements")
        meas_temple_lay = QFormLayout(meas_temple_box)
        meas_temple_lay.setSpacing(6)

        self._meas_temple_length_lbl = QLabel("—")
        meas_temple_lay.addRow("Temple length:", self._meas_temple_length_lbl)

        self._meas_endpiece_lbl = QLabel("—")
        meas_temple_lay.addRow("Endpiece width:", self._meas_endpiece_lbl)

        curve_lay.addWidget(meas_temple_box)
        self._meas_temple_box = meas_temple_box

        curve_lay.addStretch()
        # Scrolled like Guides and Canvas: unscrolled, this tab and Library
        # held the window at 619 px or taller, and on a short laptop panel the
        # status bar and the ? fell off the screen.
        tabs.addTab(SettingsDialog._scrolled(curve_w), "Properties")

        # ── Tab 1: Guides (scrollable) ────────────────────────────────────
        guides_inner = QWidget()
        guides_lay = QVBoxLayout(guides_inner)
        guides_lay.setContentsMargins(8, 8, 8, 8)
        guides_lay.setSpacing(12)

        guide_box = QGroupBox("Construction (Forming)")
        guide_lay = QFormLayout(guide_box)
        guide_lay.setSpacing(6)

        from .construction import ConstructionGuides as _CG
        self._bridge_angle_spin = QDoubleSpinBox()
        self._bridge_angle_spin.setRange(0, 45)
        self._bridge_angle_spin.setSuffix("°")
        self._bridge_angle_spin.setSingleStep(0.5)
        self._bridge_angle_spin.setValue(_CG.DEFAULT_BRIDGE_ANGLE_DEG)
        # lambdas so each call dispatches to the CURRENT active workspace's guides
        self._bridge_angle_spin.valueChanged.connect(
            lambda v: self._guides.set_bridge_angle(v))
        # bridge angle + apical radius persist in the file (forming metadata)
        self._bridge_angle_spin.valueChanged.connect(
            lambda _: self._mark_dirty())
        guide_lay.addRow("Frontal angle:", self._bridge_angle_spin)

        self._apical_spin = QDoubleSpinBox()
        self._apical_spin.setRange(2.0, 24.0)
        self._apical_spin.setSuffix(" mm")
        self._apical_spin.setSingleStep(0.5)
        self._apical_spin.setValue(_CG.DEFAULT_APICAL_RADIUS_MM)
        self._apical_spin.valueChanged.connect(
            lambda v: self._guides.set_apical_radius(v))
        self._apical_spin.valueChanged.connect(
            lambda _: self._mark_dirty())
        guide_lay.addRow("Apical radius:", self._apical_spin)

        self._guide_crest_height_spin = QDoubleSpinBox()
        self._guide_crest_height_spin.setRange(-50.0, 50.0)
        self._guide_crest_height_spin.setSuffix(" mm")
        self._guide_crest_height_spin.setSingleStep(0.5)
        self._guide_crest_height_spin.setValue(0.0)
        self._guide_crest_height_spin.setToolTip(
            "Vertical position of the apical radius arc.\n"
            "0 = arc apex at the datum line; positive = arc shifts down."
        )
        self._guide_crest_height_spin.valueChanged.connect(
            lambda v: self._guides.set_crest_height(v))
        guide_lay.addRow("Crest height:", self._guide_crest_height_spin)

        self._guide_spread_spin = QDoubleSpinBox()
        self._guide_spread_spin.setRange(0.0, 100.0)
        self._guide_spread_spin.setSuffix(" mm")
        self._guide_spread_spin.setSingleStep(0.5)
        self._guide_spread_spin.setValue(4.0)
        self._guide_spread_spin.setToolTip(
            "Horizontal distance from mirror axis to each arm pivot.\n"
            "0 = both arms meet at arc top;  R = arms start at arc quadrant."
        )
        self._guide_spread_spin.valueChanged.connect(
            lambda v: self._guides.set_spread(v))
        guide_lay.addRow("Crest width:", self._guide_spread_spin)

        self._guide_drop_spin = QDoubleSpinBox()
        self._guide_drop_spin.setRange(-50.0, 100.0)
        self._guide_drop_spin.setSuffix(" mm")
        self._guide_drop_spin.setSingleStep(0.5)
        self._guide_drop_spin.setValue(0.0)
        self._guide_drop_spin.setToolTip(
            "Vertical drop of arm pivots below the arc top (0 = at arc top).\n"
            "Set to the arc radius to start arms at the arc quadrant."
        )
        self._guide_drop_spin.valueChanged.connect(
            lambda v: self._guides.set_pivot_y(v))
        guide_lay.addRow("Angle height:", self._guide_drop_spin)

        guides_lay.addWidget(guide_box)
        self._construction_guide_box = guide_box   # ref for section show/hide

        boxing_box = QGroupBox("Boxing System")
        boxing_lay = QFormLayout(boxing_box)
        boxing_lay.setSpacing(6)

        # A and B share a chain (aspect-link) toggle that spans both rows.
        # keyboardTracking off → a typed value commits on Enter/blur (not every
        # digit), and stepping commits instantly — so locked-resize fires once
        # per real change instead of mid-typing.
        self._boxing_a_spin = QDoubleSpinBox()
        self._boxing_a_spin.setRange(20.0, 90.0)
        self._boxing_a_spin.setSuffix(" mm")
        self._boxing_a_spin.setSingleStep(0.5)
        self._boxing_a_spin.setDecimals(1)
        self._boxing_a_spin.setKeyboardTracking(False)
        self._boxing_a_spin.setValue(50.0)
        self._boxing_a_spin.valueChanged.connect(self._on_boxing_a_value)

        self._boxing_b_spin = QDoubleSpinBox()
        self._boxing_b_spin.setRange(10.0, 70.0)
        self._boxing_b_spin.setSuffix(" mm")
        self._boxing_b_spin.setSingleStep(0.5)
        self._boxing_b_spin.setDecimals(1)
        self._boxing_b_spin.setKeyboardTracking(False)
        self._boxing_b_spin.setValue(30.0)
        self._boxing_b_spin.valueChanged.connect(self._on_boxing_b_value)

        self._chain_btn = QToolButton()
        self._chain_btn.setCheckable(True)
        self._chain_btn.setIcon(_make_icon(
            "link-chain", theme.color("chrome.ink"),
            theme.color("chrome.checked_ink")))
        self._chain_btn.setToolTip(
            "Link A and B: while locked, resizing one scales the other to keep\n"
            "the lens aspect ratio. Off = resize A and B independently.")
        self._chain_btn.toggled.connect(self._on_chain_toggled)

        ab_w = QWidget()
        ab_grid = QGridLayout(ab_w)
        ab_grid.setContentsMargins(0, 0, 0, 0)
        ab_grid.setHorizontalSpacing(6)
        ab_grid.setVerticalSpacing(6)
        ab_grid.addWidget(QLabel("A (width):"), 0, 0)
        ab_grid.addWidget(self._boxing_a_spin,  0, 1)
        ab_grid.addWidget(QLabel("B (height):"), 1, 0)
        ab_grid.addWidget(self._boxing_b_spin,  1, 1)
        ab_grid.addWidget(self._chain_btn,      0, 2, 2, 1)
        ab_grid.setColumnStretch(1, 1)
        boxing_lay.addRow(ab_w)

        self._boxing_dbl_spin = QDoubleSpinBox()
        self._boxing_dbl_spin.setRange(5.0, 45.0)
        self._boxing_dbl_spin.setSuffix(" mm")
        self._boxing_dbl_spin.setSingleStep(0.5)
        self._boxing_dbl_spin.setDecimals(1)
        # As A and B: with the lens locked every value moves the lenses (and
        # pushes an undo step), so typing 17.5 went through 17 and was then
        # rewritten mid-typing to "17.0 mm", dropping the ".5".
        self._boxing_dbl_spin.setKeyboardTracking(False)
        self._boxing_dbl_spin.setValue(18.0)
        self._boxing_dbl_spin.valueChanged.connect(self._on_boxing_dbl_value)
        boxing_lay.addRow("DBL:", self._boxing_dbl_spin)

        # ── Snap / Lock to lens + bevel (M11/M12) ───────────────────────
        self._boxing_snap_chk = QCheckBox("Snap to lens shape")
        self._boxing_snap_chk.setToolTip(
            "Fit the boxing box + bevel outline to the actual LENS path.\n"
            "A/B/DBL then show the live finished-lens measurements; editing\n"
            "or moving the lens updates them in real time.")
        self._boxing_snap_chk.toggled.connect(self._on_boxing_snap_toggled)
        boxing_lay.addRow(self._boxing_snap_chk)

        self._lock_shape_chk = QCheckBox("Lock lens shape")
        self._lock_shape_chk.setEnabled(False)   # only available once snapped
        self._lock_shape_chk.setToolTip(
            "Freeze the lens spline: it can still be moved (changing DBL), but\n"
            "its size changes only by typing new A / B values, which restretch\n"
            "the shape accurately. Draw once, offer many sizes.")
        self._lock_shape_chk.toggled.connect(self._on_lock_shape_toggled)
        boxing_lay.addRow(self._lock_shape_chk)

        self._outline_lock_chk = QCheckBox("Lock outline to lens")
        self._outline_lock_chk.setEnabled(False)   # only while the shape is locked
        self._outline_lock_chk.setToolTip(
            "Co-resize the frame OUTLINE with the lens, keeping a constant\n"
            "eyewire wall (flats and corners preserved). Open outlines grow\n"
            "from the bridge side; closed (finished) frames grow symmetrically.")
        self._outline_lock_chk.toggled.connect(self._on_outline_lock_toggled)
        boxing_lay.addRow(self._outline_lock_chk)

        self._bevel_combo = QComboBox()
        # (label, preset-key) — order matches the BEVEL_PRESETS intent
        self._bevel_choices = [
            ("Flat / Rimless", "flat"),
            ("Horn / Metal",   "horn_metal"),
            ("Acetate",        "acetate"),
            ("Custom",         "custom"),
        ]
        for label, _key in self._bevel_choices:
            self._bevel_combo.addItem(label)
        self._bevel_combo.setCurrentIndex(2)   # Acetate
        self._bevel_combo.currentIndexChanged.connect(self._on_bevel_preset_changed)
        boxing_lay.addRow("Bevel:", self._bevel_combo)

        self._bevel_depth_spin = QDoubleSpinBox()
        self._bevel_depth_spin.setRange(0.0, 5.0)
        self._bevel_depth_spin.setSuffix(" mm")
        self._bevel_depth_spin.setSingleStep(0.1)
        self._bevel_depth_spin.setDecimals(2)
        self._bevel_depth_spin.setValue(BEVEL_PRESETS["acetate"])
        self._bevel_depth_spin.setEnabled(False)   # only editable for Custom
        self._bevel_depth_spin.setToolTip(
            "Outward offset of the finished (beveled) lens beyond the lens shape.")
        self._bevel_depth_spin.valueChanged.connect(self._on_bevel_depth_changed)
        boxing_lay.addRow("Bevel depth:", self._bevel_depth_spin)

        guides_lay.addWidget(boxing_box)
        self._boxing_guide_box = boxing_box   # ref for section show/hide

        stock_box = QGroupBox("Stock Blank")
        stock_lay = QFormLayout(stock_box)
        stock_lay.setSpacing(6)

        self._stock_w_spin = QDoubleSpinBox()
        self._stock_w_spin.setRange(5.0, 400.0)
        self._stock_w_spin.setSuffix(" mm")
        self._stock_w_spin.setSingleStep(1.0)
        self._stock_w_spin.setValue(170.0)
        self._stock_w_spin.setToolTip("Width of raw stock blank (mm). Toggle visibility with the Stock button.")
        self._stock_w_spin.valueChanged.connect(self._on_stock_width_changed)
        stock_lay.addRow("Width:", self._stock_w_spin)

        self._stock_h_spin = QDoubleSpinBox()
        self._stock_h_spin.setRange(5.0, 200.0)
        self._stock_h_spin.setSuffix(" mm")
        self._stock_h_spin.setSingleStep(1.0)
        self._stock_h_spin.setValue(85.0)
        self._stock_h_spin.setToolTip("Height of raw stock blank (mm).")
        self._stock_h_spin.valueChanged.connect(
            lambda v: self._stock_guide.set_height(v))
        stock_lay.addRow("Height:", self._stock_h_spin)

        guides_lay.addWidget(stock_box)
        self._stock_guide_box = stock_box   # ref for section show/hide

        pad_box = QGroupBox("Pad Block")
        pad_lay = QFormLayout(pad_box)
        pad_lay.setSpacing(6)

        self._pad_w_spin = QDoubleSpinBox()
        self._pad_w_spin.setRange(10.0, 200.0)
        self._pad_w_spin.setSuffix(" mm")
        self._pad_w_spin.setSingleStep(0.5)
        self._pad_w_spin.setValue(45.0)
        self._pad_w_spin.setToolTip("Width of pad block (mm). Toggle visibility with the Pad button.")
        self._pad_w_spin.valueChanged.connect(
            lambda v: self._pad_guide.set_width(v))
        pad_lay.addRow("Width:", self._pad_w_spin)

        self._pad_h_spin = QDoubleSpinBox()
        self._pad_h_spin.setRange(10.0, 200.0)
        self._pad_h_spin.setSuffix(" mm")
        self._pad_h_spin.setSingleStep(0.5)
        self._pad_h_spin.setValue(45.0)
        self._pad_h_spin.setToolTip("Height of pad block (mm).")
        self._pad_h_spin.valueChanged.connect(
            lambda v: self._pad_guide.set_height(v))
        pad_lay.addRow("Height:", self._pad_h_spin)

        guides_lay.addWidget(pad_box)
        self._pad_guide_box = pad_box   # ref for section show/hide

        # ── Frame Fill (display-only render overlay, M8) ─────────────────
        fill_box = QGroupBox("Frame Fill")
        fill_lay = QFormLayout(fill_box)
        fill_lay.setSpacing(6)

        self._fill_show_chk = QCheckBox("Show fill")
        self._fill_show_chk.setToolTip(
            "Fill the frame interior (OUTLINE minus LENS apertures) with a\n"
            "translucent color over the face photo. Display-only — never\n"
            "exported to DXF/SVG geometry."
        )
        self._fill_show_chk.toggled.connect(self._on_fill_visible_toggled)
        fill_lay.addRow(self._fill_show_chk)

        # Color or material swatch. A supplier's acetate sample sheet scaled
        # onto the blank shows the frame in the material it will be cut from —
        # the thing a flat color can't do for a laminate or a tortoise.
        self._fill_style_combo = QComboBox()
        self._fill_style_combo.addItem("Color", "color")
        self._fill_style_combo.addItem("Image",  "image")
        self._fill_style_combo.setToolTip(
            "Color: a flat translucent tint.\n"
            "Image: a material swatch, scaled to span the Stock Blank width\n"
            "and centered on the origin — the piece of sheet under the frame."
        )
        self._fill_style_combo.currentIndexChanged.connect(
            self._on_fill_style_changed)
        fill_lay.addRow("Style:", self._fill_style_combo)

        self._fill_color_btn = QPushButton("Color…")
        self._fill_color_btn.clicked.connect(self._on_fill_color_clicked)
        self._update_fill_swatch("#2a6099")
        fill_lay.addRow("Color:", self._fill_color_btn)

        img_row = QWidget()
        img_lay = QHBoxLayout(img_row)
        img_lay.setContentsMargins(0, 0, 0, 0)
        img_lay.setSpacing(4)
        self._fill_image_btn = QPushButton("Choose…")
        # Swatch names run long ("TORTOISE-DEMI-AMBER-3MM-SHEET.png"); let the
        # button take whatever the row leaves it and elide what won't fit,
        # rather than dragging the whole sidebar wider.
        self._fill_image_btn.setSizePolicy(QSizePolicy.Policy.Ignored,
                                           QSizePolicy.Policy.Fixed)
        self._fill_image_btn.installEventFilter(self)
        self._fill_image_full_text = "Choose…"
        self._fill_image_btn.clicked.connect(self._on_fill_image_clicked)
        self._fill_image_clear_btn = QPushButton("✕")
        # The app stylesheet gives every QPushButton min-width: 54px, which Qt
        # promotes over a plain setFixedWidth — the clear button came out 76px
        # wide and ate the filename beside it. Pin it square in a local rule
        # instead: a stylesheet width is re-applied over the widget's own
        # minimum, so setFixedWidth alone gets overruled and a bare
        # `min-width: 0` lets a narrow panel squeeze the button to a sliver.
        # The rule sizes the CONTENT box, so the theme's 1px border on each
        # side comes off the target — see build_qss.
        _clear_box = max(8, self._fill_image_btn.sizeHint().height() - 2)
        self._fill_image_clear_btn.setStyleSheet(
            f"QPushButton {{ min-width: {_clear_box}px;"
            f" max-width: {_clear_box}px; min-height: {_clear_box}px;"
            f" max-height: {_clear_box}px; padding: 0px; }}")
        self._fill_image_clear_btn.setToolTip("Forget the swatch and go back to the color.")
        self._fill_image_clear_btn.clicked.connect(self._on_fill_image_cleared)
        img_lay.addWidget(self._fill_image_btn, 1)
        img_lay.addWidget(self._fill_image_clear_btn)
        fill_lay.addRow("Image:", img_row)

        self._fill_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_opacity_slider.setRange(0, 100)
        self._fill_opacity_slider.setValue(50)
        self._fill_opacity_slider.valueChanged.connect(self._on_fill_opacity_changed)
        fill_lay.addRow("Opacity:", self._fill_opacity_slider)

        guides_lay.addWidget(fill_box)
        self._fill_box = fill_box   # ref for section show/hide

        # ── Lens Fill (display-only render overlay, v1.2) ─────────────────
        lens_fill_box = QGroupBox("Lens Fill")
        lens_fill_lay = QFormLayout(lens_fill_box)
        lens_fill_lay.setSpacing(6)

        self._lens_fill_show_chk = QCheckBox("Show lens fill")
        self._lens_fill_show_chk.setToolTip(
            "Tint each LENS aperture with a vertical two-color gradient, the\n"
            "way a dyed lens runs dark to light. Display-only — never exported\n"
            "to DXF/SVG geometry."
        )
        self._lens_fill_show_chk.toggled.connect(self._on_lens_fill_visible_toggled)
        lens_fill_lay.addRow(self._lens_fill_show_chk)

        # Swatch-only buttons — the row label already says which stop it is, so
        # a "Top…" caption inside the button would only crowd the color bar.
        self._lens_top_btn = QPushButton()
        self._lens_top_btn.setIconSize(QSize(*_LENS_SWATCH_PX))
        self._lens_top_btn.clicked.connect(lambda: self._on_lens_fill_color_clicked("top"))
        self._lens_bottom_btn = QPushButton()
        self._lens_bottom_btn.setIconSize(QSize(*_LENS_SWATCH_PX))
        self._lens_bottom_btn.clicked.connect(lambda: self._on_lens_fill_color_clicked("bottom"))

        self._lens_top_bpi_btn = QToolButton()
        self._lens_top_bpi_btn.setText("BPI")
        self._lens_top_bpi_btn.setToolTip(
            "Pick the top color from the BPI tint reference.")
        self._lens_top_bpi_btn.clicked.connect(lambda: self._show_tint_picker("top"))
        self._lens_bottom_bpi_btn = QToolButton()
        self._lens_bottom_bpi_btn.setText("BPI")
        self._lens_bottom_bpi_btn.setToolTip(
            "Pick the bottom color from the BPI tint reference.")
        self._lens_bottom_bpi_btn.clicked.connect(lambda: self._show_tint_picker("bottom"))

        self._lens_link_btn = QToolButton()
        self._lens_link_btn.setCheckable(True)
        self._lens_link_btn.setIcon(_make_icon(
            "link-chain", theme.color("chrome.ink"),
            theme.color("chrome.checked_ink")))
        self._lens_link_btn.setToolTip(
            "Link top and bottom: while locked both stops stay the same color,\n"
            "so the lens takes a flat tint. Off = a true vertical gradient.")
        self._lens_link_btn.toggled.connect(self._on_lens_fill_link_toggled)

        lens_grid_w = QWidget()
        lens_grid = QGridLayout(lens_grid_w)
        lens_grid.setContentsMargins(0, 0, 0, 0)
        lens_grid.setHorizontalSpacing(6)
        lens_grid.setVerticalSpacing(6)
        lens_grid.addWidget(QLabel("Top:"),           0, 0)
        lens_grid.addWidget(self._lens_top_btn,       0, 1)
        lens_grid.addWidget(self._lens_top_bpi_btn,   0, 2)
        lens_grid.addWidget(QLabel("Bottom:"),        1, 0)
        lens_grid.addWidget(self._lens_bottom_btn,    1, 1)
        lens_grid.addWidget(self._lens_bottom_bpi_btn, 1, 2)
        lens_grid.addWidget(self._lens_link_btn,      0, 3, 2, 1)
        lens_grid.setColumnStretch(1, 1)
        lens_fill_lay.addRow(lens_grid_w)

        if not _bpi_tints.load_tints():
            # No shipped table (stripped build) — hide the entry points rather
            # than offering a picker with nothing in it.
            self._lens_top_bpi_btn.setVisible(False)
            self._lens_bottom_bpi_btn.setVisible(False)

        self._lens_fill_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self._lens_fill_intensity_slider.setRange(0, 100)
        self._lens_fill_intensity_slider.setValue(
            slider_from_intensity(DEFAULT_LENS_FILL_INTENSITY))
        self._lens_fill_intensity_slider.setToolTip(
            "How deeply the dye reads — the tint's own strength, as opposed to\n"
            "Opacity, which is how much of the drawing behind it shows through.\n\n"
            "Reference swatches (BPI's included) show a dye at one modest depth\n"
            "over white, so a color picked from one usually needs deepening to\n"
            "look like the lens you mean. The default sits a quarter along, at\n"
            "the color exactly as picked; drag right for a deeper dye.")
        self._lens_fill_intensity_slider.valueChanged.connect(
            self._on_lens_fill_intensity_changed)
        lens_fill_lay.addRow("Intensity:", self._lens_fill_intensity_slider)

        self._lens_fill_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._lens_fill_opacity_slider.setRange(0, 100)
        self._lens_fill_opacity_slider.setValue(
            int(round(DEFAULT_LENS_FILL_OPACITY * 100)))
        self._lens_fill_opacity_slider.setToolTip(
            "How much the tint covers what is behind it — the face photo, the\n"
            "frame fill. For the tint's own strength, use Intensity.")
        self._lens_fill_opacity_slider.valueChanged.connect(
            self._on_lens_fill_opacity_changed)
        lens_fill_lay.addRow("Opacity:", self._lens_fill_opacity_slider)

        guides_lay.addWidget(lens_fill_box)
        self._lens_fill_box = lens_fill_box   # ref for section show/hide
        self._update_lens_fill_swatches(DEFAULT_LENS_FILL_TOP,
                                        DEFAULT_LENS_FILL_BOTTOM,
                                        DEFAULT_LENS_FILL_INTENSITY)
        guides_lay.addStretch()

        guides_scroll = QScrollArea()
        guides_scroll.setWidgetResizable(True)
        guides_scroll.setFrameShape(guides_scroll.Shape.NoFrame)
        guides_scroll.setWidget(guides_inner)
        tabs.addTab(guides_scroll, "Guides")

        # ── Tab 2: Image (scrollable) ─────────────────────────────────────
        image_inner = QWidget()
        image_lay = QVBoxLayout(image_inner)
        image_lay.setContentsMargins(8, 8, 8, 8)
        image_lay.setSpacing(12)

        img_box = QGroupBox("Reference Images")
        img_vlay = QVBoxLayout(img_box)
        img_vlay.setSpacing(6)

        # Add / Remove buttons
        img_btn_row = QHBoxLayout()
        add_img_btn = QPushButton("Add Image…")
        add_img_btn.setToolTip("Load a JPEG or PNG as a reference background layer.")
        add_img_btn.clicked.connect(self._add_face)
        self._remove_img_btn = QPushButton("Remove")
        self._remove_img_btn.setEnabled(False)
        self._remove_img_btn.setToolTip("Remove the selected reference image.")
        self._remove_img_btn.clicked.connect(self._remove_face)
        img_btn_row.addWidget(add_img_btn)
        img_btn_row.addWidget(self._remove_img_btn)
        img_vlay.addLayout(img_btn_row)

        # Image list
        self._face_list = QListWidget()
        self._face_list.setFixedHeight(72)
        self._face_list.setToolTip("Loaded reference images. Select one to adjust its settings.")
        self._face_list.currentRowChanged.connect(self._on_face_list_selection_changed)
        img_vlay.addWidget(self._face_list)

        # Per-image controls (disabled until an image is selected)
        img_ctrl_lay = QFormLayout()
        img_ctrl_lay.setSpacing(6)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(70)
        self._opacity_slider.setEnabled(False)
        self._opacity_slider.valueChanged.connect(self._on_face_opacity_changed)
        img_ctrl_lay.addRow("Opacity:", self._opacity_slider)

        self._rotation_spin = QDoubleSpinBox()
        self._rotation_spin.setRange(-180, 180)
        self._rotation_spin.setSuffix("°")
        self._rotation_spin.setSingleStep(0.5)
        self._rotation_spin.setEnabled(False)
        self._rotation_spin.valueChanged.connect(self._on_face_rotation_changed)
        img_ctrl_lay.addRow("Rotation:", self._rotation_spin)

        self._canvas_lock_chk = QCheckBox("Lock canvas position")
        self._canvas_lock_chk.setChecked(True)
        self._canvas_lock_chk.setEnabled(False)
        self._canvas_lock_chk.setToolTip(
            "When locked, the image cannot be accidentally dragged.\n"
            "Uncheck to freely reposition it by clicking and dragging.\n"
            "Re-check to lock it in place."
        )
        self._canvas_lock_chk.toggled.connect(self._on_canvas_lock_toggled)
        img_ctrl_lay.addRow(self._canvas_lock_chk)
        img_vlay.addLayout(img_ctrl_lay)

        image_lay.addWidget(img_box)

        calib_box = QGroupBox("Calibration")
        calib_lay = QFormLayout(calib_box)
        calib_lay.setSpacing(6)

        self._calib_label = QLabel("Not set")
        calib_lay.addRow("Status:", self._calib_label)

        calib_btn = QPushButton("Calibrate (2-point)…")
        calib_btn.setToolTip(
            "Click two landmarks on the face image, then enter their "
            "real-world distance (mm) to rescale the photo to match."
        )
        calib_btn.clicked.connect(self._start_calibration)
        calib_lay.addRow(calib_btn)

        self._pxmm_spin = QDoubleSpinBox()
        self._pxmm_spin.setRange(0.01, 9999.0)
        self._pxmm_spin.setDecimals(4)
        self._pxmm_spin.setSuffix(" img-px/mm")
        self._pxmm_spin.setValue(1.0)
        self._pxmm_spin.setToolTip("Image pixels per real-world mm — enter directly or use 2-point calibration above.")
        self._pxmm_spin.editingFinished.connect(self._apply_manual_calib)
        calib_lay.addRow("Scale:", self._pxmm_spin)

        image_lay.addWidget(calib_box)
        image_lay.addStretch()

        image_scroll = QScrollArea()
        image_scroll.setWidgetResizable(True)
        image_scroll.setFrameShape(image_scroll.Shape.NoFrame)
        image_scroll.setWidget(image_inner)
        tabs.addTab(image_scroll, "Canvas")

        # ── Tab 3: History ────────────────────────────────────────────────
        history_w = QWidget()
        history_lay = QVBoxLayout(history_w)
        history_lay.setContentsMargins(8, 8, 8, 8)
        history_lay.setSpacing(6)

        btn_add = QPushButton("Bookmark Current State…")
        btn_add.setToolTip(
            "Save a named snapshot of the current drawing as a revision point.\n"
            "Bookmarks are saved with the design.")
        btn_add.clicked.connect(self._add_bookmark)
        history_lay.addWidget(btn_add)

        self._timeline_list = QListWidget()
        self._timeline_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._timeline_list.setAlternatingRowColors(True)
        self._timeline_list.setToolTip("Double-click a bookmark to restore that state.")
        self._timeline_list.itemDoubleClicked.connect(lambda _: self._restore_bookmark())
        self._timeline_list.itemSelectionChanged.connect(self._on_timeline_selection)
        history_lay.addWidget(self._timeline_list)

        btn_row = QHBoxLayout()
        self._btn_bm_restore = QPushButton("Restore")
        self._btn_bm_rename  = QPushButton("Rename…")
        self._btn_bm_delete  = QPushButton("Delete")
        for btn in (self._btn_bm_restore, self._btn_bm_rename, self._btn_bm_delete):
            btn.setEnabled(False)
            btn_row.addWidget(btn)
        self._btn_bm_restore.setToolTip("Restore the selected bookmark (adds an undo step)")
        self._btn_bm_restore.clicked.connect(self._restore_bookmark)
        self._btn_bm_rename.clicked.connect(self._rename_bookmark)
        self._btn_bm_delete.clicked.connect(self._delete_bookmark)
        history_lay.addLayout(btn_row)

        tabs.addTab(history_w, "History")

        # ── Tab 4: Library (Pockets / Holes) ──────────────────────────────
        lib_tabs = QTabWidget()
        pockets_w = QWidget()
        lib_lay = QVBoxLayout(pockets_w)
        lib_lay.setContentsMargins(8, 8, 8, 8)
        lib_lay.setSpacing(6)

        self._lib_list = QListWidget()
        self._lib_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._lib_list.setAlternatingRowColors(True)
        self._lib_list.setToolTip(
            "Saved hinge pocket designs.\n"
            "Double-click or press Import to insert geometry into the current workspace."
        )
        self._lib_list.itemSelectionChanged.connect(self._on_lib_selection_changed)
        self._lib_list.itemDoubleClicked.connect(lambda _: self._import_from_library())
        lib_lay.addWidget(self._lib_list)

        self._btn_lib_import = QPushButton("Import into Workspace")
        self._btn_lib_import.setEnabled(False)
        self._btn_lib_import.setToolTip(
            "Insert the selected hinge design into the current workspace\n"
            "as HINGE-layer curves, centered at the canvas origin."
        )
        self._btn_lib_import.clicked.connect(self._import_from_library)
        lib_lay.addWidget(self._btn_lib_import)

        # Hinge Pocket workspace only
        self._lib_hinge_actions = QWidget()
        hinge_btn_lay = QVBoxLayout(self._lib_hinge_actions)
        hinge_btn_lay.setContentsMargins(0, 4, 0, 0)
        hinge_btn_lay.setSpacing(4)

        self._btn_lib_save = QPushButton("Save Current Pocket…")
        self._btn_lib_save.setToolTip(
            "Save this Hinge Pocket workspace's geometry to the library."
        )
        self._btn_lib_save.clicked.connect(self._save_to_library)
        hinge_btn_lay.addWidget(self._btn_lib_save)

        hinge_mgmt_row = QHBoxLayout()
        self._btn_lib_rename = QPushButton("Rename…")
        self._btn_lib_rename.setEnabled(False)
        self._btn_lib_rename.clicked.connect(self._rename_library_entry)
        self._btn_lib_delete = QPushButton("Delete")
        self._btn_lib_delete.setEnabled(False)
        self._btn_lib_delete.clicked.connect(self._delete_library_entry)
        hinge_mgmt_row.addWidget(self._btn_lib_rename)
        hinge_mgmt_row.addWidget(self._btn_lib_delete)
        hinge_btn_lay.addLayout(hinge_mgmt_row)

        lib_lay.addWidget(self._lib_hinge_actions)
        lib_lay.addStretch()
        lib_tabs.addTab(pockets_w, "Pockets")

        lib_tabs.addTab(self._build_holes_panel(), "Holes")
        tabs.addTab(SettingsDialog._scrolled(lib_tabs), "Library")

        self._side_tabs = tabs
        self._side_tabs.currentChanged.connect(
            lambda idx: self._refresh_measurements() if idx == 0 else None)
        # The dock is as wide as its five tabs, with room for a two-digit
        # bookmark count on History and for the bold of the selected tab.
        # At the old 270 px floor the bar scrolled "Library" off the edge.
        bar = tabs.tabBar()
        bar.setObjectName("sideTabs")
        bar.style().unpolish(bar)                  # measure with its own padding
        bar.style().polish(bar)
        bar.setTabText(3, "History (99)")
        fit = bar.sizeHint().width() + 10
        bar.setTabText(3, "History")
        self._prop_dock.setMinimumWidth(max(_DOCK_WIDTH, fit))
        self._wheel_guard = _WheelGuard(self)
        self._wheel_guard.guard(tabs)
        self._prop_dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._prop_dock)

    # ------------------------------------------------------------------
    # Layers panel
    # ------------------------------------------------------------------

    def _schedule_layer_panel_refresh(self, ws: "WorkspaceState"):
        """Coalesce document-change notifications into one panel rebuild."""
        if ws is not self._active_ws:
            return
        if not self._layer_refresh_pending:
            self._layer_refresh_pending = True
            QTimer.singleShot(0, self, self._do_layer_panel_refresh)

    def _do_layer_panel_refresh(self):
        self._layer_refresh_pending = False
        self._refresh_layer_panel()
        self._update_readiness()
        # Live measurements in the Properties tab track the geometry on every
        # document change (add/remove/undo/load) — no manual Refresh needed.
        self._refresh_measurements()
        # A snapped boxing guide also tracks the live lens geometry.
        if self._active_ws.boxing_snapped:
            self._active_ws.boxing_guide.refresh()
            self._sync_boxing_readouts()

    @staticmethod
    def _curve_label(c: Curve) -> str:
        if c.kind in ("circle", "arc") and c.radius is not None:
            label = f"{c.kind}  r={c.radius:.1f}"
        else:
            label = f"{c.kind}  ·  {len(c.nodes)} nodes"
            if c.closed:
                label += "  (closed)"
        if c.group_id:
            label = f"[grp {c.group_id[:4]}]  " + label
        return label

    @staticmethod
    def _text_label(t) -> str:
        """Layer-tree label for an engraving TextObject (re-editable, exported
        as outline paths at DXF time)."""
        s = t.text if len(t.text) <= 16 else t.text[:15] + "…"
        return f'text  ·  "{s}"'

    def _layer_icon(self, name: str) -> QIcon:
        """Theme-aware cached icon for the eye/padlock tree cells."""
        color = theme.color("chrome.ink")
        cache = getattr(self, "_layer_icon_cache", None)
        if cache is None:
            cache = self._layer_icon_cache = {}
        key = (name, color)
        if key not in cache:
            cache[key] = _make_icon(name, color, color)
        return cache[key]

    def _refresh_layer_panel(self):
        """Full rebuild of the layer tree (document change / tab switch)."""
        ws   = self._active_ws
        tree = self._layer_tree
        expanded = self._layer_tree_expanded.setdefault(ws.workspace_type, {})
        tree.blockSignals(True)
        tree.clear()
        self._layer_tree_rows: dict = {}        # id(curve) -> row item
        self._layer_tree_text_rows: dict = {}   # id(TextObject) -> row item
        self._layer_tree_layer_rows: dict = {}  # Layer -> top-level row
        for layer in WORKSPACE_LAYERS[ws.workspace_type]:
            curves = [c for c in ws.doc_curves if c.layer == layer]
            texts  = [t for t in ws.doc_texts if t.layer == layer]
            count  = len(curves) + len(texts)
            locked = ws.scene.is_layer_locked(layer)
            top = QTreeWidgetItem([f"{layer.value}  ({count})", "", ""])
            top.setIcon(1, self._layer_icon(
                "layer-show" if ws.scene.is_layer_visible(layer) else "layer-hide"))
            top.setIcon(2, self._layer_icon(
                "layer-lock" if locked else "layer-unlock"))
            top.setData(0, Qt.ItemDataRole.UserRole, ("layer", layer))
            # Layer rows are drop targets, never drag sources.
            top.setFlags(Qt.ItemFlag.ItemIsEnabled
                         | Qt.ItemFlag.ItemIsSelectable
                         | Qt.ItemFlag.ItemIsDropEnabled)
            tree.addTopLevelItem(top)
            self._layer_tree_layer_rows[layer] = top
            # Curve rows are drag sources (unless their layer is locked),
            # never drop targets.
            child_flags = (Qt.ItemFlag.ItemIsEnabled
                           | Qt.ItemFlag.ItemIsSelectable)
            if not locked:
                child_flags |= Qt.ItemFlag.ItemIsDragEnabled
            for c in curves:
                child = QTreeWidgetItem([self._curve_label(c), "", ""])
                child.setData(0, Qt.ItemDataRole.UserRole, ("curve", id(c)))
                child.setFlags(child_flags)
                top.addChild(child)
                self._layer_tree_rows[id(c)] = child
            # Engraving TextObjects live on their layer too.
            for t in texts:
                child = QTreeWidgetItem([self._text_label(t), "", ""])
                child.setData(0, Qt.ItemDataRole.UserRole, ("text", id(t)))
                child.setFlags(child_flags)
                top.addChild(child)
                self._layer_tree_text_rows[id(t)] = child
            # A layer the maker expanded or collapsed stays that way across
            # rebuilds (every document change rebuilds); otherwise auto.
            top.setExpanded(expanded.get(layer, bool(count) and count <= 12))
        tree.blockSignals(False)
        self._sync_layer_panel_active()
        # The rebuild dropped the row highlight; put the canvas selection back.
        self._sync_layer_panel_row()

    def _sync_layer_panel_row(self):
        """Highlight the row of a single selected curve/text (no rebuild)."""
        if self._syncing_selection:
            return
        sel = self.scene.selectedItems()
        rows = getattr(self, "_layer_tree_rows", {})
        trows = getattr(self, "_layer_tree_text_rows", {})
        row = None
        curves = [i for i in sel if isinstance(i, CurveItem)]
        texts  = [i for i in sel if isinstance(i, TextItem)]
        if len(curves) == 1 and not texts:
            row = rows.get(id(curves[0].curve))
        elif len(texts) == 1 and not curves:
            row = trows.get(id(texts[0].text_obj))
        if row is not None:
            self._syncing_selection = True
            try:
                self._layer_tree.setCurrentItem(row)
            finally:
                self._syncing_selection = False

    def _on_layer_row_expanded(self, item, expanded: bool):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "layer":
            per_ws = self._layer_tree_expanded.setdefault(
                self._active_ws.workspace_type, {})
            per_ws[data[1]] = expanded

    def _sync_layer_panel_active(self):
        """Bold the active layer row. No tree rebuild — safe inside handlers."""
        ws = self._active_ws
        for layer, top in getattr(self, "_layer_tree_layer_rows", {}).items():
            f = top.font(0)
            f.setBold(layer is ws.active_layer)
            top.setFont(0, f)

    def _set_active_layer(self, layer: Layer):
        """Make *layer* the drawing layer; live-update any active draw tool."""
        self._active_ws.active_layer = layer
        if self._draw_tool.active:
            self._draw_tool.set_layer(layer)
        if self._circle_tool.active:
            self._circle_tool.set_layer(layer)
        self._sync_layer_panel_active()
        self._update_info_label()
        self._status.showMessage(f"Active layer → {layer.value}")

    def _on_layer_tree_clicked(self, item, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind == "layer":
            layer = payload
            if column == 1:
                vis = not self.scene.is_layer_visible(layer)
                self.scene.set_layer_visible(layer, vis)
                item.setIcon(1, self._layer_icon(
                    "layer-show" if vis else "layer-hide"))
                self._mark_dirty()
            elif column == 2:
                locked = not self.scene.is_layer_locked(layer)
                self.scene.set_layer_locked(layer, locked)
                item.setIcon(2, self._layer_icon(
                    "layer-lock" if locked else "layer-unlock"))
                self._mark_dirty()
                # Child rows carry the drag flag per lock state — refresh it.
                self._refresh_layer_panel()
            else:
                self._set_active_layer(layer)
            return
        # Object rows: canvas selection is driven by the tree's own selection
        # (see _on_layer_tree_selection_changed), so a Ctrl/Shift multi-row
        # pick selects all those curves on canvas — across layers — which is
        # what Join / Mirror need.

    def _on_layer_tree_selection_changed(self):
        """Mirror the tree's selected object rows onto the canvas selection.

        Lets the maker multi-select curves in the panel (Ctrl/Shift) across
        different layers and then Join/Mirror them. The `_syncing_selection`
        guard stops this from fighting the canvas→tree row sync in
        `_on_selection_changed`. Scene signals are deliberately NOT blocked:
        each setSelected must reach EditTool (so node dots update) and the view
        (so the selection highlight repaints) — blocking them was why only a
        stale single curve appeared highlighted."""
        if self._syncing_selection:
            return
        ids, text_ids = [], []
        for it in self._layer_tree.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue
            if data[0] == "curve":
                ids.append(data[1])
            elif data[0] == "text":
                text_ids.append(data[1])
        if not ids and not text_ids:
            return   # a layer row (or nothing) selected — leave canvas as-is
        if self.view._draw_tool is not None or self._dim_tool.active:
            # A live draw tool strips the selectable flag from every item;
            # picking rows would silently select nothing.
            self._act_select.setChecked(True)
            self._set_tool_select()
        self._syncing_selection = True
        skipped = False
        try:
            picked = []
            for cid in ids:
                ci = self.scene._curve_items.get(cid)
                if ci is None:
                    continue
                lyr = ci.curve.layer
                if (self.scene.is_layer_visible(lyr)
                        and not self.scene.is_layer_locked(lyr)):
                    picked.append(ci)
                else:
                    skipped = True
            for tid in text_ids:
                ti = self.scene._text_items.get(tid)
                if ti is None:
                    continue
                lyr = ti.text_obj.layer
                if (self.scene.is_layer_visible(lyr)
                        and not self.scene.is_layer_locked(lyr)):
                    picked.append(ti)
                else:
                    skipped = True
            self.scene.select_items(picked)
        finally:
            self._syncing_selection = False
        if skipped:
            self._status.showMessage(
                "Some rows are on hidden/locked layers — not selected")

    def _on_layer_tree_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self._layer_tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        has_sel = any(isinstance(i, (CurveItem, TextItem))
                      for i in self.scene.selectedItems())
        menu = QMenu(self)
        if kind == "layer":
            layer = payload
            menu.addAction(f"Set {layer.value} as active layer",
                           lambda: self._set_active_layer(layer))
            menu.addAction(f"Select all on {layer.value}",
                           lambda: self._select_all_on_layer(layer))
            act = menu.addAction(f"Move selection to {layer.value}",
                                 lambda: self._move_selection_to_layer(layer))
            act.setEnabled(has_sel)
        else:
            # The right-click already selected the row (and so the object).
            menu.addAction("Delete", self._delete_selected)
        menu.exec(self._layer_tree.viewport().mapToGlobal(pos))

    def _select_all_on_layer(self, layer: Layer):
        if not self.scene.is_layer_visible(layer) or self.scene.is_layer_locked(layer):
            self._status.showMessage(
                f"{layer.value} is hidden or locked — nothing selected")
            return
        picked = [it for it in self.scene._curve_items.values()
                  if it.curve.layer == layer]
        picked += [it for it in self.scene._text_items.values()
                   if it.text_obj.layer == layer]
        self.scene.select_items(picked)
        self._status.showMessage(f"Selected {len(picked)} object(s) on {layer.value}")

    def _move_selection_to_layer(self, layer: Layer):
        """Reassign the selected curves/texts to *layer*."""
        targets = [i for i in self.scene.selectedItems()
                   if isinstance(i, (CurveItem, TextItem))]
        if not targets:
            self._status.showMessage("Move to layer: nothing selected")
            return
        self._move_curve_items_to_layer(targets, layer)

    def _on_layer_tree_drop(self, obj_ids: list, layer: Layer):
        """A drag-and-drop in the layer panel landed on *layer*."""
        items = [self.scene._curve_items.get(i) or self.scene._text_items.get(i)
                 for i in obj_ids]
        self._move_curve_items_to_layer([it for it in items if it is not None],
                                        layer)

    @staticmethod
    def _item_layer(it):
        return it.text_obj.layer if isinstance(it, TextItem) else it.curve.layer

    def _move_curve_items_to_layer(self, items: list, layer: Layer):
        """Shared by the context menu and layer-panel drag-and-drop; takes
        CurveItems and TextItems. Locked layers keep their objects."""
        locked = [it for it in items if self.scene.is_layer_locked(self._item_layer(it))]
        items = [it for it in items
                 if self._item_layer(it) is not layer and it not in locked]
        if not items:
            self._status.showMessage(
                f"Move to layer: {'layer is locked' if locked else 'already on ' + layer.value}")
            return
        self._push_undo_snapshot()
        for it in items:
            if isinstance(it, TextItem):
                it.text_obj.layer = layer
                it.refresh()
                self.scene._apply_layer_state_to_text(it)
            else:
                it.curve.layer = layer
                self.scene._apply_layer_state_to_item(it)
                # Through refresh_curve, not the item alone: the ghost, both
                # fills, a snapped boxing guide and the Measurements read the
                # layer too. Repainting the item left a lens moved to REF
                # still measured as a lens and still punched out of the fill.
                self.scene.refresh_curve(it.curve)
        self._refresh_layer_panel()
        self._update_readiness()
        self._refresh_measurements()
        msg = f"Moved {len(items)} object{'s' if len(items) != 1 else ''} → {layer.value}"
        if locked:
            msg += f"  ({len(locked)} on a locked layer left alone)"
        self._status.showMessage(msg)

    # ------------------------------------------------------------------
    # Status bar info label (layer + zoom)
    # ------------------------------------------------------------------

    def _update_info_label(self):
        # Readiness is NOT recomputed here: it depends only on the document
        # and the mirror (both have their own hooks), and this runs on every
        # selection change and wheel tick — the validator in that path made
        # select-all on a few hundred curves take seconds.
        layer = self._active_ws.active_layer.value
        zoom  = round(self.view.transform().m11() * 100)
        self._info_label.setText(f"{layer}  |  {zoom}%")

    def _update_readiness(self):
        """Recompute the 'Ready for GuildModel' dot for the active workspace."""
        dot = getattr(self, "_readiness_dot", None)
        if dot is None:
            return
        ws = self._active_ws
        mirror_on = bool(ws.scene.mirror and ws.scene.mirror.enabled)
        state, tip = readiness_state(ws.doc_curves, mirror_on, ws.workspace_type)
        dot.set_dark_mode(self._dark_mode)
        dot.set_readiness(state, tip)

    # ------------------------------------------------------------------
    # Workspace tab switching (Phase 14)
    # ------------------------------------------------------------------

    # True only while a file load is repopulating the workspaces; see the
    # save-on-leave guard in _on_workspace_changed.
    _loading = False

    def _on_workspace_changed(self, idx: int):
        """Called by _ws_tab_widget.currentChanged. Saves departing sidebar
        state into the old WorkspaceState; restores arriving workspace state."""
        ws = self._workspaces[idx]

        # Save sidebar state into the workspace we're leaving; explicitly
        # cancel any in-progress drawing there (it cannot be carried across,
        # and silently discarding it confused makers).
        discarded = False
        if self._last_ws_idx != idx:
            old_ws = self._workspaces[self._last_ws_idx]
            if old_ws.draw_tool.active or old_ws.circle_tool.active:
                discarded = bool(getattr(old_ws.draw_tool, "_nodes", None)
                                 or old_ws.circle_tool.active)
                old_ws.draw_tool.deactivate()
                old_ws.circle_tool.deactivate()
                old_ws.view.set_draw_tool(None)
            # Not during a load. Opening a file whose saved active tab is not
            # the one on screen switches tabs while the widgets still show the
            # OUTGOING document, so saving them here wrote the old document's
            # guide/fill/forming values straight over the freshly loaded ones.
            if not self._loading:
                self._save_ws_sidebar_state(old_ws)
        self._last_ws_idx = idx

        # Return to Select mode
        self._act_select.setChecked(True)
        self._set_tool_select()

        # Restore arriving workspace state into sidebar
        self._restore_ws_sidebar_state(ws)
        self._show_guide_sections(ws.workspace_type)
        self._refresh_timeline_list()
        self._refresh_measurements()
        if ws.boxing_snapped:
            self._sync_boxing_readouts()
        # (No library refresh: the list is global, and every save, rename and
        # delete refreshes it. Re-reading the disk per tab switch cleared the
        # maker's selection in it.)
        self._refresh_layer_panel()
        self._refresh_mirror_icons()
        self._update_info_label()
        self._update_readiness()
        self._update_undo_actions()    # the menu shows THIS tab's history
        # Selection-driven buttons follow THIS tab's selection: a curve picked
        # on the Front left Explode lit on an empty Temple R.
        self._update_split_enabled()
        self._update_explode_enabled()
        self._act_snap_ep.setEnabled(self._edit_tool.has_selected_node())

        # Fit the view the first time this workspace is shown — to the
        # geometry as well as the scene rect, so a loaded temple longer than
        # the default extents isn't half off-screen.
        if not ws.fitted:
            rect = self.scene.sceneRect().united(self.scene.geometry_rect())
            self.view.fit_view(rect)
            ws.fitted = True
            self._update_info_label()
        if discarded:
            # After the Select-mode message, or it would be overwritten.
            self._status.showMessage(
                "Workspace switched — the in-progress drawing was discarded",
                5000)

    def _save_ws_sidebar_state(self, ws: "WorkspaceState"):
        """Write current sidebar widget values into *ws* for later restore."""
        ws.mirror_enabled = self._act_mirror.isChecked()
        ws.snap_enabled   = self._act_snap.isChecked()
        ws.smooth_handles = self._act_smooth.isChecked()
        ws.guides_visible = self._act_guides.isChecked()
        ws.boxing_visible = self._act_boxing.isChecked()
        ws.stock_visible  = self._act_stock.isChecked()
        ws.pad_visible    = self._act_pad.isChecked()
        ws.bridge_angle   = self._bridge_angle_spin.value()
        ws.apical_radius  = self._apical_spin.value()
        ws.crest_height   = self._guide_crest_height_spin.value()
        ws.arm_spread     = self._guide_spread_spin.value()
        ws.arm_drop       = self._guide_drop_spin.value()
        ws.boxing_snapped = self._boxing_snap_chk.isChecked()
        ws.shape_locked   = self._lock_shape_chk.isChecked()
        ws.boxing_chain   = self._chain_btn.isChecked()
        ws.outline_locked = self._outline_lock_chk.isChecked()
        # When snapped the A/B/DBL fields hold read-outs, not the free-box values
        # — preserve the stored free-box targets so they return on un-snap.
        if not ws.boxing_snapped:
            ws.boxing_a   = self._boxing_a_spin.value()
            ws.boxing_b   = self._boxing_b_spin.value()
            ws.boxing_dbl = self._boxing_dbl_spin.value()
        ws.bevel_preset   = self._bevel_choices[self._bevel_combo.currentIndex()][1]
        ws.bevel_depth    = self._current_bevel_depth()
        ws.stock_w        = self._stock_w_spin.value()
        ws.stock_h        = self._stock_h_spin.value()
        ws.pad_w          = self._pad_w_spin.value()
        ws.pad_h          = self._pad_h_spin.value()
        ws.fill_visible   = self._fill_show_chk.isChecked()
        ws.fill_opacity   = self._fill_opacity_slider.value() / 100.0
        # (fill_color is written by _on_fill_color_clicked directly, and
        #  fill_style / fill_image by the style combo and image picker)
        ws.lens_fill_visible = self._lens_fill_show_chk.isChecked()
        ws.lens_fill_linked  = self._lens_link_btn.isChecked()
        ws.lens_fill_opacity = self._lens_fill_opacity_slider.value() / 100.0
        # NOT re-derived from the intensity slider: that mapping is geometric,
        # so position is a lossy encoding of the value (3.0 comes back 3.03) and
        # every tab switch would nudge a loaded document off its saved depth.
        # _on_lens_fill_intensity_changed is the sole writer.
        # (the two stop colors are written by _set_lens_fill_color directly)
        # Face image list paths
        ws.face_image_paths = [
            self._face_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._face_list.count())
        ]
        ws.selected_face_idx = self._face_list.currentRow()

    def _restore_ws_sidebar_state(self, ws: "WorkspaceState"):
        """Read values from *ws* into sidebar widgets (block signals to avoid
        cascading; apply to the workspace's guide objects directly)."""
        # ── Toggle actions ──────────────────────────────────────────────
        for act, val in [
            (self._act_mirror,  ws.mirror_enabled),
            (self._act_snap,    ws.snap_enabled),
            (self._act_smooth,  ws.smooth_handles),
            (self._act_guides,  ws.guides_visible),
            (self._act_boxing,  ws.boxing_visible),
            (self._act_stock,   ws.stock_visible),
            (self._act_pad,     ws.pad_visible),
        ]:
            act.blockSignals(True)
            act.setChecked(val)
            act.blockSignals(False)

        # Apply guide object states directly
        ws.const_guides.set_visible(ws.guides_visible)
        ws.boxing_guide.set_visible(ws.boxing_visible)
        ws.stock_guide.set_visible(ws.stock_visible)
        ws.pad_guide.set_visible(ws.pad_visible)
        ws.snap.set_enabled(ws.snap_enabled)
        ws.edit_tool.set_smooth_mode(ws.smooth_handles)
        if ws.scene.mirror:
            ws.scene.mirror.set_enabled(ws.mirror_enabled)
        ws.scene.set_mirror_display(ws.mirror_enabled)
        ws.snap.set_mirror(0.0, ws.mirror_enabled, horizontal=(ws.workspace_type in ("temple_r", "temple_l")))
        ws.boxing_guide.set_mirror(ws.mirror_enabled)

        # ── Spinboxes ───────────────────────────────────────────────────
        for spin, val in [
            (self._bridge_angle_spin,        ws.bridge_angle),
            (self._apical_spin,              ws.apical_radius),
            (self._guide_crest_height_spin,  ws.crest_height),
            (self._guide_spread_spin,        ws.arm_spread),
            (self._guide_drop_spin,          ws.arm_drop),
            (self._boxing_a_spin,     ws.boxing_a),
            (self._boxing_b_spin,     ws.boxing_b),
            (self._boxing_dbl_spin,   ws.boxing_dbl),
            (self._stock_w_spin,      ws.stock_w),
            (self._stock_h_spin,      ws.stock_h),
            (self._pad_w_spin,        ws.pad_w),
            (self._pad_h_spin,        ws.pad_h),
        ]:
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

        # Apply spinbox values to the workspace's guide objects directly
        ws.const_guides.set_bridge_angle(ws.bridge_angle)
        ws.const_guides.set_apical_radius(ws.apical_radius)
        ws.const_guides.set_crest_height(ws.crest_height)
        ws.const_guides.set_spread(ws.arm_spread)
        ws.const_guides.set_pivot_y(ws.arm_drop)
        ws.boxing_guide.set_a(ws.boxing_a)
        ws.boxing_guide.set_b(ws.boxing_b)
        ws.boxing_guide.set_dbl(ws.boxing_dbl)

        # ── Bevel + snap/lock-to-lens (M11/M12) ─────────────────────────
        self._bevel_depth_spin.blockSignals(True)
        self._bevel_depth_spin.setValue(ws.bevel_depth)
        self._bevel_depth_spin.setEnabled(ws.bevel_preset == "custom")
        self._bevel_depth_spin.blockSignals(False)
        idx = next((i for i, (_lbl, k) in enumerate(self._bevel_choices)
                    if k == ws.bevel_preset), 2)
        self._bevel_combo.blockSignals(True)
        self._bevel_combo.setCurrentIndex(idx)
        self._bevel_combo.blockSignals(False)
        self._boxing_snap_chk.blockSignals(True)
        self._boxing_snap_chk.setChecked(ws.boxing_snapped)
        self._boxing_snap_chk.blockSignals(False)
        self._lock_shape_chk.blockSignals(True)
        self._lock_shape_chk.setChecked(ws.shape_locked)
        self._lock_shape_chk.blockSignals(False)
        self._chain_btn.blockSignals(True)
        self._chain_btn.setChecked(ws.boxing_chain)
        self._chain_btn.blockSignals(False)
        self._outline_lock_chk.blockSignals(True)
        self._outline_lock_chk.setChecked(ws.outline_locked)
        self._outline_lock_chk.blockSignals(False)
        ws.boxing_guide.set_bevel_depth(ws.bevel_depth)
        ws.boxing_guide.set_locked(ws.boxing_snapped)
        self._apply_boxing_field_modes(ws)
        ws.stock_guide.set_width(ws.stock_w)
        ws.stock_guide.set_height(ws.stock_h)
        ws.pad_guide.set_width(ws.pad_w)
        ws.pad_guide.set_height(ws.pad_h)

        # ── Frame fill ──────────────────────────────────────────────────
        self._fill_opacity_slider.blockSignals(True)
        self._fill_opacity_slider.setValue(round(ws.fill_opacity * 100))
        self._fill_opacity_slider.blockSignals(False)
        self._update_fill_swatch(ws.fill_color)
        ws.scene.set_fill_color(QColor(ws.fill_color))
        ws.scene.set_fill_opacity(ws.fill_opacity)
        self._apply_fill_material(ws)
        self._sync_fill_style_widgets(ws)
        status = ws.scene.set_fill_visible(ws.fill_visible)
        if ws.fill_visible and status != "ok":
            ws.fill_visible = False   # saved fill-on no longer encloses a region
        self._fill_show_chk.blockSignals(True)
        self._fill_show_chk.setChecked(ws.fill_visible)
        self._fill_show_chk.blockSignals(False)

        # ── Lens fill ───────────────────────────────────────────────────
        self._lens_fill_opacity_slider.blockSignals(True)
        self._lens_fill_opacity_slider.setValue(round(ws.lens_fill_opacity * 100))
        self._lens_fill_opacity_slider.blockSignals(False)
        self._lens_link_btn.blockSignals(True)
        self._lens_link_btn.setChecked(ws.lens_fill_linked)
        self._lens_link_btn.blockSignals(False)
        self._lens_fill_intensity_slider.blockSignals(True)
        self._lens_fill_intensity_slider.setValue(
            slider_from_intensity(ws.lens_fill_intensity))
        self._lens_fill_intensity_slider.blockSignals(False)
        self._update_lens_fill_swatches(ws.lens_fill_top, ws.lens_fill_bottom,
                                        ws.lens_fill_intensity)
        ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
        ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
        lens_status = ws.scene.set_lens_fill_visible(ws.lens_fill_visible)
        if ws.lens_fill_visible and lens_status != "ok":
            ws.lens_fill_visible = False   # saved fill-on no longer encloses
        self._lens_fill_show_chk.blockSignals(True)
        self._lens_fill_show_chk.setChecked(ws.lens_fill_visible)
        self._lens_fill_show_chk.blockSignals(False)

        # (Layer list/active layer are per-workspace; _refresh_layer_panel is
        # called by _on_workspace_changed right after this restore.)

        # ── Calibration display ─────────────────────────────────────────
        self._pxmm_spin.blockSignals(True)
        if ws.image_px_per_mm:
            self._calib_label.setText(f"{ws.image_px_per_mm:.4f} img-px/mm")
            self._pxmm_spin.setValue(ws.image_px_per_mm)
        else:
            self._calib_label.setText("Not set")
            self._pxmm_spin.setValue(1.0)   # not the previous tab's value
        self._pxmm_spin.blockSignals(False)

        # ── Face image list ─────────────────────────────────────────────
        self._face_list.blockSignals(True)
        self._face_list.clear()
        for path in ws.face_image_paths:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._face_list.addItem(item)
        self._face_list.blockSignals(False)
        if ws.selected_face_idx >= 0:
            self._face_list.setCurrentRow(ws.selected_face_idx)
        has_sel = ws.selected_face_idx >= 0
        self._remove_img_btn.setEnabled(has_sel)
        self._opacity_slider.setEnabled(has_sel)
        self._rotation_spin.setEnabled(has_sel)
        self._canvas_lock_chk.setEnabled(has_sel)

    def _on_stock_width_changed(self, mm: float):
        """The blank guide's width is also the width a Frame Fill swatch spans,
        so a maker who corrects their sheet size sees the material rescale with
        it — showing/hiding the guide itself has no bearing on the fill."""
        ws = self._active_ws
        ws.stock_w = mm
        ws.stock_guide.set_width(mm)
        ws.scene.set_fill_blank_width(mm)

    # ── Frame fill controls ─────────────────────────────────────────────

    def _update_fill_swatch(self, color_hex: str):
        pm = QPixmap(16, 16)
        pm.fill(QColor(color_hex))
        self._fill_color_btn.setIcon(QIcon(pm))

    def _on_fill_visible_toggled(self, on: bool):
        ws = self._active_ws
        if on:
            status = ws.scene.set_fill_visible(True)
            if status != "ok":
                # Nothing enclosable to fill — revert the tick and explain.
                self._fill_show_chk.blockSignals(True)
                self._fill_show_chk.setChecked(False)
                self._fill_show_chk.blockSignals(False)
                ws.fill_visible = False
                if status == "leak":
                    QMessageBox.information(
                        self, "Frame Fill",
                        "The frame outline perimeter has a leak somewhere — its "
                        "ends don't close into an enclosed region, so there's "
                        "nothing to fill.\n\nClose the OUTLINE, or in Ghost mode "
                        "snap the open half's endpoints onto the mirror line, "
                        "then turn Frame Fill on again.")
                else:  # "empty"
                    QMessageBox.information(
                        self, "Frame Fill",
                        "There's no frame outline to fill yet. Draw the OUTLINE "
                        "first, then turn Frame Fill on.")
                return
            ws.fill_visible = True
        else:
            ws.fill_visible = False
            ws.scene.set_fill_visible(False)
        self._mark_dirty()   # the fill is saved with the design

    def _on_fill_auto_disabled(self, status: str, ws):
        """A geometry edit broke the OUTLINE perimeter while the fill was on;
        the scene turned it off. Sync the checkbox and note it in the status
        bar (quietly — no modal mid-edit)."""
        ws.fill_visible = False
        if ws is self._active_ws:
            self._fill_show_chk.blockSignals(True)
            self._fill_show_chk.setChecked(False)
            self._fill_show_chk.blockSignals(False)
        if status == "leak":
            self._status.showMessage(
                "Frame Fill turned off — the outline perimeter was broken.",
                5000)

    def _on_fill_color_clicked(self):
        ws = self._active_ws
        c = QColorDialog.getColor(QColor(ws.fill_color), self, "Frame fill color")
        if not c.isValid():
            return
        ws.fill_color = c.name()
        ws.scene.set_fill_color(c)
        self._update_fill_swatch(ws.fill_color)
        self._mark_dirty()

    def _on_fill_opacity_changed(self, value: int):
        ws = self._active_ws
        ws.fill_opacity = value / 100.0
        ws.scene.set_fill_opacity(ws.fill_opacity)
        self._mark_dirty()

    # ── Frame fill from a material swatch (v1.2) ────────────────────────

    def _apply_fill_material(self, ws: "WorkspaceState") -> bool:
        """Push ws.fill_style / ws.fill_image onto its scene, and keep the
        swatch scaled to that workspace's own blank width. Returns False when
        an image style was asked for but the file couldn't be read — the caller
        decides whether that deserves a modal or a silent fall back to color;
        ws.fill_style is left on "color" either way."""
        ws.scene.set_fill_blank_width(ws.stock_w)
        if ws.fill_style == "image" and ws.fill_image:
            if ws.scene.set_fill_image(ws.fill_image):
                return True
            ws.fill_style = "color"      # unreadable — show the color instead
            ws.scene.clear_fill_image()
            return False
        # An Image style with nothing behind it is not a state worth keeping —
        # it would show the color under a combo that claims otherwise.
        ws.fill_style = "color"
        ws.scene.clear_fill_image()
        return True

    def _sync_fill_style_widgets(self, ws: "WorkspaceState"):
        """Combo, image button label and per-style enablement, from *ws*."""
        idx = self._fill_style_combo.findData(ws.fill_style)
        self._fill_style_combo.blockSignals(True)
        self._fill_style_combo.setCurrentIndex(max(0, idx))
        self._fill_style_combo.blockSignals(False)
        is_image = (ws.fill_style == "image")
        self._fill_color_btn.setEnabled(not is_image)
        self._fill_image_btn.setEnabled(is_image)
        self._fill_image_clear_btn.setEnabled(is_image and bool(ws.fill_image))
        if ws.fill_image:
            self._set_fill_image_btn_text(os.path.basename(ws.fill_image))
            self._fill_image_btn.setToolTip(ws.fill_image)
        else:
            self._set_fill_image_btn_text("Choose…")
            self._fill_image_btn.setToolTip(
                "Pick a material swatch — a supplier's acetate sample sheet.")

    def _set_fill_image_btn_text(self, text: str):
        """Label the swatch button, middle-eliding a name too long for the
        row so the extension stays readable (full path in the tooltip)."""
        self._fill_image_full_text = text
        self._elide_fill_image_btn()

    def _elide_fill_image_btn(self):
        btn   = self._fill_image_btn
        avail = btn.width() - 12          # the frame the label sits inside
        text  = self._fill_image_full_text
        if avail > 0:
            text = QFontMetrics(btn.font()).elidedText(
                text, Qt.TextElideMode.ElideMiddle, avail)
        # Reached from the app-wide filter on every resize of this button, so
        # don't hand Qt a fresh layout request for a label that hasn't changed.
        if btn.text() != text:
            btn.setText(text)

    def _on_fill_style_changed(self, _index: int):
        ws = self._active_ws
        ws.fill_style = self._fill_style_combo.currentData() or "color"
        # Switching to Image with nothing chosen yet: open the picker rather
        # than leaving the maker on a style that shows the color anyway.
        if ws.fill_style == "image" and not ws.fill_image:
            self._sync_fill_style_widgets(ws)
            self._on_fill_image_clicked()
            return
        if not self._apply_fill_material(ws):
            self._fill_image_missing(ws)
        self._sync_fill_style_widgets(ws)
        self._mark_dirty()

    def _on_fill_image_clicked(self):
        ws = self._active_ws
        start = os.path.dirname(ws.fill_image) if ws.fill_image else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Frame fill material swatch", start,
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)")
        def back_to_color_if_empty():
            # Leaving the auto-opened picker without a swatch — canceled, or
            # a file that won't decode — puts the style back, so the combo
            # doesn't sit on Image (and save "image") with nothing behind it.
            if not ws.fill_image:
                ws.fill_style = "color"
                self._apply_fill_material(ws)
                self._sync_fill_style_widgets(ws)
        if not path:
            back_to_color_if_empty()
            return
        ws.scene.set_fill_blank_width(ws.stock_w)
        if not ws.scene.set_fill_image(path, reload=True):   # picked again: re-read it
            QMessageBox.warning(
                self, "Frame Fill",
                f"{os.path.basename(path)} couldn't be read as an image.")
            back_to_color_if_empty()
            return
        ws.fill_image = path
        ws.fill_style = "image"
        self._sync_fill_style_widgets(ws)
        self._mark_dirty()
        self._status.showMessage(
            f"Frame Fill material: {os.path.basename(path)}"
            f"  ·  scaled to the {ws.stock_w:g} mm blank", 5000)

    def _on_fill_image_cleared(self):
        ws = self._active_ws
        ws.fill_image = ""
        ws.fill_style = "color"
        self._apply_fill_material(ws)
        self._sync_fill_style_widgets(ws)
        self._mark_dirty()

    def _fill_image_missing(self, ws: "WorkspaceState"):
        """The saved swatch is gone (a .svg pointing at a file that didn't
        travel with it). Say so once and leave the color showing."""
        self._status.showMessage(
            f"Frame Fill: {os.path.basename(ws.fill_image) or 'the material swatch'}"
            " couldn't be read — showing the color instead.", 6000)

    # ── Lens fill controls ──────────────────────────────────────────────

    def _default_lens_fill_opacity(self) -> float:
        """Preferred starting opacity for a lens tint, 0…1."""
        pct = self._prefs.get("lens_fill_opacity_pct",
                              round(DEFAULT_LENS_FILL_OPACITY * 100))
        try:
            return max(0.0, min(1.0, float(pct) / 100.0))
        except (TypeError, ValueError):
            return DEFAULT_LENS_FILL_OPACITY

    def _default_lens_fill_intensity(self) -> float:
        """Preferred starting tint intensity (see deepen_tint)."""
        raw = self._prefs.get("lens_fill_intensity", DEFAULT_LENS_FILL_INTENSITY)
        try:
            return max(LENS_FILL_INTENSITY_MIN,
                       min(LENS_FILL_INTENSITY_MAX, float(raw)))
        except (TypeError, ValueError):
            return DEFAULT_LENS_FILL_INTENSITY

    def _update_lens_fill_swatches(self, top_hex: str, bottom_hex: str,
                                   intensity: float):
        """Repaint the two color bars.

        They show the color *as painted* — deepened by the current intensity —
        because that is what the maker is judging; the picker still opens on
        the base color, and the tooltip names both so the two never get
        confused."""
        w, h = _LENS_SWATCH_PX
        for btn, hex_, label in ((self._lens_top_btn, top_hex, "Top"),
                                 (self._lens_bottom_btn, bottom_hex, "Bottom")):
            shown = deepen_tint(hex_, intensity)
            pm = QPixmap(w, h)
            pm.fill(shown)
            p = QPainter(pm)
            p.setPen(QPen(QColor(0, 0, 0, 70)))
            p.drawRect(0, 0, w - 1, h - 1)
            p.end()
            btn.setIcon(QIcon(pm))
            tip = f"{label} gradient stop for every lens.\nColor: {hex_}"
            if shown.name() != QColor(hex_).name():
                tip += f"  ·  shown at intensity: {shown.name()}"
            btn.setToolTip(tip + "\nClick to pick a color.")

    def _on_lens_fill_visible_toggled(self, on: bool):
        ws = self._active_ws
        if on:
            status = ws.scene.set_lens_fill_visible(True)
            if status != "ok":
                # Nothing enclosable to tint — revert the tick and explain.
                self._lens_fill_show_chk.blockSignals(True)
                self._lens_fill_show_chk.setChecked(False)
                self._lens_fill_show_chk.blockSignals(False)
                ws.lens_fill_visible = False
                if status == "leak":
                    QMessageBox.information(
                        self, "Lens Fill",
                        "No lens aperture closes into an enclosed region, so "
                        "there's nothing to tint.\n\nClose the LENS shape — "
                        "select it and press Join to fuse its ends — or in "
                        "Ghost mode snap the open half's endpoints onto the "
                        "mirror line, then turn Lens Fill on again.")
                else:  # "empty"
                    QMessageBox.information(
                        self, "Lens Fill",
                        "There are no lenses to tint yet. Draw a LENS shape "
                        "first, then turn Lens Fill on.")
                return
            ws.lens_fill_visible = True
        else:
            ws.lens_fill_visible = False
            ws.scene.set_lens_fill_visible(False)
        self._mark_dirty()   # the tint is saved with the design

    def _on_lens_fill_auto_disabled(self, status: str, ws):
        """A geometry edit opened every lens aperture while the fill was on;
        the scene turned it off. Sync the checkbox and note it quietly."""
        ws.lens_fill_visible = False
        if ws is self._active_ws:
            self._lens_fill_show_chk.blockSignals(True)
            self._lens_fill_show_chk.setChecked(False)
            self._lens_fill_show_chk.blockSignals(False)
        if status == "leak":
            self._status.showMessage(
                "Lens Fill turned off — no lens aperture closes any more.",
                5000)

    def _set_lens_fill_color(self, which: str, color_hex: str):
        """Write one gradient stop (and its twin while the link is on)."""
        ws = self._active_ws
        if which == "top" or ws.lens_fill_linked:
            ws.lens_fill_top = color_hex
        if which == "bottom" or ws.lens_fill_linked:
            ws.lens_fill_bottom = color_hex
        ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
        self._update_lens_fill_swatches(ws.lens_fill_top, ws.lens_fill_bottom,
                                        ws.lens_fill_intensity)
        self._mark_dirty()

    def _on_lens_fill_color_clicked(self, which: str):
        ws = self._active_ws
        current = ws.lens_fill_top if which == "top" else ws.lens_fill_bottom
        label = "Lens tint — top" if which == "top" else "Lens tint — bottom"
        c = QColorDialog.getColor(QColor(current), self, label)
        if not c.isValid():
            return
        self._set_lens_fill_color(which, c.name())

    def _show_tint_picker(self, which: str):
        """Open the BPI tint reference; the chosen hex lands in *which* stop."""
        picker = _bpi_tints.TintPicker(
            self,
            title=("BPI tint reference — top stop" if which == "top"
                   else "BPI tint reference — bottom stop"))
        picker.tint_picked.connect(
            lambda hex_, w=which: self._set_lens_fill_color(w, hex_))
        picker.show_under(self._lens_top_bpi_btn if which == "top"
                          else self._lens_bottom_bpi_btn)

    def _on_lens_fill_link_toggled(self, on: bool):
        ws = self._active_ws
        ws.lens_fill_linked = on
        if on:
            # Collapse to a flat tint on the top stop — the primary of the pair.
            self._set_lens_fill_color("top", ws.lens_fill_top)
        self._mark_dirty()

    def _on_lens_fill_intensity_changed(self, value: int):
        ws = self._active_ws
        ws.lens_fill_intensity = intensity_from_slider(value)
        ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        self._update_lens_fill_swatches(ws.lens_fill_top, ws.lens_fill_bottom,
                                        ws.lens_fill_intensity)
        self._mark_dirty()

    def _on_lens_fill_opacity_changed(self, value: int):
        ws = self._active_ws
        ws.lens_fill_opacity = value / 100.0
        ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
        self._mark_dirty()

    def _show_guide_sections(self, ws_type: str):
        """Show/hide Guides-tab group boxes based on workspace type."""
        is_front  = (ws_type == "front")
        is_temple = (ws_type in ("temple_r", "temple_l"))
        is_hinge  = (ws_type == "hinge")
        self._construction_guide_box.setVisible(is_front)
        self._boxing_guide_box.setVisible(is_front)
        self._stock_guide_box.setVisible(True)   # all workspaces have a stock rect
        self._pad_guide_box.setVisible(is_front) # pad block only meaningful for front
        self._fill_box.setVisible(is_front or is_temple)  # fill needs an OUTLINE
        self._lens_fill_box.setVisible(is_front)          # only the front has lenses
        # Toolbar buttons: combined prefs + workspace rules in one place
        self._apply_toolbar_visibility(self._toolbar_prefs, ws_type)
        self._meas_front_box.setVisible(is_front)
        self._meas_temple_box.setVisible(is_temple)
        if is_temple:
            label = "Temple R" if ws_type == "temple_r" else "Temple L"
            self._meas_temple_box.setTitle(f"Measurements — {label}")
        # Library tab: save/rename/delete only in Hinge Pocket workspace
        self._lib_hinge_actions.setVisible(is_hinge)

    def _refresh_measurements(self):
        """Recompute and display workspace measurements in the Properties tab.
        Also stashes the representative finished A/B/DBL for the snapped boxing
        read-outs (_snap_a/_snap_b/_snap_dbl)."""
        ws = self._active_ws
        _FRONT_LAYERS  = {Layer.OUTLINE, Layer.LENS}
        _TEMPLE_LAYERS = {Layer.OUTLINE}
        self._snap_a = self._snap_b = self._snap_dbl = None

        if ws.workspace_type == "front":
            # Front view: positive x = OS (patient's left), negative x = OD (patient's right).
            mirror_x = getattr(ws.scene.mirror, '_x', 0.0) if ws.scene.mirror else 0.0
            curves = ws.doc_curves

            def _split(layer):
                """Return (os_curves, od_curves) for *layer* partitioned by centroid x."""
                os_c, od_c = [], []
                for c in curves:
                    if c.layer != layer or not c.nodes:
                        continue
                    cx = sum(n.x for n in c.nodes) / len(c.nodes)
                    if cx > mirror_x:
                        os_c.append(c)
                    elif cx < mirror_x:
                        od_c.append(c)
                return os_c, od_c

            def _set_lens(a_lbl, b_lbl, ed_lbl, a, b):
                if a is None:
                    for lbl in (a_lbl, b_lbl, ed_lbl):
                        lbl.setText("—")
                else:
                    a_lbl.setText(f"{a:.1f} mm")
                    b_lbl.setText(f"{b:.1f} mm")
                    ed_lbl.setText(f"{math.sqrt(a*a + b*b):.1f} mm")

            # ── Frame width: OUTLINE layer ─────────────────────────────
            os_out, od_out = _split(Layer.OUTLINE)
            os_ob = _curves_bbox(os_out) if os_out else None
            od_ob = _curves_bbox(od_out) if od_out else None

            if os_ob and od_ob:
                all_ob = _curves_bbox(os_out + od_out)
                fw = all_ob[2] - all_ob[0]
            elif os_ob:
                # One side drawn: full width = 2 × distance from the mirror
                # axis to the outermost edge (not 2 × the half's own width).
                fw = 2.0 * (os_ob[2] - mirror_x)
            elif od_ob:
                fw = 2.0 * (mirror_x - od_ob[0])
            else:
                # Joined closed outline centered on mirror axis (centroid == mirror_x)
                # is dropped by _split; measure directly from all OUTLINE curves.
                all_out_raw = [c for c in curves if c.layer == Layer.OUTLINE and c.nodes]
                all_ob = _curves_bbox(all_out_raw) if all_out_raw else None
                fw = (all_ob[2] - all_ob[0]) if all_ob else None
            self._meas_frame_width_lbl.setText(f"{fw:.1f} mm" if fw is not None else "—")

            # Frame height — y-extent of all OUTLINE curves (mirror is vertical
            # so no doubling). Every OUTLINE curve, not the two halves: _split
            # drops a curve centered on the axis, and a joined outline read "—".
            all_out = [c for c in curves if c.layer == Layer.OUTLINE and c.nodes]
            fh_bb = _curves_bbox(all_out) if all_out else None
            self._meas_frame_height_lbl.setText(
                f"{fh_bb[3] - fh_bb[1]:.1f} mm" if fh_bb else "—")

            # ── Lens boxing: LENS layer ────────────────────────────────
            # Use the SAMPLED bbox (same basis as the boxing guide + resizer) so
            # the read-out, the drawn box, and the typed resize target all agree.
            from .boxing import union_bbox
            os_len, od_len = _split(Layer.LENS)
            os_lb = union_bbox(os_len) if os_len else None
            od_lb = union_bbox(od_len) if od_len else None

            # A/B for each side; if only one side exists, both show the same value
            os_a = os_b = od_a = od_b = None
            if os_lb:
                os_a, os_b = os_lb[2] - os_lb[0], os_lb[3] - os_lb[1]
            if od_lb:
                od_a, od_b = od_lb[2] - od_lb[0], od_lb[3] - od_lb[1]
            if os_lb and not od_lb:
                od_a, od_b = os_a, os_b   # mirror — same shape
            elif od_lb and not os_lb:
                os_a, os_b = od_a, od_b   # mirror — same shape

            # Boxing measures the FINISHED (beveled) lens: grow A/B by the bevel.
            bevel_d = max(0.0, ws.bevel_depth)
            if bevel_d > 0:
                from .boxing import finished_ab
                if os_a is not None:
                    os_a, os_b = finished_ab(os_a, os_b, bevel_d)
                if od_a is not None:
                    od_a, od_b = finished_ab(od_a, od_b, bevel_d)

            _set_lens(self._meas_os_a_lbl, self._meas_os_b_lbl, self._meas_os_ed_lbl, os_a, os_b)
            _set_lens(self._meas_od_a_lbl, self._meas_od_b_lbl, self._meas_od_ed_lbl, od_a, od_b)

            # DBL — distance between nasal edges of the two LENS bboxes
            # OS nasal = os_lb[0] (left/inner edge of right-side lens)
            # OD nasal = od_lb[2] (right/inner edge of left-side lens)
            dbl = dbl_est = None
            if os_lb and od_lb:
                dbl = os_lb[0] - od_lb[2]
            elif os_lb:
                dbl = 2.0 * (os_lb[0] - mirror_x)
                dbl_est = True
            elif od_lb:
                dbl = 2.0 * (mirror_x - od_lb[2])
                dbl_est = True
            if dbl is not None and bevel_d > 0:
                from .boxing import finished_dbl
                dbl = finished_dbl(dbl, bevel_d)   # beveled nasal edges narrow DBL

            # Stash representative finished A/B/DBL for the snapped boxing read-outs.
            self._snap_a   = od_a if od_a is not None else os_a
            self._snap_b   = od_b if od_b is not None else os_b
            self._snap_dbl = dbl

            if dbl is not None:
                suffix = " mm ~" if dbl_est else " mm"
                self._meas_dbl_lbl.setText(f"{dbl:.1f}{suffix}")
            else:
                self._meas_dbl_lbl.setText("—")

        elif ws.workspace_type in ("temple_r", "temple_l"):
            curves = ws.doc_curves
            bbox = _curves_bbox(curves, layers=_TEMPLE_LAYERS)

            if bbox is None:
                self._meas_temple_length_lbl.setText("—")
                self._meas_endpiece_lbl.setText("—")
                return

            min_x, min_y, max_x, max_y = bbox
            x_span = max_x - min_x
            self._meas_temple_length_lbl.setText(f"{x_span:.1f} mm")

            # Endpiece width = the outline's height across the hinge-end band
            # (the first tenth of the length), measured on the drawn path.
            # Filtering whole curves by where their nodes cluster left a
            # normal one-piece temple reading "—", and doubled it with the
            # ghost on even when both halves were drawn.
            from .geometry import sample_curve
            ep_threshold = min_x + max(x_span * 0.1, 2.0)
            ys = [y for c in curves if c.layer in _TEMPLE_LAYERS and c.nodes
                  for x, y, _t in sample_curve(c) if x <= ep_threshold]
            if ys and ws.mirror_enabled and ws.scene.mirror is not None:
                axis = ws.scene.mirror.x         # a temple's axis is horizontal
                if all(y <= axis + 1e-6 for y in ys) or all(y >= axis - 1e-6 for y in ys):
                    ys += [2.0 * axis - y for y in ys]       # a half: the ghost completes it
            if ys:
                self._meas_endpiece_lbl.setText(f"{max(ys) - min(ys):.1f} mm")
            else:
                self._meas_endpiece_lbl.setText("—")

    # ------------------------------------------------------------------
    # Boxing snap / lock + bevel (M11 / M12)
    # ------------------------------------------------------------------

    def _current_bevel_depth(self) -> float:
        key = self._bevel_choices[self._bevel_combo.currentIndex()][1]
        if key == "custom":
            return self._bevel_depth_spin.value()
        return BEVEL_PRESETS.get(key, 0.0)

    def _apply_boxing_field_modes(self, ws=None):
        """A/B/DBL editability per mode: free = inputs; snapped = read-outs;
        locked = inputs again — A/B resize the lens, DBL moves the pair."""
        ws = ws or self._active_ws
        snapped, locked = ws.boxing_snapped, ws.shape_locked
        self._boxing_a_spin.setEnabled((not snapped) or locked)
        self._boxing_b_spin.setEnabled((not snapped) or locked)
        self._boxing_dbl_spin.setEnabled((not snapped) or locked)
        self._lock_shape_chk.setEnabled(snapped)
        self._outline_lock_chk.setEnabled(locked)
        # The A–B link acts only on a locked lens; lit otherwise, it looked
        # like it did something.
        self._chain_btn.setEnabled(locked)

    # A/B fields: drive the free box when not snapped; live-resize the locked
    # lens when locked (read-outs while snapped-but-unlocked never user-fire).
    def _on_boxing_a_value(self, v: float):
        ws = self._active_ws
        if not ws.boxing_snapped:
            self._boxing_guide.set_a(v)
        elif ws.shape_locked:
            self._locked_resize_from_field("a", v)

    def _on_boxing_b_value(self, v: float):
        ws = self._active_ws
        if not ws.boxing_snapped:
            self._boxing_guide.set_b(v)
        elif ws.shape_locked:
            self._locked_resize_from_field("b", v)

    def _on_boxing_dbl_value(self, v: float):
        ws = self._active_ws
        if not ws.boxing_snapped:
            self._boxing_guide.set_dbl(v)
        elif ws.shape_locked:
            self._set_dbl_by_move(v)

    def _on_chain_toggled(self, on: bool):
        self._active_ws.boxing_chain = on      # session state — not saved

    def _on_outline_lock_toggled(self, on: bool):
        self._active_ws.outline_locked = on
        self._status.showMessage(
            "Outline locked to lens — it co-resizes (constant wall)."
            if on else "Outline unlocked.")

    def _set_dbl_by_move(self, target_dbl: float):
        """Locked-mode DBL edit → translate the lens(es) along X to hit the
        target finished DBL.  Each lens moves away-from / toward the mirror axis
        by half the delta; a locked OPEN (half) outline rides along to keep the
        wall.  Closed (finished) frames are left in place (DBL is internal)."""
        ws = self._active_ws
        cur = self._finished_box_values()
        if not cur or cur[2] is None:
            return
        delta = target_dbl - cur[2]
        if abs(delta) < 0.02:
            return
        axis_x = ws.scene.mirror.x if ws.scene.mirror else 0.0
        lenses = [c for c in ws.doc_curves
                  if c.layer == Layer.LENS and not c.mirrored and c.nodes]
        if not lenses:
            return
        out_curves = [c for c in ws.doc_curves
                      if c.layer == Layer.OUTLINE and not c.mirrored and c.nodes]
        move_outline = (ws.outline_locked and out_curves
                        and self._outline_is_half(out_curves, axis_x))
        self._push_undo_snapshot()
        self._edit_tool.clear()
        for c in lenses:
            cx = sum(n.x for n in c.nodes) / len(c.nodes)
            self._translate_curve(c, (1.0 if cx >= axis_x else -1.0) * delta / 2.0, 0.0)
            self.scene.refresh_curve(c)
        if move_outline:
            ocx = (lambda b: (b[0] + b[2]) / 2)(_curves_bbox(out_curves))
            for c in out_curves:
                self._translate_curve(c, (1.0 if ocx >= axis_x else -1.0) * delta / 2.0, 0.0)
                self.scene.refresh_curve(c)
        ws.boxing_guide.refresh()
        self._refresh_measurements()
        self._sync_boxing_readouts()
        self._mark_dirty()

    @staticmethod
    def _outline_is_half(out_curves, axis_x: float) -> bool:
        """True if the outline is a single mirrored half (lies to one side of the
        axis); False if it straddles the axis as a finished full frame."""
        from .boxing import union_bbox
        ob = union_bbox(out_curves)
        if ob is None:
            return False
        w = ob[2] - ob[0]
        if w <= 1e-9:
            return False
        left, right = axis_x - ob[0], ob[2] - axis_x
        straddles = left > w * 0.25 and right > w * 0.25
        return not straddles

    def _outline_resize_plan(self, out_curves, axis_x, dW: float, dH: float):
        """Affine-scale plan for the OUTLINE that grows the eyewire wall by the
        same mm as the lens (constant wall), preserving flats/corners.  Open
        halves anchor on the nasal (bridge) edge; closed full frames scale
        symmetrically about the axis."""
        from .boxing import union_bbox
        from .resize import scale_curve_about
        ob = union_bbox(out_curves)
        if ob is None:
            return []
        out_w, out_h = ob[2] - ob[0], ob[3] - ob[1]
        piv_y = (ob[1] + ob[3]) / 2
        sy = (out_h + dH) / out_h if out_h > 1e-9 else 1.0
        if self._outline_is_half(out_curves, axis_x):
            out_cx = (ob[0] + ob[2]) / 2
            piv_x = ob[0] if out_cx >= axis_x else ob[2]      # nasal (bridge) edge
            sx = (out_w + dW) / out_w if out_w > 1e-9 else 1.0
        else:
            piv_x = axis_x                                     # symmetric full frame
            sx = (out_w + 2 * dW) / out_w if out_w > 1e-9 else 1.0
        if abs(sx - 1.0) < 1e-9 and abs(sy - 1.0) < 1e-9:
            return []
        out = []
        for c in out_curves:
            nc = scale_curve_about(c, piv_x, piv_y, sx, sy)
            nc.layer = c.layer
            nc.group_id = c.group_id
            out.append((c, nc))
        return out

    def _locked_resize_from_field(self, changed: str, v: float):
        """Live-resize the locked lens when A or B is edited.  Only the edited
        axis is targeted (the other is left untouched) unless the chain is on,
        in which case the other axis scales proportionally to keep the aspect."""
        cur = self._finished_box_values()
        if not cur or cur[0] is None or cur[1] is None:
            return
        cur_a, cur_b = cur[0], cur[1]
        chained = self._chain_btn.isChecked()
        if changed == "a":
            if abs(v - cur_a) < 0.02:
                return
            target_a = v
            target_b = cur_b * (v / cur_a) if (chained and cur_a) else None
        else:
            if abs(v - cur_b) < 0.02:
                return
            target_b = v
            target_a = cur_a * (v / cur_b) if (chained and cur_b) else None
        self._resize_locked_lens(target_a, target_b)

    def _on_boxing_visible_toggled(self, on: bool):
        """Boxing toolbar button. While snapped, a deliberate toggle also
        replaces the pre-snap memory — the maker's latest word is what
        un-snapping should restore."""
        ws = self._active_ws
        ws.boxing_guide.set_visible(on)
        if ws.boxing_snapped and not self._boxing_snap_syncing:
            ws.boxing_visible_pre_snap = on

    _boxing_snap_syncing = False

    def _on_boxing_snap_toggled(self, on: bool):
        ws = self._active_ws
        ws.boxing_snapped = on
        if not on and ws.shape_locked:
            ws.shape_locked = False              # leaving snap releases the lock
            self._lock_shape_chk.blockSignals(True)
            self._lock_shape_chk.setChecked(False)
            self._lock_shape_chk.blockSignals(False)
            self._edit_tool.refresh_for_selection()
        # Push the current bevel depth so the bevel outline appears immediately.
        ws.bevel_depth = self._current_bevel_depth()
        ws.boxing_guide.set_bevel_depth(ws.bevel_depth)
        ws.boxing_guide.set_locked(on)
        if on:
            # Snapping implies showing the guide — remember whether the maker
            # had it up, so un-snapping can put it back the way they left it.
            if ws.boxing_visible_pre_snap is None:
                ws.boxing_visible_pre_snap = self._act_boxing.isChecked()
            if not self._act_boxing.isChecked():
                self._boxing_snap_syncing = True
                try:
                    self._act_boxing.setChecked(True)
                finally:
                    self._boxing_snap_syncing = False
        self._apply_boxing_field_modes()
        if not on:
            # Restore the free-box A/B/DBL targets the read-outs overwrote.
            for spin, val in ((self._boxing_a_spin, ws.boxing_a),
                              (self._boxing_b_spin, ws.boxing_b),
                              (self._boxing_dbl_spin, ws.boxing_dbl)):
                spin.blockSignals(True)
                spin.setValue(max(spin.minimum(), min(spin.maximum(), val)))
                spin.blockSignals(False)
            ws.boxing_guide.set_a(ws.boxing_a)
            ws.boxing_guide.set_b(ws.boxing_b)
            ws.boxing_guide.set_dbl(ws.boxing_dbl)
            # Hide the guide again if it only appeared because we snapped —
            # otherwise the free box springs back at its default size and
            # position, which reads as the app forgetting what it was told.
            if ws.boxing_visible_pre_snap is False:
                self._boxing_snap_syncing = True
                try:
                    self._act_boxing.setChecked(False)
                finally:
                    self._boxing_snap_syncing = False
            ws.boxing_visible_pre_snap = None
        ws.boxing_guide.refresh()
        self._refresh_measurements()
        if on:
            self._sync_boxing_readouts()
        # No _mark_dirty: snap and lock are session state (reset_session_state),
        # never written to the file — a snap and unsnap left a clean design
        # starred and asking to be saved unchanged.

    def _on_lock_shape_toggled(self, on: bool):
        ws = self._active_ws
        if on and not ws.boxing_snapped:
            return                               # lock only meaningful while snapped
        ws.shape_locked = on
        self._apply_boxing_field_modes()
        self._edit_tool.refresh_for_selection()  # show/hide node dots for the lens
        if on:
            self._sync_boxing_readouts()
        self._status.showMessage(
            "Lens shape locked — type A/B to resize, or DBL to move the lenses."
            if on else "Lens shape unlocked — spline editing re-enabled.")

    def _resize_locked_lens(self, target_a, target_b):
        """Resize every LENS curve to the given finished target(s); a None target
        leaves that axis untouched.  Pure-computes first so a no-op never pushes
        an undo step."""
        ws = self._active_ws
        from .resize import size_to_finished_ab
        from .boxing import lens_bbox
        lenses = [c for c in ws.doc_curves
                  if c.layer == Layer.LENS and not c.mirrored and c.nodes]
        if not lenses:
            return
        axis_x = ws.scene.mirror.x if ws.scene.mirror else 0.0
        depth = ws.bevel_depth

        # Bare-shape width/height change of the representative lens — drives the
        # outline's constant-wall co-resize.
        rep_bb = lens_bbox(lenses[0])
        dW = (target_a - 2 * depth - (rep_bb[2] - rep_bb[0])) if target_a is not None else 0.0
        dH = (target_b - 2 * depth - (rep_bb[3] - rep_bb[1])) if target_b is not None else 0.0

        plans = []
        for c in lenses:
            new_c = size_to_finished_ab(c, target_a, target_b, depth, axis_x)
            if new_c is not None:
                plans.append((c, new_c))

        out_plans = []
        if ws.outline_locked and (abs(dW) > 1e-9 or abs(dH) > 1e-9):
            out_curves = [c for c in ws.doc_curves
                          if c.layer == Layer.OUTLINE and not c.mirrored and c.nodes]
            if out_curves:
                out_plans = self._outline_resize_plan(out_curves, axis_x, dW, dH)

        if not plans and not out_plans:
            return
        self._push_undo_snapshot()
        self._edit_tool.clear()
        new_sel = []
        for old_c, new_c in plans:
            new_c.layer    = old_c.layer
            new_c.group_id = old_c.group_id
            self._active_ws.remove_curve(old_c)
            new_sel.append(self._active_ws.add_curve(new_c))
        for old_c, new_c in out_plans:
            self._active_ws.remove_curve(old_c)
            self._active_ws.add_curve(new_c)
        self.scene.clearSelection()
        for it in new_sel:
            it.setSelected(True)
        ws.boxing_guide.refresh()
        self._refresh_measurements()
        self._sync_boxing_readouts()
        self._mark_dirty()

    def _finished_box_values(self):
        """(A, B, DBL) finished values stashed by the last _refresh_measurements."""
        a = getattr(self, "_snap_a", None)
        if a is None:
            return None
        return (a, getattr(self, "_snap_b", None), getattr(self, "_snap_dbl", None))

    def _sync_boxing_readouts(self):
        """Push the stashed finished A/B/DBL into the spinboxes (read-out display).
        Caller must have run _refresh_measurements first."""
        vals = self._finished_box_values()
        if vals is None:
            return
        for spin, val in zip(
                (self._boxing_a_spin, self._boxing_b_spin, self._boxing_dbl_spin),
                vals, strict=True):
            if val is None:
                continue
            spin.blockSignals(True)
            spin.setValue(max(spin.minimum(), min(spin.maximum(), val)))
            spin.blockSignals(False)

    def _schedule_boxing_follow(self, ws):
        """Coalesce live geometry changes (node edits, moves) into one update.

        Drives the live Properties-tab measurements on every edit, and — when
        boxing is snapped — also the guide that follows the lens geometry."""
        if ws is not self._active_ws:
            return
        if not getattr(self, "_boxing_follow_pending", False):
            self._boxing_follow_pending = True
            QTimer.singleShot(0, self, self._do_boxing_follow)

    def _do_boxing_follow(self):
        self._boxing_follow_pending = False
        ws = self._active_ws
        # Live measurements track node drags / moves regardless of snap state,
        # and so does the readiness dot (closing an outline's gap by dragging
        # its end node left the dot amber with the old gap in its tooltip).
        self._refresh_measurements()
        self._update_readiness()
        if ws.boxing_snapped:
            ws.boxing_guide.refresh()
            self._sync_boxing_readouts()

    def _on_bevel_preset_changed(self, idx: int):
        ws = self._active_ws
        key = self._bevel_choices[idx][1]
        ws.bevel_preset = key
        is_custom = (key == "custom")
        self._bevel_depth_spin.setEnabled(is_custom)
        if not is_custom:
            self._bevel_depth_spin.blockSignals(True)
            self._bevel_depth_spin.setValue(BEVEL_PRESETS.get(key, 0.0))
            self._bevel_depth_spin.blockSignals(False)
        ws.bevel_depth = self._current_bevel_depth()
        ws.boxing_guide.set_bevel_depth(ws.bevel_depth)
        self._refresh_measurements()
        if ws.boxing_snapped:
            self._sync_boxing_readouts()
        self._mark_dirty()

    def _on_bevel_depth_changed(self, v: float):
        ws = self._active_ws
        ws.bevel_depth = v
        ws.boxing_guide.set_bevel_depth(v)
        self._refresh_measurements()
        if ws.boxing_snapped:
            self._sync_boxing_readouts()
        self._mark_dirty()

    def _translate_curve(self, curve, dx: float, dy: float):
        """Translate all nodes (and their control points) of *curve* by (dx, dy) mm."""
        for node in curve.nodes:
            node.x += dx
            node.y += dy
            if node.cp_in:
                node.cp_in  = ControlPoint(node.cp_in.x  + dx, node.cp_in.y  + dy)
            if node.cp_out:
                node.cp_out = ControlPoint(node.cp_out.x + dx, node.cp_out.y + dy)

    def _translate_dim(self, dim, dx: float, dy: float):
        """Translate a DimLine by (dx, dy) and refresh its scene item."""
        dim.x0 += dx;  dim.y0 += dy
        dim.x1 += dx;  dim.y1 += dy
        item = self.scene._dim_items.get(id(dim))
        if item:
            item.prepareGeometryChange()
            item.update()

    def _pre_move_selected(self):
        """Called once when a drag-to-move starts (threshold exceeded)."""
        self._push_undo_snapshot()
        self._edit_tool.clear()
        # Prefer items captured at press time: super().mousePressEvent() may have
        # reselected the topmost item (e.g. outline) even though the user's intent was
        # to move an alt-clicked lower item (e.g. lens). If the press captured an
        # explicit pre-click selection, use that; otherwise fall back to current selection.
        items = self.view._drag_move_items or self.scene.selectedItems()
        self._drag_moving_curves = [it.curve    for it in items
                                    if isinstance(it, CurveItem)]
        self._drag_moving_dims   = [it.dim      for it in items
                                    if isinstance(it, DimItem)]
        self._drag_moving_texts  = [it.text_obj for it in items
                                    if isinstance(it, TextItem)]

    def _move_selected_by(self, dx: float, dy: float):
        """Translate the currently tracked selected geometry by (dx, dy) mm."""
        for curve in self._drag_moving_curves:
            self._translate_curve(curve, dx, dy)
            self.scene.refresh_curve(curve)
        for dim in self._drag_moving_dims:
            self._translate_dim(dim, dx, dy)
        for t in self._drag_moving_texts:
            t.anchor_x += dx
            t.anchor_y += dy
            self.scene.move_text(t)      # translation only — no glyph rebuild
        # Keep the gizmo centered on the moving geometry
        if self._move_gizmo is not None:
            new_c = QPointF(self._move_gizmo_center.x() + dx,
                            self._move_gizmo_center.y() + dy)
            self._move_gizmo_center = new_c
            self._move_gizmo.set_center(new_c)

    def _end_move_selected(self):
        """Rebuild edit handles after drag-to-move; restore the moved items as selection."""
        # Collect the scene items that correspond to the curves that were actually moved.
        moved_items = [self.scene._curve_items.get(id(c))
                       for c in self._drag_moving_curves]
        moved_items += [self.scene._dim_items.get(id(d))
                        for d in self._drag_moving_dims]
        moved_items += [self.scene._text_items.get(id(t))
                        for t in self._drag_moving_texts]
        moved_items = [it for it in moved_items if it is not None]

        # Re-select the moved curves. Qt may have reselected the topmost item during
        # the initial press; blockSignals prevents redundant _on_selection_changed calls.
        if moved_items:
            self.scene.blockSignals(True)
            self.scene.clearSelection()
            for it in moved_items:
                it.setSelected(True)
            self.scene.blockSignals(False)

        # Rebuild edit handles only for a single moved curve — a multi-curve
        # selection stays rigid (no node dots), matching EditTool._on_selection
        # so a follow-up drag can't grab and endpoint-snap a node.
        self._edit_tool.clear()
        if len(moved_items) == 1 and isinstance(moved_items[0], CurveItem):
            self._edit_tool._add_curve_items(moved_items[0])

        self._drag_moving_curves = []
        self._drag_moving_dims   = []
        self._drag_moving_texts  = []

        # Sync the Layers panel row and info label with the restored selection.
        if moved_items:
            self._on_selection_changed()

    def _gizmo_center_from_selection(self) -> QPointF | None:
        """Return the gizmo origin: bounding-box center of the selected
        curves and text objects."""
        xs, ys = [], []
        for it in self.scene.selectedItems():
            if isinstance(it, CurveItem):
                for node in it.curve.nodes:
                    xs.append(node.x)
                    ys.append(node.y)
            elif isinstance(it, TextItem):
                r = it.sceneBoundingRect()
                xs += [r.left(), r.right()]
                ys += [r.top(), r.bottom()]
        if not xs:
            return None
        return QPointF((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def _show_move_gizmo(self):
        """Show the move gizmo at the current selection center (no-op if nothing selected)."""
        center = self._gizmo_center_from_selection()
        if center is None:
            self._status.showMessage("Move gizmo: nothing selected")
            return
        self._hide_move_gizmo()   # remove any existing gizmo first
        from .canvas.move_gizmo import MoveGizmo
        self._move_gizmo_center = center
        self._move_gizmo = MoveGizmo(
            self.scene, self.view, center,
            on_pre_move = self._pre_move_selected,
            on_move     = self._move_selected_by,
            on_move_end = self._end_move_selected,
        )
        mk = self._hotkey_prefs.get("move_gizmo", "").strip()
        self._status.showMessage(
            "Move gizmo active  |  drag arrow to move  |  click arrow for exact "
            f"distance  |  {mk + ' or Esc' if mk else 'Esc'} to dismiss")

    def _hide_move_gizmo(self):
        if self._move_gizmo is not None:
            self._move_gizmo.remove()
            self._move_gizmo = None

    def _toggle_move_gizmo(self):
        if self._move_gizmo is not None:
            self._hide_move_gizmo()
        else:
            self._show_move_gizmo()

    # Toolbar visibility + hotkey management
    # ------------------------------------------------------------------

    # Actions restricted to certain workspaces. Final visibility is the AND
    # of the user's toolbar pref and this rule.
    _WS_ONLY_ACTIONS = _WS_ONLY_ACTIONS

    def _apply_toolbar_visibility(self, toolbar_prefs: dict, ws_type: str | None = None):
        """Show/hide toolbar actions: user prefs AND per-workspace rules.

        Both inputs must be applied together — applying prefs alone (the old
        Settings-dialog path) resurrected workspace-hidden buttons (e.g.
        Mirror Copy on Front) until the next tab switch, and applying
        workspace rules alone resurrected pref-hidden buttons on tab switch.
        """
        if ws_type is None:
            ws_type = self._active_ws.workspace_type
        for key, act in self._toolbar_actions.items():
            if key == "select":
                act.setVisible(True)
                continue
            visible = toolbar_prefs.get(key, True)
            allowed = self._WS_ONLY_ACTIONS.get(key)
            if allowed is not None:
                visible = visible and (ws_type in allowed)
            act.setVisible(visible)

    def _hotkey_dispatch(self, target):
        """Run a hotkey target unless a text-entry widget has focus.

        Hotkeys are single letters (L, S, E, …) with window-wide scope; without
        this guard they fire while the user is typing in a HUD line edit
        (MeasureBar, Point Move X/Y, Move gizmo distance).
        """
        from PySide6.QtWidgets import QAbstractSpinBox
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QAbstractSpinBox)):
            return
        target()

    def _apply_hotkeys(self, hotkey_prefs: dict):
        """Tear down existing hotkey QShortcuts and rebuild from hotkey_prefs."""
        from PySide6.QtGui import QShortcut, QKeySequence
        for sc in self._shortcuts.values():
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()
        self._square_seq = None
        self._refresh_hotkey_tooltips(hotkey_prefs)
        for key, target in self._hotkey_targets.items():
            key_str = hotkey_prefs.get(key, "").strip()
            if not key_str:
                continue
            if key_str in SettingsDialog._RESERVED_KEYS or key_str in _TYPING_KEYS:
                # An older prefs file can hold a key that is now fixed (Ctrl+O)
                # or read by the tools: bound twice, Qt fires neither.
                continue
            if key in _TEXT_FIELD_HOTKEYS:
                # NOT a QShortcut: application-context shortcuts go dead
                # while a modal dialog blocks their parent window, and this
                # binding is needed exactly there (bookmark names, library
                # saves, the engraving text dialog). The QApplication event
                # filter (eventFilter below) matches the sequence instead.
                self._square_seq = QKeySequence(key_str)
                continue
            sc = QShortcut(QKeySequence(key_str), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(
                lambda t=target: self._hotkey_dispatch(t))
            self._shortcuts[key] = sc

    def _refresh_hotkey_tooltips(self, hotkey_prefs: dict):
        for key, act in (("line", self._act_line), ("spline", self._act_spline),
                         ("circle", self._act_circle), ("arc", self._act_arc),
                         ("arc_sec", self._act_arc_sec), ("fillet", self._act_fillet),
                         ("dim", self._act_dim), ("trim", self._act_trim),
                         ("split_curve", self._act_split_curve),
                         ("offset", self._act_offset), ("rebuild", self._act_rebuild),
                         ("point_move", self._act_point_move), ("text", self._act_text),
                         ("snap_node_ep", self._act_snap_ep), ("join", self._act_join)):
            key_str = hotkey_prefs.get(key, "").strip()
            if key_str in SettingsDialog._RESERVED_KEYS or key_str in _TYPING_KEYS:
                key_str = ""                      # not bound (see _apply_hotkeys)
            # Built from the tooltip as written (its typed "(X)" dropped once),
            # never from the last result: a key like "/" or "Num+5" that the
            # pattern cannot strip otherwise piled up one more per OK.
            bases = self.__dict__.setdefault("_tip_bases", {})
            base = bases.setdefault(key, _tip_with_key(act.toolTip(), ""))
            act.setToolTip(_tip_with_key(base, key_str))

    def eventFilter(self, obj, event):
        """App-wide filter — installed on the QApplication, so this runs for
        every event the app delivers. A single Settings apply pushes ~12,000
        events through it, so it must stay one event.type() and an early
        fall-through.

        Never import inside this function. `from PySide6...` here runs
        shiboken's import hook on every one of those events; that is what hung
        the macOS Intel runner for the whole 120s test timeout, with the
        traceback parked in shibokensupport feature_imported underneath
        setStyleSheet re-polishing every widget. The import shipped in v1.1.0
        and only ever cost throughput until a slow runner turned it into a
        stall.
        """
        etype = event.type()
        if etype == QEvent.Type.KeyPress:
            # □ insertion (see _apply_hotkeys for why this is not a QShortcut).
            # getattr: the swatch button installs this filter while the side
            # panel is built, before _apply_hotkeys binds the sequence.
            if (_matches_key_event(getattr(self, "_square_seq", None), event)
                    and self._insert_square_char()):
                return True
        elif (etype == QEvent.Type.Resize
                and obj is getattr(self, "_fill_image_btn", None)):
            self._elide_fill_image_btn()
        return super().eventFilter(obj, event)

    def _insert_square_char(self) -> bool:
        """Type "□" (U+25A1) into the focused text field — the boxing square
        of frame-size notation A□DBL-TempleLength (e.g. 49□27-145).
        Returns True when inserted (eventFilter consumes the key press)."""
        fw = QApplication.focusWidget()
        # The hotkey-recording field must SEE the combo, not get a □ typed.
        if isinstance(fw, KeyCaptureEdit):
            return False
        return _insert_text_into(fw, "□")

    # ------------------------------------------------------------------
    # Toolbar icon refresh (called on build and on theme change)
    # ------------------------------------------------------------------

    def _apply_toolbar_icons(self, dark: bool):
        normal_c  = theme.color("chrome.ink")
        checked_c = theme.color("chrome.checked_ink")
        pairs = [
            (self._act_select,       "tool-select"),
            (self._act_line,         "tool-line"),
            (self._act_spline,       "tool-spline"),
            (self._act_circle,       "tool-circle"),
            (self._act_arc,          "tool-arc"),
            (self._act_arc_sec,      "tool-arc-sec"),
            (self._act_fillet,       "op-fillet"),
            (self._act_dim,          "tool-dim"),
            (self._act_mirror,       "toggle-mirror"),
            (self._act_guides,       "toggle-guides"),
            (self._act_snap,         "toggle-snap"),
            (self._act_snap_palette, "toggle-snap-palette"),
            (self._act_grid,         "toggle-grid"),
            (self._act_smooth,       "toggle-smooth"),
            (self._act_boxing,       "toggle-boxing"),
            (self._act_stock,        "toggle-stock"),
            (self._act_pad,          "toggle-pad"),
            (self._act_mirror_close, "op-mirror-close"),
            (self._act_dup_mirror,   "op-dup-mirror"),
            (self._act_copy_temple,  "op-copy-temple"),
            (self._act_join,         "op-join"),
            (self._act_snap_ep,      "op-snap-node"),
            (self._act_split,        "op-split"),
            (self._act_explode,      "op-explode"),
            (self._act_fit,          "op-fit"),
            (self._act_trim,         "tool-trim"),
            (self._act_split_curve,  "tool-split-curve"),
            (self._act_offset,       "tool-offset"),
            (self._act_rebuild,      "tool-rebuild"),
            (self._act_point_move,   "tool-point-move"),
            (self._act_text,         "tool-text"),
            (self._act_panel,        "view-sidebar"),
            (self._act_tooltips,     "toggle-tooltips"),
        ]
        for act, name in pairs:
            svg = _ICONS_DIR / f"{name}.svg"
            if svg.exists():
                act.setIcon(_make_icon(name, normal_c, checked_c))
        if (_ICONS_DIR / "link-chain.svg").exists():
            for attr in ("_chain_btn", "_lens_link_btn"):
                btn = getattr(self, attr, None)
                if btn is not None:
                    btn.setIcon(_make_icon("link-chain", normal_c, checked_c))
        self._refresh_mirror_icons()

    def _refresh_mirror_icons(self):
        """Re-render ghost and mirror-close icons rotated 90° for temple workspaces."""
        normal_c  = theme.color("chrome.ink")
        checked_c = theme.color("chrome.checked_ink")
        ws_type = self._active_ws.workspace_type if self._workspaces else "front"
        rot = 90 if ws_type in ("temple_r", "temple_l") else 0
        if (_ICONS_DIR / "toggle-mirror.svg").exists():
            self._act_mirror.setIcon(
                _make_icon("toggle-mirror", normal_c, checked_c, rotation=rot))
        if (_ICONS_DIR / "op-mirror-close.svg").exists():
            self._act_mirror_close.setIcon(
                _make_icon("op-mirror-close", normal_c, checked_c, rotation=rot))

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def _build_menus(self):
        mb = self.menuBar()

        from PySide6.QtGui import QKeySequence
        file_menu = mb.addMenu("File")
        # New / Open / Quit and the zooms had no shortcuts at all. Kept on
        # self: a text+slot addAction's wrapper is Python-owned (see Ctrl+,).
        self._act_new = file_menu.addAction("New", self._new)
        self._act_new.setShortcut(QKeySequence("Ctrl+N"))
        self._act_open = file_menu.addAction("Open…", self._open)
        self._act_open.setShortcut(QKeySequence("Ctrl+O"))
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._recent_menu.setToolTipsVisible(True)
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        # Real shortcuts (not tab-text like Undo/Redo) so the menu shows the
        # key AND the binding works window-wide through Qt's action system.
        act_save = file_menu.addAction("Save", self._save)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save_as = file_menu.addAction("Save As…", self._save_as)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction("Add Reference Image…", self._add_face)
        file_menu.addSeparator()
        imp = file_menu.addMenu("Import")
        imp.addAction("DXF…", self._import_dxf)
        imp.addAction("OMA Lens Trace…", self._import_oma)
        exp = file_menu.addMenu("Export")
        exp.addAction("DXF…", self._export_dxf)
        exp.addAction("All DXF…", self._export_all_dxf)
        exp.addAction("SVG…", self._export_svg)
        exp.addAction("PNG…", self._export_png)
        exp.addAction("OMA Lens Trace…", self._export_oma)
        exp.addSeparator()
        exp.addAction("PDF (1:1 Scale)…", self._export_pdf_1to1)
        exp.addAction("PDF Front + Temples (1:1 Templates)…",
                      self._export_pdf_templates)
        exp.addAction("PDF for Catalog…", self._export_pdf_catalog)
        file_menu.addSeparator()
        file_menu.addAction("Print at 1:1 Scale…", self._print_1to1)
        file_menu.addAction("Print Front + Temples (1:1 Templates)…",
                            self._print_templates)
        file_menu.addSeparator()
        self._act_quit = file_menu.addAction("Quit", self.close)
        self._act_quit.setShortcut(QKeySequence("Ctrl+Q"))

        edit_menu = mb.addMenu("Edit")
        self._act_undo = edit_menu.addAction("Undo\tCtrl+Z", self._handle_undo)
        self._act_undo.setEnabled(False)
        self._act_redo = edit_menu.addAction("Redo\tCtrl+Y", self._redo)
        self._act_redo.setEnabled(False)
        edit_menu.addSeparator()
        edit_menu.addAction("Copy\tCtrl+C",        self._copy_selected)
        edit_menu.addAction("Paste\tCtrl+V",       self._paste)
        edit_menu.addAction("Duplicate\tCtrl+D",   self._duplicate_selected)
        edit_menu.addAction("Select All\tCtrl+A",  self._select_all)
        edit_menu.addAction("Transform…\tCtrl+T",  self._transform_selected)
        edit_menu.addSeparator()
        edit_menu.addAction("Group\tCtrl+G", self._group_selected)
        edit_menu.addAction("Ungroup\tCtrl+Shift+G", self._ungroup_selected)

        view_menu = mb.addMenu("View")
        self._act_zoom_in = view_menu.addAction(
            "Zoom In", lambda: self.view.zoom_by(1.2))
        self._act_zoom_in.setShortcuts([QKeySequence("Ctrl++"),
                                        QKeySequence("Ctrl+=")])
        self._act_zoom_out = view_menu.addAction(
            "Zoom Out", lambda: self.view.zoom_by(1 / 1.2))
        self._act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self._act_fit_menu = view_menu.addAction("Fit", self._fit_view)
        self._act_fit_menu.setShortcut(QKeySequence("Ctrl+0"))
        view_menu.addSeparator()
        # The menu's own entries for the two toggles, following the toolbar's
        # each time the menu opens. Sharing the toolbar's QActions meant that
        # hiding the button in Preferences ▸ Toolbar hid the menu entry too —
        # and Ghost has no hotkey, so nothing could switch it any more.
        self._view_menu_toggles: dict[str, tuple[QAction, QAction]] = {}
        for key, act in (("ghost", self._act_mirror), ("guides", self._act_guides)):
            proxy = QAction(act.text(), self, checkable=True)
            proxy.setToolTip(act.toolTip())
            proxy.triggered.connect(lambda checked, a=act: a.setChecked(checked))
            view_menu.addAction(proxy)
            self._view_menu_toggles[key] = (proxy, act)
        view_menu.aboutToShow.connect(self._sync_view_menu_toggles)
        view_menu.addSeparator()
        view_menu.addAction(
            "Revision History",
            lambda: (self._prop_dock.show(), self._side_tabs.setCurrentIndex(3)),
        )
        view_menu.addSeparator()
        view_menu.addAction(self._prop_dock.toggleViewAction())

        settings_menu = mb.addMenu("Settings")
        self._act_dark = QAction("Dark Mode", self, checkable=True, checked=False)
        self._act_dark.triggered.connect(self._toggle_dark_mode)
        settings_menu.addAction(self._act_dark)
        settings_menu.addSeparator()
        # Ctrl+, — the ecosystem-wide Preferences shortcut (GuildSend set the
        # convention; GuildDraw and GuildModel now match). Kept on self: a
        # text+slot addAction's wrapper is Python-owned in PySide6, and losing
        # the last reference deletes the underlying QAction.
        self._act_prefs = settings_menu.addAction(
            "Preferences…", self._open_settings)
        self._act_prefs.setShortcut(QKeySequence("Ctrl+,"))

    def _sync_view_menu_toggles(self):
        ws_type = self._active_ws.workspace_type
        for key, (proxy, act) in self._view_menu_toggles.items():
            proxy.blockSignals(True)
            proxy.setChecked(act.isChecked())
            proxy.blockSignals(False)
            allowed = _WS_ONLY_ACTIONS.get(key)
            proxy.setVisible(allowed is None or ws_type in allowed)

    # ------------------------------------------------------------------
    # Tool switching
    # ------------------------------------------------------------------

    def _current_layer(self) -> Layer:
        return self._active_ws.active_layer

    def _deactivate_cursor_tools(self):
        """Deactivate the cursor tools (trim, fillet, split, offset, rebuild,
        point move) and clear their state."""
        self._trim_tool.deactivate()
        self._fillet_tool.deactivate()
        self._split_tool.deactivate()
        self._offset_tool.deactivate()
        self._rebuild_tool.deactivate()
        self._point_move_tool.deactivate()

    def _teardown_tools(self, clear_selection: bool):
        """Single teardown path for ALL tool switches.

        Every _set_tool_* must call this first. The per-setter teardown
        dances drifted apart repeatedly (stale Offset HUD, undeactivated
        tools) — never deactivate tools individually in a setter again.

        clear_selection=False for tools that operate on the current
        selection (Select keeps it for inspection; Offset/Point Move
        consume it).
        """
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._text_tool.deactivate()
        self._deactivate_cursor_tools()
        # Calibration too: armed, it outranks every tool in the view's press
        # handler, so after pressing L the next clicks still calibrated.
        if self._calib_tool.active:
            self._calib_tool.cancel(self.scene)
        self.view.measure_bar.hide_bar()
        if clear_selection:
            self._edit_tool.clear()
            self.scene.clearSelection()
        # The draw tool just deactivated — gray out the context snaps. A
        # line/spline setter re-enables them right after (below).
        self._update_snap_context()

    def _set_tool_select(self):
        self._teardown_tools(clear_selection=False)
        self._status.showMessage("Select: click a curve to select and show nodes")

    def _set_tool_line(self):
        self._teardown_tools(clear_selection=True)
        self._draw_tool.activate("line", self._current_layer(), self.scene,
                                 self.view, snap=self._snap,
                                 all_curves=self._doc_curves)
        self.view.set_draw_tool(self._draw_tool)
        self._update_snap_context()

    def _set_tool_spline(self):
        self._teardown_tools(clear_selection=True)
        self._draw_tool.activate("spline", self._current_layer(), self.scene,
                                 self.view, snap=self._snap,
                                 all_curves=self._doc_curves)
        self.view.set_draw_tool(self._draw_tool)
        self._update_snap_context()

    def _set_tool_circle(self):
        self._teardown_tools(clear_selection=True)
        self._circle_tool.activate("circle", self._current_layer(), self.scene,
                                   self.view, snap=self._snap,
                                   all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_arc(self):
        self._teardown_tools(clear_selection=True)
        self._circle_tool.activate("arc", self._current_layer(), self.scene,
                                   self.view, snap=self._snap,
                                   all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_arc_sec(self):
        self._teardown_tools(clear_selection=True)
        self._circle_tool.activate("arc_sec", self._current_layer(), self.scene,
                                   self.view, snap=self._snap,
                                   all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_fillet(self):
        self._teardown_tools(clear_selection=True)
        self._fillet_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._fillet_tool)

    def _set_tool_dim(self):
        self._teardown_tools(clear_selection=True)
        self._dim_tool.activate(self.scene, self.view,
                                snap=self._snap, all_curves=self._doc_curves)
        self.view.set_dim_tool(self._dim_tool)

    def _set_tool_text(self):
        # ENGRAVING is a temple-workspace layer (toolbar hides the button
        # elsewhere, but the hotkey can still fire).
        if Layer.ENGRAVING not in WORKSPACE_LAYERS[self._active_ws.workspace_type]:
            self._back_to_select(
                "Text engraving is available in the Temple workspaces.")
            return
        self._teardown_tools(clear_selection=True)
        self._text_tool.activate(Layer.ENGRAVING, self.scene, self.view,
                                 self._active_ws.snap)
        self.view.set_draw_tool(self._text_tool)

    def _on_text_added(self, text_obj):
        self._push_undo_snapshot()
        self._active_ws.add_text(text_obj)
        self._act_select.setChecked(True)
        self._set_tool_select()
        self._status.showMessage(
            f"Text placed on {text_obj.layer.value} — drag to move, "
            "double-click to edit, Del to remove."
        )

    def _on_text_canceled(self):
        self._back_to_select()

    def _back_to_select(self, message: str | None = None):
        """Put the view and toolbar back in Select mode, keeping `message` —
        or, when None, whatever the tool last said — on show. Select's own
        prompt otherwise replaced a refusal ("select something first") or a
        tool's "canceled" the moment it appeared."""
        msg = self._status.currentMessage() if message is None else message
        self._act_select.setChecked(True)
        self._set_tool_select()
        if msg:
            self._status.showMessage(msg, 4000)

    def _on_draw_canceled(self):
        """Esc in Line/Spline/Circle/Arc/Dim: the tool has deactivated
        itself; put the view and toolbar back in Select mode (they used to
        keep routing to the dead tool, so nothing was selectable until the
        Select button was clicked). Keep the tool's own message on show."""
        self._back_to_select()

    def _edit_text_object(self, text_obj):
        """Double-click on a TextItem — re-open the dialog pre-filled."""
        dlg = TextDialog(self, text_obj)
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        if not v["text"].strip():
            self._status.showMessage(
                "Edit Text: empty text ignored — use Delete to remove the object.")
            return
        # Only what changed: OK on an untouched dialog pushed an undo step and
        # starred the design. TextDialog hands back the stored value of any
        # field left alone, so an exact comparison is the right one.
        changes = {k: v[k] for k in ("text", "family", "size_mm", "rotation",
                                     "anchor_x", "anchor_y")
                   if v[k] != getattr(text_obj, k)}
        if not changes:
            return
        self._push_undo_snapshot()
        for k, val in changes.items():
            setattr(text_obj, k, val)
        self.scene.refresh_text(text_obj)
        self._refresh_layer_panel()   # label shows the (now-changed) string
        self._status.showMessage("Text updated.")

    def _set_tool_trim(self):
        self._teardown_tools(clear_selection=True)
        self._trim_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._trim_tool)

    def _set_tool_split_curve(self):
        self._teardown_tools(clear_selection=True)
        self._split_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._split_tool)

    def _on_trim_applied(self, original, remaining: list):
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self._active_ws.remove_curve(original)
        for c in remaining:
            self._active_ws.add_curve(c)

    def _on_split_applied(self, pairs: list):
        """Apply all splits from one click — [(original, [parts]), ...] —
        as a single undo step (an intersection split breaks several curves)."""
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        for original, parts in pairs:
            self._active_ws.remove_curve(original)
            for c in parts:
                self._active_ws.add_curve(c)

    def _on_fillet_applied(self, line1, line2, new_curves: list):
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self._active_ws.remove_curve(line1)
        self._active_ws.remove_curve(line2)
        for c in new_curves:
            self._active_ws.add_curve(c)

    def _on_trim_canceled(self):
        self._back_to_select()

    def _on_split_canceled(self):
        self._back_to_select()

    # ------------------------------------------------------------------
    # Offset tool
    # ------------------------------------------------------------------

    def _set_tool_offset(self):
        # Capture selection before teardown (deactivation may clear it)
        selected_curves = [
            item.curve for item in self.scene.selectedItems()
            if isinstance(item, CurveItem) and not item.curve.mirrored
        ]
        source = selected_curves[0] if len(selected_curves) == 1 else None

        self._teardown_tools(clear_selection=False)
        self._offset_tool.activate(self.scene, self.view, source)
        self.view.set_draw_tool(self._offset_tool)

    def _on_offset_applied(self, source_curve, offset_curve):
        self._push_undo_snapshot()
        self._active_ws.add_curve(offset_curve)
        # Return to Select mode first (re-enables ItemIsSelectable on all items)
        self._act_select.setChecked(True)
        self._set_tool_select()
        # Now selection is possible — clear and select the new curve
        self.scene.clearSelection()
        item = self.scene._curve_items.get(id(offset_curve))
        if item is not None:
            item.setSelected(True)
        self._status.showMessage(
            f"Offset {offset_curve.layer.value} curve created — select + edit nodes to refine"
        )

    def _on_offset_canceled(self):
        self._back_to_select()

    # ------------------------------------------------------------------
    # Rebuild Spline tool (M31.2)
    # ------------------------------------------------------------------

    def _set_tool_rebuild(self):
        # Capture selection before teardown (deactivation may clear it).
        selected = [
            item.curve for item in self.scene.selectedItems()
            if isinstance(item, CurveItem) and not item.curve.mirrored
        ]
        source = selected[0] if len(selected) == 1 else None

        self._teardown_tools(clear_selection=False)
        self._rebuild_tool.activate(self.scene, self.view, source)
        self.view.set_draw_tool(self._rebuild_tool)

    def _on_rebuild_applied(self, source_curve, rebuilt_curve):
        # Rebuild REPLACES the source: the whole point is to swap a dense/heavy
        # curve for the clean one at the same place. Undoable, so Ctrl+Z brings
        # the original back.
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self._active_ws.remove_curve(source_curve)
        self._active_ws.add_curve(rebuilt_curve)
        # Return to Select mode (re-enables ItemIsSelectable), then select the new curve.
        self._act_select.setChecked(True)
        self._set_tool_select()
        self.scene.clearSelection()
        item = self.scene._curve_items.get(id(rebuilt_curve))
        if item is not None:
            item.setSelected(True)
        self._status.showMessage(
            f"Rebuilt to {len(rebuilt_curve.nodes)} nodes — select + edit to refine"
        )

    def _on_rebuild_canceled(self):
        self._back_to_select()

    # ------------------------------------------------------------------
    # Point Move tool
    # ------------------------------------------------------------------

    def _set_tool_point_move(self):
        # Capture the selection NOW: set_draw_tool() strips ItemIsSelectable
        # from every item, which clears the Qt selection out from under us.
        # Relying on the live selection (or on the view's stale drag-capture
        # list) is why Point Move only worked intermittently.
        sel = self.scene.selectedItems()
        self._pm_curves = [it.curve for it in sel if isinstance(it, CurveItem)]
        self._pm_dims   = [it.dim for it in sel if isinstance(it, DimItem)]
        self._pm_texts  = [it.text_obj for it in sel if isinstance(it, TextItem)]
        if not self._pm_curves and not self._pm_dims and not self._pm_texts:
            # Back to Select: a previous tool must not stay live.
            self._back_to_select("Point Move: select something first")
            return
        self._teardown_tools(clear_selection=False)
        self._point_move_tool.activate(self.scene, self.view,
                                        self._active_ws.snap)
        self.view.set_draw_tool(self._point_move_tool)

    def _on_point_moved(self, dx: float, dy: float):
        """Translate the selection captured at tool activation by (dx, dy)."""
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self._drag_moving_curves = list(self._pm_curves)
        self._drag_moving_dims   = list(self._pm_dims)
        self._drag_moving_texts  = list(getattr(self, "_pm_texts", []))
        self._move_selected_by(dx, dy)
        # Restore Select mode first so ItemIsSelectable is True before
        # _end_move_selected calls setSelected(True) on the moved items.
        self._act_select.setChecked(True)
        self._set_tool_select()
        self._end_move_selected()
        self._status.showMessage(
            f"Moved  Δx {dx:+.3f} mm  Δy {dy:+.3f} mm"
        )

    def _on_point_move_canceled(self):
        self._back_to_select()

    def _on_dim_added(self, dim: DimLine):
        self._push_undo_snapshot()
        self._active_ws.add_dim(dim)
        self._act_select.setChecked(True)
        self._set_tool_select()
        dist = math.hypot(dim.x1 - dim.x0, dim.y1 - dim.y0)
        self._status.showMessage(
            f"Dim placed: {dist:.2f} mm  (select + Del to remove)"
        )

    def _on_measure_commit_radius(self, radius_mm: float):
        """MeasureBar Enter: confirm circle radius or lock arc radius."""
        if not self._circle_tool.active:
            return
        self._circle_tool.set_radius_and_advance(radius_mm)
        self.view.setFocus()

    def _toggle_snap_palette(self, on: bool):
        if on:
            anchor = self._toolbar.widgetForAction(self._act_snap_palette)
            panel = self._toolbar.visible_panel()
            if panel is not None and (anchor is None or not anchor.isVisible()):
                anchor = panel.button_for(self._act_snap_palette) or anchor
            self._snap_palette.reposition(self._toolbar, anchor)
            if panel is not None:
                # Beside the pinned pop-out, not under it: both anchor at the
                # toolbar's edge, and the pop-out re-raises on every refresh.
                right = panel.geometry().right() + 4
                if self._snap_palette.x() < right:
                    self._snap_palette.move(right, self._snap_palette.y())
            self._update_snap_context()
            self._snap_palette.show()
            self._snap_palette.raise_()
        else:
            self._snap_palette.hide()

    def _update_snap_context(self):
        """Enable the palette's context snaps (tangent/perpendicular) only while
        a line/spline draw is active — they need a point being drawn."""
        pal = getattr(self, "_snap_palette", None)
        if pal is not None:
            pal.set_context_available(self._draw_tool.active)

    # ------------------------------------------------------------------
    # Grid overlay (global — same grid on every workspace)
    # ------------------------------------------------------------------

    def _apply_grid_config(self, save: bool = False):
        """Push grid visibility + spacing + appearance from prefs onto every
        view and every snap engine (grid snap uses the overlay spacing)."""
        visible     = bool(self._prefs.get("grid_visible", False))
        spacing     = float(self._prefs.get("grid_spacing_mm", 2.0))
        major       = int(self._prefs.get("grid_major", 5))
        minor_color = str(self._prefs.get("grid_minor_color", "") or "")
        major_color = str(self._prefs.get("grid_major_color", "") or "")
        major_width = float(self._prefs.get("grid_major_width_px", 1.0))
        for ws in self._workspaces:
            ws.view.set_grid(visible=visible, spacing_mm=spacing, major=major,
                             minor_color=minor_color, major_color=major_color,
                             major_width=major_width)
            ws.snap.set_grid_spacing(spacing)
        if save:
            _prefs_mod.save(self._prefs)

    def _on_grid_toggled(self, on: bool):
        self._prefs["grid_visible"] = bool(on)
        for ws in self._workspaces:
            ws.view.set_grid(visible=on)
        _prefs_mod.save(self._prefs)

    def _on_snap_types_changed(self, types: dict):
        """Palette toggles apply to every workspace and persist immediately."""
        for ws in self._workspaces:
            ws.snap.set_enabled_types(types)
        self._prefs["snap_types"] = dict(types)
        _prefs_mod.save(self._prefs)

    def _on_snap_radius_changed(self, px: int):
        for ws in self._workspaces:
            ws.snap.set_radius_px(px)
        self._prefs["snap_radius_px"] = int(px)
        _prefs_mod.save(self._prefs)

    def _on_mirror_toggled(self, on: bool):
        if self.scene.mirror:
            self.scene.mirror.set_enabled(on)
        self.scene.set_mirror_display(on)
        axis_x     = self.scene.mirror.x if self.scene.mirror else 0.0
        horizontal = (self._active_ws.workspace_type in ("temple_r", "temple_l"))
        self._snap.set_mirror(axis_x, on, horizontal=horizontal)
        self._boxing_guide.set_mirror(on)
        self._boxing_guide.set_axis_x(axis_x)
        # Keep the workspace flag live (measurements read it) — it used to be
        # written only when leaving the tab. mirror.enabled is saved with the
        # document, so this is an unsaved change.
        self._active_ws.mirror_enabled = on
        self._mark_dirty()
        self._update_readiness()   # mirror doubling changes LENS/OUTLINE counts

    def _on_curve_added(self, curve):
        curve.line_weight = self._default_line_weight
        self._push_undo_snapshot()        # snapshot BEFORE the curve is added
        self._active_ws.add_curve(curve)  # (measurements refresh via _notify)
        # Return to select mode so the user can immediately inspect the new curve
        self._act_select.setChecked(True)
        self._set_tool_select()

    # ------------------------------------------------------------------
    # Layer re-labeling for selected curves
    # ------------------------------------------------------------------

    def _expand_selection_to_groups(self):
        """Selecting any member of a group selects the whole group.

        Runs with scene signals blocked so the expansion does not recurse;
        callers continue with the (now expanded) selection.
        """
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        gids = {i.curve.group_id for i in selected if i.curve.group_id}
        if not gids:
            return
        to_add = [it for it in self.scene._curve_items.values()
                  if it.curve.group_id in gids and not it.isSelected()]
        if not to_add:
            return
        self.scene.blockSignals(True)
        for it in to_add:
            it.setSelected(True)
        self.scene.blockSignals(False)
        # Repaint: blocked signals suppressed the view's selection-highlight update.
        self.view.viewport().update()

    def _on_selection_changed(self):
        """Reflect the selected curve's layer and weight in the UI (Select mode)."""
        if self._draw_tool.active or self._circle_tool.active:
            return
        self._expand_selection_to_groups()
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if len(selected) == 1:
            # Selecting a curve makes its layer the active drawing layer
            # (preserves the old combo behavior) and highlights its row.
            sel_layer = selected[0].curve.layer
            if sel_layer is not self._active_ws.active_layer:
                self._active_ws.active_layer = sel_layer
                self._sync_layer_panel_active()
            # Reflect a single canvas selection in the tree's current row, but
            # NOT while we're syncing FROM the tree (that would clear the user's
            # multi-row pick mid-loop).
            if not self._syncing_selection:
                row = getattr(self, "_layer_tree_rows", {}).get(id(selected[0].curve))
                if row is not None:
                    self._syncing_selection = True
                    self._layer_tree.setCurrentItem(row)
                    self._syncing_selection = False
            self._updating_weight_spin = True
            self._weight_spin.setValue(selected[0].curve.line_weight)
            self._updating_weight_spin = False
        # A single selected engraving text highlights its panel row too.
        texts = [i for i in self.scene.selectedItems() if isinstance(i, TextItem)]
        if not selected and len(texts) == 1 and not self._syncing_selection:
            row = getattr(self, "_layer_tree_text_rows", {}).get(id(texts[0].text_obj))
            if row is not None:
                self._syncing_selection = True
                self._layer_tree.setCurrentItem(row)
                self._syncing_selection = False
        # Reposition gizmo on selection change, or hide if nothing selected
        if self._move_gizmo is not None:
            center = self._gizmo_center_from_selection()
            if center is not None:
                self._move_gizmo_center = center
                self._move_gizmo.set_center(center)
            else:
                self._hide_move_gizmo()
        self._update_info_label()

    def _on_weight_spin_changed(self, value: float):
        """Apply line-weight spinbox changes to selected curves or store for new curves."""
        if self._updating_weight_spin:
            return
        if self._draw_tool.active:
            return
        targets = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not targets:
            return
        self._push_undo_snapshot()
        for item in targets:
            item.curve.line_weight = value
            item.refresh()
        self._status.showMessage(f"Line weight → {value:.2f} px")

    # ------------------------------------------------------------------
    # Undo / redo  (snapshot-based: full deep-copy of curves + dims)
    # ------------------------------------------------------------------

    def _take_snapshot(self) -> dict:
        """Deep copy of the active workspace's curves and dims."""
        return self._active_ws.take_snapshot()

    def _push_undo_snapshot(self):
        """Snapshot the active workspace, then sync UI + dirty state."""
        self._active_ws.push_undo_snapshot()
        self._update_undo_actions()
        self._mark_dirty()   # every snapshot precedes a document mutation

    def _pre_edit_snapshot(self):
        """Called by EditTool just before any node or handle drag begins."""
        self._push_undo_snapshot()

    def _restore_snapshot(self, snapshot: dict):
        """Rebuild the active workspace's canvas from a snapshot."""
        self._active_ws.restore_snapshot(snapshot)

    def _end_operations_holding_curves(self):
        """Undo and redo rebuild every Curve object. A tool mid-operation —
        Rebuild, Fillet, Offset, Point Move — still holds the old ones and
        then applies to curves no longer in the document: Fillet left both
        originals beside their trimmed copies, Point Move reported a move
        that never happened. End it first."""
        if any(t.active for t in (self._rebuild_tool, self._fillet_tool,
                                  self._offset_tool, self._point_move_tool)):
            self._act_select.setChecked(True)
            self._set_tool_select()

    def _undo(self):
        self._end_operations_holding_curves()
        if not self._active_ws.undo():
            self._status.showMessage("Nothing to undo")
            return
        self._update_undo_actions()
        self._mark_dirty()
        n = len(self._undo_stack)
        self._status.showMessage(
            f"Undo — {n} step{'s' if n != 1 else ''} remaining")

    def _redo(self):
        self._end_operations_holding_curves()
        if not self._active_ws.redo():
            self._status.showMessage("Nothing to redo")
            return
        self._update_undo_actions()
        self._mark_dirty()
        n = len(self._redo_stack)
        self._status.showMessage(
            f"Redo — {n} step{'s' if n != 1 else ''} remaining")

    def _handle_undo(self):
        """Ctrl+Z: undo last draw-point when drawing, else canvas undo — also
        when the Line tool is up with no point placed (Ctrl+Z did nothing)."""
        if self._draw_tool.active and self._draw_tool.undo_last_point():
            self._status.showMessage("Undo: last point removed")
            return
        self._undo()

    def _update_undo_actions(self):
        u, r = len(self._undo_stack), len(self._redo_stack)
        self._act_undo.setEnabled(bool(u))
        self._act_redo.setEnabled(bool(r))
        self._act_undo.setText(f"Undo ({u})\tCtrl+Z" if u else "Undo\tCtrl+Z")
        self._act_redo.setText(f"Redo ({r})\tCtrl+Y" if r else "Redo\tCtrl+Y")

    def _delete_selected(self):
        # If a node is selected, delete the node (not the whole curve)
        if self._edit_tool.has_selected_node():
            self._push_undo_snapshot()
            curve = self._edit_tool.delete_selected_node()
            if curve is None:
                # Curve would have <2 nodes — delete the whole curve instead
                selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
                for item in selected:
                    self._active_ws.remove_curve(item.curve)
                self._status.showMessage("Node delete: curve too short, removed curve")
            else:
                self.scene.refresh_curve(curve)
                # Rebuild the edit handles so indices stay consistent
                items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
                self._edit_tool.clear()
                for it in items:
                    self._edit_tool._add_curve_items(it)
                self._status.showMessage(
                    f"Deleted node — {len(curve.nodes)} nodes remain")
            return

        selected_curves = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        selected_dims   = [i for i in self.scene.selectedItems() if isinstance(i, DimItem)]
        selected_texts  = [i for i in self.scene.selectedItems() if isinstance(i, TextItem)]

        if not selected_curves and not selected_dims and not selected_texts:
            self._status.showMessage("Nothing selected to delete")
            return

        self._push_undo_snapshot()

        for item in selected_dims:
            self._active_ws.remove_dim(item.dim)
        for item in selected_texts:
            self._active_ws.remove_text(item.text_obj)

        doc_ids = {id(c) for c in self._doc_curves}
        to_remove = [item.curve for item in selected_curves if id(item.curve) in doc_ids]
        if to_remove:
            self.scene.clearSelection()
            for curve in to_remove:
                self._active_ws.remove_curve(curve)
            n = len(to_remove)
            self._status.showMessage(f"Deleted {n} curve{'s' if n > 1 else ''}")
        elif selected_texts:
            n = len(selected_texts)
            self._status.showMessage(f"Deleted {n} text object{'s' if n > 1 else ''}")
        elif selected_dims:
            n = len(selected_dims)
            self._status.showMessage(f"Deleted {n} dimension{'s' if n > 1 else ''}")

    def _insert_node(self, curve: Curve, scene_pos):
        """Insert a node at the nearest point on *curve* to *scene_pos*."""
        if self._active_ws.shape_locked and curve.layer == Layer.LENS:
            self._status.showMessage(
                "Lens shape is locked — unlock it to add nodes")
            return
        if curve.group_id:
            self._status.showMessage(
                "Curve is grouped — Ctrl+Shift+G to ungroup before editing nodes")
            return
        snapshot = self._active_ws.take_snapshot()
        if self._edit_tool.insert_node_at(curve, scene_pos):
            # Push only now that something changed — pushing before the
            # attempt would wipe the redo stack even on a failed insert.
            self._active_ws.push_undo_state(snapshot)
            self._update_undo_actions()
            self._mark_dirty()
            self.scene.refresh_curve(curve)
            # Rebuild edit handles so the new dot appears
            items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
            self._edit_tool.clear()
            for it in items:
                self._edit_tool._add_curve_items(it)
            self._status.showMessage(
                f"Inserted node — {len(curve.nodes)} nodes total")

    # ------------------------------------------------------------------
    # Copy / Paste / Duplicate / Select All
    # ------------------------------------------------------------------

    _PASTE_OFFSET_MM = 5.0

    def _selection_payload(self):
        """(curves, dims, texts) behind the current canvas selection."""
        sel = self.scene.selectedItems()
        curves = [it.curve    for it in sel if isinstance(it, CurveItem)]
        dims   = [it.dim      for it in sel if isinstance(it, DimItem)]
        texts  = [it.text_obj for it in sel if isinstance(it, TextItem)]
        return curves, dims, texts

    @staticmethod
    def _payload_summary(verb: str, curves, dims, texts) -> str:
        """'Copied 3 curves, 1 text' — only the kinds that are present."""
        parts = []
        for n, noun in ((len(curves), "curve"), (len(dims), "dim"),
                        (len(texts), "text")):
            if n:
                parts.append(f"{n} {noun}{'s' if n != 1 else ''}")
        return f"{verb} " + ", ".join(parts)

    def _copy_selected(self):
        curves, dims, texts = self._selection_payload()
        if not curves and not dims and not texts:
            self._status.showMessage("Copy: nothing selected")
            return
        # In-memory clipboard — survives workspace switches, so curves can be
        # copied between tabs.
        self._clipboard = {"curves": copy.deepcopy(curves),
                           "dims":   copy.deepcopy(dims),
                           "texts":  copy.deepcopy(texts)}
        self._status.showMessage(
            self._payload_summary("Copied", curves, dims, texts))

    def _paste(self):
        clip = getattr(self, "_clipboard", None)
        if not clip or not any(clip.get(k) for k in ("curves", "dims", "texts")):
            self._status.showMessage("Paste: clipboard is empty")
            return
        self._paste_payload(copy.deepcopy(clip["curves"]),
                            copy.deepcopy(clip["dims"]),
                            copy.deepcopy(clip.get("texts", [])))

    def _duplicate_selected(self):
        curves, dims, texts = self._selection_payload()
        if not curves and not dims and not texts:
            self._status.showMessage("Duplicate: nothing selected")
            return
        self._paste_payload(copy.deepcopy(curves), copy.deepcopy(dims),
                            copy.deepcopy(texts))

    def _paste_payload(self, curves: list, dims: list, texts: list = ()):
        """Insert deep-copied curves/dims/texts at +5 mm offset and select them."""
        self._push_undo_snapshot()
        allowed = set(WORKSPACE_LAYERS[self._active_ws.workspace_type])
        gid_map: dict = {}
        remapped = 0
        new_items = []
        off = self._PASTE_OFFSET_MM
        for c in curves:
            self._translate_curve(c, off, off)
            if c.layer not in allowed:
                # Layer doesn't exist in this workspace (cross-tab paste) —
                # land on REF so the curve stays visible and non-machined.
                c.layer = Layer.REF
                remapped += 1
            if c.group_id:
                # Fresh group ids: the paste must not merge with the original
                c.group_id = gid_map.setdefault(c.group_id, uuid.uuid4().hex[:8])
            new_items.append(self._active_ws.add_curve(c))
        for d in dims:
            d.x0 += off; d.y0 += off
            d.x1 += off; d.y1 += off
            new_items.append(self._active_ws.add_dim(d))
        for t in texts:
            t.anchor_x += off
            t.anchor_y += off
            if t.layer not in allowed:
                t.layer = Layer.REF
                remapped += 1
            new_items.append(self._active_ws.add_text(t))
        self.scene.select_items(new_items)
        msg = self._payload_summary("Pasted", curves, dims, texts)
        if remapped:
            msg += f"  ({remapped} moved to REF — layer not in this workspace)"
        self._status.showMessage(msg)

    def _select_all(self):
        """Select every visible, unlocked curve and dim (Ctrl+A)."""
        if self.view._draw_tool is not None or self._dim_tool.active:
            self._act_select.setChecked(True)
            self._set_tool_select()
        picked = [it for group in (self.scene._curve_items, self.scene._dim_items,
                                   self.scene._text_items)
                  for it in group.values()
                  if it.isVisible()
                  and bool(it.flags() & it.GraphicsItemFlag.ItemIsSelectable)]
        self.scene.select_items(picked)
        self._status.showMessage(f"Selected {len(picked)} object(s)")

    # ------------------------------------------------------------------
    # Transform (scale / rotate)
    # ------------------------------------------------------------------

    def _transform_selected(self):
        sel = self.scene.selectedItems()
        items = [i for i in sel if isinstance(i, CurveItem)]
        text_items = [i for i in sel if isinstance(i, TextItem)]
        # Dims ride along: Ctrl+A then Transform scaled the drawing and left
        # its dimensions measuring the old one (and said nothing of them).
        dims = [i.dim for i in sel if isinstance(i, DimItem)]
        if not items and not text_items and not dims:
            self._status.showMessage("Transform: select curves or text first")
            return
        dlg = TransformDialog(self)
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        sx, sy, rot, pivot_origin = dlg.values()
        if sx == 1.0 and sy == 1.0 and rot == 0.0:
            return

        curves = [i.curve for i in items]
        if pivot_origin:
            px = py = 0.0
        else:
            xs, ys = [], []
            if curves:
                bb = _curves_bbox(curves)
                xs += [bb[0], bb[2]]; ys += [bb[1], bb[3]]
            for ti in text_items:
                r = ti.sceneBoundingRect()
                xs += [r.left(), r.right()]; ys += [r.top(), r.bottom()]
            for d in dims:
                xs += [d.x0, d.x1]; ys += [d.y0, d.y1]
            px, py = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

        # The dialog's angle is counter-clockwise on screen; the scene is
        # y-down, where a positive angle turns clockwise — hence the minus.
        cos_t = math.cos(math.radians(-rot))
        sin_t = math.sin(math.radians(-rot))

        def xf(x: float, y: float):
            dx, dy = (x - px) * sx, (y - py) * sy
            return (px + dx * cos_t - dy * sin_t,
                    py + dx * sin_t + dy * cos_t)

        self._push_undo_snapshot()
        self._edit_tool.clear()
        uniform = abs(sx - sy) < 1e-9
        final_curves = []
        for curve in curves:
            if curve.kind in ("circle", "arc") and not uniform:
                # Ellipse result — not representable; convert to spline first
                repl = (circle_to_spline(curve) if curve.kind == "circle"
                        else arc_to_spline(curve))
                self._active_ws.remove_curve(curve)
                for n in repl.nodes:
                    n.x, n.y = xf(n.x, n.y)
                    if n.cp_in:
                        n.cp_in = ControlPoint(*xf(n.cp_in.x, n.cp_in.y))
                    if n.cp_out:
                        n.cp_out = ControlPoint(*xf(n.cp_out.x, n.cp_out.y))
                self._active_ws.add_curve(repl)
                final_curves.append(repl)
            elif curve.kind in ("circle", "arc"):
                c0 = curve.nodes[0]
                c0.x, c0.y = xf(c0.x, c0.y)
                curve.radius = (curve.radius or 0.0) * abs(sx)
                if curve.kind == "arc" and rot:
                    # Rotation shifts both angles equally (same atan2 space,
                    # scene y-down, so a counter-clockwise turn subtracts)
                    curve.start_angle = (curve.start_angle - rot) % 360
                    curve.end_angle   = (curve.end_angle - rot) % 360
                self.scene.refresh_curve(curve)
                final_curves.append(curve)
            else:
                for n in curve.nodes:
                    n.x, n.y = xf(n.x, n.y)
                    if n.cp_in:
                        n.cp_in = ControlPoint(*xf(n.cp_in.x, n.cp_in.y))
                    if n.cp_out:
                        n.cp_out = ControlPoint(*xf(n.cp_out.x, n.cp_out.y))
                self.scene.refresh_curve(curve)
                final_curves.append(curve)

        # Text objects: the anchor rides the same transform; the glyphs
        # themselves scale by size (uniform only — lettering has no
        # stretched form) and turn with the rotation. The dialog's angle and
        # TextObject.rotation are both counter-clockwise.
        from .textpath import normalize_rotation
        text_note = ""
        for ti in text_items:
            t = ti.text_obj
            t.anchor_x, t.anchor_y = xf(t.anchor_x, t.anchor_y)
            if uniform:
                t.size_mm = max(0.1, t.size_mm * abs(sx))
            elif sx != 1.0 or sy != 1.0:
                text_note = "  (text size unchanged — non-uniform scale)"
            if rot:
                t.rotation = normalize_rotation(t.rotation + rot)
            self.scene.refresh_text(t)

        for d in dims:
            d.x0, d.y0 = xf(d.x0, d.y0)
            d.x1, d.y1 = xf(d.x1, d.y1)
            if uniform:
                d.offset *= abs(sx)
            item = self.scene._dim_items.get(id(d))
            if item:
                item.prepareGeometryChange()
                item.update()

        picked = [self.scene._curve_items.get(id(c)) for c in final_curves]
        picked = [it for it in picked if it is not None] + text_items
        picked += [it for it in (self.scene._dim_items.get(id(d)) for d in dims)
                   if it is not None]
        self.scene.select_items(picked)
        self._refresh_measurements()
        self._status.showMessage(
            self._payload_summary("Transformed", final_curves, dims,
                                  [ti.text_obj for ti in text_items])
            + f"  (scale {sx * 100:.0f}% × {sy * 100:.0f}%, rotate {rot:+.1f}°)"
            + text_note)

    # ------------------------------------------------------------------
    # Group / Ungroup
    # ------------------------------------------------------------------

    def _group_selected(self):
        """Bind the selected curves into a rigid group (Ctrl+G)."""
        curves = [it.curve for it in self.scene.selectedItems()
                  if isinstance(it, CurveItem)]
        if len(curves) < 2:
            self._status.showMessage("Group: select 2 or more curves first")
            return
        self._push_undo_snapshot()
        gid = uuid.uuid4().hex[:8]
        for c in curves:
            c.group_id = gid
        # Grouped curves expose no node dots — rebuild the edit handles
        self._edit_tool.clear()
        self._on_selection_changed()
        self._refresh_layer_panel()
        self._status.showMessage(
            f"Grouped {len(curves)} curves — moves as one unit "
            "(Ctrl+Shift+G to ungroup)")

    def _ungroup_selected(self):
        """Dissolve the group(s) in the current selection (Ctrl+Shift+G)."""
        curves = [it.curve for it in self.scene.selectedItems()
                  if isinstance(it, CurveItem) and it.curve.group_id]
        if not curves:
            self._status.showMessage("Ungroup: no grouped curves selected")
            return
        self._push_undo_snapshot()
        for c in curves:
            c.group_id = None
        # Node dots are allowed again — rebuild edit handles for the selection
        self._edit_tool._on_selection()
        self._refresh_layer_panel()
        self._status.showMessage(f"Ungrouped {len(curves)} curves")

    # ------------------------------------------------------------------
    # Copy-across-mirror (Mirror Close)
    # ------------------------------------------------------------------

    def _copy_across_mirror(self):
        """Combine a selected open half-curve with its mirror image into one
        closed curve.  The two endpoints are snapped to the mirror axis before
        combining, so the halves join cleanly even if they were placed slightly
        off-axis.

        Every hand-tuned Bézier handle is preserved: the kept half keeps its
        handles verbatim and the mirrored half gets their exact reflections
        (handles were previously recomputed wholesale, which discarded the
        maker's shaping)."""
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if len(selected) != 1:
            self._status.showMessage("Mirror Close: select exactly one open curve first")
            return

        curve = selected[0].curve

        if curve.closed:
            self._status.showMessage("Mirror Close: curve is already closed")
            return
        if len(curve.nodes) < 2:
            self._status.showMessage("Mirror Close: need at least 2 nodes")
            return

        self._push_undo_snapshot()

        is_horiz = bool(self.scene.mirror and getattr(self.scene.mirror, '_horizontal', False))
        axis_x   = self.scene.mirror.x if self.scene.mirror else 0.0

        def mp(x: float, y: float) -> tuple:
            return (x, -y) if is_horiz else (2.0 * axis_x - x, y)

        def copy_node(n: SplineNode) -> SplineNode:
            nn = SplineNode(x=n.x, y=n.y)
            if n.cp_in:
                nn.cp_in  = ControlPoint(n.cp_in.x,  n.cp_in.y)
            if n.cp_out:
                nn.cp_out = ControlPoint(n.cp_out.x, n.cp_out.y)
            return nn

        def mirror_node(n: SplineNode) -> SplineNode:
            """Reflected copy traversed in REVERSE order: cp_in/cp_out swap."""
            nn = SplineNode(*mp(n.x, n.y))
            if n.cp_out:
                nn.cp_in  = ControlPoint(*mp(n.cp_out.x, n.cp_out.y))
            if n.cp_in:
                nn.cp_out = ControlPoint(*mp(n.cp_in.x, n.cp_in.y))
            return nn

        # Kept half: snap the two end nodes onto the axis, translating their
        # handles with the node (exactly what dragging the node would do).
        original = [copy_node(n) for n in curve.nodes]
        for end in (0, -1):
            n = original[end]
            dx, dy = (0.0, -n.y) if is_horiz else (axis_x - n.x, 0.0)
            n.x += dx
            n.y += dy
            if n.cp_in:
                n.cp_in  = ControlPoint(n.cp_in.x + dx,  n.cp_in.y + dy)
            if n.cp_out:
                n.cp_out = ControlPoint(n.cp_out.x + dx, n.cp_out.y + dy)

        # Traversal: A (=original[0]) → kept half → B (=original[-1]) →
        # mirrored interior (reversed) → back to A.
        new_nodes = original + [mirror_node(n) for n in reversed(original[1:-1])]

        # Seam handles: A and B sit on the axis; the closed loop enters/leaves
        # them from the mirrored half, so the handle on that side is the exact
        # reflection of the kept-side handle — a mirror-symmetric join.
        node_a, node_b = original[0], original[-1]
        if node_a.cp_out:
            node_a.cp_in  = ControlPoint(*mp(node_a.cp_out.x, node_a.cp_out.y))
        if node_b.cp_in:
            node_b.cp_out = ControlPoint(*mp(node_b.cp_in.x, node_b.cp_in.y))

        new_curve = Curve(
            kind        = curve.kind,
            layer       = curve.layer,
            nodes       = new_nodes,
            closed      = True,
            line_weight = curve.line_weight,
        )

        # Replace the open half with the new closed shape
        self.scene.clearSelection()
        self._active_ws.remove_curve(curve)
        self._active_ws.add_curve(new_curve)
        self._status.showMessage(
            f"Mirror-closed → {len(new_nodes)}-node closed {new_curve.layer.value}"
        )

    # ------------------------------------------------------------------
    # Duplicate Mirror — bake ghost into real geometry
    # ------------------------------------------------------------------

    def _on_duplicate_mirror(self):
        """Create real mirrored copies of all selected curves across the mirror axis.

        After this operation both the originals and copies are independent
        geometry.  The mirror toggle is turned off so the live ghost disappears
        and export does not double-mirror the result.
        """
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not selected:
            self._status.showMessage(
                "Duplicate Mirror: select one or more curves first"
            )
            return

        is_horiz = bool(self.scene.mirror and getattr(self.scene.mirror, '_horizontal', False))
        axis_x   = self.scene.mirror.x if self.scene.mirror else 0.0

        self._push_undo_snapshot()
        # This step turns Ghost off below; Undo puts it back (see undo()).
        self._undo_stack[-1]["mirror"] = self._act_mirror.isChecked()
        self.scene.clearSelection()

        gid_map: dict = {}
        copies = []
        for item in selected:
            c = mirror_curve(item.curve, axis_x, horizontal=is_horiz)
            if item.curve.group_id:   # the copy is its own rigid group
                c.group_id = gid_map.setdefault(item.curve.group_id,
                                                uuid.uuid4().hex[:8])
            copies.append(c)
        for c in copies:
            self._active_ws.add_curve(c)

        # Turn off live mirror so the originals no longer generate a ghost
        # and the export does not auto-mirror these curves a second time.
        self._act_mirror.setChecked(False)

        n = len(copies)
        self._status.showMessage(
            f"Duplicate Mirror: {n} curve{'s' if n != 1 else ''} duplicated. "
            "Use Join or Mirror-Close to connect halves."
        )

    # ------------------------------------------------------------------
    # Mirror Copy: temple_r ↔ temple_l
    # ------------------------------------------------------------------

    def _copy_temple_to_other(self):
        """Flip all content from the current temple workspace into the other.

        Both directions reflect through the horizontal axis (y = 0): the
        temples are drawn hinge-left, so the other side is the same arm
        flipped brow-edge-for-brow-edge. Curves and dims reflect exactly;
        engraving text lands on the reflected footprint but stays readable
        (see textpath.mirror_text), so the maker only has to change the
        words. Confirms before overwriting a non-empty target; pushes an
        undo snapshot in the target.
        """
        ws_type = self._active_ws.workspace_type
        if ws_type not in ("temple_r", "temple_l"):
            return

        # Identify source and target workspace objects
        tab_names = ["front", "temple_r", "temple_l", "hinge"]
        src_ws = self._active_ws
        if not (src_ws.doc_curves or src_ws.doc_dims or src_ws.doc_texts):
            self._status.showMessage(
                "Temple Copy: this temple is empty — nothing to copy")
            return
        target_type = "temple_l" if ws_type == "temple_r" else "temple_r"
        tgt_ws = self._workspaces[tab_names.index(target_type)]

        # Always confirm — a mis-click must never silently wipe a workspace.
        label = "Temple L" if target_type == "temple_l" else "Temple R"
        has_content = bool(tgt_ws.doc_curves or tgt_ws.doc_dims
                           or tgt_ws.doc_texts)
        detail = (f"This will REPLACE everything currently in {label}."
                  if has_content else f"{label} is currently empty.")
        r = QMessageBox.question(
            self, "Temple Copy",
            f"Send a mirrored copy of this temple to {label}?\n\n{detail}\n"
            f"(Ctrl+Z in {label} restores its previous content.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if r != QMessageBox.StandardButton.Yes:
            return

        def flip_dim(d: DimLine) -> DimLine:
            # The offset is measured along the dim's own normal, which the
            # y-flip reverses — negate it so the line stays on the same side
            # of the reflected geometry.
            return DimLine(x0=d.x0, y0=-d.y0,
                           x1=d.x1, y1=-d.y1,
                           offset=-d.offset)

        # Snapshot target for undo, replace its geometry with the flipped copy.
        tgt_ws.push_undo_snapshot()
        tgt_ws.clear_geometry()
        gid_map: dict = {}
        for c in src_ws.doc_curves:
            m = mirror_curve(c, 0.0, horizontal=True)
            if c.group_id:      # a grouped hinge stays a group on the other side
                m.group_id = gid_map.setdefault(c.group_id, uuid.uuid4().hex[:8])
            tgt_ws.add_curve(m)
        for d in src_ws.doc_dims:
            tgt_ws.add_dim(flip_dim(d))
        from .textpath import mirror_text
        for t in src_ws.doc_texts:
            tgt_ws.add_text(mirror_text(t, 0.0, horizontal=True))

        # Switch to target tab
        self._ws_tab_widget.setCurrentIndex(tab_names.index(target_type))
        self._mark_dirty()
        self._update_undo_actions()   # the promised Ctrl+Z is on THIS tab now
        self._status.showMessage(
            self._payload_summary("Temple Copy:", tgt_ws.doc_curves,
                                  tgt_ws.doc_dims, tgt_ws.doc_texts)
            + f" copied to {label}.")

    # ------------------------------------------------------------------
    # Join curves
    # ------------------------------------------------------------------

    _JOIN_TOL = 2.0  # mm — max endpoint distance to consider curves connectable

    def _close_single_curve(self, source):
        """Join applied to one curve: fuse its own two ends into a closed loop.

        This is the shape that comes back from importing a lens trace (OMA/DXF)
        and rebuilding it — one spline that reads as closed but is still an open
        path, so it never counts as a finished LENS. Chaining can't help: there
        is no second curve to connect to.
        """
        from .document import SplineNode, Curve as _Curve

        curve = arc_to_spline(source) if source.kind == "arc" else source
        if curve.kind == "circle" or curve.closed:
            self._status.showMessage("Join: that curve is already closed.")
            return
        if len(curve.nodes) < 2:
            self._status.showMessage("Join: not enough nodes to close a loop.")
            return

        head, tail = curve.nodes[0], curve.nodes[-1]
        gap = math.hypot(tail.x - head.x, tail.y - head.y)
        if gap > self._JOIN_TOL:
            self._status.showMessage(
                f"Join: the curve's two ends are {gap:.2f} mm apart — snap one "
                f"onto the other (within {self._JOIN_TOL} mm) to close it, or "
                f"select a second curve to chain onto.")
            return

        # Fuse tail into head exactly as a multi-curve chain does when it comes
        # back round: the head keeps its position and outgoing handle, and
        # inherits the tail's incoming handle so the wrap segment curves the
        # way the drawn tail did.
        nodes = [SplineNode(x=n.x, y=n.y, cp_in=n.cp_in, cp_out=n.cp_out)
                 for n in curve.nodes]
        nodes[0] = SplineNode(x=head.x, y=head.y,
                              cp_in=tail.cp_in, cp_out=head.cp_out)
        nodes.pop()
        if len(nodes) < 3:
            self._status.showMessage(
                "Join: a closed curve needs at least 3 nodes.")
            return

        self._push_undo_snapshot()
        closed_curve = _Curve(
            kind=curve.kind,
            layer=curve.layer,
            nodes=nodes,
            closed=True,
            line_weight=curve.line_weight,
            group_id=source.group_id,
        )
        self.scene.clearSelection()
        self._active_ws.remove_curve(source)
        item = self._active_ws.add_curve(closed_curve)
        item.setSelected(True)
        note = f"  (ends were {gap:.2f} mm apart)" if gap > 1e-6 else ""
        self._status.showMessage(
            f"Closed {curve.kind} ({len(nodes)} nodes){note}")

    def _join_selected_curves(self):
        """Chain 2+ selected open curves into one by connecting nearest endpoints.

        With exactly one curve selected, Join closes that curve onto itself
        instead — see _close_single_curve."""
        from .document import SplineNode, Curve as _Curve

        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not selected_items:
            self._status.showMessage(
                "Join: select one curve to close it, or 2+ curves to chain them")
            return

        # The original curves are what we remove from the document at the end.
        originals = [item.curve for item in selected_items]

        if len(originals) == 1:
            self._close_single_curve(originals[0])
            return

        # Arcs store only their center node, so their endpoints can't be read
        # from nodes[0]/nodes[-1] — convert them to splines (with real endpoint
        # nodes) before chaining. Closed circles have no endpoints to join to,
        # so they're dropped from the join with a note.
        curves = []
        skipped_circles = 0
        for c in originals:
            if c.kind == "arc":
                curves.append(arc_to_spline(c))
            elif c.kind == "circle":
                skipped_circles += 1
            else:
                curves.append(c)

        if len(curves) < 2:
            if skipped_circles:
                self._status.showMessage(
                    "Join: circles have no endpoints — trim/split a circle to an "
                    "arc first, then join. Need 2+ joinable curves.")
            else:
                self._status.showMessage("Join: select 2 or more joinable curves")
            return

        def ep_dist(a, b):
            return math.hypot(a.x - b.x, a.y - b.y)

        def reversed_nodes(c):
            """Nodes in reverse order with cp_in/cp_out swapped (path reversal)."""
            return [SplineNode(x=n.x, y=n.y, cp_in=n.cp_out, cp_out=n.cp_in)
                    for n in reversed(c.nodes)]

        # Build chain: list of (curve, forward: bool)
        chain = [(curves[0], True)]
        remaining = list(curves[1:])

        while remaining:
            c0, fwd0 = chain[0]
            cN, fwdN = chain[-1]
            chain_head = c0.nodes[0]  if fwd0  else c0.nodes[-1]
            chain_tail = cN.nodes[-1] if fwdN  else cN.nodes[0]

            best_d    = float("inf")
            best_c    = None
            best_mode = None   # 'tail_fwd' | 'tail_rev' | 'head_cend' | 'head_cstart'

            for c in remaining:
                for d, mode in [
                    (ep_dist(chain_tail, c.nodes[0]),  "tail_fwd"),
                    (ep_dist(chain_tail, c.nodes[-1]), "tail_rev"),
                    (ep_dist(chain_head, c.nodes[-1]), "head_cend"),
                    (ep_dist(chain_head, c.nodes[0]),  "head_cstart"),
                ]:
                    if d < best_d:
                        best_d, best_c, best_mode = d, c, mode

            if best_d > self._JOIN_TOL:
                break
            remaining.remove(best_c)
            if   best_mode == "tail_fwd":    chain.append((best_c, True))
            elif best_mode == "tail_rev":    chain.append((best_c, False))
            elif best_mode == "head_cend":   chain.insert(0, (best_c, True))
            else:                            chain.insert(0, (best_c, False))

        if remaining:
            self._status.showMessage(
                f"Join: {len(remaining)} curve(s) couldn't connect — "
                f"endpoints must be within {self._JOIN_TOL} mm")
            return

        self._push_undo_snapshot()

        # Determine result properties
        result_kind   = "spline" if any(c.kind == "spline" for c, _ in chain) else "line"
        result_layer  = chain[0][0].layer
        result_weight = chain[0][0].line_weight

        # Build merged node list; handle cp_in/cp_out at each junction
        result_nodes = []
        for i, (c, fwd) in enumerate(chain):
            seg = list(c.nodes) if fwd else reversed_nodes(c)
            if i == 0:
                result_nodes.extend(seg)
            else:
                # Merge junction: keep chain tail pos/cp_in, take cp_out from seg head
                jn = result_nodes[-1]
                sh = seg[0]
                result_nodes[-1] = SplineNode(
                    x=jn.x, y=jn.y,
                    cp_in=jn.cp_in,
                    cp_out=sh.cp_out,
                )
                result_nodes.extend(seg[1:])

        # Check if chain forms a closed loop
        is_closed = ep_dist(result_nodes[0], result_nodes[-1]) < self._JOIN_TOL
        if is_closed:
            # Merge tail into head: head takes cp_in from tail
            tail = result_nodes[-1]
            head = result_nodes[0]
            result_nodes[0] = SplineNode(
                x=head.x, y=head.y,
                cp_in=tail.cp_in,
                cp_out=head.cp_out,
            )
            result_nodes.pop()

        new_curve = _Curve(
            kind=result_kind,
            layer=result_layer,
            nodes=result_nodes,
            closed=is_closed,
            line_weight=result_weight,
        )

        self.scene.clearSelection()
        for c in originals:
            self._active_ws.remove_curve(c)

        item = self._active_ws.add_curve(new_curve)
        item.setSelected(True)
        note = (f"  ({skipped_circles} circle(s) skipped)"
                if skipped_circles else "")
        self._status.showMessage(
            f"Joined {len(curves)} curves{note} → "
            f"{'closed' if is_closed else 'open'} {result_kind} "
            f"({len(result_nodes)} nodes)"
        )

    # ------------------------------------------------------------------
    # Snap selected node to nearest endpoint
    # ------------------------------------------------------------------

    def _snap_selected_node_to_endpoint(self):
        """Move the selected (red) NodeDot to the nearest endpoint of any other open curve."""
        dot = self._edit_tool.selected_dot
        if dot is None:
            self._status.showMessage(
                "Snap Node: select a curve, then click a node to highlight it red, then press E")
            return

        curve    = dot._curve
        node_idx = dot.node_index
        node     = curve.nodes[node_idx]
        sx, sy   = node.x, node.y

        best_x, best_y = None, None
        best_d         = float("inf")

        for c in self._doc_curves:
            if c is curve or not c.nodes:
                continue
            # Only snap to endpoints of open curves
            if not c.closed:
                for ep in (c.nodes[0], c.nodes[-1]):
                    d = math.hypot(ep.x - sx, ep.y - sy)
                    if d < best_d:
                        best_d, best_x, best_y = d, ep.x, ep.y

        if best_x is None:
            self._status.showMessage("Snap Node: no endpoints found on other open curves")
            return

        self._push_undo_snapshot()

        dx, dy = best_x - node.x, best_y - node.y
        if node.cp_in:
            node.cp_in  = ControlPoint(node.cp_in.x  + dx, node.cp_in.y  + dy)
        if node.cp_out:
            node.cp_out = ControlPoint(node.cp_out.x + dx, node.cp_out.y + dy)
        node.x, node.y = best_x, best_y

        self.scene.refresh_curve(curve)

        # Rebuild edit handles from the updated data model; re-select the same node
        items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        self._edit_tool.clear()
        for it in items:
            self._edit_tool._add_curve_items(it)
        for ndot in self._edit_tool._dots:
            if ndot.node_index == node_idx:
                self._edit_tool._on_node_clicked(ndot)
                break

        self._status.showMessage(
            f"Snapped node to endpoint ({best_x:.2f}, {best_y:.2f}) mm  "
            f"[moved {best_d:.2f} mm]"
        )

    # ------------------------------------------------------------------
    # Split / Explode  (Phase 10b)
    # ------------------------------------------------------------------

    def _update_split_enabled(self, _=None):
        one_curve = (
            len([i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]) == 1
        )
        self._act_split.setEnabled(one_curve and self._edit_tool.has_selected_node())

    def _update_explode_enabled(self):
        any_curve = any(isinstance(i, CurveItem) for i in self.scene.selectedItems())
        self._act_explode.setEnabled(any_curve)

    def _split_at_node(self):
        """Break the selected curve at the selected (red) node into two open curves."""
        curve, idx = self._edit_tool.selected_node_info()
        if curve is None or not any(c is curve for c in self._doc_curves):
            self._status.showMessage("Split: select a node first")
            return

        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()

        if curve.closed:
            # Rotate node list so idx is both first and last → one open curve.
            # The seam node appears twice; deepcopy the slices SEPARATELY so
            # its two copies are independent objects (one deepcopy of the
            # combined list memoizes them into a single shared node, and
            # dragging one endpoint would silently move the other).
            rotated = (copy.deepcopy(curve.nodes[idx:])
                       + copy.deepcopy(curve.nodes[:idx + 1]))
            results = [
                Curve(kind=curve.kind, layer=curve.layer,
                      nodes=rotated, closed=False, line_weight=curve.line_weight)
            ]
        else:
            left_nodes  = copy.deepcopy(curve.nodes[:idx + 1])
            right_nodes = copy.deepcopy(curve.nodes[idx:])
            results = [
                Curve(kind=curve.kind, layer=curve.layer,
                      nodes=left_nodes,  closed=False, line_weight=curve.line_weight),
                Curve(kind=curve.kind, layer=curve.layer,
                      nodes=right_nodes, closed=False, line_weight=curve.line_weight),
            ]

        self._active_ws.remove_curve(curve)
        self.scene.select_items([self._active_ws.add_curve(c) for c in results])

        n = len(results)
        self._status.showMessage(f"Split → {n} curve{'s' if n > 1 else ''}")

    def _explode_selected(self):
        """Break each selected curve into individual 2-node segments."""
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not selected_items:
            self._status.showMessage("Explode: select one or more curves first")
            return

        # A circle or arc has one (center) node and no segments to break
        # into — exploding it deleted the arc and left a radius-less ghost
        # for the circle.
        round_items = [i for i in selected_items if i.curve.kind in ("circle", "arc")]
        selected_items = [i for i in selected_items if i not in round_items]
        if not selected_items:
            self._status.showMessage(
                "Explode: circles and arcs have no segments to break apart")
            return

        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()

        total_segs = 0
        new_items = []
        for item in selected_items:
            curve  = item.curve
            nodes  = curve.nodes
            n      = len(nodes)
            pairs  = range(n) if curve.closed else range(n - 1)

            segments = []
            for i in pairs:
                a   = copy.copy(nodes[i])
                b   = copy.copy(nodes[(i + 1) % n])
                seg = Curve(kind=curve.kind, layer=curve.layer,
                            nodes=[a, b], closed=False, line_weight=curve.line_weight)
                segments.append(seg)

            self._active_ws.remove_curve(curve)
            new_items += [self._active_ws.add_curve(seg) for seg in segments]
            total_segs += len(segments)
        self.scene.select_items(new_items)

        n_orig = len(selected_items)
        msg = f"Explode: {n_orig} curve{'s' if n_orig > 1 else ''} → {total_segs} segments"
        if round_items:
            msg += f"  ({len(round_items)} circle/arc left whole)"
        self._status.showMessage(msg)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self):
        # Pre-populate from stored prefs (startup defaults), with the durable
        # live values (theme, weight, toolbar, hotkeys) overlaid.
        current = {
            **self._prefs,
            "dark_mode":           self._dark_mode,
            "default_line_weight": self._default_line_weight,
            "toolbar":             dict(self._toolbar_prefs),
            "hotkeys":             dict(self._hotkey_prefs),
        }
        dlg = SettingsDialog(current, self)
        accepted = _run_modal(dlg) == QDialog.DialogCode.Accepted
        # The size the maker left it at is theirs to keep, Cancel or OK.
        self._prefs["prefs_dialog_size"] = [int(dlg.width()), int(dlg.height())]
        if not accepted:
            _prefs_mod.save(self._prefs)
            return
        self._apply_settings(dlg.to_prefs())

    def _apply_settings(self, p: dict) -> None:
        """Apply an accepted Settings-dialog prefs dict to the live session
        and persist it. Split from _open_settings so tests can exercise the
        apply logic without executing the modal dialog."""
        old_lens_opacity   = self._default_lens_fill_opacity()
        old_lens_intensity = self._default_lens_fill_intensity()
        old_prefs = dict(self._prefs)
        self._prefs.update(p)   # dialog is the sole writer of startup defaults

        # Theme + appearance first, so a mode toggle (or the explicit refresh
        # below) repaints with the new tokens in one pass. set_overrides
        # replaces the whole override set, so the viewport overlay must be
        # re-applied on top (same order as startup).
        theme.set_overrides(p["theme"])
        vp = p["viewport"]
        theme.apply_viewport(vp["preset"], vp.get("custom_bg"))
        theme.set_dot_radius(p["dot_radius_px"])
        theme.set_compact(p["compact_toolbar"])
        # The dots on show take the new size now, not at the next selection.
        for ws in self._workspaces:
            ws.edit_tool.refresh_for_selection()
        # Grid spacing/major changed in the dialog — re-push to views + engines
        # (visibility stays as the toolbar toggle left it).
        self._apply_grid_config()
        for ws in self._workspaces:
            ws.view.set_vignette(vp.get("vignette", 0))
        if p["dark_mode"] != self._dark_mode:
            self._act_dark.setChecked(p["dark_mode"])
            self._toggle_dark_mode(p["dark_mode"])
        else:
            self._refresh_theme_dependents()

        # Drawing — the spin shows the default; guard it so the change is not
        # applied to whatever curve happens to be selected (with an undo step).
        self._default_line_weight = p["default_line_weight"]
        self._updating_weight_spin = True
        try:
            self._weight_spin.setValue(p["default_line_weight"])
        finally:
            self._updating_weight_spin = False

        # Startup toggles + guide dimensions — these prefs describe the Frame
        # Front workspace (temple/hinge have their own fixed stock defaults),
        # so apply them to the front workspace ONLY. Driving the live toolbar
        # widgets from any other tab pushed front stock/pad guides into that
        # workspace's session state (GitHub issue #4: saving Settings inside a
        # Temple workspace re-drew the temple stock as the frame-front stock
        # and stranded a pad guide with no button to remove it).
        #
        # And only the ones the maker CHANGED: OK re-applied every one, so
        # opening Preferences to switch dark mode turned Snap back on and put
        # the stock and boxing sizes back to their defaults. The Ghost axis is
        # never pushed into the open document — it is saved with the design
        # (an asymmetric one would have flipped, and saved, mirrored); the
        # startup value is for the documents that follow.
        changed = {k for k in (
            "guides_on_startup", "snap_on_startup", "smooth_handles",
            "boxing_on_startup", "stock_on_startup", "pad_on_startup",
            "boxing_a_mm", "boxing_b_mm", "boxing_dbl_mm",
            "stock_width_mm", "stock_height_mm", "pad_width_mm", "pad_height_mm",
        ) if p[k] != old_prefs.get(k)}
        front = self._workspaces[0]
        if self._active_ws is front:
            # Widgets drive the active (= front) workspace via their signals.
            for key, act in (("guides_on_startup", self._act_guides),
                             ("snap_on_startup",   self._act_snap),
                             ("smooth_handles",    self._act_smooth),
                             ("boxing_on_startup", self._act_boxing),
                             ("stock_on_startup",  self._act_stock),
                             ("pad_on_startup",    self._act_pad)):
                if key in changed:
                    act.setChecked(p[key])
            if not front.boxing_snapped:
                # Snapped, the fields follow the lens (and with the shape
                # locked would RESIZE it to the startup A/B) — leave them.
                for key, spin in (("boxing_a_mm",   self._boxing_a_spin),
                                  ("boxing_b_mm",   self._boxing_b_spin),
                                  ("boxing_dbl_mm", self._boxing_dbl_spin)):
                    if key in changed:
                        spin.setValue(p[key])
            for key, spin in (("stock_width_mm",  self._stock_w_spin),
                              ("stock_height_mm", self._stock_h_spin),
                              ("pad_width_mm",    self._pad_w_spin),
                              ("pad_height_mm",   self._pad_h_spin)):
                if key in changed:
                    spin.setValue(p[key])
        else:
            # Write the front workspace's session state directly; the sidebar
            # widgets stay on the active workspace's values and the front tab
            # picks these up on activation (_restore_ws_sidebar_state).
            for key, attr in (("guides_on_startup", "guides_visible"),
                              ("snap_on_startup",   "snap_enabled"),
                              ("smooth_handles",    "smooth_handles"),
                              ("boxing_on_startup", "boxing_visible"),
                              ("stock_on_startup",  "stock_visible"),
                              ("pad_on_startup",    "pad_visible"),
                              ("boxing_a_mm",       "boxing_a"),
                              ("boxing_b_mm",       "boxing_b"),
                              ("boxing_dbl_mm",     "boxing_dbl"),
                              ("stock_width_mm",    "stock_w"),
                              ("stock_height_mm",   "stock_h"),
                              ("pad_width_mm",      "pad_w"),
                              ("pad_height_mm",     "pad_h")):
                if key in changed:
                    setattr(front, attr, p[key])

        # Lens Fill default opacity — a starting value, so it moves the live
        # slider only for workspaces that are still sitting on the old default
        # (a maker who has already dialed a tint in keeps their setting).
        # The values are saved with the design, so a design with content that
        # moves is marked unsaved — it used to change silently, leaving the
        # screen and the file disagreeing until the next save.
        moved_a_design = False
        new_opacity = self._default_lens_fill_opacity()
        if new_opacity != old_lens_opacity:
            for ws in self._workspaces:
                if abs(ws.lens_fill_opacity - old_lens_opacity) < 1e-9:
                    ws.lens_fill_opacity = new_opacity
                    ws.scene.set_lens_fill_opacity(new_opacity)
                    moved_a_design |= bool(ws.doc_curves)
            self._lens_fill_opacity_slider.blockSignals(True)
            self._lens_fill_opacity_slider.setValue(
                round(self._active_ws.lens_fill_opacity * 100))
            self._lens_fill_opacity_slider.blockSignals(False)
        new_intensity = self._default_lens_fill_intensity()
        if new_intensity != old_lens_intensity:
            for ws in self._workspaces:
                if abs(ws.lens_fill_intensity - old_lens_intensity) < 1e-9:
                    ws.lens_fill_intensity = new_intensity
                    ws.scene.set_lens_fill_intensity(new_intensity)
                    moved_a_design |= bool(ws.doc_curves)
            self._lens_fill_intensity_slider.blockSignals(True)
            self._lens_fill_intensity_slider.setValue(
                slider_from_intensity(self._active_ws.lens_fill_intensity))
            self._lens_fill_intensity_slider.blockSignals(False)
            self._update_lens_fill_swatches(self._active_ws.lens_fill_top,
                                            self._active_ws.lens_fill_bottom,
                                            self._active_ws.lens_fill_intensity)
        if moved_a_design:
            self._mark_dirty()

        # Toolbar visibility
        self._toolbar_prefs = p["toolbar"]
        self._apply_toolbar_visibility(self._toolbar_prefs)

        # Hotkeys
        self._hotkey_prefs = p["hotkeys"]
        self._apply_hotkeys(self._hotkey_prefs)

        self._save_prefs()

    # ------------------------------------------------------------------
    # Revision timeline (History tab)
    # ------------------------------------------------------------------

    def _on_timeline_selection(self):
        has = bool(self._timeline_list.selectedItems())
        self._btn_bm_restore.setEnabled(has)
        self._btn_bm_rename.setEnabled(has)
        self._btn_bm_delete.setEnabled(has)

    def _refresh_timeline_list(self):
        self._timeline_list.blockSignals(True)
        self._timeline_list.clear()
        for i, bm in enumerate(self._bookmarks):
            item = QListWidgetItem(f"{bm['name']}  ·  {bm['timestamp']}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            n = len(bm["snapshot"]["curves"])
            item.setToolTip(
                f"Created: {bm['timestamp']}\n{n} curve{'s' if n != 1 else ''}")
            self._timeline_list.addItem(item)
        self._timeline_list.blockSignals(False)
        self._on_timeline_selection()
        n = len(self._bookmarks)
        self._side_tabs.setTabText(3, f"History ({n})" if n else "History")

    def _add_bookmark(self):
        name, ok = QInputDialog.getText(
            self, "Bookmark Current State",
            "Revision name:",
            text=f"Revision {len(self._bookmarks) + 1}",
        )
        if not ok or not name.strip():
            return
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._bookmarks.append({
            "name":      name.strip(),
            "timestamp": ts,
            "snapshot":  self._take_snapshot(),
        })
        self._refresh_timeline_list()
        self._timeline_list.setCurrentRow(len(self._bookmarks) - 1)
        self._mark_dirty()   # bookmarks are persisted in the file
        self._status.showMessage(f"Bookmarked: {name.strip()}")

    def _restore_bookmark(self):
        items = self._timeline_list.selectedItems()
        if not items:
            return
        self._end_operations_holding_curves()     # it rebuilds every Curve too
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        bm = self._bookmarks[idx]
        self._push_undo_snapshot()
        # Deep-copy: _restore_snapshot installs the snapshot's objects as the
        # live document, and later in-place node edits would otherwise mutate
        # the stored bookmark.
        self._restore_snapshot(copy.deepcopy(bm["snapshot"]))
        self._status.showMessage(f"Restored bookmark: {bm['name']}")

    def _rename_bookmark(self):
        items = self._timeline_list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        bm = self._bookmarks[idx]
        name, ok = QInputDialog.getText(
            self, "Rename Bookmark", "New name:", text=bm["name"])
        if ok and name.strip():
            bm["name"] = name.strip()
            self._refresh_timeline_list()
            self._timeline_list.setCurrentRow(idx)
            self._mark_dirty()

    def _delete_bookmark(self):
        items = self._timeline_list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        bm = self._bookmarks[idx]
        r = QMessageBox.question(
            self, "Delete Bookmark",
            f"Delete bookmark \"{bm['name']}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self._bookmarks.pop(idx)
            self._refresh_timeline_list()
            self._mark_dirty()

    # ------------------------------------------------------------------
    # Hinge Library
    # ------------------------------------------------------------------

    def _refresh_library_panel(self) -> None:
        """Repopulate the Library list from disk."""
        from .library import HingeLibrary
        lib = HingeLibrary()
        entries = lib.list_entries()
        self._lib_list.clear()
        for e in entries:
            item = QListWidgetItem(f"{e['name']}  ·  {e['date']}")
            item.setData(Qt.ItemDataRole.UserRole, e["path"])
            self._lib_list.addItem(item)
        self._on_lib_selection_changed()

    def _on_lib_selection_changed(self) -> None:
        has_sel = self._lib_list.currentRow() >= 0
        self._btn_lib_import.setEnabled(has_sel)
        self._btn_lib_rename.setEnabled(has_sel)
        self._btn_lib_delete.setEnabled(has_sel)

    def _import_from_library(self) -> None:
        item = self._lib_list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        try:
            from .library import HingeLibrary
            curves, dims = HingeLibrary().load_entry(path)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        if not curves:
            QMessageBox.information(self, "Empty entry",
                                    "This library entry contains no geometry.")
            return

        # Translate bounding-box center to canvas origin.
        # _curves_bbox is radius-aware, so circles/arcs center correctly
        # (node-only bbox put a lone circle's *center point* at the origin).
        bb = _curves_bbox([c for c in curves if not c.mirrored])
        if bb:
            cx = (bb[0] + bb[2]) / 2
            cy = (bb[1] + bb[3]) / 2
            for c in curves:
                for nd in c.nodes:
                    nd.x -= cx;  nd.y -= cy
                    if nd.cp_in:
                        nd.cp_in.x  -= cx;  nd.cp_in.y  -= cy
                    if nd.cp_out:
                        nd.cp_out.x -= cx;  nd.cp_out.y -= cy
            for d in dims:
                d.x0 -= cx;  d.y0 -= cy
                d.x1 -= cx;  d.y1 -= cy

        self._push_undo_snapshot()
        # Import as a GROUP: the hinge moves as one rigid unit and exposes no
        # node dots, so its nodes can't be distorted by accidental node drags
        # snapping onto nearby frame geometry at the origin.
        gid = uuid.uuid4().hex[:8]
        for c in curves:
            c.mirrored = False
            c.group_id = gid
            self._active_ws.add_curve(c)
        for d in dims:
            self._active_ws.add_dim(d)

        name = item.text().split("  ·")[0]
        self._status.showMessage(
            f"Imported '{name}' as a group — {len(curves)} curve(s) at origin. "
            "Drag or Point Move (G) to place; Ctrl+Shift+G to ungroup."
        )

    def _save_to_library(self) -> None:
        if not self._doc_curves:
            QMessageBox.information(self, "Nothing to save",
                                    "There is no geometry in this workspace to save.")
            return
        name, ok = QInputDialog.getText(
            self, "Save to Library", "Name for this hinge design:"
        )
        if not ok or not name.strip():
            return
        try:
            from .library import HingeLibrary
            path = HingeLibrary().save_entry(
                name.strip(), self._doc_curves, self._doc_dims
            )
            self._refresh_library_panel()
            self._status.showMessage(
                f"Saved to library: {os.path.basename(path)}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _rename_library_entry(self) -> None:
        item = self._lib_list.currentItem()
        if not item:
            return
        old_path = item.data(Qt.ItemDataRole.UserRole)
        old_name = item.text().split("  ·")[0]
        new_name, ok = QInputDialog.getText(
            self, "Rename Library Entry", "New name:", text=old_name
        )
        if not ok or not new_name.strip():
            return
        try:
            from .library import HingeLibrary
            HingeLibrary().rename_entry(old_path, new_name.strip())
            self._refresh_library_panel()
        except Exception as exc:
            QMessageBox.critical(self, "Rename failed", str(exc))

    def _delete_library_entry(self) -> None:
        item = self._lib_list.currentItem()
        if not item:
            return
        name = item.text().split("  ·")[0]
        r = QMessageBox.question(
            self, "Delete Library Entry",
            f"Delete \"{name}\" from the library?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            from .library import HingeLibrary
            HingeLibrary().delete_entry(item.data(Qt.ItemDataRole.UserRole))
            self._refresh_library_panel()

    # ------------------------------------------------------------------
    # Drill holes (DRILL layer + pattern library, M13)
    # ------------------------------------------------------------------

    def _build_holes_panel(self) -> QWidget:
        """Drill-hole coordinate entry + pattern library (front workspace)."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        hint = QLabel("Holes go on the DRILL layer, offset from the lens boxing "
                      "center (the OMA datum).")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        entry = QGroupBox("Place hole")
        form = QFormLayout(entry)
        form.setSpacing(6)
        self._drill_x = QDoubleSpinBox()
        self._drill_x.setRange(-60, 60); self._drill_x.setSuffix(" mm")
        self._drill_x.setDecimals(2); self._drill_x.setSingleStep(0.5)
        self._drill_y = QDoubleSpinBox()
        self._drill_y.setRange(-40, 40); self._drill_y.setSuffix(" mm")
        self._drill_y.setDecimals(2); self._drill_y.setSingleStep(0.5)
        self._drill_dia = QDoubleSpinBox()
        self._drill_dia.setRange(0.5, 6.0); self._drill_dia.setSuffix(" mm")
        self._drill_dia.setDecimals(2); self._drill_dia.setSingleStep(0.1)
        self._drill_dia.setValue(1.4)
        self._drill_x.setToolTip("Toward the nose is positive, on either lens.")
        self._drill_y.setToolTip("Above the lens center is positive, as in an "
                                 "OMA trace.")
        form.addRow("X (from center):", self._drill_x)
        form.addRow("Y (from center):", self._drill_y)
        form.addRow("Diameter:", self._drill_dia)
        btn_add = QPushButton("Add Hole")
        btn_add.setToolTip("Place a hole at this offset from the lens boxing center.")
        btn_add.clicked.connect(self._add_drill_hole_from_fields)
        form.addRow(btn_add)
        lay.addWidget(entry)

        lay.addWidget(QLabel("Saved patterns:"))
        self._drill_list = QListWidget()
        self._drill_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._drill_list.setAlternatingRowColors(True)
        self._drill_list.itemSelectionChanged.connect(self._on_drill_selection_changed)
        self._drill_list.itemDoubleClicked.connect(lambda _: self._import_drill_pattern())
        lay.addWidget(self._drill_list)

        self._btn_drill_import = QPushButton("Import Pattern onto Lens")
        self._btn_drill_import.setEnabled(False)
        self._btn_drill_import.clicked.connect(self._import_drill_pattern)
        lay.addWidget(self._btn_drill_import)

        self._btn_drill_save = QPushButton("Save Current Holes as Pattern…")
        self._btn_drill_save.clicked.connect(self._save_drill_pattern)
        lay.addWidget(self._btn_drill_save)

        drow = QHBoxLayout()
        self._btn_drill_rename = QPushButton("Rename…")
        self._btn_drill_rename.setEnabled(False)
        self._btn_drill_rename.clicked.connect(self._rename_drill_pattern)
        self._btn_drill_delete = QPushButton("Delete")
        self._btn_drill_delete.setEnabled(False)
        self._btn_drill_delete.clicked.connect(self._delete_drill_pattern)
        drow.addWidget(self._btn_drill_rename)
        drow.addWidget(self._btn_drill_delete)
        lay.addLayout(drow)
        lay.addStretch()

        self._refresh_drill_library_panel()
        return w

    def _lens_boxing_center(self):
        """(cx, cy) of the representative front LENS (sampled), or None."""
        front = self._workspaces[0]
        lenses = [c for c in front.doc_curves
                  if c.layer == Layer.LENS and not c.mirrored and c.nodes]
        if not lenses:
            return None
        from .boxing import lens_bbox
        boxes = [bb for bb in (lens_bbox(c) for c in lenses) if bb is not None]
        if not boxes:
            return None
        # With both lenses drawn the datum is the OD lens (smaller boxing-
        # center x, the OMA export's rule), not whichever was drawn first.
        bb = min(boxes, key=lambda b: (b[0] + b[2]) / 2.0)
        return ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)

    def _drill_datum(self):
        """(cx, cy, sx) for drill offsets: the datum lens's boxing center and
        the x sign that puts an offset in the OD lens's frame. A pattern's dx
        is measured on the OD lens (the OMA rule), so an offset taken from or
        placed on a lens drawn right of the axis (the OS side) is mirrored —
        before, a pattern saved on one side landed nasal-for-temporal on a
        frame drawn on the other. Either way +dx points toward the nose."""
        center = self._lens_boxing_center()
        if center is None:
            return None
        cx, cy = center
        front = self._workspaces[0]
        axis_x = front.scene.mirror.x if front.scene.mirror is not None else 0.0
        return cx, cy, (-1.0 if cx > axis_x else 1.0)

    def _place_drill_holes(self, holes, od_frame: bool = True) -> bool:
        """holes: list of (dx, dy, dia), dx in the OD lens's frame (see
        _drill_datum) — or, od_frame=False, as drawn (a version-1 pattern).
        Place DRILL circles relative to the lens boxing center on the front
        workspace; undo-safe + selected."""
        center = self._drill_datum()
        if center is None:
            QMessageBox.information(
                self, "No lens",
                "Draw a LENS shape first — drill holes are placed relative to the "
                "lens boxing center.")
            return False
        cx, cy, sx = center
        if not od_frame:
            sx = 1.0
        self._ws_tab_widget.setCurrentIndex(0)   # holes live on the front
        self._push_undo_snapshot()
        self.scene.clearSelection()
        for dx, dy, dia in holes:
            c = Curve(kind="circle", layer=Layer.DRILL,
                      nodes=[SplineNode(cx + sx * dx, cy + dy)],
                      radius=max(0.05, dia / 2.0), closed=True)
            self._active_ws.add_curve(c).setSelected(True)
        return True

    def _add_drill_hole_from_fields(self):
        # The field reads y-up, as the hint's OMA datum does; the scene is
        # y-down. Typed as-is, a lab's "3 mm above" landed 3 mm below.
        if self._place_drill_holes([(self._drill_x.value(), -self._drill_y.value(),
                                     self._drill_dia.value())]):
            self._status.showMessage(
                f"Placed a {self._drill_dia.value():.2f} mm hole at "
                f"({self._drill_x.value():.2f}, {self._drill_y.value():.2f}) "
                "from the lens center.")

    def _current_drill_holes_relative(self):
        """Front DRILL circles → [(dx, dy, dia)] offsets from the boxing
        center, dx in the OD lens's frame (see _drill_datum)."""
        center = self._drill_datum()
        if center is None:
            return []
        cx, cy, sx = center
        holes = []
        for c in self._workspaces[0].doc_curves:
            if (c.layer == Layer.DRILL and not c.mirrored
                    and c.kind == "circle" and c.nodes):
                holes.append((sx * (c.nodes[0].x - cx), c.nodes[0].y - cy,
                              2.0 * (c.radius or 0.7)))
        return holes

    def _save_drill_pattern(self):
        holes = self._current_drill_holes_relative()
        if not holes:
            QMessageBox.information(
                self, "No holes",
                "There are no DRILL holes on the front workspace to save.")
            return
        name, ok = QInputDialog.getText(self, "Save Drill Pattern",
                                        "Name for this hole pattern:")
        if not ok or not name.strip():
            return
        from .library import DrillLibrary
        DrillLibrary().save_entry(
            name.strip(),
            [{"dx": h[0], "dy": h[1], "dia": h[2]} for h in holes])
        self._refresh_drill_library_panel()
        self._status.showMessage(
            f"Saved drill pattern '{name.strip()}' ({len(holes)} hole(s)).")

    def _import_drill_pattern(self):
        item = self._drill_list.currentItem()
        if item is None:
            return
        from .library import DrillLibrary
        try:
            holes = DrillLibrary().load_entry(item.data(Qt.ItemDataRole.UserRole))
        except Exception as exc:        # a damaged pattern file did nothing, silently
            QMessageBox.warning(self, "Import failed",
                                f"The pattern could not be read.\n\n{exc}")
            return
        if holes and self._place_drill_holes(
                [(h["dx"], h["dy"], h["dia"]) for h in holes],
                od_frame=all(h.get("od_frame", True) for h in holes)):
            self._status.showMessage(
                f"Imported {len(holes)} hole(s) from "
                f"'{item.text().split('  ·')[0]}'.")

    def _refresh_drill_library_panel(self):
        from .library import DrillLibrary
        self._drill_list.clear()
        for e in DrillLibrary().list_entries():
            it = QListWidgetItem(f"{e['name']}  ·  {e['date']}")
            it.setData(Qt.ItemDataRole.UserRole, e["path"])
            self._drill_list.addItem(it)
        self._on_drill_selection_changed()

    def _on_drill_selection_changed(self):
        has = self._drill_list.currentItem() is not None
        self._btn_drill_import.setEnabled(has)
        self._btn_drill_rename.setEnabled(has)
        self._btn_drill_delete.setEnabled(has)

    def _rename_drill_pattern(self):
        item = self._drill_list.currentItem()
        if item is None:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename Pattern", "New name:",
            text=item.text().split("  ·")[0])
        if not ok or not new_name.strip():
            return
        from .library import DrillLibrary
        try:
            DrillLibrary().rename_entry(item.data(Qt.ItemDataRole.UserRole),
                                        new_name.strip())
        except ValueError as e:
            QMessageBox.warning(self, "Rename failed", str(e))
            return
        self._refresh_drill_library_panel()

    def _delete_drill_pattern(self):
        item = self._drill_list.currentItem()
        if item is None:
            return
        if QMessageBox.question(
                self, "Delete Pattern",
                f"Delete '{item.text().split('  ·')[0]}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            from .library import DrillLibrary
            DrillLibrary().delete_entry(item.data(Qt.ItemDataRole.UserRole))
            self._refresh_drill_library_panel()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def _start_calibration(self):
        self.view.setFocus()
        self._calib_tool.start(self.scene)

    def _apply_calibration(self, px_per_mm: float):
        """Scale the face image so px_per_mm image pixels = 1 scene mm."""
        self._image_px_per_mm = px_per_mm
        self.scene.set_face_calibration(px_per_mm)
        self._mark_dirty()   # calibration is persisted in the file
        self._pxmm_spin.blockSignals(True)
        self._pxmm_spin.setValue(px_per_mm)
        self._pxmm_spin.blockSignals(False)
        self._calib_label.setText(f"{px_per_mm:.4f} img-px/mm")
        self._status.showMessage(
            f"Face image calibrated: {px_per_mm:.4f} image pixels per mm"
        )

    def _apply_manual_calib(self):
        v = self._pxmm_spin.value()
        current = self._image_px_per_mm
        # editingFinished fires on a mere click away. Apply a change only:
        # leaving an uncalibrated photo's untouched 1.0 placeholder applied
        # 1 px/mm — a 3000 px photo became 3 m wide — and marked the design
        # changed.
        if v <= 0 or (current and abs(v - current) < 1e-9) \
                or (not current and v == 1.0):
            return
        self._apply_calibration(v)

    # ------------------------------------------------------------------
    # Dirty flag / window title
    # ------------------------------------------------------------------

    def _update_title(self):
        name = (os.path.basename(self._current_path)
                if self._current_path else "Untitled")
        star = "*" if self._dirty else ""
        self.setWindowTitle(f"GuildDraw {__version__} — {name}{star}")

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _clear_dirty(self):
        if self._dirty:
            self._dirty = False
        self._update_title()

    def _confirm_discard(self) -> bool:
        """If there are unsaved changes, offer Save / Discard / Cancel.

        Returns True when it is safe to proceed (saved, discarded, or clean).
        """
        if not self._dirty:
            return True
        r = QMessageBox.warning(
            self, "Unsaved changes",
            "This document has unsaved changes.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            self._save()
            if self._dirty and self._current_path \
                    and not self._current_path.lower().endswith(".gdraw") \
                    and self._other_workspaces_in_use():
                # "Save Front Only" into a .svg: the rest is still unsaved, so
                # stay open — and say why, or the window just refuses to close.
                QMessageBox.information(
                    self, "Not closed",
                    "Only the Frame Front was saved. Unsaved work remains in "
                    f"{', '.join(self._other_workspaces_in_use())}: save as a "
                    ".gdraw project to keep it, or close again and choose "
                    "Discard.")
            return not self._dirty   # False if the save dialog was canceled
        return True   # Discard

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self._prefs["main_window_geometry"] = bytes(
            self.saveGeometry().toBase64()).decode()
        _prefs_mod.save(self._prefs)
        # The app-wide filters go with the window. Left installed, a closed
        # window's two filters kept running on every event the app delivers —
        # one stylesheet pass is ~12,000 of them — and a test session's
        # closed windows piled them up until each new window took seconds.
        app = QApplication.instance()
        app.removeEventFilter(self._tooltip_filter)
        app.removeEventFilter(self)
        self._clear_autosave()
        for lock in [getattr(self, "_autosave_lock", None),
                     *getattr(self, "_orphan_locks", {}).values()]:
            if lock is not None:
                lock.unlock()
        # Teardown: destroying a scene deletes its items, and deleting a
        # selected item emits selectionChanged — into slots that would call
        # back into the half-destroyed scene (shiboken RuntimeError on quit).
        # Sever every selectionChanged connection (ours + each EditTool's)
        # now that no further UI updates can matter.
        for ws in self._workspaces:
            try:
                ws.scene.selectionChanged.disconnect()
            except RuntimeError:
                pass   # already disconnected / already gone
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Autosave + crash recovery
    # ------------------------------------------------------------------

    _AUTOSAVE_MS  = 180_000   # 3 minutes
    _AUTOSAVE_DIR = Path.home() / ".guilddraw" / "autosave"

    # One recovery slot per running copy, "recovery-<pid>-<token>" (the token
    # so a crashed copy whose pid comes round again is never taken for this
    # one), owned through a QLockFile held while that copy runs. A slot whose lock can be taken
    # belongs to a copy that is gone — a crash's work, offered at startup.
    # Until 1.3 every copy shared one "recovery.gdraw": a second launch
    # offered the first copy's live work, and answering No deleted it.
    # (That legacy name is still offered once, as an orphan.)

    def _autosave_paths(self) -> tuple[Path, Path]:
        token = getattr(self, "_autosave_token", None)
        if token is None:
            token = self._autosave_token = uuid.uuid4().hex[:8]
        slot = self._AUTOSAVE_DIR / f"recovery-{os.getpid()}-{token}"
        return slot.with_suffix(".gdraw"), slot.with_suffix(".json")

    def _hold_autosave_slot(self) -> bool:
        """Take (once) the lock that marks this copy's slot as live."""
        lock = getattr(self, "_autosave_lock", None)
        if lock is None:
            from PySide6.QtCore import QLockFile
            self._AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
            rec, _meta = self._autosave_paths()
            lock = QLockFile(str(rec.with_suffix(".lock")))
            lock.setStaleLockTime(0)          # stale only when the owner is gone
            self._autosave_lock = lock
        return lock.isLocked() or lock.tryLock(0)

    def _orphan_slots(self) -> list[Path]:
        """Recovery files left by copies that are no longer running, newest
        first. Taking an orphan's lock keeps a second copy starting now from
        offering the same work; it is let go with the slot (_remove_slot)."""
        try:
            found = [p for p in self._AUTOSAVE_DIR.glob("recovery*.gdraw")
                     if p != self._autosave_paths()[0]]
        except OSError:
            return []
        from PySide6.QtCore import QLockFile
        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0
        self._sweep_leftover_locks()
        out = []
        for rec in sorted(found, key=_mtime, reverse=True):
            lock = QLockFile(str(rec.with_suffix(".lock")))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0) and lock.getLockInfo()[0] == 0 \
                    and _mtime(rec) < time.time() - 2 * self._AUTOSAVE_MS / 1000:
                # A lock cut short by a crash or a power cut names no owner, so
                # Qt can never call it stale. Its slot has not been written in
                # two autosave periods: nobody owns it.
                rec.with_suffix(".lock").unlink(missing_ok=True)
                lock.tryLock(0)
            if lock.isLocked():               # its owner is gone (or never locked)
                self._orphan_locks = {**getattr(self, "_orphan_locks", {}),
                                      rec: lock}
                out.append(rec)
        return out

    def _sweep_leftover_locks(self):
        """Delete the lock files of slots that no longer exist — a copy that
        crashed after a save, New or Open (which empty its slot) left one."""
        from PySide6.QtCore import QLockFile
        own = self._autosave_paths()[0].with_suffix(".lock")
        try:
            leftovers = [p for p in self._AUTOSAVE_DIR.glob("recovery*.lock")
                         if p != own and not p.with_suffix(".gdraw").exists()]
        except OSError:
            return
        for path in leftovers:
            lock = QLockFile(str(path))
            lock.setStaleLockTime(0)
            if lock.tryLock(0):               # stale: taking and letting go removes it
                lock.unlock()
            elif lock.getLockInfo()[0] == 0:
                # Unreadable (cut short by a crash). A minute old, it is not a
                # lock another copy is writing this instant.
                try:
                    if path.stat().st_mtime < time.time() - 60:
                        path.unlink()
                except OSError:
                    pass

    def _release_orphan(self, rec: Path):
        """Let go of an orphan's lock and leave its files for the next launch."""
        lock = getattr(self, "_orphan_locks", {}).pop(rec, None)
        if lock is not None:
            lock.unlock()

    def _remove_slot(self, rec: Path):
        for p in (rec, rec.with_suffix(".json"), rec.with_name(rec.name + ".tmp")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        lock = getattr(self, "_orphan_locks", {}).pop(rec, None)
        if lock is not None:
            lock.unlock()                     # removes the orphan's lock file

    def _do_autosave(self):
        """Timer tick: snapshot dirty work to the recovery slot.

        Must never interrupt the user — failures are silent; success shows a
        brief status note.
        """
        if not self._dirty:
            return
        rec, meta = self._autosave_paths()
        try:
            if not self._hold_autosave_slot():
                return
            tmp = str(rec) + ".tmp"
            self._do_save_gdraw(tmp)
            os.replace(tmp, rec)
            meta.write_text(json.dumps({
                "source_path": self._current_path,
                "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }), encoding="utf-8")
            # A brief note that hands the bar back: shown bare, it wiped the
            # active tool's instructions every three minutes.
            covered = self._status.currentMessage()
            self._status.showMessage("Autosaved", 2000)
            if covered:
                self._autosave_covered = covered
                QTimer.singleShot(2100, self, self._restore_after_autosave_note)
        except Exception:
            pass

    def _restore_after_autosave_note(self):
        msg, self._autosave_covered = getattr(self, "_autosave_covered", ""), ""
        if msg and not self._status.currentMessage():
            self._status.showMessage(msg)

    def _clear_autosave(self):
        """Empty this copy's own slot (after a save, New, Open or a clean
        close). Other copies' slots are never touched here."""
        self._remove_slot(self._autosave_paths()[0])

    def _offer_recovery(self, opening: str | None = None) -> bool:
        """On startup: offer to restore work a crashed copy left behind.
        Runs once. `opening` is a file named on the command line, which is
        opened only when the maker declines. Returns True when work was
        restored."""
        if getattr(self, "_recovery_offered", False):
            return False
        self._recovery_offered = True
        for rec in self._orphan_slots():
            if self._offer_one_recovery(rec, opening):
                return True
        return False

    def _ask_recovery(self, text: str, detail: str) -> str:
        """"restore", "later" (also Esc and the window's close box: the safe
        answer) or "discard"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Recover unsaved work?")
        box.setText(text)
        box.setInformativeText(detail)
        restore = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(restore)
        box.setEscapeButton(later)
        _run_modal(box)
        clicked = box.clickedButton()
        return ("restore" if clicked is restore
                else "discard" if clicked is discard else "later")

    def _offer_one_recovery(self, rec: Path, opening: str | None) -> bool:
        meta = rec.with_suffix(".json")
        source = None
        when   = "an unknown time"
        try:
            info   = json.loads(meta.read_text(encoding="utf-8"))
            source = info.get("source_path")
            when   = info.get("saved_at", when)
        except Exception:
            pass
        name = os.path.basename(source) if source else "an unsaved document"
        try:    # "2026-09-27T10:33:12" → "2026-09-27 at 10:33"
            when = datetime.datetime.fromisoformat(when).strftime("%Y-%m-%d at %H:%M")
        except (TypeError, ValueError):
            pass
        text = f"GuildDraw found autosaved work from {when}\n({name})."
        later = "Later keeps it and asks again next time."
        if opening:
            # A file was double-clicked: say what happens to it, and never
            # steer toward the answer that throws the recovered work away.
            later = (f"Later opens {os.path.basename(opening)} now, and keeps "
                     "the autosaved work to ask about next time.")
        choice = self._ask_recovery(
            text, f"Restore it? {later} Discard deletes it.")
        if choice == "later":
            self._release_orphan(rec)
            return False
        if choice != "restore":
            self._remove_slot(rec)
            return False
        status = self._open_gdraw(str(rec), remember=False)
        if status is None:
            # Unreadable: keep it for manual salvage under another name so
            # the next launch does not ask (and fail) again.
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                rec.rename(rec.with_name(f"failed-{stamp}.gdraw.bak"))
            except OSError:
                pass
            self._remove_slot(rec)
            self._status.showMessage(
                f"Recovery file could not be read — kept as failed-{stamp}.gdraw.bak")
            return False
        if status == "ok":
            # The recovered content belongs to the original document, not
            # the recovery file: restore the real path and mark it unsaved.
            self._current_path = (source if source and os.path.isfile(source)
                                  else None)
        # ("errors": _open_gdraw already dropped the path so Save asks for a
        # new name — a half-recovered file must never overwrite the original.)
        self._mark_dirty()
        self._update_title()
        # The work is in this copy now: write it to this copy's own slot
        # before letting the dead copy's go, so a second crash loses nothing.
        self._do_autosave()
        if self._autosave_paths()[0].exists():
            self._remove_slot(rec)
        # Say what happened in the maker's words; _open_gdraw's own message
        # named the internal slot file.
        self._status.showMessage(
            f"Restored autosaved work from {when}"
            + (f"; {os.path.basename(opening)} was not opened" if opening else ""))
        return True

    # ------------------------------------------------------------------
    # Recent files
    # ------------------------------------------------------------------

    _MAX_RECENT = 8

    def _add_recent(self, path: str):
        path = os.path.abspath(path)
        self._recent_files = ([path]
                              + [p for p in self._recent_files if p != path])
        del self._recent_files[self._MAX_RECENT:]
        self._prefs["recent_files"] = list(self._recent_files)
        _prefs_mod.save(self._prefs)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        m = self._recent_menu
        m.clear()
        if not self._recent_files:
            empty = m.addAction("(empty)")
            empty.setEnabled(False)
            return
        for p in self._recent_files:
            act = m.addAction(os.path.basename(p),
                              lambda checked=False, p=p: self._open_recent(p))
            act.setToolTip(p)
        m.addSeparator()
        m.addAction("Clear Recent", self._clear_recent)

    def _clear_recent(self):
        self._recent_files = []
        self._prefs["recent_files"] = []
        _prefs_mod.save(self._prefs)
        self._rebuild_recent_menu()

    def _open_recent(self, path: str):
        if not os.path.isfile(path):
            QMessageBox.warning(self, "File not found",
                                f"{path}\n\nno longer exists.")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._prefs["recent_files"] = list(self._recent_files)
            _prefs_mod.save(self._prefs)
            self._rebuild_recent_menu()
            return
        if not self._confirm_discard():
            return
        self._open_path(path)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _add_face(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add Reference Image", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not path:
            return
        idx = self.scene.add_face(path)
        if idx is not None:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._face_list.addItem(item)
            self._face_list.setCurrentRow(idx)
            if idx == 0:
                self.view.fit_view(self.scene.sceneRect())
            self._mark_dirty()
            self._status.showMessage(f"Loaded: {os.path.basename(path)}")
        else:
            self._status.showMessage(f"Failed to load image: {path}")

    def _remove_face(self):
        idx = self._face_list.currentRow()
        if idx < 0:
            return
        self.scene.remove_face(idx)
        self._face_list.takeItem(idx)
        self._mark_dirty()
        count = self._face_list.count()
        if count > 0:
            self._face_list.setCurrentRow(min(idx, count - 1))
        else:
            self._selected_face_idx = -1
            self._remove_img_btn.setEnabled(False)
            self._opacity_slider.setEnabled(False)
            self._rotation_spin.setEnabled(False)
            self._canvas_lock_chk.setEnabled(False)

    def _on_face_list_selection_changed(self, row: int):
        self._selected_face_idx = row
        has_sel = (row >= 0)
        self._remove_img_btn.setEnabled(has_sel)
        self._opacity_slider.setEnabled(has_sel)
        self._rotation_spin.setEnabled(has_sel)
        self._canvas_lock_chk.setEnabled(has_sel)
        if has_sel:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(int(self.scene.face_opacity(row) * 100))
            self._opacity_slider.blockSignals(False)
            self._rotation_spin.blockSignals(True)
            self._rotation_spin.setValue(self.scene.face_rotation(row))
            self._rotation_spin.blockSignals(False)
            self._canvas_lock_chk.blockSignals(True)
            self._canvas_lock_chk.setChecked(self.scene.face_is_locked(row))
            self._canvas_lock_chk.blockSignals(False)

    def _on_face_opacity_changed(self, v: int):
        if self._selected_face_idx >= 0:
            self.scene.set_face_opacity(self._selected_face_idx, v / 100)
            self._mark_dirty()

    def _on_face_rotation_changed(self, v: float):
        if self._selected_face_idx >= 0:
            self.scene.set_face_rotation(self._selected_face_idx, v)
            self._mark_dirty()

    def _on_canvas_lock_toggled(self, locked: bool):
        if self._selected_face_idx >= 0:
            self.scene.set_canvas_locked(self._selected_face_idx, locked)

    # ------------------------------------------------------------------
    # New / Open / Save (SVG as native format)
    # ------------------------------------------------------------------

    def _settle_before_replacing_document(self):
        """Before New or Open swaps the document: end any tool mid-operation
        (a half-drawn Line carried its nodes into the next document, and the
        next click continued it) and flush the panel into the active
        workspace as a tab switch does — the restore that follows otherwise
        reverted the edits made since the last switch, some fields and not
        others."""
        self._act_select.setChecked(True)
        self._set_tool_select()
        self._save_ws_sidebar_state(self._active_ws)

    def _new(self):
        if not self._confirm_discard():
            return
        self._settle_before_replacing_document()
        for ws in self._workspaces:
            ws.clear_document()
            ws.bookmarks.clear()
            ws.scene.clear_faces()
            ws.face_image_paths.clear()
            ws.selected_face_idx = -1
            ws.image_px_per_mm = None        # calibration belongs to the document
            # (snap/lock/bevel/forming state: reset by clear_document)
            ws.fill_visible = False          # fill resets with the document
            ws.fill_color   = "#2a6099"
            ws.fill_opacity = 0.50
            ws.fill_style   = "color"
            ws.fill_image   = ""
            ws.scene.set_fill_color(QColor(ws.fill_color))
            ws.scene.set_fill_opacity(ws.fill_opacity)
            ws.scene.clear_fill_image()
            ws.scene.set_fill_visible(False)
            ws.lens_fill_visible = False
            ws.lens_fill_top     = DEFAULT_LENS_FILL_TOP
            ws.lens_fill_bottom  = DEFAULT_LENS_FILL_BOTTOM
            ws.lens_fill_linked  = False
            ws.lens_fill_opacity = self._default_lens_fill_opacity()
            ws.lens_fill_intensity = self._default_lens_fill_intensity()
            ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
            ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
            ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
            ws.scene.set_lens_fill_visible(False)
        self._restore_ws_sidebar_state(self._active_ws)
        # Refresh sidebar for the currently visible workspace
        self._face_list.clear()
        self._remove_img_btn.setEnabled(False)
        self._opacity_slider.setEnabled(False)
        self._rotation_spin.setEnabled(False)
        self._canvas_lock_chk.setEnabled(False)
        self._refresh_timeline_list()
        self._update_undo_actions()
        self._current_path = None
        self._clear_autosave()
        self._clear_dirty()
        self._update_info_label()      # the layer shown was the old document's
        self._status.showMessage("New document")

    def _open(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GuildDraw File", "",
            "GuildDraw Files (*.gdraw *.svg);;GuildDraw Project (*.gdraw);;SVG Files (*.svg)"
        )
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path: str):
        """Dispatch an open by extension. Caller handles the discard prompt."""
        if path.lower().endswith(".gdraw"):
            self._open_gdraw(path)
        else:
            self._open_svg(path)

    def _open_svg(self, path: str):
        """Load a single .svg into the active (Front) workspace."""
        try:
            from .export.svg import (load_svg, resolve_face_images,
                                     resolve_fill_image)
            data = load_svg(path)
            resolve_face_images(data.get("face_images", []), path)
            resolve_fill_image(data.get("fill"), path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        self._settle_before_replacing_document()
        # A plain .svg is a single-workspace document: the temples and hinge
        # start empty, or the previous project's would ride along into the
        # next save.
        for ws in self._workspaces[1:]:
            ws.clear_document()
            ws.bookmarks.clear()
            ws.scene.clear_faces()
            ws.face_image_paths.clear()
            ws.selected_face_idx = -1
            ws.image_px_per_mm = None
        self._load_ws_data(self._workspaces[0], data)
        # Switch to Front tab
        self._loading = True
        try:
            self._ws_tab_widget.setCurrentIndex(0)
        finally:
            self._loading = False
        # Pull the loaded state into the sidebar. The tab change above does
        # this via _on_workspace_changed — but only when the index actually
        # moves, so opening a file while already on Front left the widgets
        # (fill tick, tint colors, guide sizes) showing the previous document.
        self._restore_ws_sidebar_state(self._active_ws)
        self._current_path = path
        self._clear_dirty()
        self._clear_autosave()      # the recovery slot held the previous document
        self._add_recent(path)
        self.view.fit_view(self.scene.sceneRect())
        bm = self._workspaces[0].bookmarks
        self._status.showMessage(
            f"Opened: {os.path.basename(path)}"
            + (f"  ·  {len(bm)} bookmark(s)" if bm else "")
        )

    def _open_gdraw(self, path: str, remember: bool = True) -> str | None:
        """Load a .gdraw ZIP into all four workspaces.

        Returns "ok", "errors" (some tabs loaded empty; the path was NOT
        kept, so Save asks for a new name) or None (nothing was loaded)."""
        try:
            from .export.gdraw import load_gdraw
            all_data = load_gdraw(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return None
        self._settle_before_replacing_document()
        tab_names = ["front", "temple_r", "temple_l", "hinge"]
        for ws, tab in zip(self._workspaces, tab_names, strict=True):
            self._load_ws_data(ws, all_data[tab])
        # Switch to the active tab stored in the file
        active = all_data.get("active_tab", "front")
        target_idx = tab_names.index(active) if active in tab_names else 0
        self._loading = True
        try:
            self._ws_tab_widget.setCurrentIndex(target_idx)
        finally:
            self._loading = False
        # See _open_svg: a no-op tab change fires no restore of its own.
        self._restore_ws_sidebar_state(self._active_ws)
        self.view.fit_view(self.scene.sceneRect())

        errors = all_data.get("errors") or []
        if errors:
            # A corrupt tab loaded empty: do NOT keep the path — Save would
            # overwrite the original file with that empty content. Force
            # Save As and flag the document as unsaved.
            QMessageBox.warning(
                self, "Some workspaces failed to load",
                "These workspaces could not be read and were loaded empty:\n\n"
                + "\n".join(f"• {e}" for e in errors)
                + "\n\nThe original file will not be touched — saving will "
                  "ask for a new file name (Save As).")
            self._current_path = None
            self._dirty = True
            self._update_title()
            self._status.showMessage(
                f"Opened with errors: {os.path.basename(path)}")
            return "errors"

        self._current_path = path
        self._clear_dirty()
        if remember:
            self._add_recent(path)
            self._clear_autosave()  # the recovery slot held the previous document
        self._status.showMessage(f"Opened: {os.path.basename(path)}")
        return "ok"

    def _load_ws_data(self, ws: "WorkspaceState", data: dict):
        """Populate a WorkspaceState from a load_svg result dict.  Clears first."""
        ws.clear_document()

        # Apply layer visibility/locks BEFORE adding curves so each new item
        # picks up its layer state on creation.
        for lname, flags in (data.get("layers") or {}).items():
            try:
                layer = Layer(lname)
            except ValueError:
                continue   # unknown layer name from a future version
            ws.scene.set_layer_visible(layer, flags.get("visible", True))
            ws.scene.set_layer_locked(layer, flags.get("locked", False))

        # Mirror ghost state is saved per workspace — restore it (before the
        # curves are added, so ghosts aren't built and immediately removed).
        mir = data.get("mirror")
        if mir is not None:
            ws.mirror_enabled = bool(getattr(mir, "enabled", True))
            horizontal = ws.workspace_type in ("temple_r", "temple_l")
            if ws.scene.mirror:
                ws.scene.mirror.set_enabled(ws.mirror_enabled)
            ws.scene.set_mirror_display(ws.mirror_enabled)
            ws.snap.set_mirror(0.0, ws.mirror_enabled, horizontal=horizontal)
            ws.boxing_guide.set_mirror(ws.mirror_enabled)
            if ws is self._active_ws:
                self._act_mirror.blockSignals(True)
                self._act_mirror.setChecked(ws.mirror_enabled)
                self._act_mirror.blockSignals(False)

        for curve in data.get("curves", []):
            ws.add_curve(curve)

        frm = data.get("forming", FormingMetadata())
        ws.bridge_angle  = frm.bridge_angle_deg
        ws.apical_radius = frm.apical_radius_mm

        bevel = data.get("bevel")
        if bevel is not None:
            ws.bevel_preset = bevel.preset
            ws.bevel_depth  = bevel.depth_mm
            ws.boxing_guide.set_bevel_depth(ws.bevel_depth)

        ws.scene.clear_faces()
        ws.face_image_paths.clear()
        ws.selected_face_idx = -1
        face_images_data = data.get("face_images", [])
        for fi in face_images_data:
            if fi.path and os.path.isfile(fi.path):
                idx = ws.scene.add_face(fi.path)
                if idx is not None:
                    ws.face_image_paths.append(fi.path)
                    ws.scene.set_face_opacity(idx, fi.opacity)
                    ws.scene.set_face_rotation(idx, fi.rotation)

        cal = data.get("calibration", Calibration())
        if cal.is_set:
            ws.image_px_per_mm = cal.px_per_mm
            if ws is self._active_ws:
                self._apply_calibration(cal.px_per_mm)
            else:
                ws.scene.set_face_calibration(cal.px_per_mm)

        visible_idx = 0
        for fi in face_images_data:
            if fi.path and os.path.isfile(fi.path):
                if fi.tx != 0.0 or fi.ty != 0.0:
                    item = ws.scene.get_face_item(visible_idx)
                    if item is not None:
                        item.setPos(fi.tx, fi.ty)
                visible_idx += 1

        for dim in data.get("dims", []):
            ws.add_dim(dim)

        for tobj in data.get("texts", []):
            ws.add_text(tobj)

        ws.bookmarks = list(data.get("bookmarks", []))

        fill = data.get("fill") or {}
        ws.fill_visible = bool(fill.get("visible", False))
        ws.fill_color   = _hex_or(fill.get("color"), "#2a6099")
        ws.fill_opacity = _num_or(fill.get("opacity"), 0.50, 0.0, 1.0)
        # Absent in pre-1.2 files, and any unknown style from a future version
        # degrades to the color rather than blanking the fill.
        img = fill.get("image")
        ws.fill_image = img if isinstance(img, str) else ""
        ws.fill_style = "image" if fill.get("style") == "image" else "color"
        ws.scene.set_fill_color(QColor(ws.fill_color))
        ws.scene.set_fill_opacity(ws.fill_opacity)
        if not self._apply_fill_material(ws):
            self._fill_image_missing(ws)
        if ws.scene.set_fill_visible(ws.fill_visible) != "ok":
            ws.fill_visible = False   # a saved fill-on that no longer encloses

        # Lens fill. Absent in pre-1.2 files: the tint stays off at the shipped
        # colors, with the opacity the maker prefers for a fresh tint.
        lens_fill = data.get("lens_fill") or {}
        ws.lens_fill_visible = bool(lens_fill.get("visible", False))
        ws.lens_fill_top     = _hex_or(lens_fill.get("top"),
                                       DEFAULT_LENS_FILL_TOP)
        ws.lens_fill_bottom  = _hex_or(lens_fill.get("bottom"),
                                       DEFAULT_LENS_FILL_BOTTOM)
        ws.lens_fill_linked  = bool(lens_fill.get("linked", False))
        ws.lens_fill_opacity = _num_or(
            lens_fill.get("opacity"), self._default_lens_fill_opacity(), 0.0, 1.0)
        ws.lens_fill_intensity = _num_or(
            lens_fill.get("intensity"), self._default_lens_fill_intensity(),
            LENS_FILL_INTENSITY_MIN, LENS_FILL_INTENSITY_MAX)
        ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
        ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
        if ws.scene.set_lens_fill_visible(ws.lens_fill_visible) != "ok":
            ws.lens_fill_visible = False

        # If this is the active workspace, sync sidebar widgets
        if ws is self._active_ws:
            self._bridge_angle_spin.blockSignals(True)
            self._bridge_angle_spin.setValue(ws.bridge_angle)
            self._bridge_angle_spin.blockSignals(False)
            self._apical_spin.blockSignals(True)
            self._apical_spin.setValue(ws.apical_radius)
            self._apical_spin.blockSignals(False)
            self._face_list.clear()
            for p in ws.face_image_paths:
                item = QListWidgetItem(os.path.basename(p))
                item.setData(Qt.ItemDataRole.UserRole, p)
                self._face_list.addItem(item)
            if ws.scene.face_count() > 0:
                self._face_list.setCurrentRow(0)
            self._refresh_timeline_list()
            self._update_undo_actions()

    def _save(self):
        if not hasattr(self, "_current_path") or not self._current_path:
            self._save_as()
        else:
            self._do_save(self._current_path)

    def _save_as(self, start: str | None = None):
        # Untitled project: suggest the frame-size notation (49□27.gdraw) so
        # the □ is in the filename without typing it — the native Windows
        # dialog can't receive the insert-□ application shortcut.
        start = start or getattr(self, "_current_path", "") or ""
        if not start:
            size = self._size_string()
            if size:
                start = f"{size}.gdraw"
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save GuildDraw File", start,
            "GuildDraw Project (*.gdraw);;SVG Files (*.svg)"
        )
        if not path:
            return
        if not path.lower().endswith((".gdraw", ".svg")):
            # Non-native dialogs hand back exactly what was typed; a bare
            # name used to fall through to the single-workspace SVG writer.
            path += ".svg" if "svg" in chosen.lower() else ".gdraw"
        # _do_save takes the path on success only: set before it, a failed
        # Save As left every later Ctrl+S aimed at the file that failed.
        self._do_save(path)

    def _size_string(self) -> str | None:
        """Frame-size notation ``A□DBL`` from the front workspace's finished
        boxing dims, e.g. ``"49□27"``; None when no lens is drawn.

        Same measurement basis as _refresh_measurements (sampled union_bbox,
        finished A/DBL grown/narrowed by the bevel) — keep them in step."""
        front = next((w for w in self._workspaces
                      if w.workspace_type == "front"), None)
        if front is None:
            return None
        from .boxing import finished_ab, finished_dbl, union_bbox
        mirror_x = getattr(front.scene.mirror, "_x", 0.0) \
            if front.scene.mirror else 0.0
        os_c, od_c = [], []
        for c in front.doc_curves:
            if c.layer != Layer.LENS or not c.nodes:
                continue
            cx = sum(n.x for n in c.nodes) / len(c.nodes)
            if cx > mirror_x:
                os_c.append(c)
            elif cx < mirror_x:
                od_c.append(c)
        os_lb = union_bbox(os_c) if os_c else None
        od_lb = union_bbox(od_c) if od_c else None
        lb = od_lb or os_lb
        if lb is None:
            return None
        a = lb[2] - lb[0]
        b = lb[3] - lb[1]
        if os_lb and od_lb:
            dbl = os_lb[0] - od_lb[2]
        elif os_lb:
            dbl = 2.0 * (os_lb[0] - mirror_x)
        else:
            dbl = 2.0 * (mirror_x - od_lb[2])
        bevel_d = max(0.0, front.bevel_depth)
        if bevel_d > 0:
            a, _b = finished_ab(a, b, bevel_d)
            dbl   = finished_dbl(dbl, bevel_d)
        if dbl <= 0:
            return None
        return f"{a:.0f}□{dbl:.0f}"

    def _other_workspaces_in_use(self) -> list[str]:
        """Tab names of the non-front workspaces holding anything a .svg
        cannot carry (it is the Frame Front alone)."""
        return [self._ws_tab_widget.tabText(i)
                for i, ws in enumerate(self._workspaces)
                if ws.workspace_type != "front"
                and (ws.doc_curves or ws.doc_dims or ws.doc_texts
                     or ws.face_image_paths or ws.bookmarks)]

    def _ask_svg_scope(self, path: str, others: list[str]) -> str:
        """A .svg holds the Frame Front alone: "gdraw" (Save As a project),
        "front" (write the front anyway) or "cancel"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Save as .svg?")
        box.setText(f"{os.path.basename(path)} can hold only the Frame Front. "
                    f"{', '.join(others)} would not be saved.")
        box.setInformativeText("Save the whole design as a .gdraw project instead?")
        as_gdraw = box.addButton("Save as .gdraw…", QMessageBox.ButtonRole.AcceptRole)
        front = box.addButton("Save Front Only", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(as_gdraw)
        _run_modal(box)
        clicked = box.clickedButton()
        return ("gdraw" if clicked is as_gdraw
                else "front" if clicked is front else "cancel")

    def _do_save(self, path: str) -> bool:
        """Atomic save: write a temp file, keep the previous version as .bak,
        then replace. A failure mid-write can never destroy the existing file.
        Returns True when the file was written; on success `path` becomes the
        document's path."""
        front_only = False
        if not path.lower().endswith(".gdraw"):
            others = self._other_workspaces_in_use()
            if others:
                # Ctrl+S on a legacy .svg used to write the front, clear the
                # star and drop the temple and hinge work without a word.
                choice = self._ask_svg_scope(path, others)
                if choice == "gdraw":
                    self._save_as(start=os.path.splitext(path)[0] + ".gdraw")
                    return False
                if choice != "front":
                    return False
                front_only = True
        tmp = path + ".tmp"
        try:
            if path.lower().endswith(".gdraw"):
                self._do_save_gdraw(tmp)
            else:
                self._do_save_svg(tmp)
            if os.path.exists(path):
                try:
                    os.replace(path, path + ".bak")
                except OSError:
                    pass   # backup is best-effort; the save still proceeds
            os.replace(tmp, path)
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
            QMessageBox.critical(self, "Save failed", str(e))
            return False
        self._current_path = path
        self._add_recent(path)
        if front_only:
            # The temples and hinge are still unsaved: keep the star, the
            # close prompt and the recovery slot.
            self._update_title()
            self._status.showMessage(
                f"Saved the Frame Front to {os.path.basename(path)}; the other "
                "workspaces are not saved. Use Save As .gdraw to keep them.", 10000)
            return True
        self._clear_dirty()
        self._clear_autosave()
        self._status.showMessage(f"Saved: {os.path.basename(path)}")
        return True

    def _ws_to_data_dict(self, ws: "WorkspaceState") -> dict:
        """Build the data dict for save_svg from a WorkspaceState."""
        from .document import WORKSPACE_LAYERS
        return {
            "layers": {
                layer.value: {
                    "visible": ws.scene.is_layer_visible(layer),
                    "locked":  ws.scene.is_layer_locked(layer),
                }
                for layer in WORKSPACE_LAYERS[ws.workspace_type]
            },
            "curves":      ws.doc_curves,
            "dims":        ws.doc_dims,
            "calibration": Calibration(px_per_mm=ws.image_px_per_mm),
            "mirror":      ws.scene.mirror or MirrorAxis(),
            "forming":     FormingMetadata(
                               bridge_angle_deg=ws.bridge_angle,
                               apical_radius_mm=ws.apical_radius,
                           ),
            "machined_bridge": MachinedBridge(),
            "bevel": BevelSpec(preset=ws.bevel_preset, depth_mm=ws.bevel_depth),
            "face_images": [
                FaceImage(
                    path     = ws.face_image_paths[i] if i < len(ws.face_image_paths) else "",
                    tx       = ws.scene.face_scene_pos(i)[0],
                    ty       = ws.scene.face_scene_pos(i)[1],
                    rotation = ws.scene.face_rotation(i),
                    opacity  = ws.scene.face_opacity(i),
                )
                for i in range(ws.scene.face_count())
            ],
            "bookmarks": ws.bookmarks,
            "fill": {
                "visible": ws.fill_visible,
                "color":   ws.fill_color,
                "opacity": ws.fill_opacity,
                "style":   ws.fill_style,
                # Saved even while the color is showing, so switching back to
                # Image after a reload finds the swatch still attached.
                "image":   ws.fill_image,
            },
            "lens_fill": {
                "visible": ws.lens_fill_visible,
                "top":     ws.lens_fill_top,
                "bottom":  ws.lens_fill_bottom,
                "linked":  ws.lens_fill_linked,
                "opacity": ws.lens_fill_opacity,
                "intensity": ws.lens_fill_intensity,
            },
            "texts": ws.doc_texts,
        }

    def _do_save_svg(self, path: str, ws: "WorkspaceState | None" = None):
        """Write one workspace as a plain SVG. Used by File > Save/Save As
        for a .svg document (legacy single-workspace format: always the
        Frame Front, whatever tab is showing — otherwise Ctrl+S from a
        temple tab wrote the temple over front.svg) and by Export > SVG
        (the active workspace)."""
        # First flush sidebar into active ws
        self._save_ws_sidebar_state(self._active_ws)
        from .export.svg import save_svg, portable_face_images, portable_fill
        ws = ws or self._workspaces[0]
        d  = self._ws_to_data_dict(ws)
        save_svg(
            curves          = d["curves"],
            path            = path,
            calibration     = d["calibration"],
            mirror          = d["mirror"],
            forming         = d["forming"],
            machined_bridge = d["machined_bridge"],
            face_images     = portable_face_images(d["face_images"], path),
            bookmarks       = d["bookmarks"],
            dims            = d["dims"],
            layers          = d["layers"],
            fill            = portable_fill(d["fill"], path),
            lens_fill       = d["lens_fill"],
            texts           = d["texts"],
            bevel           = d["bevel"],
        )

    def _do_save_gdraw(self, path: str):
        """Save all three workspaces as a .gdraw ZIP."""
        # Flush sidebar into active workspace before building data dicts
        self._save_ws_sidebar_state(self._active_ws)
        tab_names = ["front", "temple_r", "temple_l", "hinge"]
        from .export.gdraw import save_gdraw
        ws_data = {}
        for ws, tab in zip(self._workspaces, tab_names, strict=True):
            ws_data[tab] = self._ws_to_data_dict(ws)
        active_tab = tab_names[self._ws_tab_widget.currentIndex()]
        save_gdraw(ws_data, path, active_tab=active_tab)

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def _readiness_note(self) -> str:
        """One-line GuildModel-readiness summary for the active workspace, used
        as the status-bar marker after a (never-blocked) DXF export."""
        from .export.validate import validate
        errors, warnings = validate(self._doc_curves, self._act_mirror.isChecked(),
                                    self._active_ws.workspace_type)
        if errors:
            return f"not yet GuildModel-ready ({errors[0]})"
        if warnings:
            return f"ready for GuildModel (with warnings: {warnings[0]})"
        return "ready for GuildModel"

    def _export_dxf(self):
        # DXF export is never blocked on the contract: the maker may want a
        # partial frame, or an unusual multi-lens shape GuildModel will finish.
        # The readiness dot and the status note below report GuildModel-readiness.
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DXF", "", "DXF Files (*.dxf)"
        )
        if not path:
            return
        path = self._ensure_suffix(path, ".dxf")
        try:
            from .export.dxf import export_dxf
            # TextObjects become outline splines on their layer at export
            # time only — the document keeps the editable text.
            curves = list(self._doc_curves)
            if self._active_ws.doc_texts:
                from .textpath import text_to_curves
                for tobj in self._active_ws.doc_texts:
                    curves.extend(text_to_curves(tobj))
            export_dxf(
                curves     = curves,
                path       = path,
                mirror_on  = self._act_mirror.isChecked(),
                axis_x     = self.scene.mirror.x if self.scene.mirror else 0.0,
                horizontal = (self._active_ws.workspace_type
                              in ("temple_r", "temple_l")),
            )
            self._status.showMessage(
                f"DXF exported: {os.path.basename(path)} — {self._readiness_note()}")
        except Exception as e:
            QMessageBox.critical(self, "DXF export failed", str(e))

    def _export_all_dxf(self):
        """File > Export > Export All DXF… — one DXF per populated workspace
        (<base>_front.dxf, _temple_r, _temple_l, _hinge). Export is never
        blocked; the per-workspace validator only annotates which files aren't
        GuildModel-ready yet (reported after the write)."""
        from .export.batch import (
            BatchWorkspace, base_from_path, check_batch, write_batch,
        )
        # Flush sidebar state so the active workspace's mirror toggle is
        # current in ws.mirror_enabled (the other workspaces were flushed
        # when their tabs were left).
        self._save_ws_sidebar_state(self._active_ws)

        items = []
        tab_names = ["front", "temple_r", "temple_l", "hinge"]
        for ws, tab in zip(self._workspaces, tab_names, strict=True):
            curves = [c for c in ws.doc_curves if not c.mirrored]
            if ws.doc_texts:
                from .textpath import text_to_curves
                for tobj in ws.doc_texts:
                    curves.extend(text_to_curves(tobj))
            items.append(BatchWorkspace(
                workspace_type = tab,
                curves         = curves,
                mirror_on      = ws.mirror_enabled,
                axis_x         = ws.scene.mirror.x if ws.scene.mirror else 0.0,
            ))

        if not any(it.curves for it in items):
            QMessageBox.information(self, "Export All DXF",
                                    "All workspaces are empty — nothing to export.")
            return

        ws_titles = {"front": "Frame Front", "temple_r": "Temple R",
                     "temple_l": "Temple L",  "hinge": "Hinge Pocket"}
        # Validation never blocks the batch export — it only annotates which
        # workspaces aren't GuildModel-ready yet (reported after the write).
        report = check_batch(items)

        suggested = ""
        if self._current_path:
            suggested = os.path.splitext(self._current_path)[0] + ".dxf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export All DXF — choose base name", suggested,
            "DXF Files (*.dxf)")
        if not path:
            return
        base = base_from_path(path)
        try:
            written = write_batch(items, base)
        except Exception as e:
            QMessageBox.critical(self, "Batch DXF export failed", str(e))
            return
        names = ", ".join(os.path.basename(p) for p in written)
        msg = f"Exported {len(written)} DXF file(s): {names}"
        if report.skipped:
            msg += " — skipped (empty): " + ", ".join(
                ws_titles[t] for t in report.skipped)
        not_ready = [t for t in ws_titles if t in report.errors]
        if not_ready:
            msg += " — not yet GuildModel-ready: " + ", ".join(
                ws_titles[t] for t in not_ready)
        self._status.showMessage(msg)
        # The file-name preview in the dialog can't show the suffixing, so
        # confirm what actually landed on disk.
        info = "Written:\n" + "\n".join(f"• {os.path.basename(p)}" for p in written)
        if report.skipped:
            info += "\n\nSkipped (empty): " + ", ".join(
                ws_titles[t] for t in report.skipped)
        if not_ready:
            info += "\n\nNot yet GuildModel-ready (exported anyway):"
            for tab in not_ready:
                info += f"\n• {ws_titles[tab]}: {report.errors[tab][0]}"
        QMessageBox.information(self, "Export All DXF", info)

    def _export_svg(self):
        """Export the active workspace as SVG without touching the current
        document path or window title (unlike File > Save)."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", "", "SVG Files (*.svg)"
        )
        if not path:
            return
        path = self._ensure_suffix(path, ".svg")
        try:
            self._do_save_svg(path, self._active_ws)
            self._status.showMessage(f"SVG exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "SVG export failed", str(e))

    _PNG_DPI_CHOICES = [
        ("150 dpi — draft",       150),
        ("300 dpi — print",       300),
        ("600 dpi — high detail", 600),
        ("1200 dpi — maximum",    1200),
    ]

    def _png_content_rect(self) -> QRectF | None:
        """Tight scene-mm bounds for the PNG export: the geometry (same bbox
        rule as the SVG viewBox), its mirror ghost when displayed, the
        engraving text, and any visible face photos. None = no content
        (caller falls back to sceneRect)."""
        from .export.svg import _content_bbox
        from .textpath import text_outline_path
        ws = self._active_ws
        rect = QRectF()
        curves = [c for c in self._doc_curves if c.nodes]
        if curves:
            x0, y0, x1, y1 = _content_bbox(curves)
            rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            if self._act_mirror.isChecked():
                if ws.workspace_type in ("temple_r", "temple_l"):
                    ghost = QRectF(x0, -y1, x1 - x0, y1 - y0)
                else:
                    ax = self.scene.mirror.x if self.scene.mirror else 0.0
                    ghost = QRectF(2 * ax - x1, y0, x1 - x0, y1 - y0)
                rect = rect.united(ghost)
        for t in ws.doc_texts:
            if t.text.strip() and self.scene.is_layer_visible(t.layer):
                rect = rect.united(text_outline_path(t).boundingRect())
        for i in range(self.scene.face_count()):
            item = self.scene.get_face_item(i)
            if item is not None and item.isVisible():
                rect = rect.united(item.sceneBoundingRect())
        return rect if not rect.isEmpty() else None

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", "", "PNG Files (*.png)"
        )
        if not path:
            return
        # Some file dialogs hand back exactly what was typed. Without the
        # suffix the raster lands somewhere the maker won't find it (and used
        # to not land at all), so add it here rather than trust the dialog.
        if not path.lower().endswith(".png"):
            path += ".png"
        labels = [lbl for lbl, _dpi in self._PNG_DPI_CHOICES]
        dpis   = [dpi for _lbl, dpi in self._PNG_DPI_CHOICES]
        last   = self._prefs.get("png_export_dpi", 600)
        idx    = dpis.index(last) if last in dpis else 2
        choice, ok = QInputDialog.getItem(
            self, "Export PNG",
            "Resolution (scene mm rendered at true print scale):",
            labels, idx, False)
        if not ok:
            return
        dpi = dpis[labels.index(choice)]
        if dpi != last:
            self._prefs["png_export_dpi"] = dpi
            self._save_prefs()
        try:
            from .export.png import render_png
            render_png(self.scene, path, dpi=dpi,
                       rect=self._png_content_rect(),
                       background=theme.color("canvas.bg"))
            self._status.showMessage(f"PNG exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "PNG export failed", str(e))

    # ------------------------------------------------------------------
    # OMA lens-trace interchange (M7)
    # ------------------------------------------------------------------

    def _import_dxf(self):
        """File > Import > DXF… — pour any DXF's geometry into the active
        workspace.  Recognized GuildDraw layer names valid for this workspace
        are kept; everything else lands on the active layer, ungrouped, so the
        maker can drag each path to the right layer in the Layers panel."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import DXF", "", "DXF Files (*.dxf);;All Files (*)")
        if not path:
            return
        ws = self._active_ws
        try:
            from .export.dxf_import import import_dxf
            curves, notes = import_dxf(path, ws.active_layer, ws.workspace_type)
        except Exception as e:
            QMessageBox.critical(self, "DXF import failed", str(e))
            return
        if not curves:
            extra = ("\n\n" + "\n".join(notes)) if notes else ""
            QMessageBox.information(
                self, "Nothing imported",
                f"No supported geometry was found in this DXF.{extra}")
            return

        self._push_undo_snapshot()
        self.scene.clearSelection()
        for c in curves:
            c.mirrored = False
            self._active_ws.add_curve(c).setSelected(True)

        msg = f"Imported {len(curves)} curve(s) from {os.path.basename(path)}."
        if notes:
            msg += "  " + "  ".join(notes)
        self._status.showMessage(msg)

    def _ask_oma_import_bevel(self, default_depth: float) -> float | None:
        """Ask whether to shrink an imported OMA trace by the bevel depth.

        Returns the depth to shrink by (0.0 = import at traced size), or
        None if the user canceled the import. Split out so tests can
        monkeypatch the answer without driving a modal dialog."""
        return self._ask_oma_bevel(
            "Import OMA Lens Trace",
            "A tracer follows the bevel groove of the <b>finished</b> lens — "
            "the drawn lens shape grown outward by the bevel depth (this is "
            "also what OMA export writes).<br><br>"
            "Shrink the imported shape by the bevel depth to recover the "
            "drawn lens? Importing at the same depth the file was exported "
            "with round-trips exactly.",
            default_depth, "Apply Reduction", "Import As Traced")

    def _ask_oma_export_bevel(self, default_depth: float) -> float | None:
        """Ask whether to grow the exported OMA trace by the bevel depth.

        Returns the depth to grow by (0.0 = export the drawn lens opening
        as-is), or None if the user canceled the export. Split out so tests
        can monkeypatch the answer without driving a modal dialog."""
        return self._ask_oma_bevel(
            "Export OMA Trace",
            "A frame trace follows the bevel groove of the <b>finished</b> "
            "lens, not the drawn lens opening.<br><br>"
            "Grow the exported trace by the bevel depth so labs and edgers "
            "receive the finished size? The depth defaults to the boxing "
            "guide's bevel setting; HBOX/VBOX/DBL are computed from the "
            "same geometry either way.",
            default_depth, "Apply Increase", "Export As-Is")

    def _ask_oma_bevel(self, title: str, note_html: str, default_depth: float,
                       apply_label: str, asis_label: str) -> float | None:
        """Shared import/export bevel-depth dialog. Returns the chosen depth,
        0.0 for the as-is button, or None on cancel."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        note = QLabel(note_html)
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel("Bevel depth:"))
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 5.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setSuffix(" mm")
        spin.setValue(default_depth)
        row.addWidget(spin)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QDialogButtonBox()
        b_apply = btns.addButton(apply_label, QDialogButtonBox.AcceptRole)
        b_asis  = btns.addButton(asis_label, QDialogButtonBox.ActionRole)
        btns.addButton(QDialogButtonBox.Cancel)
        btns.rejected.connect(dlg.reject)
        result: dict = {}
        def _accept(mode):
            result["mode"] = mode
            dlg.accept()
        b_apply.clicked.connect(lambda: _accept("apply"))
        b_asis.clicked.connect(lambda: _accept("asis"))
        b_apply.setDefault(True)
        lay.addWidget(btns)
        if _run_modal(dlg) != QDialog.Accepted:
            return None
        return spin.value() if result.get("mode") == "apply" else 0.0

    def _import_oma(self):
        """File > Import > OMA Lens Trace… — traced lens shapes (from a frame
        tracer / lab DCS file) become editable LENS splines in Frame Front."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import OMA Lens Trace", "",
            "OMA / DCS Trace Files (*.oma *.dcs *.txt);;All Files (*)")
        if not path:
            return
        try:
            from .export.oma import parse_oma, trace_to_curve
            with open(path, encoding="ascii", errors="replace") as f:
                job = parse_oma(f.read())
            if not job.traces:
                QMessageBox.information(
                    self, "No trace data",
                    "This file contains no TRCFMT/R lens-trace records.")
                return
            lenses = {side: trace_to_curve(tr.radii_mm)
                      for side, tr in job.traces.items()}
        except Exception as e:
            QMessageBox.critical(self, "OMA import failed", str(e))
            return

        # DBL from the file when present, else the boxing-guide setting.
        front = self._workspaces[0]
        dbl_vals = job.floats("DBL")
        dbl = dbl_vals[0] if dbl_vals else front.boxing_dbl

        # A tracer follows the bevel groove of the FINISHED lens — the drawn
        # lens grown outward by the bevel depth (exactly what OMA export
        # writes). Ask whether to shrink back to the drawn lens shape.
        shrink = self._ask_oma_import_bevel(front.bevel_depth)
        if shrink is None:
            return                              # canceled
        if shrink > 0.0:
            try:
                from .geometry import offset_curve as _offset
                lenses = {side: _offset(c, -shrink)
                          for side, c in lenses.items()}
            except Exception as e:
                QMessageBox.warning(
                    self, "Bevel reduction failed",
                    f"Could not shrink the trace by {shrink:.2f} mm "
                    f"({e}).\nImporting at traced (finished) size instead.")
                shrink = 0.0
        # The file's DBL describes the finished lenses; after shrinking, the
        # drawn nasal edges sit a bevel depth further apart on each side so
        # the finished edges still land DBL apart.
        dbl_place = dbl + 2.0 * shrink

        # Place each lens: boxing centers on y = 0, nasal edges DBL apart.
        # Side R (OD) sits at negative x — viewer's left, same convention as
        # the measurement panel's OD/OS split about the mirror axis.
        # Sampled bbox (lens_bbox) so placement uses the same boxing basis as
        # the measurements panel, not the control-point extents.
        from .boxing import lens_bbox
        for side, c in lenses.items():
            bb = lens_bbox(c)
            if bb is None:
                continue
            w  = bb[2] - bb[0]
            tx = (-(dbl_place / 2 + w / 2) if side == "R"
                  else (dbl_place / 2 + w / 2)) \
                 - (bb[0] + bb[2]) / 2
            ty = -(bb[1] + bb[3]) / 2
            for nd in c.nodes:
                nd.x += tx;  nd.y += ty
                if nd.cp_in:
                    nd.cp_in.x  += tx;  nd.cp_in.y  += ty
                if nd.cp_out:
                    nd.cp_out.x += tx;  nd.cp_out.y += ty

        # Traces always land in Frame Front — switch first so the undo
        # snapshot and status bar belong to the workspace that changes.
        self._ws_tab_widget.setCurrentIndex(0)
        self._push_undo_snapshot()
        for c in lenses.values():
            self._active_ws.add_curve(c)

        # DRILLE holes → DRILL circles. OMA is y-up from the binocular frame
        # center, which the import places at the scene origin (0, 0).
        for d in job.drills:
            self._active_ws.add_curve(Curve(
                kind="circle", layer=Layer.DRILL,
                nodes=[SplineNode(d.x, -d.y)],
                radius=max(0.05, d.dia / 2.0), closed=True))

        src = "file DBL" if dbl_vals else "boxing-guide DBL"
        msg = (f"Imported {len(lenses)} traced lens shape"
               f"{'s' if len(lenses) != 1 else ''} onto LENS "
               f"({src} {dbl:.1f} mm).")
        if shrink > 0.0:
            msg += f"  Bevel reduction −{shrink:.2f} mm applied."
        if job.drills:
            msg += f"  +{len(job.drills)} drill hole(s) on DRILL."
        if len(lenses) == 1:
            msg += " Single-side file — the mirror ghost previews the other side."
        self._status.showMessage(msg)

    def _export_oma(self):
        """File > Export > OMA Trace… — write the two LENS contours as a
        TRCFMT format-1 DCS file for labs and edgers.

        A dialog asks whether the trace should describe the FINISHED lens —
        the drawn LENS shape grown outward by the bevel depth (a frame trace
        follows the bevel groove, not the lens opening; depth defaults to the
        boxing guide's bevel setting) — or the drawn lens opening as-is.
        HBOX/VBOX/DBL come from the same chosen geometry, so at the guide
        depth the file agrees with the boxing panel's finished read-outs."""
        if self._active_ws.workspace_type != "front":
            QMessageBox.information(
                self, "OMA export",
                "OMA lens traces are exported from the Frame Front workspace.")
            return

        from .export.oma import (
            OmaJob, OmaTrace, build_oma, curve_to_trace, points_to_trace,
            boxing_center,
        )
        from .boxing import finished_geometry
        lenses = [c for c in self._doc_curves
                  if not c.mirrored and c.layer == Layer.LENS]
        if self._act_mirror.isChecked():
            axis_x = self.scene.mirror.x if self.scene.mirror else 0.0
            lenses += [mirror_curve(c, axis_x) for c in list(lenses)]
        if len(lenses) != 2:
            QMessageBox.warning(
                self, "OMA export",
                f"OMA export needs exactly 2 LENS contours "
                f"(found {len(lenses)}).\nMirror doubling counts — draw one "
                "lens with Ghost on, or both lenses with it off.")
            return
        for c in lenses:
            if not c.closed and len(c.nodes) >= 2:
                n0, n1 = c.nodes[0], c.nodes[-1]
                gap = math.hypot(n1.x - n0.x, n1.y - n0.y)
                if gap > 0.1:
                    QMessageBox.warning(
                        self, "OMA export",
                        f"A LENS contour is not closed "
                        f"(endpoint gap {gap:.3f} mm > 0.1 mm).")
                    return

        # OD (side R) = the lens with the smaller boxing-center x.
        lenses.sort(key=lambda c: boxing_center(c)[0])
        od, os_lens = lenses

        depth = self._ask_oma_export_bevel(max(0.0, self._active_ws.bevel_depth))
        if depth is None:
            return                              # canceled

        # Build the job before asking for a filename — the tracer rejects
        # non-star-shaped contours and we want that error first.
        try:
            job = OmaJob()
            boxes = {}
            for side, c in (("R", od), ("L", os_lens)):
                bb, outline = finished_geometry(c, depth)
                if bb is None:
                    raise ValueError("A LENS contour has no area — cannot trace.")
                radii = (points_to_trace(outline) if outline is not None
                         else curve_to_trace(c))
                job.traces[side] = OmaTrace(side=side, radii_mm=radii)
                boxes[side] = bb
            job.set_record("HBOX", ";".join(
                f"{boxes[s][2] - boxes[s][0]:.2f}" for s in ("R", "L")))
            job.set_record("VBOX", ";".join(
                f"{boxes[s][3] - boxes[s][1]:.2f}" for s in ("R", "L")))
            job.set_record("DBL", f"{boxes['L'][0] - boxes['R'][2]:.2f}")
            job.set_record("FED", ";".join(
                f"{2.0 * max(job.traces[s].radii_mm):.2f}" for s in ("R", "L")))
        except ValueError as e:
            QMessageBox.critical(self, "OMA export failed", str(e))
            return

        # Drill-mount holes (DRILL layer) → DRILLE features, in the binocular
        # frame system: origin midway between the two lens centers, y-up.
        from .export.oma import OmaDrill
        origin_x = (boxing_center(od)[0] + boxing_center(os_lens)[0]) / 2.0
        mirror_on = self._act_mirror.isChecked()
        axis_x = (self.scene.mirror.x if (mirror_on and self.scene.mirror)
                  else origin_x)
        for c in self._doc_curves:
            if (c.mirrored or c.layer != Layer.DRILL
                    or c.kind != "circle" or not c.nodes):
                continue
            hx, hy = c.nodes[0].x, c.nodes[0].y
            dia = 2.0 * (c.radius or 0.7)
            job.drills.append(OmaDrill(hx - origin_x, -hy, dia))
            if mirror_on:
                job.drills.append(OmaDrill((2.0 * axis_x - hx) - origin_x, -hy, dia))

        path, _ = QFileDialog.getSaveFileName(
            self, "Export OMA Trace", "",
            "OMA / DCS Trace Files (*.oma);;All Files (*)")
        if not path:
            return
        path = self._ensure_suffix(path, ".oma")
        try:
            with open(path, "w", encoding="ascii", newline="") as f:
                f.write(build_oma(job))
            size = (f"finished lens (+{depth:.2f} mm bevel)" if depth > 0.0
                    else "drawn lens opening (as-is)")
            self._status.showMessage(
                f"OMA trace exported: {os.path.basename(path)} — {size}.")
        except Exception as e:
            QMessageBox.critical(self, "OMA export failed", str(e))

    # ------------------------------------------------------------------
    # Print / PDF at 1:1 scale (M8)
    # ------------------------------------------------------------------

    _PRINT_PAD_MM = 5.0

    def _view_source_rect(self):
        """The scene-mm rectangle currently framed in the viewport (WYSIWYG)."""
        return self.view.mapToScene(self.view.viewport().rect()).boundingRect()

    def _print_1to1(self):
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        if not self._has_visible_geometry():
            QMessageBox.information(
                self, "Print at 1:1",
                "Nothing to print — this workspace has no visible geometry.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print at 1:1 Scale")
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        try:
            clipped = self._render_1to1(printer, self._view_source_rect())
        except Exception as e:
            QMessageBox.critical(self, "Print failed", str(e))
            return
        self._status.showMessage(
            "Printed at 1:1 — view larger than the page, edges cropped."
            if clipped else "Printed at 1:1 scale.")

    def _export_pdf_1to1(self):
        from PySide6.QtPrintSupport import QPrinter
        if not self._has_visible_geometry():
            QMessageBox.information(
                self, "Export PDF",
                "Nothing to export — this workspace has no visible geometry.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF (current view, 1:1)", "", "PDF Files (*.pdf)")
        if not path:
            return
        path = self._ensure_suffix(path, ".pdf")
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        try:
            clipped = self._render_1to1(printer, self._view_source_rect())
        except Exception as e:
            QMessageBox.critical(self, "PDF export failed", str(e))
            return
        self._status.showMessage(
            f"PDF exported at 1:1: {os.path.basename(path)}"
            + ("  — view larger than the page, edges cropped." if clipped else ""))

    def _has_visible_geometry(self) -> bool:
        if any(c.nodes and not c.mirrored and self.scene.is_layer_visible(c.layer)
               for c in self._doc_curves):
            return True
        return any(t.text.strip() and self.scene.is_layer_visible(t.layer)
                   for t in self._active_ws.doc_texts)

    def _render_1to1(self, printer, source):
        """Paint the CURRENT VIEW at exactly 1 mm = 1 mm paper scale.

        Renders the visible-layer geometry (and its mirror ghost) and the
        engraving text currently framed in the viewport, drawn as clean
        vectors in each layer's color at the uniform PDF line weight from
        Settings ▸ PDF, shifted by the vertical frame offset. A 50 mm ruler
        verifies the scale. Content larger than the page is cropped 1:1.
        """
        from PySide6.QtCore import QRectF as _QRectF
        from PySide6.QtPrintSupport import QPrinter
        from .canvas.items import build_path
        from .geometry import mirror_curve
        from .textpath import text_outline_path

        cfg    = self._prefs.get("catalog_pdf", {})
        lw_mm  = float(cfg.get("line_weight_mm", 0.6))
        off_mm = float(cfg.get("content_offset_mm", 0.0))

        px_mm_x = printer.logicalDpiX() / 25.4
        px_mm_y = printer.logicalDpiY() / 25.4
        page = printer.pageRect(QPrinter.Unit.DevicePixel)

        target_w = source.width()  * px_mm_x
        target_h = source.height() * px_mm_y
        clipped = target_w > page.width() or target_h > page.height()
        target = _QRectF((page.width()  - target_w) / 2,
                         (page.height() - target_h) / 2 + off_mm * px_mm_y,
                         target_w, target_h)

        # Visible-layer geometry + mirror ghost (guides/photos never print).
        vis = [c for c in self._doc_curves
               if c.nodes and not c.mirrored and self.scene.is_layer_visible(c.layer)]
        draw = list(vis)
        if self._act_mirror.isChecked() and self.scene.mirror is not None:
            horizontal = self._active_ws.workspace_type in ("temple_r", "temple_l")
            axis_x = self.scene.mirror.x
            # The layers the canvas ghosts, no others: a REF line printed
            # twice though the screen showed it once.
            draw += [mirror_curve(c, axis_x, horizontal=horizontal)
                     for c in vis if c.layer in _GHOST_LAYERS]

        # begin() checked, as the template and catalog exports do: an
        # unwritable PDF path left the painter inactive and the status bar
        # announcing a file that was never written.
        painter = QPainter()
        if not painter.begin(printer):
            where = printer.outputFileName() or printer.printerName()
            raise OSError(f"could not write {where}")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.save()
            painter.setClipRect(target)              # crop to the framed view
            painter.translate(target.left(), target.top())
            painter.scale(px_mm_x, px_mm_y)          # 1 mm = 1 mm
            painter.translate(-source.left(), -source.top())
            cos_w = lw_mm * px_mm_x                   # cosmetic px == lw_mm on paper
            for c in draw:
                # Always the light-mode (print) layer inks — dark-mode inks are
                # pale and would wash out on white paper.
                pen = QPen(QColor(theme.default_layer_color(c.layer.value, False)))
                pen.setCosmetic(True)
                pen.setWidthF(cos_w)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(build_path(c))
            for t in self._active_ws.doc_texts:
                if not self.scene.is_layer_visible(t.layer):
                    continue
                pen = QPen(QColor(theme.default_layer_color(t.layer.value, False)))
                pen.setCosmetic(True)
                pen.setWidthF(cos_w)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(text_outline_path(t))
            painter.restore()

            # 50 mm verification ruler, bottom-left of the printable area
            pen = QPen(QColor("#000000"))
            pen.setWidthF(0.3 * px_mm_x)
            painter.setPen(pen)
            rx, ry = 5.0 * px_mm_x, page.height() - 6.0 * px_mm_y
            painter.drawLine(QPointF(rx, ry), QPointF(rx + 50.0 * px_mm_x, ry))
            for mm in (0.0, 50.0):
                x = rx + mm * px_mm_x
                painter.drawLine(QPointF(x, ry - 1.5 * px_mm_y),
                                 QPointF(x, ry + 1.5 * px_mm_y))
            font = painter.font()
            font.setPixelSize(round(3.0 * px_mm_y))
            painter.setFont(font)
            painter.drawText(
                QPointF(rx, ry - 2.5 * px_mm_y),
                "50 mm — measure to verify 1:1 (print with scaling/'fit to page' OFF)")
        finally:
            painter.end()

        return clipped

    # ------------------------------------------------------------------
    # Print Front + Temples — 1:1 cutting templates (front + both temples,
    # stacked at true size on the maker's paper, paginated as needed)
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_suffix(path: str, suffix: str) -> str:
        """Append *suffix* unless the chosen name already ends with it (a
        non-native file dialog returns exactly what was typed; QPrinter and
        ezdxf happily write to a suffix-less name)."""
        return path if path.lower().endswith(suffix) else path + suffix

    def _design_name(self) -> str:
        """The open file's stem, or '' for an unsaved design."""
        return (os.path.splitext(os.path.basename(self._current_path))[0]
                if self._current_path else "")

    def _gather_template_components(self) -> dict:
        """What each of the front and temple workspaces currently shows —
        visible-layer curves plus the mirror ghost (so a half-drawn front
        prints whole) and visible engraving text — keyed for
        export.template_print."""
        # Flush the live toolbar into the active workspace (mirror toggle).
        self._save_ws_sidebar_state(self._active_ws)
        out = {}
        for key, ws in zip(("front", "temple_r", "temple_l"),
                           self._workspaces[:3], strict=True):
            vis = [c for c in ws.doc_curves
                   if c.nodes and not c.mirrored
                   and ws.scene.is_layer_visible(c.layer)]
            curves = list(vis)
            if ws.mirror_enabled and ws.scene.mirror is not None:
                horizontal = ws.workspace_type in ("temple_r", "temple_l")
                curves += [mirror_curve(c, ws.scene.mirror.x, horizontal=horizontal)
                           for c in vis if c.layer in _GHOST_LAYERS]
            texts = [t for t in ws.doc_texts
                     if t.text.strip() and ws.scene.is_layer_visible(t.layer)]
            out[key] = {"curves": curves, "texts": texts}
        return out

    def _template_print_status(self, verb: str, pages: int, clipped: bool):
        msg = f"{verb} {pages} page{'s' if pages != 1 else ''} at 1:1."
        if clipped:
            msg += "  A piece was larger than the page — its edges are cropped."
        self._status.showMessage(msg)

    def _print_templates(self):
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from .export.template_print import configure_printer, render_template_pages
        components = self._gather_template_components()
        if not any(c["curves"] or c["texts"] for c in components.values()):
            QMessageBox.information(
                self, "Print Front + Temples",
                "Nothing to print — the front and temple workspaces have no "
                "visible geometry.")
            return
        cfg = self._prefs.get("template_print", {})
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        configure_printer(printer, cfg, components)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print Front + Temples at 1:1")
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        try:
            pages, clipped = render_template_pages(
                printer, components, cfg, self._design_name())
        except Exception as e:
            QMessageBox.critical(self, "Print failed", str(e))
            return
        self._template_print_status("Printed", pages, clipped)

    def _export_pdf_templates(self):
        from .export.template_print import export_template_pdf
        components = self._gather_template_components()
        if not any(c["curves"] or c["texts"] for c in components.values()):
            QMessageBox.information(
                self, "PDF Front + Temples",
                "Nothing to export — the front and temple workspaces have no "
                "visible geometry.")
            return
        base = self._design_name()
        suggested = f"{base} templates.pdf" if base else "templates.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF Front + Temples (1:1 templates)", suggested,
            "PDF Files (*.pdf)")
        if not path:
            return
        path = self._ensure_suffix(path, ".pdf")
        try:
            pages, clipped = export_template_pdf(
                path, components, self._prefs.get("template_print", {}), base)
        except Exception as e:
            QMessageBox.critical(self, "PDF export failed", str(e))
            return
        self._template_print_status(
            f"Templates PDF exported ({os.path.basename(path)}):", pages, clipped)

    # ------------------------------------------------------------------
    # PDF for Catalog (front + both temples on one sheet + the design name)
    # ------------------------------------------------------------------

    def _catalog_component_curves(self, ws, layer_names) -> list:
        """Selected-layer geometry for one workspace, INCLUDING the mirror ghost
        so the full frame (not just the drawn half) reaches the catalog."""
        from .geometry import mirror_curve
        wanted = set(layer_names)
        base = [c for c in ws.doc_curves
                if c.layer.value in wanted and not c.mirrored and c.nodes]
        out = list(base)
        if ws.mirror_enabled and ws.scene.mirror is not None:
            horizontal = ws.workspace_type in ("temple_r", "temple_l")
            axis_x = ws.scene.mirror.x
            out += [mirror_curve(c, axis_x, horizontal=horizontal)
                    for c in base if c.layer in _GHOST_LAYERS]
        return out

    def _gather_catalog_components(self) -> dict:
        cfg = self._prefs.get("catalog_pdf", {})
        front_layers  = cfg.get("front_layers", ["OUTLINE", "LENS"])
        temple_layers = cfg.get("temple_layers", ["OUTLINE"])
        front, temple_r, temple_l = self._workspaces[0], self._workspaces[1], self._workspaces[2]
        return {
            "front":    self._catalog_component_curves(front, front_layers),
            "temple_r": self._catalog_component_curves(temple_r, temple_layers),
            "temple_l": self._catalog_component_curves(temple_l, temple_layers),
        }

    def _gather_catalog_fills(self) -> dict:
        """Per-component Frame Fill / Lens Fill overlays for the catalog sheet,
        taken from each workspace's own live scene so the page shows the tint
        that workspace shows. {} unless Settings ▸ PDF asks for them; a
        workspace with its fill off simply contributes nothing."""
        if not self._prefs.get("catalog_pdf", {}).get("include_fill", False):
            return {}
        out = {}
        for key, ws in zip(("front", "temple_r", "temple_l"),
                           self._workspaces[:3], strict=True):
            frame = ws.scene.fill_paint_spec()
            lens  = ws.scene.lens_fill_paint_spec()
            if frame or lens:
                out[key] = {"frame": frame, "lens": lens}
        return out

    def _export_pdf_catalog(self):
        # Flush the live sidebar into the active workspace so its curves are current.
        self._save_ws_sidebar_state(self._active_ws)
        components = self._gather_catalog_components()
        if not any(components.values()):
            QMessageBox.information(
                self, "PDF for Catalog",
                "Nothing to export — the front and temple workspaces have no "
                "geometry on the selected layers (set them in "
                "Preferences ▸ PDF).")
            return
        base = self._design_name()
        suggested = f"{base}.pdf" if base else "catalog.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF for Catalog", suggested, "PDF Files (*.pdf)")
        if not path:
            return
        path = self._ensure_suffix(path, ".pdf")
        caption = base or os.path.splitext(os.path.basename(path))[0]
        try:
            from .export.catalog_pdf import export_catalog_pdf
            export_catalog_pdf(path, components, self._prefs.get("catalog_pdf", {}),
                               caption, self._gather_catalog_fills())
            self._status.showMessage(
                f"Catalog PDF exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Catalog PDF export failed", str(e))

    # ------------------------------------------------------------------
    # Persistent preferences
    # ------------------------------------------------------------------

    def _save_prefs(self):
        """Persist durable settings only.

        Startup toggles and guide dimensions are written exclusively by the
        Settings dialog (see _open_settings) — toggling Ghost mid-session must
        not silently rewrite mirror_on_startup.
        """
        self._prefs["dark_mode"]           = self._dark_mode
        self._prefs["default_line_weight"] = self._default_line_weight
        self._prefs["toolbar_pinned"]      = self._toolbar.is_pinned()
        self._prefs["toolbar"]             = dict(self._toolbar_prefs)
        self._prefs["hotkeys"]             = dict(self._hotkey_prefs)
        _prefs_mod.save(self._prefs)

    def _on_toolbar_pin_changed(self, pinned: bool):
        """User toggled the toolbar overflow pin — persist the choice."""
        self._save_prefs()

    def _on_tooltips_toggled(self, on: bool, announce: bool = True):
        """The ? button: tooltips on or off, app-wide, remembered."""
        self._tooltip_filter.enabled = bool(on)
        self._act_tooltips.setToolTip(
            "Tooltips are on \u2014 click to hide them everywhere" if on
            else "Tooltips are off \u2014 click to show them again")
        if self._prefs.get("tooltips") != bool(on):
            self._prefs["tooltips"] = bool(on)
            _prefs_mod.save(self._prefs)
        if announce:
            self._status.showMessage(
                "Tooltips on" if on
                else "Tooltips off \u2014 the ? button turns them back on", 4000)

    # ------------------------------------------------------------------
    # Dark mode
    # ------------------------------------------------------------------

    def _refresh_theme_dependents(self):
        """Re-render everything that resolves theme colors — call after the
        mode, a viewport preset, or any token override changes."""
        dark = self._dark_mode
        QApplication.instance().setStyleSheet(theme.build_qss())
        _tb_px = theme.toolbar_icon_px()
        self._toolbar.setIconSize(QSize(_tb_px, _tb_px))
        bg = theme.color("canvas.bg")
        for ws in self._workspaces:
            ws.view.setBackgroundBrush(QBrush(QColor(bg)))
            ws.scene.set_dark_mode(dark)
            ws.const_guides.set_dark_mode(dark)
            ws.boxing_guide.set_dark_mode(dark)
            ws.stock_guide.set_dark_mode(dark)
            ws.pad_guide.set_dark_mode(dark)
            ws.edit_tool.refresh_theme()
        self._apply_toolbar_icons(dark)
        self._toolbar.set_dark(dark)  # overflow pop-out panel matches theme
        if getattr(self, "_snap_palette", None) is not None:
            self._snap_palette.apply_theme()
        self._refresh_layer_panel()   # eye/padlock icons are theme-colored
        self._update_readiness()      # dot colors are theme-aware

    def _toggle_dark_mode(self, dark: bool):
        self._dark_mode = dark
        theme.set_dark(dark)
        self._refresh_theme_dependents()
        self._save_prefs()

    # ------------------------------------------------------------------

    def _fit_view(self):
        # Include geometry drawn/imported beyond the pinned scene rect —
        # fitting sceneRect alone left far-from-origin DXF imports off-screen.
        rect = self.scene.sceneRect()
        content = self.scene.geometry_rect()
        if not content.isNull():
            rect = rect.united(content)
        self.view.fit_view(rect)
        self._update_info_label()


_CRASH_FP = None


def _install_crash_logger():
    """Record any fatal error to ~/.guilddraw/crash.log.

    Covers both a Python exception escaping a Qt slot/virtual (which PySide6
    routes through sys.excepthook, and may then abort) and a hard C-level fault
    — faulthandler writes on the signal at the C level, so a segfault that
    would otherwise vanish with unflushed buffers still leaves a trace. Cheap,
    always-on, and only writes when something goes wrong."""
    global _CRASH_FP
    import datetime
    import faulthandler
    import pathlib
    import traceback
    try:
        d = pathlib.Path.home() / ".guilddraw"
        d.mkdir(parents=True, exist_ok=True)
        _CRASH_FP = open(d / "crash.log", "a", buffering=1, encoding="utf-8")
        _CRASH_FP.write(
            f"\n=== session {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
            f"v{__version__} ===\n")
        _CRASH_FP.flush()
        faulthandler.enable(file=_CRASH_FP, all_threads=True)
    except Exception:
        _CRASH_FP = None

    _prev_hook = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            if _CRASH_FP is not None:
                _CRASH_FP.write(
                    f"\n--- unhandled exception "
                    f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
                traceback.print_exception(exc_type, exc, tb, file=_CRASH_FP)
                _CRASH_FP.flush()
        except Exception:
            pass
        _prev_hook(exc_type, exc, tb)

    sys.excepthook = _hook


def main():
    _install_crash_logger()
    app = QApplication(sys.argv)
    app.setApplicationName("GuildDraw")
    app.setApplicationDisplayName("GuildDraw")
    app.setOrganizationName("Guild of American Spectacle Makers")
    app.setStyleSheet(theme.build_qss())

    # Show the loading splash before building the (slower) main window, so the
    # maker sees the app is starting and doesn't re-launch a second copy.
    from .splash import make_splash
    splash = make_splash(app)

    win = MainWindow()
    win.show()
    splash.finish(win)   # dismiss once the window is up
    # Open a project passed on the command line (e.g. double-clicking a
    # .gdraw/.svg via the installed file association) — after the recovery
    # offer, not before: on its 400 ms timer the offer used to find the slot
    # already emptied by the open, and a crash's work was lost to a
    # double-click.
    target = next((a for a in app.arguments()[1:]
                   if not a.startswith("-") and os.path.isfile(a)), None)
    if target is not None and not win._offer_recovery(opening=target):
        win._open_path(target)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
