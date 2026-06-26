"""Regression: selecting a curve must not snap/move its nodes.

When a single curve is selected, EditTool builds a NodeDot (and, for splines,
HandleDots) at every node, placing each with setPos() in the constructor. If
ItemSendsGeometryChanges is enabled *before* that setPos, the constructor's
placement fires itemChange(ItemPositionChange) -> the endpoint-snap callback,
which yanks the freshly-shown node onto a nearby endpoint the instant the curve
is selected -- and *outside* the undo stack, since no drag ever began. DXF
imports (full of near-coincident endpoints) made this destructive.

Snapping must only run during an actual drag, i.e. for setPos calls that happen
after construction.
"""
from PySide6.QtCore import QPointF

from framedraft.canvas.items import NodeDot, HandleDot

from helpers import spline


def _snap_shift(value: QPointF) -> QPointF:
    """A snap callback that would move any point far away if it ever ran."""
    return QPointF(value.x() + 100.0, value.y() + 100.0)


def test_nodedot_construction_does_not_snap():
    curve = spline([(0, 0), (10, 0), (10, 10)], closed=False)
    n = curve.nodes[1]
    x0, y0 = n.x, n.y
    cp_in0 = (n.cp_in.x, n.cp_in.y)
    cp_out0 = (n.cp_out.x, n.cp_out.y)

    moved: list = []
    dot = NodeDot(curve, 1, on_moved=lambda c: moved.append(c),
                  on_snap=_snap_shift)

    # Mere selection must leave the node and its handles untouched.
    assert (n.x, n.y) == (x0, y0)
    assert (n.cp_in.x, n.cp_in.y) == cp_in0
    assert (n.cp_out.x, n.cp_out.y) == cp_out0
    assert moved == []
    # The dot sits at the node, not at the snap target.
    assert (dot.pos().x(), dot.pos().y()) == (x0, y0)


def test_nodedot_drag_still_snaps():
    # After construction, a real position change (a drag) must still snap.
    curve = spline([(0, 0), (10, 0), (10, 10)], closed=False)
    dot = NodeDot(curve, 1, on_moved=lambda c: None, on_snap=_snap_shift)

    dot.setPos(QPointF(5.0, 5.0))   # snap adds (100, 100)

    assert (dot.pos().x(), dot.pos().y()) == (105.0, 105.0)
    assert (curve.nodes[1].x, curve.nodes[1].y) == (105.0, 105.0)


def test_handledot_construction_does_not_write_model():
    curve = spline([(0, 0), (10, 0), (10, 10)], closed=False)
    moved: list = []
    HandleDot(curve, 1, "cp_out", on_moved=lambda c: moved.append(c))
    assert moved == []
