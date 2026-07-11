"""RC4 follow-up round — □-hotkey event-filter matching, the Radius/Diameter
chip anchoring near the circle centre, and grid appearance settings."""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QStatusBar

from framedraft.app import CanvasView, _matches_key_event
from framedraft.canvas.scene import FrameScene
from framedraft.prefs import DEFAULTS


def _key_event(key, mods=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QEvent.Type.KeyPress, key, mods)


# ------------------------------------------------------ □ hotkey matching


def test_square_sequence_matches_exact_combo():
    seq = QKeySequence("Ctrl+Shift+B")
    ev = _key_event(Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier)
    assert _matches_key_event(seq, ev)


def test_square_sequence_rejects_other_keys():
    seq = QKeySequence("Ctrl+Shift+B")
    assert not _matches_key_event(seq, _key_event(Qt.Key.Key_B))
    assert not _matches_key_event(
        seq, _key_event(Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier))
    assert not _matches_key_event(None, _key_event(Qt.Key.Key_B))
    assert not _matches_key_event(QKeySequence(""), _key_event(Qt.Key.Key_B))


# ------------------------------------------------- measure chip anchoring


def _make_view():
    scene = FrameScene()
    view = CanvasView(scene, QStatusBar())
    view.resize(800, 600)
    QApplication.processEvents()
    return scene, view


def test_measure_chip_pops_near_anchor():
    _scene, view = _make_view()
    bar = view.measure_bar
    anchor = QPointF(0.0, 0.0)          # scene origin
    bar.show_radius(anchor)
    vp = view.mapFromScene(anchor)
    # Near the anchor (offset +18,+18), not docked at the bottom edge.
    assert abs(bar.x() - (vp.x() + 18)) <= 4
    assert abs(bar.y() - (vp.y() + 18)) <= 4
    assert bar.geometry().bottom() < view.height() - 4


def test_measure_chip_clamps_inside_viewport():
    _scene, view = _make_view()
    bar = view.measure_bar
    # Anchor far outside the visible area — chip must stay inside the view.
    far = view.mapToScene(QPoint(5000, 5000))
    bar.show_radius(far)
    r = bar.geometry()
    assert r.left() >= 0 and r.top() >= 0
    assert r.right() <= view.width() and r.bottom() <= view.height()


# ------------------------------------------------------- grid appearance


def test_grid_defaults_are_2mm_with_10mm_major():
    assert DEFAULTS["grid_spacing_mm"] == 2.0
    assert DEFAULTS["grid_major"] == 5           # 2 mm × 5 = 10 mm
    assert DEFAULTS["grid_minor_color"] == ""
    assert DEFAULTS["grid_major_color"] == ""
    assert DEFAULTS["grid_major_width_px"] == 1.0


def test_settings_dialog_builds_and_collects_grid_prefs():
    """The dialog only opens at runtime — pin that the new grid controls
    construct and round-trip through to_prefs()."""
    from framedraft.app import SettingsDialog
    dlg = SettingsDialog(dict(DEFAULTS), None)
    p = dlg.to_prefs()
    assert p["grid_spacing_mm"] == 2.0
    assert p["grid_major"] == 5
    assert p["grid_minor_color"] == ""
    assert p["grid_major_color"] == ""
    assert p["grid_major_width_px"] == 1.0


def test_set_grid_appearance_plumbs_through():
    _scene, view = _make_view()
    view.set_grid(minor_color="#ff0000", major_color="#00ff00",
                  major_width=2.5)
    assert view._grid_minor_color == "#ff0000"
    assert view._grid_major_color == "#00ff00"
    assert view._grid_major_width == 2.5
    # "" = back to the theme tokens
    view.set_grid(minor_color="", major_color="")
    assert view._grid_minor_color is None
    assert view._grid_major_color is None
    # None leaves values untouched; nonpositive width ignored
    view.set_grid(major_width=-1.0)
    assert view._grid_major_width == 2.5
