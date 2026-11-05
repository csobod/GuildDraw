"""View Formed and the groups behind it (BUILDPLAN *Road to 2.3*): the
front after the press over the faded flat drawing, the temple with its tip
bend, each tab's Forming group, Flatten Lens Shape, the file round trip and the
OMA export's forming records. A view only, as View Obverse is."""
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QFileDialog, QFormLayout, QMessageBox

import framedraft.prefs as prefs_mod
from framedraft.document import Layer, TextObject
from framedraft.forming import ThermoformParams, TipBendParams
from helpers import circle, closed_diamond, line

_SVG_NS = "http://www.w3.org/2000/svg"


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


def _front(win):
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 60), circle(-32, 0, 24), circle(32, 0, 24)):
        ws.add_curve(c)
    win._fit_view()
    QApplication.processEvents()
    return ws


def _tab(win, i):
    win._ws_tab_widget.setCurrentIndex(i)
    QApplication.processEvents()
    return win._active_ws


def _temple(win, i=1):
    ws = _tab(win, i)
    ws.add_curve(line([(0, -4), (140, -4), (140, 4), (0, 4)], closed=True,
                      layer=Layer.OUTLINE))
    QApplication.processEvents()
    return ws


def _settle(win):
    timer = getattr(win, "_formed_timer", None)
    if timer is not None and timer.isActive():
        timer.stop()
        win._refresh_formed()
    QApplication.processEvents()


def _answer(monkeypatch, label, tick=False):
    """Answer the next message boxes by clicking *label*; the texts asked."""
    asked = []

    def exec_(box):
        asked.append(box.text())
        if tick and box.checkBox() is not None:
            box.checkBox().setChecked(True)
        next(b for b in box.buttons()
             if b.text().replace("&", "") == label).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", exec_)
    return asked


def _state(path, member):
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read(member))
    return json.loads(root.find(f"{{{_SVG_NS}}}metadata").text)


# ── the toggle ─────────────────────────────────────────────────────────────

def test_view_formed_overlays_the_formed_front_and_fades_the_flat_one(win):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)             # SBT base 4 / lens 4
    _settle(win)
    assert ws.thermoform.press_preset == "SBT base 4 / lens 4"
    assert len(ws.scene.formed) == 0 and not ws.view.formed_badge.isVisible()
    win._act_formed.trigger()
    _settle(win)
    assert ws.formed_view and ws.view.is_formed()
    assert len(ws.scene.formed) == 3                 # the outline and two lenses
    item = ws.scene._curve_items[id(ws.doc_curves[1])]
    assert item.faded and item.pen().color().alphaF() == pytest.approx(0.28, abs=0.01)
    # The formed lens is narrower than the drawn one, and nothing in the
    # document moved.
    formed = [p.boundingRect() for p in ws.scene.formed.paths()]
    lens_w = sorted(r.width() for r in formed)[0]
    assert 46.0 < lens_w < 48.0
    assert ws.doc_curves[1].radius == 24.0
    # A curve added meanwhile fades too.
    ws.add_curve(circle(0, 30, 5, layer=Layer.REF))
    assert ws.scene._curve_items[id(ws.doc_curves[-1])].faded
    win._act_formed.trigger()
    _settle(win)
    assert not ws.formed_view and len(ws.scene.formed) == 0
    assert not item.faded and not ws.view.formed_badge.isVisible()


def test_the_overlay_follows_edits_and_hidden_layers(win):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    win._act_formed.trigger()
    _settle(win)
    before = ws.scene.formed.paths()[1].boundingRect()
    ws.doc_curves[1].radius = 20.0
    ws.scene.refresh_curve(ws.doc_curves[1])
    QApplication.processEvents()
    win._refresh_measurements()
    after = ws.scene.formed.paths()[1].boundingRect()
    assert after.width() < before.width() - 7.0
    ws.scene.set_layer_visible(Layer.LENS, False)
    win._refresh_formed()
    assert len(ws.scene.formed) == 1                 # the outline alone


def test_each_tab_keeps_its_own_view_and_the_component_tab_refuses(win):
    _front(win)
    win._act_formed.trigger()
    assert win._active_ws.formed_view
    ws_t = _tab(win, 1)
    assert not ws_t.formed_view and not win._act_formed.isChecked()
    front = _tab(win, 0)
    assert front.formed_view and win._act_formed.isChecked()
    _tab(win, 3)
    win._hotkey_targets["formed"]()
    assert not win._act_formed.isChecked() and not win._active_ws.formed_view
    # The toolbar button, the hotkey, the menu entry and the icon.
    assert prefs_mod.DEFAULTS["hotkeys"]["formed"] == "W"
    assert prefs_mod.DEFAULTS["toolbar"]["formed"] is True
    assert win._toolbar_actions["formed"] is win._act_formed
    proxy, act = win._view_menu_toggles["formed"]
    assert act is win._act_formed and proxy.text().startswith("View Formed")


def test_a_new_document_clears_the_formed_views(win):
    ws = _front(win)
    win._act_formed.trigger()
    assert ws.formed_view
    win._dirty = False
    win._new()
    assert not ws.formed_view and len(ws.scene.formed) == 0
    assert not win._act_formed.isChecked() and not ws.scene.formed_fade()


# ── the Forming group ──────────────────────────────────────────────────────

