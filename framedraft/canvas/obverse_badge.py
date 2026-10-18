"""ObverseBadge — the corner chip of View Obverse (BUILDPLAN *Road to 2.0*,
item 8).

While a workspace's view is mirrored to show the drawing's other face, this
chip sits in the canvas's top-left corner with the one word for the face now
toward the viewer (a front's posterior, a temple's anterior), in the HUD's
box and border. In the default view a quiet label in the same corner names
the face the drawing is seen from. The two words share their place and their
size, so toggling the view swaps the word and adds or removes the box, and
nothing moves (the maker, 2026-10-17: the earlier glyph and "Obverse" title
were a bit distracting). Both are children of the view, outside the scene and
its transform, so they never mirror with the drawing, and they let every
click through to the canvas.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .. import theme

_MARGIN_PX = 8          # from the viewport's top-left corner
# The face word's top-left in the viewport, the quiet label's and the chip's
# alike.
_TEXT_X = _MARGIN_PX + 2
_TEXT_Y = _MARGIN_PX - 2
_PAD_X, _PAD_Y = 6, 2   # the chip's room around its word
_FACE_PX = 10           # the word's size, in both


class ObverseBadge(QWidget):
    """The face toward the viewer, one word in a HUD chip."""

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName("ObverseBadge")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(_PAD_X, _PAD_Y, _PAD_X, _PAD_Y)
        row.setSpacing(0)
        self._face = QLabel("")
        row.addWidget(self._face)

        self.refresh_theme()
        self.hide()

    def refresh_theme(self):
        """The HUD chip's own tokens (theme.build_hud_qss), as the measure
        chip uses them; the word in the HUD accent, at the quiet label's
        size. The box and its border are the emphasis, not the word."""
        self.setStyleSheet(
            theme.build_hud_qss("#ObverseBadge")
            + f"#ObverseBadge QLabel {{ font-size: {_FACE_PX}px; "
            f'color: {theme.color("hud.accent")}; }}')
        self.adjustSize()

    def face(self) -> str:
        return self._face.text()

    def face_label(self) -> QLabel:
        """The word itself, for the view's alignment and for tests."""
        return self._face

    def set_face(self, face: str):
        """The face toward the viewer while the view is mirrored."""
        self._face.setText(face)
        self.adjustSize()

    def reposition(self):
        """Pin the chip so its word lands where the quiet label's does; the
        view calls this on every resize."""
        view = self.parent()
        if view is None:
            return
        self.adjustSize()
        vp = view.viewport().geometry()
        self.move(vp.left() + _TEXT_X - _PAD_X, vp.top() + _TEXT_Y - _PAD_Y)
        self.raise_()


def canvas_muted() -> str:
    """A muted ink for words on the canvas: half way from the canvas color to
    the drawing's ink, readable on any viewport preset. The chrome's muted ink
    was brown on Blueprint's navy, and faint on White in dark mode."""
    bg = QColor(theme.color("canvas.bg"))
    ink = QColor(theme.color("geometry.ink"))
    return QColor(*(round(0.45 * b + 0.55 * i) for b, i in
                    ((bg.red(), ink.red()), (bg.green(), ink.green()),
                     (bg.blue(), ink.blue())))).name()


class CanvasHint(QLabel):
    """What to do first, centered on an empty canvas: a fresh window said
    nothing, where GuildModel says "Open a DXF file to begin". Transparent to
    the mouse; hidden once there is anything on the tab."""

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName("CanvasHint")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.refresh_theme()
        self.hide()

    def refresh_theme(self):
        # On a chip of the canvas color, so the guides drawn at the center
        # never run through the words.
        bg = QColor(theme.color("canvas.bg"))
        self.setStyleSheet(
            f"#CanvasHint {{ background: rgba({bg.red()}, {bg.green()}, "
            f"{bg.blue()}, 225); border-radius: 6px; padding: 8px 12px; "
            f"font-size: 13px; color: {canvas_muted()}; }}")

    def reposition(self):
        view = self.parent()
        if view is None:
            return
        vp = view.viewport().geometry()
        w = min(440, max(160, vp.width() - 40))
        self.setFixedWidth(w)
        self.adjustSize()
        # Above the middle, where the guides and the drawing start.
        self.move(vp.left() + (vp.width() - w) // 2,
                  vp.top() + max(8, round(vp.height() * 0.12)))
        self.raise_()


class QuietFaceLabel(QLabel):
    """The default view's face, said quietly where the Obverse badge appears:
    a front's "anterior", a temple's "posterior". Small, muted, no chip, and
    transparent to the mouse; hidden while the badge shows."""

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName("QuietFaceLabel")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.refresh_theme()
        self.hide()

    def refresh_theme(self):
        self.setStyleSheet(
            f"#QuietFaceLabel {{ background: transparent; font-size: {_FACE_PX}px; "
            f"color: {canvas_muted()}; }}")
        self.adjustSize()

    def reposition(self):
        view = self.parent()
        if view is None:
            return
        self.adjustSize()
        vp = view.viewport().geometry()
        self.move(vp.left() + _TEXT_X, vp.top() + _TEXT_Y)
        self.raise_()
