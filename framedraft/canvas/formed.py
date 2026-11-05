"""The formed drawing over the faded flat one: View Formed's overlay
(BUILDPLAN *Road to 2.3*).

The window works out where every point lands after the press (the front,
`forming.FrontForming`) or after the tip bend (a temple, `forming.TipBend`)
and hands this overlay one polyline per drawn curve, Ghost twin and text,
each with its layer and weight; the overlay paints them in the layer pens
above the flat items, which the scene fades meanwhile. A view only: the
items here are never selectable or snapped to, and no export carries them
but the PNG, which is the canvas as seen (as it is with View Obverse).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath

from .items import FLAT_FADE, _layer_pen   # noqa: F401  (FLAT_FADE: the scene's)

#: The overlay's z: above the curves (10) and the Ghost (9), under the
#: dimensions and the node dots.
Z_FORMED = 10.5


def _path_of(polylines) -> QPainterPath:
    path = QPainterPath()
    for pts in polylines:
        if len(pts) < 2:
            continue
        path.moveTo(QPointF(float(pts[0][0]), float(pts[0][1])))
        for x, y in pts[1:]:
            path.lineTo(QPointF(float(x), float(y)))
    return path


class FormedOverlay:
    """``set_entries([(polylines, layer, line_weight, ghost, filled), …])``;
    *polylines* is a list of point lists (a text is several), *ghost* draws
    dotted as the Ghost does, *filled* tints the path as a text is."""

    def __init__(self, scene):
        self._scene = scene
        self._items: list = []

    def clear(self) -> None:
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

    def set_entries(self, entries) -> None:
        self.clear()
        for polylines, layer, line_weight, ghost, filled in entries:
            path = _path_of(polylines)
            if path.isEmpty():
                continue
            pen = _layer_pen(layer, line_weight)
            if ghost:
                pen.setStyle(Qt.PenStyle.DotLine)
            item = self._scene.addPath(path, pen)
            if filled:
                fill = QColor(pen.color())
                fill.setAlpha(70)
                item.setBrush(QBrush(fill))
            item.setZValue(Z_FORMED)
            item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, False)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._items.append(item)

    def __len__(self) -> int:
        return len(self._items)

    def paths(self) -> list[QPainterPath]:
        """The painted paths, for tests."""
        return [item.path() for item in self._items]