def test_the_forming_group_reads_and_writes_the_workspace(win):
    ws = _front(win)
    assert ws.thermoform.is_flat
    assert win._radius_lbl.text() == "flat"
    win._base_curve_spin.setValue(4.0)
    _settle(win)
    assert ws.thermoform.base_curve == 4.0
    assert ws.thermoform.base_radius_mm == pytest.approx(132.5)
    assert win._radius_lbl.text() == "R 132.5 mm"
    assert win._press_combo.currentIndex() == 0
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    p = ws.thermoform
    assert (p.base_curve, p.base_radius_mm, p.face_form_deg) == (4.0, 144.0, 163.97)
    assert win._radius_lbl.text() == "R 144.0 mm (the die)"
    assert win._face_form_spin.value() == 8.02       # per side, not the included 163.97
    # A value off the row turns the row to Custom and the radius to the index's.
    win._face_form_spin.setValue(5.0)
    _settle(win)
    assert win._press_combo.currentIndex() == 0 and ws.thermoform.press_preset == ""
    assert ws.thermoform.face_form_wrap_deg == 10.0
    assert ws.thermoform.base_radius_mm == pytest.approx(132.5)
    assert win._dirty


def test_the_forming_group_holds_what_a_maker_sets_for_a_design(win):
    lay = win._forming_box.body.layout()
    assert isinstance(lay, QFormLayout)
    labels = [lay.itemAt(i, QFormLayout.ItemRole.LabelRole).widget().text()
              for i in range(lay.rowCount())
              if lay.itemAt(i, QFormLayout.ItemRole.LabelRole) is not None
              and lay.itemAt(i, QFormLayout.ItemRole.LabelRole).widget() is not None]
    assert labels[:5] == ["Preset:", "Base curve:", "Radius:", "Face form:",
                          "Bridge projection:"]
    # The switch first, the button last, and no note under it.
    first = lay.itemAt(0, QFormLayout.ItemRole.SpanningRole).widget()
    assert first is win._forming_preview_chk
    assert first.text() == "Show forming preview"
    last = lay.itemAt(lay.rowCount() - 1, QFormLayout.ItemRole.FieldRole).widget()
    assert last is win._flatten_btn and last.text() == "Flatten Lens Shape"
    for gone in ("_radius_rule_combo", "_sheet_spin", "_neutral_spin", "_forming_note",
                 "_face_form_side_lbl", "_unform_btn"):
        assert not hasattr(win, gone), gone


@pytest.mark.parametrize("row_index", [1, 2, 3, 4])
def test_a_preset_stays_through_an_edit_beside_its_rounded_face_form(win, row_index):
    """The field rounds to 0.01°: 8.015 and 4.945 per side must not read back
    as another angle and turn the row to Custom at any other edit."""
    ws = _front(win)
    win._press_combo.setCurrentIndex(row_index)
    _settle(win)
    wrap = ws.thermoform.face_form_wrap_deg
    win._projection_spin.setValue(2.0)
    _settle(win)
    assert win._press_combo.currentIndex() == row_index
    assert ws.thermoform.press_preset
    assert ws.thermoform.face_form_wrap_deg == wrap
    # A real edit of the field is taken as typed, and leaves the row.
    win._face_form_spin.setValue(win._face_form_spin.value() + 0.01)
    _settle(win)
    assert win._press_combo.currentIndex() == 0
    assert ws.thermoform.face_form_per_side_deg == pytest.approx(win._face_form_spin.value())


def test_show_forming_preview_and_the_toolbar_button_are_one_switch(win):
    ws = _front(win)
    chk, act = win._forming_preview_chk, win._act_formed
    assert not chk.isChecked() and not act.isChecked()
    chk.click()
    assert act.isChecked() and ws.formed_view and ws.view.is_formed()
    act.trigger()
    assert not chk.isChecked() and not ws.formed_view
    act.trigger()
    assert chk.isChecked()
    # A tab keeps its own view: the box shows the front's when it comes back.
    _tab(win, 1)
    assert not act.isChecked()
    _tab(win, 0)
    assert chk.isChecked() and act.isChecked()
    # A new document starts flat.
    win._dirty = False
    win._new()
    QApplication.processEvents()
    assert not chk.isChecked() and not act.isChecked()


# ── Preferences ▸ General ▸ Forming ────────────────────────────────────────

def _set_forming_prefs(win, **values):
    """Through the dialog, as OK does."""
    from framedraft.app import SettingsDialog
    dlg = SettingsDialog({**win._prefs}, win)
    spins = {"tooling_index": dlg._tooling_index_spin,
             "sheet_thickness_mm": dlg._sheet_spin,
             "neutral_fraction": dlg._neutral_spin}
    for key, value in values.items():
        spins[key].setValue(value)
    win._apply_settings(dlg.to_prefs())
    dlg.deleteLater()
    QApplication.processEvents()


def test_preferences_start_at_the_historical_standard(win):
    from framedraft.app import SettingsDialog
    dlg = SettingsDialog({**win._prefs}, win)
    assert dlg._tooling_index_spin.value() == 1.53
    assert dlg._sheet_spin.value() == 6.0
    assert dlg._neutral_spin.value() == 0.0
    assert dlg.to_prefs()["forming"] == {"tooling_index": 1.53,
                                         "sheet_thickness_mm": 6.0,
                                         "neutral_fraction": 0.0}
    dlg.deleteLater()


def test_the_tooling_index_names_the_radius_off_a_preset_only(win):
    ws = _front(win)
    win._base_curve_spin.setValue(4.0)
    _settle(win)
    assert ws.thermoform.base_radius_mm == pytest.approx(132.5)
    win._dirty = False
    _set_forming_prefs(win, tooling_index=1.523)
    assert ws.thermoform.base_radius_mm == pytest.approx(523.0 / 4.0)
    assert ws.thermoform.radius_rule == 523.0
    assert win._radius_lbl.text() == "R 130.8 mm"
    assert win._dirty                                 # the file holds the old copy
    # The next base curve typed names its radius under the new index.
    win._base_curve_spin.setValue(6.0)
    _settle(win)
    assert ws.thermoform.base_radius_mm == pytest.approx(523.0 / 6.0)
    # A preset keeps its die's own radius.
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    assert ws.thermoform.base_radius_mm == 144.0
    _set_forming_prefs(win, tooling_index=1.53)
    assert ws.thermoform.base_radius_mm == 144.0
    assert ws.thermoform.radius_rule == 530.0


