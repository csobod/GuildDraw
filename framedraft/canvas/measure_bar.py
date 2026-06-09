"""
MeasureBar — exact-measurement input overlay.

Shown at the bottom of CanvasView when a draw tool is active and at least
one node has been placed.  Allows the user to type an exact length + angle
(line mode) or an exact radius (circle / arc mode) and press Enter to
place the next geometry without lifting the mouse.

Two modes
---------
  show_line()   — Length (mm) + Angle (°) fields; Enter places the next node.
  show_radius() — Radius or Diameter (mm) field; Enter confirms the circle
                  radius (circle) or locks the radius for arc placement.

Keyboard
--------
  Typing digits while canvas has focus redirects to the Length field via
  DrawTool.handle_key → MeasureBar.start_length_input().
  Tab  in Length  → focus Angle.
  Enter in Length → focus Angle (if empty), else commit.
  Enter in Angle  → commit line placement.
  Enter in Radius → commit radius.
  Esc  in any field → return focus to canvas.
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
    commit_line(float, float)  — (length_mm, angle_deg) ready to place
    commit_radius(float)       — radius_mm ready to confirm
    """

    commit_line   = Signal(float, float)
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

        # ── Line mode ──────────────────────────────────────────────────
        self._lbl_len   = QLabel("Length:")
        self._lbl_len.setStyleSheet(self._STYLE_LABEL)

        self._len_edit  = _NumEdit(90)
        self._len_edit.setStyleSheet(self._STYLE_EDIT)
        self._len_edit.setPlaceholderText("—")
        self._len_edit.setToolTip(
            "Exact segment length (mm). Press Tab to move to Angle field.")

        self._lbl_mm    = QLabel("mm")
        self._lbl_mm.setStyleSheet(self._STYLE_LABEL)

        self._lbl_angle = QLabel("Angle:")
        self._lbl_angle.setStyleSheet(self._STYLE_LABEL)

        self._angle_edit = _NumEdit(75)
        self._angle_edit.setStyleSheet(self._STYLE_EDIT)
        self._angle_edit.setPlaceholderText("—")
        self._angle_edit.setToolTip(
            "Segment angle in degrees (0°=right, CCW+). Press Enter to place node.")

        self._lbl_deg   = QLabel("°")
        self._lbl_deg.setStyleSheet(self._STYLE_LABEL)

        self._line_widgets = [
            self._lbl_len, self._len_edit, self._lbl_mm,
            self._lbl_angle, self._angle_edit, self._lbl_deg,
        ]

        # ── Radius mode ────────────────────────────────────────────────
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

        self._radius_widgets = [
            self._lbl_rad, self._rad_edit, self._lbl_rad_mm, self._diam_btn,
        ]

        # ── Shared hint ────────────────────────────────────────────────
        self._hint = QLabel("↵ place  |  Esc = back to canvas")
        self._hint.setStyleSheet(self._STYLE_HINT)

        for w in self._line_widgets + self._radius_widgets + [self._hint]:
            layout.addWidget(w)
        layout.addStretch()

        # Tab order: Length → Angle
        self.setTabOrder(self._len_edit, self._angle_edit)

        # Enter / Esc wiring
        self._len_edit.confirmed.connect(self._on_len_confirmed)
        self._len_edit.escaped.connect(self._return_focus_to_canvas)
        self._angle_edit.confirmed.connect(self._commit_line)
        self._angle_edit.escaped.connect(self._return_focus_to_canvas)
        self._rad_edit.confirmed.connect(self._commit_radius)
        self._rad_edit.escaped.connect(self._return_focus_to_canvas)

        self._use_diameter  = False
        self._last_radius   = 0.0

        self.hide()

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def show_line(self):
        """Switch to line mode and show the bar."""
        for w in self._radius_widgets:
            w.hide()
        for w in self._line_widgets:
            w.show()
        self._hint.show()
        self._reposition()
        self.show()
        self.raise_()

    def show_radius(self):
        """Switch to radius mode and show the bar."""
        for w in self._line_widgets:
            w.hide()
        for w in self._radius_widgets:
            w.show()
        self._hint.show()
        self._reposition()
        self.show()
        self.raise_()

    def hide_bar(self):
        """Hide the bar and clear all fields."""
        self._len_edit.clear()
        self._angle_edit.clear()
        self._rad_edit.clear()
        self._diam_btn.setChecked(False)
        self.hide()

    # ------------------------------------------------------------------
    # Live updates (called from tools on mouse move)
    # ------------------------------------------------------------------

    def update_line(self, length_mm: float, angle_deg: float):
        """Refresh Length and Angle fields when they are not user-focused."""
        if not self._len_edit.hasFocus():
            self._len_edit.setText(f"{length_mm:.2f}")
        if not self._angle_edit.hasFocus():
            self._angle_edit.setText(f"{angle_deg:.1f}")

    def update_radius(self, radius_mm: float):
        """Refresh Radius field when it is not user-focused."""
        self._last_radius = radius_mm
        if not self._rad_edit.hasFocus():
            display = radius_mm * 2.0 if self._use_diameter else radius_mm
            self._rad_edit.setText(f"{display:.2f}")

    def clear_inputs(self):
        """Clear user-typed locks; live updates resume for unfocused fields."""
        if not self._len_edit.hasFocus():
            self._len_edit.clear()
        if not self._angle_edit.hasFocus():
            self._angle_edit.clear()
        if not self._rad_edit.hasFocus():
            self._rad_edit.clear()

    # ------------------------------------------------------------------
    # Programmatic focus (called from DrawTool.handle_key)
    # ------------------------------------------------------------------

    def start_length_input(self, char: str):
        """Focus the Length field and seed it with *char* (from canvas key press)."""
        if not self.isVisible():
            return
        self._len_edit.clear()
        self._len_edit.setText(char)
        self._len_edit.setFocus()
        self._len_edit.setCursorPosition(len(char))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_len_confirmed(self):
        """Enter in Length field: go to Angle field if empty, else commit."""
        if not self._angle_edit.text().strip():
            self._angle_edit.setFocus()
        else:
            self._commit_line()

    def _commit_line(self):
        length = _parse_float(self._len_edit.text())
        angle  = _parse_float(self._angle_edit.text())
        if length is None or angle is None:
            return
        if length <= 0:
            return
        self.commit_line.emit(length, angle)

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
