"""Engraving text as a first-class object (v1.3): readable mirroring,
clipboard / duplicate, Transform, Temple Copy, drag-move, and Delete from
the Layers panel."""
import math

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from framedraft.document import Layer, TextObject
from framedraft.textpath import (mirror_text, normalize_rotation,
                                 text_bbox_center, text_outline_path)
from helpers import line


# ------------------------------------------------------------ mirror_text


def test_normalize_rotation_folds_into_half_turn():
    assert normalize_rotation(0.0) == 0.0
    assert normalize_rotation(180.0) == 180.0
    assert normalize_rotation(-180.0) == 180.0
    assert normalize_rotation(190.0) == -170.0
    assert normalize_rotation(530.0) == 170.0


def test_horizontal_mirror_keeps_the_footprint_and_flips_up():
    t = TextObject(text="GUILD", family="Arial", size_mm=5.0, rotation=180.0,
                   anchor_x=40.0, anchor_y=-6.0)
    m = mirror_text(t, 0.0, horizontal=True)
    # the right temple's brow-down engraving becomes brow-up on the left
    assert m.rotation == 0.0
    cx, cy = text_bbox_center(t)
    mx, my = text_bbox_center(m)
    assert math.isclose(mx, cx, abs_tol=1e-6)
    assert math.isclose(my, -cy, abs_tol=1e-6)
    # exactly the reflected footprint, not a reflected glyph
    src = text_outline_path(t).boundingRect()
    dst = text_outline_path(m).boundingRect()
    assert math.isclose(src.width(),  dst.width(),  abs_tol=1e-6)
    assert math.isclose(src.height(), dst.height(), abs_tol=1e-6)
    # untouched: the words, font, size, layer
    assert (m.text, m.family, m.size_mm, m.layer) == \
        (t.text, t.family, t.size_mm, t.layer)
    assert t.rotation == 180.0 and t.anchor_x == 40.0   # source untouched


def test_horizontal_mirror_is_an_involution():
    t = TextObject(text="Ab", family="Arial", size_mm=4.0, rotation=25.0,
                   anchor_x=12.0, anchor_y=3.0)
    back = mirror_text(mirror_text(t, horizontal=True), horizontal=True)
    assert math.isclose(back.rotation, 25.0, abs_tol=1e-9)
    assert math.isclose(back.anchor_x, 12.0, abs_tol=1e-6)
    assert math.isclose(back.anchor_y, 3.0, abs_tol=1e-6)


def test_vertical_mirror_negates_rotation_about_the_axis():
    t = TextObject(text="HE", family="Arial", size_mm=5.0, rotation=30.0,
                   anchor_x=10.0, anchor_y=0.0)
    m = mirror_text(t, axis_x=5.0, horizontal=False)
    assert m.rotation == -30.0
    cx, cy = text_bbox_center(t)
    mx, my = text_bbox_center(m)
    assert math.isclose(mx, 2 * 5.0 - cx, abs_tol=1e-6)
    assert math.isclose(my, cy, abs_tol=1e-6)


def test_empty_text_mirrors_without_error():
    m = mirror_text(TextObject(text="", family="Arial", size_mm=5.0,
                               anchor_x=3.0, anchor_y=4.0), horizontal=True)
    assert m.rotation == 180.0


# -------------------------------------------------------------------- app


@pytest.fixture(scope="module")
def win():
    from framedraft.app import MainWindow
    w = MainWindow()
    yield w
    w._dirty = False
    w.close()


@pytest.fixture()
def temple(win):
    """A fresh document on the Temple R tab with one engraving text."""
    win._dirty = False
    win._new()
    win._ws_tab_widget.setCurrentIndex(1)
    t = TextObject(text="RIGHT", family="Arial", size_mm=5.0, rotation=180.0,
                   anchor_x=30.0, anchor_y=-4.0)
    win._active_ws.add_text(t)
    return win, t


def _text_items(win):
    return list(win.scene._text_items.values())


