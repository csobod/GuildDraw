"""Wheel-zoom anchoring (GitHub issue #3).

The point under the cursor must stay put across wheel zooms in EVERY mode.
The old wheelEvent trusted AnchorUnderMouse, whose internally tracked mouse
position only updates in QGraphicsView.mouseMoveEvent — the tool branches of
CanvasView.mouseMoveEvent consume moves without calling the base handler, so
with any tool active the anchor went stale and each wheel tick yanked the
viewport toward it. wheelEvent now anchors manually via the scrollbars.
"""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QStatusBar

from framedraft.app import CanvasView
from framedraft.canvas.scene import FrameScene
from framedraft.document import Curve, Layer, SplineNode
from framedraft.tools.draw import DrawTool


def _make_view():
    scene = FrameScene()
    view = CanvasView(scene, QStatusBar())
    view.resize(800, 600)
    QApplication.processEvents()
    return scene, view


def _wheel(view, vp: QPoint, delta_y: int):
    ev = QWheelEvent(
        QPointF(vp), QPointF(view.mapToGlobal(vp)),
        QPoint(0, 0), QPoint(0, delta_y),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(ev)


def _assert_anchored(view, vp: QPoint, steps):
    before = view.mapToScene(vp)
    for delta in steps:
        _wheel(view, vp, delta)
    after = view.mapToScene(vp)
    # Scrollbar values are integers, so allow ~2 device px of slack in scene mm
    tol = 2.0 / abs(view.transform().m11())
    assert (after - before).manhattanLength() < tol, (
        f"anchor drifted: {before} -> {after}")


def test_wheel_zoom_anchors_under_cursor_select_mode():
    _scene, view = _make_view()
    _assert_anchored(view, QPoint(500, 400), [120, 120, 120, -120])


def test_wheel_zoom_anchors_under_cursor_with_draw_tool_active():
    scene, view = _make_view()
    curve = Curve(kind="line", layer=Layer.OUTLINE,
                  nodes=[SplineNode(x=0, y=0), SplineNode(x=40, y=25)])
    scene.add_curve(curve)

    tool = DrawTool()
    tool.activate("line", Layer.OUTLINE, scene, view)
    view.set_draw_tool(tool)
    assert tool.active

    # Never send a mouse move: QGraphicsView's internal anchor position stays
    # stale, which is exactly the reported condition.
    _assert_anchored(view, QPoint(620, 130), [120, 120, 120])
    _assert_anchored(view, QPoint(620, 130), [-120, -120])


def test_wheel_zero_delta_does_not_zoom():
    _scene, view = _make_view()
    before = view.transform().m11()
    _wheel(view, QPoint(400, 300), 0)
    assert view.transform().m11() == before
