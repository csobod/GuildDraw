import copy
import datetime
import math
import os
import sys
from pathlib import Path
from . import __version__
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QStatusBar,
    QGraphicsView, QDockWidget, QWidget, QVBoxLayout,
    QFormLayout, QGroupBox, QPushButton, QSlider, QLabel,
    QDoubleSpinBox, QFileDialog, QComboBox, QMessageBox,
    QDialog, QCheckBox, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem,
    QScrollArea, QTabWidget, QLineEdit,
)
from PySide6.QtCore import Qt, QPointF, QSize, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QBrush, QIcon, QPainter, QPixmap

from .canvas.items import CurveItem
from .canvas.dim import DimItem
from .canvas.measure_bar import MeasureBar
from .canvas.scene import FrameScene
from .canvas.snapping import SnapEngine
from .calibration import CalibTool
from .construction import ConstructionGuides, BoxingGuide, RectGuide
from . import prefs as _prefs_mod
from .document import (
    Layer, Calibration, MirrorAxis, FormingMetadata, MachinedBridge, FaceImage,
    Curve, SplineNode, ControlPoint, DimLine,
)
from .tools.draw import DrawTool
from .tools.edit import EditTool
from .tools.dim import DimTool
from .tools.circle import CircleTool
from .tools.trim import TrimTool
from .tools.split import SplitTool
from .tools.offset import OffsetTool
from .tools.point_move import PointMoveTool

_ICONS_DIR = Path(__file__).parent / "resources" / "icons"


