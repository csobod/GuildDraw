"""The 2026-09-29 UI/UX review — one regression per window-level fix, grouped
as the reviews were: the chrome and its flows, the Properties dock, and the
canvas. (Tool-module fixes are pinned in test_ui_review_canvas.py.)"""
import json
import math
import os

import pytest
from PySide6.QtCore import QEvent, QLockFile, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox

import framedraft.prefs as prefs_mod
from framedraft.document import Layer
from helpers import closed_diamond, line


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    monkeypatch.setattr(MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    w = MainWindow()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()


def _answer(monkeypatch, button):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: button))


# ═══════════════════════════════════════════════════════ recovery slots

def _orphan(win, name="recovery-999999.gdraw"):
    """A recovery file left by a copy that is gone (no live lock)."""
    other = win._workspaces[0].add_curve(closed_diamond(0, 0, 20)).curve
    win._AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
    rec = win._AUTOSAVE_DIR / name
    win._do_save_gdraw(str(rec))
    win._workspaces[0].remove_curve(other)
    win._dirty = False
    return rec


def test_a_crashed_copys_work_is_offered_before_a_command_line_open(win, tmp_path,
                                                                    monkeypatch):
    rec = _orphan(win)
    target = tmp_path / "double-clicked.gdraw"
    target.write_bytes(b"")
    asked = []
    monkeypatch.setattr(win, "_ask_recovery",
                        lambda text, detail: asked.append(detail) or "restore")
    assert win._offer_recovery(opening=str(target)) is True
    assert "double-clicked.gdraw" in asked[0]
    assert "recovery-" not in win._status.currentMessage()   # no slot names
    assert len(win._workspaces[0].doc_curves) == 1           # restored
    assert win._dirty
    assert not rec.exists()                                   # handed over…
    assert win._autosave_paths()[0].exists()                  # …to this copy's slot
    assert win._offer_recovery() is False                     # once only


def test_discard_removes_the_orphan_and_lets_the_open_go_ahead(win, monkeypatch):
    rec = _orphan(win)
    monkeypatch.setattr(win, "_ask_recovery", lambda *_a: "discard")
    assert win._offer_recovery(opening="x.gdraw") is False
    assert not rec.exists()


def test_later_keeps_the_work_for_the_next_launch(win, monkeypatch):
    """The double-click case used to steer to No, and No deleted the work."""
    rec = _orphan(win)
    monkeypatch.setattr(win, "_ask_recovery", lambda *_a: "later")
    assert win._offer_recovery(opening="x.gdraw") is False
    assert rec.exists()
    assert not rec.with_suffix(".lock").exists()          # let go, not held
    assert win._orphan_slots() == [rec]                   # offered again


def test_a_lock_cut_short_by_a_crash_does_not_hide_the_work(win):
    import os
    import time
    rec = _orphan(win)
    rec.with_suffix(".lock").write_bytes(b"")             # written half-way
    old = time.time() - 3600
    os.utime(rec, (old, old))
    assert win._orphan_slots() == [rec]
    leftover = win._AUTOSAVE_DIR / "recovery-1-dead.lock" # its slot is gone
    leftover.write_bytes(b"")
    os.utime(leftover, (old, old))
    win._sweep_leftover_locks()
    assert not leftover.exists()


def test_a_running_copys_slot_is_never_offered_or_cleared(win):
    rec = _orphan(win, "recovery-424242.gdraw")
    live = QLockFile(str(rec.with_suffix(".lock")))
    assert live.tryLock(0)                  # held by a running process (this one)
    try:
        assert win._orphan_slots() == []
        win._clear_autosave()               # clears this copy's slot only
        assert rec.exists()
    finally:
        live.unlock()


def test_autosave_writes_a_slot_of_its_own(win):
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    win._mark_dirty()
    win._do_autosave()
    rec, meta = win._autosave_paths()
    assert rec.exists() and meta.exists()
    assert str(os.getpid()) in rec.name
    assert win._autosave_lock.isLocked()


# ═══════════════════════════════════════════════════════ saving

