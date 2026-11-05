"""The 2.3 bug hunt of the main window (BUILDPLAN *Road to 2.3*, item 8):
four read-only reviews, each finding confirmed offscreen, pinned here."""

import sys

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.document import Layer
from helpers import circle, closed_diamond, line


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _select(win, curves):
    win.scene.clearSelection()
    for c in curves:
        win.scene._curve_items[id(c)].setSelected(True)
    QApplication.processEvents()


def test_group_takes_a_member_on_a_hidden_layer_and_refuses_a_regroup(win):
    ws = win._active_ws
    pocket = closed_diamond(30, 0, 4, layer=Layer.COMPONENT)
    guide = line([(26, 0), (34, 0)], layer=Layer.REF)
    outline = closed_diamond(0, 0, 50)
    for c in (pocket, guide, outline):
        ws.add_curve(c)
    pocket.group_id = guide.group_id = "hinge001"
    ws.scene.set_layer_visible(Layer.REF, False)
    _select(win, [pocket, outline])
    win._group_selected()
    assert pocket.group_id == guide.group_id == outline.group_id != "hinge001"
    steps = len(ws.undo_stack)
    _select(win, [pocket, outline])
    win._group_selected()                        # already one group: no step
    assert len(ws.undo_stack) == steps
    assert win._status.currentMessage().startswith("Group: the selection is already")


def test_space_and_shift_tab_cannot_become_hotkeys(win):
    from framedraft.app import _FIXED_SHORTCUTS, _TYPING_KEYS, SettingsDialog
    fixed = {k for _n, keys in _FIXED_SHORTCUTS for k in keys}
    assert "Space" in fixed and "Shift+Tab" in _TYPING_KEYS and "Backtab" in _TYPING_KEYS
    assert "Space" in SettingsDialog._RESERVED_KEYS


def test_the_apical_radius_typed_at_the_field_minimum_is_saved(win, tmp_path):
    ws = win._active_ws
    ws.apical_radius = 0.0                       # a file with no forming block
    win._restore_ws_sidebar_state(ws)
    assert win._apical_spin.value() == 2.0       # clamped on show
    win._apical_spin.setValue(2.0)               # typing the minimum: no change seen
    win._apical_spin.setValue(2.5)
    win._apical_spin.setValue(2.0)
    win._save_ws_sidebar_state(ws)
    assert ws.apical_radius == 2.0


def test_a_full_turn_is_no_transform(win, monkeypatch):
    from framedraft.app import TransformDialog
    ws = win._active_ws
    ws.add_curve(circle(0, 0, 10))
    _select(win, ws.doc_curves)
    monkeypatch.setattr(TransformDialog, "values", lambda self: (1.0, 1.0, 360.0, False))
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod, "_run_modal", lambda d: d.DialogCode.Accepted)
    steps = len(ws.undo_stack)
    win._transform_selected()
    assert len(ws.undo_stack) == steps and not win._dirty


def test_preferences_opens_over_a_theme_mode_that_is_not_a_mapping(win, tmp_path):
    from framedraft.app import SettingsDialog
    prefs = dict(prefs_mod.load())
    prefs["theme"] = {"light": 3, "dark": "x"}
    dlg = SettingsDialog(prefs, win)
    assert dlg._base_theme == {"light": {}, "dark": {}}
    dlg.deleteLater()


# ── the canvas and the tools ───────────────────────────────────────────────

def _press_at(win, scene_x, scene_y):
    from PySide6.QtCore import QPoint
    vp = win.view.mapFromScene(scene_x, scene_y)
    return QPoint(vp.x(), vp.y())


def test_a_click_picks_the_nearest_curve_not_the_later_drawn_one(win):
    """Two REF lines 0.8 mm apart at 30 px/mm: the pick box held both and
    the topmost (later-drawn) one took a click on the other."""
    ws = win._active_ws
    lower = line([(-20, 0.0), (20, 0.0)], layer=Layer.REF)
    upper = line([(-20, 0.8), (20, 0.8)], layer=Layer.REF)
    ws.add_curve(lower)
    ws.add_curve(upper)
    win.view.resetTransform()
    win.view.scale(30, 30)
    win.view.centerOn(0, 0)
    QApplication.processEvents()
    picked = win.view._near_pick(_press_at(win, 0.0, 0.0))
    assert picked.curve is lower
    picked = win.view._near_pick(_press_at(win, 0.0, 0.8))
    assert picked.curve is upper
    # A click 27 px beside a lone curve (0.9 mm here) picks nothing.
    assert win.view._near_pick(_press_at(win, 0.0, 1.7)) is None
    # At 1 px/mm a hairline is still clickable from the pick box.
    win.view.resetTransform()
    win.view.centerOn(0, 0)
    QApplication.processEvents()
    assert win.view._near_pick(_press_at(win, 5.0, 0.0)) is not None


