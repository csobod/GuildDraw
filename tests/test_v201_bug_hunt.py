"""The 2.0.1 bug hunt: five read-only reviews of 2.0.0 (the main window in
two halves, the files, the canvas and tools, the geometry and validator).
Each test names the finding it pins. The font box's eaten keystrokes, the
round's first fix, are pinned in test_fontpicker.py."""
import copy
import gc
import json
import math
import os
import zipfile

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QKeyEvent, QKeySequence,
                           QMouseEvent, QShortcut)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import framedraft.export.gdraw as gdraw_mod
import framedraft.prefs as prefs_mod
from framedraft import geometry as G
from framedraft.canvas.items import CurveItem
from framedraft.document import Curve, Layer, SplineNode
from framedraft.export.validate import validate
from helpers import circle, closed_diamond, line, spline


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    gc.collect()


def _settings_with(win, **changes):
    """Preferences as its dialog would hand them back, with *changes*."""
    from framedraft.app import SettingsDialog
    current = {**win._prefs, "dark_mode": win._dark_mode,
               "default_line_weight": win._default_line_weight,
               "toolbar": dict(win._toolbar_prefs),
               "hotkeys": dict(win._hotkey_prefs)}
    dlg = SettingsDialog(current, win, images_in_use=win._images_in_use)
    p = dlg.to_prefs()
    dlg.deleteLater()
    p.update(changes)
    return p


# ── The main window ───────────────────────────────────────────────────────

def test_a_boxing_value_typed_before_snap_survives_unsnap_and_save(win):
    ws = win._active_ws
    ws.add_curve(circle(25, 0, 20))
    ws.add_curve(circle(-25, 0, 20))
    QApplication.processEvents()
    win._boxing_a_spin.setValue(57.0)
    win._boxing_b_spin.setValue(33.0)
    win._boxing_dbl_spin.setValue(19.5)
    win._boxing_snap_chk.setChecked(True)
    # A save while snapped writes the free box the maker typed, not the old one.
    win._save_ws_sidebar_state(ws)
    assert (ws.boxing_a, ws.boxing_b, ws.boxing_dbl) == (57.0, 33.0, 19.5)
    win._boxing_snap_chk.setChecked(False)
    assert win._boxing_a_spin.value() == 57.0
    assert win._boxing_b_spin.value() == 33.0
    assert win._boxing_dbl_spin.value() == 19.5


def test_clicking_through_the_scale_field_keeps_a_two_point_calibration(win, tmp_path):
    img = QImage(600, 400, QImage.Format.Format_RGB32)
    img.fill(QColor("#888"))
    path = str(tmp_path / "face.png")
    img.save(path)
    win._add_face(path)
    QApplication.processEvents()
    win._apply_calibration(3000 / 127.9, 0)       # a 2-point result
    exact = win.scene.face_calibration(0)
    win._dirty = False
    win._pxmm_spin.editingFinished.emit()         # a click in, then away
    assert win.scene.face_calibration(0) == exact
    assert not win._dirty


@pytest.mark.parametrize("key, value", [("stock_width_mm", 160.0),
                                        ("stock_height_mm", 80.0),
                                        ("pad_width_mm", 40.0)])
def test_a_guide_size_in_preferences_leaves_an_empty_design_unstarred(win, key, value):
    win._dirty = False
    win._apply_settings(_settings_with(win, **{key: value}))
    assert not win._dirty


def test_unlinking_a_lens_tint_never_brings_back_another_designs_color(win, tmp_path):
    ws = win._active_ws
    ws.add_curve(circle(25, 0, 20))
    ws.add_curve(circle(-25, 0, 20))
    win._set_lens_fill_color("top", "#00aa00")
    win._set_lens_fill_color("bottom", "#00aa00")
    win._lens_link_btn.setChecked(True)
    saved = str(tmp_path / "b.gdraw")
    assert win._do_save(saved)
    win._new()
    ws = win._active_ws
    ws.add_curve(circle(25, 0, 20))
    win._set_lens_fill_color("top", "#ff0000")
    win._set_lens_fill_color("bottom", "#0000ff")
    win._lens_link_btn.setChecked(True)            # sets blue aside
    win._dirty = False
    win._open_path(saved)
    ws = win._active_ws
    assert ws.lens_fill_linked
    win._lens_link_btn.setChecked(False)
    assert ws.lens_fill_bottom.lower() != "#0000ff"


def test_a_second_click_beside_a_selected_curve_keeps_it_selected(win):
    win.resize(1400, 900)
    win.show()
    QApplication.processEvents()
    ws = win._active_ws
    c = line([(-60, 0), (60, 0)], layer=Layer.OUTLINE)
    ws.add_curve(c)
    QApplication.processEvents()
    v = win.view
    v.resetTransform()
    v.scale(0.5, 0.5)                              # zoomed well out
    v.centerOn(0, 0)
    QApplication.processEvents()
    item = ws.scene._curve_items[id(c)]
    beside = v.mapFromScene(QPointF(0, 0)) + QPoint(0, 3)
    for _ in range(3):
        QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, beside)
        QApplication.processEvents()
        assert item.isSelected()