def test_ok_with_nothing_changed_leaves_the_design_unmarked(win):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    before = ws.thermoform
    win._dirty = False
    _set_forming_prefs(win)
    assert ws.thermoform == before and not win._dirty


def test_a_flat_front_is_not_marked_when_the_setup_changes(win):
    ws = _front(win)
    win._dirty = False
    _set_forming_prefs(win, sheet_thickness_mm=8.0)
    assert ws.thermoform.sheet_thickness_mm == 8.0 and not win._dirty


def test_the_neutral_surface_moves_the_formed_measurements(win):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    at_front = float(win._fm["a_od"]["plane"].text())
    _set_forming_prefs(win, neutral_fraction=0.5, sheet_thickness_mm=8.0)
    assert (ws.thermoform.neutral_fraction, ws.thermoform.sheet_thickness_mm) == (0.5, 8.0)
    assert float(win._fm["a_od"]["plane"].text()) != at_front
    assert win._press_combo.currentIndex() == 3          # the design's values stand


def test_preferences_win_over_the_copy_a_file_carries(win, tmp_path):
    """No design has a field for these, so a file saved before a coupon
    settled the neutral surface must follow Preferences, or never could."""
    _front(win)
    win._base_curve_spin.setValue(4.0)
    win._face_form_spin.setValue(5.0)
    _settle(win)
    path = tmp_path / "older.gdraw"
    win._do_save_gdraw(str(path))
    assert _state(path, "front.svg")["thermoform"]["neutral_fraction"] == 0.0
    _set_forming_prefs(win, tooling_index=1.523, sheet_thickness_mm=8.0, neutral_fraction=0.5)
    win._dirty = False
    win._new()
    win._open_path(str(path))
    QApplication.processEvents()
    p = win._workspaces[0].thermoform
    assert (p.neutral_fraction, p.sheet_thickness_mm, p.radius_rule) == (0.5, 8.0, 523.0)
    assert p.base_radius_mm == pytest.approx(523.0 / 4.0)
    assert (p.base_curve, p.face_form_wrap_deg) == (4.0, 10.0)   # the design's own
    assert not win._dirty                                        # opening is not an edit
    # GuildModel reads the copy, as of the save.
    stored = _state(path, "front.svg")["thermoform"]
    assert stored["neutral_fraction"] == 0.0
    win._do_save_gdraw(str(path))
    stored = _state(path, "front.svg")["thermoform"]
    assert (stored["neutral_fraction"], stored["sheet_thickness_mm"],
            stored["radius_rule"]) == (0.5, 8.0, 523.0)


def test_a_flat_design_saves_the_setup_too(win, tmp_path):
    _front(win)
    _set_forming_prefs(win, sheet_thickness_mm=8.0)
    path = tmp_path / "flat.gdraw"
    win._new()
    win._active_ws.add_curve(closed_diamond(0, 0, 60))
    win._do_save_gdraw(str(path))
    assert _state(path, "front.svg")["thermoform"]["sheet_thickness_mm"] == 8.0


def test_the_formed_measurements_read_flat_then_formed(win):
    ws = _front(win)
    cells = lambda key: {k: v.text() for k, v in win._fm[key].items()}
    assert set(cells("a_od").values()) == {"—"}
    assert win._fm_flags.text().startswith("Flat")
    assert win._fm_table.isHidden() and win._fm_singles.isHidden()
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    assert not win._fm_table.isHidden() and not win._fm_singles.isHidden()
    a = cells("a_od")
    assert a["flat"] == "49.99" and float(a["head_on"]) < float(a["plane"]) < 49.99
    assert a["d3"] == "—"
    assert cells("dbl")["flat"] == "14.01" and cells("dbl")["plane"] == "—"
    circ = cells("circ_od")
    assert circ["head_on"] == "—" and float(circ["d3"]) >= float(circ["plane"])
    assert "ISO" in win._fm_flags.text()         # base 4 on this front
    assert win._fm_single["curve"].text() == "4.00 D · R 144.0 mm"
    assert win._fm_single["face"].text() == "8.02° per side · 163.97° included"
    assert win._fm_single["tilt"].text().count("°") == 2
    assert ws.thermoform.press_preset
    # The Nose Fit group kept its fields.
    assert win._construction_guide_box.title() == "Nose Fit"


FLATTEN_TEXT = (
    "This will recursively flatten the present lens shape based on the Forming "
    "settings as marked; this will replace the existing lens shape with its "
    "flattened version, which when formed to these parameters, will produce the "
    "lens shape as it was previously viewed. This can be undone by Ctrl+Z. Do you "
    "wish to continue?")


def test_flatten_lens_shape_is_undoable_and_keeps_the_lens_plane_size(win, monkeypatch):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    before = [c.radius for c in ws.doc_curves[1:]]
    asked = _answer(monkeypatch, "Yes")
    win._flatten_btn.click()
    QApplication.processEvents()
    assert asked == [FLATTEN_TEXT]
    assert all(c.kind == "spline" for c in ws.doc_curves[1:])
    assert win._status.currentMessage().startswith("Flattened 2 lenses")
    _settle(win)
    plane = float(win._fm["a_od"]["plane"].text())
    assert plane == pytest.approx(49.99, abs=0.1)
    ws.undo()
    QApplication.processEvents()
    assert [c.radius for c in ws.doc_curves[1:]] == before
    # Flat: nothing to do, and the box is not asked.
    win._press_combo.setCurrentIndex(0)
    win._base_curve_spin.setValue(0.0)
    _settle(win)
    assert not ws.thermoform.is_flat               # the face form still bends
    win._face_form_spin.setValue(0.0)
    _settle(win)
    assert ws.thermoform.is_flat
    asked.clear()
    win._flatten_btn.click()
    assert win._status.currentMessage().startswith("Flatten Lens Shape: the front is flat")
    assert asked == []


