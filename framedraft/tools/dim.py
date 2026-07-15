"""DimTool — two-click snap-aware dimension placement."""

from PySide6.QtCore import QObject, Signal, QPointF, Qt
from PySide6.QtGui import QPen, QColor

from ..document import DimLine


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
        self._hover_marker = None   # follows the (snapped) cursor in pick-A

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
            self._clear_hover_marker()
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
        if not self.active:
            return
        if self._snap:
            # Query even while hovering for the FIRST point so the snap
            # indicator shows before point A is placed — it used to appear
            # only for the second click (RC4 M26.1).
            pos = self._snap.snap(pos, [], self._view, use_snap)
        if self._pt_a is not None:
            self._repaint_rubber(pos)
        else:
            # No rubber-band yet in the pick-A phase, so give the first point
            # its own clear feedback: a crosshair that follows the (snapped)
            # cursor showing exactly where point 1 will land.
            self._update_hover_marker(pos)

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

    def _update_hover_marker(self, pos: QPointF):
        """Live crosshair at the pending first point (pick-A phase only)."""
        self._clear_hover_marker()
        if self._scene is None:
            return
        from PySide6.QtGui import QPainterPath
        R = 7
        path = QPainterPath()
        path.moveTo(-R, 0); path.lineTo(R, 0)
        path.moveTo(0, -R); path.lineTo(0, R)
        pen = QPen(QColor("#7a5c2e"), 1.5)
        pen.setCosmetic(True)
        item = self._scene.addPath(path, pen)
        item.setPos(pos)
        item.setFlag(item.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(101)
        self._hover_marker = item

    def _clear_hover_marker(self):
        if self._hover_marker is not None:
            if self._scene:
                self._scene.removeItem(self._hover_marker)
            self._hover_marker = None

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
        self._clear_hover_marker()
        if self._scene:
            for item in self._preview_items:
                try:
                    self._scene.removeItem(item)
                except Exception:
                    pass
        self._preview_items.clear()