@pytest.mark.parametrize("seq", ["Ctrl+G", "Ctrl+Y"])
def test_group_and_redo_keys_stay_out_of_a_text_field(win, seq):
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    ws = win._active_ws
    a = closed_diamond(-30, 0, 10, layer=Layer.OUTLINE)
    b = closed_diamond(30, 0, 10, layer=Layer.OUTLINE)
    ws.add_curve(a)
    ws.add_curve(b)
    QApplication.processEvents()
    for c in (a, b):
        ws.scene._curve_items[id(c)].setSelected(True)
    if seq == "Ctrl+Y":
        win._group_selected()
        win._undo()                                # something to redo
    history = (len(ws.undo_stack), len(ws.redo_stack))
    win._side_tabs.setCurrentIndex(1)
    win._stock_w_spin.setFocus()
    QApplication.processEvents()
    # The window's own shortcut, fired directly: which keys a text field
    # takes for itself is the platform's choice (offscreen takes Windows',
    # where Ctrl+Y is the field's Redo; Linux and macOS leave it to us).
    hits = [sc for sc in win.findChildren(QShortcut)
            if sc.key() == QKeySequence(seq)]
    assert hits
    for sc in hits:
        sc.activated.emit()
    QApplication.processEvents()
    assert (len(ws.undo_stack), len(ws.redo_stack)) == history
    if seq == "Ctrl+G":
        assert a.group_id is None and b.group_id is None


def test_the_weight_box_follows_the_arriving_tabs_selection(win):
    ws = win._active_ws
    c = closed_diamond(0, 0, 20, layer=Layer.OUTLINE)
    c.line_weight = 4.0
    ws.add_curve(c)
    QApplication.processEvents()
    ws.scene._curve_items[id(c)].setSelected(True)
    QApplication.processEvents()
    assert win._weight_spin.isEnabled()
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    assert not win._weight_spin.isEnabled()
    assert win._weight_spin.value() == win._default_line_weight


# ── The canvas and tools ──────────────────────────────────────────────────
# Real QMouseEvents through the view's handlers, as test_v200_canvas does. A
# double-click is press, release, double-click, release: QTest.mouseDClick
# on the offscreen platform sends the double-click alone.

_L, _NONE = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
_NOMOD = Qt.KeyboardModifier.NoModifier


def _ev(view, kind, pt, buttons=None):
    vp = view.mapFromScene(pt)
    if buttons is None:
        buttons = _NONE if kind == QEvent.Type.MouseButtonRelease else _L
    button = _NONE if kind == QEvent.Type.MouseMove else _L
    return QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                       button, buttons, _NOMOD)


def _press(v, pt):
    v.mousePressEvent(_ev(v, QEvent.Type.MouseButtonPress, pt))


def _release(v, pt):
    v.mouseReleaseEvent(_ev(v, QEvent.Type.MouseButtonRelease, pt))


def _move(v, pt, buttons=_NONE):
    v.mouseMoveEvent(_ev(v, QEvent.Type.MouseMove, pt, buttons))


def _click(v, pt):
    _press(v, pt)
    _release(v, pt)


def _dbl(v, pt):
    """The whole double-click: press, release, double-click, release."""
    _click(v, pt)
    v.mouseDoubleClickEvent(_ev(v, QEvent.Type.MouseButtonDblClick, pt))
    _release(v, pt)


def _key(v, k, text=""):
    v.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, _NOMOD, text))


@pytest.fixture()
def shown(win):
    win.resize(1200, 800)
    win.show()
    QApplication.processEvents()
    win.view.fit_view(QRectF(-60, -60, 120, 120))
    QApplication.processEvents()
    return win