def test_saving_temples_to_svg_asks_first(win, tmp_path, monkeypatch):
    win._workspaces[1].add_curve(line([(0, 0), (140, 0)], layer=Layer.OUTLINE))
    win._mark_dirty()
    p = tmp_path / "front.svg"
    seen = []
    monkeypatch.setattr(win, "_ask_svg_scope",
                        lambda path, others: seen.append(others) or "cancel")
    assert win._do_save(str(p)) is False
    assert seen == [["Temple R"]] and not p.exists() and win._dirty
    monkeypatch.setattr(win, "_ask_svg_scope", lambda *_a: "front")
    assert win._do_save(str(p)) is True
    assert p.exists()
    assert win._dirty, "the temple is still unsaved"
    offered = []
    monkeypatch.setattr(win, "_ask_svg_scope", lambda *_a: "gdraw")
    monkeypatch.setattr(win, "_save_as", lambda start=None: offered.append(start))
    assert win._do_save(str(p)) is False
    assert offered == [str(tmp_path / "front.gdraw")]


def test_a_failed_save_as_keeps_the_old_path(win, tmp_path, monkeypatch):
    import framedraft.app as app_mod
    good = tmp_path / "a.gdraw"
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    assert win._do_save(str(good))
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "b.gdraw"), "")))
    monkeypatch.setattr(win, "_do_save_gdraw",
                        lambda path: (_ for _ in ()).throw(OSError("read-only")))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    win._mark_dirty()
    win._save_as()
    assert win._current_path == str(good)


# ═══════════════════════════════════════════════════════ preferences apply

def test_ok_without_changes_leaves_the_live_front_alone(win):
    win._act_snap.setChecked(False)
    win._act_mirror.setChecked(False)
    win._stock_h_spin.setValue(60.0)
    win._boxing_a_spin.setValue(44.0)
    win._dirty = False
    win._apply_settings({k: v for k, v in win._prefs.items()})
    assert not win._act_snap.isChecked()
    assert not win._act_mirror.isChecked()
    assert win._stock_h_spin.value() == 60.0
    assert win._boxing_a_spin.value() == 44.0
    assert not win._dirty


def test_a_changed_startup_value_still_applies(win):
    p = dict(win._prefs)
    p["stock_height_mm"] = 70.0
    win._apply_settings(p)
    assert win._stock_h_spin.value() == 70.0


# ═══════════════════════════════════════════════════════ the dock

def _wheel_at(widget):
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    return QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())),
                       QPoint(0, 0), QPoint(0, -120),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


def test_the_wheel_scrolls_past_an_unfocused_field(win):
    spin = win._boxing_a_spin
    before = spin.value()
    QApplication.sendEvent(spin, _wheel_at(spin))
    assert spin.value() == before
    assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_dbl_settles_on_commit(win):
    assert win._boxing_dbl_spin.keyboardTracking() is False


def test_clicking_away_from_an_untouched_scale_applies_nothing(win):
    win._dirty = False
    win._pxmm_spin.editingFinished.emit()
    assert win._image_px_per_mm is None and not win._dirty


def test_frame_height_reads_a_joined_outline_on_the_axis(win):
    win._workspaces[0].add_curve(closed_diamond(0, 0, 30, layer=Layer.OUTLINE))
    win._refresh_measurements()
    assert win._meas_frame_height_lbl.text().endswith(" mm")    # was "—"


def test_snapping_the_boxing_guide_does_not_star_the_design(win):
    win._workspaces[0].add_curve(closed_diamond(-30, 0, 20, layer=Layer.LENS))
    win._dirty = False
    win._boxing_snap_chk.setChecked(True)
    win._boxing_snap_chk.setChecked(False)
    assert not win._dirty


def test_an_unreadable_swatch_puts_the_style_back(win, tmp_path, monkeypatch):
    import framedraft.app as app_mod
    bad = tmp_path / "swatch.png"
    bad.write_bytes(b"not an image")
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(bad), "")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    ws = win._active_ws
    ws.fill_style = "image"
    win._on_fill_image_clicked()
    assert ws.fill_style == "color"


def test_typed_hole_y_reads_up(win):
    win._workspaces[0].add_curve(closed_diamond(-30, 0, 20, layer=Layer.LENS))
    cx, cy = win._lens_boxing_center()
    win._drill_x.setValue(0.0)
    win._drill_y.setValue(3.0)
    win._add_drill_hole_from_fields()
    [hole] = [c for c in win._workspaces[0].doc_curves if c.layer == Layer.DRILL]
    assert math.isclose(hole.nodes[0].y, cy - 3.0)            # scene y-down: above


