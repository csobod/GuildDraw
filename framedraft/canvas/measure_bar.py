"""
MeasureBar — exact-measurement input overlay.

Shown at the bottom of CanvasView while the circle/arc tool wants a radius.
The user types an exact radius (or diameter) in mm and presses Enter to
confirm the circle radius or lock the arc radius without lifting the mouse.

(The old line mode — Length/Angle fields — was superseded by DrawTool's
cursor HUD with type-to-lock input and has been removed.)

Keyboard
--------
  Enter in Radius → commit radius.
  Esc  in the field → return focus to canvas.
"""

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)


def _parse_float(text: str) -> float | None:
    try:
        v = float(text.strip())
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


class _NumEdit(QLineEdit):
    """Single-line float editor that selects all on focus and emits signals for Enter/Esc."""

    confirmed = Signal()
    escaped   = Signal()

    def __init__(self, width_hint: int = 80, parent=None):
        super().__init__(parent)
        self.setFixedWidth(width_hint)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirmed.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.escaped.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MeasureBar(QWidget):
    """
    Measurement HUD overlay parented to CanvasView.

    Signals
    -------
    commit_radius(float) — radius_mm ready to confirm
    """

    commit_radius = Signal(float)

    _STYLE_BG = (
        "MeasureBar { background: rgba(20, 20, 20, 210); "
        "border-top: 1px solid rgba(255,255,255,40); }"
    )
    _STYLE_EDIT = (
        "QLineEdit { background: rgba(45, 45, 45, 230); color: #f0f0f0; "
        "border: 1px solid #606060; border-radius: 3px; padding: 2px 5px; }"
        "QLineEdit:focus { border-color: #ffd580; color: #ffffff; }"
    )
    _STYLE_LABEL = "QLabel { color: #bbbbbb; }"
    _STYLE_HINT  = "QLabel { color: #666666; font-size: 9px; }"
    _STYLE_BTN = (
        "QPushButton { background: rgba(55, 55, 55, 220); color: #bbbbbb; "
        "border: 1px solid #606060; border-radius: 3px; "
        "padding: 2px 8px; min-width: 0; }"
        "QPushButton:hover  { background: rgba(75, 75, 75, 220); }"
        "QPushButton:checked { background: #ffd580; color: #1f1f1f; "
        "border-color: #d4a840; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MeasureBar")
        self.setStyleSheet(self._STYLE_BG)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        font = QFont("Segoe UI", 10)
        self.setFont(font)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)

        self._lbl_rad   = QLabel("Radius:")
        self._lbl_rad.setStyleSheet(self._STYLE_LABEL)

        self._rad_edit  = _NumEdit(90)
        self._rad_edit.setStyleSheet(self._STYLE_EDIT)
        self._rad_edit.setPlaceholderText("—")
        self._rad_edit.setToolTip("Exact radius (mm). Press Enter to confirm.")

        self._lbl_rad_mm = QLabel("mm")
        self._lbl_rad_mm.setStyleSheet(self._STYLE_LABEL)

        self._diam_btn  = QPushButton("⇄ Diam")
        self._diam_btn.setCheckable(True)
        self._diam_btn.setChecked(False)
        self._diam_btn.setStyleSheet(self._STYLE_BTN)
        self._diam_btn.setToolTip("Toggle Radius ↔ Diameter display.")
        self._diam_btn.toggled.connect(self._on_diam_toggled)

        self._hint = QLabel("↵ place  |  Esc = back to canvas")
        self._hint.setStyleSheet(self._STYLE_HINT)

        for w in (self._lbl_rad, self._rad_edit, self._lbl_rad_mm,
                  self._diam_btn, self._hint):
            layout.addWidget(w)
        layout.addStretch()

        self._rad_edit.confirmed.connect(self._commit_radius)
        self._rad_edit.escaped.connect(self._return_focus_to_canvas)

        self._use_diameter  = False
        self._last_radius   = 0.0

        self.hide()

    # ------------------------------------------------------------------
    # Show / hide
    # ------------------------------------------------------------------

    def show_radius(self):
        """Show the bar (radius entry)."""
        self._reposition()
        self.show()
        self.raise_()

    def hide_bar(self):
        """Hide the bar and clear the field."""
        self._rad_edit.clear()
        self._diam_btn.setChecked(False)
        self.hide()

    # ------------------------------------------------------------------
    # Live updates (called from tools on mouse move)
    # ------------------------------------------------------------------

    def update_radius(self, radius_mm: float):
        """Refresh Radius field when it is not user-focused."""
        self._last_radius = radius_mm
        if not self._rad_edit.hasFocus():
            display = radius_mm * 2.0 if self._use_diameter else radius_mm
            self._rad_edit.setText(f"{display:.2f}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _commit_radius(self):
        val = _parse_float(self._rad_edit.text())
        if val is None or val <= 0:
            return
        radius = val / 2.0 if self._use_diameter else val
        self.commit_radius.emit(radius)

    def _on_diam_toggled(self, checked: bool):
        self._use_diameter = checked
        self._lbl_rad.setText("Diameter:" if checked else "Radius:")
        # Recompute display from last known radius
        if self._last_radius > 0:
            display = self._last_radius * 2.0 if checked else self._last_radius
            self._rad_edit.setText(f"{display:.2f}")

    def _return_focus_to_canvas(self):
        parent = self.parent()
        if parent is not None:
            parent.setFocus()

    def _reposition(self):
        """Stretch bar to full parent width and place it at the bottom."""
        parent = self.parent()
        if parent is None:
            return
        self.adjustSize()
        w = parent.width()
        h = self.sizeHint().height()
        self.setFixedWidth(w)
        self.move(0, parent.height() - h)