def test_a_locked_curve_on_top_does_not_take_the_click_from_its_neighbor(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    out = line([(-30, 0), (30, 0)], layer=Layer.OUTLINE)
    ref = line([(-30, 0.4), (30, 0.4)], layer=Layer.REF)    # drawn later: on top
    ws.add_curve(out)
    ws.add_curve(ref)
    w.scene.set_layer_locked(Layer.REF, True)
    _click(v, QPointF(10, 0))
    assert [i.curve for i in w.scene.selectedItems()
            if isinstance(i, CurveItem)] == [out]


def test_fillet_leaves_a_closed_polyline_alone(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    square = line([(0, 0), (20, 0), (20, 20), (0, 20)], layer=Layer.OUTLINE)
    square.closed = True
    leg = line([(0, 0), (-20, -10)], layer=Layer.OUTLINE)
    ws.add_curve(square)
    ws.add_curve(leg)
    w._act_fillet.trigger()
    _click(v, QPointF(10, 0))                     # the square's bottom side
    _click(v, QPointF(-10, -5))                   # the leg
    _key(v, Qt.Key.Key_2, "2")
    _key(v, Qt.Key.Key_Return)
    assert square in ws.doc_curves and square.closed
    assert len(square.nodes) == 4


def test_a_double_click_with_trim_trims_once(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    a = line([(-30, 0), (40, 0)])
    for c in (a, line([(20, -30), (20, 30)]), line([(-20, -30), (-20, 30)])):
        ws.add_curve(c)
    w._act_trim.trigger()
    p = QPointF(21.0, 0.0)                        # on the stub right of x=20
    _move(v, p)
    _dbl(v, p)
    horizontal = [c for c in ws.doc_curves
                  if c.kind == "line" and abs(c.nodes[0].y - c.nodes[-1].y) < 1e-9]
    assert len(horizontal) == 1
    ends = sorted(round(n.x, 3) for n in horizontal[0].nodes)
    assert ends == [-30.0, 20.0]                  # only the stub went
    assert len(ws.undo_stack) == 1


def test_an_open_end_beside_the_origin_snaps_to_the_end(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    ws.add_curve(line([(1.2, -0.8), (20, -15)], layer=Layer.OUTLINE))
    w._act_line.trigger()
    end = QPointF(1.2, -0.8)
    _move(v, end)
    _click(v, end)
    _move(v, QPointF(-20, -20))
    _click(v, QPointF(-20, -20))
    _key(v, Qt.Key.Key_Return)
    n0 = ws.doc_curves[-1].nodes[0]
    assert (n0.x, n0.y) == pytest.approx((1.2, -0.8))
    # The origin itself still snaps when it is the nearest target.
    w._act_line.trigger()
    _move(v, QPointF(0.05, 0.05))
    _click(v, QPointF(0.05, 0.05))
    _move(v, QPointF(-20, 20))
    _click(v, QPointF(-20, 20))
    _key(v, Qt.Key.Key_Return)
    n0 = ws.doc_curves[-1].nodes[0]
    assert (n0.x, n0.y) == pytest.approx((0.0, 0.0))


def test_rebuild_picked_in_the_tool_leaves_a_group_whole(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    a = spline([(-30, 0), (-20, 8), (-10, 2), (0, 9), (10, 1), (20, 7)],
               layer=Layer.COMPONENT)
    b = line([(-30, -10), (20, -10)], layer=Layer.COMPONENT)
    a.group_id = b.group_id = "g1"
    ws.add_curve(a)
    ws.add_curve(b)
    w.scene.clearSelection()
    w._act_rebuild.trigger()
    _click(v, QPointF(-30, 0))
    _key(v, Qt.Key.Key_3, "3")
    _key(v, Qt.Key.Key_Return)
    assert a in ws.doc_curves and len(a.nodes) == 6
    assert {c.group_id for c in ws.doc_curves} == {"g1"}
    assert "group" in w._status.currentMessage()


def test_a_double_click_on_an_arcs_end_places_no_center(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    w._act_arc_sec.trigger()
    s, e = QPointF(-20, 0), QPointF(20, 0)
    _move(v, s)
    _click(v, s)
    _move(v, e)
    _dbl(v, e)
    assert ws.doc_curves == []                    # still waiting for a center


def test_explode_refuses_a_group(win):
    ws = win._active_ws
    a = line([(0, 0), (10, 0), (10, 10)], layer=Layer.OUTLINE)
    b = line([(20, 0), (30, 0), (30, 10)], layer=Layer.OUTLINE)
    a.group_id = b.group_id = "g1"
    for c in (a, b):
        ws.add_curve(c)
    win.scene.select_items([win.scene._curve_items[id(a)]])
    win._explode_selected()
    assert ws.doc_curves == [a, b]
    assert "group" in win._status.currentMessage()


def test_mirror_close_keeps_a_group_member_in_its_group(win):
    ws = win._active_ws
    half = line([(0, -5), (-10, 0), (0, 5)], layer=Layer.OUTLINE)
    other = Curve(kind="circle", layer=Layer.REF, nodes=[SplineNode(-20, 0)],
                  radius=2, closed=True)
    half.group_id = other.group_id = "g1"
    for c in (half, other):
        ws.add_curve(c)
    win.scene.set_layer_visible(Layer.REF, False)
    win.scene.select_items([win.scene._curve_items[id(half)]])
    win._copy_across_mirror()
    closed = [c for c in ws.doc_curves if c.layer == Layer.OUTLINE]
    assert len(closed) == 1 and closed[0].closed
    assert closed[0].group_id == "g1"


@pytest.mark.parametrize("tool", ["trim", "split"])
def test_a_refused_group_edit_does_not_report_success(shown, tool):
    w, v, ws = shown, shown.view, shown._active_ws
    a = line([(-30, 0), (30, 0)])
    b = line([(0, -30), (0, 30)])
    a.group_id = b.group_id = "g1"
    for c in (a, b, line([(10, -30), (10, 30)])):
        ws.add_curve(c)
    (w._act_trim if tool == "trim" else w._act_split_curve).trigger()
    _click(v, QPointF(20, 0) if tool == "trim" else QPointF(-20, 0))
    assert len(ws.doc_curves) == 3
    assert "group" in w._status.currentMessage()


def test_a_tool_picked_mid_drag_leaves_no_node_dots_behind(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    a = line([(-30, 0), (0, 0), (10, 10)], layer=Layer.OUTLINE)
    ws.add_curve(a)
    _click(v, QPointF(-20, 0))
    _press(v, QPointF(-20, 0))
    _move(v, QPointF(-15, 3), buttons=_L)
    _move(v, QPointF(-10, 5), buttons=_L)
    w._act_line.trigger()                         # the L key, mid-drag
    _move(v, QPointF(-5, 8), buttons=_L)
    _release(v, QPointF(-5, 8))
    _key(v, Qt.Key.Key_Escape)
    assert not w.scene.selectedItems()
    assert not w._edit_tool._dots


def test_the_line_tool_places_no_zero_length_segment(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    w._act_line.trigger()
    _move(v, QPointF(0, 0))
    _click(v, QPointF(0, 0))
    _move(v, QPointF(-20, 0))                     # behind the typed angle
    _key(v, Qt.Key.Key_Tab)
    _key(v, Qt.Key.Key_0, "0")
    _key(v, Qt.Key.Key_Return)                    # refused: no length
    _move(v, QPointF(15, 0))
    _click(v, QPointF(15, 0))
    _click(v, QPointF(15, 0))                     # a slow second click
    _key(v, Qt.Key.Key_Return)
    pts = [(round(n.x, 4), round(n.y, 4)) for n in ws.doc_curves[-1].nodes]
    assert pts == [(0.0, 0.0), (15.0, 0.0)]


def test_deleting_a_node_of_a_closed_triangle_is_refused(shown):
    w, v, ws = shown, shown.view, shown._active_ws
    tri = line([(0, 0), (20, 0), (10, 15)], layer=Layer.OUTLINE)
    tri.closed = True
    ws.add_curve(tri)
    _click(v, QPointF(10, 0))                     # select the curve
    QApplication.processEvents()
    dot = next(d for d in w._edit_tool._dots if d.node_index == 1)
    w._edit_tool._on_node_clicked(dot)            # the node turns red
    w._delete_selected()
    assert tri in ws.doc_curves and len(tri.nodes) == 3
    assert ws.undo_stack == []


def test_a_file_dropped_on_the_drawing_opens(shown, tmp_path):
    """Drop-to-open (B29) reached the window from the toolbar and status
    bar only: the canvas took the drag and refused it."""
    import ezdxf
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (20, 10))
    path = str(tmp_path / "l.dxf")
    doc.saveas(path)
    target = shown.view.viewport()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    pos = target.rect().center()
    args = (Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, _NOMOD)
    for e in (QDragEnterEvent(pos, *args), QDragMoveEvent(pos, *args),
              QDropEvent(QPointF(pos), *args)):
        QApplication.sendEvent(target, e)
        assert e.isAccepted()
    for _ in range(3):
        QApplication.processEvents()
    assert len(shown._active_ws.doc_curves) == 1


# ── The files ─────────────────────────────────────────────────────────────


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    """A scratch image cache: opening a design with stored photos fills it."""
    monkeypatch.setattr(gdraw_mod, "_IMAGE_CACHE_ROOT", tmp_path / "imagecache")
    return tmp_path


def _photo(path, w, h, color="red"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    img.save(str(path))
    return str(path)


def test_an_uncalibrated_photo_keeps_its_size_on_reopen(win, cache):
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 30, Layer.OUTLINE))
    win._add_face(_photo(cache / "face.png", 1200, 800))
    win._add_face(_photo(cache / "detail.png", 400, 300, "blue"))
    win._apply_calibration(10.0, 0)                # photo 0 only
    before = ws.scene.get_face_item(1).sceneBoundingRect().size()
    for i in (0, 1):
        ws.scene.set_face_stored(i, True)
    path = str(cache / "cal.gdraw")
    assert win._do_save(path)
    assert win._open_gdraw(path, remember=False) == "ok"
    ws = win._active_ws
    assert ws.scene.face_calibration(0) == pytest.approx(10.0)
    assert ws.scene.face_calibration(1) is None
    after = ws.scene.get_face_item(1).sceneBoundingRect().size()
    assert (after.width(), after.height()) == pytest.approx(
        (before.width(), before.height()))


def test_a_temples_exported_svg_opens_into_its_own_tab(win, cache, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from framedraft.document import TextObject
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    ws = win._active_ws
    ws.add_curve(spline([(0, -4), (60, -3), (140, 0), (60, 3), (0, 4)],
                        closed=True, layer=Layer.OUTLINE))
    ws.add_text(TextObject("Logo", "DejaVu Sans", 2.5, anchor_x=20))
    out = str(cache / "temple.svg")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "SVG Files (*.svg)")))
    win._export_svg()
    win._new()
    win._open_path(out)
    front, temple = win._workspaces[0], win._workspaces[1]
    assert front.doc_curves == [] and front.doc_texts == []
    assert len(temple.doc_curves) == 1 and len(temple.doc_texts) == 1
    assert win._ws_tab_widget.currentIndex() == 1
    assert win._current_path is None              # Save asks; never the front


def test_a_first_batch_catalog_run_does_not_write_into_the_designs(tmp_path):
    from framedraft.batch_catalog_ui import BatchCatalogOptionsDialog
    last = dict(prefs_mod.load().get("batch_catalog", {}))
    dlg = BatchCatalogOptionsDialog(None, str(tmp_path), last)
    assert not dlg._save_chk.isChecked()
    assert dlg.options().save is False
    dlg.deleteLater()


def test_save_as_carries_a_photo_the_open_left_in_the_file(win, cache, monkeypatch):
    monkeypatch.setattr(gdraw_mod, "_MAX_PHOTOS_PER_TAB", 1)
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 30, Layer.OUTLINE))
    for i in range(2):
        win._add_face(_photo(cache / f"p{i}.png", 20, 20, ("red", "blue")[i]))
        ws.scene.set_face_stored(i, True)
    a = str(cache / "A.gdraw")
    assert win._do_save(a)
    images = lambda p: sorted(n for n in zipfile.ZipFile(p).namelist()
                              if n.startswith("images/"))
    assert len(images(a)) == 2
    assert win._open_gdraw(a, remember=False) == "ok"
    assert len(win._active_ws.unshown_faces) == 1  # left in the file
    b = str(cache / "B.gdraw")
    assert win._do_save(b)
    assert len(images(b)) == 2


def test_a_photo_beside_a_design_at_a_drive_root_is_found(monkeypatch):
    from framedraft.document import FaceImage
    from framedraft.export import svg as svg_mod
    real = os.path.isfile
    root_photo = os.path.join(os.path.abspath(os.sep), "photo.png")
    monkeypatch.setattr(os.path, "isfile", lambda p: p == root_photo or real(p))
    fis = [FaceImage(path="photo.png", stored=True)]
    svg_mod.resolve_face_images(fis, os.path.join(os.path.abspath(os.sep), "frame.svg"))
    assert fis[0].path == root_photo


def test_an_inkscape_svg_with_a_curves_layer_is_imported_not_opened(tmp_path):
    from framedraft.app import _is_guilddraw_svg
    p = tmp_path / "logo.svg"
    p.write_text(
        '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<metadata id="m5"><rdf:RDF/></metadata>'
        '<g inkscape:label="curves"><path d="M 0 0 L 40 0 Z"/></g></svg>')
    assert not _is_guilddraw_svg(str(p))


def test_a_guilddraw_svg_still_reads_as_a_design(win, tmp_path):
    from framedraft.app import _is_guilddraw_svg
    win._active_ws.add_curve(closed_diamond(0, 0, 20, Layer.OUTLINE))
    p = str(tmp_path / "front.svg")
    win._do_save_svg(p)
    assert _is_guilddraw_svg(p)


def test_batch_catalog_opacity_is_whole_percents():
    from framedraft.export.batch_catalog import BatchCatalogOptions
    opts = BatchCatalogOptions(opacity=0.855, inlay_opacity=0.333)
    assert (opts.opacity, opts.inlay_opacity) == (0.86, 0.33)


def test_an_upgrade_from_1_3_shows_mirror_close(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    toolbar = {k: v for k, v in prefs_mod.DEFAULTS["toolbar"].items()
               if k != "obverse"}                 # as 1.3.1 wrote it
    toolbar["mirror_close"] = False
    (tmp_path / "prefs.json").write_text(json.dumps({"toolbar": toolbar}))
    assert prefs_mod.load()["toolbar"]["mirror_close"] is True
    # Hidden in 2.0 (the toolbar has "obverse"), it stays hidden.
    toolbar["obverse"] = True
    (tmp_path / "prefs.json").write_text(json.dumps({"toolbar": toolbar}))
    assert prefs_mod.load()["toolbar"]["mirror_close"] is False


def test_a_files_apical_radius_survives_a_save_unless_edited(win):
    from framedraft.document import FormingMetadata
    ws = win._active_ws
    win._load_ws_data(ws, {"curves": [closed_diamond(0, 0, 20, Layer.OUTLINE)],
                           "forming": FormingMetadata(bridge_angle_deg=0.0,
                                                      apical_radius_mm=0.0)})
    win._restore_ws_sidebar_state(ws)
    win._save_ws_sidebar_state(ws)
    assert ws.apical_radius == 0.0
    win._apical_spin.setValue(9.0)                 # the maker's edit
    win._save_ws_sidebar_state(ws)
    assert ws.apical_radius == 9.0


def test_a_utf16_svg_declaring_entities_is_refused(tmp_path):
    from framedraft.export.svg import load_svg
    doc = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE svg '
           '[<!ENTITY e "x">]><svg xmlns="http://www.w3.org/2000/svg">'
           '<metadata>{"curves": [], "n": "&e;"}</metadata></svg>')
    p = tmp_path / "ent16.svg"
    p.write_bytes(doc.encode("utf-16"))
    with pytest.raises(ValueError, match="(?i)doctype|entit"):
        load_svg(str(p))


# Two left by the hunt (BUILDPLAN 2.0.1, Not done), done after it: a design
# opened on a computer that lacks one of its images changed when saved there.

def test_an_image_fill_whose_file_did_not_travel_is_saved_as_image(win, tmp_path):
    from framedraft.export.batch_catalog import fill_record, inlay_record
    ws = win._active_ws
    gone = str(tmp_path / "gone.png")
    win._load_ws_data(ws, {"fill": {"style": "image", "image": gone},
                           "inlay_fill": {"style": "image", "image": gone}})
    win._restore_ws_sidebar_state(ws)
    # The canvas and the combo show the color; the file keeps Image.
    assert ws.fill_style == "color" and ws.inlay_fill_style == "color"
    assert win._fill_style_combo.currentData() == "color"
    data = win._ws_to_data_dict(ws)
    assert data["fill"]["style"] == "image"
    assert data["inlay_fill"]["style"] == "image"
    assert fill_record(ws)["style"] == inlay_record(ws)["style"] == "image"
    # Clearing it is the way to keep the color.
    assert win._fill_image_clear_btn.isEnabled()
    assert "Not found on this computer" in win._fill_image_btn.toolTip()
    win._on_fill_image_cleared()
    assert win._ws_to_data_dict(ws)["fill"]["style"] == "color"


def test_an_image_not_found_keeps_its_place_in_the_stack(win, tmp_path):
    from framedraft.export.svg import load_svg
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 30, Layer.OUTLINE))
    names = ["under.png", "middle.png", "over.png"]
    for i, name in enumerate(names):
        win._add_face(_photo(tmp_path / name, 20, 20, ("red", "green", "blue")[i]))
        ws.scene.set_face_stored(i, True)
    first = str(tmp_path / "A.svg")
    win._do_save_svg(first)
    os.remove(tmp_path / "middle.png")             # not on this computer
    win._open_path(first)
    ws = win._active_ws
    assert ws.scene.face_count() == 2 and len(ws.unshown_faces) == 1
    second = str(tmp_path / "B.svg")
    win._do_save_svg(second)
    assert [os.path.basename(fi.path)
            for fi in load_svg(second)["face_images"]] == names


