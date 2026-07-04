"""Shared SVG icon rendering.

Recolors a ``currentColor`` SVG into a two-state QIcon (Off/On), so a
checkable button shows one colour when idle and another when checked. Kept
out of app.py so the snap palette (and any future widget) can build icons
without importing the main window — that would be circular.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer

ICONS_DIR = Path(__file__).parent / "resources" / "icons"

_RENDER_PX = 20   # icons are authored on a 20×20 viewBox


def make_icon(name: str, normal_color: str, checked_color: str,
              rotation: int = 0) -> QIcon:
    """Render ``resources/icons/<name>.svg`` at two colours for off/on states.

    rotation: clockwise degrees to rotate the pixmap (0, 90, 180, 270).
    Returns an empty QIcon if the SVG is missing (callers that care already
    guard on ``ICONS_DIR/<name>.svg`` existence).
    """
    icon = QIcon()
    try:
        src = (ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8")
    except OSError:
        return icon
    for color, state in ((normal_color,  QIcon.State.Off),
                         (checked_color, QIcon.State.On)):
        renderer = QSvgRenderer(src.replace("currentColor", color).encode())
        px = QPixmap(_RENDER_PX, _RENDER_PX)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        renderer.render(p)
        p.end()
        if rotation:
            # A bare rotate() auto-sizes the output to contain the rotated
            # content (stays 20×20 for 90°/270° on a square); do NOT wrap with
            # translate()…translate() — that shifts the canvas.
            px = px.transformed(QTransform().rotate(rotation),
                                Qt.TransformationMode.SmoothTransformation)
        icon.addPixmap(px, QIcon.Mode.Normal, state)
    return icon


def make_pixmap(name: str, color: str, size: int = 16) -> QPixmap:
    """Single-colour pixmap of an icon (for a QLabel used as a static glyph)."""
    return make_icon(name, color, color).pixmap(QSize(size, size))