def test_a_double_click_keeps_a_node_whose_press_was_refused(win):
    """The last two nodes 7.5 px apart: the double-click's press was refused
    as a zero-length segment and the node under it was popped anyway."""
    from PySide6.QtCore import QPointF
    ws = win._active_ws
    tool = ws.draw_tool
    win._act_line.trigger()
    QApplication.processEvents()
    win.view.resetTransform()
    win.view.scale(5, 5)
    tool.handle_press(QPointF(0, 0), use_snap=False)
    tool.handle_press(QPointF(10, 0), use_snap=False)
    tool.handle_press(QPointF(11.5, 0), use_snap=False)    # 7.5 px from the last
    tool.handle_press(QPointF(11.5, 0), use_snap=False)    # the double-click's press: refused
    tool.handle_dbl_click(QPointF(11.5, 0), use_snap=False)
    QApplication.processEvents()
    assert len(ws.doc_curves) == 1 and len(ws.doc_curves[0].nodes) == 3
    # A 2 mm segment at 5 px/mm survives its double-click too.
    win._act_line.trigger()
    QApplication.processEvents()
    tool.handle_press(QPointF(0, 20), use_snap=False)
    tool.handle_press(QPointF(2, 20), use_snap=False)
    tool.handle_press(QPointF(2, 20), use_snap=False)
    tool.handle_dbl_click(QPointF(2, 20), use_snap=False)
    QApplication.processEvents()
    assert len(ws.doc_curves) == 2 and len(ws.doc_curves[1].nodes) == 2


def test_offset_refuses_a_distance_past_ten_meters(win):
    ws = win._active_ws
    ws.add_curve(circle(0, 0, 10))
    tool = ws.offset_tool
    tool._input_str = "100000000000"
    assert tool._parse_d() is None
    tool._input_str = "1,5"
    assert tool._parse_d() == 1.5


def test_rebuild_refuses_a_fit_with_no_shape_left(win):
    from helpers import spline
    ws = win._active_ws
    hair = spline([(0, 0), (0.002, 0), (0.002, 0.002), (0, 0.002)], closed=True,
                  layer=Layer.OUTLINE)
    ws.add_curve(hair)
    tool = ws.rebuild_tool
    messages = []
    tool.status_message.connect(messages.append)
    tool._source_curve = hair
    tool._mode = "count"
    tool._input_str = "4"
    tool._fit_timer.stop()
    tool._apply()
    assert hair in ws.doc_curves and len(hair.nodes) == 4
    assert any("too small to refit" in m for m in messages)


def test_the_fade_leaves_the_selection_halo_full_and_reaches_a_rebuilt_fill(win, tmp_path):
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 60), circle(-32, 0, 24), circle(32, 0, 24)):
        ws.add_curve(c)
    win._press_combo.setCurrentIndex(3)
    win._act_formed.trigger()
    win._formed_timer.stop()
    win._refresh_formed()
    QApplication.processEvents()
    item = ws.scene._curve_items[id(ws.doc_curves[0])]
    assert item.opacity() == 1.0 and item.faded
    assert item.pen().color().alphaF() == pytest.approx(0.28, abs=0.01)
    # A lens fill switched on under the view, and rebuilt by the fill timer,
    # comes in faded.
    ws.scene.set_lens_fill_visible(True)
    ws.scene._rebuild_dirty_overlays()
    QApplication.processEvents()
    assert ws.scene._lens_fill_items
    assert all(it.opacity() == pytest.approx(0.28) for it in ws.scene._lens_fill_items)
    win._act_formed.trigger()
    QApplication.processEvents()
    assert not item.faded and item.pen().color().alphaF() == 1.0
    assert all(it.opacity() == 1.0 for it in ws.scene._lens_fill_items)


# ── the sweep before the release (2026-11-05) ──────────────────────────────

def _type_into(spin, text):
    """Type into a panel field and leave it unentered, the focus still in it.
    The focus is the active window's to give: where a test runner's desktop
    will not make the window active, there is nothing to test."""
    from PySide6.QtTest import QTest
    top = spin.window()
    top.activateWindow()
    top.raise_()
    QTest.qWaitForWindowActive(top, 2000)
    spin.setFocus()
    QApplication.processEvents()
    if QApplication.focusWidget() is not spin:
        pytest.skip("this desktop did not give the window the keyboard focus")
    spin.selectAll()
    QTest.keyClicks(spin, text)
    QApplication.processEvents()