def test_restacking_follows_the_file_past_a_removed_or_added_image():
    from framedraft.app import _restack_faces
    from framedraft.document import FaceImage
    a, b, c = (FaceImage(path=p, order=k) for k, p in enumerate("abc"))
    new = FaceImage(path="new")
    paths = lambda faces: [f.path for f in faces]
    assert paths(_restack_faces([a, c], [b])) == ["a", "b", "c"]
    assert paths(_restack_faces([c], [b])) == ["b", "c"]         # a removed
    assert paths(_restack_faces([a, c, new], [b])) == ["a", "b", "c", "new"]
    assert paths(_restack_faces([a], [b, c])) == ["a", "b", "c"]


# The maker's call on the last item the hunt left: 1:1 Print and PDF follow
# View Obverse, as PNG export does.

class _Sheet(QImage):
    """A page for a 1:1 print, 4 px a millimeter."""

    def pageRect(self, _unit):
        return QRectF(0, 0, self.width(), self.height())

    def outputFileName(self):
        return ""

    def printerName(self):
        return "sheet"


def test_the_1to1_render_turns_the_drawing_with_view_obverse(win):
    win._set_ghost(win._active_ws, False)          # its twin would balance it
    win._active_ws.add_curve(line([(-40, -10), (-20, 10)], layer=Layer.OUTLINE))
    white = QColor("white")
    mean_x = {}
    for mirrored in (False, True):
        sheet = _Sheet(1200, 800, QImage.Format.Format_ARGB32)
        sheet.setDotsPerMeterX(4000)
        sheet.setDotsPerMeterY(4000)
        sheet.fill(white)
        win._render_1to1(sheet, QRectF(-100, -50, 200, 100), mirrored=mirrored)
        ink = [x for y in range(300, 500, 5) for x in range(0, 1200, 2)
               if sheet.pixelColor(x, y) != white]       # the ruler is lower
        mean_x[mirrored] = sum(ink) / len(ink)
    # 200 mm framed on 300 mm of paper: the line at 60–80 mm, or 120–140.
    assert mean_x[False] == pytest.approx(480, abs=8)
    assert mean_x[True] == pytest.approx(720, abs=8)


