"""The 2.0 polish round on the canvas and its tools (BUILDPLAN Road to 2.0,
item 14): panning without a middle button, a double-click that finishes a
tool, groups under Ctrl+click, coordinates and angles as the screen shows
them (y up, counter-clockwise, View Obverse included), and typed numbers
with a decimal comma."""
import gc
import math

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft import library as lib_mod
from framedraft.document import Layer
from helpers import closed_diamond, line

L, R, NONE = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.NoButton


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    root = tmp_path / "library"
    monkeypatch.setattr(lib_mod, "_LIBRARY_DIR", root)
    monkeypatch.setattr(lib_mod, "_COMPONENTS_DIR", root / "components")
    monkeypatch.setattr(lib_mod, "_HINGES_DIR", root / "hinges")
    monkeypatch.setattr(lib_mod, "_SEED_MANIFEST", root / "seeded.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    w.view.fit_view(QRectF(-60, -60, 120, 120))
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    gc.collect()            # see test_v200_bug_hunt's fixture


def _ev(view, kind, scene_pt, button=L, buttons=None,
        mods=Qt.KeyboardModifier.NoModifier):
    vp = view.mapFromScene(scene_pt)
    if buttons is None:
        buttons = NONE if kind == QEvent.Type.MouseButtonRelease else button
    return QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                       button, buttons, mods)


def _click(view, pt, button=L, mods=Qt.KeyboardModifier.NoModifier):
    view.mousePressEvent(_ev(view, QEvent.Type.MouseButtonPress, pt, button, mods=mods))
    view.mouseReleaseEvent(_ev(view, QEvent.Type.MouseButtonRelease, pt, button,
                               mods=mods))


def _key(view, key, text=""):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key,
                                 Qt.KeyboardModifier.NoModifier, text))


# ── A double-click that finishes a tool ────────────────────────────────────

def test_closing_a_line_with_a_double_click_adds_no_node(win):
    """The press closed the line; the double-click's second half fell to
    Select mode and inserted a fifth node on the seam."""
    view = win.view
    win._act_line.trigger()
    pts = [QPointF(0, 0), QPointF(20, 0), QPointF(20, 20), QPointF(0, 20)]
    for p in pts:
        _click(view, p)
    _click(view, pts[0])                             # closes on the first node
    view.mouseDoubleClickEvent(_ev(view, QEvent.Type.MouseButtonDblClick, pts[0]))
    curves = win._active_ws.doc_curves
    assert len(curves) == 1 and curves[0].closed
    assert len(curves[0].nodes) == 4


def test_a_double_click_in_select_mode_still_inserts_a_node(win):
    view = win.view
    c = win._active_ws.add_curve(line([(-30, 0), (30, 0)], layer=Layer.REF)).curve
    view.mousePressEvent(_ev(view, QEvent.Type.MouseButtonPress, QPointF(5, 0)))
    view.mouseReleaseEvent(_ev(view, QEvent.Type.MouseButtonRelease, QPointF(5, 0)))
    view.mouseDoubleClickEvent(_ev(view, QEvent.Type.MouseButtonDblClick, QPointF(5, 0)))
    assert len(c.nodes) == 3


# ── Panning ────────────────────────────────────────────────────────────────

def _scroll(view):
    return view.horizontalScrollBar().value(), view.verticalScrollBar().value()


def test_a_right_drag_pans_and_a_right_click_keeps_the_selection(win):
    view = win.view
    item = win._active_ws.add_curve(line([(-30, 10), (30, 10)], layer=Layer.REF))
    item.setSelected(True)
    _click(view, QPointF(0, 30), R)                  # a right-click, no drag
    assert item.isSelected()

    before = _scroll(view)
    view.mousePressEvent(_ev(view, QEvent.Type.MouseButtonPress, QPointF(0, 0), R))
    view.mouseMoveEvent(_ev(view, QEvent.Type.MouseMove, QPointF(20, 15), NONE, R))
    view.mouseReleaseEvent(_ev(view, QEvent.Type.MouseButtonRelease, QPointF(20, 15), R))
    assert _scroll(view) != before
    assert item.isSelected()                         # no box select either