def _front(win):
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 60), circle(-32, 0, 24), circle(32, 0, 24)):
        ws.add_curve(c)
    QApplication.processEvents()
    return ws


def test_a_value_typed_and_not_entered_is_saved_by_ctrl_s(win, tmp_path):
    """The fields take a value on Enter or on leaving, and a shortcut takes
    no focus: the file was written without the value, with no star (2.0.0
    saved the Nose Fit and Stock fields as typed)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from framedraft.export.gdraw import load_gdraw
    ws = _front(win)
    path = tmp_path / "a.gdraw"
    assert win._do_save(str(path)) and not win._dirty
    _type_into(win._base_curve_spin, "6")
    assert win._base_curve_spin.hasFocus() and ws.thermoform.base_curve == 0.0
    if sys.platform.startswith("linux"):
        # The key itself: the shortcut's event passes the window's filter
        # before the Save action runs. (How a test's key press reaches a
        # shortcut is each platform's own; the filter's branch is one line.)
        QTest.keyClick(win._base_curve_spin, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    else:
        win._save()
    QApplication.processEvents()
    assert ws.thermoform.base_curve == 6.0 and not win._dirty
    assert load_gdraw(str(path))["front"]["thermoform"]["base_curve"] == 6.0
    # The Save button takes no focus either: the action itself enters it.
    _type_into(win._bridge_angle_spin, "33")
    win._save()
    assert ws.bridge_angle == 33.0
    assert load_gdraw(str(path))["front"]["forming"].bridge_angle_deg == 33.0


def test_a_value_typed_and_not_entered_stays_with_its_tab(win):
    """A click on a workspace tab takes no focus: the value was dropped and
    the field went back."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    _front(win)
    bar = win._ws_tab_widget.tabBar()

    def click_tab(i):
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(i).center())
        QApplication.processEvents()

    _type_into(win._base_curve_spin, "4")
    click_tab(1)
    assert win._ws_tab_widget.currentIndex() == 1
    assert win._workspaces[0].thermoform.base_curve == 4.0
    _type_into(win._bend_length_spin, "100")
    click_tab(2)
    assert win._workspaces[1].tip_bend.length_to_bend_mm == 100.0
    assert win._workspaces[2].tip_bend.length_to_bend_mm == 0.0
    # A press on the field itself is not leaving it: nothing is entered early.
    click_tab(0)
    _type_into(win._base_curve_spin, "1")
    QTest.mouseClick(win._base_curve_spin.lineEdit(), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win._workspaces[0].thermoform.base_curve == 4.0
    win._base_curve_spin.setValue(4.0)      # nothing left typed for the close to ask about


def test_closing_over_a_value_typed_and_not_entered_asks(win, tmp_path, monkeypatch):
    """It was lost without a prompt: the star came only as the window died."""
    from PySide6.QtWidgets import QMessageBox
    ws = _front(win)
    assert win._do_save(str(tmp_path / "a.gdraw")) and not win._dirty
    _type_into(win._base_curve_spin, "2")
    asked = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Cancel))
    assert win.close() is False
    assert asked and asked[0].startswith("Save the changes")
    assert ws.thermoform.base_curve == 2.0 and win._dirty


def test_a_field_in_a_dialog_is_not_entered_by_the_window(win):
    """Preferences' own fields are Preferences' to enter, on OK."""
    from PySide6.QtWidgets import QDoubleSpinBox
    from framedraft.app import SettingsDialog
    dlg = SettingsDialog(win._prefs, win)
    dlg.show()
    QApplication.processEvents()
    spin = next(s for s in dlg.findChildren(QDoubleSpinBox) if s.isVisibleTo(dlg))
    was = spin.value()
    _type_into(spin, "7")
    win._commit_pending_field()
    assert spin.value() == was
    dlg.reject()
    dlg.deleteLater()