def test_a_1to1_pdf_follows_view_obverse_and_says_so(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win._active_ws.add_curve(line([(-40, -10), (-20, 10)], layer=Layer.OUTLINE))
    asked = []
    monkeypatch.setattr(win, "_render_1to1",
                        lambda printer, source, mirrored=False: asked.append(mirrored))
    out = str(tmp_path / "view.pdf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "PDF Files (*.pdf)")))
    win._export_pdf_1to1()
    win._act_obverse.setChecked(True)
    win._export_pdf_1to1()
    assert asked == [False, True]
    assert "the posterior, as View Obverse shows it" in win._status.currentMessage()


def test_a_rename_by_case_alone_passes_on_a_disk_that_ignores_case(tmp_path, monkeypatch):
    # Fixed in the hunt by reading only (library.rename_entry, samefile);
    # here a disk that folds case, as macOS's does, stands in for a Mac.
    import pathlib

    from framedraft.library import ComponentLibrary
    lib = ComponentLibrary()
    old = tmp_path / "zoye th-22.svg"
    old.write_text("<svg/>")
    (tmp_path / "Other.svg").write_text("<svg/>")
    folded = lambda p: str(p).casefold()
    real_exists = pathlib.Path.exists
    monkeypatch.setattr(pathlib.Path, "exists", lambda self, *a, **k: (
        real_exists(self, *a, **k)
        or any(folded(q) == folded(self) for q in self.parent.glob("*"))))
    monkeypatch.setattr(pathlib.Path, "samefile",
                        lambda self, other: folded(self) == folded(other))
    new = lib.rename_entry(str(old), "Zoye TH-22")
    assert pathlib.Path(new).name == "Zoye TH-22.svg"
    with pytest.raises(ValueError):
        lib.rename_entry(new, "other")             # another file, in any case


# ── The main window, second half ──────────────────────────────────────────

def test_an_import_onto_a_hidden_layer_says_so(win, tmp_path, monkeypatch):
    import ezdxf
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (20, 10))
    path = str(tmp_path / "l.dxf")
    doc.saveas(path)
    ws = win._active_ws
    win.scene.set_layer_visible(ws.active_layer, False)
    win._import_dxf(path)
    assert "hidden" in win._status.currentMessage()


def test_png_export_of_a_photo_only_tab_says_nothing_is_empty(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    told = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: told.append(a)))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    win._add_face(_photo(tmp_path / "face.png", 300, 200))
    win._export_png()
    assert told == []


