"""Print Front + Temples — 1:1 cutting templates.

Lays the frame front and both temples out at true size (1 mm = 1 mm on
paper) on the maker's own paper size, for the hand-made workflow: print,
cut the pieces out, glue them to the blank and saw to the line. Everything
is drawn as vectors in each layer's print ink at a uniform line weight, so
the outline is as crisp as the printer can make it.

The pieces stack down the page, centered, front first; a piece that will not
fit under the previous one starts a new page. A piece larger than the page
still gets a page of its own and is cropped at the margin — the maker is
told so. Every page carries a tick-marked ruler to verify the print scale
and a page counter.

Painting is device-agnostic (``paint_template_page`` takes any QPainter with
a device-pixel origin at the page's top-left), so the printer, the PDF
writer and the tests all drive the same code.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF, QMarginsF, QSizeF
from PySide6.QtGui import (QPainter, QPen, QColor, QFont, QFontMetricsF,
                           QPageSize, QPageLayout)

from ..canvas.items import build_path

# key -> (label, width_mm, height_mm) in PORTRAIT.
PAPER_SIZES: dict[str, tuple[str, float, float]] = {
    "letter":      ("US Letter (8.5 × 11 in)",    215.9, 279.4),
    "legal":       ("US Legal (8.5 × 14 in)",     215.9, 355.6),
    "tabloid":     ("Tabloid (11 × 17 in)",       279.4, 431.8),
    "a4":          ("A4",                         210.0, 297.0),
    "a3":          ("A3",                         297.0, 420.0),
    "a5":          ("A5",                         148.0, 210.0),
    "half_letter": ("Half Letter (5.5 × 8.5 in)", 139.7, 215.9),
}
_QT_PAGE_IDS = {
    "letter":  QPageSize.PageSizeId.Letter,
    "legal":   QPageSize.PageSizeId.Legal,
    "tabloid": QPageSize.PageSizeId.Tabloid,
    "a4":      QPageSize.PageSizeId.A4,
    "a3":      QPageSize.PageSizeId.A3,
    "a5":      QPageSize.PageSizeId.A5,
}
ORIENTATIONS = ("auto", "portrait", "landscape")

COMPONENT_ORDER  = ("front", "temple_r", "temple_l")
COMPONENT_LABELS = {"front": "Frame Front", "temple_r": "Temple R",
                    "temple_l": "Temple L"}

MARGIN_MM       = 10.0    # page edge → printable area (covers most printers' dead zone)
GAP_MM          = 10.0    # between stacked pieces
LABEL_MM        = 5.0     # room above a piece for its name
RULER_STRIP_MM  = 14.0    # reserved along the bottom for ruler + note + page counter
_INK            = "#000000"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def component_bbox(component: dict):
    """(min_x, min_y, max_x, max_y) of what a component DRAWS — the exact
    curve extents (not the Bézier handles) and the text outlines — or None
    when it has nothing to print. Exact bounds matter here: the pieces are
    packed at 1:1 and a label sits right above each one."""
    rect = QRectF()
    for c in component.get("curves") or []:
        if c.nodes:
            rect = rect.united(build_path(c).boundingRect())
    texts = component.get("texts") or []
    if texts:
        from ..textpath import text_outline_path
        for t in texts:
            rect = rect.united(text_outline_path(t).boundingRect())
    if rect.isNull():
        return None
    return (rect.left(), rect.top(), rect.right(), rect.bottom())


def component_sizes(components: dict) -> list:
    """[(key, bbox, w, h)] for the components that have something to print,
    in stacking order."""
    out = []
    for key in COMPONENT_ORDER:
        comp = components.get(key)
        if not comp:
            continue
        bb = component_bbox(comp)
        if bb is None:
            continue
        out.append((key, bb, bb[2] - bb[0], bb[3] - bb[1]))
    return out


def printable_area(page_w_mm: float, page_h_mm: float) -> tuple[float, float]:
    """(width, height) of the area the pieces may occupy on one page."""
    return (page_w_mm - 2 * MARGIN_MM,
            page_h_mm - 2 * MARGIN_MM - RULER_STRIP_MM)


def layout_pages(sizes: list, avail_w: float, avail_h: float,
                 label_h: float = LABEL_MM, gap: float = GAP_MM) -> list:
    """Stack pieces down the page at 1:1, centered, spilling onto further
    pages as needed.

    sizes:   [(key, bbox, w, h)] in stacking order (see component_sizes).
    Returns: [[(key, x, y), ...] per page] where (x, y) is where the piece's
             bbox top-left lands, in mm from the printable area's top-left.
             *label_h* mm are kept free above every piece for its name.

    A piece taller or wider than the area still gets a page of its own
    (it will be cropped); the caller checks pages_clipped() to say so.
    """
    pages: list = []
    page:  list = []
    y = 0.0
    for key, _bb, w, h in sizes:
        need = label_h + h
        if page and y + need > avail_h + 1e-9:
            pages.append(page)
            page, y = [], 0.0
        x = max(0.0, (avail_w - w) / 2.0)
        page.append((key, x, y + label_h))
        y += need + gap
    if page:
        pages.append(page)
    return pages


def pages_clipped(sizes: list, avail_w: float, avail_h: float,
                  label_h: float = LABEL_MM) -> bool:
    """True when at least one piece is larger than the printable area."""
    return any(w > avail_w + 1e-9 or h + label_h > avail_h + 1e-9
               for _k, _bb, w, h in sizes)


def resolve_page(settings: dict, sizes: list) -> tuple[float, float, str]:
    """(page_w_mm, page_h_mm, orientation) for the paper in *settings*.

    ``orientation == "auto"`` picks whichever way round needs fewer pages;
    on a tie, the one that fits the widest piece, then landscape (a frame
    front is wider than it is tall).
    """
    key = settings.get("paper", "letter")
    _label, pw, ph = PAPER_SIZES.get(key, PAPER_SIZES["letter"])
    orient = settings.get("orientation", "auto")
    if orient not in ORIENTATIONS:
        orient = "auto"
    if orient == "portrait":
        return pw, ph, orient
    if orient == "landscape":
        return ph, pw, orient

    def score(w, h):
        aw, ah = printable_area(w, h)
        n = len(layout_pages(sizes, aw, ah)) if sizes else 1
        widest = max((s[2] for s in sizes), default=0.0)
        return (n, 0 if widest <= aw else 1)

    land, port = score(ph, pw), score(pw, ph)
    if port < land:
        return pw, ph, "portrait"
    return ph, pw, "landscape"


# ---------------------------------------------------------------------------
# Painting
# ---------------------------------------------------------------------------

def _layer_pen(layer, lw_mm: float, px_per_mm: float) -> QPen:
    # Always the light-mode (print) layer inks — dark-mode inks are pale and
    # would wash out on white paper. Cosmetic: constant width on paper
    # regardless of the mm transform the painter is under.
    from .. import theme
    pen = QPen(QColor(theme.default_layer_color(layer.value, False)))
    pen.setCosmetic(True)
    pen.setWidthF(lw_mm * px_per_mm)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _small_font(px_per_mm: float, mm: float) -> QFont:
    font = QFont("Helvetica")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(max(1, round(mm * px_per_mm)))
    return font


def _draw_ruler(painter: QPainter, px_per_mm: float, x_mm: float,
                y_mm: float, length_mm: float) -> None:
    """Tick-marked ruler: baseline at y_mm, ticks upward every 10 mm,
    numbers beneath. Device-pixel painter."""
    ink = QColor(_INK)
    pen = QPen(ink)
    pen.setWidthF(0.3 * px_per_mm)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    x0, y0 = x_mm * px_per_mm, y_mm * px_per_mm
    painter.drawLine(QPointF(x0, y0), QPointF(x0 + length_mm * px_per_mm, y0))
    painter.setFont(_small_font(px_per_mm, 2.6))
    mm = 0
    while mm <= length_mm + 1e-9:
        x = x0 + mm * px_per_mm
        tall = mm % 50 == 0
        painter.drawLine(QPointF(x, y0),
                         QPointF(x, y0 - (3.0 if tall else 1.5) * px_per_mm))
        if tall:
            label = f"{mm:d}" if mm else "0"
            if mm == length_mm:
                label += " mm"
            painter.drawText(QRectF(x - 20 * px_per_mm, y0 + 0.5 * px_per_mm,
                                    40 * px_per_mm, 3.5 * px_per_mm),
                             int(Qt.AlignmentFlag.AlignHCenter
                                 | Qt.AlignmentFlag.AlignTop), label)
        mm += 10


def paint_template_page(painter: QPainter, px_per_mm: float,
                        page_w_mm: float, page_h_mm: float,
                        placements: list, components: dict, settings: dict,
                        footer: str = "") -> None:
    """Paint one page of the template print onto *painter* (device space,
    top-left origin at the page corner).

    placements: one entry of layout_pages() — [(key, x, y)] in mm from the
                printable area's top-left.
    components: {key: {"curves": [Curve], "texts": [TextObject]}} scene mm.
    settings:   the "template_print" prefs dict (line_weight_mm, labels).
    footer:     right-aligned text in the ruler strip ("NAME · page 1 of 2").
    """
    lw     = float(settings.get("line_weight_mm", 0.35))
    labels = bool(settings.get("labels", True))
    ink    = QColor(_INK)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # ── the pieces, in mm — clipped to the printable area so an oversized
    # piece is cropped at the margin instead of running over the ruler ──
    avail_w, avail_h = printable_area(page_w_mm, page_h_mm)
    painter.save()
    painter.scale(px_per_mm, px_per_mm)
    painter.translate(MARGIN_MM, MARGIN_MM)
    painter.setClipRect(QRectF(0.0, 0.0, avail_w, avail_h))
    for key, x, y in placements:
        comp = components.get(key) or {}
        bb = component_bbox(comp)
        if bb is None:
            continue
        painter.save()
        painter.translate(x - bb[0], y - bb[1])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for c in comp.get("curves") or []:
            painter.setPen(_layer_pen(c.layer, lw, px_per_mm))
            painter.drawPath(build_path(c))
        texts = comp.get("texts") or []
        if texts:
            from ..textpath import text_outline_path
            for t in texts:
                painter.setPen(_layer_pen(t.layer, lw, px_per_mm))
                painter.drawPath(text_outline_path(t))
        painter.restore()
    painter.restore()

    # ── piece names (device px, so the small type stays crisp) ──
    if labels:
        painter.setPen(QPen(ink))
        painter.setFont(_small_font(px_per_mm, 3.2))
        for key, x, y in placements:
            name = COMPONENT_LABELS.get(key, key)
            left = (MARGIN_MM + x) * px_per_mm
            top  = (MARGIN_MM + y - LABEL_MM) * px_per_mm
            painter.drawText(QRectF(left, top, 120 * px_per_mm, 4.0 * px_per_mm),
                             int(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignBottom), name)

    # ── ruler strip along the bottom: note + footer on the first line, the
    # ruler with its numerals beneath (so the footer never lands on "100 mm")
    strip_top = page_h_mm - MARGIN_MM - RULER_STRIP_MM
    length = 100.0 if avail_w >= 110.0 else 50.0
    font = _small_font(px_per_mm, 2.8)
    painter.setPen(QPen(ink))
    painter.setFont(font)
    line = QRectF(MARGIN_MM * px_per_mm, strip_top * px_per_mm,
                  avail_w * px_per_mm, 4.0 * px_per_mm)
    note_w = line.width()
    if footer:
        fm = QFontMetricsF(font)
        painter.drawText(line, int(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter), footer)
        note_w = max(0.0, line.width() - fm.horizontalAdvance(footer)
                     - 4.0 * px_per_mm)
    note = (f"Scale 1:1 — measure the {length:.0f} mm ruler to verify. "
            "Print at 100 % with “fit to page” off.")
    note = QFontMetricsF(font).elidedText(note, Qt.TextElideMode.ElideRight,
                                          note_w)
    painter.drawText(QRectF(line.left(), line.top(), note_w, line.height()),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                     note)
    _draw_ruler(painter, px_per_mm, MARGIN_MM, strip_top + 8.5, length)


# ---------------------------------------------------------------------------
# Printer / PDF drivers
# ---------------------------------------------------------------------------

def configure_printer(printer, settings: dict, components: dict) -> None:
    """Set paper size and orientation from *settings* (the print dialog can
    still change them; rendering reads the final page back)."""
    key = settings.get("paper", "letter")
    if key in _QT_PAGE_IDS:
        size = QPageSize(_QT_PAGE_IDS[key])
    else:
        _label, pw, ph = PAPER_SIZES.get(key, PAPER_SIZES["letter"])
        size = QPageSize(QSizeF(pw, ph), QPageSize.Unit.Millimeter, _label)
    printer.setPageSize(size)
    _w, _h, orient = resolve_page(settings, component_sizes(components))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape
                               if orient == "landscape"
                               else QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)


def render_template_pages(printer, components: dict, settings: dict,
                          caption: str = "") -> tuple[int, bool]:
    """Paint every page onto *printer*. Returns (page_count, clipped) —
    *clipped* when a piece was larger than the printable area."""
    from PySide6.QtPrintSupport import QPrinter
    page_mm   = printer.pageRect(QPrinter.Unit.Millimeter)
    px_per_mm = printer.logicalDpiX() / 25.4
    sizes = component_sizes(components)
    avail_w, avail_h = printable_area(page_mm.width(), page_mm.height())
    pages = layout_pages(sizes, avail_w, avail_h)
    clipped = pages_clipped(sizes, avail_w, avail_h)
    # begin() fails when the PDF cannot be opened (a read-only folder) or the
    # printer refuses the job; painting on regardless produced nothing and
    # the caller still reported the pages as done.
    painter = QPainter()
    if not painter.begin(printer):
        path = printer.outputFileName()
        if path:
            raise OSError(f"could not write {path}")
        name = printer.printerName()
        raise OSError(f"could not start the print job on {name}" if name
                      else "could not start the print job")
    try:
        for i, placements in enumerate(pages):
            if i:
                printer.newPage()
            counter = f"page {i + 1} of {len(pages)}"
            footer = f"{caption}  ·  {counter}" if caption else counter
            paint_template_page(painter, px_per_mm, page_mm.width(),
                                page_mm.height(), placements, components,
                                settings, footer)
    finally:
        painter.end()
    return len(pages), clipped


def export_template_pdf(path: str, components: dict, settings: dict,
                        caption: str = "") -> tuple[int, bool]:
    """Write the template pages to *path* as a PDF; see render_template_pages."""
    from PySide6.QtPrintSupport import QPrinter
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    configure_printer(printer, settings, components)
    return render_template_pages(printer, components, settings, caption)