def test_a_new_hotkey_yields_to_a_key_the_maker_already_uses(tmp_path, monkeypatch):
    """View Formed's W, merged in beside a maker's own W: neither fired, and
    Preferences opened with OK disabled over the conflict."""
    import json
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    theirs = {k: v for k, v in prefs_mod.DEFAULTS["hotkeys"].items() if k != "formed"}
    theirs["arc_sec"] = "w"                         # a 2.0 file, W on Arc S-E-C
    (tmp_path / "prefs.json").write_text(json.dumps({"hotkeys": theirs}), encoding="utf-8")
    got = prefs_mod.load()["hotkeys"]
    assert got["arc_sec"] == "w" and got["formed"] == ""
    # A maker with W free gets the new key, and one who cleared it keeps it clear.
    theirs["arc_sec"] = ""
    (tmp_path / "prefs.json").write_text(json.dumps({"hotkeys": theirs}), encoding="utf-8")
    assert prefs_mod.load()["hotkeys"]["formed"] == "W"
    theirs["formed"] = ""
    (tmp_path / "prefs.json").write_text(json.dumps({"hotkeys": theirs}), encoding="utf-8")
    assert prefs_mod.load()["hotkeys"]["formed"] == ""
    # A file with no hotkeys of its own, or a damaged block: the defaults.
    (tmp_path / "prefs.json").write_text(json.dumps({"hotkeys": "junk"}), encoding="utf-8")
    assert prefs_mod.load()["hotkeys"]["formed"] == "W"
    # The window opens on the first file with nothing in conflict.
    theirs.pop("formed")
    theirs["arc_sec"] = "W"
    (tmp_path / "prefs.json").write_text(json.dumps({"hotkeys": theirs}), encoding="utf-8")
    from framedraft.app import MainWindow, SettingsDialog
    w = MainWindow()
    try:
        dlg = SettingsDialog(w._prefs, w)
        assert dlg._ok_btn.isEnabled() and dlg._conflict_label.isHidden()
        dlg.deleteLater()
    finally:
        w._dirty = False
        w.close()
        w.deleteLater()
        QApplication.processEvents()


# ── OMA drill holes as the lab standard defines them (DCS 3.14 §5.5.2) ──────

def _oma_text(drills, dbl="18.00", a=27.0, b=20.0):
    """Two traced lenses a × b (half sizes) with *drills*: (eye, x, y)."""
    import math
    from framedraft.export.oma import OmaDrill, OmaJob, OmaTrace, build_oma
    job = OmaJob()
    if dbl is not None:
        job.set_record("DBL", dbl)
    radii = [a * b / math.hypot(b * math.cos(t), a * math.sin(t))
             for t in (2 * math.pi * i / 360 for i in range(360))]
    for side in ("R", "L"):
        job.traces[side] = OmaTrace(side=side, radii_mm=list(radii))
    for eye, x, y in drills:
        job.drills.append(OmaDrill(x=x, y=y, dia=1.4, eye=eye))
    return build_oma(job)


def _import_oma(win, monkeypatch, tmp_path, text):
    import framedraft.app as app_mod
    src = tmp_path / "lab.oma"
    src.write_text(text, encoding="ascii", newline="")
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(src), "")))
    monkeypatch.setattr(win, "_ask_oma_import_bevel", lambda d, **_k: 0.0)
    monkeypatch.setattr(win, "_ask_oma_import_mode", lambda n: "replace")
    win._import_oma()
    QApplication.processEvents()
    ws = win._active_ws
    holes = sorted((round(c.nodes[0].x, 2), round(c.nodes[0].y, 2))
                   for c in ws.doc_curves if c.layer == Layer.DRILL)
    return ws, holes


def test_a_mount_s_drill_holes_import_into_their_lenses(win, monkeypatch, tmp_path):
    """A rimless mount's file: four B records, each the right lens's hole
    and the left's mirrored. They were read from the midpoint between the
    lenses: four holes, heaped at the lens centers."""
    mount = [("B", -24.0, 4.0), ("B", -21.0, 4.0), ("B", 21.0, 3.0), ("B", 24.0, 3.0)]
    ws, holes = _import_oma(win, monkeypatch, tmp_path, _oma_text(mount))
    # Lens centers at ±(9 + 27): OD's holes as written, OS's mirrored.
    assert holes == sorted([(-60.0, -4.0), (-57.0, -4.0), (-15.0, -3.0), (-12.0, -3.0),
                            (60.0, -4.0), (57.0, -4.0), (15.0, -3.0), (12.0, -3.0)])
    msg = win._status.currentMessage()
    assert "+8 drill holes on DRILL, each from its lens's center." in msg
    assert "before 2.3" not in msg


