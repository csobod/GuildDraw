"""Snap palette — pinnable per-type snap toggles beside the toolbar.

The Snap toolbar button stays the master on/off (and Ctrl still suspends
everything); this panel refines WHICH targets snap. It is a plain child
widget of the main window (same non-auto-hiding pattern as the pinnable
toolbar's overflow pop-out) so it stays open across operations until the
palette button is toggled off.

Kept deliberately small: a two-column grid of icon toggles (the type name
lives in the tooltip, not on the button) plus a magnet-labelled radius
field, so leaving it pinned costs little viewport.

Emits ``types_changed({key: bool})`` and ``radius_changed(px)`` — the host
applies them to every workspace's SnapEngine and persists them in prefs.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QSize, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)

from . import theme
from .icons import make_icon, make_pixmap
from .canvas.snapping import SNAP_TYPES

_RADIUS_MIN = 4
_RADIUS_MAX = 40    # two digits; a larger snap reach becomes unwieldy
_ICON_PX    = 18
_BTN_PX     = 26
_GRID_COLS  = 2


class SnapPalette(QFrame):

    types_changed  = Signal(dict)   # {type key: bool}
    radius_changed = Signal(int)    # snap radius, screen px

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.setObjectName("snapPalette")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(4)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(3)
        self._btns: dict[str, QToolButton] = {}
        self._btn_icons: dict[str, str] = {}   # key -> svg name
        for i, (key, label, tip) in enumerate(SNAP_TYPES):
            btn = QToolButton(self)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setToolTip(f"{label} — {tip}")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
            btn.setFixedSize(_BTN_PX, _BTN_PX)
            btn.toggled.connect(self._emit_types)
            self._btns[key] = btn
            self._btn_icons[key] = f"snap-{key}"
            grid.addWidget(btn, i // _GRID_COLS, i % _GRID_COLS)
        lay.addLayout(grid)

        # Radius: a magnet glyph + "r", then a compact no-arrows field.
        rad_row = QHBoxLayout()
        rad_row.setContentsMargins(0, 0, 0, 0)
        rad_row.setSpacing(3)
        rad_tip = "Radius of snap distance"
        self._mag = QLabel(self)
        self._mag.setToolTip(rad_tip)
        self._r_lbl = QLabel("r", self)
        self._r_lbl.setToolTip(rad_tip)
        self._radius = QSpinBox(self)
        self._radius.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._radius.setRange(_RADIUS_MIN, _RADIUS_MAX)
        self._radius.setValue(10)
        self._radius.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._radius.setKeyboardTracking(False)
        self._radius.setFixedWidth(30)
        self._radius.setToolTip(rad_tip)
        self._radius.valueChanged.connect(
            lambda v: self.radius_changed.emit(int(v)))
        rad_row.addWidget(self._mag)
        rad_row.addWidget(self._r_lbl)
        rad_row.addWidget(self._radius)
        rad_row.addStretch()
        rad_holder = QWidget(self)
        rad_holder.setLayout(rad_row)
        lay.addWidget(rad_holder)

        self.apply_theme()
        self.hide()

    # ------------------------------------------------------------------

    def state(self) -> dict:
        return {key: btn.isChecked() for key, btn in self._btns.items()}

    def set_state(self, types: dict, radius_px: int):
        """Install saved state without emitting change signals."""
        for key, btn in self._btns.items():
            btn.blockSignals(True)
            btn.setChecked(bool(types.get(key, True)))
            btn.blockSignals(False)
        self._radius.blockSignals(True)
        self._radius.setValue(
            max(_RADIUS_MIN, min(_RADIUS_MAX, int(radius_px))))
        self._radius.blockSignals(False)

    def _emit_types(self, _on: bool):
        self.types_changed.emit(self.state())

    # ------------------------------------------------------------------

    def apply_theme(self):
        bg     = theme.color("chrome.bg")
        border = theme.color("chrome.border")
        ink    = theme.color("chrome.ink")
        checked_bg  = theme.color("chrome.checked_bg")
        checked_ink = theme.color("chrome.checked_ink")
        self.setStyleSheet(
            f"#snapPalette {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: 4px; }}"
            f"#snapPalette QToolButton {{ min-width: 0; padding: 1px; "
            f"border: 1px solid {border}; border-radius: 3px; "
            f"background-color: {theme.color('chrome.panel')}; }}"
            f"#snapPalette QToolButton:checked {{ background-color: {checked_bg}; }}"
            f"#snapPalette QLabel {{ color: {ink}; }}"
        )
        for key, btn in self._btns.items():
            btn.setIcon(make_icon(self._btn_icons[key], ink, checked_ink))
        self._mag.setPixmap(make_pixmap("snap-radius", ink, 15))

    def reposition(self, toolbar, anchor_widget=None):
        """Place beside the toolbar, top-aligned with the anchor (the palette
        toolbar button) when it is visible, else with the toolbar top."""
        win = self.window()
        if win is None:
            return
        self.adjustSize()
        x = toolbar.mapTo(win, QPoint(toolbar.width(), 0)).x() + 2
        if anchor_widget is not None and anchor_widget.isVisible():
            y = anchor_widget.mapTo(win, QPoint(0, 0)).y()
        else:
            y = toolbar.mapTo(win, QPoint(0, 0)).y() + 4
        x = max(0, min(x, win.width() - self.width()))
        y = max(0, min(y, win.height() - self.height()))
        self.move(x, y)
