"""
Text → outline-path → Curve conversion (M8 ENGRAVING workflow).

Any installed outline font is converted to cubic-Bézier letter shapes via
QPainterPath.addText — closed filled-letter contours suitable for pocket
engraving or laser fill. (Single-stroke Hershey fonts stay deferred.)

Sizing: ``size_mm`` is the CAP HEIGHT in mm. Point-size → rendered-height
varies per font, so the path is built at a fixed pixel size and rescaled by
the font's measured cap height — a 5 mm "E" really is 5 mm tall.

Rotation: positive degrees rotate CCW as displayed. The scene is y-down, so
that is a negative Qt rotation.

Needs a QGuiApplication for font metrics (always true in the app; tests
create an offscreen one). No QtWidgets dependency.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath, QTransform

from .document import ControlPoint, Curve, SplineNode, TextObject

_BASE_PX = 256.0   # build glyphs at this pixel size, then scale to mm


def text_outline_path(t: TextObject) -> QPainterPath:
    """Outline path for a TextObject in scene mm, anchored at
    (anchor_x, anchor_y) = baseline left."""
    font = QFont(t.family)
    font.setPixelSize(int(_BASE_PX))
    cap = QFontMetricsF(font).capHeight()
    if cap <= 0:
        cap = QFontMetricsF(font).ascent() or _BASE_PX

    path = QPainterPath()
    path.addText(0.0, 0.0, font, t.text)

    xf = QTransform()
    xf.translate(t.anchor_x, t.anchor_y)
    if t.rotation:
        xf.rotate(-t.rotation)     # scene is y-down: CCW display = negative Qt angle
    xf.scale(t.size_mm / cap, t.size_mm / cap)
    return xf.map(path)


def text_bbox_center(t: TextObject) -> tuple[float, float]:
    """Center (scene mm) of the rendered glyph footprint of *t*."""
    c = text_outline_path(t).boundingRect().center()
    return c.x(), c.y()


def normalize_rotation(deg: float) -> float:
    """Fold an angle into (-180, 180] so the Edit Text dialog shows the
    short form (170°, not 530° or -190°)."""
    r = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if r == -180.0 else r


def mirror_text(t: TextObject, axis_x: float = 0.0,
                horizontal: bool = False) -> TextObject:
    """Mirror a TextObject across the same axis ``geometry.mirror_curve`` uses
    -- but readable.

    A true reflection of lettering is mirror writing, which no temple wants
    engraved. The copy therefore keeps its glyphs unreflected and instead:

    * lands on the reflected footprint (the glyph bounding box is mirrored
      and the copy is centered on it), and
    * has its rotation transformed so the text's "up" side follows the
      reflection. On a temple that is the side facing the brow edge: the
      right temple's engraving sits at rotation 180 (drawn hinge-left,
      brow-down), the left temple's at 0, and each reads upright from the
      outside when worn. Reading direction reverses as a consequence.

    horizontal=False: vertical axis at x = axis_x (rotation -> -rotation).
    horizontal=True : horizontal axis at y = 0 (rotation -> 180 - rotation).
    """
    rot = normalize_rotation(180.0 - t.rotation if horizontal else -t.rotation)
    cx, cy = text_bbox_center(t)
    if horizontal:
        tx, ty = cx, -cy
    else:
        tx, ty = 2.0 * axis_x - cx, cy
    probe = replace(t, rotation=rot, anchor_x=0.0, anchor_y=0.0)
    px, py = text_bbox_center(probe)
    return replace(t, rotation=rot, anchor_x=tx - px, anchor_y=ty - py)


def text_to_curves(t: TextObject) -> list[Curve]:
    """Convert a TextObject to closed spline Curves (one per letter outline
    or counter-shape). Used at DXF-export time; results are transient."""
    path = text_outline_path(t)
    curves: list[Curve] = []
    nodes: list[SplineNode] = []

    def _flush():
        nonlocal nodes
        if len(nodes) >= 2:
            # addText subpaths repeat the start point as the last element —
            # fold it into the first node so 'closed' doesn't double it.
            # build_path's closing segment uses last.cp_out + first.cp_in,
            # so a curved closing element's cp_in must move to the first node.
            first, last = nodes[0], nodes[-1]
            if abs(first.x - last.x) < 1e-9 and abs(first.y - last.y) < 1e-9:
                if last.cp_in is not None:
                    first.cp_in = last.cp_in
                nodes.pop()
            if len(nodes) >= 2:
                curves.append(Curve(kind="spline", layer=t.layer, nodes=nodes,
                                    closed=True, line_weight=t.line_weight))
        nodes = []

    i = 0
    n = path.elementCount()
    while i < n:
        el = path.elementAt(i)
        if el.type == QPainterPath.ElementType.MoveToElement:
            _flush()
            nodes.append(SplineNode(x=el.x, y=el.y))
            i += 1
        elif el.type == QPainterPath.ElementType.LineToElement:
            nodes.append(SplineNode(x=el.x, y=el.y))
            i += 1
        else:   # CurveToElement: c1 (el), c2 (el+1), endpoint (el+2)
            c1 = path.elementAt(i)
            c2 = path.elementAt(i + 1)
            ep = path.elementAt(i + 2)
            if nodes:
                nodes[-1].cp_out = ControlPoint(c1.x, c1.y)
            nodes.append(SplineNode(x=ep.x, y=ep.y,
                                    cp_in=ControlPoint(c2.x, c2.y)))
            i += 3
    _flush()
    return curves