def test_drill_holes_keep_their_place_through_an_export_and_an_import(win, monkeypatch, tmp_path):
    """One record a hole, its own eye, from its own lens's box center."""
    import framedraft.app as app_mod
    from framedraft.export.oma import parse_oma
    ws = win._active_ws
    win._act_mirror.setChecked(False)
    drawn = [(-55.0, -6.0), (-13.0, 2.0), (14.0, 3.0), (52.0, -8.0)]   # an uneven mount
    for c in (closed_diamond(0, 0, 70), circle(-34, 0, 25), circle(34, 0, 25),
              *(circle(x, y, 0.7, layer=Layer.DRILL) for x, y in drawn)):
        ws.add_curve(c)
    ws.boxing_dbl = 18.0
    monkeypatch.setattr(win, "_ask_oma_export_bevel", lambda d: 0.0)
    out = tmp_path / "trace.oma"
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win._export_oma()
    job = parse_oma(out.read_text(encoding="ascii"))
    assert sorted((d.eye, round(d.x, 2), round(d.y, 2)) for d in job.drills) == [
        ("L", -20.0, -3.0), ("L", 18.0, 8.0), ("R", -21.0, 6.0), ("R", 21.0, -2.0)]
    assert job.floats("DBL") == [18.0]
    win._dirty = False
    win._new()
    _ws, holes = _import_oma(win, monkeypatch, tmp_path, out.read_text(encoding="ascii"))
    assert holes == sorted(drawn)


def test_a_guilddraw_trace_from_before_2_3_imports_as_it_was_drawn(win, monkeypatch, tmp_path):
    """Its holes were written from the frame's center, every one tagged B:
    told apart (a temple-side hole would land a lens-width off its lens)
    and read the old way, with a word saying so."""
    old = [("B", -57.0, 6.0), ("B", -12.0, -2.0), ("B", 12.0, -2.0), ("B", 57.0, 6.0)]
    _ws, holes = _import_oma(win, monkeypatch, tmp_path, _oma_text(old))
    assert holes == [(-57.0, -6.0), (-12.0, 2.0), (12.0, 2.0), (57.0, -6.0)]
    assert "read as a GuildDraw export from before 2.3" in win._status.currentMessage()


def test_a_trace_that_states_no_dbl_takes_the_boxing_guide_s(win, monkeypatch, tmp_path):
    """A rimless pattern file writes DBL=0: the lenses came in touching
    (and a negative one overlapped them, 99999 set them 100 m apart)."""
    from framedraft.boxing import lens_bbox
    win._workspaces[0].boxing_dbl = 17.0
    for stated in ("0", "-5", "99999", None):
        win._dirty = False
        win._new()
        win._workspaces[0].boxing_dbl = 17.0
        ws, _ = _import_oma(win, monkeypatch, tmp_path, _oma_text([], dbl=stated))
        od, os_ = sorted((lens_bbox(c) for c in ws.doc_curves if c.layer == Layer.LENS),
                         key=lambda b: b[0])
        assert os_[0] - od[2] == pytest.approx(17.0, abs=0.05), stated
        assert "boxing-guide DBL 17.0 mm" in win._status.currentMessage()
    win._dirty = False
    win._new()
    ws, _ = _import_oma(win, monkeypatch, tmp_path, _oma_text([], dbl="21.5"))
    od, os_ = sorted((lens_bbox(c) for c in ws.doc_curves if c.layer == Layer.LENS),
                     key=lambda b: b[0])
    assert os_[0] - od[2] == pytest.approx(21.5, abs=0.05)
    assert "file DBL 21.5 mm" in win._status.currentMessage()


def test_the_ghost_s_twins_are_found_by_their_bounds_not_by_trying_them_all(monkeypatch):
    """Every twin was tried against every drawn curve of its layer: an
    outline of 20 000 pieces with the Ghost and the Frame Fill on took 21 s
    to reopen, and as long after each edit. Counted, not timed."""
    import math
    import framedraft.export.validate as V

    def half_ring(n, r=60.0):
        pts = [(r * math.cos(-math.pi / 2 + math.pi * i / n),
                r * math.sin(-math.pi / 2 + math.pi * i / n)) for i in range(n + 1)]
        return [line([pts[i], pts[i + 1]], layer=Layer.OUTLINE) for i in range(n)]

    calls = [0]
    real = V._stands_for
    monkeypatch.setattr(V, "_stands_for",
                        lambda *a: calls.__setitem__(0, calls[0] + 1) or real(*a))
    pieces = half_ring(1500)
    twins = V.ghost_twins(pieces, pieces)
    # The right half drawn: all but the pieces at the axis are twinned.
    assert 1400 < len(twins) <= 1500
    assert calls[0] < 20 * len(pieces), calls[0]          # it was 1500 × 1500 bounds apart
    # The answer is the scan's: a ring drawn whole needs no twin at all.
    pts = [(60 * math.cos(2 * math.pi * i / 400), 60 * math.sin(2 * math.pi * i / 400))
           for i in range(400)]
    whole = [line([pts[i], pts[(i + 1) % 400]], layer=Layer.OUTLINE) for i in range(400)]
    assert V.ghost_twins(whole, whole) == []


