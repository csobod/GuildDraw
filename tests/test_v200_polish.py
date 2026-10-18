"""The 2.0 polish round (BUILDPLAN Road to 2.0, item 14): the menus reach
every command, dialogs name what they act on and default to the safe
answer, the library's Save asks before replacing, the Layers panel names
groups as the maker sees them."""
import gc

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import framedraft.prefs as prefs_mod
from framedraft import library as lib_mod
from framedraft.canvas.items import CurveItem
from framedraft.document import Layer
from helpers import circle, closed_diamond


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
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    gc.collect()            # see test_v200_bug_hunt's fixture


def _select(win):
    win.scene.clearSelection()
    for it in win.scene.items():
        if isinstance(it, CurveItem):
            it.setSelected(True)


# ── Menus ──────────────────────────────────────────────────────────────────

def test_the_menus_have_mnemonics_and_an_about_box(win, monkeypatch):
    tops = [a.text() for a in win.menuBar().actions()]
    assert tops == ["&File", "&Edit", "&View", "&Settings", "&Help"]
    shown = []
    monkeypatch.setattr(QMessageBox, "about", lambda *a: shown.append(a))
    win._act_about.trigger()
    assert shown and "GuildDraw" in shown[0][1] and "2.0.0" in shown[0][2]


def test_a_hidden_button_stays_in_the_menus(win):
    prefs = dict(win._toolbar_prefs, split=False, explode=False, grid=False)
    win._apply_toolbar_visibility(prefs)
    assert not win._act_explode.isVisible()
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 20, layer=Layer.OUTLINE))
    _select(win)
    win._sync_modify_menu()
    proxy, act = win._modify_menu_ops["explode"]
    assert proxy.isVisible() and proxy.isEnabled()
    proxy.trigger()
    assert len(ws.doc_curves) == 4                    # exploded
    grid_proxy, grid_act = win._view_menu_toggles["grid"]
    grid_proxy.trigger()
    assert grid_act.isChecked()


def test_menu_entries_show_their_hotkeys_and_follow_the_tab(win):
    win._sync_view_menu_toggles()
    obverse, _act = win._view_menu_toggles["obverse"]
    assert obverse.text() == "View Obverse\tV"
    win._sync_modify_menu()
    copy_temple, _act = win._modify_menu_ops["copy_temple"]
    assert not copy_temple.isVisible()                # temples only
    win._sync_edit_menu()
    assert win._menu_move_gizmo.text() == "Move Gizmo\tM"


# ── Save and open ──────────────────────────────────────────────────────────

def test_the_save_question_names_the_design_and_the_action(win, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.Cancel)
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    win._mark_dirty()
    assert not win._confirm_discard("starting a new design")
    assert asked[0][1] == "Save Changes?"
    assert asked[0][2] == "Save the changes to this design before starting a new design?"


def test_a_canceled_save_says_nothing_was_saved(win, monkeypatch):
    """It said "Only the Frame Front was saved" after a canceled save."""
    told = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a))
    monkeypatch.setattr(win, "_save_as", lambda start=None: False)
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    win._mark_dirty()
    assert not win._confirm_discard()
    assert told == []


def test_an_unreadable_file_names_itself_and_its_backup(win, tmp_path, monkeypatch):
    bad = tmp_path / "frame.gdraw"
    bad.write_bytes(b"not a zip")
    (tmp_path / "frame.gdraw.bak").write_bytes(b"older")
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: told.append(a))
    assert win._open_gdraw(str(bad), remember=False) is None
    title, text = told[0][1], told[0][2]
    assert title == "Could Not Open the File"
    assert text.startswith("frame.gdraw could not be opened.")
    assert "frame.gdraw.bak" in text and "Technical detail:" in text


def test_new_returns_to_the_frame_front(win):
    win._ws_tab_widget.setCurrentIndex(2)
    win._new()
    assert win._ws_tab_widget.currentIndex() == 0


# ── Dialogs ────────────────────────────────────────────────────────────────