def test_declining_flatten_lens_shape_changes_nothing(win, monkeypatch):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    win._dirty = False
    undo_depth = len(ws.undo_stack)
    _answer(monkeypatch, "No", tick=True)
    win._flatten_btn.click()
    assert all(c.kind == "circle" for c in ws.doc_curves[1:])
    assert len(ws.undo_stack) == undo_depth and not win._dirty
    assert win._prefs["prompt_flatten_lens"] is True      # No does not silence it


def test_flatten_lens_shape_asks_nothing_when_it_cannot_run(win, monkeypatch):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    asked = _answer(monkeypatch, "Yes")
    ws.shape_locked = True
    win._flatten_btn.click()
    assert "locked" in win._status.currentMessage() and asked == []
    ws.shape_locked = False
    for c in list(ws.doc_curves[1:]):
        ws.doc_curves.remove(c)
    win._flatten_btn.click()
    assert win._status.currentMessage() == "Flatten Lens Shape: no lens is drawn."
    assert asked == []


def test_dont_ask_again_silences_the_box_and_preferences_turn_it_back_on(win, monkeypatch):
    from framedraft.app import SettingsDialog
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    asked = _answer(monkeypatch, "Yes", tick=True)
    win._flatten_btn.click()
    assert len(asked) == 1 and win._prefs["prompt_flatten_lens"] is False
    ws.undo()
    win._flatten_btn.click()
    assert len(asked) == 1                                # flattened without asking
    assert all(c.kind == "spline" for c in ws.doc_curves[1:])
    dlg = SettingsDialog({**win._prefs}, win)
    assert not dlg._prompt_flatten_chk.isChecked()
    dlg._prompt_flatten_chk.setChecked(True)
    assert dlg.to_prefs()["prompt_flatten_lens"] is True
    dlg.deleteLater()


# ── the Forming group on a temple ──────────────────────────────────────────

def test_the_temple_s_section_reads_as_the_front_s(win):
    assert win._tip_bend_box.title() == win._forming_box.title() == "Forming"
    # Two sections, two folds: the title is not the key.
    assert win._folds["Tip Bend"] is win._tip_bend_box
    assert win._folds["Forming"] is win._forming_box
    win._folds["Forming"].set_expanded(False)
    assert win._folds["Tip Bend"].is_expanded()
    lay = win._tip_bend_box.body.layout()
    first = lay.itemAt(0, QFormLayout.ItemRole.SpanningRole).widget()
    assert first is win._tip_bend_preview_chk
    assert first.text() == "Show temple tip bend"
    # Each tab shows its own section.
    _tab(win, 1)
    assert not win._tip_bend_box.isHidden() and win._forming_box.isHidden()
    _tab(win, 0)
    assert not win._forming_box.isHidden() and win._tip_bend_box.isHidden()


def test_show_temple_tip_bend_and_the_toolbar_button_are_one_switch(win):
    ws = _temple(win, 1)
    chk, act = win._tip_bend_preview_chk, win._act_formed
    assert not chk.isChecked() and not act.isChecked()
    chk.click()
    assert act.isChecked() and ws.formed_view and ws.view.is_formed()
    _settle(win)
    assert len(ws.scene.formed) == 1                 # the bent outline
    act.trigger()
    assert not chk.isChecked() and not ws.formed_view
    act.trigger()
    assert chk.isChecked()
    # Each tab keeps its own view, and the box shows the tab's.
    _tab(win, 2)
    assert not chk.isChecked() and not act.isChecked()
    _tab(win, 0)
    assert not win._forming_preview_chk.isChecked()
    _tab(win, 1)
    assert chk.isChecked() and act.isChecked()
    # A new document starts flat.
    win._dirty = False
    win._new()
    QApplication.processEvents()
    assert not chk.isChecked() and not act.isChecked()


def test_the_note_under_the_temple_s_section_only_warns(win):
    _tab(win, 1)
    # No outline: nothing under the section; the status bar says it when asked.
    win._refresh_measurements()
    assert win._bend_note.isHidden() and win._bend_note.text() == ""
    assert win._bend_reach_lbl.text() == "—"
    win._tip_bend_preview_chk.click()
    assert win._status.currentMessage().startswith("View Formed: the temple has no outline")
    win._tip_bend_preview_chk.click()
    # A bend that fits: nothing, with the view on or off.
    _temple(win, 1)
    win._refresh_measurements()
    assert win._bend_note.isHidden() and win._bend_note.text() == ""
    win._act_formed.trigger()
    _settle(win)
    assert win._bend_note.isHidden()
    # A bend that does not fit shows straight, and says why.
    win._bend_length_spin.setValue(138.0)
    _settle(win)
    assert not win._bend_note.isHidden()
    assert win._bend_note.text().startswith("Out of range")
    win._bend_length_spin.setValue(0.0)
    _settle(win)
    assert win._bend_note.isHidden() and win._bend_note.text() == ""


