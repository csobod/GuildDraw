"""PDF-for-Catalog export.

Lays the frame front and both temples out on one printable sheet with the
design's file name, for a catalog page that shows a frame and its name. The
front sits at the top, the two temples stacked beneath it, everything centred
horizontally and drawn at a uniform line weight. True size (1 mm = 1 mm on
paper) when it fits; scaled down uniformly only if the content is taller than
the page.

The painting is device-agnostic (``paint_catalog`` takes any QPainter), so the
same layout drives the PDF writer and the on-screen preview.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QMarginsF, QSizeF
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPageSize, QPageLayout

from ..canvas.items import build_path

# Paper sizes, portrait (width, height) mm; always rendered LANDSCAPE.
PAPER_MM = {
    "a5":          (148.0, 210.0),
    "half_letter": (139.7, 215.9),
}
_MARGIN_MM = 12.0
_GAP_MM    = 8.0            # vertical gap between stacked components
_CAP_GAP_MM = 6.0          # gap above the caption
_INK        = "#1a1a1a"

# The order components stack down the page.
_ORDER = ("front", "temple_r", "temple_l")


def _content_bbox(curves):
    """(min_x, min_y, max_x, max_y) over the drawn extent of *curves*, or None."""
    from ..geometry import arc_bbox
    xs, ys = [], []
    for c in curves:
        if (c.kind == "arc" and c.radius and c.nodes
                and c.start_angle is not None and c.end_angle is not None):
            bx0, by0, bx1, by1 = arc_bbox(c.nodes[0].x, c.nodes[0].y, c.radius,
                                          c.start_angle, c.end_angle)
            xs.extend([bx0, bx1]); ys.extend([by0, by1])
        elif c.kind in ("circle", "arc") and c.radius and c.nodes:
            cx, cy, r = c.nodes[0].x, c.nodes[0].y, c.radius
            xs.extend([cx - r, cx + r]); ys.extend([cy - r, cy + r])
        else:
            for n in c.nodes:
                xs.append(n.x); ys.append(n.y)
                if n.cp_in:  xs.append(n.cp_in.x);  ys.append(n.cp_in.y)
                if n.cp_out: xs.append(n.cp_out.x); ys.append(n.cp_out.y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _draw_component(painter, curves, place_x, place_y, s, bb, pen):
    """Draw *curves* so their bbox top-left lands at (place_x, place_y) mm,
    scaled by *s*. Painter is already in mm; the pen is cosmetic so the line
    weight stays constant regardless of *s*."""
    painter.save()
    painter.translate(place_x, place_y)
    painter.scale(s, s)
    painter.translate(-bb[0], -bb[1])
    painter.setPen(pen)
    for c in curves:
        painter.drawPath(build_path(c))
    painter.restore()


def paint_catalog(painter: QPainter, page_w_mm: float, page_h_mm: float,
                  px_per_mm: float, components: dict, caption: str,
                  settings: dict) -> None:
    """Paint the catalog layout onto *painter* (device space, top-left origin).

    components: {"front"|"temple_r"|"temple_l": [Curve, ...]} in scene mm.
    caption:    file-name string (already stripped of extension); "" = none.
    """
    lw   = float(settings.get("line_weight_mm", 0.6))
    font_name = settings.get("caption_font", "Courier New")
    show_caption = bool(settings.get("caption", True)) and bool(caption)
    show_scale   = bool(settings.get("show_scale", False))
    ink = QColor(_INK)

    pen = QPen(ink)
    pen.setCosmetic(True)                       # constant weight under any scale
    pen.setWidthF(lw * px_per_mm)               # device px == lw mm on paper
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)

    rows = []
    for key in _ORDER:
        curves = components.get(key) or []
        bb = _content_bbox(curves)
        if bb is None:
            continue
        rows.append((key, curves, bb, bb[2] - bb[0], bb[3] - bb[1]))
    if not rows:
        return

    avail_w = page_w_mm - 2 * _MARGIN_MM
    avail_h = page_h_mm - 2 * _MARGIN_MM

    max_w   = max(r[3] for r in rows)
    stack_h = sum(r[4] for r in rows) + _GAP_MM * (len(rows) - 1)
    cap_h   = 6.0 if show_caption else 0.0
    # The caption is pinned to the lower-right corner; the content block gets
    # the space above it and is centred there.
    cap_reserve   = (cap_h + _CAP_GAP_MM) if show_caption else 0.0
    content_avail = avail_h - cap_reserve

    s = 1.0
    if max_w > avail_w:
        s = min(s, avail_w / max_w)
    if stack_h > content_avail:
        s = min(s, content_avail / stack_h)

    painter.save()
    painter.scale(px_per_mm, px_per_mm)         # work in mm
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Centre the content block vertically in the area above the caption, then
    # apply the maker's vertical offset (for a binding/spine margin). The
    # caption is unaffected — it stays pinned to the corner below.
    offset = float(settings.get("content_offset_mm", 0.0))
    y = _MARGIN_MM + max(0.0, (content_avail - stack_h * s) / 2.0) + offset
    for _key, curves, bb, w, h in rows:
        place_x = _MARGIN_MM + (avail_w - w * s) / 2.0   # centre horizontally
        _draw_component(painter, curves, place_x, y, s, bb, pen)
        y += h * s + _GAP_MM * s
    painter.restore()

    # ── caption: file name, pinned to the lower-right corner ──
    if show_caption:
        font = QFont(font_name)
        font.setStyleHint(QFont.StyleHint.TypeWriter)   # fall back to any monospace
        font.setPointSizeF(11.0)
        painter.setFont(font)
        painter.setPen(QPen(ink))
        right_px  = (page_w_mm - _MARGIN_MM) * px_per_mm
        top_px    = (page_h_mm - _MARGIN_MM - cap_h) * px_per_mm
        h_px      = cap_h * px_per_mm
        painter.drawText(QRectF(0, top_px, right_px, h_px),
                         int(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter), caption)

    # ── optional scale note, lower-left ──
    if show_scale:
        font = QFont(font_name)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setPointSizeF(8.0)
        painter.setFont(font)
        painter.setPen(QPen(ink))
        ratio = "1:1" if abs(s - 1.0) < 1e-3 else f"1:{1.0 / s:.2f}"
        left_px   = _MARGIN_MM * px_per_mm
        bottom_px = (page_h_mm - _MARGIN_MM) * px_per_mm
        painter.drawText(QRectF(left_px, bottom_px - 20,
                                page_w_mm * px_per_mm, 20),
                         int(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignBottom),
                         f"Scale {ratio}")


def _make_printer(path: str, paper: str):
    from PySide6.QtPrintSupport import QPrinter
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    if paper == "half_letter":
        size = QPageSize(QSizeF(139.7, 215.9), QPageSize.Unit.Millimeter,
                         "Half Letter")
    else:
        size = QPageSize(QPageSize.PageSizeId.A5)
    printer.setPageSize(size)
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    return printer


def export_catalog_pdf(path: str, components: dict, settings: dict,
                       caption: str) -> None:
    """Write the catalog layout to *path* as a landscape PDF."""
    from PySide6.QtPrintSupport import QPrinter

    printer = _make_printer(path, settings.get("paper", "a5"))
    page_mm = printer.pageRect(QPrinter.Unit.Millimeter)
    px_per_mm = printer.logicalDpiX() / 25.4
    painter = QPainter(printer)
    try:
        paint_catalog(painter, page_mm.width(), page_mm.height(), px_per_mm,
                      components, caption, settings)
    finally:
        painter.end()