def test_the_text_dialog_waits_for_text(win):
    from PySide6.QtWidgets import QDialogButtonBox
    from framedraft.tools.text import TextDialog
    dlg = TextDialog(win)
    ok = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dlg._text_edit.setText("GUILD")
    assert ok.isEnabled()
    dlg.deleteLater()


def test_delete_questions_default_to_no(win, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.No)
    win._refresh_library_panel(select=("folder", "Hinges"))
    win._delete_library_entry()
    assert asked[-1][4] == QMessageBox.StandardButton.No


# ── The library ────────────────────────────────────────────────────────────

def test_saving_over_a_taken_name_asks_to_replace(win, monkeypatch):
    from framedraft.library import ComponentLibrary
    win._ws_tab_widget.setCurrentIndex(3)
    QApplication.processEvents()
    win._active_ws.add_curve(closed_diamond(0, 0, 3, layer=Layer.COMPONENT))
    monkeypatch.setattr(win, "_ask_library_save", lambda default: ("Saddle", "Bridges"))
    win._save_to_library()
    answers = iter(["replace", "keep", "cancel"])
    monkeypatch.setattr(win, "_ask_replace_entry", lambda name, folder: next(answers))
    for _ in range(3):
        win._save_to_library()
    names = sorted(e["name"] for g in ComponentLibrary().tree()
                   if g["folder"] == "Bridges" for e in g["entries"])
    assert names == ["Saddle", "Saddle_2"]           # replaced, kept, canceled


def test_library_rows_show_names_and_drag_only_on_the_component_tab(win):
    from PySide6.QtWidgets import QAbstractItemView
    tree = win._lib_tree
    hinges = tree.topLevelItem(0)
    assert hinges.text(0) == "Hinges"
    first = hinges.child(0)
    assert "·" not in first.text(0) and "Saved " in first.toolTip(0)
    assert tree.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
    win._ws_tab_widget.setCurrentIndex(3)
    QApplication.processEvents()
    assert tree.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove


# ── The Layers panel ───────────────────────────────────────────────────────

def test_layer_rows_name_groups_and_kinds(win):
    from framedraft.app import MainWindow
    a, b = circle(0, 0, 2, layer=Layer.COMPONENT), circle(9, 0, 2, layer=Layer.COMPONENT)
    a.group_id, b.group_id = "f00d", "beef"
    a.component_kind = "Hinges"
    assert MainWindow._curve_label(a, 1).startswith("Hinges 1  ·  circle")
    assert MainWindow._curve_label(b, 2).startswith("group 2  ·  circle")
    win._active_ws.add_curve(a)
    win._active_ws.add_curve(b)
    win._refresh_layer_panel()
    texts = [win._layer_tree_rows[id(c)].text(0) for c in (a, b)]
    assert texts[0].startswith("Hinges 1") and texts[1].startswith("group 2")
    assert not any("grp" in t for t in texts)


def test_the_component_tabs_dxf_note_says_it_is_for_the_library(win):
    win._ws_tab_widget.setCurrentIndex(3)
    QApplication.processEvents()
    win._active_ws.add_curve(closed_diamond(0, 0, 3, layer=Layer.COMPONENT))
    assert "GuildModel reads it only once it is placed" in win._readiness_note()


# ── Fills ──────────────────────────────────────────────────────────────────

def test_a_fill_pauses_with_its_box_ticked_and_says_why(win):
    """An outline opened mid-edit switched Frame Fill off for good, saying
    "the outline perimeter was broken"; it now waits for the outline."""
    ws = win._active_ws
    outline = closed_diamond(60, 0, 20, layer=Layer.OUTLINE)   # off the axis:
    ws.add_curve(outline)                                       # the Ghost
    ws.add_curve(circle(60, 0, 8))                              # cannot close it
    win._fill_show_chk.setChecked(True)
    assert ws.fill_visible and ws.scene._fill_item.isVisible()
    outline.closed = False
    ws.scene.refresh_curve(outline)
    ws.scene.rebuild_fill()
    assert win._fill_show_chk.isChecked() and ws.fill_visible
    assert "paused" in win._status.currentMessage()
    outline.closed = True
    ws.scene.refresh_curve(outline)
    ws.scene.rebuild_fill()
    assert ws.scene._fill_item.isVisible()