def test_the_tip_bend_bends_the_temple_and_its_text(win):
    ws = _temple(win)
    ws.add_text(TextObject(text="GUILD", family="DejaVu Sans", size_mm=4.0,
                           rotation=0.0, anchor_x=120.0, anchor_y=1.5,
                           layer=Layer.ENGRAVING))
    win._refresh_measurements()
    assert win._bend_ltb_lbl.text() == "103.0 mm (auto)"
    assert win._bend_drop_lbl.text() == "37.0 mm"
    assert win._bend_overall_lbl.text() == "140.0 mm"
    assert win._bend_reach_lbl.text().startswith("127.5 mm")
    win._act_formed.trigger()
    _settle(win)
    assert len(ws.scene.formed) == 2                 # the outline and the text
    outline = ws.scene.formed.paths()[0].boundingRect()
    assert outline.right() < 132.0 and outline.bottom() > 28.0
    win._bend_length_spin.setValue(138.0)
    _settle(win)
    assert ws.tip_bend.length_to_bend_mm == 138.0
    assert win._bend_note.text().startswith("Out of range")
    assert ws.scene.formed.paths()[0].boundingRect().right() == pytest.approx(140.0)
    win._bend_angle_spin.setValue(0.0)
    _settle(win)
    assert win._bend_reach_lbl.text().endswith("(straight)")
    # The other temple keeps its own bend.
    other = _temple(win, 2)
    assert other.tip_bend == TipBendParams()


def test_a_dropped_tip_pair_bends_each_temple_toward_its_own_drop(win, monkeypatch):
    """GuildModel's hand-off, 2026-11-04: the left tab is the right's mirror
    about the core line (Temple Copy makes it so), and View Formed bent its
    tip toward +y all the same, against the drawn drop."""
    import framedraft.app as app_mod
    right = _tab(win, 1)
    right.add_curve(line([(0, -4.5), (95, -4.5), (140, -1), (140, 8), (95, 5), (0, 4.5)],
                         closed=True, layer=Layer.OUTLINE))
    win._refresh_measurements()
    win._act_formed.trigger()
    _settle(win)
    bent_r = right.scene.formed.paths()[0].boundingRect()
    reach_r = win._bend_reach_lbl.text()
    assert bent_r.bottom() > 28.0 and bent_r.top() == pytest.approx(-4.5)
    monkeypatch.setattr(
        app_mod.QMessageBox, "question",
        staticmethod(lambda *a, **k: app_mod.QMessageBox.StandardButton.Yes))
    win._copy_temple_to_other()
    left = win._active_ws
    assert left.workspace_type == "temple_l"
    win._act_formed.trigger()
    _settle(win)
    bent_l = left.scene.formed.paths()[0].boundingRect()
    # The right's bent outline, mirrored about the core line.
    assert bent_l.top() == pytest.approx(-bent_r.bottom())
    assert bent_l.bottom() == pytest.approx(-bent_r.top())
    assert bent_l.left() == pytest.approx(bent_r.left())
    assert bent_l.right() == pytest.approx(bent_r.right())
    # The same part reads the same: its reach, and its tip "down".
    assert win._bend_reach_lbl.text() == reach_r and "down" in reach_r
    assert "-" not in reach_r


def test_temple_copy_takes_the_tip_bend_with_the_temple(win, monkeypatch):
    """The 2.3 sweep: the copy kept the other tab's own bend, so the pair
    showed, and saved for GuildModel, two different bends."""
    import framedraft.app as app_mod
    right = _temple(win, 1)
    win._bend_length_spin.setValue(100.0)
    win._bend_angle_spin.setValue(45.0)
    win._bend_radius_spin.setValue(20.0)
    _settle(win)
    monkeypatch.setattr(
        app_mod.QMessageBox, "question",
        staticmethod(lambda *a, **k: app_mod.QMessageBox.StandardButton.Yes))
    win._copy_temple_to_other()
    left = win._active_ws
    assert left.workspace_type == "temple_l" and left.tip_bend == right.tip_bend
    assert left.tip_bend is not right.tip_bend             # its own copy
    assert win._bend_length_spin.value() == 100.0 and win._bend_radius_spin.value() == 20.0
    assert win._status.currentMessage().endswith("with its tip bend.")
    win._bend_length_spin.setValue(90.0)                   # the left edited alone
    _settle(win)
    assert left.tip_bend.length_to_bend_mm == 90.0 and right.tip_bend.length_to_bend_mm == 100.0


def test_the_formed_view_follows_a_text_edit_a_text_move_and_a_line_weight(win, monkeypatch):
    """The 2.3 sweep: none of the three reached the overlay, which kept the
    old glyphs, the old place and the old pen until some other edit."""
    import framedraft.app as app_mod
    from PySide6.QtWidgets import QDialog
    ws = _temple(win)
    t = TextObject(text="GUILD", family="DejaVu Sans", size_mm=4.0, rotation=0.0,
                   anchor_x=110.0, anchor_y=1.5, layer=Layer.ENGRAVING)
    ws.add_text(t)
    win._refresh_measurements()
    win._act_formed.trigger()
    _settle(win)

    def painted():
        return [(round(r.x(), 3), round(r.y(), 3), round(r.width(), 3), round(r.height(), 3),
                 round(i.pen().widthF(), 3))
                for i in ws.scene.formed._items for r in [i.path().boundingRect()]]

    def is_fresh():
        was = painted()
        win._refresh_formed()
        return was == painted()

    class Edited:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def deleteLater(self): pass
        def values(self):
            return dict(text="A LONGER ENGRAVING", family=t.family, size_mm=t.size_mm,
                        rotation=t.rotation, anchor_x=t.anchor_x, anchor_y=t.anchor_y)

    before = painted()
    monkeypatch.setattr(app_mod, "TextDialog", Edited)
    win._edit_text_object(t)
    assert t.text == "A LONGER ENGRAVING" and painted() != before and is_fresh()
    # The text dragged alone: each tick of the drag.
    item = ws.scene._text_items[id(t)]
    ws.scene.clearSelection()
    item.setSelected(True)
    QApplication.processEvents()
    ws.view._drag_move_items = [item]
    win._pre_move_selected()
    before = painted()
    win._move_selected_by(-15.0, 0.5)
    assert painted() != before and is_fresh()
    win._end_move_selected()
    # A line weight on the selected outline.
    ws.scene.clearSelection()
    ws.scene._curve_items[id(ws.doc_curves[0])].setSelected(True)
    QApplication.processEvents()
    before = painted()
    win._weight_spin.setValue(4.0)
    QApplication.processEvents()
    assert ws.doc_curves[0].line_weight == 4.0 and painted() != before and is_fresh()