def test_copy_paste_text(temple):
    win, t = temple
    win.scene.clearSelection()
    win.scene._text_items[id(t)].setSelected(True)
    win._copy_selected()
    assert "1 text" in win._status.currentMessage()
    win._paste()
    texts = win._active_ws.doc_texts
    assert len(texts) == 2 and texts[1] is not t
    new = texts[1]
    assert (new.text, new.rotation, new.size_mm) == ("RIGHT", 180.0, 5.0)
    assert math.isclose(new.anchor_x, 35.0) and math.isclose(new.anchor_y, 1.0)
    # the pasted copy is what's selected now
    sel = [it.text_obj for it in win.scene.selectedItems()
           if hasattr(it, "text_obj")]
    assert sel == [new]
    assert win._status.currentMessage().startswith("Pasted 1 text")
    # editing the copy leaves the original alone
    new.text = "LEFT"
    assert t.text == "RIGHT"


def test_duplicate_text_and_undo(temple):
    win, t = temple
    win.scene.clearSelection()
    win.scene._text_items[id(t)].setSelected(True)
    win._duplicate_selected()
    assert len(win._active_ws.doc_texts) == 2
    win._undo()
    assert win._active_ws.doc_texts == [t]


def test_paste_text_into_the_front_lands_on_ref(temple):
    win, t = temple
    win.scene.clearSelection()
    win.scene._text_items[id(t)].setSelected(True)
    win._copy_selected()
    win._ws_tab_widget.setCurrentIndex(0)
    win._paste()
    [pasted] = win._active_ws.doc_texts
    assert pasted.layer is Layer.REF
    assert "moved to REF" in win._status.currentMessage()


def test_copy_mixed_selection_reports_each_kind(temple):
    win, t = temple
    c = win._active_ws.add_curve(line([(0, 0), (50, 0)], layer=Layer.OUTLINE))
    win.scene.clearSelection()
    c.setSelected(True)
    win.scene._text_items[id(t)].setSelected(True)
    win._copy_selected()
    assert win._status.currentMessage() == "Copied 1 curve, 1 text"
    win._paste()
    assert len(win._active_ws.doc_curves) == 2
    assert len(win._active_ws.doc_texts) == 2


def test_temple_copy_carries_readable_text(temple, monkeypatch):
    import framedraft.app as app_mod
    win, t = temple
    win._active_ws.add_curve(line([(0, 0), (140, 0), (140, 8), (0, 8)],
                                  closed=True, layer=Layer.OUTLINE))
    monkeypatch.setattr(
        app_mod.QMessageBox, "question",
        staticmethod(lambda *a, **k: app_mod.QMessageBox.StandardButton.Yes))
    win._copy_temple_to_other()
    assert win._active_ws.workspace_type == "temple_l"
    [lt] = win._active_ws.doc_texts
    assert lt is not t and lt.text == "RIGHT"
    assert lt.rotation == 0.0                       # brow-down → brow-up
    cx, cy = text_bbox_center(t)
    lx, ly = text_bbox_center(lt)
    assert math.isclose(lx, cx, abs_tol=1e-6) and math.isclose(ly, -cy, abs_tol=1e-6)
    assert len(win._active_ws.doc_curves) == 1
    assert "1 curve, 1 text copied to Temple L" in win._status.currentMessage()
    # the text is on the canvas and in the layer panel
    assert id(lt) in win.scene._text_items
    assert id(lt) in win._layer_tree_text_rows
    # Ctrl+Z in Temple L puts the (empty) previous content back
    win._undo()
    assert win._active_ws.doc_texts == [] and win._active_ws.doc_curves == []


def test_temple_copy_confirms_when_target_holds_only_text(temple, monkeypatch):
    import framedraft.app as app_mod
    win, t = temple
    win._workspaces[2].add_text(TextObject(text="OLD", family="Arial",
                                           size_mm=4.0))
    seen = []

    def _q(_parent, _title, text, *a, **k):
        seen.append(text)
        return app_mod.QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(app_mod.QMessageBox, "question", staticmethod(_q))
    win._copy_temple_to_other()
    assert seen and "REPLACE" in seen[0]
    assert [x.text for x in win._workspaces[2].doc_texts] == ["OLD"]


