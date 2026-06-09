"""DimTool — two-click snap-aware dimension placement."""

import math
from PySide6.QtCore import QObject, Signal, QPointF, Qt
from PySide6.QtGui import QPen, QColor

from ..document import DimLine, SplineNode


class DimTool(QObject):
    """Two-click placement of a DimLine annotation.

    First click sets point A; second click sets point B and emits dim_added.
    Snaps to existing curve nodes/handles and the mirror axis (same engine used
    by DrawTool).
    """

    dim_added      = Signal(object)   # DimLine
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene  = None
        self._view   = None
        self._snap   = None
        self._pt_a:  QPointF | None = None
        self._preview_items: list   = []

    @property
    def active(self) -> bool:
        return self._scene is not None

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate(self, scene, view, snap=None, all_curves=None):
        self._clear_preview()
        self._pt_a   = None
        self._scene  = scene
        self._view   = view
        self._snap   = snap
        if snap is not None:
            snap.set_doc_curves(all_curves or [])
        self.status_message.emit(
            "Dim: click first point  |  Esc to cancel"
        )

    def deactivate(self):
        self._clear_preview()
        self._pt_a  = None
        if self._snap:
            self._snap.hide()
        self._scene = None
        self._view  = None
        self._snap  = None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_press(self, pos: QPointF, use_snap: bool = True) -> bool:
        if not self.active:
            return False
        if self._snap:
            pos = self._snap.snap(pos, [], self._view, use_snap)

        if self._pt_a is None:
            self._pt_a = pos
            self._draw_point_marker(pos)
            self.status_message.emit(
                "Dim: click second point  |  Esc to cancel"
            )
        else:
            dim = DimLine(
                x0=self._pt_a.x(), y0=self._pt_a.y(),
                x1=pos.x(),        y1=pos.y(),
            )
            self._clear_preview()
            self._pt_a  = None
            self._scene = None
            self._view  = None
            self.dim_added.emit(dim)
        return True

    def handle_move(self, pos: QPointF, use_snap: bool = True):
        if not self.active or self._pt_a is None:
            return
        if self._snap:
            pos = self._snap.snap(pos, [], self._view, use_snap)
        self._repaint_rubber(pos)

    def handle_key(self, key) -> bool:
        if not self.active:
            return False
        if key == Qt.Key.Key_Escape:
            self.deactivate()
            self.status_message.emit("Dim: cancelled")
            return True
        return False

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _draw_point_marker(self, pos: QPointF):
        R   = 4
        pen = QPen(QColor("#7a5c2e"), 1.5)
        pen.setCosmetic(True)
        dot = self._scene.addEllipse(-R, -R, 2 * R, 2 * R, pen)
        dot.setPos(pos)
        dot.setFlag(dot.GraphicsItemFlag.ItemIgnoresTransformations, True)
        dot.setZValue(101)
        self._preview_items.append(dot)

    def _repaint_rubber(self, pos: QPointF):
        # Remove only the rubber-band line (keep the first-point marker)
        for item in self._preview_items[1:]:
            self._scene.removeItem(item)
        self._preview_items = self._preview_items[:1]

        pen = QPen(QColor("#7a5c2e"), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        line = self._scene.addLine(
            self._pt_a.x(), self._pt_a.y(), pos.x(), pos.y(), pen
        )
        line.setZValue(100)
        self._preview_items.append(line)

    def _clear_preview(self):
        if self._scene:
            for item in self._preview_items:
                try:
                    self._scene.removeItem(item)
                except Exception:
                    pass
        self._preview_items.clear()