# ── the files ──────────────────────────────────────────────────────────────

def test_the_forming_and_the_bends_travel_in_the_gdraw(win, tmp_path):
    _front(win)
    win._press_combo.setCurrentIndex(3)
    win._projection_spin.setValue(3.0)
    _settle(win)
    _temple(win, 1)
    win._bend_length_spin.setValue(100.0)
    win._bend_radius_spin.setValue(12.0)
    _settle(win)
    path = tmp_path / "formed.gdraw"
    win._do_save_gdraw(str(path))
    front = _state(path, "front.svg")
    assert front["thermoform"]["press_preset"] == "SBT base 4 / lens 4"
    assert front["thermoform"]["bridge_projection_mm"] == 3.0
    assert "tip_bend" not in front
    temple = _state(path, "temple_r.svg")
    assert temple["tip_bend"] == {"length_to_bend_mm": 100.0, "drop_angle_deg": 50.0,
                                  "bend_radius_mm": 12.0}
    assert "thermoform" not in temple
    win._dirty = False
    win._new()
    assert win._workspaces[0].thermoform.is_flat
    win._open_path(str(path))
    QApplication.processEvents()
    assert win._workspaces[0].thermoform.press_preset == "SBT base 4 / lens 4"
    assert win._workspaces[0].thermoform.bridge_projection_mm == 3.0
    assert win._workspaces[1].tip_bend.bend_radius_mm == 12.0
    assert win._workspaces[2].tip_bend == TipBendParams()
    _tab(win, 0)
    assert win._press_combo.currentIndex() == 3
    assert win._projection_spin.value() == 3.0


def test_a_file_without_the_blocks_opens_flat_and_straight(tmp_path):
    from framedraft.export.svg import load_svg
    svg = (f'<svg xmlns="{_SVG_NS}"><metadata>'
           + json.dumps({"curves": [], "thermoform": "junk", "tip_bend": [1]})
           + '</metadata></svg>')
    p = tmp_path / "old.svg"
    p.write_text(svg, encoding="utf-8")
    data = load_svg(str(p))
    assert data["thermoform"] is None and data["tip_bend"] is None
    assert ThermoformParams.from_dict(data["thermoform"]).is_flat


# ── the OMA export ─────────────────────────────────────────────────────────

def _export(win, monkeypatch, tmp_path):
    out = tmp_path / "trace.oma"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(win, "_ask_oma_export_bevel", lambda d: 1.0)
    win._export_oma()
    return out.read_text(encoding="ascii")


def test_the_oma_export_writes_the_forming_records_only_for_a_formed_front(
        win, monkeypatch, tmp_path):
    _front(win)
    flat = _export(win, monkeypatch, tmp_path)
    assert "FCRV" not in flat and "ZTILT" not in flat and "CIRC" not in flat
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    formed = _export(win, monkeypatch, tmp_path)
    records = dict(l.split("=", 1) for l in formed.splitlines() if "=" in l)
    assert records["FCRV"] == "3.68;3.68"            # 530 / the die's 144 mm, not the tag
    assert records["ZTILT"].split(";")[0].startswith("8.0")
    circ = [float(v) for v in records["CIRC"].split(";")]
    assert 150.0 < circ[0] < 158.0
    # The lens-plane shape is smaller than the flat one, DBL head-on larger.
    flat_r = dict(l.split("=", 1) for l in flat.splitlines() if "=" in l)
    assert float(records["HBOX"].split(";")[0]) < float(flat_r["HBOX"].split(";")[0])
    assert "Formed" in win._status.currentMessage()


def test_the_formed_table_fits_the_dock_at_its_least_width(win):
    """The one-line readouts clipped at the dock's width (the 2.3 interface
    review); the table's columns fit, forming set, at the least width."""
    from PySide6.QtWidgets import QScrollArea, QStyle
    _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    room = (win._prop_dock.minimumWidth()
            - win.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
    tabs = win._side_tabs
    for i in range(2):                     # Properties, Guides
        tabs.setCurrentIndex(i)
        QApplication.processEvents()
        page = tabs.widget(i)
        inner = page.widget() if isinstance(page, QScrollArea) else page
        assert inner.minimumSizeHint().width() <= room, tabs.tabText(i)
    assert not win._fm_table.isHidden()


def test_the_fade_keeps_a_swatch_fill_at_its_own_opacity(win, tmp_path):
    """The 2.3 forming review: View Formed set the frame fill's item to 1.0
    on the way out, over the slider's 50 % for a swatch image."""
    from PySide6.QtGui import QImage
    ws = _front(win)
    img = tmp_path / "swatch.png"
    QImage(8, 8, QImage.Format.Format_RGB32).save(str(img))
    ws.scene.set_fill_visible(True)
    assert ws.scene.set_fill_image(str(img))
    ws.scene.set_fill_opacity(0.5)
    QApplication.processEvents()
    item = ws.scene._fill_item
    assert item.opacity() == pytest.approx(0.5)
    win._press_combo.setCurrentIndex(3)
    win._act_formed.trigger()
    _settle(win)
    assert item.opacity() == pytest.approx(0.5 * 0.28)
    ws.scene.set_fill_opacity(0.8)             # a slider tick while the view is on
    QApplication.processEvents()
    assert ws.scene._fill_item.opacity() == pytest.approx(0.8 * 0.28)
    win._act_formed.trigger()
    _settle(win)
    assert ws.scene._fill_item.opacity() == pytest.approx(0.8)


def test_a_temple_without_an_outline_is_not_faded_and_the_png_takes_the_bend(
        win, tmp_path, monkeypatch):
    ws = _tab(win, 1)
    ws.add_curve(line([(10, -2), (60, -2)], layer=Layer.REF))
    win._act_formed.trigger()
    _settle(win)
    assert not ws.scene.formed_fade() and len(ws.scene.formed) == 0
    ws.add_curve(line([(0, -4), (140, -4), (140, 4), (0, 4)], closed=True,
                      layer=Layer.OUTLINE))
    win._refresh_measurements()
    assert ws.scene.formed_fade() and len(ws.scene.formed) == 2
    rect = win._png_content_rect()
    assert rect.bottom() > 25.0                 # the bent tail, past the flat 4 mm
    out = tmp_path / "bent.png"
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("150 dpi — draft", True)))
    win._export_png()
    assert out.exists() and "formed" in win._status.currentMessage()


