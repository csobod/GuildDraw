"""Snapping the boxing guide to the lens must not strand a default-sized box.

Snapping force-shows the boxing guide, because the bevel outline rides on it.
Un-snapping used to leave the guide up at its free-box default size and
position — the maker turned a feature off and got a stray rectangle over their
drawing. The guide's pre-snap visibility is remembered and restored instead.
"""
import pytest

from framedraft.document import Layer
from helpers import closed_diamond


@pytest.fixture(scope="module")
def win():
    from framedraft.app import MainWindow
    w = MainWindow()
    yield w
    for ws in w._workspaces:
        ws.scene.clearSelection()
    w._dirty = False


@pytest.fixture()
def fresh(win):
    win._dirty = False
    win._new()
    win._ws_tab_widget.setCurrentIndex(0)
    win._active_ws.add_curve(closed_diamond(0, 0, 20, layer=Layer.LENS))
    win._act_boxing.setChecked(False)
    win._boxing_snap_chk.setChecked(False)
    return win


def test_snapping_shows_the_guide(fresh):
    win = fresh
    win._boxing_snap_chk.setChecked(True)
    assert win._act_boxing.isChecked()


def test_unsnapping_hides_a_guide_that_was_hidden(fresh):
    win = fresh
    assert not win._act_boxing.isChecked()

    win._boxing_snap_chk.setChecked(True)
    assert win._act_boxing.isChecked()          # snapping brought it up

    win._boxing_snap_chk.setChecked(False)
    assert not win._act_boxing.isChecked()      # …and un-snapping puts it back
    assert win._active_ws.boxing_guide._visible is False


def test_unsnapping_leaves_a_guide_that_was_already_shown(fresh):
    win = fresh
    win._act_boxing.setChecked(True)

    win._boxing_snap_chk.setChecked(True)
    win._boxing_snap_chk.setChecked(False)
    assert win._act_boxing.isChecked()


def test_manual_toggle_while_snapped_wins(fresh):
    # The maker turned the guide on deliberately after snapping, so that is
    # what un-snapping should honour — not the state from before the snap.
    win = fresh
    win._boxing_snap_chk.setChecked(True)
    win._act_boxing.setChecked(False)
    win._act_boxing.setChecked(True)

    win._boxing_snap_chk.setChecked(False)
    assert win._act_boxing.isChecked()


def test_manual_hide_while_snapped_is_also_honoured(fresh):
    win = fresh
    win._act_boxing.setChecked(True)
    win._boxing_snap_chk.setChecked(True)
    win._act_boxing.setChecked(False)

    win._boxing_snap_chk.setChecked(False)
    assert not win._act_boxing.isChecked()


def test_memory_clears_after_a_round_trip(fresh):
    win = fresh
    win._boxing_snap_chk.setChecked(True)
    win._boxing_snap_chk.setChecked(False)
    assert win._active_ws.boxing_visible_pre_snap is None

    # Second cycle starts from the restored (hidden) state, not a stale True.
    win._boxing_snap_chk.setChecked(True)
    win._boxing_snap_chk.setChecked(False)
    assert not win._act_boxing.isChecked()


def test_new_document_forgets_the_memory(fresh):
    win = fresh
    win._boxing_snap_chk.setChecked(True)
    win._dirty = False
    win._new()
    assert win._active_ws.boxing_visible_pre_snap is None
