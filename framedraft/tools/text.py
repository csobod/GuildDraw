"""Text tool (M8) — click an anchor point, fill in the placement dialog,
get a re-editable TextObject on the ENGRAVING layer.

The same dialog re-opens when a TextItem is double-clicked (pre-filled,
with anchor coordinates editable for precise placement).
"""
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLineEdit,
)

from ..document import Layer, TextObject
from ..fontpicker import FontFilterCombo


class TextDialog(QDialog):
    """Placement / re-edit dialog for one TextObject."""

    def __init__(self, parent=None, text_obj: TextObject | None = None):
        super().__init__(parent)
        self.setWindowTitle("Engraving Text" if text_obj is None else "Edit Text")
        lay = QFormLayout(self)

        self._text_edit = QLineEdit(text_obj.text if text_obj else "")
        lay.addRow("Text:", self._text_edit)

        self._font_combo = FontFilterCombo(
            family=text_obj.family if text_obj else "")
        self._font_combo.setToolTip(
            "Type to filter — the list narrows to the families that match, so "
            "a weight\nor an italic is one glance away instead of a scroll. "
            "The arrow re-filters\non what's in the box, showing the current "
            "family's siblings.")
        lay.addRow("Font:", self._font_combo)

        # Ranges cover what Transform can produce (a 0.1 mm floor, no cap on
        # scale-up or on where a scaled anchor lands); the old 1–50 mm and
        # ±1000 mm limits clamped a transformed text on a plain OK.
        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(0.1, 10000.0)
        self._size_spin.setDecimals(3)
        self._size_spin.setSingleStep(0.5)
        self._size_spin.setSuffix(" mm")
        self._size_spin.setToolTip("Capital-letter height in mm (true scale).")
        self._size_spin.setValue(text_obj.size_mm if text_obj else 5.0)
        lay.addRow("Size:", self._size_spin)

        self._rot_spin = QDoubleSpinBox()
        self._rot_spin.setRange(-360.0, 360.0)
        self._rot_spin.setSingleStep(5.0)
        self._rot_spin.setSuffix(" °")
        self._rot_spin.setToolTip("Positive rotates counter-clockwise.")
        self._rot_spin.setValue(text_obj.rotation if text_obj else 0.0)
        lay.addRow("Rotation:", self._rot_spin)

        self._x_spin = QDoubleSpinBox()
        self._x_spin.setRange(-100000.0, 100000.0)
        self._x_spin.setDecimals(3)
        self._x_spin.setSuffix(" mm")
        self._y_spin = QDoubleSpinBox()
        self._y_spin.setRange(-100000.0, 100000.0)
        self._y_spin.setDecimals(3)
        self._y_spin.setSuffix(" mm")
        if text_obj:
            self._x_spin.setValue(text_obj.anchor_x)
            self._y_spin.setValue(text_obj.anchor_y)
            lay.addRow("Anchor X:", self._x_spin)
            lay.addRow("Anchor Y:", self._y_spin)

        # A spin box rounds to its decimals and clamps to its range, so even
        # the wider ranges cannot show every float a .gdraw file may hold.
        # Keep the exact stored values and return them for any field the
        # maker leaves as shown: OK on an untouched field changes nothing.
        self._exact: dict = {}
        if text_obj:
            for key, spin, v in (("size_mm", self._size_spin, text_obj.size_mm),
                                 ("rotation", self._rot_spin, text_obj.rotation),
                                 ("anchor_x", self._x_spin, text_obj.anchor_x),
                                 ("anchor_y", self._y_spin, text_obj.anchor_y)):
                self._exact[key] = (spin.value(), v)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addRow(btns)
        self._text_edit.setFocus()

    def _value(self, key: str, spin: QDoubleSpinBox) -> float:
        shown, exact = self._exact.get(key, (None, None))
        return exact if shown is not None and spin.value() == shown else spin.value()

    def values(self) -> dict:
        return {
            "text":     self._text_edit.text(),
            "family":   self._font_combo.current_family(),
            "size_mm":  self._value("size_mm", self._size_spin),
            "rotation": self._value("rotation", self._rot_spin),
            "anchor_x": self._value("anchor_x", self._x_spin),
            "anchor_y": self._value("anchor_y", self._y_spin),
        }


class TextTool(QObject):
    """Click-to-place text tool. Follows the DrawTool handle_* interface so
    CanvasView routes events to it unchanged."""

    text_added     = Signal(object)   # TextObject
    canceled      = Signal()
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene  = None
        self._view   = None
        self._snap   = None
        self._layer  = Layer.ENGRAVING
        self._parent_widget = parent

    @property
    def active(self) -> bool:
        return self._scene is not None

    def activate(self, layer: Layer, scene, view, snap=None):
        self._layer = layer
        self._scene = scene
        self._view  = view
        self._snap  = snap      # the anchor click snaps like Draw and Dim do
        self.status_message.emit(
            "Text: click the baseline-left anchor point for the engraving text  |  Esc to cancel"
        )

    def deactivate(self):
        if self._snap is not None:
            self._snap.hide()
        self._scene = None
        self._view  = None
        self._snap  = None

    # ── CanvasView tool interface ────────────────────────────────────────

    def handle_press(self, pos: QPointF, use_snap: bool = True,
                     constrain: bool = False):
        if not self.active:
            return
        if self._snap is not None:
            pos = self._snap.snap(pos, [], self._view, use_snap)
        dlg = TextDialog(self._parent_widget)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        dlg.deleteLater()        # one use; read below, deleted after this handler
        if not accepted:
            self.canceled.emit()
            return
        v = dlg.values()
        if not v["text"].strip():
            self.canceled.emit()
            return
        self.text_added.emit(TextObject(
            text=v["text"], family=v["family"], size_mm=v["size_mm"],
            rotation=v["rotation"], anchor_x=pos.x(), anchor_y=pos.y(),
            layer=self._layer,
        ))

    def handle_move(self, pos: QPointF, use_snap: bool = True,
                    constrain: bool = False):
        if self.active and self._snap is not None:
            self._snap.snap(pos, [], self._view, use_snap)   # indicator only

    def handle_dbl_click(self, pos: QPointF, use_snap: bool = True,
                         constrain: bool = False):
        pass

    def handle_key(self, key, text: str = "") -> bool:
        if key == Qt.Key.Key_Escape:
            self.canceled.emit()
            return True
        return False

    def cancel(self):
        self.canceled.emit()