# ── the canvas and the tools (the 2.3 sweep; each also in 2.0.0) ────────────

def test_a_polyline_offset_grows_whatever_the_winding_and_the_distance():
    """The side was chosen by which result had the larger area, and past
    half a shape's size the inside-out inward one has: one of a library
    front's two hinge slots, 3.5 × 2 mm, offset +3 came back 2.5 × 4."""
    from framedraft.geometry import offset_curve
    slot = [(0, 0), (3.5, 0), (3.5, 2), (0, 2)]
    for pts in (slot, slot[::-1]):
        for d, want in ((0.5, (4.5, 3.0)), (3.0, (9.5, 8.0)), (9.0, (21.5, 20.0)),
                        (-0.5, (2.5, 1.0))):
            out = offset_curve(line(pts, closed=True, layer=Layer.COMPONENT), d)
            xs, ys = [n.x for n in out.nodes], [n.y for n in out.nodes]
            assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx(want), (pts[1], d)
            assert out.kind == "line" and out.closed and len(out.nodes) == 4


def test_a_polyline_offset_past_a_narrow_part_stays_one_clean_outline():
    """A block with a 2 mm lug, offset −1.5: the lug came back inside out,
    out to x = 18.5, with no word. It is dropped, as the distance swallows
    it; a shape the distance cuts in two is out of range."""
    from shapely.geometry import Polygon
    from framedraft.geometry import OffsetOutOfRange, offset_curve
    lug = [(0, 0), (10, 0), (10, 4), (20, 4), (20, 6), (10, 6), (10, 10), (0, 10)]
    for pts in (lug, lug[::-1]):
        out = offset_curve(line(pts, closed=True), -1.5)
        got = Polygon([(n.x, n.y) for n in out.nodes])
        assert got.is_valid and got.bounds == pytest.approx((1.5, 1.5, 8.5, 8.5))
        ring = [(n.x, n.y) for n in out.nodes]
        turn = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1], strict=True))
        src = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1], strict=True))
        assert (turn > 0) == (src > 0)                 # the drawn winding kept
        # In range, it is the miter it always was, node for node.
        assert len(offset_curve(line(pts, closed=True), -0.5).nodes) == 8
    u = [(0, 0), (10, 0), (10, 10), (12, 10), (12, 0), (22, 0), (22, 12), (0, 12)]
    with pytest.raises(OffsetOutOfRange, match="separate pieces"):
        offset_curve(line(u, closed=True), -1.2)
    with pytest.raises(OffsetOutOfRange, match="nothing of the shape"):
        offset_curve(line(u, closed=True), -8.0)


def test_a_double_click_on_a_new_point_keeps_it_as_the_line_s_end(win):
    """Its press placed the node, and within 12 px of the node before it was
    folded away as a duplicate: a last millimeter at working zoom, 3 mm
    zoomed out, and a two-node line canceled. Only a double-click on the
    last node (within a click's own reach) has a duplicate to fold."""
    from PySide6.QtCore import QPointF
    ws = win._active_ws
    tool = ws.draw_tool
    win._act_line.trigger()
    QApplication.processEvents()
    win.view.resetTransform()
    win.view.scale(9, 9)                                    # 9 px a millimeter
    tool.handle_press(QPointF(-20, 0), use_snap=False)
    tool.handle_press(QPointF(0, 0), use_snap=False)
    tool.handle_press(QPointF(1, 0), use_snap=False)        # the double-click's press, 9 px on
    tool.handle_dbl_click(QPointF(1, 0), use_snap=False)
    QApplication.processEvents()
    assert [(n.x, n.y) for n in ws.doc_curves[0].nodes] == [(-20, 0), (0, 0), (1, 0)]
    # A line of two nodes 9 px apart is a line.
    win._act_line.trigger()
    QApplication.processEvents()
    tool.handle_press(QPointF(0, 20), use_snap=False)
    tool.handle_press(QPointF(1, 20), use_snap=False)
    tool.handle_dbl_click(QPointF(1, 20), use_snap=False)
    QApplication.processEvents()
    assert len(ws.doc_curves) == 2 and len(ws.doc_curves[1].nodes) == 2
    # On the last node, a click's aim off it (3 px): the duplicate is folded.
    win._act_line.trigger()
    QApplication.processEvents()
    tool.handle_press(QPointF(0, 40), use_snap=False)
    tool.handle_press(QPointF(10, 40), use_snap=False)
    tool.handle_press(QPointF(10.3, 40), use_snap=False)
    tool.handle_dbl_click(QPointF(10.3, 40), use_snap=False)
    QApplication.processEvents()
    assert [(n.x, n.y) for n in ws.doc_curves[2].nodes] == [(0, 40), (10, 40)]