def test_transform_scales_and_rotates_text(temple, monkeypatch):
    import framedraft.app as app_mod
    win, t = temple
    win.scene.clearSelection()
    win.scene._text_items[id(t)].setSelected(True)
    monkeypatch.setattr(app_mod.TransformDialog, "exec",
                        lambda self: app_mod.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(app_mod.TransformDialog, "values",
                        lambda self: (2.0, 2.0, 90.0, True))   # about the origin
    win._transform_selected()
    assert t.size_mm == 10.0
    # anchor (30, -4) scaled ×2 → (60, -8), then +90° counter-clockwise on
    # screen (scene y-down; the Text dialog's convention since the 2026-09-29
    # UI review — it used to turn clockwise) → (-8, -60)
    assert math.isclose(t.anchor_x, -8.0, abs_tol=1e-9)
    assert math.isclose(t.anchor_y, -60.0, abs_tol=1e-9)
    # the same counter-clockwise turn for the lettering: 180 → 270
    from framedraft.textpath import normalize_rotation
    assert t.rotation == normalize_rotation(270.0)
    assert win._status.currentMessage().startswith("Transformed 1 text")
    win._undo()
    assert t.size_mm == 5.0 or win._active_ws.doc_texts[0].size_mm == 5.0


def test_transform_non_uniform_leaves_text_size(temple, monkeypatch):
    import framedraft.app as app_mod
    win, t = temple
    win.scene.clearSelection()
    win.scene._text_items[id(t)].setSelected(True)
    monkeypatch.setattr(app_mod.TransformDialog, "exec",
                        lambda self: app_mod.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(app_mod.TransformDialog, "values",
                        lambda self: (2.0, 1.0, 0.0, True))
    win._transform_selected()
    assert t.size_mm == 5.0 and math.isclose(t.anchor_x, 60.0)
    assert "text size unchanged" in win._status.currentMessage()


def test_gizmo_move_carries_text_with_curves(temple):
    win, t = temple
    c = win._active_ws.add_curve(line([(0, 0), (50, 0)], layer=Layer.OUTLINE))
    win.scene.clearSelection()
    c.setSelected(True)
    win.scene._text_items[id(t)].setSelected(True)
    center = win._gizmo_center_from_selection()
    assert center is not None
    win.view._drag_move_items = []
    win._pre_move_selected()
    win._move_selected_by(3.0, -2.0)
    win._end_move_selected()
    assert math.isclose(t.anchor_x, 33.0) and math.isclose(t.anchor_y, -6.0)
    assert math.isclose(c.curve.nodes[0].x, 3.0)
    assert win.scene._text_items[id(t)].pos().x() == pytest.approx(33.0)


def test_text_only_selection_has_a_gizmo_center(temple):
    win, t = temple
    win.scene.clearSelection()
    win.scene._text_items[id(t)].setSelected(True)
    c = win._gizmo_center_from_selection()
    r = win.scene._text_items[id(t)].sceneBoundingRect()
    assert c is not None and math.isclose(c.x(), r.center().x(), abs_tol=1e-6)


def test_delete_key_in_layers_panel_removes_selected_rows(temple):
    win, t = temple
    c = win._active_ws.add_curve(line([(0, 0), (50, 0)], layer=Layer.OUTLINE))
    keep = win._active_ws.add_curve(line([(0, 20), (50, 20)], layer=Layer.REF))
    QApplication.processEvents()          # the panel rebuild is deferred
    tree = win._layer_tree
    tree.clearSelection()
    win._layer_tree_rows[id(c.curve)].setSelected(True)
    win._layer_tree_text_rows[id(t)].setSelected(True)
    # the panel pick is mirrored onto the canvas…
    assert {type(i).__name__ for i in win.scene.selectedItems()} == \
        {"CurveItem", "TextItem"}
    # …and Delete in the panel removes exactly those
    QTest.keyClick(tree, Qt.Key.Key_Delete)
    assert win._active_ws.doc_texts == []
    assert win._active_ws.doc_curves == [keep.curve]
    win._undo()
    assert len(win._active_ws.doc_curves) == 2
    assert len(win._active_ws.doc_texts) == 1


def test_delete_key_on_a_layer_row_does_nothing(temple):
    win, t = temple
    tree = win._layer_tree
    tree.clearSelection()
    win._layer_tree_layer_rows[Layer.ENGRAVING].setSelected(True)
    QTest.keyClick(tree, Qt.Key.Key_Delete)
    assert win._active_ws.doc_texts == [t]


def test_print_sees_a_text_only_workspace(temple):
    win, t = temple
    assert win._has_visible_geometry()
    win.scene.set_layer_visible(Layer.ENGRAVING, False)
    assert not win._has_visible_geometry()
    win.scene.set_layer_visible(Layer.ENGRAVING, True)
