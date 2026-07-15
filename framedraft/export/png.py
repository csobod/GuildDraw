"""PNG render — composite of face image + geometry at a chosen DPI."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

# Safety cap on the raster size (memory): a side longer than this shrinks the
# effective DPI instead of allocating a multi-hundred-MB image.
_MAX_SIDE_PX = 8192


def render_png(scene, path: str, dpi: float = 300.0,
               rect: QRectF | None = None,
               background: str = "#faf6ee") -> None:
    """
    Render *rect* (scene coords; defaults to the full sceneRect) to a PNG.

    Scene units are millimetres, so pixels = mm * dpi / 25.4 — true print
    scale (a 60 mm lens at 300 dpi is ~709 px). The old export mapped scene
    units at 96/inch, which capped a whole frame at around a thousand pixels
    regardless of the requested DPI (GitHub issue #7).

    WYSIWYG: whatever items are visible in the scene (geometry, guides,
    ghosts, face photos) are included — callers pass a tight content rect
    and hide anything they don't want first.
    """
    if rect is None or rect.isEmpty():
        rect = scene.sceneRect()

    scale = dpi / 25.4
    longest = max(rect.width(), rect.height())
    if longest * scale > _MAX_SIDE_PX:
        scale = _MAX_SIDE_PX / longest
    px_w = max(1, round(rect.width() * scale))
    px_h = max(1, round(rect.height() * scale))

    img = QImage(px_w, px_h, QImage.Format.Format_ARGB32)
    img.fill(QColor(background))

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(0, 0, px_w, px_h), rect)
    painter.end()

    img.save(path)
