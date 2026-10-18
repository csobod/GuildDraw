"""Shared SVG icon rendering.

Recolors a ``currentColor`` SVG into a two-state QIcon (Off/On), so a
checkable button shows one color when idle and another when checked. Kept
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
_RENDER_DPR = 2.0 # rasterize at 2× and tag the pixmap so HiDPI screens get
                  # a sharp glyph instead of an upscaled 20 px one


def make_icon(name: str, normal_color: str, checked_color: str,
              rotation: int = 0, selected_color: str | None = None) -> QIcon:
    """Render ``resources/icons/<name>.svg`` at two colors for off/on states,
    and in the theme's disabled ink for the Disabled mode: left to Qt, a
    disabled glyph was a whitened copy, brighter than an enabled one in dark
    mode.

    rotation: clockwise degrees to rotate the pixmap (0, 90, 180, 270).
    selected_color: the glyph on a selected row of a list or tree. Left to Qt,
    it was tinted with the highlight it sits on, and all but vanished.
    Returns an empty QIcon if the SVG is missing (callers that care already
    guard on ``ICONS_DIR/<name>.svg`` existence).
    """
    from . import theme
    icon = QIcon()
    try:
        src = (ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8")
    except OSError:
        return icon
    off = theme.color("chrome.disabled_ink")
    looks = [(normal_color,  QIcon.State.Off, QIcon.Mode.Normal),
             (checked_color, QIcon.State.On,  QIcon.Mode.Normal),
             (off, QIcon.State.Off, QIcon.Mode.Disabled),
             (off, QIcon.State.On,  QIcon.Mode.Disabled)]
    if selected_color:
        looks += [(selected_color, QIcon.State.Off, QIcon.Mode.Selected),
                  (selected_color, QIcon.State.On,  QIcon.Mode.Selected)]
    for color, state, mode in looks:
        renderer = QSvgRenderer(src.replace("currentColor", color).encode())
        side = round(_RENDER_PX * _RENDER_DPR)
        px = QPixmap(side, side)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        renderer.render(p)
        p.end()
        if rotation:
            # A bare rotate() auto-sizes the output to contain the rotated
            # content (stays square for 90°/270°); do NOT wrap with
            # translate()…translate() — that shifts the canvas.
            px = px.transformed(QTransform().rotate(rotation),
                                Qt.TransformationMode.SmoothTransformation)
        px.setDevicePixelRatio(_RENDER_DPR)
        icon.addPixmap(px, mode, state)
    return icon


def make_pixmap(name: str, color: str, size: int = 16) -> QPixmap:
    """Single-color pixmap of an icon (for a QLabel used as a static glyph)."""
    return make_icon(name, color, color).pixmap(QSize(size, size))