def test_a_drill_pattern_lands_the_same_way_on_either_side(win, tmp_path, monkeypatch):
    """Saved from a lens drawn right of the axis, a temporal hole used to land
    nasal on a frame drawn on the left."""
    import json
    import framedraft.library as lib
    monkeypatch.setattr(lib, "_DRILLS_DIR", tmp_path / "drills")
    front = win._workspaces[0]
    front.add_curve(closed_diamond(30, 0, 20, layer=Layer.LENS))     # OS side
    win._drill_x.setValue(-15.0)                    # toward the temple
    win._drill_y.setValue(0.0)
    win._add_drill_hole_from_fields()
    [hole] = [c for c in front.doc_curves if c.layer == Layer.DRILL]
    assert hole.nodes[0].x > 30                     # temporal on the OS lens
    holes = win._current_drill_holes_relative()
    path = lib.DrillLibrary().save_entry("p", [
        {"dx": dx, "dy": dy, "dia": dia} for dx, dy, dia in holes])
    assert json.loads(open(path).read())["version"] == 2
    front.clear_document()
    front.add_curve(closed_diamond(-30, 0, 20, layer=Layer.LENS))    # OD side
    placed = lib.DrillLibrary().load_entry(path)
    win._place_drill_holes([(h["dx"], h["dy"], h["dia"]) for h in placed],
                           od_frame=placed[0]["od_frame"])
    [hole] = [c for c in front.doc_curves if c.layer == Layer.DRILL]
    assert hole.nodes[0].x < -30                    # temporal on the OD lens too


def test_a_version_1_pattern_is_placed_as_drawn(win, tmp_path, monkeypatch):
    import framedraft.library as lib
    monkeypatch.setattr(lib, "_DRILLS_DIR", tmp_path / "drills")
    (tmp_path / "drills").mkdir()
    old = tmp_path / "drills" / "old.json"
    old.write_text('{"version": 1, "holes": [{"dx": 10, "dy": 0, "dia": 1.4}]}')
    front = win._workspaces[0]
    front.add_curve(closed_diamond(30, 0, 20, layer=Layer.LENS))
    placed = lib.DrillLibrary().load_entry(str(old))
    assert placed[0]["od_frame"] is False
    win._place_drill_holes([(h["dx"], h["dy"], h["dia"]) for h in placed],
                           od_frame=False)
    [hole] = [c for c in front.doc_curves if c.layer == Layer.DRILL]
    assert math.isclose(hole.nodes[0].x, 40.0)      # as it always was


def test_the_chain_is_live_only_on_a_locked_lens(win):
    assert not win._chain_btn.isEnabled()


# ═══════════════════════════════════════════════════════ chrome

def test_selection_buttons_follow_the_tab(win):
    it = win._workspaces[0].add_curve(line([(0, 0), (10, 0)]))
    it.setSelected(True)
    assert win._act_explode.isEnabled()
    win._ws_tab_widget.setCurrentIndex(1)
    assert not win._act_explode.isEnabled()


def test_new_ends_a_half_drawn_line(win):
    win._act_line.trigger()
    win._draw_tool.handle_press(QPointF(0, 0), False, False)
    win._draw_tool.handle_press(QPointF(10, 0), False, False)
    win._new()
    assert not win._draw_tool.active
    assert win._act_select.isChecked()


def test_hiding_the_ghost_button_keeps_its_menu_entry(win):
    p = dict(win._toolbar_prefs, ghost=False)
    win._apply_toolbar_visibility(p)
    assert not win._act_mirror.isVisible()
    proxy, act = win._view_menu_toggles["ghost"]
    win._sync_view_menu_toggles()
    assert proxy.isVisible()
    before = act.isChecked()
    proxy.trigger()
    assert act.isChecked() is not before


def test_hotkey_tooltips_follow_the_binding(win):
    assert win._act_offset.toolTip().startswith("Offset (O):")
    assert win._act_line.toolTip().startswith("Line (L):")
    win._apply_hotkeys({**win._hotkey_prefs, "offset": "Q", "line": ""})
    assert win._act_offset.toolTip().startswith("Offset (Q):")
    assert win._act_line.toolTip().startswith("Line:")
    assert win._act_arc_sec.toolTip().startswith("Arc (start-end-center):")


def test_typing_keys_and_fixed_shortcuts_are_refused_as_hotkeys(win):
    from framedraft.app import SettingsDialog
    dlg = SettingsDialog(dict(win._prefs), None)
    dlg._key_edits[0].setText("1")
    assert not dlg._ok_btn.isEnabled()
    assert "typing" in dlg._conflict_label.text()
    dlg._key_edits[0].setText("Ctrl+O")
    assert "fixed shortcut" in dlg._conflict_label.text()
    # an older prefs file holding one is simply not bound
    win._apply_hotkeys({**win._hotkey_prefs, "offset": "Ctrl+O"})
    assert "offset" not in win._shortcuts