def test_the_formed_oma_export_moves_the_holes_with_the_lenses(win, monkeypatch, tmp_path):
    """The 2.3 files hunt: the radii were in the lens plane while the holes
    stayed in the flat drawing. Each hole is written from its own lens's box
    center, on its own eye (the 2.3 sweep; DCS 3.14 §5.5.2)."""
    from framedraft.export.oma import parse_oma
    ws = _front(win)
    ws.add_curve(circle(-50, -10, 0.7, layer=Layer.DRILL))   # 18 mm temporal of OD's center
    flat = parse_oma(_export(win, monkeypatch, tmp_path))
    assert [(d.eye, d.ftype) for d in flat.drills] == [("R", "C"), ("L", "C")]   # and its Ghost twin
    assert (flat.drills[0].x, flat.drills[0].y) == pytest.approx((-18.0, 10.0), abs=1e-6)
    assert (flat.drills[1].x, flat.drills[1].y) == pytest.approx((18.0, 10.0), abs=1e-6)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    formed = parse_oma(_export(win, monkeypatch, tmp_path))
    r, l = formed.drills
    assert (r.eye, l.eye) == ("R", "L")
    # In the lens plane the lens is narrower, and the hole with it: nearer
    # its lens's center, by the lens's own shrink, on both eyes alike.
    hbox_flat, hbox = flat.floats("HBOX")[0], formed.floats("HBOX")[0]
    assert hbox < hbox_flat
    assert -18.0 < r.x < -17.0 and r.x / -18.0 == pytest.approx(hbox / hbox_flat, abs=0.01)
    assert (l.x, l.y) == pytest.approx((-r.x, r.y), abs=0.011)   # each rounded to 0.01
    # It keeps its place in the lens: as far inside the box's edge as before.
    assert hbox / 2 + r.x == pytest.approx((hbox_flat / 2 - 18.0) * hbox / hbox_flat, abs=0.05)


def test_a_gdraw_naming_a_tab_it_does_not_hold_is_an_error(win, tmp_path, monkeypatch):
    """The 2.3 files hunt: such a file opened "ok" and the next Save wrote an
    empty tab over it."""
    import os
    from framedraft.export.gdraw import load_gdraw
    _front(win)
    path = tmp_path / "damaged.gdraw"
    win._do_save_gdraw(str(path))
    cut = tmp_path / "cut.gdraw"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(cut, "w") as dst:
        for name in src.namelist():
            if name != "front.svg":
                dst.writestr(name, src.read(name))
    data = load_gdraw(str(cut))
    assert data["errors"] and data["errors"][0].startswith("front:")
    # A file from before the manifest named its tabs opens as it did.
    bare = tmp_path / "bare.gdraw"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(bare, "w") as dst:
        for name in src.namelist():
            if name not in ("front.svg", "manifest.json"):
                dst.writestr(name, src.read(name))
    assert not load_gdraw(str(bare))["errors"]
    win._dirty = False
    win._new()
    from PySide6.QtWidgets import QMessageBox
    boxes = []
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, _n=name, **k: boxes.append(_n) or 0))
    win._open_path(str(cut))
    QApplication.processEvents()
    assert boxes
    assert win._current_path is None             # not kept for the next Save
    assert os.path.getsize(cut) > 0


# ── the sweep before the release (2026-11-05) ──────────────────────────────

def test_flatten_puts_the_node_dots_on_the_new_nodes_and_lights_undo(win, monkeypatch):
    """A selected lens kept its dots where the nodes had been (a circle its
    one center dot, now bound to a node of the spline it became), and the
    next drag of one wrecked the lens; Edit ▸ Undo stayed gray beside a
    status bar saying "Undo takes it back"."""
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    _answer(monkeypatch, "Yes")
    lens = ws.doc_curves[1]
    ws.scene.clearSelection()
    ws.scene._curve_items[id(lens)].setSelected(True)
    QApplication.processEvents()
    assert not win._act_undo.isEnabled()
    win._flatten_btn.click()
    QApplication.processEvents()
    assert lens.kind == "spline" and ws.doc_curves[2].kind == "circle"   # the selected one only
    dots = sorted((round(d.pos().x(), 6), round(d.pos().y(), 6)) for d in win._edit_tool._dots)
    assert dots == sorted((round(n.x, 6), round(n.y, 6)) for n in lens.nodes)
    assert win._act_undo.isEnabled() and win._dirty
    win._undo()
    QApplication.processEvents()
    assert all(c.kind == "circle" for c in ws.doc_curves[1:])


