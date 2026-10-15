"""A collapsible section: a header the maker clicks to fold its contents away.

GuildModel's convention (its ``gui/widgets/collapsible.py``, BUILDPLAN M20
there), brought to GuildDraw's Properties dock in *Road to 2.0*, item 5, so
the two apps' docks fold alike: a flat ``QToolButton`` with an arrow and the
title, over a bare body that a builder lays out exactly as it laid out the
``QGroupBox`` it replaces. Folded, only the header shows; the state is the
button's checked state, so it can be saved and restored like any other.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleBox(QWidget):
    """``box = CollapsibleBox("Frame Fill"); form = QFormLayout(box.body)``."""

    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None,
                 *, expanded: bool = True) -> None:
        super().__init__(parent)
        self.header = QToolButton(self)
        self.header.setObjectName("collapsibleHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  self.header.sizePolicy().verticalPolicy())
        self.body = QWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.header.toggled.connect(self._on_toggled)
        self._on_toggled(expanded)

    def _on_toggled(self, on: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if on
                                 else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)
        self.toggled.emit(on)

    def set_expanded(self, on: bool) -> None:
        self.header.setChecked(on)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def title(self) -> str:
        return self.header.text()

    def set_title(self, title: str) -> None:
        self.header.setText(title)