def test_every_menu_shortcut_is_in_the_fixed_list(win):
    from framedraft.app import SettingsDialog
    for act in win.menuBar().findChildren(type(win._act_new)):
        for seq in act.shortcuts():
            s = seq.toString()
            if s:
                assert s in SettingsDialog._RESERVED_KEYS, (act.text(), s)
    assert win._act_new.shortcut().toString() == "Ctrl+N"
    assert win._act_open.shortcut().toString() == "Ctrl+O"


def test_the_window_remembers_its_geometry(win, tmp_path):
    win.resize(900, 640)
    win.close()
    saved = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert saved.get("main_window_geometry")


def test_the_readiness_dot_follows_a_node_drag(win):
    win._ws_tab_widget.setCurrentIndex(1)            # a temple: OUTLINE alone
    ws = win._workspaces[1]
    c = ws.add_curve(line([(0, 0), (40, 0), (40, 20), (0, 20), (0, 5)],
                          layer=Layer.OUTLINE)).curve
    win._update_readiness()
    assert "gap" in win._readiness_dot.toolTip()
    c.nodes[-1].y = 0.0
    c.closed = True
    ws.scene.refresh_curve(c)
    win._do_boxing_follow()
    assert "gap" not in win._readiness_dot.toolTip()


def test_the_autosave_note_hands_the_bar_back(win):
    win._act_fillet.trigger()
    prompt = win._status.currentMessage()
    assert prompt
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    win._mark_dirty()
    win._do_autosave()
    assert win._status.currentMessage() == "Autosaved"
    win._status.clearMessage()                      # the 2 s timeout
    win._restore_after_autosave_note()
    assert win._status.currentMessage() == prompt


# ═══════════════════════════════════════════════════════ canvas (window side)

def _press(view, scene_pt, button, mods=Qt.KeyboardModifier.NoModifier):
    vp = view.mapFromScene(scene_pt)
    return QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(vp),
                       QPointF(view.viewport().mapToGlobal(vp)), button, button, mods)


def test_a_right_click_places_no_line_node(win):
    win.show()
    win._act_line.trigger()
    win.view.mousePressEvent(_press(win.view, QPointF(5, 5),
                                    Qt.MouseButton.RightButton))
    assert not win._draw_tool._nodes


def test_text_is_never_left_movable_by_a_tool_switch(win):
    from framedraft.document import TextObject
    win._ws_tab_widget.setCurrentIndex(1)
    t = TextObject(text="GUILD", family="DejaVu Sans", size_mm=5.0,
                   anchor_x=10.0, anchor_y=0.0, layer=Layer.ENGRAVING)
    win._active_ws.add_text(t)
    win._act_line.trigger()
    win._act_select.trigger()
    item = win.scene._text_items[id(t)]
    assert not item.flags() & item.GraphicsItemFlag.ItemIsMovable


def test_undo_mid_fillet_ends_the_tool(win):
    win._workspaces[0].add_curve(line([(0, 0), (10, 0)]))
    win._push_undo_snapshot()
    win._act_fillet.trigger()
    assert win._fillet_tool.active
    win._undo()
    assert not win._fillet_tool.active
    assert win._act_select.isChecked()


def test_ctrl_z_with_the_line_tool_idle_undoes_the_document(win):
    win._push_undo_snapshot()
    win._workspaces[0].add_curve(line([(0, 0), (10, 0)]))
    win._act_line.trigger()
    win._handle_undo()
    assert win._workspaces[0].doc_curves == []


def test_double_click_does_not_edit_a_locked_layer(win):
    win.show()
    ws = win._workspaces[0]
    c = ws.add_curve(line([(0, 0), (40, 0)], layer=Layer.LENS)).curve
    ws.scene.set_layer_locked(Layer.LENS, True)
    win.view.set_draw_tool(None)                    # re-apply selectability
    win.view.fit_view(ws.scene.itemsBoundingRect())
    vp = win.view.mapFromScene(QPointF(20, 0))
    ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(vp),
                     QPointF(win.view.viewport().mapToGlobal(vp)),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    win.view.mouseDoubleClickEvent(ev)
    assert len(c.nodes) == 2


