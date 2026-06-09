import math
from PySide6.QtCore import QObject, Signal, QPointF
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QDoubleSpinBox, QLabel
from PySide6.QtGui import QColor, QPen


class CalibTool(QObject):
    """
    Two-point face-image calibration tool.

    The user clicks two points on the face image, then enters the known
    real-world distance between them (mm).  The face image is rescaled so
    those two landmarks are exactly that many mm apart in the scene.

    Because the scene is already in mm, the calibration only affects the
    face image scale — it does not change any drawn geometry.
    """
    calibrated = Signal(float)    # emits px_per_mm (image pixels per real mm)
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = 0   # 0=idle, 1=waiting p1, 2=waiting p2
        self._p1: QPointF | None = None
        self._scene = None
        self._line_item = None

    @property
    def active(self) -> bool:
        return self._state != 0

    def start(self, scene=None):
        self._state = 1
        self._p1 = None
        self._scene = scene
        if scene is not None and not scene.has_face():
            self._state = 0
            self.status_message.emit("Load a face image first, then calibrate.")
            return
        self.status_message.emit("Calibrate: click first reference point on the face image  [Esc to cancel]")

    def cancel(self, scene):
        self._clear_line(scene)
        self._state = 0
        self._scene = None
        self.status_message.emit("Calibration cancelled")

    def handle_press(self, pos: QPointF, scene) -> bool:
        """Return True if event was consumed."""
        if self._state == 1:
            self._p1 = pos
            self._state = 2
            self.status_message.emit("Calibrate: click second reference point  [Esc to cancel]")
            return True
        if self._state == 2:
            self._clear_line(scene)
            self._state = 0
            self._scene = None
            self._do_calibrate(scene, pos)
            return True
        return False

    def _do_calibrate(self, scene, p2: QPointF):
        face_item = scene.get_face_item(0)
        if face_item is None:
            self.status_message.emit("No face image loaded — calibration cancelled")
            return

        # Map scene-mm click positions to image pixel coordinates.
        # This correctly handles whatever scale the image is currently at.
        p1_img = face_item.mapFromScene(self._p1)
        p2_img = face_item.mapFromScene(p2)
        pixel_dist = math.hypot(p2_img.x() - p1_img.x(), p2_img.y() - p1_img.y())

        if pixel_dist < 1.0:
            self.status_message.emit("Reference points too close — calibration cancelled")
            return

        dlg = _CalibDialog(pixel_dist)
        if dlg.exec():
            real_mm = dlg.real_mm()
            if real_mm > 0:
                px_per_mm = pixel_dist / real_mm
                self.calibrated.emit(px_per_mm)
        else:
            self.status_message.emit("Calibration cancelled")

    def handle_move(self, pos: QPointF, scene):
        if self._state == 2 and self._p1 is not None:
            self._clear_line(scene)
            pen = QPen(QColor("#c0392b"), 0)
            self._line_item = scene.addLine(
                self._p1.x(), self._p1.y(), pos.x(), pos.y(), pen
            )

    def _clear_line(self, scene):
        if self._line_item is not None:
            scene.removeItem(self._line_item)
            self._line_item = None


class _CalibDialog(QDialog):
    def __init__(self, pixel_dist: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrate Face Image Scale")
        lay = QFormLayout(self)
        lay.addRow("Reference pixels:", QLabel(f"{pixel_dist:.1f} px"))
        self._spin = QDoubleSpinBox()
        self._spin.setRange(0.1, 9999.0)
        self._spin.setDecimals(2)
        self._spin.setSuffix(" mm")
        self._spin.setValue(63.0)   # default: typical PD ~63 mm
        lay.addRow("Real-world distance:", self._spin)
        hint = QLabel(
            "Tip: click two landmarks whose real distance you know — "
            "e.g. pupillary distance (PD), or a ruler held in the photo."
        )
        hint.setWordWrap(True)
        lay.addRow(hint)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self._spin.selectAll()
        self._spin.setFocus()

    def real_mm(self) -> float:
        return self._spin.value()