def test_space_and_the_left_button_pan(win):
    view = win.view
    item = win._active_ws.add_curve(line([(-30, 10), (30, 10)], layer=Layer.REF))
    item.setSelected(True)
    _key(view, Qt.Key.Key_Space, " ")
    before = _scroll(view)
    view.mousePressEvent(_ev(view, QEvent.Type.MouseButtonPress, QPointF(0, 0)))
    view.mouseMoveEvent(_ev(view, QEvent.Type.MouseMove, QPointF(20, 15), NONE, L))
    view.mouseReleaseEvent(_ev(view, QEvent.Type.MouseButtonRelease, QPointF(20, 15)))
    view.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space,
                                   Qt.KeyboardModifier.NoModifier, " "))
    assert _scroll(view) != before
    assert item.isSelected() and not view._space_held


# ── Groups ─────────────────────────────────────────────────────────────────

def test_ctrl_click_takes_a_whole_group_out_of_the_selection(win):
    view = win.view
    a = win._active_ws.add_curve(line([(-30, 0), (-10, 0)], layer=Layer.REF))
    b = win._active_ws.add_curve(line([(10, 0), (30, 0)], layer=Layer.REF))
    a.curve.group_id = b.curve.group_id = "beef"
    _click(view, QPointF(-20, 0))
    assert a.isSelected() and b.isSelected()
    _click(view, QPointF(20, 0), mods=Qt.KeyboardModifier.ControlModifier)
    assert not a.isSelected() and not b.isSelected()
    _click(view, QPointF(-20, 0), mods=Qt.KeyboardModifier.ControlModifier)
    assert a.isSelected() and b.isSelected()


# ── Coordinates and angles as the screen shows them ────────────────────────

def test_the_readout_and_point_move_are_y_up(win):
    from framedraft.tools.point_move import _PointMoveHud
    assert win.view._fmt(QPointF(1.0, 2.5)) == "x: 1.00 mm  y: -2.50 mm"
    hud = _PointMoveHud(win.view)
    got = []
    hud.show_for(10, 10, 4.0, 6.0, on_commit=got.append, on_cancel=lambda: None)
    assert hud._y.text() == "-6.000"
    hud._x.setText("3,5")                            # a decimal comma
    hud._y.setText("4")
    hud._commit()
    assert got == [QPointF(3.5, -4.0)]


def _start_line(win):
    win._act_line.trigger()
    _click(win.view, QPointF(0, 0))
    return win._draw_tool


def _hud_angle(tool) -> float:
    return float(tool._hud.text().split()[2].rstrip("°"))


def test_the_line_hud_reads_counter_clockwise_in_both_views(win):
    tool = _start_line(win)
    tool.handle_move(QPointF(10, -10), use_snap=False)       # up and right
    assert _hud_angle(tool) == pytest.approx(45.0)
    win._act_obverse.trigger()
    tool.handle_move(QPointF(-10, -10), use_snap=False)      # up-right on screen
    assert _hud_angle(tool) == pytest.approx(45.0)


def test_a_typed_angle_takes_its_minus_and_a_typed_length_its_comma(win):
    tool = _start_line(win)
    for ch in "12,5":
        tool.handle_key(Qt.Key.Key_unknown, ch)
    assert tool._locked_len == 12.5
    tool.handle_key(Qt.Key.Key_Tab)
    for ch in "-30":
        tool.handle_key(Qt.Key.Key_unknown, ch)
    assert tool._locked_angle == -30.0
    p = tool._apply_polar_constraints(QPointF(10, 0), tool._nodes[-1])
    # −30° is down and to the right on screen: scene y grows downward.
    assert p.x() == pytest.approx(12.5 * math.cos(math.radians(30)))
    assert p.y() == pytest.approx(12.5 * math.sin(math.radians(30)))


def test_an_arc_runs_clockwise_on_screen_in_view_obverse(win):
    from framedraft.tools.circle import CircleTool

    class _View:
        def __init__(self, obverse):
            self._o = obverse

        def is_obverse(self):
            return self._o

    tool = CircleTool()
    tool._start_angle = 0.0
    tool._view = _View(False)
    assert tool._arc_angles(90.0) == (0.0, 90.0)
    tool._view = _View(True)
    assert tool._arc_angles(90.0) == (90.0, 0.0)


