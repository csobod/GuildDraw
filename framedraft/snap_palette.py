"""Snap palette — pinnable per-type snap toggles beside the toolbar.

The Snap toolbar button stays the master on/off (and Ctrl still suspends
everything); this panel refines WHICH targets snap. It is a plain child
widget of the main window (same non-auto-hiding pattern as the pinnable
toolbar's overflow pop-out) so it stays open across operations until the
palette button is toggled off.

Emits ``types_changed({key: bool})`` and ``radius_changed(px)`` — the host
applies them to every workspace's SnapEngine and persists them in prefs.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QDoubleSpinBox,
)

from . import theme
from .canvas.snapping import SNAP_TYPES


class SnapPalette(QFrame):

    types_changed  = Signal(dict)   # {type key: bool}
    radius_changed = Signal(int)    # snap radius, screen px

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.setObjectName("snapPalette")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(2)

        title = QLabel("Snap to")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        self._btns: dict[str, QToolButton] = {}
        for key, label, tip in SNAP_TYPES:
            btn = QToolButton(self)
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setSizePolicy(btn.sizePolicy().horizontalPolicy(),
                              btn.sizePolicy().verticalPolicy())
            btn.setMinimumWidth(96)
            btn.toggled.connect(self._emit_types)
            self._btns[key] = btn
            lay.addWidget(btn)

        rad_row = QHBoxLayout()
        rad_row.setContentsMargins(0, 4, 0, 0)
        rad_row.setSpacing(4)
        rad_lbl = QLabel("Radius")
        rad_lbl.setToolTip("Snap reach in screen pixels.")
        self._radius = QDoubleSpinBox(self)
        self._radius.setRange(4, 40)
        self._radius.setDecimals(0)
        self._radius.setSuffix(" px")
        self._radius.setValue(10)
        self._radius.setKeyboardTracking(False)
        self._radius.valueChanged.connect(
            lambda v: self.radius_changed.emit(int(v)))
        rad_row.addWidget(rad_lbl)
        rad_row.addWidget(self._radius, 1)
        lay.addLayout(rad_row)

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
        self._radius.setValue(int(radius_px))
        self._radius.blockSignals(False)

    def _emit_types(self, _on: bool):
        self.types_changed.emit(self.state())

    # ------------------------------------------------------------------

    def apply_theme(self):
        bg, border = theme.color("chrome.bg"), theme.color("chrome.border")
        self.setStyleSheet(
            f"#snapPalette {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: 4px; }}"
        )

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