def test_ungroup_frees_members_on_a_hidden_layer_too(win):
    ws = win._active_ws
    out = closed_diamond(0, 0, 20, Layer.OUTLINE)
    ref = line([(-30, 0), (30, 0)], layer=Layer.REF)
    out.group_id = ref.group_id = "g1"
    ws.add_curve(out)
    ws.add_curve(ref)
    win.scene.set_layer_visible(Layer.REF, False)
    win.scene.select_items([win.scene._curve_items[id(out)]])
    win._ungroup_selected()
    assert out.group_id is None and ref.group_id is None


def test_a_recent_file_with_an_ampersand_keeps_it(win, tmp_path):
    p = tmp_path / "R&D 49.gdraw"
    p.write_bytes(b"")
    win._add_recent(str(p))
    texts = [a.text() for a in win._recent_menu.actions()]
    assert "R&&D 49.gdraw" in texts


# ── Geometry and the validator ────────────────────────────────────────────


def _rim(cx, r, closed=True):
    return spline([(cx - r, 0), (cx, -r * 0.7), (cx + r, 0), (cx, r * 0.7)],
                  closed=closed, layer=Layer.OUTLINE)


def test_a_rim_with_no_lens_is_not_green():
    errors, _ = validate([_rim(35, 25), _rim(-36, 26),
                          circle(35, 0, 12, Layer.LENS)], False, "front")
    assert any("no lens" in e for e in errors)


@pytest.mark.parametrize("side", [-1, 1])
def test_an_empty_rim_the_same_size_is_not_green_on_either_side(side):
    # Two rims alike: the one without its lens was a stray when it came
    # second, and the front read green with a warning (and GuildModel built
    # a monocle). Found running GuildModel's intake after the hunt.
    errors, _ = validate([_rim(-35, 25), _rim(35, 25),
                          circle(side * 35, 0, 12, Layer.LENS)], False, "front")
    assert any("no lens" in e for e in errors)


def test_two_lenses_on_one_eye_are_not_green():
    errors, _ = validate([closed_diamond(0, 0, 40, Layer.OUTLINE),
                          circle(20, 0, 12, Layer.LENS),
                          circle(22, 0, 11, Layer.LENS)], False, "front")
    assert any("one eye" in e for e in errors)


@pytest.mark.parametrize("curves", [
    [closed_diamond(0, 0, 40, Layer.OUTLINE), circle(20, 0, 12, Layer.LENS),
     circle(-20, 0, 12, Layer.LENS)],
    [closed_diamond(0, 0, 40, Layer.OUTLINE), circle(20, 0, 12, Layer.LENS),
     circle(-17, 3, 9, Layer.LENS)],                      # not mirror images
    [_rim(35, 25), _rim(-35, 25), circle(35, 0, 12, Layer.LENS),
     circle(-35, 0, 12, Layer.LENS)],                     # separated rims
    [_rim(35, 25), circle(35, 0, 12, Layer.LENS)],        # a monocle
], ids=["pair", "uneven pair", "separated rims", "monocle"])
def test_ordinary_fronts_stay_green(curves):
    assert validate(curves, False, "front")[0] == []


