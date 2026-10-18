"""
Construction guides: bridge-angle lines and apical-radius arc.

Scene units = mm (1 scene unit = 1 mm), so all mm dimensions are used
directly as scene coordinates.  No px_per_mm conversion needed.

These guides are NEVER exported as DXF machined geometry.
"""

import math
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPen, QColor, QPainterPath

from . import theme


_Z = 4   # z-value: above face image, below geometry


def _guide_color(dark: bool) -> QColor:
    return QColor(theme.color("guide.construction"))

def _boxing_color(dark: bool) -> QColor:
    return QColor(theme.color("guide.boxing"))


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
        # The crest height is above the datum line, positive up as the optical
        # convention measures it (the scene is y-down); the arms' pivots hang
        # from the crest, as the Angle height says. They were placed from the
        # datum line, and a crest of 10 put them above the apex.
        top    = -self._crest_height_mm
        py     = top + self._pivot_y_mm

        arc_path = QPainterPath()
        arc_path.moveTo(R, R + top)
        arc_path.arcTo(-R, top, 2 * R, 2 * R, 0, 180)
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
        self._locked        = False   # lock-to-lens: derive boxes from geometry
        self._bevel_depth   = 0.0     # finished-lens outline offset (mm)
        self._lens_provider = None    # fn() -> list[Curve] (LENS curves)

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

    def set_locked(self, on: bool):
        self._locked = on
        self._refresh()

    def set_bevel_depth(self, mm: float):
        self._bevel_depth = mm
        self._refresh()

    def set_lens_provider(self, fn):
        """fn() -> list[Curve]; used in locked mode to box the real lenses."""
        self._lens_provider = fn

    def refresh(self):
        """Public re-draw — call when the locked lens geometry changes."""
        self._refresh()

    def _refresh(self):
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

        if not self._visible:
            return

        pen = QPen(_boxing_color(self._dark), 0)
        pen.setStyle(Qt.PenStyle.DashDotLine)

        if self._locked:
            self._draw_locked(pen)
        else:
            self._draw_from_values(pen)

    def _draw_from_values(self, pen):
        """Free-floating A × B boxes at DBL separation (unlocked default)."""
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

    def _draw_locked(self, pen):
        """Boxes derived from the real LENS geometry (+ bevel offset).  A box
        and center cross are drawn around each lens's finished bbox, plus the
        bevel-offset 'full lens depth' outline (computed from the sampled shape
        via Shapely so it stays clean on complex curves)."""
        from .boxing import finished_geometry
        from .document import Layer

        lenses = []
        if self._lens_provider:
            lenses = [c for c in self._lens_provider()
                      if c.layer == Layer.LENS and not c.mirrored and c.nodes]
        draw_curves = list(lenses)
        if self._mirror_on and lenses:
            # Boxes for the eyes the Ghost adds only: with both lenses drawn
            # every lens cast a twin box over the other, four boxes in all.
            from .export.validate import ghost_twins
            draw_curves += ghost_twins(lenses, lenses, self._axis_x)

        depth = self._bevel_depth
        out_pen = QPen(_boxing_color(self._dark), 0)
        out_pen.setStyle(Qt.PenStyle.DashLine)

        for c in draw_curves:
            bb, pts = finished_geometry(c, depth)
            if bb is None:
                continue
            x0, y0, x1, y1 = bb
            rect = QPainterPath()
            rect.addRect(x0, y0, x1 - x0, y1 - y0)
            ri = self._scene.addPath(rect, pen)
            ri.setZValue(self._Z)
            self._items.append(ri)
            xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
            for li in (self._scene.addLine(x0, ym, x1, ym, pen),
                       self._scene.addLine(xm, y0, xm, y1, pen)):
                li.setZValue(self._Z)
                self._items.append(li)
            if pts:
                path = QPainterPath()
                path.moveTo(pts[0][0], pts[0][1])
                for px, py in pts[1:]:
                    path.lineTo(px, py)
                path.closeSubpath()
                pi = self._scene.addPath(path, out_pen)
                pi.setZValue(self._Z)
                self._items.append(pi)


class RectGuide:
    """Dashed rectangle centered at the scene origin — stock blank or pad block
    reference.

    With ``core_line`` on (the temple blanks) a dash-dot line runs across the
    rectangle at y = 0: the core line, where the wire runs. GuildModel draws the
    same line on its blank and, since 1.8.2, places a temple by the drawing's
    origin — so a temple drawn on this line sits on the wire there, and one
    drawn beside it is cut beside the wire.
    """

    _Z = 5

    def __init__(self, scene, color_token: str,
                 width_mm: float = 170.0, height_mm: float = 85.0,
                 core_line: bool = False):
        self._scene       = scene
        self._items: list = []
        self._visible     = False
        self._width_mm    = width_mm
        self._height_mm   = height_mm
        self._core_line   = core_line
        self._color_token = color_token   # theme token, e.g. "guide.stock"

    @property
    def width_mm(self) -> float:
        return self._width_mm

    @property
    def height_mm(self) -> float:
        return self._height_mm

    @property
    def core_line(self) -> bool:
        return self._core_line

    def rect(self) -> QRectF:
        """The guide's rectangle in scene mm while it is shown, else a null
        rectangle (what Fit frames along with the drawing)."""
        if not self._visible:
            return QRectF()
        w, h = self._width_mm, self._height_mm
        return QRectF(-w / 2, -h / 2, w, h)

    def set_visible(self, on: bool):
        self._visible = on
        self._refresh()

    def set_core_line(self, on: bool):
        self._core_line = on
        self._refresh()

    def set_width(self, mm: float):
        self._width_mm = mm
        self._refresh()

    def set_height(self, mm: float):
        self._height_mm = mm
        self._refresh()

    def set_dark_mode(self, dark: bool):
        # Mode lives in the theme module; just redraw with resolved colors.
        self._refresh()

    def _refresh(self):
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

        if not self._visible:
            return

        pen = QPen(QColor(theme.color(self._color_token)), 0)
        pen.setStyle(Qt.PenStyle.DashLine)

        w, h = self._width_mm, self._height_mm
        rp = QPainterPath()
        rp.addRect(-w / 2, -h / 2, w, h)
        item = self._scene.addPath(rp, pen)
        item.setZValue(self._Z)
        self._items.append(item)

        if self._core_line:
            # A drafting center line (long-short dashes) along y = 0, the full
            # width of the blank: where the wire runs.
            core_pen = QPen(QColor(theme.color(self._color_token)), 0)
            core_pen.setStyle(Qt.PenStyle.DashDotLine)
            line = self._scene.addLine(-w / 2, 0.0, w / 2, 0.0, core_pen)
            line.setZValue(self._Z)
            self._items.append(line)
