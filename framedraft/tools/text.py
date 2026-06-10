"""Text tool (M8) — click an anchor point, fill in the placement dialog,
get a re-editable TextObject on the ENGRAVING layer.

The same dialog re-opens when a TextItem is double-clicked (pre-filled,
with anchor coordinates editable for precise placement).
"""
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFontComboBox, QFormLayout,
    QLineEdit,
)

from ..document import Layer, TextObject


class TextDialog(QDialog):
    """Placement / re-edit dialog for one TextObject."""

    def __init__(self, parent=None, text_obj: TextObject | None = None):
        super().__init__(parent)
        self.setWindowTitle("Engraving Text" if text_obj is None else "Edit Text")
        lay = QFormLayout(self)

        self._text_edit = QLineEdit(text_obj.text if text_obj else "")
        lay.addRow("Text:", self._text_edit)

        self._font_combo = QFontComboBox()
        if text_obj:
            self._font_combo.setCurrentFont(text_obj.family)
        lay.addRow("Font:", self._font_combo)

        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(1.0, 50.0)
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
        self._x_spin.setRange(-1000.0, 1000.0)
        self._x_spin.setDecimals(3)
        self._x_spin.setSuffix(" mm")
        self._y_spin = QDoubleSpinBox()
        self._y_spin.setRange(-1000.0, 1000.0)
        self._y_spin.setDecimals(3)
        self._y_spin.setSuffix(" mm")
        if text_obj:
            self._x_spin.setValue(text_obj.anchor_x)
            self._y_spin.setValue(text_obj.anchor_y)
            lay.addRow("Anchor X:", self._x_spin)
            lay.addRow("Anchor Y:", self._y_spin)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addRow(btns)
        self._text_edit.setFocus()

    def values(self) -> dict:
        return {
            "text":     self._text_edit.text(),
            "family":   self._font_combo.currentFont().family(),
            "size_mm":  self._size_spin.value(),
            "rotation": self._rot_spin.value(),
            "anchor_x": self._x_spin.value(),
            "anchor_y": self._y_spin.value(),
        }


class TextTool(QObject):
    """Click-to-place text tool. Follows the DrawTool handle_* interface so
    CanvasView routes events to it unchanged."""

    text_added     = Signal(object)   # TextObject
    cancelled      = Signal()
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene  = None
        self._view   = None
        self._layer  = Layer.ENGRAVING
        self._parent_widget = parent

    @property
    def active(self) -> bool:
        return self._scene is not None

    def activate(self, layer: Layer, scene, view):
        self._layer = layer
        self._scene = scene
        self._view  = view
        self.status_message.emit(
            "Text: click the baseline-left anchor point for the engraving text. Esc to cancel."
        )

    def deactivate(self):
        self._scene = None
        self._view  = None

    # ── CanvasView tool interface ────────────────────────────────────────

    def handle_press(self, pos: QPointF, use_snap: bool = True,
                     constrain: bool = False):
        if not self.active:
            return
        dlg = TextDialog(self._parent_widget)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.cancelled.emit()
            return
        v = dlg.values()
        if not v["text"].strip():
            self.cancelled.emit()
            return
        self.text_added.emit(TextObject(
            text=v["text"], family=v["family"], size_mm=v["size_mm"],
            rotation=v["rotation"], anchor_x=pos.x(), anchor_y=pos.y(),
            layer=self._layer,
        ))

    def handle_move(self, pos: QPointF, use_snap: bool = True,
                    constrain: bool = False):
        pass

    def handle_dbl_click(self, pos: QPointF, use_snap: bool = True,
                         constrain: bool = False):
        pass

    def handle_key(self, key, text: str = "") -> bool:
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return True
        return False

    def cancel(self):
        self.cancelled.emit()
