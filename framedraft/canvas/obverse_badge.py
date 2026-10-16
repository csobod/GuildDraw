"""ObverseBadge — the corner chip of View Obverse (BUILDPLAN *Road to 2.0*,
item 8).

While a workspace's view is mirrored to show the drawing's other face, this
chip sits in the canvas's top-left corner: the View Obverse glyph, the word
*Obverse*, and under it the face now toward the viewer (a front's posterior,
a temple's anterior). It is a child of the view, outside the scene and its
transform, so it never mirrors with the drawing, and it lets every click
through to the canvas. In the default view a quiet label in the same corner
names the face the drawing is seen from.
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..icons import make_pixmap

_MARGIN_PX = 8          # from the viewport's top-left corner
_ICON_PX   = 18


class ObverseBadge(QWidget):
    """``Obverse`` over the face toward the viewer, in a HUD chip."""

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName("ObverseBadge")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFont(QFont("Segoe UI", 10))

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 10, 4)
        row.setSpacing(6)
        self._glyph = QLabel()
        self._glyph.setFixedSize(QSize(_ICON_PX, _ICON_PX))
        row.addWidget(self._glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._title = QLabel("Obverse")
        self._face = QLabel("")
        self._face.setProperty("hudRole", "hint")
        col.addWidget(self._title)
        col.addWidget(self._face)
        row.addLayout(col)

        self.refresh_theme()
        self.hide()

    def refresh_theme(self):
        """The HUD chip's own tokens (theme.build_hud_qss), as the measure
        chip uses them; the glyph and the face in the HUD accent."""
        # The face is what the chip is for: in the accent, not the muted
        # hint gray, though smaller than the word above it.
        self.setStyleSheet(
            theme.build_hud_qss("#ObverseBadge")
            + '#ObverseBadge QLabel[hudRole="hint"] { font-size: 9px; '
            f'color: {theme.color("hud.accent")}; }}')
        self._glyph.setPixmap(make_pixmap("view-obverse",
                                          theme.color("hud.accent"), _ICON_PX))

    def face(self) -> str:
        return self._face.text()

    def set_face(self, face: str):
        """The face toward the viewer while the view is mirrored."""
        self._face.setText(face)
        self._face.setVisible(bool(face))
        self.adjustSize()

    def reposition(self):
        """Pin the chip to the viewport's top-left corner; the view calls this
        on every resize."""
        view = self.parent()
        if view is None:
            return
        self.adjustSize()
        vp = view.viewport().geometry()
        self.move(vp.left() + _MARGIN_PX, vp.top() + _MARGIN_PX)
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
            "#QuietFaceLabel { background: transparent; font-size: 10px; "
            f"color: {theme.color('chrome.muted')}; }}")
        self.adjustSize()

    def reposition(self):
        view = self.parent()
        if view is None:
            return
        self.adjustSize()
        vp = view.viewport().geometry()
        self.move(vp.left() + _MARGIN_PX + 2, vp.top() + _MARGIN_PX - 2)
        self.raise_()