def test_flatten_leaves_a_locked_or_hidden_lens_layer_alone(win, monkeypatch):
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    asked = _answer(monkeypatch, "Yes")
    depth = len(ws.undo_stack)
    ws.scene.set_layer_locked(Layer.LENS, True)
    win._flatten_btn.click()
    assert "LENS layer is locked" in win._status.currentMessage()
    ws.scene.set_layer_locked(Layer.LENS, False)
    ws.scene.set_layer_visible(Layer.LENS, False)
    win._flatten_btn.click()
    assert "LENS layer is hidden" in win._status.currentMessage()
    assert asked == [] and len(ws.undo_stack) == depth
    assert all(c.kind == "circle" for c in ws.doc_curves[1:])


def test_flatten_says_so_when_the_forming_is_too_deep_and_changes_nothing(win, monkeypatch):
    ws = _front(win)
    for c, x in zip(ws.doc_curves[1:], (-42.0, 42.0), strict=True):   # 64 mm lenses
        c.nodes[0].x, c.radius = x, 32.0
        ws.scene.refresh_curve(c)
    win._base_curve_spin.setValue(16.0)
    win._face_form_spin.setValue(15.0)
    _settle(win)
    _answer(monkeypatch, "Yes")
    depth = len(ws.undo_stack)
    win._dirty = False
    win._flatten_btn.click()
    msg = win._status.currentMessage()
    assert msg.startswith("Flatten Lens Shape: the flat shape was not found")
    assert msg.endswith("Nothing was changed.")
    assert all(c.kind == "circle" for c in ws.doc_curves[1:])
    assert len(ws.undo_stack) == depth and not win._dirty


def test_a_stray_line_on_the_lens_layer_is_no_lens(win, monkeypatch):
    """It gave "Flattened 1 lens: ;", an undo step and a star, and as a
    third "lens" it moved the map's apex."""
    ws = _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    tilt = win._fm_single["tilt"].text()
    ws.add_curve(line([(-3, 30), (3, 31)], layer=Layer.LENS))
    win._refresh_measurements()
    _settle(win)
    assert win._fm_single["tilt"].text() == tilt
    asked = _answer(monkeypatch, "Yes")
    for c in list(ws.doc_curves[1:3]):
        ws.remove_curve(c)
    depth = len(ws.undo_stack)
    win._flatten_btn.click()
    assert win._status.currentMessage() == "Flatten Lens Shape: no lens is drawn."
    assert asked == [] and len(ws.undo_stack) == depth


def test_the_band_flag_is_quiet_on_a_front_with_a_bevel(win):
    """Every front with a bevel depth read "reaches into the bridge band"
    in red: the band is measured from the drawn lenses, the readout from
    the finished ones."""
    ws = _front(win)
    assert ws.bevel_depth > 0.0
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    assert "bridge band" not in win._fm_flags.text()
    # A pair well off the axis does reach in, and says so.
    for c in ws.doc_curves[1:]:
        c.nodes[0].x += 3.0
        ws.scene.refresh_curve(c)
    win._refresh_measurements()
    _settle(win)
    assert "OD: the lens reaches into the bridge band" in win._fm_flags.text()


def test_a_face_form_with_no_base_curve_exports_and_reads_flat(win, monkeypatch, tmp_path):
    """The OMA export divided by the radius: "The lenses could not be
    traced: division by zero"."""
    _front(win)
    win._face_form_spin.setValue(6.0)
    _settle(win)
    assert win._fm_single["curve"].text() == "Flat"
    text = _export(win, monkeypatch, tmp_path)
    assert "FCRV=0.00;0.00" in text and "ZTILT=" in text


def test_an_out_of_range_bend_reads_no_negative_drop(win):
    _temple(win)
    win._bend_length_spin.setValue(150.0)
    _settle(win)
    assert win._bend_note.text().startswith("Out of range")
    assert win._bend_drop_lbl.text() == "—" and win._bend_reach_lbl.text() == "—"


def test_a_temple_drawn_with_the_line_tool_bends_as_a_temple(win):
    """Its four corners were bent and joined with straight lines: a skewed
    quadrilateral, 22 mm from the temple."""
    ws = _temple(win)
    win._act_formed.trigger()
    _settle(win)
    path = ws.scene.formed.paths()[0]
    assert path.elementCount() > 280
    # The lower edge of the bent temple hangs well below the chord between
    # its bent corners at the middle of the straight run: it is the drawn
    # edge there, 4 mm under the core.
    assert path.contains(QPointF(60.0, 3.9)) and not path.contains(QPointF(60.0, 4.2))
    assert path.contains(QPointF(60.0, -3.9)) and not path.contains(QPointF(60.0, -4.2))


def test_the_flatten_box_is_gone_once_answered(win, monkeypatch):
    """Its "Don't ask again" checkbox had no parent: a box that outlived the
    call (any stubbed exec, as here) pointed at a checkbox already deleted,
    and the next restyle crashed the interpreter in QMessageBox."""
    _front(win)
    win._press_combo.setCurrentIndex(3)
    _settle(win)
    _answer(monkeypatch, "Yes")
    win._flatten_btn.click()
    # Back in the event loop the box is deleted (processEvents alone leaves
    # deferred deletes waiting when no loop is running, as under pytest).
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    assert not [b for b in win.findChildren(QMessageBox)
                if b.windowTitle() == "Flatten Lens Shape"]
    win._act_dark.trigger()                      # the restyle
    QApplication.processEvents()
    win._act_dark.trigger()
    QApplication.processEvents()