def _make_icon(name: str, normal_color: str, checked_color: str,
               rotation: int = 0) -> QIcon:
    """Render an SVG icon at two colors for off/on toolbar states.

    rotation: clockwise degrees to rotate the rendered pixmap (0, 90, 180, 270).
    """
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtGui import QTransform
    src = (_ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8")
    icon = QIcon()
    for color, mode, state in [
        (normal_color,  QIcon.Mode.Normal, QIcon.State.Off),
        (checked_color, QIcon.Mode.Normal, QIcon.State.On),
    ]:
        renderer = QSvgRenderer(src.replace("currentColor", color).encode())
        px = QPixmap(20, 20)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        renderer.render(p)
        p.end()
        if rotation:
            # QPixmap.transformed with a bare rotate() auto-sizes the output to
            # contain the rotated content (stays 20×20 for 90°/270° on a square).
            # Do NOT wrap with translate()…translate() — that shifts the canvas.
            tx = QTransform().rotate(rotation)
            px = px.transformed(tx, Qt.TransformationMode.SmoothTransformation)
        icon.addPixmap(px, mode, state)
    return icon


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
    xs, ys = [], []
    for c in matched:
        if c.kind in ("circle", "arc") and c.radius and c.nodes:
            ox, oy, r = c.nodes[0].x, c.nodes[0].y, c.radius
            xs.extend([ox - r, ox + r]); ys.extend([oy - r, oy + r])
        else:
            for n in c.nodes:
                xs.append(n.x); ys.append(n.y)
                if n.cp_in:  xs.append(n.cp_in.x);  ys.append(n.cp_in.y)
                if n.cp_out: xs.append(n.cp_out.x); ys.append(n.cp_out.y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


QSS = """
QMainWindow, QWidget {
    background-color: #ffd580;
    color: #1f1f1f;
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QToolBar {
    background-color: #ffd580;
    border: none;
    spacing: 2px;
    padding: 4px;
}
QToolButton, QPushButton {
    background-color: #fce9c2;
    border: 1px solid #1f1f1f;
    border-radius: 4px;
}
QToolButton { padding: 5px; min-width: 30px; }
QPushButton { padding: 4px 10px; min-width: 54px; }
QToolButton:hover, QPushButton:hover { background-color: #ffe9b8; }
QToolButton:checked, QPushButton:checked { background-color: #1f1f1f; color: #ffd580; }
QToolBar::separator { background: #d4a840; width: 1px; margin: 4px 3px; }
QStatusBar {
    background-color: #ffd580;
    border-top: 1px solid #d4a840;
}
QMenuBar { background-color: #ffd580; color: #1f1f1f; }
QMenuBar::item:selected { background-color: #fce9c2; }
QMenu { background-color: #fce9c2; color: #1f1f1f; border: 1px solid #1f1f1f; }
QMenu::item:selected { background-color: #1f1f1f; color: #ffd580; }
QMenu::separator { height: 1px; background: #d4a840; margin: 2px 6px; }
QDockWidget { background-color: #ffd580; }
QDockWidget::title {
    background-color: #d4a840;
    padding: 4px 6px;
    font-weight: bold;
}
QGroupBox {
    border: 1px solid #d4a840;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    background-color: #ffd580;
}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background-color: #fce9c2;
    border: 1px solid #d4a840;
    border-radius: 3px;
    padding: 2px 4px;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #1f1f1f; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #fce9c2;
    border: 1px solid #1f1f1f;
    selection-background-color: #1f1f1f;
    selection-color: #ffd580;
}
QSlider::groove:horizontal {
    border: 1px solid #d4a840;
    height: 4px;
    background: #fce9c2;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #1f1f1f;
    border: 1px solid #1f1f1f;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #555; }
QTabWidget::pane { border-top: 1px solid #d4a840; }
QTabBar::tab {
    background: #fce9c2;
    color: #1f1f1f;
    border: 1px solid #d4a840;
    border-bottom: none;
    padding: 5px 8px;
    min-width: 40px;
}
QTabBar::tab:selected { background: #ffd580; font-weight: bold; }
QTabBar::tab:hover:!selected { background: #ffe9b8; }
"""

QSS_DARK = """
QMainWindow, QWidget {
    background-color: #1a1a1a;
    color: #d4cfc0;
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QToolBar {
    background-color: #1a1a1a;
    border: none;
    spacing: 2px;
    padding: 4px;
}
QToolButton, QPushButton {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    border-radius: 4px;
    color: #d4cfc0;
}
QToolButton { padding: 5px; min-width: 30px; }
QPushButton { padding: 4px 10px; min-width: 54px; }
QToolButton:hover, QPushButton:hover { background-color: #3a3a3a; }
QToolButton:checked, QPushButton:checked { background-color: #d4cfc0; color: #1a1a1a; }
QToolBar::separator { background: #554433; width: 1px; margin: 4px 3px; }
QStatusBar {
    background-color: #1a1a1a;
    border-top: 1px solid #554433;
}
QMenuBar { background-color: #1a1a1a; color: #d4cfc0; }
QMenuBar::item:selected { background-color: #2a2a2a; }
QMenu { background-color: #2a2a2a; color: #d4cfc0; border: 1px solid #554433; }
QMenu::item:selected { background-color: #d4cfc0; color: #1a1a1a; }
QMenu::separator { height: 1px; background: #554433; margin: 2px 6px; }
QDockWidget { background-color: #1a1a1a; }
QDockWidget::title {
    background-color: #2a2a2a;
    padding: 4px 6px;
    font-weight: bold;
}
QGroupBox {
    border: 1px solid #554433;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    background-color: #1a1a1a;
}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    border-radius: 3px;
    padding: 2px 4px;
    color: #d4cfc0;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #d4cfc0; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    selection-background-color: #d4cfc0;
    selection-color: #1a1a1a;
}
QSlider::groove:horizontal {
    border: 1px solid #554433;
    height: 4px;
    background: #2a2a2a;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #d4cfc0;
    border: 1px solid #d4cfc0;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #e8e0d0; }
QTabWidget::pane { border-top: 1px solid #554433; }
QTabBar::tab {
    background: #2a2a2a;
    color: #d4cfc0;
    border: 1px solid #554433;
    border-bottom: none;
    padding: 5px 8px;
    min-width: 40px;
}
QTabBar::tab:selected { background: #1a1a1a; font-weight: bold; }
QTabBar::tab:hover:!selected { background: #3a3a3a; }
"""

_CANVAS_BG_LIGHT = "#faf6ee"
_CANVAS_BG_DARK  = "#1e1e1e"

_DOCK_WIDTH = 270
_LAYERS = [l.value for l in Layer]

# Ordered toolbar action definitions used by SettingsDialog and _toolbar_actions.
# Tuple: (prefs_key, display_label, user_hideable)
_TOOLBAR_ACTION_DEFS = [
    ("select",       "Select",                  False),
    ("line",         "Line",                    True),
    ("spline",       "Spline",                  True),
    ("circle",       "Circle",                  True),
    ("arc",          "Arc",                     True),
    ("dim",          "Dim",                     True),
    ("trim",         "Trim",                    True),
    ("split_curve",  "Split Curve",             True),
    ("offset",       "Offset",                  True),
    ("point_move",   "Point Move",              True),
    ("ghost",        "Ghost (mirror toggle)",   True),
    ("guides",       "Guides",                  True),
    ("snap",         "Snap",                    True),
    ("smooth",       "Smooth Handles",          True),
    ("boxing",       "Boxing",                  True),
    ("stock",        "Stock",                   True),
    ("pad",          "Pad",                     True),
    ("mirror",       "Mirror (bake)",           True),
    ("mirror_close", "Mirror-Close",            True),
    ("copy_temple",  "Mirror Copy →",           True),
    ("join",         "Join",                    True),
    ("snap_node",    "Snap Node",               True),
    ("split",        "Split",                   True),
    ("explode",      "Explode",                 True),
    ("fit",          "Fit",                     True),
]

# Ordered hotkey action definitions used by SettingsDialog.
# Tuple: (prefs_key, display_label)
_HOTKEY_ACTION_DEFS = [
    ("line",         "Line tool"),
    ("spline",       "Spline tool"),
    ("circle",       "Circle tool"),
    ("arc",          "Arc tool"),
    ("dim",          "Dim tool"),
    ("trim",         "Trim tool"),
    ("split_curve",  "Split Curve tool"),
    ("offset",       "Offset tool"),
    ("point_move",   "Point Move tool"),
    ("snap_node_ep", "Snap Node to Endpoint"),
    ("move_gizmo",   "Move gizmo"),
]


class CanvasView(QGraphicsView):
    """QGraphicsView: wheel-zoom, middle-click pan, tool event routing."""

    zoom_changed = Signal(int)  # current zoom as integer percent (100 = 100%)

    def __init__(self, scene: FrameScene, status_bar: QStatusBar):
        super().__init__(scene)
        self._status_bar = status_bar
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
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#faf6ee")))

        self.measure_bar = MeasureBar(self)
        QTimer.singleShot(0, self._reposition_measure_bar)

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

    def set_calib_tool(self, tool: CalibTool):
        self._calib_tool = tool

    def set_draw_tool(self, tool: DrawTool | None):
        self._draw_tool = tool
        if tool is None and self._dim_tool is None:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        elif tool is not None:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        # Disable scene item selection while drawing
        for item in self.scene().items():
            if isinstance(item, CurveItem):
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, tool is None)

    def set_dim_tool(self, tool):
        self._dim_tool = tool
        if tool is not None:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif self._draw_tool is None:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def _reposition_measure_bar(self):
        bar = self.measure_bar
        bar.adjustSize()
        w = self.width()
        h = bar.sizeHint().height()
        bar.setFixedWidth(max(w, 1))
        bar.move(0, self.height() - h)
        bar.raise_()

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

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self.zoom_changed.emit(round(self.transform().m11() * 100))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
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
                candidates = [
                    it for it in self.items(vp_pos)
                    if isinstance(it, (CurveItem, DimItem))
                ]
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
                # itemAt() uses the view transform and correctly handles
                # ItemIgnoresTransformations (NodeDots, HandleDots, gizmo arrows).
                # Only start drag tracking when the topmost hit is a CurveItem.
                # DimItems handle their own offset-drag via mousePressEvent/mouseMoveEvent;
                # intercepting them here would translate the anchor points instead.
                top_item = self.scene().itemAt(scene_pos, self.transform())
                if isinstance(top_item, CurveItem):
                    # Check whether a currently-selected item is anywhere under cursor.
                    selected_ids = {id(it) for it in self.scene().selectedItems()
                                    if isinstance(it, (CurveItem, DimItem))}
                    hit_ids = {id(it) for it in self.items(vp_pos)
                               if isinstance(it, (CurveItem, DimItem))}
                    if selected_ids & hit_ids:
                        # A selected item is under the cursor. Capture the pre-click
                        # selection now — super() may reselect the topmost item instead.
                        self._drag_move_items = [
                            it for it in self.scene().selectedItems()
                            if isinstance(it, (CurveItem, DimItem))
                        ]
                    else:
                        # Nothing selected under cursor; after super() selects the
                        # clicked item, _pre_move_selected will use that new selection.
                        self._drag_move_items = []
                    self._drag_move_start = scene_pos
                else:
                    # NodeDot, HandleDot, gizmo arrow, or empty — don't intercept.
                    self._drag_move_items = []
                    self._drag_move_start = None
                self._drag_moving     = False
                self._drag_pre_called = False
            else:
                self._drag_move_items = []
                self._drag_move_start = None
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._draw_tool and self._draw_tool.active:
            pos       = self.mapToScene(event.position().toPoint())
            mods      = event.modifiers()
            use_snap  = not (mods & Qt.KeyboardModifier.ControlModifier)
            constrain = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self._draw_tool.handle_dbl_click(pos, use_snap, constrain)
            event.accept()
        else:
            # Double-click on a CurveItem in select mode → insert node
            scene_pos = self.mapToScene(event.position().toPoint())
            item = self.scene().itemAt(scene_pos, self.transform())
            if isinstance(item, CurveItem) and self._insert_node_callback:
                self._insert_node_callback(item.curve, scene_pos)
                event.accept()
                return
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
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
        else:
            was_moving = self._drag_moving
            self._drag_move_start = None
            self._drag_moving     = False
            self._drag_pre_called = False
            if was_moving and self._move_end_cb:
                self._move_end_cb()
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        # Delete / Backspace: remove selected curves (select mode only)
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not (self._draw_tool and self._draw_tool.active):
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

    _LABELS = {
        "front":    "Frame Front",
        "temple_r": "Temple R",
        "temple_l": "Temple L",
        "hinge":    "Hinge Pocket",
    }

    def __init__(self, workspace_type: str, status_bar, parent_win):
        from .canvas.scene import FrameScene
        from .canvas.snapping import SnapEngine
        from .calibration import CalibTool
        from .construction import ConstructionGuides, BoxingGuide, RectGuide
        from .tools.draw import DrawTool
        from .tools.edit import EditTool
        from .tools.dim import DimTool
        from .tools.circle import CircleTool
        from .tools.trim import TrimTool
        from .tools.split import SplitTool

        self.workspace_type = workspace_type

        # ── Document state ────────────────────────────────────────────────
        self.doc_curves: list = []
        self.doc_dims:   list = []
        self.bookmarks:  list = []
        self.undo_stack: list = []
        self.redo_stack: list = []
        self.image_px_per_mm: float | None = None

        # ── Canvas ────────────────────────────────────────────────────────
        self.scene = FrameScene()
        self.scene.init_mirror(horizontal=(workspace_type in ("temple_r", "temple_l")))
        self.snap  = SnapEngine(self.scene)
        self.view  = CanvasView(self.scene, status_bar)

        # ── Tools ─────────────────────────────────────────────────────────
        self.calib_tool  = CalibTool(parent_win)
        self.draw_tool   = DrawTool(parent_win)
        self.circle_tool = CircleTool(parent_win)
        self.edit_tool   = EditTool(self.scene, parent_win)
        self.dim_tool    = DimTool(parent_win)
        self.trim_tool   = TrimTool(parent_win)
        self.split_tool  = SplitTool(parent_win)
        self.offset_tool     = OffsetTool(parent_win)
        self.point_move_tool = PointMoveTool(parent_win)

        # ── Guides ────────────────────────────────────────────────────────
        self.const_guides = ConstructionGuides(self.scene)
        self.boxing_guide = BoxingGuide(self.scene)
        self.stock_guide  = RectGuide(self.scene, "#27ae60", "#2ecc71")
        self.pad_guide    = RectGuide(self.scene, "#8e44ad", "#9b59b6",
                                      width_mm=45.0, height_mm=45.0)

        # ── Move gizmo state ──────────────────────────────────────────────
        self.move_gizmo             = None
        self.move_gizmo_center      = QPointF(0, 0)
        self.drag_moving_curves:list = []
        self.drag_moving_dims:  list = []

        # ── Sidebar state saved/restored on tab switch ────────────────────
        from .construction import ConstructionGuides as _CG
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
        self.stock_w:        float = 170.0
        self.stock_h:        float = 85.0
        self.pad_w:          float = 45.0
        self.pad_h:          float = 45.0
        self.selected_face_idx: int       = -1
        self.face_image_paths:  list[str] = []
        self.fitted:            bool      = False   # True once fitInView has been called

        # Wire endpoint drag-snap using the workspace's own mutable list and view.
        # snap_enabled_fn is set by MainWindow after the toolbar is built.
        self.edit_tool.set_endpoint_snap_context(self.doc_curves, self.view)


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
        seq = QKeySequence(int(event.modifiers()) | key)
        self.setText(seq.toString())
        event.accept()


class SettingsDialog(QDialog):
    """Application-wide preferences dialog (General / Toolbar / Hotkeys tabs)."""

    def __init__(self, prefs: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(380)
        self.setMinimumHeight(480)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        tabs = QTabWidget()
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

        # ── Helper ────────────────────────────────────────────────────────
        def _spinbox(lo, hi, step, val, suffix=" mm", decimals=1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            s.setSuffix(suffix)
            s.setValue(val)
            return s

        # ═══════════════════════════════════════════════════════════════════
        # Tab 0 — General
        # ═══════════════════════════════════════════════════════════════════
        gen_scroll = QScrollArea()
        gen_scroll.setWidgetResizable(True)
        gen_scroll.setFrameShape(gen_scroll.Shape.NoFrame)
        gen_inner  = QWidget()
        gen_lay    = QVBoxLayout(gen_inner)
        gen_lay.setSpacing(12)
        gen_lay.setContentsMargins(16, 16, 16, 8)
        gen_scroll.setWidget(gen_inner)
        tabs.addTab(gen_scroll, "General")

        # Appearance
        app_box  = QGroupBox("Appearance")
        app_form = QFormLayout(app_box)
        self._dark_check = QCheckBox("Enable dark mode")
        self._dark_check.setChecked(prefs["dark_mode"])
        app_form.addRow(self._dark_check)
        gen_lay.addWidget(app_box)

        # Drawing
        draw_box  = QGroupBox("Drawing")
        draw_form = QFormLayout(draw_box)
        self._weight_spin = _spinbox(0.25, 10.0, 0.25, prefs["default_line_weight"],
                                     suffix=" px", decimals=2)
        self._weight_spin.setToolTip("Default line weight (screen pixels) for new curves.")
        draw_form.addRow("Default line weight:", self._weight_spin)
        gen_lay.addWidget(draw_box)

        # Startup toggles
        start_box  = QGroupBox("Startup — show/enable at launch")
        start_form = QFormLayout(start_box)
        self._mirror_chk = QCheckBox("Ghost axis");        self._mirror_chk.setChecked(prefs["mirror_on_startup"])
        self._guides_chk = QCheckBox("Construction guides"); self._guides_chk.setChecked(prefs["guides_on_startup"])
        self._snap_chk   = QCheckBox("Snap");              self._snap_chk.setChecked(prefs["snap_on_startup"])
        self._smooth_chk = QCheckBox("Smooth handles");    self._smooth_chk.setChecked(prefs["smooth_handles"])
        self._boxing_chk = QCheckBox("Boxing guide");      self._boxing_chk.setChecked(prefs["boxing_on_startup"])
        self._stock_chk  = QCheckBox("Stock guide");       self._stock_chk.setChecked(prefs["stock_on_startup"])
        self._pad_chk    = QCheckBox("Pad guide");         self._pad_chk.setChecked(prefs["pad_on_startup"])
        for chk in (self._mirror_chk, self._guides_chk, self._snap_chk,
                    self._smooth_chk, self._boxing_chk, self._stock_chk, self._pad_chk):
            start_form.addRow(chk)
        gen_lay.addWidget(start_box)

        # Boxing guide
        box_box  = QGroupBox("Boxing Guide")
        box_form = QFormLayout(box_box)
        self._box_a   = _spinbox(30.0, 80.0,  0.5, prefs["boxing_a_mm"])
        self._box_b   = _spinbox(15.0, 60.0,  0.5, prefs["boxing_b_mm"])
        self._box_dbl = _spinbox(8.0,  40.0,  0.5, prefs["boxing_dbl_mm"])
        box_form.addRow("A (width):",  self._box_a)
        box_form.addRow("B (height):", self._box_b)
        box_form.addRow("DBL:",        self._box_dbl)
        gen_lay.addWidget(box_box)

        # Stock guide
        stock_box  = QGroupBox("Stock Blank Guide  (green, centered at origin)")
        stock_form = QFormLayout(stock_box)
        self._stock_w = _spinbox(50.0,  400.0, 1.0, prefs["stock_width_mm"])
        self._stock_h = _spinbox(20.0,  200.0, 1.0, prefs["stock_height_mm"])
        stock_form.addRow("Width:",  self._stock_w)
        stock_form.addRow("Height:", self._stock_h)
        gen_lay.addWidget(stock_box)

        # Pad guide
        pad_box  = QGroupBox("Pad Block Guide  (purple, centered at origin)")
        pad_form = QFormLayout(pad_box)
        self._pad_w = _spinbox(10.0, 200.0, 0.5, prefs["pad_width_mm"])
        self._pad_h = _spinbox(10.0, 200.0, 0.5, prefs["pad_height_mm"])
        pad_form.addRow("Width:",  self._pad_w)
        pad_form.addRow("Height:", self._pad_h)
        gen_lay.addWidget(pad_box)

        gen_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Tab 1 — Toolbar visibility
        # ═══════════════════════════════════════════════════════════════════
        tb_scroll = QScrollArea()
        tb_scroll.setWidgetResizable(True)
        tb_scroll.setFrameShape(tb_scroll.Shape.NoFrame)
        tb_inner  = QWidget()
        tb_lay    = QVBoxLayout(tb_inner)
        tb_lay.setSpacing(4)
        tb_lay.setContentsMargins(16, 16, 16, 8)
        tb_scroll.setWidget(tb_inner)
        tabs.addTab(tb_scroll, "Toolbar")

        note = QLabel("Uncheck a button to hide it. Hidden buttons remain\n"
                      "accessible via their hotkey (set in the Hotkeys tab).")
        note.setWordWrap(True)
        tb_lay.addWidget(note)

        toolbar_prefs = prefs.get("toolbar", {})
        self._tb_checks: dict[str, QCheckBox] = {}
        for key, label, hideable in _TOOLBAR_ACTION_DEFS:
            default_on = key != "mirror_close"
            chk = QCheckBox(label)
            chk.setChecked(toolbar_prefs.get(key, default_on))
            if not hideable:
                chk.setEnabled(False)
                chk.setToolTip("Select is always visible.")
            self._tb_checks[key] = chk
            tb_lay.addWidget(chk)
        tb_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Tab 2 — Hotkeys
        # ═══════════════════════════════════════════════════════════════════
        hk_outer  = QWidget()
        hk_lay    = QVBoxLayout(hk_outer)
        hk_lay.setSpacing(8)
        hk_lay.setContentsMargins(16, 16, 16, 8)
        tabs.addTab(hk_outer, "Hotkeys")

        hint = QLabel("Click a field and press a key (or Ctrl/Shift/Alt + key).\n"
                      "Press Esc inside a field to clear it.")
        hint.setWordWrap(True)
        hk_lay.addWidget(hint)

        hk_form = QFormLayout()
        hk_form.setSpacing(6)
        hk_lay.addLayout(hk_form)

        hotkey_prefs = prefs.get("hotkeys", {})
        self._key_edits: list[KeyCaptureEdit] = []
        self._hk_keys:   list[str]            = []
        from . import prefs as _pm
        defaults = _pm.DEFAULTS["hotkeys"]
        for key, label in _HOTKEY_ACTION_DEFS:
            edit = KeyCaptureEdit()
            edit.setPlaceholderText("none")
            edit.setMaximumWidth(120)
            edit.setText(hotkey_prefs.get(key, defaults.get(key, "")))
            edit.textChanged.connect(self._check_conflicts)
            self._key_edits.append(edit)
            self._hk_keys.append(key)
            hk_form.addRow(label + ":", edit)

        self._conflict_label = QLabel()
        self._conflict_label.setStyleSheet("color: #cc0000;")
        self._conflict_label.hide()
        hk_lay.addWidget(self._conflict_label)

        non_reassignable = QLabel(
            "Non-reassignable (hardcoded):\n"
            "  Ctrl+Z  Undo    Ctrl+Y / Ctrl+Shift+Z  Redo\n"
            "  Del / Backspace  Delete     Esc  Cancel"
        )
        non_reassignable.setStyleSheet("color: #888; font-size: 11px;")
        hk_lay.addWidget(non_reassignable)
        hk_lay.addStretch()

        self._check_conflicts()

    # ------------------------------------------------------------------

    def _check_conflicts(self):
        texts = [e.text().strip() for e in self._key_edits]
        non_empty = [t for t in texts if t]
        conflict_keys = {t for t in non_empty if non_empty.count(t) > 1}
        for edit in self._key_edits:
            txt = edit.text().strip()
            if txt and txt in conflict_keys:
                edit.setStyleSheet("background: #ffcccc;")
            else:
                edit.setStyleSheet("")
        has_conflict = bool(conflict_keys)
        self._ok_btn.setEnabled(not has_conflict)
        if has_conflict:
            dupes = ", ".join(sorted(conflict_keys))
            self._conflict_label.setText(f"Conflict: {dupes} assigned to multiple actions.")
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
            "toolbar":              toolbar,
            "hotkeys":              hotkeys,
        }


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
    def _split_tool(self): return self._active_ws.split_tool
    @property
    def _offset_tool(self): return self._active_ws.offset_tool
    @property
    def _point_move_tool(self): return self._active_ws.point_move_tool

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

    # Sidebar face-image selection index
    @property
    def _selected_face_idx(self): return self._active_ws.selected_face_idx
    @_selected_face_idx.setter
    def _selected_face_idx(self, v): self._active_ws.selected_face_idx = v

    # ────────────────────────────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GuildDraw {__version__}")
        self.resize(1440, 860)

        # Load persistent preferences first
        self._prefs = _prefs_mod.load()

        # ── Global (non-workspace) state ──────────────────────────────────
        self._updating_layer_combo = False
        self._dark_mode            = self._prefs["dark_mode"]
        self._updating_weight_spin = False
        self._default_line_weight: float = self._prefs["default_line_weight"]
        self._current_path: str | None = None   # .gdraw file path (or single SVG)

        # Status bar must exist before WorkspaceState creates CanvasView instances
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._info_label = QLabel()
        self._info_label.setContentsMargins(0, 0, 8, 0)
        self._status.addPermanentWidget(self._info_label)

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
        for ws in self._workspaces:
            ws.view.set_calib_tool(ws.calib_tool)
            ws.calib_tool.calibrated.connect(self._apply_calibration)
            ws.calib_tool.status_message.connect(self._status.showMessage)
            ws.draw_tool.curve_added.connect(self._on_curve_added)
            ws.draw_tool.status_message.connect(self._status.showMessage)
            ws.circle_tool.curve_added.connect(self._on_curve_added)
            ws.circle_tool.status_message.connect(self._status.showMessage)
            ws.dim_tool.dim_added.connect(self._on_dim_added)
            ws.dim_tool.status_message.connect(self._status.showMessage)
            ws.trim_tool.trim_applied.connect(self._on_trim_applied)
            ws.trim_tool.status_message.connect(self._status.showMessage)
            ws.trim_tool.cancelled.connect(self._on_trim_cancelled)
            ws.split_tool.split_applied.connect(self._on_split_applied)
            ws.split_tool.status_message.connect(self._status.showMessage)
            ws.split_tool.cancelled.connect(self._on_split_cancelled)
            ws.offset_tool.offset_applied.connect(self._on_offset_applied)
            ws.offset_tool.status_message.connect(self._status.showMessage)
            ws.offset_tool.cancelled.connect(self._on_offset_cancelled)
            ws.point_move_tool.moved.connect(self._on_point_moved)
            ws.point_move_tool.status_message.connect(self._status.showMessage)
            ws.point_move_tool.cancelled.connect(self._on_point_move_cancelled)

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
            "dim":          self._act_dim.trigger,
            "trim":         self._act_trim.trigger,
            "split_curve":  self._act_split_curve.trigger,
            "offset":       self._act_offset.trigger,
            "point_move":   self._act_point_move.trigger,
            "snap_node_ep": self._snap_selected_node_to_endpoint,
            "move_gizmo":   self._toggle_move_gizmo,
        }
        self._apply_toolbar_visibility(self._toolbar_prefs)
        self._apply_hotkeys(self._hotkey_prefs)

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
            ws.view.measure_bar.commit_radius.connect(self._on_measure_commit_radius)

        # ── Toggle actions wired to dispatch helpers (lambdas evaluate _active_ws) ─
        self._act_mirror.toggled.connect(self._on_mirror_toggled)
        self._act_guides.toggled.connect(lambda v: self._guides.set_visible(v))
        self._act_snap.toggled.connect(lambda v: self._snap.set_enabled(v))
        self._act_smooth.toggled.connect(lambda v: self._edit_tool.set_smooth_mode(v))
        self._act_boxing.toggled.connect(lambda v: self._boxing_guide.set_visible(v))
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

        # Connect toggles/spinboxes to _save_prefs AFTER applying initial values
        for act in (self._act_mirror, self._act_guides, self._act_snap,
                    self._act_smooth, self._act_boxing, self._act_stock, self._act_pad):
            act.toggled.connect(lambda _: self._save_prefs())
        for spin in (self._boxing_a_spin, self._boxing_b_spin, self._boxing_dbl_spin,
                     self._stock_w_spin, self._stock_h_spin,
                     self._pad_w_spin, self._pad_h_spin):
            spin.valueChanged.connect(lambda _: self._save_prefs())

        # Layer combo
        self._layer_combo.currentTextChanged.connect(self._on_layer_combo_changed)

        # Undo/redo keyboard shortcuts (window-scope)
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._handle_undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self._redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self._redo)

        # Wire workspace tab-change now that all actions exist
        self._last_ws_idx = 0
        self._ws_tab_widget.currentChanged.connect(self._on_workspace_changed)
        self._show_guide_sections("front")
        self._refresh_library_panel()

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
        QTimer.singleShot(0, _initial_fit)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = QToolBar("Tools")
        self._toolbar = tb
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setIconSize(QSize(20, 20))
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
        self._act_dim    = QAction("Dim",    self, checkable=True)
        self._act_dim.setToolTip(
            "Dim: click two points to place a dimension annotation (mm).\n"
            "Snaps to curve nodes. Never exported.")

        self._act_trim = QAction("Trim", self, checkable=True)
        self._act_trim.setToolTip(
            "Trim: click a curve to remove the segment between its two nearest\n"
            "intersections with all other curves.  Stay in trim mode to trim more.\n"
            "Esc to exit."
        )
        self._act_split_curve = QAction("Split\nCurve", self, checkable=True)
        self._act_split_curve.setToolTip(
            "Split Curve: click anywhere on a curve to split it into two open curves\n"
            "at that point.  Click near an intersection to split both curves at once.\n"
            "Esc to exit."
        )

        self._act_offset = QAction("Offset", self, checkable=True)
        self._act_offset.setToolTip(
            "Offset (O): select a curve, then type a distance (mm) and press Enter\n"
            "to create a parallel curve at that offset.\n"
            "Positive = outward (left-hand normal); negative = inward.\n"
            "Esc to cancel."
        )

        self._act_point_move = QAction("Point\nMove", self, checkable=True)
        self._act_point_move.setToolTip(
            "Point Move (G): click a grab point on the selection, then click\n"
            "the destination (or type X Y coordinates) to move the selection\n"
            "so the grab point lands exactly on the destination.\n"
            "Esc to cancel."
        )

        self._act_select.triggered.connect(self._set_tool_select)
        self._act_line.triggered.connect(self._set_tool_line)
        self._act_spline.triggered.connect(self._set_tool_spline)
        self._act_circle.triggered.connect(self._set_tool_circle)
        self._act_arc.triggered.connect(self._set_tool_arc)
        self._act_dim.triggered.connect(self._set_tool_dim)
        self._act_trim.triggered.connect(self._set_tool_trim)
        self._act_split_curve.triggered.connect(self._set_tool_split_curve)
        self._act_offset.triggered.connect(self._set_tool_offset)
        self._act_point_move.triggered.connect(self._set_tool_point_move)

        for act in (self._act_select, self._act_line, self._act_spline,
                    self._act_circle, self._act_arc, self._act_dim,
                    self._act_trim, self._act_split_curve, self._act_offset,
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
        tb.addAction(self._act_smooth)
        tb.addAction(self._act_boxing)
        tb.addAction(self._act_stock)
        tb.addAction(self._act_pad)

        tb.addSeparator()

        self._act_mirror_close = QAction("Mirror\nClose", self)
        self._act_mirror_close.setToolTip(
            "Mirror-Close: combine selected open curve with its mirror to form "
            "a single closed shape.\nBoth endpoints must be snapped to the mirror axis."
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

        self._act_copy_temple = QAction("Copy →", self)
        self._act_copy_temple.setToolTip(
            "Mirror Copy: flip all content from this temple workspace into\n"
            "the other temple workspace (R → L or L → R).\n"
            "Replaces all content in the target workspace."
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
            "Select a curve, click a node to turn it red, then press this button or E."
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

        # Map prefs keys → QAction objects (used by visibility and hotkey systems)
        self._toolbar_actions: dict[str, QAction] = {
            "select":       self._act_select,
            "line":         self._act_line,
            "spline":       self._act_spline,
            "circle":       self._act_circle,
            "arc":          self._act_arc,
            "dim":          self._act_dim,
            "trim":         self._act_trim,
            "split_curve":  self._act_split_curve,
            "offset":       self._act_offset,
            "point_move":   self._act_point_move,
            "ghost":        self._act_mirror,
            "guides":       self._act_guides,
            "snap":         self._act_snap,
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

        self._layer_combo = QComboBox()
        self._layer_combo.addItems(_LAYERS)
        draw_lay.addRow("Layer:", self._layer_combo)

        self._weight_spin = QDoubleSpinBox()
        self._weight_spin.setRange(0.25, 10.0)
        self._weight_spin.setDecimals(2)
        self._weight_spin.setSingleStep(0.25)
        self._weight_spin.setValue(1.5)
        self._weight_spin.setToolTip(
            "Line weight (screen pixels, cosmetic).\n"
            "Applies to selected curve(s) in Select mode, or to new curves in draw mode."
        )
        self._weight_spin.valueChanged.connect(self._on_weight_spin_changed)
        draw_lay.addRow("Line weight:", self._weight_spin)

        curve_lay.addWidget(draw_box)

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

        meas_refresh_btn = QPushButton("Refresh")
        meas_refresh_btn.clicked.connect(self._refresh_measurements)
        meas_front_lay.addRow(meas_refresh_btn)

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
        tabs.addTab(curve_w, "Properties")

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
        guide_lay.addRow("Frontal angle:", self._bridge_angle_spin)

        self._apical_spin = QDoubleSpinBox()
        self._apical_spin.setRange(2.0, 24.0)
        self._apical_spin.setSuffix(" mm")
        self._apical_spin.setSingleStep(0.5)
        self._apical_spin.setValue(_CG.DEFAULT_APICAL_RADIUS_MM)
        self._apical_spin.valueChanged.connect(
            lambda v: self._guides.set_apical_radius(v))
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

        self._boxing_a_spin = QDoubleSpinBox()
        self._boxing_a_spin.setRange(30.0, 80.0)
        self._boxing_a_spin.setSuffix(" mm")
        self._boxing_a_spin.setSingleStep(0.5)
        self._boxing_a_spin.setValue(50.0)
        self._boxing_a_spin.valueChanged.connect(
            lambda v: self._boxing_guide.set_a(v))
        boxing_lay.addRow("A (width):", self._boxing_a_spin)

        self._boxing_b_spin = QDoubleSpinBox()
        self._boxing_b_spin.setRange(15.0, 60.0)
        self._boxing_b_spin.setSuffix(" mm")
        self._boxing_b_spin.setSingleStep(0.5)
        self._boxing_b_spin.setValue(30.0)
        self._boxing_b_spin.valueChanged.connect(
            lambda v: self._boxing_guide.set_b(v))
        boxing_lay.addRow("B (height):", self._boxing_b_spin)

        self._boxing_dbl_spin = QDoubleSpinBox()
        self._boxing_dbl_spin.setRange(8.0, 40.0)
        self._boxing_dbl_spin.setSuffix(" mm")
        self._boxing_dbl_spin.setSingleStep(0.5)
        self._boxing_dbl_spin.setValue(18.0)
        self._boxing_dbl_spin.valueChanged.connect(
            lambda v: self._boxing_guide.set_dbl(v))
        boxing_lay.addRow("DBL:", self._boxing_dbl_spin)

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
        self._stock_w_spin.valueChanged.connect(
            lambda v: self._stock_guide.set_width(v))
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
        calib_lay.addRow("img-px/mm:", self._pxmm_spin)

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
            "Bookmarks persist for this session only.")
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

        # ── Tab 4: Hinge Library ──────────────────────────────────────────
        lib_w   = QWidget()
        lib_lay = QVBoxLayout(lib_w)
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
            "as HINGE-layer curves, centred at the canvas origin."
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

        tabs.addTab(lib_w, "Library")

        self._side_tabs = tabs
        self._side_tabs.currentChanged.connect(
            lambda idx: self._refresh_measurements() if idx == 0 else None)
        self._prop_dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._prop_dock)

    # ------------------------------------------------------------------
    # Status bar info label (layer + zoom)
    # ------------------------------------------------------------------

    def _update_info_label(self):
        layer = self._layer_combo.currentText()
        zoom  = round(self.view.transform().m11() * 100)
        self._info_label.setText(f"{layer}  |  {zoom}%")

    # ------------------------------------------------------------------
    # Workspace tab switching (Phase 14)
    # ------------------------------------------------------------------

    def _on_workspace_changed(self, idx: int):
        """Called by _ws_tab_widget.currentChanged. Saves departing sidebar
        state into the old WorkspaceState; restores arriving workspace state."""
        ws = self._workspaces[idx]

        # Save sidebar state into the workspace we're leaving
        if hasattr(self, "_last_ws_idx") and self._last_ws_idx != idx:
            self._save_ws_sidebar_state(self._workspaces[self._last_ws_idx])
        self._last_ws_idx = idx

        # Return to Select mode
        self._act_select.setChecked(True)
        self._set_tool_select()

        # Restore arriving workspace state into sidebar
        self._restore_ws_sidebar_state(ws)
        self._show_guide_sections(ws.workspace_type)
        self._refresh_timeline_list()
        self._refresh_measurements()
        self._refresh_library_panel()
        self._refresh_mirror_icons()
        self._update_info_label()

        # Fit the view the first time this workspace is shown
        if not ws.fitted:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            ws.fitted = True
            self._update_info_label()

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
        ws.boxing_a       = self._boxing_a_spin.value()
        ws.boxing_b       = self._boxing_b_spin.value()
        ws.boxing_dbl     = self._boxing_dbl_spin.value()
        ws.stock_w        = self._stock_w_spin.value()
        ws.stock_h        = self._stock_h_spin.value()
        ws.pad_w          = self._pad_w_spin.value()
        ws.pad_h          = self._pad_h_spin.value()
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
        ws.stock_guide.set_width(ws.stock_w)
        ws.stock_guide.set_height(ws.stock_h)
        ws.pad_guide.set_width(ws.pad_w)
        ws.pad_guide.set_height(ws.pad_h)

        # ── Layer combo ─────────────────────────────────────────────────
        from .document import WORKSPACE_LAYERS
        self._updating_layer_combo = True
        self._layer_combo.blockSignals(True)
        self._layer_combo.clear()
        self._layer_combo.addItems(
            [l.value for l in WORKSPACE_LAYERS[ws.workspace_type]]
        )
        self._layer_combo.blockSignals(False)
        self._updating_layer_combo = False

        # ── Calibration display ─────────────────────────────────────────
        if ws.image_px_per_mm:
            self._calib_label.setText(f"{ws.image_px_per_mm:.4f} img-px/mm")
            self._pxmm_spin.blockSignals(True)
            self._pxmm_spin.setValue(ws.image_px_per_mm)
            self._pxmm_spin.blockSignals(False)
        else:
            self._calib_label.setText("Not set")

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

    def _show_guide_sections(self, ws_type: str):
        """Show/hide Guides-tab group boxes based on workspace type."""
        is_front  = (ws_type == "front")
        is_temple = (ws_type in ("temple_r", "temple_l"))
        is_hinge  = (ws_type == "hinge")
        self._construction_guide_box.setVisible(is_front)
        self._boxing_guide_box.setVisible(is_front)
        self._stock_guide_box.setVisible(True)   # all workspaces have a stock rect
        self._pad_guide_box.setVisible(is_front) # pad block only meaningful for front
        for act in (self._act_guides, self._act_boxing):
            act.setVisible(is_front)
        self._act_stock.setVisible(True)
        self._act_pad.setVisible(is_front)
        self._meas_front_box.setVisible(is_front)
        self._meas_temple_box.setVisible(is_temple)
        if is_temple:
            label = "Temple R" if ws_type == "temple_r" else "Temple L"
            self._meas_temple_box.setTitle(f"Measurements — {label}")
        # Mirror Copy: visible only in temple workspaces
        if hasattr(self, "_act_copy_temple"):
            self._act_copy_temple.setVisible(is_temple)
        # Library tab: save/rename/delete only in Hinge Pocket workspace
        self._lib_hinge_actions.setVisible(is_hinge)

    def _refresh_measurements(self):
        """Recompute and display workspace measurements in the Properties tab."""
        ws = self._active_ws
        _FRONT_LAYERS  = {Layer.OUTLINE, Layer.LENS}
        _TEMPLE_LAYERS = {Layer.OUTLINE}

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
                fw = (os_ob[2] - os_ob[0]) * 2.0
            elif od_ob:
                fw = (od_ob[2] - od_ob[0]) * 2.0
            else:
                # Joined closed outline centred on mirror axis (centroid == mirror_x)
                # is dropped by _split; measure directly from all OUTLINE curves.
                all_out_raw = [c for c in curves if c.layer == Layer.OUTLINE and c.nodes]
                all_ob = _curves_bbox(all_out_raw) if all_out_raw else None
                fw = (all_ob[2] - all_ob[0]) if all_ob else None
            self._meas_frame_width_lbl.setText(f"{fw:.1f} mm" if fw is not None else "—")

            # Frame height — y-extent of all OUTLINE curves (mirror is vertical so no doubling)
            all_out = os_out + od_out
            fh_bb = _curves_bbox(all_out) if all_out else None
            self._meas_frame_height_lbl.setText(
                f"{fh_bb[3] - fh_bb[1]:.1f} mm" if fh_bb else "—")

            # ── Lens boxing: LENS layer ────────────────────────────────
            os_len, od_len = _split(Layer.LENS)
            os_lb = _curves_bbox(os_len) if os_len else None
            od_lb = _curves_bbox(od_len) if od_len else None

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

            # Endpiece width = y-extent in the leftmost region (hinge end)
            ep_threshold = min_x + max(x_span * 0.1, 2.0)
            ep_bbox = _curves_bbox(curves, layers=_TEMPLE_LAYERS, x_hi=ep_threshold)
            if ep_bbox:
                ep_h = ep_bbox[3] - ep_bbox[1]
                if ws.mirror_enabled:
                    ep_h *= 2  # horizontal mirror doubles the height
                self._meas_endpiece_lbl.setText(f"{ep_h:.1f} mm")
            else:
                self._meas_endpiece_lbl.setText("—")

    # ------------------------------------------------------------------
    # Move gizmo + drag-to-move
    # ------------------------------------------------------------------

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
        initial_items = self.view._drag_move_items
        if initial_items:
            self._drag_moving_curves = [it.curve for it in initial_items
                                        if isinstance(it, CurveItem)]
            self._drag_moving_dims   = [it.dim   for it in initial_items
                                        if isinstance(it, DimItem)]
        else:
            self._drag_moving_curves = [it.curve for it in self.scene.selectedItems()
                                        if isinstance(it, CurveItem)]
            self._drag_moving_dims   = [it.dim   for it in self.scene.selectedItems()
                                        if isinstance(it, DimItem)]

    def _move_selected_by(self, dx: float, dy: float):
        """Translate the currently tracked selected geometry by (dx, dy) mm."""
        for curve in self._drag_moving_curves:
            self._translate_curve(curve, dx, dy)
            self.scene.refresh_curve(curve)
        for dim in self._drag_moving_dims:
            self._translate_dim(dim, dx, dy)
        # Keep the gizmo centred on the moving geometry
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
        moved_items = [it for it in moved_items if it is not None]

        # Re-select the moved curves. Qt may have reselected the topmost item during
        # the initial press; blockSignals prevents redundant _on_selection_changed calls.
        if moved_items:
            self.scene.blockSignals(True)
            self.scene.clearSelection()
            for it in moved_items:
                it.setSelected(True)
            self.scene.blockSignals(False)

        # Rebuild edit handles for the (now-selected) moved curves.
        self._edit_tool.clear()
        for it in moved_items:
            self._edit_tool._add_curve_items(it)

        self._drag_moving_curves = []
        self._drag_moving_dims   = []

        # Sync layer combo and info label with the restored selection.
        if moved_items:
            self._on_selection_changed()

    def _gizmo_center_from_selection(self) -> QPointF | None:
        """Return the gizmo origin: bounding-box centre of the selected curves."""
        selected = [it for it in self.scene.selectedItems() if isinstance(it, CurveItem)]
        if not selected:
            return None
        xs, ys = [], []
        for it in selected:
            for node in it.curve.nodes:
                xs.append(node.x)
                ys.append(node.y)
        if not xs:
            return None
        return QPointF((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def _show_move_gizmo(self):
        """Show the move gizmo at the current selection centre (no-op if nothing selected)."""
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
        )
        self._status.showMessage(
            "Move gizmo active  |  drag arrow to move  |  click arrow for exact distance  |  M or Esc to dismiss"
        )

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

    def _apply_toolbar_visibility(self, toolbar_prefs: dict):
        """Show/hide toolbar actions according to toolbar_prefs dict."""
        for key, act in self._toolbar_actions.items():
            if key == "select":
                act.setVisible(True)
            else:
                act.setVisible(toolbar_prefs.get(key, True))

    def _apply_hotkeys(self, hotkey_prefs: dict):
        """Tear down existing hotkey QShortcuts and rebuild from hotkey_prefs."""
        from PySide6.QtGui import QShortcut, QKeySequence
        for sc in self._shortcuts.values():
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()
        for key, target in self._hotkey_targets.items():
            key_str = hotkey_prefs.get(key, "").strip()
            if key_str:
                sc = QShortcut(QKeySequence(key_str), self)
                sc.setContext(Qt.ShortcutContext.WindowShortcut)
                sc.activated.connect(target)
                self._shortcuts[key] = sc

    # ------------------------------------------------------------------
    # Toolbar icon refresh (called on build and on theme change)
    # ------------------------------------------------------------------

    def _apply_toolbar_icons(self, dark: bool):
        normal_c  = "#d4cfc0" if dark else "#1f1f1f"
        checked_c = "#1a1a1a" if dark else "#ffd580"
        pairs = [
            (self._act_select,       "tool-select"),
            (self._act_line,         "tool-line"),
            (self._act_spline,       "tool-spline"),
            (self._act_circle,       "tool-circle"),
            (self._act_arc,          "tool-arc"),
            (self._act_dim,          "tool-dim"),
            (self._act_mirror,       "toggle-mirror"),
            (self._act_guides,       "toggle-guides"),
            (self._act_snap,         "toggle-snap"),
            (self._act_smooth,       "toggle-smooth"),
            (self._act_boxing,       "toggle-boxing"),
            (self._act_stock,        "toggle-stock"),
            (self._act_pad,          "toggle-pad"),
            (self._act_mirror_close, "op-mirror-close"),
            (self._act_dup_mirror,   "op-dup-mirror"),
            (self._act_join,         "op-join"),
            (self._act_snap_ep,      "op-snap-node"),
            (self._act_split,        "op-split"),
            (self._act_explode,      "op-explode"),
            (self._act_fit,          "op-fit"),
            (self._act_trim,         "tool-trim"),
            (self._act_split_curve,  "tool-split-curve"),
            (self._act_offset,       "tool-offset"),
            (self._act_point_move,   "tool-point-move"),
            (self._act_panel,        "view-sidebar"),
        ]
        for act, name in pairs:
            svg = _ICONS_DIR / f"{name}.svg"
            if svg.exists():
                act.setIcon(_make_icon(name, normal_c, checked_c))
        self._refresh_mirror_icons()

    def _refresh_mirror_icons(self):
        """Re-render ghost and mirror-close icons rotated 90° for temple workspaces."""
        dark = self._dark_mode
        normal_c  = "#d4cfc0" if dark else "#1f1f1f"
        checked_c = "#1a1a1a" if dark else "#ffd580"
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

        file_menu = mb.addMenu("File")
        file_menu.addAction("New",              self._new)
        file_menu.addAction("Open…",            self._open)
        file_menu.addSeparator()
        file_menu.addAction("Save",             self._save)
        file_menu.addAction("Save As…",         self._save_as)
        file_menu.addSeparator()
        file_menu.addAction("Add Reference Image…", self._add_face)
        file_menu.addSeparator()
        exp = file_menu.addMenu("Export")
        exp.addAction("Export DXF…", self._export_dxf)
        exp.addAction("Export SVG…", self._export_svg)
        exp.addAction("Export PNG…", self._export_png)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        edit_menu = mb.addMenu("Edit")
        self._act_undo = edit_menu.addAction("Undo\tCtrl+Z", self._handle_undo)
        self._act_undo.setEnabled(False)
        self._act_redo = edit_menu.addAction("Redo\tCtrl+Y", self._redo)
        self._act_redo.setEnabled(False)

        view_menu = mb.addMenu("View")
        view_menu.addAction("Zoom In",  lambda: self.view.scale(1.2, 1.2))
        view_menu.addAction("Zoom Out", lambda: self.view.scale(1 / 1.2, 1 / 1.2))
        view_menu.addAction("Fit",      self._fit_view)
        view_menu.addSeparator()
        view_menu.addAction(self._act_mirror)
        view_menu.addAction(self._act_guides)
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
        settings_menu.addAction("Preferences…", self._open_settings)

    # ------------------------------------------------------------------
    # Tool switching
    # ------------------------------------------------------------------

    def _current_layer(self) -> Layer:
        return Layer(self._layer_combo.currentText())

    def _deactivate_cursor_tools(self):
        """Deactivate trim/split/offset/point-move tools and clear their state."""
        self._trim_tool.deactivate()
        self._split_tool.deactivate()
        self._offset_tool.deactivate()
        self._point_move_tool.deactivate()

    def _set_tool_select(self):
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._deactivate_cursor_tools()
        self.view.measure_bar.hide_bar()
        self._status.showMessage("Select: click a curve to select and show nodes")

    def _set_tool_line(self):
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._circle_tool.deactivate()
        self._deactivate_cursor_tools()
        self._edit_tool.clear()
        self.scene.clearSelection()
        layer = self._current_layer()
        self._draw_tool.activate("line", layer, self.scene, self.view,
                                 snap=self._snap, all_curves=self._doc_curves)
        self.view.set_draw_tool(self._draw_tool)

    def _set_tool_spline(self):
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._circle_tool.deactivate()
        self._deactivate_cursor_tools()
        self._edit_tool.clear()
        self.scene.clearSelection()
        layer = self._current_layer()
        self._draw_tool.activate("spline", layer, self.scene, self.view,
                                 snap=self._snap, all_curves=self._doc_curves)
        self.view.set_draw_tool(self._draw_tool)

    def _set_tool_circle(self):
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._deactivate_cursor_tools()
        self._edit_tool.clear()
        self.scene.clearSelection()
        layer = self._current_layer()
        self._circle_tool.activate("circle", layer, self.scene, self.view,
                                   snap=self._snap, all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_arc(self):
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._deactivate_cursor_tools()
        self._edit_tool.clear()
        self.scene.clearSelection()
        layer = self._current_layer()
        self._circle_tool.activate("arc", layer, self.scene, self.view,
                                   snap=self._snap, all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_dim(self):
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._deactivate_cursor_tools()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self.view.measure_bar.hide_bar()
        self._dim_tool.activate(self.scene, self.view,
                                snap=self._snap, all_curves=self._doc_curves)
        self.view.set_dim_tool(self._dim_tool)

    def _set_tool_trim(self):
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._split_tool.deactivate()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self.view.measure_bar.hide_bar()
        self._trim_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._trim_tool)

    def _set_tool_split_curve(self):
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._trim_tool.deactivate()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self.view.measure_bar.hide_bar()
        self._split_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._split_tool)

    def _on_trim_applied(self, original, remaining: list):
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self.scene.remove_curve(original)
        self._doc_curves.remove(original)
        for c in remaining:
            self._doc_curves.append(c)
            self.scene.add_curve(c)

    def _on_split_applied(self, original, parts: list):
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        if original in self._doc_curves:
            self.scene.remove_curve(original)
            self._doc_curves.remove(original)
        for c in parts:
            self._doc_curves.append(c)
            self.scene.add_curve(c)

    def _on_trim_cancelled(self):
        self._act_select.setChecked(True)
        self._set_tool_select()

    def _on_split_cancelled(self):
        self._act_select.setChecked(True)
        self._set_tool_select()

    # ------------------------------------------------------------------
    # Offset tool
    # ------------------------------------------------------------------

    def _set_tool_offset(self):
        from .canvas.items import CurveItem as _CI
        # Capture selection before deactivating tools (which may clear it)
        selected_curves = [
            item.curve for item in self.scene.selectedItems()
            if isinstance(item, _CI) and not item.curve.mirrored
        ]
        source = selected_curves[0] if len(selected_curves) == 1 else None

        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._trim_tool.deactivate()
        self._split_tool.deactivate()
        self.view.measure_bar.hide_bar()

        if source is None and not selected_curves:
            # No curve selected at all — prompt via status, let tool handle click-pick
            pass
        self._offset_tool.activate(self.scene, self.view, source)
        self.view.set_draw_tool(self._offset_tool)

    def _on_offset_applied(self, source_curve, offset_curve):
        self._push_undo_snapshot()
        self._doc_curves.append(offset_curve)
        self.scene.add_curve(offset_curve)
        # Return to Select mode first (re-enables ItemIsSelectable on all items)
        self._act_select.setChecked(True)
        self._set_tool_select()
        # Now selection is possible — clear and select the new curve
        self.scene.clearSelection()
        from .canvas.items import CurveItem as _CI
        for item in self.scene.items():
            if isinstance(item, _CI) and item.curve is offset_curve:
                item.setSelected(True)
                break
        self._status.showMessage(
            f"Offset {offset_curve.layer.value} curve created — select + edit nodes to refine"
        )

    def _on_offset_cancelled(self):
        self._act_select.setChecked(True)
        self._set_tool_select()

    # ------------------------------------------------------------------
    # Point Move tool
    # ------------------------------------------------------------------

    def _set_tool_point_move(self):
        from .canvas.items import CurveItem as _CI
        selected = [it for it in self.scene.selectedItems() if isinstance(it, _CI)]
        if not selected:
            self._status.showMessage("Point Move: select curves first")
            self._act_select.setChecked(True)
            return
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._trim_tool.deactivate()
        self._split_tool.deactivate()
        self._offset_tool.deactivate()
        self.view.measure_bar.hide_bar()
        self._point_move_tool.activate(self.scene, self.view,
                                        self._active_ws.snap)
        self.view.set_draw_tool(self._point_move_tool)

    def _on_point_moved(self, dx: float, dy: float):
        self._pre_move_selected()
        self._move_selected_by(dx, dy)
        # Restore Select mode first so ItemIsSelectable is True before
        # _end_move_selected calls setSelected(True) on the moved items.
        self._act_select.setChecked(True)
        self._set_tool_select()
        self._end_move_selected()
        self._status.showMessage(
            f"Moved  Δx {dx:+.3f} mm  Δy {dy:+.3f} mm"
        )

    def _on_point_move_cancelled(self):
        self._act_select.setChecked(True)
        self._set_tool_select()

    def _on_dim_added(self, dim: DimLine):
        self._push_undo_snapshot()
        self._doc_dims.append(dim)
        self.scene.add_dim(dim)
        self._act_select.setChecked(True)
        self._set_tool_select()
        import math as _math
        dist = _math.hypot(dim.x1 - dim.x0, dim.y1 - dim.y0)
        self._status.showMessage(
            f"Dim placed: {dist:.2f} mm  (select + Del to remove)"
        )

    def _on_measure_commit_radius(self, radius_mm: float):
        """MeasureBar Enter: confirm circle radius or lock arc radius."""
        if not self._circle_tool.active:
            return
        self._circle_tool.set_radius_and_advance(radius_mm)
        self.view.setFocus()

    def _on_mirror_toggled(self, on: bool):
        if self.scene.mirror:
            self.scene.mirror.set_enabled(on)
        self.scene.set_mirror_display(on)
        axis_x     = self.scene.mirror.x if self.scene.mirror else 0.0
        horizontal = (self._active_ws.workspace_type in ("temple_r", "temple_l"))
        self._snap.set_mirror(axis_x, on, horizontal=horizontal)
        self._boxing_guide.set_mirror(on)
        self._boxing_guide.set_axis_x(axis_x)

    def _on_curve_added(self, curve):
        curve.line_weight = self._default_line_weight
        self._push_undo_snapshot()        # snapshot BEFORE the curve is added
        self._doc_curves.append(curve)
        self.scene.add_curve(curve)
        self._refresh_measurements()
        # Return to select mode so the user can immediately inspect the new curve
        self._act_select.setChecked(True)
        self._set_tool_select()

    # ------------------------------------------------------------------
    # Layer re-labeling for selected curves
    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        """Reflect the selected curve's layer and weight in the UI (Select mode)."""
        if self._draw_tool.active or self._circle_tool.active:
            return
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if len(selected) == 1:
            self._updating_layer_combo = True
            self._layer_combo.setCurrentText(selected[0].curve.layer.value)
            self._updating_layer_combo = False
            self._updating_weight_spin = True
            self._weight_spin.setValue(selected[0].curve.line_weight)
            self._updating_weight_spin = False
        # Reposition gizmo on selection change, or hide if nothing selected
        if self._move_gizmo is not None:
            center = self._gizmo_center_from_selection()
            if center is not None:
                self._move_gizmo_center = center
                self._move_gizmo.set_center(center)
            else:
                self._hide_move_gizmo()
        self._update_info_label()

    def _on_layer_combo_changed(self, text: str):
        """Apply layer combo changes to selected curves (Select mode) or draw tool (draw mode)."""
        new_layer = Layer(text)
        if self._draw_tool.active:
            self._draw_tool.set_layer(new_layer)
            return
        if self._circle_tool.active:
            self._circle_tool.set_layer(new_layer)
            return
        if self._updating_layer_combo:
            return
        targets = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not targets:
            return
        self._push_undo_snapshot()
        for item in targets:
            item.curve.layer = new_layer
            item.refresh()
        self.scene._update_ghosts()
        self._status.showMessage(f"Layer → {new_layer.value}")
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

    _MAX_UNDO = 100

    def _take_snapshot(self) -> dict:
        """Return a deep copy of the current curves and dims."""
        return {
            "curves": copy.deepcopy(self._doc_curves),
            "dims":   copy.deepcopy(self._doc_dims),
        }

    def _push_undo_snapshot(self):
        """Push the current state onto the undo stack and wipe the redo future."""
        self._undo_stack.append(self._take_snapshot())
        self._redo_stack.clear()
        if len(self._undo_stack) > self._MAX_UNDO:
            self._undo_stack.pop(0)
        self._update_undo_actions()

    def _pre_edit_snapshot(self):
        """Called by EditTool just before any node or handle drag begins."""
        self._push_undo_snapshot()

    def _restore_snapshot(self, snapshot: dict):
        """Rebuild the canvas from a snapshot, clearing any active edit handles."""
        self._edit_tool.clear()
        self.scene.clearSelection()
        for c in list(self._doc_curves):
            self.scene.remove_curve(c)
        self._doc_curves.clear()
        for d in list(self._doc_dims):
            self.scene.remove_dim(d)
        self._doc_dims.clear()
        for c in snapshot["curves"]:
            self._doc_curves.append(c)
            self.scene.add_curve(c)
        for d in snapshot["dims"]:
            self._doc_dims.append(d)
            self.scene.add_dim(d)

    def _undo(self):
        if not self._undo_stack:
            self._status.showMessage("Nothing to undo")
            return
        self._redo_stack.append(self._take_snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self._update_undo_actions()
        n = len(self._undo_stack)
        self._status.showMessage(
            f"Undo — {n} step{'s' if n != 1 else ''} remaining")

    def _redo(self):
        if not self._redo_stack:
            self._status.showMessage("Nothing to redo")
            return
        self._undo_stack.append(self._take_snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self._update_undo_actions()
        n = len(self._redo_stack)
        self._status.showMessage(
            f"Redo — {n} step{'s' if n != 1 else ''} remaining")

    def _handle_undo(self):
        """Ctrl+Z: undo last draw-point when drawing, else canvas undo."""
        if self._draw_tool.active:
            if self._draw_tool.undo_last_point():
                self._status.showMessage("Undo: last point removed")
        else:
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
                    c = item.curve
                    if c in self._doc_curves:
                        self._doc_curves.remove(c)
                        self.scene.remove_curve(c)
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

        if not selected_curves and not selected_dims:
            self._status.showMessage("Nothing selected to delete")
            return

        self._push_undo_snapshot()

        for item in selected_dims:
            dim = item.dim
            if dim in self._doc_dims:
                self._doc_dims.remove(dim)
            self.scene.remove_dim(dim)

        to_remove = [item.curve for item in selected_curves if item.curve in self._doc_curves]
        if to_remove:
            self.scene.clearSelection()
            for curve in to_remove:
                self._doc_curves.remove(curve)
                self.scene.remove_curve(curve)
            n = len(to_remove)
            self._status.showMessage(f"Deleted {n} curve{'s' if n > 1 else ''}")
        elif selected_dims:
            n = len(selected_dims)
            self._status.showMessage(f"Deleted {n} dimension{'s' if n > 1 else ''}")

    def _insert_node(self, curve: Curve, scene_pos):
        """Insert a node at the nearest point on *curve* to *scene_pos*."""
        from PySide6.QtCore import QPointF
        self._push_undo_snapshot()
        if self._edit_tool.insert_node_at(curve, scene_pos):
            self.scene.refresh_curve(curve)
            # Rebuild edit handles so the new dot appears
            items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
            self._edit_tool.clear()
            for it in items:
                self._edit_tool._add_curve_items(it)
            self._status.showMessage(
                f"Inserted node — {len(curve.nodes)} nodes total")
        else:
            self._undo_stack.pop()   # nothing changed, discard snapshot
            self._update_undo_actions()

    # ------------------------------------------------------------------
    # Copy-across-mirror (Mirror Close)
    # ------------------------------------------------------------------

    def _copy_across_mirror(self):
        """Combine a selected open half-curve with its mirror image into one
        closed curve.  The two endpoints are snapped to the mirror axis before
        combining, so the halves join cleanly even if they were placed slightly
        off-axis."""
        from .tools.draw import compute_catmull_handles

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

        if is_horiz:
            axis_y = 0.0  # horizontal axis always at y=0

            def reflect(n):
                return SplineNode(x=n.x, y=-n.y)

            # Snap first and last y to the axis so halves join cleanly
            original = list(curve.nodes)
            original[0]  = SplineNode(x=original[0].x,  y=axis_y)
            original[-1] = SplineNode(x=original[-1].x, y=axis_y)

            new_nodes = [SplineNode(x=n.x, y=n.y) for n in original]
            for n in reversed(original[1:-1]):
                new_nodes.append(reflect(n))
        else:
            axis_x = self.scene.mirror.x if self.scene.mirror else 0.0

            def reflect(n):
                return SplineNode(x=2.0 * axis_x - n.x, y=n.y)

            # Snap first and last x to the axis so halves join cleanly
            original = list(curve.nodes)
            original[0]  = SplineNode(x=axis_x, y=original[0].y)
            original[-1] = SplineNode(x=axis_x, y=original[-1].y)

            new_nodes = [SplineNode(x=n.x, y=n.y) for n in original]
            for n in reversed(original[1:-1]):
                new_nodes.append(reflect(n))

        new_curve = Curve(
            kind        = curve.kind,
            layer       = curve.layer,
            nodes       = new_nodes,
            closed      = True,
            line_weight = curve.line_weight,
        )
        if curve.kind == "spline":
            compute_catmull_handles(new_curve.nodes, closed=True)

        # Replace the open half with the new closed shape
        self.scene.clearSelection()
        self.scene.remove_curve(curve)
        self._doc_curves.remove(curve)

        self._doc_curves.append(new_curve)
        self.scene.add_curve(new_curve)
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

        if is_horiz:
            # Temple workspace: horizontal axis at y=0 — reflect y
            def _dup(curve: Curve) -> Curve:
                if curve.kind == "circle":
                    return Curve(
                        kind="circle", layer=curve.layer, closed=curve.closed,
                        nodes=[SplineNode(x=curve.nodes[0].x, y=-curve.nodes[0].y)],
                        radius=curve.radius, line_weight=curve.line_weight,
                    )
                if curve.kind == "arc":
                    new_start = (-curve.end_angle)   % 360 if curve.end_angle   is not None else None
                    new_end   = (-curve.start_angle) % 360 if curve.start_angle is not None else None
                    return Curve(
                        kind="arc", layer=curve.layer, closed=curve.closed,
                        nodes=[SplineNode(x=curve.nodes[0].x, y=-curve.nodes[0].y)],
                        radius=curve.radius, start_angle=new_start, end_angle=new_end,
                        line_weight=curve.line_weight,
                    )
                new_nodes = []
                for n in curve.nodes:
                    mn = SplineNode(x=n.x, y=-n.y)
                    if n.cp_in:  mn.cp_in  = ControlPoint(n.cp_in.x,  -n.cp_in.y)
                    if n.cp_out: mn.cp_out = ControlPoint(n.cp_out.x, -n.cp_out.y)
                    new_nodes.append(mn)
                return Curve(kind=curve.kind, layer=curve.layer, nodes=new_nodes,
                             closed=curve.closed, line_weight=curve.line_weight)
        else:
            # Front/hinge workspace: vertical axis at x=axis_x — reflect x
            axis_x = self.scene.mirror.x if self.scene.mirror else 0.0

            def mx(x: float) -> float:
                return 2.0 * axis_x - x

            def _dup(curve: Curve) -> Curve:
                if curve.kind == "circle":
                    return Curve(
                        kind="circle", layer=curve.layer, closed=curve.closed,
                        nodes=[SplineNode(x=mx(curve.nodes[0].x), y=curve.nodes[0].y)],
                        radius=curve.radius, line_weight=curve.line_weight,
                    )
                if curve.kind == "arc":
                    new_start = (180.0 - curve.end_angle)   if curve.end_angle   is not None else None
                    new_end   = (180.0 - curve.start_angle) if curve.start_angle is not None else None
                    return Curve(
                        kind="arc", layer=curve.layer, closed=curve.closed,
                        nodes=[SplineNode(x=mx(curve.nodes[0].x), y=curve.nodes[0].y)],
                        radius=curve.radius, start_angle=new_start, end_angle=new_end,
                        line_weight=curve.line_weight,
                    )
                new_nodes = []
                for n in curve.nodes:
                    mn = SplineNode(x=mx(n.x), y=n.y)
                    if n.cp_in:  mn.cp_in  = ControlPoint(mx(n.cp_in.x),  n.cp_in.y)
                    if n.cp_out: mn.cp_out = ControlPoint(mx(n.cp_out.x), n.cp_out.y)
                    new_nodes.append(mn)
                return Curve(kind=curve.kind, layer=curve.layer, nodes=new_nodes,
                             closed=curve.closed, line_weight=curve.line_weight)

        self._push_undo_snapshot()
        self.scene.clearSelection()

        copies = [_dup(item.curve) for item in selected]
        for c in copies:
            self._doc_curves.append(c)
            self.scene.add_curve(c)

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

        temple_r → temple_l: flip across x = 0 (negate all x-coords).
        temple_l → temple_r: same flip — both sides mirror through the Y axis.
        Confirms before overwriting non-empty target; pushes undo snapshot in target.
        """
        import copy as _copy
        from .document import SplineNode as _SN, ControlPoint as _CP, Curve as _Curve, DimLine

        ws_type = self._active_ws.workspace_type
        if ws_type not in ("temple_r", "temple_l"):
            return

        # Identify source and target workspace objects
        tab_names = ["front", "temple_r", "temple_l", "hinge"]
        src_ws = self._active_ws
        target_type = "temple_l" if ws_type == "temple_r" else "temple_r"
        tgt_ws = self._workspaces[tab_names.index(target_type)]

        # Confirm if target has content
        if tgt_ws.doc_curves or tgt_ws.doc_dims:
            label = "Temple L" if target_type == "temple_l" else "Temple R"
            r = QMessageBox.question(
                self, "Replace temple content?",
                f"Replace all content in {label}? This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if r != QMessageBox.StandardButton.Yes:
                return

        def flip_y(y: float) -> float:
            return -y

        def flip_curve(c: _Curve) -> _Curve:
            if c.kind == "circle":
                return _Curve(
                    kind="circle", layer=c.layer, closed=c.closed,
                    nodes=[_SN(x=c.nodes[0].x, y=flip_y(c.nodes[0].y))],
                    radius=c.radius, line_weight=c.line_weight,
                )
            if c.kind == "arc":
                # Reflect across X axis: θ → -θ, sweep direction reverses so swap start/end
                new_start = (-c.end_angle)   % 360 if c.end_angle   is not None else None
                new_end   = (-c.start_angle) % 360 if c.start_angle is not None else None
                return _Curve(
                    kind="arc", layer=c.layer, closed=c.closed,
                    nodes=[_SN(x=c.nodes[0].x, y=flip_y(c.nodes[0].y))],
                    radius=c.radius, start_angle=new_start, end_angle=new_end,
                    line_weight=c.line_weight,
                )
            new_nodes = []
            for n in c.nodes:
                mn = _SN(x=n.x, y=flip_y(n.y))
                if n.cp_in:  mn.cp_in  = _CP(n.cp_in.x,  flip_y(n.cp_in.y))
                if n.cp_out: mn.cp_out = _CP(n.cp_out.x, flip_y(n.cp_out.y))
                new_nodes.append(mn)
            return _Curve(kind=c.kind, layer=c.layer, nodes=new_nodes,
                          closed=c.closed, line_weight=c.line_weight)

        def flip_dim(d: DimLine) -> DimLine:
            return DimLine(x0=d.x0, y0=flip_y(d.y0),
                           x1=d.x1, y1=flip_y(d.y1),
                           offset=d.offset)

        # Push undo snapshot in target workspace before clearing
        tgt_ws.undo_stack.append(_copy.deepcopy(tgt_ws.doc_curves))
        if len(tgt_ws.undo_stack) > 100:
            tgt_ws.undo_stack.pop(0)
        tgt_ws.redo_stack.clear()

        # Clear target
        tgt_ws.edit_tool.clear()
        for c in list(tgt_ws.doc_curves):
            tgt_ws.scene.remove_curve(c)
        tgt_ws.doc_curves.clear()
        for d in list(tgt_ws.doc_dims):
            tgt_ws.scene.remove_dim(d)
        tgt_ws.doc_dims.clear()

        # Copy + flip curves and dims from source into target
        for c in src_ws.doc_curves:
            flipped = flip_curve(c)
            tgt_ws.doc_curves.append(flipped)
            tgt_ws.scene.add_curve(flipped)
        for d in src_ws.doc_dims:
            flipped_d = flip_dim(d)
            tgt_ws.doc_dims.append(flipped_d)
            tgt_ws.scene.add_dim(flipped_d)

        # Switch to target tab
        self._ws_tab_widget.setCurrentIndex(tab_names.index(target_type))
        label = "Temple L" if target_type == "temple_l" else "Temple R"
        nc = len(tgt_ws.doc_curves)
        self._status.showMessage(
            f"Mirror Copy: {nc} curve{'s' if nc != 1 else ''} copied to {label}."
        )

    # ------------------------------------------------------------------
    # Join curves
    # ------------------------------------------------------------------

    _JOIN_TOL = 2.0  # mm — max endpoint distance to consider curves connectable

    def _join_selected_curves(self):
        """Chain 2+ selected open curves into one by connecting nearest endpoints."""
        from .document import SplineNode, Curve as _Curve

        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if len(selected_items) < 2:
            self._status.showMessage("Join: select 2 or more curves first")
            return

        curves = [item.curve for item in selected_items]

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
        for c in curves:
            self.scene.remove_curve(c)
            if c in self._doc_curves:
                self._doc_curves.remove(c)

        self._doc_curves.append(new_curve)
        item = self.scene.add_curve(new_curve)
        item.setSelected(True)
        self._status.showMessage(
            f"Joined {len(curves)} curves → "
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
        if curve is None or curve not in self._doc_curves:
            self._status.showMessage("Split: select a node first")
            return

        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()

        if curve.closed:
            # Rotate node list so idx is both first and last → one open curve
            rotated = copy.deepcopy(curve.nodes[idx:] + curve.nodes[:idx + 1])
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

        self.scene.remove_curve(curve)
        self._doc_curves.remove(curve)
        for c in results:
            self._doc_curves.append(c)
            self.scene.add_curve(c).setSelected(True)

        n = len(results)
        self._status.showMessage(f"Split → {n} curve{'s' if n > 1 else ''}")

    def _explode_selected(self):
        """Break each selected curve into individual 2-node segments."""
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not selected_items:
            self._status.showMessage("Explode: select one or more curves first")
            return

        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()

        total_segs = 0
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

            self.scene.remove_curve(curve)
            self._doc_curves.remove(curve)
            for seg in segments:
                self._doc_curves.append(seg)
                self.scene.add_curve(seg).setSelected(True)
            total_segs += len(segments)

        n_orig = len(selected_items)
        self._status.showMessage(
            f"Explode: {n_orig} curve{'s' if n_orig > 1 else ''} → {total_segs} segments"
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self):
        # Pre-populate dialog from live widget state (not stale prefs)
        live = self._collect_prefs()
        dlg = SettingsDialog(live, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        p = dlg.to_prefs()

        # Appearance
        if p["dark_mode"] != self._dark_mode:
            self._act_dark.setChecked(p["dark_mode"])
            self._toggle_dark_mode(p["dark_mode"])

        # Drawing
        self._default_line_weight = p["default_line_weight"]
        self._weight_spin.setValue(p["default_line_weight"])

        # Startup toggles — apply immediately so the toolbar reflects the new defaults
        self._act_mirror.setChecked(p["mirror_on_startup"])
        self._act_guides.setChecked(p["guides_on_startup"])
        self._act_snap.setChecked(p["snap_on_startup"])
        self._act_smooth.setChecked(p["smooth_handles"])
        self._act_boxing.setChecked(p["boxing_on_startup"])
        self._act_stock.setChecked(p["stock_on_startup"])
        self._act_pad.setChecked(p["pad_on_startup"])

        # Guide dimensions
        self._boxing_a_spin.setValue(p["boxing_a_mm"])
        self._boxing_b_spin.setValue(p["boxing_b_mm"])
        self._boxing_dbl_spin.setValue(p["boxing_dbl_mm"])
        self._stock_w_spin.setValue(p["stock_width_mm"])
        self._stock_h_spin.setValue(p["stock_height_mm"])
        self._pad_w_spin.setValue(p["pad_width_mm"])
        self._pad_h_spin.setValue(p["pad_height_mm"])

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
        self._status.showMessage(f"Bookmarked: {name.strip()}")

    def _restore_bookmark(self):
        items = self._timeline_list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        bm = self._bookmarks[idx]
        self._push_undo_snapshot()
        self._restore_snapshot(bm["snapshot"])
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

        # Translate bounding-box centre to canvas origin
        xs = [n.x for c in curves if not c.mirrored for n in c.nodes]
        ys = [n.y for c in curves if not c.mirrored for n in c.nodes]
        if xs:
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2
            for c in curves:
                for nd in c.nodes:
                    nd.x -= cx;  nd.y -= cy
                    if nd.cp_in:
                        nd.cp_in.x  -= cx;  nd.cp_in.y  -= cy
                    if nd.cp_out:
                        nd.cp_out.x -= cx;  nd.cp_out.y -= cy
                if c.kind in ("circle", "arc") and c.nodes:
                    pass  # centre node already translated above
            for d in dims:
                d.x0 -= cx;  d.y0 -= cy
                d.x1 -= cx;  d.y1 -= cy

        self._push_undo_snapshot()
        for c in curves:
            c.mirrored = False
            self._doc_curves.append(c)
            self.scene.add_curve(c)
        for d in dims:
            self._doc_dims.append(d)
            self.scene.add_dim(d)

        name = item.text().split("  ·")[0]
        self._status.showMessage(
            f"Imported '{name}' — {len(curves)} curve(s) placed at canvas origin"
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
    # Calibration
    # ------------------------------------------------------------------

    def _start_calibration(self):
        self.view.setFocus()
        self._calib_tool.start(self.scene)

    def _apply_calibration(self, px_per_mm: float):
        """Scale the face image so px_per_mm image pixels = 1 scene mm."""
        self._image_px_per_mm = px_per_mm
        self.scene.set_face_calibration(px_per_mm)
        self._pxmm_spin.blockSignals(True)
        self._pxmm_spin.setValue(px_per_mm)
        self._pxmm_spin.blockSignals(False)
        self._calib_label.setText(f"{px_per_mm:.4f} img-px/mm")
        self._status.showMessage(
            f"Face image calibrated: {px_per_mm:.4f} image pixels per mm"
        )

    def _apply_manual_calib(self):
        v = self._pxmm_spin.value()
        if v > 0:
            self._apply_calibration(v)

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
                self.view.fitInView(self.scene.sceneRect(),
                                    Qt.AspectRatioMode.KeepAspectRatio)
            self._status.showMessage(f"Loaded: {os.path.basename(path)}")
        else:
            self._status.showMessage(f"Failed to load image: {path}")

    def _remove_face(self):
        idx = self._face_list.currentRow()
        if idx < 0:
            return
        self.scene.remove_face(idx)
        self._face_list.takeItem(idx)
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

    def _on_face_rotation_changed(self, v: float):
        if self._selected_face_idx >= 0:
            self.scene.set_face_rotation(self._selected_face_idx, v)

    def _on_canvas_lock_toggled(self, locked: bool):
        if self._selected_face_idx >= 0:
            self.scene.set_canvas_locked(self._selected_face_idx, locked)

    # ------------------------------------------------------------------
    # New / Open / Save (SVG as native format)
    # ------------------------------------------------------------------

    def _new(self):
        any_content = any(ws.doc_curves for ws in self._workspaces)
        if any_content:
            r = QMessageBox.question(
                self, "New Document",
                "Discard all workspaces and start over?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        for ws in self._workspaces:
            ws.edit_tool.clear()
            for c in list(ws.doc_curves):
                ws.scene.remove_curve(c)
            ws.doc_curves.clear()
            for d in list(ws.doc_dims):
                ws.scene.remove_dim(d)
            ws.doc_dims.clear()
            ws.undo_stack.clear()
            ws.redo_stack.clear()
            ws.bookmarks.clear()
            ws.scene.clear_faces()
            ws.face_image_paths.clear()
            ws.selected_face_idx = -1
        # Refresh sidebar for the currently visible workspace
        self._face_list.clear()
        self._remove_img_btn.setEnabled(False)
        self._opacity_slider.setEnabled(False)
        self._rotation_spin.setEnabled(False)
        self._canvas_lock_chk.setEnabled(False)
        self._refresh_timeline_list()
        self._update_undo_actions()
        self._current_path = None
        self.setWindowTitle(f"GuildDraw {__version__}")
        self._status.showMessage("New document")

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GuildDraw File", "",
            "GuildDraw Files (*.gdraw *.svg);;GuildDraw Project (*.gdraw);;SVG Files (*.svg)"
        )
        if not path:
            return

        if path.lower().endswith(".gdraw"):
            self._open_gdraw(path)
        else:
            self._open_svg(path)

    def _open_svg(self, path: str):
        """Load a single .svg into the active (Front) workspace."""
        try:
            from .export.svg import load_svg
            data = load_svg(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        self._load_ws_data(self._workspaces[0], data)
        # Switch to Front tab
        self._ws_tab_widget.setCurrentIndex(0)
        self._current_path = path
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        bm = self._workspaces[0].bookmarks
        self._status.showMessage(
            f"Opened: {os.path.basename(path)}"
            + (f"  ·  {len(bm)} bookmark(s)" if bm else "")
        )

    def _open_gdraw(self, path: str):
        """Load a .gdraw ZIP into all three workspaces."""
        try:
            from .export.gdraw import load_gdraw
            all_data = load_gdraw(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        tab_names = ["front", "temple_r", "temple_l", "hinge"]
        for ws, tab in zip(self._workspaces, tab_names):
            self._load_ws_data(ws, all_data[tab])
        # Switch to the active tab stored in the file
        active = all_data.get("active_tab", "front")
        target_idx = tab_names.index(active) if active in tab_names else 0
        self._ws_tab_widget.setCurrentIndex(target_idx)
        self._current_path = path
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._status.showMessage(f"Opened: {os.path.basename(path)}")

    def _load_ws_data(self, ws: "WorkspaceState", data: dict):
        """Populate a WorkspaceState from a load_svg result dict.  Clears first."""
        ws.edit_tool.clear()
        for c in list(ws.doc_curves):
            ws.scene.remove_curve(c)
        ws.doc_curves.clear()
        for d in list(ws.doc_dims):
            ws.scene.remove_dim(d)
        ws.doc_dims.clear()
        ws.undo_stack.clear()
        ws.redo_stack.clear()

        for curve in data.get("curves", []):
            ws.doc_curves.append(curve)
            ws.scene.add_curve(curve)

        frm = data.get("forming", FormingMetadata())
        ws.bridge_angle  = frm.bridge_angle_deg
        ws.apical_radius = frm.apical_radius_mm

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
            ws.doc_dims.append(dim)
            ws.scene.add_dim(dim)

        ws.bookmarks = list(data.get("bookmarks", []))

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

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save GuildDraw File", "",
            "GuildDraw Project (*.gdraw);;SVG Files (*.svg)"
        )
        if path:
            self._current_path = path
            self._do_save(path)

    def _do_save(self, path: str):
        try:
            if path.lower().endswith(".gdraw"):
                self._do_save_gdraw(path)
            else:
                self._do_save_svg(path)
            self.setWindowTitle(f"GuildDraw — {os.path.basename(path)}")
            self._status.showMessage(f"Saved: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _ws_to_data_dict(self, ws: "WorkspaceState") -> dict:
        """Build the data dict for save_svg from a WorkspaceState."""
        return {
            "curves":      ws.doc_curves,
            "dims":        ws.doc_dims,
            "calibration": Calibration(px_per_mm=ws.image_px_per_mm),
            "mirror":      ws.scene.mirror or MirrorAxis(),
            "forming":     FormingMetadata(
                               bridge_angle_deg=ws.bridge_angle,
                               apical_radius_mm=ws.apical_radius,
                           ),
            "machined_bridge": MachinedBridge(),
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
        }

    def _do_save_svg(self, path: str):
        """Save the active workspace as a plain SVG (legacy format)."""
        # First flush sidebar into active ws
        self._save_ws_sidebar_state(self._active_ws)
        from .export.svg import save_svg
        ws = self._active_ws
        d  = self._ws_to_data_dict(ws)
        save_svg(
            curves          = d["curves"],
            path            = path,
            calibration     = d["calibration"],
            mirror          = d["mirror"],
            forming         = d["forming"],
            machined_bridge = d["machined_bridge"],
            face_images     = d["face_images"],
            bookmarks       = d["bookmarks"],
            dims            = d["dims"],
        )

    def _do_save_gdraw(self, path: str):
        """Save all three workspaces as a .gdraw ZIP."""
        # Flush sidebar into active workspace before building data dicts
        self._save_ws_sidebar_state(self._active_ws)
        tab_names = ["front", "temple_r", "temple_l", "hinge"]
        from .export.gdraw import save_gdraw
        ws_data = {}
        for ws, tab in zip(self._workspaces, tab_names):
            ws_data[tab] = self._ws_to_data_dict(ws)
        active_tab = tab_names[self._ws_tab_widget.currentIndex()]
        save_gdraw(ws_data, path, active_tab=active_tab)

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def _run_validator(self) -> bool:
        """Show validation errors/warnings. Return True if export may proceed."""
        from .export.validate import validate
        mirror_on = self._act_mirror.isChecked()
        errors, warnings = validate(self._doc_curves, mirror_on)
        if errors:
            msg = "Export blocked — fix the following:\n\n" + "\n".join(f"• {e}" for e in errors)
            if warnings:
                msg += "\n\nWarnings:\n" + "\n".join(f"• {w}" for w in warnings)
            QMessageBox.critical(self, "Validation failed", msg)
            return False
        if warnings:
            msg = "Warnings (export will proceed):\n\n" + "\n".join(f"• {w}" for w in warnings)
            r = QMessageBox.warning(
                self, "Validation warnings", msg,
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            return r == QMessageBox.StandardButton.Ok
        return True

    def _export_dxf(self):
        if not self._run_validator():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DXF", "", "DXF Files (*.dxf)"
        )
        if not path:
            return
        try:
            from .export.dxf import export_dxf
            export_dxf(
                curves    = self._doc_curves,
                path      = path,
                mirror_on = self._act_mirror.isChecked(),
                axis_x    = self.scene.mirror.x if self.scene.mirror else 0.0,
            )
            self._status.showMessage(f"DXF exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "DXF export failed", str(e))

    def _export_svg(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", "", "SVG Files (*.svg)"
        )
        if path:
            self._do_save(path)

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", "", "PNG Files (*.png)"
        )
        if not path:
            return
        try:
            from .export.png import render_png
            render_png(self.scene, path)
            self._status.showMessage(f"PNG exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "PNG export failed", str(e))

    # ------------------------------------------------------------------
    # Persistent preferences
    # ------------------------------------------------------------------

    def _collect_prefs(self) -> dict:
        """Build a prefs dict from the current live widget state."""
        return {
            "dark_mode":            self._dark_mode,
            "default_line_weight":  self._default_line_weight,
            "mirror_on_startup":    self._act_mirror.isChecked(),
            "guides_on_startup":    self._act_guides.isChecked(),
            "snap_on_startup":      self._act_snap.isChecked(),
            "smooth_handles":       self._act_smooth.isChecked(),
            "boxing_on_startup":    self._act_boxing.isChecked(),
            "boxing_a_mm":          self._boxing_a_spin.value(),
            "boxing_b_mm":          self._boxing_b_spin.value(),
            "boxing_dbl_mm":        self._boxing_dbl_spin.value(),
            "stock_on_startup":     self._act_stock.isChecked(),
            "stock_width_mm":       self._stock_w_spin.value(),
            "stock_height_mm":      self._stock_h_spin.value(),
            "pad_on_startup":       self._act_pad.isChecked(),
            "pad_width_mm":         self._pad_w_spin.value(),
            "pad_height_mm":        self._pad_h_spin.value(),
            "toolbar":              dict(self._toolbar_prefs),
            "hotkeys":              dict(self._hotkey_prefs),
        }

    def _save_prefs(self):
        """Collect current state and write to disk."""
        self._prefs = self._collect_prefs()
        _prefs_mod.save(self._prefs)

    # ------------------------------------------------------------------
    # Dark mode
    # ------------------------------------------------------------------

    def _toggle_dark_mode(self, dark: bool):
        self._dark_mode = dark
        app = QApplication.instance()
        app.setStyleSheet(QSS_DARK if dark else QSS)
        bg = _CANVAS_BG_DARK if dark else _CANVAS_BG_LIGHT
        for ws in self._workspaces:
            ws.view.setBackgroundBrush(QBrush(QColor(bg)))
            ws.scene.set_dark_mode(dark)
            ws.const_guides.set_dark_mode(dark)
            ws.boxing_guide.set_dark_mode(dark)
            ws.stock_guide.set_dark_mode(dark)
            ws.pad_guide.set_dark_mode(dark)
            ws.edit_tool.refresh_theme()
        self._apply_toolbar_icons(dark)
        self._save_prefs()

    # ------------------------------------------------------------------

    def _fit_view(self):
        self.view.fitInView(self.scene.sceneRect(),
                            Qt.AspectRatioMode.KeepAspectRatio)
        self._update_info_label()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