def _zoom(win, px_per_mm, at=(0.0, 0.0)):
    from PySide6.QtCore import QPointF
    win.view.resetTransform()
    win.view.scale(px_per_mm, px_per_mm)
    win.view.centerOn(QPointF(*at))
    QApplication.processEvents()


def test_the_cursor_tools_pick_nothing_well_beside_a_curve_at_high_zoom(win):
    """A curve's hit stroke is 2 mm wide at any zoom: Trim, Split, Fillet,
    Offset and Rebuild acted on a click 27 px beside a line at 30 px/mm,
    60 px at 80. Select has stopped at 7 px since the 2.3 hunt."""
    from PySide6.QtCore import QPointF
    from framedraft.tools.trim import curve_item_at
    ws = win._active_ws
    c = line([(-20, 0), (20, 0)])
    ws.add_curve(c)
    for zoom in (30, 80):
        _zoom(win, zoom)
        on = curve_item_at(win.view, QPointF(1.0, 6.0 / zoom))        # 6 px beside it
        assert on is not None and on.curve is c
        assert curve_item_at(win.view, QPointF(1.0, 27.0 / zoom)) is None
    _zoom(win, 4)                                                     # zoomed out: 8 px is 2 mm
    assert curve_item_at(win.view, QPointF(1.0, 1.5)).curve is c


def test_split_snaps_to_a_crossing_on_screen_and_a_double_click_splits_once(win):
    """Its snap was 1.5 mm at any zoom (120 px at 80 px/mm): a click nowhere
    near a crossing split there, and the crossing curve with it. And the
    double-click was taken for a second press, which split one of the two
    pieces again."""
    from PySide6.QtCore import QPointF
    ws = win._active_ws
    a, b = line([(-20, 0), (20, 0)]), line([(0, -20), (0, 20)])
    ws.add_curve(a)
    ws.add_curve(b)
    _zoom(win, 80)
    win._act_split_curve.trigger()
    QApplication.processEvents()
    tool = ws.split_tool
    steps = len(ws.undo_stack)
    pos = QPointF(1.2, 0.0)                                 # 96 px from the crossing
    tool.handle_press(pos, use_snap=False)
    tool.handle_dbl_click(pos, use_snap=False)
    QApplication.processEvents()
    assert len(ws.undo_stack) == steps + 1                  # one split, one step
    assert b in ws.doc_curves                               # the crossing line whole
    cuts = sorted(round(n.x, 6) for c in ws.doc_curves if c is not b
                  for n in (c.nodes[0], c.nodes[-1]))
    assert cuts == [-20.0, 1.2, 1.2, 20.0]                  # at the click, not the crossing
    # Near the crossing on screen it still snaps there and splits both.
    win._undo()
    QApplication.processEvents()
    win._act_split_curve.trigger()
    QApplication.processEvents()
    line_a = next(c for c in ws.doc_curves if c.nodes[0].y == 0 and c.nodes[-1].y == 0)
    assert len(line_a.nodes) == 2
    tool.handle_press(QPointF(0.1, 0.0), use_snap=False)    # 8 px from it
    QApplication.processEvents()
    ends = sorted((round(c.nodes[0].x, 6) + 0.0, round(c.nodes[0].y, 6) + 0.0,
                   round(c.nodes[-1].x, 6) + 0.0, round(c.nodes[-1].y, 6) + 0.0)
                  for c in ws.doc_curves)
    assert ends == [(-20.0, 0.0, 0.0, 0.0), (0.0, -20.0, 0.0, 0.0),
                    (0.0, 0.0, 0.0, 20.0), (0.0, 0.0, 20.0, 0.0)], ends


