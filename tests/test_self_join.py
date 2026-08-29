"""Join on a single curve — fusing a path's own two ends into a closed loop.

The shape that motivates this: an imported OMA/DXF lens trace, rebuilt to a
handful of nodes, comes back as ONE spline that reads as closed but is still an
open path. Chaining can't fix it (there is no second curve), so Join closes it
in place. Without that the curve never counts as a finished LENS.
"""
import pytest

from framedraft.document import Layer
from helpers import arc, circle, closed_diamond, spline


@pytest.fixture(scope="module")
def win():
    from framedraft.app import MainWindow
    w = MainWindow()
    yield w
    # Leave nothing selected: the selection-changed handlers reach back into
    # the scene, and at interpreter shutdown it may already be gone.
    for ws in w._workspaces:
        ws.scene.clearSelection()
    w._dirty = False


@pytest.fixture()
def fresh(win):
    win._dirty = False
    win._new()
    win._ws_tab_widget.setCurrentIndex(0)
    return win


def _open_ring(cx=0.0, cy=0.0, r=20.0, gap=0.0, layer=Layer.LENS):
    """A ring drawn as an OPEN spline whose last node lands back on the first
    (offset by *gap* mm) — the imported-and-rebuilt lens trace shape."""
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy),
           (cx + gap, cy - r)]
    return spline(pts, closed=False, layer=layer)


def _only_curve(win):
    curves = win._active_ws.doc_curves
    assert len(curves) == 1
    return curves[0]


def test_coincident_ends_close_into_a_loop(fresh):
    win = fresh
    win._active_ws.add_curve(_open_ring()).setSelected(True)
    win._join_selected_curves()

    result = _only_curve(win)
    assert result.closed is True
    assert len(result.nodes) == 4       # the duplicated end node is folded away
    assert result.layer == Layer.LENS


def test_wrap_segment_inherits_the_tail_handle(fresh):
    win = fresh
    src = _open_ring()
    tail_cp_in = src.nodes[-1].cp_in
    win._active_ws.add_curve(src).setSelected(True)
    win._join_selected_curves()

    head = _only_curve(win).nodes[0]
    assert head.cp_in.x == pytest.approx(tail_cp_in.x)
    assert head.cp_in.y == pytest.approx(tail_cp_in.y)


def test_ends_within_tolerance_still_close(fresh):
    win = fresh
    win._active_ws.add_curve(_open_ring(gap=1.0)).setSelected(True)
    win._join_selected_curves()
    assert _only_curve(win).closed is True


def test_ends_too_far_apart_are_refused(fresh):
    win = fresh
    src = _open_ring(gap=5.0)
    win._active_ws.add_curve(src).setSelected(True)
    win._join_selected_curves()

    assert _only_curve(win) is src        # untouched
    assert src.closed is False
    assert "apart" in win._status.currentMessage()


def test_already_closed_curve_is_left_alone(fresh):
    win = fresh
    src = closed_diamond(0, 0, 20, layer=Layer.LENS)
    win._active_ws.add_curve(src).setSelected(True)
    win._join_selected_curves()

    assert _only_curve(win) is src
    assert "already closed" in win._status.currentMessage()


def test_circle_is_already_closed(fresh):
    win = fresh
    win._active_ws.add_curve(circle(0, 0, 10)).setSelected(True)
    win._join_selected_curves()
    assert "already closed" in win._status.currentMessage()


def test_full_sweep_arc_closes(fresh):
    # An arc's endpoints live on its geometry, not its nodes, so it has to be
    # converted before its ends can be compared at all.
    win = fresh
    win._active_ws.add_curve(arc(0, 0, 10, 0, 359.5)).setSelected(True)
    win._join_selected_curves()

    result = _only_curve(win)
    assert result.kind == "spline"
    assert result.closed is True


def test_half_arc_is_refused(fresh):
    win = fresh
    src = arc(0, 0, 10, 0, 90)
    win._active_ws.add_curve(src).setSelected(True)
    win._join_selected_curves()

    assert _only_curve(win) is src
    assert "apart" in win._status.currentMessage()


def test_two_node_stub_cannot_become_a_loop(fresh):
    win = fresh
    src = spline([(0, 0), (0, 0)], closed=False, layer=Layer.LENS)
    win._active_ws.add_curve(src).setSelected(True)
    win._join_selected_curves()

    assert _only_curve(win) is src
    assert "at least 3 nodes" in win._status.currentMessage()


def test_closing_is_undoable(fresh):
    win = fresh
    win._active_ws.add_curve(_open_ring()).setSelected(True)
    win._join_selected_curves()
    assert _only_curve(win).closed is True

    win._handle_undo()
    assert _only_curve(win).closed is False


def test_group_membership_survives(fresh):
    win = fresh
    src = _open_ring()
    src.group_id = "abcd1234"
    win._active_ws.add_curve(src).setSelected(True)
    win._join_selected_curves()
    assert _only_curve(win).group_id == "abcd1234"


def test_empty_selection_explains_both_modes(fresh):
    win = fresh
    win._join_selected_curves()
    msg = win._status.currentMessage()
    assert "one curve" in msg and "2+" in msg


def test_two_curves_still_chain(fresh):
    # The multi-curve path is untouched by the single-curve addition.
    win = fresh
    a = spline([(0, 0), (10, -8), (20, 0)], closed=False, layer=Layer.LENS)
    b = spline([(20, 0), (10, 8), (0, 0)], closed=False, layer=Layer.LENS)
    win._active_ws.add_curve(a).setSelected(True)
    win._active_ws.add_curve(b).setSelected(True)
    win._join_selected_curves()

    result = _only_curve(win)
    assert result.closed is True
    # 3 + 3 nodes, less one folded at the mid junction and one at the close.
    assert len(result.nodes) == 4
    ends = {(round(n.x, 6), round(n.y, 6)) for n in result.nodes}
    assert (0.0, 0.0) in ends and (20.0, 0.0) in ends
