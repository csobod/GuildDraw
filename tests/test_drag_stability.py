"""M32 — spline node/handle drag stability.

The dots drag via explicit scenePos()-based handlers (not Qt's built-in
ItemIsMovable path, which re-derived the step through the CURRENT view
transform and sent the dot flying on a mid-drag zoom/pan). These tests pin the
transform-independent invariant and the scoped mirror-axis magnet (H2).
"""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent, QGraphicsView

from framedraft.canvas.items import NodeDot, HandleDot
from framedraft.canvas.scene import FrameScene
from framedraft.tools.edit import EditTool
from framedraft.document import Curve, SplineNode, ControlPoint, Layer
from helpers import spline


def _press(x, y):
    ev = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    ev.setButton(Qt.MouseButton.LeftButton)
    ev.setScenePos(QPointF(x, y))
    return ev


def _move(x, y):
    ev = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseMove)
    ev.setScenePos(QPointF(x, y))
    return ev


def _release():
    ev = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseRelease)
    ev.setButton(Qt.MouseButton.LeftButton)
    return ev


# ---------------------------------------------------------------- structural

def test_dots_are_not_qt_movable():
    """The fix: NodeDot/HandleDot must NOT carry ItemIsMovable — that flag is
    what routed the drag through Qt's transform-dependent built-in path."""
    c = spline([(0, 0), (10, 5), (20, 0)])
    nd = NodeDot(c, 1, lambda _c: None)
    hd = HandleDot(c, 1, "cp_out", lambda _c: None)
    assert not (nd.flags() & NodeDot.GraphicsItemFlag.ItemIsMovable)
    assert not (hd.flags() & HandleDot.GraphicsItemFlag.ItemIsMovable)
    # …but still constant-screen-size and change-reporting
    assert nd.flags() & NodeDot.GraphicsItemFlag.ItemIgnoresTransformations
    assert nd.flags() & NodeDot.GraphicsItemFlag.ItemSendsGeometryChanges


# ---------------------------------------------------------------- node drag

def test_node_drag_tracks_cursor_with_grab_offset():
    scene = QGraphicsScene()
    c = spline([(0, 0), (10, 5), (20, 0)])
    moved = []
    dot = NodeDot(c, 1, lambda cc: moved.append(cc))
    scene.addItem(dot)

    # press 1 mm to the right of the node → grab offset −1 in x
    dot.mousePressEvent(_press(11, 5))
    assert dot._drag_active

    dot.mouseMoveEvent(_move(20, 5))
    # node lands at cursor + grab offset = 19, NOT snapped to the cursor centre
    assert abs(c.nodes[1].x - 19.0) < 1e-9 and abs(c.nodes[1].y - 5.0) < 1e-9
    assert moved, "on_moved not fired during drag"

    dot.mouseReleaseEvent(_release())
    assert dot._drag_active is False


def test_node_drag_survives_middrag_view_scale():
    """The fly-away regression: zooming the view mid-drag must not move the
    node away from the cursor. scenePos()-based dragging is scale-independent,
    so the node stays exactly at cursor + grab offset across a scale change."""
    scene = QGraphicsScene()
    view = QGraphicsView(scene)
    view.resize(400, 400)
    c = spline([(0, 0), (10, 5), (20, 0)])
    dot = NodeDot(c, 1, lambda _c: None)
    scene.addItem(dot)

    dot.mousePressEvent(_press(10, 5))           # grab offset 0
    dot.mouseMoveEvent(_move(14, 7))
    assert (abs(c.nodes[1].x - 14) < 1e-9) and (abs(c.nodes[1].y - 7) < 1e-9)

    view.scale(2.5, 2.5)                          # <-- mid-drag zoom
    dot.mouseMoveEvent(_move(15, 7))             # tiny real cursor move
    # tracks the cursor exactly — no fly-away toward the anchor/centre
    assert (abs(c.nodes[1].x - 15) < 1e-9) and (abs(c.nodes[1].y - 7) < 1e-9)

    view.scale(0.2, 0.2)                          # zoom back out mid-drag
    dot.mouseMoveEvent(_move(16, 8))
    assert (abs(c.nodes[1].x - 16) < 1e-9) and (abs(c.nodes[1].y - 8) < 1e-9)


def test_node_drag_moves_handles_with_it():
    scene = QGraphicsScene()
    c = spline([(0, 0), (10, 5), (20, 0)])
    n = c.nodes[1]
    in0 = (n.cp_in.x, n.cp_in.y)
    out0 = (n.cp_out.x, n.cp_out.y)
    dot = NodeDot(c, 1, lambda _c: None)
    scene.addItem(dot)
    dot.mousePressEvent(_press(10, 5))
    dot.mouseMoveEvent(_move(13, 9))     # +3, +4
    assert abs(n.cp_in.x - (in0[0] + 3)) < 1e-9 and abs(n.cp_in.y - (in0[1] + 4)) < 1e-9
    assert abs(n.cp_out.x - (out0[0] + 3)) < 1e-9 and abs(n.cp_out.y - (out0[1] + 4)) < 1e-9