def test_a_rim_drawn_open_but_closed_is_checked_against_the_ghost():
    rim = _rim(35, 25, closed=False)
    first = rim.nodes[0]
    rim.nodes.append(SplineNode(x=first.x + 0.05, y=first.y,
                                cp_in=copy.deepcopy(rim.nodes[-1].cp_out)))
    errors, _ = validate([rim, circle(35, 0, 12, Layer.LENS)], True, "front")
    assert any("Ghost's only" in e for e in errors)


def test_offsetting_a_polyline_with_a_repeated_node_moves_every_corner():
    rect = line([(0, 0), (10, 0), (10, 0), (10, 10), (0, 10)], layer=Layer.OUTLINE)
    rect.closed = True
    out = G.offset_curve(rect, 1.0)
    pts = {(round(n.x, 6), round(n.y, 6)) for n in out.nodes}
    assert pts == {(-1, -1), (11, -1), (11, 11), (-1, 11)}


# The offset that crossed itself at corners (BUILDPLAN 2.0.1, not done in
# the hunt, done after it): the pieces of two sides were joined end to end,
# never trimmed where they overlap.

def _cornered(pts, closed=True, layer=Layer.COMPONENT):
    """A spline with no handles: every node a corner."""
    return Curve(kind="spline", layer=layer, closed=closed,
                 nodes=[SplineNode(x=x, y=y) for x, y in pts])


def _crosses_itself(c) -> bool:
    """The readiness dot's test for a closed curve (validate._shape_checks);
    shapely's for an open one."""
    from shapely.geometry import LineString, Polygon
    pts = G.flatten_curve(c, 0.02)
    return not (Polygon(pts).is_valid if c.closed else LineString(pts).is_simple)


def _area(c) -> float:
    from shapely.geometry import Polygon
    return Polygon(G.flatten_curve(c, 0.01)).area


def test_an_inward_offset_of_a_cornered_spline_does_not_cross_itself():
    out = G.offset_curve(_cornered([(0, 0), (10, 0), (10, 6), (0, 6)]), -0.5)
    assert not _crosses_itself(out)
    pts = sorted((n.x, n.y) for n in out.nodes)
    assert pts == pytest.approx([(0.5, 0.5), (0.5, 5.5), (9.5, 0.5), (9.5, 5.5)],
                                abs=1e-9)


def test_an_outward_offset_of_a_cornered_spline_keeps_its_bevels():
    out = G.offset_curve(_cornered([(0, 0), (10, 0), (10, 6), (0, 6)]), 0.5)
    assert len(out.nodes) == 8 and not _crosses_itself(out)


@pytest.mark.parametrize("start", range(4))
def test_an_offset_near_collapse_keeps_what_is_left(start):
    # 2.9 mm into a 6 mm wide shape: the corner loops outsize what is left.
    pts = [(0, 0), (10, 0), (10, 6), (0, 6)]
    out = G.offset_curve(_cornered(pts[start:] + pts[:start]), -2.9)
    assert not _crosses_itself(out)
    assert _area(out) == pytest.approx(4.2 * 0.2, abs=1e-6)


@pytest.mark.parametrize("start", range(6))
def test_an_outward_offset_cuts_its_inside_corner_wherever_the_seam_is(start):
    pts = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
    out = G.offset_curve(_cornered(pts[start:] + pts[:start], layer=Layer.OUTLINE), 1.0)
    assert not _crosses_itself(out)
    # 75 + the perimeter's 40 + five bevels' 0.5, less the 1 the inside
    # corner's two strips share.
    assert _area(out) == pytest.approx(116.5, abs=1e-6)


def test_an_open_offset_trims_its_inside_corner_only():
    src = _cornered([(0, 0), (10, 0), (10, 10)], closed=False)
    inside = G.offset_curve(src, 1.0)
    assert [(n.x, n.y) for n in inside.nodes] == pytest.approx(
        [(0, 1), (9, 1), (9, 10)], abs=1e-9)
    assert len(G.offset_curve(src, -1.0).nodes) == 4     # the bevel stays