def test_transform_turns_counter_clockwise_and_carries_dims(win, monkeypatch):
    import framedraft.app as app_mod
    from framedraft.document import DimLine
    ws = win._workspaces[0]
    it = ws.add_curve(line([(10, 0), (20, 0)]))
    d = DimLine(10, 0, 20, 0, offset=2.0)
    ws.add_dim(d)
    it.setSelected(True)
    ws.scene._dim_items[id(d)].setSelected(True)
    monkeypatch.setattr(app_mod.TransformDialog, "exec",
                        lambda self: app_mod.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(app_mod.TransformDialog, "values",
                        lambda self: (2.0, 2.0, 90.0, True))
    win._transform_selected()
    n = it.curve.nodes[1]
    # (20, 0) doubled → (40, 0), turned 90° counter-clockwise on screen
    # (scene y-down) → (0, -40)
    assert math.isclose(n.x, 0.0, abs_tol=1e-9) and math.isclose(n.y, -40.0)
    assert math.isclose(d.x1, 0.0, abs_tol=1e-9) and math.isclose(d.y1, -40.0)
    assert d.offset == 4.0
    assert "1 dim" in win._status.currentMessage()


def test_edit_text_ok_unchanged_pushes_nothing(win, monkeypatch):
    import framedraft.app as app_mod
    from framedraft.document import TextObject
    win._ws_tab_widget.setCurrentIndex(1)
    t = TextObject(text="GUILD", family="DejaVu Sans", size_mm=0.5,
                   anchor_x=10.123456, anchor_y=0.0, layer=Layer.ENGRAVING)
    win._active_ws.add_text(t)
    monkeypatch.setattr(app_mod.TextDialog, "exec",
                        lambda self: app_mod.QDialog.DialogCode.Accepted)
    depth = len(win._active_ws.undo_stack)
    win._dirty = False
    win._edit_text_object(t)
    assert len(win._active_ws.undo_stack) == depth and not win._dirty
    assert t.anchor_x == 10.123456 and t.size_mm == 0.5


def test_moving_a_lens_to_another_layer_updates_the_measurements(win):
    ws = win._workspaces[0]
    lens = ws.add_curve(closed_diamond(-30, 0, 20, layer=Layer.LENS))
    QApplication.processEvents()
    assert win._meas_od_a_lbl.text() != "—"
    win.scene.clearSelection()
    lens.setSelected(True)
    win._move_selection_to_layer(Layer.REF)
    assert win._meas_od_a_lbl.text() == "—"             # no Refresh to press
    assert not [b for b in win._prop_dock.findChildren(type(win._btn_bm_restore))
                if b.text() == "Refresh"]


def test_checkboxes_are_drawn_by_the_stylesheet_in_both_modes():
    import re
    from pathlib import Path
    from framedraft import theme
    for dark in (False, True):
        theme.set_dark(dark)
        try:
            qss = theme.build_qss()
        finally:
            theme.set_dark(False)
        assert "QCheckBox::indicator" in qss
        [tick] = re.findall(r'image: url\("([^"]+)"\)', qss)
        assert Path(tick).is_file() and tick.endswith(
            "check-dark.svg" if dark else "check-light.svg")



# ═══════════════════════════════════════════════════════ the second sweep

def test_the_wheel_still_scrolls_the_panels(win):
    """The guard caught the scroll bars too, so nothing scrolled at all."""
    from PySide6.QtWidgets import QScrollArea
    win.resize(1200, 500)
    win.show()
    win._side_tabs.setCurrentIndex(1)                    # Guides
    QApplication.processEvents()
    area = win._side_tabs.currentWidget()
    assert isinstance(area, QScrollArea)
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0
    vp = area.viewport()
    QApplication.sendEvent(vp, _wheel_at(vp))
    assert bar.value() > 0


def test_restoring_a_bookmark_ends_a_curve_holding_tool(win):
    win._workspaces[0].add_curve(line([(0, 0), (10, 0)]))
    win._active_ws.bookmarks.append(
        {"name": "b", "timestamp": "t", "snapshot": win._take_snapshot()})
    win._refresh_timeline_list()
    win._timeline_list.setCurrentRow(0)
    win._act_fillet.trigger()
    win._restore_bookmark()
    assert not win._fillet_tool.active


def test_a_fill_turned_on_behind_a_hidden_layer_waits_for_it(win):
    ws = win._workspaces[0]
    ws.add_curve(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    ws.scene.set_layer_visible(Layer.OUTLINE, False)
    assert ws.scene.set_fill_visible(True) == "ok"
    ws.scene.set_layer_visible(Layer.OUTLINE, True)
    ws.scene.rebuild_fill()
    assert ws.scene.fill_state()["visible"] is True


def test_preferences_leaves_no_dialog_behind(win, monkeypatch):
    from framedraft.app import SettingsDialog
    monkeypatch.setattr(SettingsDialog, "exec",
                        lambda self: SettingsDialog.DialogCode.Rejected)
    for _ in range(3):
        win._open_settings()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not win.findChildren(SettingsDialog)


def test_a_scale_typed_before_the_photo_applies_to_it(win, tmp_path):
    from PySide6.QtGui import QImage
    img = tmp_path / "face.png"
    QImage(300, 200, QImage.Format.Format_RGB32).save(str(img))
    win.scene.set_face_calibration(10.0)
    idx = win.scene.add_face(str(img))
    item = win.scene.get_face_item(idx)
    assert math.isclose(item.boundingRect().width() * item.scale(), 30.0, rel_tol=1e-6)


def test_hotkey_tooltips_do_not_pile_up(win):
    for key in ("/", "F2", "[", "Num+5", "", "O"):
        win._apply_hotkeys({**win._hotkey_prefs, "offset": key})
    assert win._act_offset.toolTip().startswith("Offset (O):")
    assert win._act_offset.toolTip().count("(") == 1 + win._act_offset.toolTip().split(":", 1)[1].count("(")


def test_a_middle_double_click_still_pans(win):
    win.show()
    vp = win.view.viewport().rect().center()
    ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(vp),
                     QPointF(win.view.viewport().mapToGlobal(vp)),
                     Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton,
                     Qt.KeyboardModifier.NoModifier)
    win.view.mouseDoubleClickEvent(ev)
    assert win.view._pan_active


def test_the_1to1_pdf_reports_an_unwritable_path(win, tmp_path, monkeypatch):
    import framedraft.app as app_mod
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    bad = tmp_path / "missing" / "x.pdf"
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(bad), "")))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: errors.append(a)))
    win._export_pdf_1to1()
    assert errors and not bad.exists()