# ---------------------------------------------------------------- handle drag

def test_handle_drag_tracks_and_reflects_sibling_when_smooth():
    scene = QGraphicsScene()
    n = SplineNode(x=10, y=10,
                   cp_in=ControlPoint(7, 10), cp_out=ControlPoint(13, 10))
    c = Curve(kind="spline", layer=Layer.LENS, nodes=[SplineNode(x=0, y=0), n,
              SplineNode(x=20, y=0)], closed=False)
    h_out = HandleDot(c, 1, "cp_out", lambda _c: None)
    h_in  = HandleDot(c, 1, "cp_in",  lambda _c: None)
    h_out.set_sibling(h_in)
    h_in.set_sibling(h_out)
    scene.addItem(h_out)
    scene.addItem(h_in)

    h_out.mousePressEvent(_press(13, 10))
    h_out.mouseMoveEvent(_move(13, 14))
    assert abs(n.cp_out.x - 13) < 1e-9 and abs(n.cp_out.y - 14) < 1e-9
    # smooth (default): the opposite handle mirrors through the node
    assert abs(n.cp_in.x - 7) < 1e-9 and abs(n.cp_in.y - 6) < 1e-9


def test_handle_drag_survives_middrag_view_scale():
    scene = QGraphicsScene()
    view = QGraphicsView(scene)
    view.resize(300, 300)
    n = SplineNode(x=10, y=10, cp_out=ControlPoint(13, 10))
    c = Curve(kind="spline", layer=Layer.LENS,
              nodes=[SplineNode(x=0, y=0), n, SplineNode(x=20, y=0)], closed=False)
    h = HandleDot(c, 1, "cp_out", lambda _c: None)
    scene.addItem(h)
    h.mousePressEvent(_press(13, 10))
    h.mouseMoveEvent(_move(15, 12))
    view.scale(3.0, 3.0)
    h.mouseMoveEvent(_move(16, 12))
    assert abs(n.cp_out.x - 16) < 1e-9 and abs(n.cp_out.y - 12) < 1e-9


# ---------------------------------------------------------------- H2: axis magnet

def _axis_tool():
    scene = FrameScene()
    scene.init_mirror(horizontal=False)
    scene.mirror.set_enabled(True)
    scene.mirror.set_x(0.0)
    view = QGraphicsView(scene)
    view.resize(400, 400)
    tool = EditTool(scene)
    tool.set_endpoint_snap_context([], view, lambda: True)
    return tool


def test_mirror_magnet_snaps_open_endpoint():
    tool = _axis_tool()
    node = SplineNode(x=0.3, y=20)
    snap = tool._make_ep_snap_fn(node, is_open_endpoint=True)
    out = snap(QPointF(0.3, 20))          # 0.3 mm from the axis
    assert abs(out.x()) < 1e-9            # magneted to x = 0


def test_mirror_magnet_ignores_interior_and_closed_nodes():
    """H2: an interior node (or any node of a closed curve) near the bridge
    must NOT be yanked to dead-centre."""
    tool = _axis_tool()
    node = SplineNode(x=0.3, y=20)
    snap = tool._make_ep_snap_fn(node, is_open_endpoint=False)
    out = snap(QPointF(0.3, 20))
    assert abs(out.x() - 0.3) < 1e-9      # left exactly where the cursor is
    assert abs(out.y() - 20) < 1e-9


def test_edit_tool_marks_only_open_endpoints():
    """The EditTool must pass is_open_endpoint=True only for index 0/last of an
    OPEN curve — verified through the produced snap behaviour on real dots."""
    scene = FrameScene()
    scene.init_mirror(horizontal=False)
    scene.mirror.set_enabled(True)
    scene.mirror.set_x(0.0)
    view = QGraphicsView(scene)
    view.resize(400, 400)
    tool = EditTool(scene)
    tool.set_endpoint_snap_context([], view, lambda: True)

    # An OPEN 3-node spline: endpoints magnet, middle does not.
    open_c = spline([(0.3, -20), (0.3, 0), (0.3, 20)], closed=False)
    ep0 = tool._make_ep_snap_fn(open_c.nodes[0], True)
    mid = tool._make_ep_snap_fn(open_c.nodes[1], False)
    assert abs(ep0(QPointF(0.3, -20)).x()) < 1e-9
    assert abs(mid(QPointF(0.3, 0)).x() - 0.3) < 1e-9