def test_an_offset_of_a_curve_that_crosses_itself_is_left_as_it_was():
    bow = _cornered([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert len(G.offset_curve(bow, -0.5).nodes) == 8


def test_every_shipped_hinge_pocket_offsets_inward_without_crossing_itself():
    from pathlib import Path

    from framedraft.export.svg import load_svg
    root = Path(G.__file__).parent / "resources" / "library" / "components"
    pockets = [c for p in sorted(root.rglob("*.svg"))
               for c in load_svg(str(p))["curves"] if c.kind == "spline" and c.closed]
    assert pockets
    for c in pockets:
        out = G.offset_curve(c, -0.3)
        assert not _crosses_itself(out)
        assert _area(out) < _area(c)


def test_a_hairpin_left_where_a_loop_lost_its_crossing_is_cut():
    # Past a bend tighter than the offset distance the approximation, held
    # to 0.02 mm, can miss the loop's crossing and leave a spike a hair wide
    # (two library outlines at ±1 mm): here 0.035 mm long, 0.0015 mm wide.
    src = _cornered([(0, 0), (10, 0), (10, 6), (0, 6)])
    off = _cornered([(0, 0), (10, 0), (10, 6), (5, 6), (5.035, 5.9985), (0, 6)])
    out = G._untangle_offset(src, off, -1.0)
    assert len(out.nodes) == 5 and not _crosses_itself(out)


# The offset that froze the window (the maker, 2026-10-29): −10 mm on an open
# outline ran for minutes on the GUI thread. A far offset loops at every bend;
# the loop search weighed each crossing against all the others, and the refit
# measured its points one by one in Python. Out of range now says so.

def _zigzag(n=40):
    """An open spline bending every 2 mm: 5 mm off it, a loop at each bend."""
    return spline([(i * 2.0, 1.5 * (1 if i % 2 else -1)) for i in range(n)])


@pytest.mark.parametrize("kind", ["spline", "line"])
def test_an_inward_offset_past_the_width_is_out_of_range(kind):
    pts = [(0, 0), (10, 0), (10, 6), (0, 6)]
    shape = _cornered(pts) if kind == "spline" else line(pts, closed=True)
    with pytest.raises(G.OffsetOutOfRange, match="nothing of the shape"):
        G.offset_curve(shape, -3.5)
    assert not _crosses_itself(G.offset_curve(shape, -2.9))   # a sliver is kept


def test_a_lens_shrunk_past_its_width_is_out_of_range():
    with pytest.raises(G.OffsetOutOfRange, match="nothing of the shape"):
        G.offset_curve(closed_diamond(0, 0, 20, Layer.LENS), -25.0)


def test_an_offset_folding_over_itself_too_often_is_out_of_range():
    with pytest.raises(G.OffsetOutOfRange, match="folds over itself"):
        G.offset_curve(_zigzag(), 5.0)
    assert len(G.offset_curve(_zigzag(16), 5.0).nodes) > 2   # fewer folds: cut


@pytest.mark.parametrize("budget", ["_LOOP_MAX_CUTS", "_LOOP_MAX_WORK"])
def test_a_loop_search_out_of_budget_hands_back_no_tangled_curve(budget, monkeypatch):
    # Out of passes, the search returned the offset as it was, crossings and
    # all: 18 s of work for a curve of no use.
    monkeypatch.setattr(G, budget, 2)
    with pytest.raises(G.OffsetOutOfRange):
        G.offset_curve(_cornered([(0, 0), (10, 0), (10, 6), (0, 6)]), -0.5)


def test_a_source_that_crosses_itself_is_not_judged_by_its_width():
    bow = _cornered([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert len(G.offset_curve(bow, -6.0).nodes) == 8


def _offset_tool(src):
    from PySide6.QtWidgets import QGraphicsView

    from framedraft.canvas.scene import FrameScene
    from framedraft.tools.offset import OffsetTool
    scene = FrameScene()
    tool = OffsetTool()
    tool._test_view = QGraphicsView(scene)
    msgs, added = [], []
    tool.status_message.connect(msgs.append)
    tool.offset_applied.connect(lambda s, c: added.append(c))
    tool.activate(scene, tool._test_view, src)
    return tool, msgs, added


def _type(tool, s):
    for ch in s:
        tool.handle_key(0, ch)


def test_the_offset_tool_says_out_of_range_and_adds_nothing():
    tool, msgs, added = _offset_tool(_cornered([(0, 0), (10, 0), (10, 6), (0, 6)]))
    _type(tool, "-5")
    tool._update_preview()                       # the pause in the typing
    assert tool._preview_item is None
    assert tool._hud.text().endswith("out of range")
    assert "out of range" in msgs[-1] and "nothing of the shape" in msgs[-1]
    tool.handle_key(Qt.Key.Key_Return)
    assert added == [] and "out of range" in msgs[-1]
    tool.handle_key(Qt.Key.Key_Backspace)
    _type(tool, "1")
    tool._update_preview()
    assert tool._preview_item is not None
    assert "out of range" not in tool._hud.text() and "press Enter" in msgs[-1]


def test_the_offset_preview_waits_for_the_typing_and_enter_adds_what_it_showed(monkeypatch):
    calls = []
    real = G.offset_curve
    monkeypatch.setattr(G, "offset_curve", lambda c, d: calls.append(d) or real(c, d))
    tool, _msgs, added = _offset_tool(_cornered([(0, 0), (10, 0), (10, 6), (0, 6)]))
    _type(tool, "-1.5")
    assert calls == [] and tool._preview_timer.isActive()
    tool._update_preview()
    assert calls == [-1.5]
    tool.handle_key(Qt.Key.Key_Return)
    assert calls == [-1.5] and len(added) == 1
    assert added[0] is not tool._result[0]       # the preview's own is not reused


def test_split_at_a_node_leaves_no_hidden_duplicate():
    pts = [(0, 0), (13, 4), (21, -3), (37, 8), (44, 1), (60, 0), (71, 9)]
    s = spline(pts)
    for k in range(1, len(pts) - 1):
        t = G.t_nearest(s, s.nodes[k].x, s.nodes[k].y)
        left, right = G.split_curve_at_t(s, t)
        assert len(left.nodes) + len(right.nodes) == len(pts) + 1
        for piece in (left, right):
            gaps = [math.hypot(a.x - b.x, a.y - b.y)
                    for a, b in zip(piece.nodes, piece.nodes[1:], strict=False)]
            assert min(gaps) > 1e-3


def test_an_opening_the_canvas_does_not_ghost_asks_for_no_bake():
    hole = spline([(0.6, -8), (4, -5), (0.6, -2), (0.4, -5)], closed=True,
                  layer=Layer.OUTLINE)
    front = [closed_diamond(0, 0, 40, Layer.OUTLINE), hole,
             circle(20, 0, 10, Layer.LENS), circle(-20, 0, 10, Layer.LENS)]
    assert validate(front, True, "front")[0] == []


def test_a_polygon_lens_measures_to_its_corners():
    from framedraft.boxing import lens_bbox
    pts = [(25 * math.cos(math.radians(90 + 72 * i)),
            25 * math.sin(math.radians(90 + 72 * i))) for i in range(5)]
    lens = line(pts, layer=Layer.LENS)
    lens.closed = True
    x0, y0, x1, y1 = lens_bbox(lens)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert x1 - x0 == pytest.approx(max(xs) - min(xs), abs=1e-6)    # A
    assert y1 - y0 == pytest.approx(max(ys) - min(ys), abs=1e-6)    # B