def test_transform_turns_as_the_screen_shows_in_view_obverse(win, monkeypatch):
    import framedraft.app as app_mod
    it = win._active_ws.add_curve(line([(10, 0), (20, 0)], layer=Layer.REF))
    it.setSelected(True)
    win._act_obverse.trigger()
    monkeypatch.setattr(app_mod.TransformDialog, "exec",
                        lambda self: app_mod.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(app_mod.TransformDialog, "values",
                        lambda self: (1.0, 1.0, 90.0, True))
    win._transform_selected()
    n = it.curve.nodes[1]
    # (20, 0) sits left of the axis on the turned screen; 90° counter-
    # clockwise on screen points it down, scene y-down: (0, 20).
    assert n.x == pytest.approx(0.0, abs=1e-9) and n.y == pytest.approx(20.0)


def test_the_text_dialog_shows_the_anchor_y_up(win):
    from framedraft.document import TextObject
    from framedraft.tools.text import TextDialog
    t = TextObject(text="GUILD", family="DejaVu Sans", size_mm=5.0,
                   anchor_x=3.0, anchor_y=-7.25, layer=Layer.ENGRAVING)
    dlg = TextDialog(win, t)
    assert dlg._y_spin.value() == pytest.approx(7.25)
    assert dlg.values()["anchor_y"] == -7.25          # untouched: exact
    dlg._y_spin.setValue(2.0)
    assert dlg.values()["anchor_y"] == -2.0
    dlg.deleteLater()


def test_a_zero_gizmo_move_pushes_nothing(win):
    from framedraft.canvas.move_gizmo import _MoveHud
    hud = _MoveHud(win.view)
    got = []
    hud.show_for(1, 0, 10, 10, on_commit=lambda dx, dy: got.append((dx, dy)),
                 on_cancel=lambda: None)
    hud._edit.setText("0")
    hud._commit()
    hud.show_for(1, 0, 10, 10, on_commit=lambda dx, dy: got.append((dx, dy)),
                 on_cancel=lambda: None)
    hud._edit.setText("2,5")
    hud._commit()
    assert got == [(2.5, 0.0)]


def test_the_circle_tool_reads_its_radius_once(win):
    win._act_circle.trigger()
    tool = win._circle_tool
    _click(win.view, QPointF(0, 0))
    tool.handle_move(QPointF(12, 0), use_snap=False)
    assert win.view.measure_bar.isVisible()
    assert not tool._hud.isVisible()                 # the chip reads it
    tool.handle_key(Qt.Key.Key_unknown, "8")
    assert tool._hud.isVisible() and tool._hud.text().startswith("8_")


def test_the_zoom_reads_in_pixels_per_mm(win):
    win._update_info_label()
    assert win._info_label.text().startswith("Layer: ")
    assert win._info_label.text().endswith(" px/mm")


# ── Line weight ────────────────────────────────────────────────────────────

def test_the_weight_box_is_gray_with_nothing_selected(win):
    spin = win._weight_spin
    assert not spin.isEnabled()
    assert spin.value() == win._default_line_weight
    item = win._active_ws.add_curve(line([(-30, 10), (30, 10)], layer=Layer.REF))
    item.setSelected(True)
    assert spin.isEnabled()


def test_a_weight_set_after_a_save_stars_the_design(win):
    item = win._active_ws.add_curve(line([(-30, 10), (30, 10)], layer=Layer.REF))
    item.setSelected(True)
    win._weight_spin.setValue(2.0)
    win._clear_dirty()                               # as a save does
    win._weight_spin.setValue(2.5)
    assert win._dirty and item.curve.line_weight == 2.5


def test_a_hidden_grid_pulls_nothing(win):
    snap = win._active_ws.snap
    assert not win._prefs.get("grid_visible", False)
    assert snap._grid_spacing == 0.0
    win._on_grid_toggled(True)
    assert snap._grid_spacing > 0.0
    win._on_grid_toggled(False)
    assert snap._grid_spacing == 0.0


def test_a_curve_beside_a_dimension_can_be_clicked(win):
    """A dim's 3 mm band covered a curve 2 mm away at any zoom."""
    from framedraft.canvas.items import CurveItem
    from framedraft.document import DimLine
    ws = win._active_ws
    ws.add_curve(line([(-20, 0), (20, 0)], layer=Layer.REF))
    ws.add_dim(DimLine(-20, 2, 20, 2, offset=0.0))
    view = win.view
    for zoom in (4.0, 20.0):
        view.resetTransform()
        view.scale(zoom, zoom)
        view.centerOn(QPointF(0, 1))
        picked = view._top_pick(view.mapFromScene(QPointF(0, 0)))
        assert isinstance(picked, CurveItem), zoom
    from framedraft.canvas.dim import DimItem
    picked = view._top_pick(view.mapFromScene(QPointF(0, 2)))
    assert isinstance(picked, DimItem)                # on the dim: the dim


# ── Mirror Close ───────────────────────────────────────────────────────────

def test_mirror_close_refuses_ends_far_off_the_axis_and_a_crossing(win):
    ws = win._active_ws
    far = ws.add_curve(line([(12, -10), (30, 0), (12, 10)], layer=Layer.LENS))
    far.setSelected(True)
    win._copy_across_mirror()
    assert ws.doc_curves == [far.curve] and not far.curve.closed
    assert "12.0 mm from the axis" in win._status.currentMessage()
    ws.remove_curve(far.curve)
    across = ws.add_curve(line([(0, -10), (-20, 0), (20, 5), (0, 10)],
                               layer=Layer.LENS))
    across.setSelected(True)
    win._copy_across_mirror()
    assert not across.curve.closed
    assert "crosses the axis" in win._status.currentMessage()


def test_mirror_close_still_closes_a_half_on_the_axis(win):
    ws = win._active_ws
    half = ws.add_curve(line([(0.5, -10), (20, 0), (0, 10)], layer=Layer.LENS))
    half.setSelected(True)
    win._copy_across_mirror()
    (closed,) = ws.doc_curves
    assert closed.closed and len(closed.nodes) == 4
    assert win._status.currentMessage().startswith("Mirror Close: closed into")


# ── Snap Node to Endpoint (E) ──────────────────────────────────────────────

def _red_node(win, item, idx):
    win.scene.clearSelection()
    item.setSelected(True)
    QApplication.processEvents()
    dot = next(d for d in win._edit_tool._dots if d.node_index == idx)
    win._edit_tool._on_node_clicked(dot)


def _arc(cx, cy, r, sa, ea, layer=Layer.REF):
    from framedraft.document import Curve, SplineNode
    return Curve(kind="arc", layer=layer, nodes=[SplineNode(x=cx, y=cy)],
                 closed=False, radius=r, start_angle=sa, end_angle=ea)


def test_e_takes_an_arcs_real_end_not_its_center(win):
    ws = win._active_ws
    ws.add_curve(_arc(0, 0, 20, 0, 90))              # ends (20, 0) and (0, 20)
    item = ws.add_curve(line([(40, 0), (20.5, 0.5)], layer=Layer.REF))
    _red_node(win, item, 1)
    win._snap_selected_node_to_endpoint()
    end = item.curve.nodes[1]
    assert (end.x, end.y) == pytest.approx((20.0, 0.0), abs=1e-9)


def test_e_keeps_to_its_reach_and_to_shown_layers(win):
    ws = win._active_ws
    ws.add_curve(line([(-60, 0), (-40, 0)], layer=Layer.REF))       # far off
    hidden = ws.add_curve(line([(10, 1), (10, 10)], layer=Layer.SCULPT)).curve
    ws.scene.set_layer_visible(Layer.SCULPT, False)
    item = ws.add_curve(line([(30, 0), (10, 0)], layer=Layer.REF))
    depth = len(ws.undo_stack)
    _red_node(win, item, 1)
    win._snap_selected_node_to_endpoint()
    end = item.curve.nodes[1]
    assert (end.x, end.y) == (10, 0) and len(ws.undo_stack) == depth
    assert "no free end" in win._status.currentMessage()
    assert hidden.nodes[0].x == 10


def test_e_on_an_end_already_met_pushes_nothing(win):
    ws = win._active_ws
    ws.add_curve(line([(0, 0), (10, 0)], layer=Layer.REF))
    item = ws.add_curve(line([(10, 0), (20, 5)], layer=Layer.REF))
    depth = len(ws.undo_stack)
    _red_node(win, item, 0)
    win._snap_selected_node_to_endpoint()
    assert len(ws.undo_stack) == depth and not win._dirty


# ── Hidden and locked layers, pastes ───────────────────────────────────────

def test_a_tool_on_a_hidden_layer_asks_to_show_it(win, monkeypatch):
    ws = win._active_ws
    ws.scene.set_layer_visible(Layer.LENS, False)
    win._set_active_layer(Layer.LENS)
    asked = []
    monkeypatch.setattr(win, "_ask_to_act",
                        lambda title, text, act: asked.append(act) or False)
    win._act_circle.trigger()
    assert asked == ["Show LENS"] and not win._circle_tool.active
    assert win._act_select.isChecked()
    monkeypatch.setattr(win, "_ask_to_act", lambda title, text, act: True)
    win._act_circle.trigger()
    assert win._circle_tool.active and ws.scene.is_layer_visible(Layer.LENS)


def test_a_tool_on_a_locked_layer_asks_to_unlock_it(win, monkeypatch):
    ws = win._active_ws
    ws.scene.set_layer_locked(Layer.OUTLINE, True)
    win._set_active_layer(Layer.OUTLINE)
    monkeypatch.setattr(win, "_ask_to_act", lambda title, text, act: act == "Unlock OUTLINE")
    win._act_line.trigger()
    assert win._draw_tool.active and not ws.scene.is_layer_locked(Layer.OUTLINE)


def test_each_paste_lands_one_step_further_and_names_a_hidden_layer(win):
    ws = win._active_ws
    item = ws.add_curve(line([(0, 0), (10, 0)], layer=Layer.REF))
    item.setSelected(True)
    win._copy_selected()
    win._paste()
    win._paste()
    xs = sorted(c.nodes[0].x for c in ws.doc_curves)
    assert xs == [0.0, 5.0, 10.0]
    ws.scene.set_layer_visible(Layer.REF, False)
    win._paste()
    assert "REF hidden" in win._status.currentMessage()


def test_a_component_placed_on_a_temple_keeps_only_the_temples_layers(win, monkeypatch):
    from framedraft.library import ComponentLibrary
    from helpers import circle
    path = ComponentLibrary().save_entry(
        "Hinges", "Front Plate",
        [closed_diamond(0, 0, 3, layer=Layer.COMPONENT),
         circle(0, 0, 1, layer=Layer.DRILL), circle(5, 0, 1, layer=Layer.LENS)], [])
    win._ws_tab_widget.setCurrentIndex(1)              # Temple R
    QApplication.processEvents()
    monkeypatch.setattr(win, "_lib_selected", lambda: ("entry", path))
    win._import_from_library()
    layers = sorted(c.layer.value for c in win._active_ws.doc_curves)
    assert layers == ["COMPONENT", "REF", "REF"]
    assert "DRILL and LENS moved to REF" in win._status.currentMessage()
    kinds = {c.layer: c.component_kind for c in win._active_ws.doc_curves}
    assert kinds[Layer.COMPONENT] == "Hinges" and kinds[Layer.REF] is None


def test_a_text_stays_on_engraving_or_ref(win):
    from framedraft.document import TextObject
    from framedraft.textpath import text_to_curves
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    t = TextObject(text="GUILD", family="DejaVu Sans", size_mm=5.0,
                   anchor_x=10.0, anchor_y=0.0, layer=Layer.ENGRAVING)
    win._active_ws.add_text(t)
    item = win.scene._text_items[id(t)]
    win._move_curve_items_to_layer([item], Layer.OUTLINE)
    assert t.layer == Layer.ENGRAVING
    assert "stays on ENGRAVING or REF" in win._status.currentMessage()
    win._move_curve_items_to_layer([item], Layer.REF)
    assert t.layer == Layer.REF
    t.layer = Layer.OUTLINE                       # as an older file may hold it
    assert {c.layer for c in text_to_curves(t)} == {Layer.ENGRAVING}


# ── Shape operations keep a component whole ────────────────────────────────

def _select_all_curves(win):
    from framedraft.canvas.items import CurveItem
    win.scene.select_items([it for it in win.scene.items() if isinstance(it, CurveItem)])


def test_join_refuses_curves_on_two_layers(win):
    ws = win._active_ws
    ws.add_curve(line([(0, 0), (10, 0)], layer=Layer.OUTLINE))
    ws.add_curve(line([(10, 0), (10, 10)], layer=Layer.REF))
    _select_all_curves(win)
    win._join_selected_curves()
    assert len(ws.doc_curves) == 2
    assert "OUTLINE and REF" in win._status.currentMessage()


def test_join_carries_a_shared_group_and_kind_and_says_what_it_moved(win):
    ws = win._active_ws
    a = ws.add_curve(line([(0, 0), (10, 0)], layer=Layer.COMPONENT)).curve
    b = ws.add_curve(line([(10.8, 0), (10, 10)], layer=Layer.COMPONENT)).curve
    for c in (a, b):
        c.group_id, c.component_kind = "f00d", "Hinges"
    _select_all_curves(win)
    win._join_selected_curves()
    (joined,) = ws.doc_curves
    assert joined.group_id == "f00d" and joined.component_kind == "Hinges"
    assert "0.80 mm apart were brought together" in win._status.currentMessage()


def test_close_keeps_the_kind(win):
    ws = win._active_ws
    c = ws.add_curve(line([(0, 0), (10, 0), (5, 8), (0.05, 0)],
                          layer=Layer.COMPONENT)).curve
    c.component_kind = "Bridges"
    win._close_single_curve(c)
    (closed,) = ws.doc_curves
    assert closed.closed and closed.component_kind == "Bridges"


def test_trim_leaves_a_placed_component_alone(win):
    ws = win._active_ws
    c = ws.add_curve(line([(0, 0), (10, 0)], layer=Layer.COMPONENT)).curve
    c.group_id = "beef"
    win._on_trim_applied(c, [line([(0, 0), (5, 0)], layer=Layer.COMPONENT)])
    assert ws.doc_curves == [c]
    assert "ungroup it first" in win._status.currentMessage()


def test_an_offset_rides_with_its_source(win):
    ws = win._active_ws
    src = ws.add_curve(closed_diamond(0, 0, 5, layer=Layer.COMPONENT)).curve
    src.group_id, src.component_kind = "cafe", "Hinges"
    off = closed_diamond(0, 0, 6, layer=Layer.COMPONENT)
    win._on_offset_applied(src, off)
    assert off.group_id == "cafe" and off.component_kind == "Hinges"


def test_a_trimmed_piece_keeps_its_kind():
    from framedraft.geometry import extract_open_segment
    c = line([(0, 0), (10, 0), (20, 0)], layer=Layer.COMPONENT)
    c.component_kind = "Hinges"
    assert extract_open_segment(c, 0.2, 0.7).component_kind == "Hinges"


def test_a_line_of_two_nodes_does_not_close(win):
    view = win.view
    win._act_line.trigger()
    _click(view, QPointF(0, 0))
    _click(view, QPointF(20, 0))
    _click(view, QPointF(0, 0))                     # back on the first node
    assert len(win._draw_tool._nodes) == 2 and win._draw_tool.active
    assert win._active_ws.doc_curves == []


def test_open_results_carry_no_handles_past_their_ends(win):
    from framedraft.document import ControlPoint, SplineNode
    from framedraft.document import Curve as _C
    ws = win._active_ws
    nodes = [SplineNode(x=0, y=0, cp_out=ControlPoint(3, 3)),
             SplineNode(x=10, y=0, cp_in=ControlPoint(7, 3), cp_out=ControlPoint(13, -3)),
             SplineNode(x=20, y=0, cp_in=ControlPoint(17, -3))]
    item = ws.add_curve(_C(kind="spline", layer=Layer.REF, nodes=nodes, closed=False))
    item.setSelected(True)
    win._explode_selected()
    for seg in ws.doc_curves:
        assert seg.nodes[0].cp_in is None and seg.nodes[-1].cp_out is None
    tool_curves = []
    win._act_spline.trigger()
    win._draw_tool.curve_added.connect(tool_curves.append)
    for p in (QPointF(-30, 20), QPointF(-20, 30), QPointF(-10, 20)):
        _click(win.view, p)
    win._draw_tool._finish(closed=False)
    (drawn,) = tool_curves
    assert drawn.nodes[0].cp_in is None and drawn.nodes[-1].cp_out is None


def test_a_gizmo_goes_when_another_tab_clears_its_selection(win):
    temple_l = win._workspaces[2]
    win._ws_tab_widget.setCurrentIndex(2)
    QApplication.processEvents()
    item = temple_l.add_curve(closed_diamond(70, 0, 20, layer=Layer.OUTLINE))
    item.setSelected(True)
    win._show_move_gizmo()
    assert temple_l.move_gizmo is not None
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    temple_l.scene.clearSelection()                  # as Temple Copy does
    assert temple_l.move_gizmo is None


def test_a_bookmark_brings_back_its_ghost(win, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QInputDialog
    ws = win._active_ws
    ws.add_curve(line([(0, -10), (20, 0), (0, 10)], layer=Layer.LENS))
    win._act_mirror.setChecked(True)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Half", True))
    win._add_bookmark()
    win._act_mirror.setChecked(False)                # as a bake leaves it
    win._timeline_list.setCurrentRow(0)
    win._restore_bookmark()
    assert win._act_mirror.isChecked()
    win._undo()                                      # and Undo takes it back
    assert not win._act_mirror.isChecked()
    # It travels in the file too.
    path = str(tmp_path / "bm.gdraw")
    win._do_save_gdraw(path)
    from framedraft.export.gdraw import load_gdraw
    assert load_gdraw(path)["front"]["bookmarks"][0]["snapshot"]["mirror"] is True


# ── Fit ────────────────────────────────────────────────────────────────────

def test_fit_frames_the_drawing_not_the_default_extents(win):
    win._ws_tab_widget.setCurrentIndex(3)                # Component
    QApplication.processEvents()
    win._active_ws.add_curve(closed_diamond(0, 0, 5, layer=Layer.COMPONENT))
    win._fit_view()
    view = win.view
    shown = view.mapFromScene(QRectF(-5, -5, 10, 10)).boundingRect()
    # With the tab's 10 × 20 mm stock guide in the frame too (it was ~30 px).
    assert shown.height() > 0.35 * view.viewport().height()


def test_every_tab_fits_the_next_document_on_first_sight(win, tmp_path):
    temple = win._workspaces[1]
    temple.fitted = True
    temple.view.scale(20, 20)                            # zoomed in on the old one
    win._workspaces[0].add_curve(closed_diamond(0, 0, 30))
    p = tmp_path / "next.gdraw"
    win._do_save(str(p))
    win._open_gdraw(str(p), remember=False)
    assert not temple.fitted                             # refits when shown


# ── The readiness dot ──────────────────────────────────────────────────────

def test_the_readiness_dot_answers_with_tooltips_off(win):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QHelpEvent
    f = win._tooltip_filter
    f.enabled = False
    dot = win._readiness_dot
    ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(2, 2), dot.mapToGlobal(QPoint(2, 2)))
    assert f.eventFilter(dot, ev) is True and dot.toolTip()   # shown, not swallowed
    other = QHelpEvent(QEvent.Type.ToolTip, QPoint(2, 2), QPoint(2, 2))
    assert f.eventFilter(win._weight_spin, other) is True     # swallowed: off


def test_the_readiness_tip_lists_every_gap(win):
    from framedraft.canvas.readiness_dot import readiness_state
    curves = [closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
              line([(0, 0), (5, 5), (10, 0)], layer=Layer.LENS),
              line([(20, 0), (25, 5), (30, 0)], layer=Layer.LENS)]
    state, tip = readiness_state(curves, mirror_on=False, workspace_type="front")
    assert tip.startswith("Not ready for GuildModel:\n• ")
    assert tip.count("\n• ") >= 2
    assert win._readiness_dot.toolTip() == ("Nothing to hand off yet: draw the "
                                            "OUTLINE, then the lenses.")


def test_the_panels_open_as_their_tab_and_style_have_them(win):
    assert not win._fill_image_btn.isEnabled()           # Color style: no Choose…
    assert not win._inlay_fill_tumble_chk.isEnabled()
    assert win._lib_tabs.isTabVisible(1)                  # Holes on the front
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    assert not win._lib_tabs.isTabVisible(1)
    assert win.minimumWidth() >= win._prop_dock.minimumWidth() + 480


def test_an_empty_tab_says_what_to_do_first(win):
    view = win.view
    assert view.empty_hint.isVisible()
    assert "OUTLINE" in view.empty_hint.text()
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    QApplication.processEvents()
    assert not view.empty_hint.isVisible()
    win._ws_tab_widget.setCurrentIndex(3)
    QApplication.processEvents()
    assert win.view.empty_hint.isVisible()
    assert "COMPONENT" in win.view.empty_hint.text()


def test_a_disabled_icon_is_drawn_in_the_disabled_ink(win):
    from PySide6.QtGui import QColor, QIcon
    from framedraft import theme
    from framedraft.icons import make_icon
    icon = make_icon("ellipsis", "#000000", "#000000")
    img = icon.pixmap(20, 20, QIcon.Mode.Disabled).toImage()
    inks = {img.pixelColor(x, y).name() for x in range(img.width())
            for y in range(img.height()) if img.pixelColor(x, y).alpha() == 255}
    assert inks == {QColor(theme.color("chrome.disabled_ink")).name()}


def test_snapped_boxing_with_no_lens_reads_nothing(win):
    from helpers import circle
    win._boxing_snap_chk.setChecked(True)
    QApplication.processEvents()
    for spin in (win._boxing_a_spin, win._boxing_b_spin, win._boxing_dbl_spin):
        assert spin.text() == "—"
    assert not win._lock_shape_chk.isEnabled()
    for c in (closed_diamond(0, 0, 45, layer=Layer.OUTLINE),
              circle(-20, 0, 12), circle(20, 0, 12)):
        win._active_ws.add_curve(c)
    QApplication.processEvents()
    win._refresh_measurements()
    win._sync_boxing_readouts()
    assert win._boxing_a_spin.text() != "—"
    assert win._lock_shape_chk.isEnabled()


def test_unlinking_the_lens_tint_gives_the_bottom_back(win):
    ws = win._active_ws
    win._set_lens_fill_color("top", "#112233")
    win._set_lens_fill_color("bottom", "#aabbcc")
    win._lens_link_btn.setChecked(True)
    assert ws.lens_fill_bottom == "#112233"
    win._lens_link_btn.setChecked(False)
    assert ws.lens_fill_bottom == "#aabbcc"
    assert win._fill_opacity_slider.value_label.text() == \
        f"{win._fill_opacity_slider.value()}%"


def test_the_temple_axis_shows_above_the_core_line(win):
    temple = win._workspaces[1]
    axis = temple.scene.mirror._item
    core = temple.stock_guide._items[-1]
    assert axis.zValue() > core.zValue()


# ── Snapping in every tool, and the readiness deferral (F35) ───────────────

def test_the_circle_and_dim_tools_snap_to_an_end(win):
    ws = win._active_ws
    ws.add_curve(line([(10.0, 5.0), (30.0, 5.0)], layer=Layer.REF))
    near = QPointF(10.3, 5.2)                        # within the snap radius
    win._act_circle.trigger()
    _click(win.view, near)
    assert win._circle_tool._center == pytest.approx((10.0, 5.0))
    win._act_select.trigger()
    win._act_dim.trigger()
    _click(win.view, near)
    a = win._dim_tool._pt_a
    assert (a.x(), a.y()) == pytest.approx((10.0, 5.0))


def test_readiness_waits_only_for_a_drag_on_the_canvas(win, monkeypatch):
    """A press held on a spin box's arrow never reached the canvas's release,
    and the dot kept its old color."""
    from PySide6.QtWidgets import QWidget
    monkeypatch.setattr(QApplication, "mouseButtons",
                        staticmethod(lambda: Qt.MouseButton.LeftButton))
    monkeypatch.setattr(QWidget, "mouseGrabber", staticmethod(lambda: None))
    win._readiness_deferred = False
    win._do_boxing_follow()
    assert not win._readiness_deferred               # updated at once
    viewport = win.view.viewport()
    monkeypatch.setattr(QWidget, "mouseGrabber", staticmethod(lambda: viewport))
    win._do_boxing_follow()
    assert win._readiness_deferred                   # a canvas drag: waits
    win.view.released.emit()
    assert not win._readiness_deferred               # and flushes on release
