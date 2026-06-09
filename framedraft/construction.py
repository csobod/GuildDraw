"""
Construction guides: bridge-angle lines and apical-radius arc.

Scene units = mm (1 scene unit = 1 mm), so all mm dimensions are used
directly as scene coordinates.  No px_per_mm conversion needed.

These guides are NEVER exported as DXF machined geometry.
"""

import math
from PySide6.QtCore import Qt
from PySide6.QtGui import QPen, QColor, QPainterPath


_Z = 4   # z-value: above face image, below geometry


def _guide_color(dark: bool) -> QColor:
    return QColor("#4ab8d8") if dark else QColor("#2a7f9e")

def _boxing_color(dark: bool) -> QColor:
    return QColor("#e8730a") if dark else QColor("#d35400")


class ConstructionGuides:
    """Manages bridge-angle lines and apical-radius arc on the canvas."""

    DEFAULT_BRIDGE_ANGLE_DEG = 15.0
    DEFAULT_APICAL_RADIUS_MM = 8.0

    def __init__(self, scene):
        self._scene = scene
        self._items: list = []
        self._visible = True
        self._bridge_angle_deg = self.DEFAULT_BRIDGE_ANGLE_DEG
        self._apical_radius_mm = self.DEFAULT_APICAL_RADIUS_MM
        self._crest_height_mm = 0.0
        self._spread_mm  = 4.0
        self._pivot_y_mm = 0.0
        self._dark = False
        self._refresh()

    # ------------------------------------------------------------------

    def set_visible(self, on: bool):
        self._visible = on
        for item in self._items:
            item.setVisible(on)

    def set_bridge_angle(self, deg: float):
        self._bridge_angle_deg = deg
        self._refresh()

    def set_apical_radius(self, mm: float):
        self._apical_radius_mm = mm
        self._refresh()

    def set_crest_height(self, mm: float):
        self._crest_height_mm = mm
        self._refresh()

    def set_spread(self, mm: float):
        self._spread_mm = mm
        self._refresh()

    def set_pivot_y(self, mm: float):
        self._pivot_y_mm = mm
        self._refresh()

    def set_dark_mode(self, dark: bool):
        self._dark = dark
        self._refresh()

    # ------------------------------------------------------------------

    def _refresh(self):
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

        pen = QPen(_guide_color(self._dark), 0)
        pen.setStyle(Qt.PenStyle.DashLine)

        R      = self._apical_radius_mm   # already mm = scene units
        spread = self._spread_mm
        py     = self._pivot_y_mm
        ch     = self._crest_height_mm

        arc_path = QPainterPath()
        arc_path.moveTo(R, R + ch)
        arc_path.arcTo(-R, ch, 2 * R, 2 * R, 0, 180)
        arc = self._scene.addPath(arc_path, pen)
        arc.setZValue(_Z)
        arc.setVisible(self._visible)
        self._items.append(arc)

        line_r    = max(R * 8, 40.0)
        angle_rad = math.radians(self._bridge_angle_deg)
        ax = line_r * math.sin(angle_rad)
        ay = line_r * math.cos(angle_rad)

        for sx in (+1, -1):
            px   = sx * spread
            line = self._scene.addLine(px, py, px + sx * ax, py + ay, pen)
            line.setZValue(_Z)
            line.setVisible(self._visible)
            self._items.append(line)


class BoxingGuide:
    """Dashed boxing-system rectangle guides (A × B lens box at DBL separation)."""

    _Z = 6

    def __init__(self, scene):
        self._scene       = scene
        self._items: list = []
        self._visible     = False
        self._a_mm        = 50.0
        self._b_mm        = 30.0
        self._dbl_mm      = 18.0
        self._axis_x      = 0.0
        self._mirror_on   = True
        self._dark        = False

    def set_visible(self, on: bool):
        self._visible = on
        self._refresh()

    def set_a(self, mm: float):
        self._a_mm = mm
        self._refresh()

    def set_b(self, mm: float):
        self._b_mm = mm
        self._refresh()

    def set_dbl(self, mm: float):
        self._dbl_mm = mm
        self._refresh()

    def set_axis_x(self, x: float):
        self._axis_x = x
        self._refresh()

    def set_mirror(self, on: bool):
        self._mirror_on = on
        self._refresh()

    def set_dark_mode(self, dark: bool):
        self._dark = dark
        self._refresh()

    def _refresh(self):
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

        if not self._visible:
            return

        pen = QPen(_boxing_color(self._dark), 0)
        pen.setStyle(Qt.PenStyle.DashDotLine)

        a        = self._a_mm        # mm = scene units
        b        = self._b_mm
        dbl_half = self._dbl_mm / 2
        ax       = self._axis_x
        y_top    = -b / 2
        y_bot    =  b / 2

        def _add_box(x_inner: float, width: float):
            x_outer = x_inner + width
            x_mid   = x_inner + width / 2
            rect_path = QPainterPath()
            rect_path.addRect(x_inner, y_top, width, b)
            ri = self._scene.addPath(rect_path, pen)
            ri.setZValue(self._Z)
            self._items.append(ri)
            for li in (
                self._scene.addLine(x_inner, 0.0, x_outer, 0.0, pen),
                self._scene.addLine(x_mid, y_top, x_mid, y_bot, pen),
            ):
                li.setZValue(self._Z)
                self._items.append(li)

        _add_box(ax + dbl_half, a)
        _add_box(ax - dbl_half - a, a)


class RectGuide:
    """Dashed rectangle centered at the scene origin — stock blank or pad block reference."""

    _Z = 5

    def __init__(self, scene, color_light: str, color_dark: str,
                 width_mm: float = 170.0, height_mm: float = 85.0):
        self._scene       = scene
        self._items: list = []
        self._visible     = False
        self._width_mm    = width_mm
        self._height_mm   = height_mm
        self._dark        = False
        self._col_light   = color_light
        self._col_dark    = color_dark

    def set_visible(self, on: bool):
        self._visible = on
        self._refresh()

    def set_width(self, mm: float):
        self._width_mm = mm
        self._refresh()

    def set_height(self, mm: float):
        self._height_mm = mm
        self._refresh()

    def set_dark_mode(self, dark: bool):
        self._dark = dark
        self._refresh()

    def _refresh(self):
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

        if not self._visible:
            return

        pen = QPen(QColor(self._col_dark if self._dark else self._col_light), 0)
        pen.setStyle(Qt.PenStyle.DashLine)

        w, h = self._width_mm, self._height_mm
        rp = QPainterPath()
        rp.addRect(-w / 2, -h / 2, w, h)
        item = self._scene.addPath(rp, pen)
        item.setZValue(self._Z)
        self._items.append(item)