def test_prints_mirror_only_what_the_canvas_ghosts(win):
    ws = win._workspaces[0]
    ws.add_curve(line([(-30, 5), (-10, 5)], layer=Layer.REF))
    ws.add_curve(closed_diamond(-25, 0, 10, layer=Layer.LENS))
    win._save_ws_sidebar_state(ws)
    front = win._gather_template_components()["front"]["curves"]
    assert sum(c.layer == Layer.REF for c in front) == 1
    assert sum(c.layer == Layer.LENS for c in front) == 2


def test_dragging_a_photo_marks_the_design_unsaved(win, tmp_path):
    from PySide6.QtGui import QImage
    img = tmp_path / "face.png"
    QImage(300, 200, QImage.Format.Format_RGB32).save(str(img))
    idx = win.scene.add_face(str(img))
    win._dirty = False
    win.view._faces_at_press = win.view._face_positions()
    win.scene.get_face_item(idx).moveBy(5, 5)
    rel = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
                      Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier)
    win.view.mouseReleaseEvent(rel)
    assert win._dirty


def test_a_new_lens_fill_default_that_moves_a_design_stars_it(win):
    win._workspaces[0].add_curve(closed_diamond(-25, 0, 10, layer=Layer.LENS))
    win._dirty = False
    p = dict(win._prefs)
    p["lens_fill_opacity_pct"] = 85
    win._apply_settings(p)
    assert win._dirty


def test_the_endpiece_reads_a_one_piece_temple(win):
    win._ws_tab_widget.setCurrentIndex(1)
    win._active_ws.add_curve(line([(0, -6), (150, -3), (150, 3), (0, 6)],
                                  closed=True, layer=Layer.OUTLINE))
    win._refresh_measurements()
    assert win._meas_endpiece_lbl.text() == "12.0 mm"


def test_the_window_can_be_short(win):
    assert win.minimumSizeHint().height() < 520


def test_snap_node_goes_dark_when_the_red_node_goes(win):
    ws = win._workspaces[0]
    it = ws.add_curve(line([(0, 0), (10, 0), (20, 0)]))
    it.setSelected(True)
    win._edit_tool._on_node_clicked(win._edit_tool._dots[1])
    assert win._act_snap_ep.isEnabled()
    win._edit_tool.clear()
    assert not win._act_snap_ep.isEnabled()


def test_the_layer_label_follows_new(win):
    win._active_ws.active_layer = Layer.REF
    win._update_info_label()
    win._new()
    assert win._info_label.text().startswith(win._active_ws.active_layer.value)
