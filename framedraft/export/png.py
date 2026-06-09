"""PNG render — composite of face image + geometry at a chosen DPI."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter


def render_png(scene, path: str, dpi: float = 150) -> None:
    """
    Render the full scene to a PNG at the specified DPI.
    Construction guides are part of the scene and will be included unless
    the caller hides them first.
    """
    rect  = scene.sceneRect()
    px_w  = max(1, int(rect.width()  * dpi / 96))   # 96 scene-units/inch arbitrary
    px_h  = max(1, int(rect.height() * dpi / 96))

    img = QImage(px_w, px_h, QImage.Format.Format_ARGB32)
    img.fill(0xFFFAF6EE)   # canvas warm off-white

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(0, 0, px_w, px_h), rect)
    painter.end()

    img.save(path)
