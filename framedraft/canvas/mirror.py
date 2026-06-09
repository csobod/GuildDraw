from PySide6.QtWidgets import QGraphicsLineItem
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPen, QColor, Qt


def _mirror_axis_color(dark: bool) -> QColor:
    return QColor("#e05555") if dark else QColor("#c0392b")


class MirrorAxis:
    """
    Mirror axis drawn as a dashed red line across the canvas.
    Vertical (horizontal=False, default): line at x, reflects across x.
    Horizontal (horizontal=True): line at y=0, reflects across y=0.
    """

    def __init__(self, scene, horizontal: bool = False):
        self._scene      = scene
        self._x          = 0.0
        self._on         = True
        self._dark       = False
        self._horizontal = horizontal
        self._item: QGraphicsLineItem | None = None
        self._refresh_line()

    @property
    def x(self) -> float:
        return self._x

    @property
    def enabled(self) -> bool:
        return self._on

    def set_x(self, x: float):
        self._x = x
        self._refresh_line()

    def set_enabled(self, on: bool):
        self._on = on
        self._refresh_line()

    def refresh_theme(self, dark: bool):
        self._dark = dark
        self._refresh_line()

    # ------------------------------------------------------------------

    def _refresh_line(self):
        if self._item is not None:
            self._scene.removeItem(self._item)
            self._item = None

        if not self._on:
            return

        r = self._scene.sceneRect()
        pen = QPen(_mirror_axis_color(self._dark), 0)
        pen.setStyle(Qt.PenStyle.DashLine)
        if self._horizontal:
            self._item = self._scene.addLine(r.left(), 0.0, r.right(), 0.0, pen)
        else:
            self._item = self._scene.addLine(self._x, r.top(), self._x, r.bottom(), pen)
        self._item.setZValue(5)

    def scene_rect_changed(self):
        """Call when the scene rect grows (e.g. after loading an image)."""
        self._refresh_line()

    # ------------------------------------------------------------------

    def mirror_point(self, p: QPointF) -> QPointF:
        if self._horizontal:
            return QPointF(p.x(), -p.y())
        return QPointF(2 * self._x - p.x(), p.y())
