"""Readiness traffic-light dot — GuildDraw's upstream mirror of GuildCAM's M5.2.

A small painted circle docked in the status-bar corner that tells the maker at
a glance whether the *current workspace* satisfies the GuildCAM export contract
before they hand off a DXF. Dot only — the gap (if any) lives in the tooltip:

    grey/off  nothing to hand off yet (no machined geometry)
    amber     machined geometry present but the handoff contract isn't met
    green     ready for GuildCAM (validator passes)

GuildCAM answers "is this job ready to cut?"; GuildDraw answers "is this design
ready to send?". The state is computed from the same validator the export path
already uses (``framedraft.export.validate.validate``), so the dot never drifts
from what export will actually allow. The indicator is non-blocking: export
still works regardless of colour — this only warns.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtCore import QSize

from ..document import MACHINED_LAYERS

# State keys.
OFF = "off"
AMBER = "amber"
GREEN = "green"

# Dot fill colours per theme: (light, dark). Kept local — GuildDraw has no
# central theme palette module.
_COLORS = {
    OFF:   ("#b8b2a3", "#5a564d"),
    AMBER: ("#e0a52e", "#e0a52e"),
    GREEN: ("#3aa657", "#46c46b"),
}

_DIAMETER = 10  # px — subtle


def readiness_state(curves: list, mirror_on: bool,
                    workspace_type: str = "front") -> tuple[str, str]:
    """Return ``(state, tooltip)`` for the workspace's handoff readiness.

    Pure function of the document — drives the dot and is unit-testable
    without Qt. Reuses the export validator so the indicator and the export
    gate can never disagree.
    """
    from ..export.validate import validate

    has_machined = any((not c.mirrored) and c.layer in MACHINED_LAYERS
                       for c in curves)
    if not has_machined:
        return OFF, "Nothing to hand off yet — draw machined geometry first"

    errors, warnings = validate(curves, mirror_on, workspace_type)
    if errors:
        return AMBER, "Not ready for GuildCAM — " + errors[0]
    if warnings:
        return GREEN, "Ready for GuildCAM (with warnings — " + warnings[0] + ")"
    return GREEN, "Ready for GuildCAM"


class ReadinessDot(QWidget):
    """A ~10 px filled circle whose colour + tooltip reflect handoff readiness."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = OFF
        self._dark = False
        self.setFixedSize(_DIAMETER + 8, _DIAMETER + 6)
        self.setToolTip("Nothing to hand off yet")

    def state(self) -> str:
        return self._state

    def set_readiness(self, state: str, tooltip: str) -> None:
        if state not in _COLORS:
            raise ValueError(f"unknown readiness state: {state!r}")
        changed = state != self._state
        self._state = state
        self.setToolTip(tooltip)
        if changed:
            self.update()

    def set_dark_mode(self, dark: bool) -> None:
        if dark == self._dark:
            return
        self._dark = dark
        self.update()

    def _color(self) -> QColor:
        light, dark = _COLORS[self._state]
        return QColor(dark if self._dark else light)

    def sizeHint(self) -> QSize:
        return QSize(_DIAMETER + 8, _DIAMETER + 6)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = self._color()
        p.setBrush(QBrush(color))
        p.setPen(QPen(color.darker(135), 1))   # faint rim, legible on any tone
        x = (self.width() - _DIAMETER) / 2
        y = (self.height() - _DIAMETER) / 2
        p.drawEllipse(int(round(x)), int(round(y)), _DIAMETER, _DIAMETER)
        p.end()