def test_join_leaves_a_v_open_rather_than_fold_a_leg_away(win):
    """Two 20 mm lines meeting at a point, their free ends 1.5 mm apart:
    Join closed the chain by moving the tail onto the head, and what came
    back was one line there and back."""
    ws = win._active_ws
    a, b = line([(20, 0), (0, 0)]), line([(0, 0), (20, 1.5)])
    ws.add_curve(a)
    ws.add_curve(b)
    _select(win, [a, b])
    win._join_selected_curves()
    QApplication.processEvents()
    [v] = ws.doc_curves
    assert not v.closed and len(v.nodes) == 3
    assert sorted((n.x, n.y) for n in v.nodes) == [(0, 0), (20, 0), (20, 1.5)]
    # Four sides drawn as four lines, the last corner a hair open, still close.
    ws.remove_curve(v)
    sides = [line([(0, 0), (10, 0)]), line([(10, 0), (10, 6)]), line([(10, 6), (0, 6)]),
             line([(0, 6), (0, 0.05)])]
    for c in sides:
        ws.add_curve(c)
    _select(win, sides)
    win._join_selected_curves()
    QApplication.processEvents()
    [box] = ws.doc_curves
    assert box.closed and len(box.nodes) == 4


def test_a_typed_length_takes_plain_digits_only(win):
    """str.isdigit() says yes to "²", a plain key on an AZERTY keyboard: it
    went into the buffer, the buffer did not parse, and Enter ended the line."""
    from PySide6.QtCore import QPointF, Qt
    ws = win._active_ws
    tool = ws.draw_tool
    win._act_line.trigger()
    QApplication.processEvents()
    tool.handle_press(QPointF(0, 0), use_snap=False)
    tool.handle_key(Qt.Key.Key_twosuperior, "²")
    tool.handle_key(Qt.Key.Key_5, "5")
    assert tool._len_input == "5"
    tool.handle_key(Qt.Key.Key_Escape, "")
    QApplication.processEvents()


# ── files (the 2.3 sweep) ───────────────────────────────────────────────────

def test_a_fill_image_named_in_a_gdraw_and_not_found_keeps_its_name(tmp_path):
    """Emptied, the fill's Image style was written as Color at the next save
    and the name was gone; an .svg design in the same place kept both."""
    import zipfile
    from framedraft.export import gdraw
    doc = tmp_path / "a.gdraw"
    with zipfile.ZipFile(doc, "w") as zf:
        zf.writestr("manifest.json", "{}")
    with zipfile.ZipFile(doc) as zf:
        fill = {"style": "image", "image": "UB-0614.jpeg"}
        gdraw._extract_fill_image(zf, zf.namelist(), str(doc), "front", fill)
        assert fill["image"] == "UB-0614.jpeg"
        (tmp_path / "UB-0614.jpeg").write_bytes(b"\xff\xd8\xff\xe0swatch")
        gdraw._extract_fill_image(zf, zf.namelist(), str(doc), "front", fill)
        assert fill["image"] == str(tmp_path / "UB-0614.jpeg")
        # A name that climbs out of the design's folder is not followed.
        out = {"style": "image", "image": "../outside.jpeg"}
        (tmp_path.parent / "outside.jpeg").write_bytes(b"\xff\xd8\xff\xe0x")
        try:
            gdraw._extract_fill_image(zf, zf.namelist(), str(doc), "front", out)
            assert not out["image"].endswith(str(tmp_path.parent / "outside.jpeg"))
            assert out["image"] != str((tmp_path.parent / "outside.jpeg").resolve())
        finally:
            (tmp_path.parent / "outside.jpeg").unlink()


def test_absurd_numbers_in_the_preferences_do_not_stop_the_start(tmp_path, monkeypatch):
    """An integer of 310 digits has no float, a list nested 100 000 deep
    overruns the reader, and a vignette of 1e15 overflowed its slider:
    GuildDraw did not start, or Preferences did not open."""
    import json
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text('{"snap_radius_px": ' + "9" * 310 + "}",
                                         encoding="utf-8")
    assert prefs_mod.load()["snap_radius_px"] == prefs_mod.DEFAULTS["snap_radius_px"]
    (tmp_path / "prefs.json").write_text("[" * 100000, encoding="utf-8")
    assert prefs_mod.load()["snap_radius_px"] == prefs_mod.DEFAULTS["snap_radius_px"]
    assert prefs_mod.LOAD_NOTE and "could not be read" in prefs_mod.LOAD_NOTE
    for stale in tmp_path.glob("prefs.json.damaged-*"):
        stale.unlink()
    (tmp_path / "prefs.json").write_text(json.dumps({"viewport": {"vignette": 1e15}}),
                                         encoding="utf-8")
    from framedraft.app import MainWindow, SettingsDialog
    w = MainWindow()
    try:
        dlg = SettingsDialog(w._prefs, w)
        assert 0 <= dlg._vignette_slider.value() <= 100
        dlg.deleteLater()
    finally:
        w._dirty = False
        w.close()
        w.deleteLater()
        QApplication.processEvents()
