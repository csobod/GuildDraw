"""The 2.0 bug hunt's GuildDraw findings (HANDOFF-GuildDraw-2026-10-16):
each test names the finding it pins. The validator's own rules are in
test_validate.py; these are the app's paths."""
import gc
import os

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.canvas.items import CurveItem
from framedraft.document import Layer
from helpers import circle, closed_diamond, line


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
    # Collect the window's reference cycles now, while Qt is consistent:
    # left to pytest's last collection, removed curve items and their node
    # dots from these undo-and-reselect tests were freed in an order that
    # crashed the process at exit. The app itself exits cleanly.
    gc.collect()


def _select(win, layers=None):
    win.scene.clearSelection()
    for it in win.scene.items():
        if isinstance(it, CurveItem) and (layers is None or it.curve.layer in layers):
            it.setSelected(True)


# ── 2. Mirror (bake) never lays a twin on a curve ──────────────────────────

def test_select_all_then_mirror_bakes_only_the_lens(win):
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 45, layer=Layer.OUTLINE))
    ws.add_curve(circle(-17, 0, 11, layer=Layer.LENS))
    _select(win)
    win._on_duplicate_mirror()
    outlines = [c for c in ws.doc_curves if c.layer == Layer.OUTLINE]
    lenses = [c for c in ws.doc_curves if c.layer == Layer.LENS]
    assert len(outlines) == 1 and len(lenses) == 2
    assert "1 skipped" in win._status.currentMessage()
    win._update_readiness()
    assert win._readiness_dot.state() == "green"


def test_mirror_on_a_baked_front_adds_nothing_and_no_undo_step(win):
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 45, layer=Layer.OUTLINE),
              circle(-17, 0, 11, layer=Layer.LENS),
              circle(17, 0, 11, layer=Layer.LENS)):
        ws.add_curve(c)
    undo_depth = len(win._undo_stack)
    _select(win)
    win._on_duplicate_mirror()
    assert len(ws.doc_curves) == 3
    assert len(win._undo_stack) == undo_depth
    assert win._act_mirror.isChecked()          # nothing baked, Ghost untouched
    assert "nothing to bake" in win._status.currentMessage()


def test_an_open_half_reaching_the_axis_is_still_baked(win):
    ws = win._active_ws
    ws.add_curve(line([(0, -20), (-30, -10), (-30, 10), (0, 20)],
                      layer=Layer.OUTLINE))
    _select(win)
    win._on_duplicate_mirror()
    assert len([c for c in ws.doc_curves if c.layer == Layer.OUTLINE]) == 2


# ── 4. Nothing of the last document leaks into the next ───────────────────

def _front(*extra):
    return {"curves": [closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
                       circle(-15, 0, 10), circle(15, 0, 10), *extra]}


def test_the_photo_calibration_does_not_leak_into_the_next_file(win, tmp_path):
    from framedraft.document import Calibration
    from framedraft.export.gdraw import load_gdraw, save_gdraw
    a, b = str(tmp_path / "a.gdraw"), str(tmp_path / "b.gdraw")
    save_gdraw({"front": {**_front(), "calibration": Calibration(px_per_mm=4.0)}}, a)
    save_gdraw({"front": _front()}, b)
    win._open_gdraw(a, remember=False)
    assert win._workspaces[0].image_px_per_mm == 4.0
    win._open_gdraw(b, remember=False)
    assert win._workspaces[0].image_px_per_mm is None
    win._do_save_gdraw(b)
    assert not load_gdraw(b)["front"]["calibration"].is_set


def test_new_starts_the_ghost_and_the_guides_from_preferences(win):
    win._act_mirror.setChecked(False)
    win._stock_w_spin.setValue(190.0)
    win._pad_h_spin.setValue(60.0)
    temple = win._workspaces[1]
    temple.stock_w = 120.0
    win._dirty = False
    win._new()
    front = win._workspaces[0]
    assert win._act_mirror.isChecked() and front.mirror_enabled
    assert (front.stock_w, front.pad_h) == (170.0, 45.0)
    assert win._stock_w_spin.value() == 170.0 and front.stock_guide.width_mm == 170.0
    assert temple.stock_w == 170.0 and temple.stock_h == 30.0


# ── 5. A file that fails halfway leaves nothing behind ─────────────────────

def test_a_file_that_fails_while_filling_leaves_an_empty_pathless_document(
        win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from framedraft.export.gdraw import save_gdraw
    good, bad = str(tmp_path / "good.gdraw"), str(tmp_path / "bad.gdraw")
    arm = {"curves": [closed_diamond(60, 0, 30, layer=Layer.OUTLINE)]}
    save_gdraw({"front": _front(), "temple_r": arm}, good)
    save_gdraw({"front": _front(), "temple_r": arm}, bad)
    assert win._open_gdraw(good, remember=False) == "ok"

    real, calls = win._load_ws_data, []

    def fails_on_the_second(ws, data):
        calls.append(ws)
        if len(calls) == 2:
            raise ValueError("a value the reader let through")
        real(ws, data)

    monkeypatch.setattr(win, "_load_ws_data", fails_on_the_second)
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: told.append(a))
    assert win._open_gdraw(bad, remember=False) is None
    assert told
    assert win._current_path is None                  # Ctrl+S asks for a name
    assert all(not ws.doc_curves for ws in win._workspaces)


def _svg_with(state: dict) -> str:
    import json
    return ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">'
            f'<metadata>{json.dumps(state)}</metadata></svg>')


def test_load_svg_checks_what_the_file_says(tmp_path):
    from framedraft.export.svg import load_svg
    p = tmp_path / "t.svg"
    p.write_text(_svg_with({"layers": {"OUTLINE": True, "LENS": {"visible": 0}},
                            "fill": [1, 2], "face_images": [{"path": 3}],
                            "calibration": {"px_per_mm": "x"}}))
    data = load_svg(str(p))
    assert data["layers"] == {"LENS": {"visible": False}}
    assert data["fill"] is None and data["face_images"] == []
    assert not data["calibration"].is_set
    # A curve that does not read is left out and said, not the whole tab
    # (the 2.0 bug hunt, second round).
    good = {"kind": "line", "layer": "OUTLINE",
            "nodes": [{"x": 0, "y": 0}, {"x": 5, "y": 0}]}
    p.write_text(_svg_with({"curves": [{"kind": "line", "layer": "OUTLINE",
                                        "nodes": [{"x": "a", "y": 0}]},
                                       dict(good, layer="SOMEDAY"), good]}))
    data = load_svg(str(p))
    assert len(data["curves"]) == 1
    [said] = data["left_out"]
    assert said.startswith("2 curves (the first: a node x is not a number")


def test_a_layer_flag_of_true_no_longer_stops_the_open(win, tmp_path):
    import json
    import zipfile
    state = {"layers": {"OUTLINE": True},
             "curves": [{"kind": "circle", "layer": "LENS", "closed": True,
                         "radius": 9.0, "nodes": [{"x": 0, "y": 0}]}]}
    path = tmp_path / "flag.gdraw"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"version": 1}))
        zf.writestr("front.svg", _svg_with(state))
    assert win._open_gdraw(str(path), remember=False) == "ok"
    assert len(win._workspaces[0].doc_curves) == 1


# ── 6. A photo keeps its name through any number of saves ──────────────────

@pytest.fixture()
def cache_root(tmp_path, monkeypatch):
    import framedraft.export.gdraw as gdraw_mod
    root = tmp_path / "imagecache"
    monkeypatch.setattr(gdraw_mod, "_IMAGE_CACHE_ROOT", root)
    return root


def _png(path):
    from PySide6.QtGui import QImage
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    assert img.save(str(path))
    return str(path)


def test_a_photo_keeps_its_name_through_save_and_open_cycles(tmp_path, cache_root):
    import os
    import zipfile
    from framedraft.document import FaceImage
    from framedraft.export.gdraw import load_gdraw, save_gdraw
    path = str(tmp_path / "d.gdraw")
    face = FaceImage(stored=True, path=_png(tmp_path / "face.png"))
    for _ in range(4):
        save_gdraw({"front": {"face_images": [face]}}, path)
        [face] = load_gdraw(path)["front"]["face_images"]
        assert os.path.basename(face.path) == "face.png"
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if n.startswith("images/")]
        assert members == ["images/front_0_face.png"]
        assert zf.getinfo(members[0]).compress_type == zipfile.ZIP_STORED
    assert len([p for p in cache_root.rglob("*") if p.is_file()]) == 1


def test_a_grown_name_heals_and_the_old_copies_are_pruned(tmp_path, cache_root):
    import os
    import zipfile
    from framedraft.export.gdraw import _cache_dir_for, load_gdraw
    path = tmp_path / "old.gdraw"
    grown = "images/front_0_front_0_front_0_face.png"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("front.svg", _svg_with({"face_images": [{"path": grown}]}))
        zf.write(_png(tmp_path / "src.png"), grown)
    stale = _cache_dir_for(str(path)) / "front_0_front_0_face.png"
    stale.write_bytes(b"left by an older open")
    [face] = load_gdraw(str(path))["front"]["face_images"]
    assert os.path.basename(face.path) == "face.png"
    assert not stale.exists()


@pytest.mark.parametrize("member, written", [
    # On Windows a backslash parts the name like a slash, and the bare
    # "evil.png" is as safe inside the cache.
    ("images/front_0_..\\..\\evil.png",
     "evil.png" if os.name == "nt" else ".._.._evil.png"),
    ("images/front_0_CON.png", "_CON.png"),
    ("images/front_0_c:evil.png", "c_evil.png"),
    ("images/front_0_2026-10-17T10:15:22.jpg", "2026-10-17T10_15_22.jpg")])
def test_a_member_name_is_made_safe_and_the_photo_still_opens(
        tmp_path, cache_root, member, written):
    """Refusing such names lost a photo named for its time on Linux, where a
    colon is ordinary; the cache now writes a safe name, inside itself."""
    import os
    import zipfile
    from framedraft.export.gdraw import load_gdraw, save_gdraw
    path = tmp_path / "crafted.gdraw"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("front.svg", _svg_with({"face_images": [{"path": member}]}))
        # writestr, not write: write normalizes the name on Windows and
        # resolves its "..", so the hostile name was never stored.
        with open(_png(tmp_path / "src.png"), "rb") as f:
            zf.writestr(zipfile.ZipInfo(member), f.read())
    [face] = load_gdraw(str(path))["front"]["face_images"]
    assert os.path.basename(face.path) == written
    assert os.path.isfile(face.path) and str(cache_root) in face.path
    assert not list(tmp_path.glob("evil*"))
    save_gdraw({"front": {"face_images": [face]}}, str(path))   # kept on save
    with zipfile.ZipFile(path) as zf:
        assert [n for n in zf.namelist() if n.startswith("images/")]


def test_a_second_open_never_prunes_a_photo_in_use(tmp_path, cache_root):
    """A photo's cache folder is named by its bytes: a second open of the
    same design, after an earlier photo was removed, used to prune the
    folder the first open's photo sat in, and its next save dropped it."""
    import os
    from framedraft.document import FaceImage
    from framedraft.export.gdraw import load_gdraw, save_gdraw
    from PySide6.QtGui import QImage
    path = str(tmp_path / "d.gdraw")
    p, q = tmp_path / "p.png", tmp_path / "q.png"
    for f, color in ((p, 0x112233), (q, 0x445566)):
        img = QImage(4, 4, QImage.Format.Format_RGB32)
        img.fill(color)
        img.save(str(f))
    save_gdraw({"front": {"face_images": [FaceImage(stored=True, path=str(p)),
                                          FaceImage(stored=True, path=str(q))]}}, path)
    first = load_gdraw(path)["front"]["face_images"]
    save_gdraw({"front": {"face_images": [first[1]]}}, path)    # p removed
    load_gdraw(path)                                            # a second open
    assert os.path.isfile(first[1].path)
    save_gdraw({"front": {"face_images": [first[1]]}}, path)
    [kept] = load_gdraw(path)["front"]["face_images"]
    assert os.path.basename(kept.path) == "q.png"


def test_a_manifest_with_a_byte_order_mark_opens(tmp_path):
    import json
    import zipfile
    from framedraft.export.gdraw import load_gdraw
    path = tmp_path / "bom.gdraw"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json",
                    "﻿" + json.dumps({"version": 1, "active_tab": "temple_r"}))
        zf.writestr("front.svg", _svg_with({}))
    assert load_gdraw(str(path))["active_tab"] == "temple_r"


# ── 7. Split never leaves a degenerate curve ───────────────────────────────

def _pick_node(win, monkeypatch, curve, idx):
    monkeypatch.setattr(win._edit_tool, "selected_node_info", lambda: (curve, idx))
    monkeypatch.setattr(win._edit_tool, "has_selected_node", lambda: True)


@pytest.mark.parametrize("which", ["circle", "end node"])
def test_split_refuses_a_circles_center_and_an_end_node(win, monkeypatch, which):
    ws = win._active_ws
    c = (circle(0, 0, 5, layer=Layer.DRILL) if which == "circle"
         else line([(0, 0), (10, 0), (10, 10)], layer=Layer.OUTLINE))
    ws.add_curve(c)
    _select(win)
    _pick_node(win, monkeypatch, c, 0)
    win._update_split_enabled()
    assert not win._act_split.isEnabled()
    win._split_at_node()
    assert ws.doc_curves == [c]
    _pick_node(win, monkeypatch, c, 1)
    win._update_split_enabled()
    assert win._act_split.isEnabled() == (which == "end node")


def test_transform_of_a_curve_that_draws_nothing_does_not_raise(win, monkeypatch):
    import framedraft.app as app_mod
    from PySide6.QtWidgets import QDialog
    ws = win._active_ws
    c = circle(0, 0, 5, layer=Layer.DRILL)
    c.radius = None
    ws.add_curve(c)
    _select(win)
    monkeypatch.setattr(app_mod, "_run_modal", lambda dlg: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(app_mod.TransformDialog, "values",
                        lambda self: (2.0, 2.0, 0.0, False))
    win._transform_selected()
    assert "draws nothing" in win._status.currentMessage()


# ── 8. Medium ──────────────────────────────────────────────────────────────

def test_guide_size_edits_mark_the_design_dirty(win):
    for spin, value in ((win._stock_w_spin, 180.0), (win._stock_h_spin, 80.0),
                        (win._pad_w_spin, 50.0), (win._pad_h_spin, 40.0)):
        win._dirty = False
        spin.setValue(value)
        assert win._dirty
    ws = win._active_ws
    assert (ws.pad_w, ws.pad_h) == (50.0, 40.0)


def test_the_snap_engine_keeps_the_live_curve_list(win):
    ws = win._active_ws
    assert not ws.doc_curves
    win._set_tool_line()
    assert ws.snap._doc_curves is ws.doc_curves
    win._set_tool_select()


def test_a_fresh_window_with_the_ghost_off_at_start_up_is_clean(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(json.dumps({"mirror_on_startup": False}))
    from framedraft.app import MainWindow
    w = MainWindow()
    try:
        assert not w._act_mirror.isChecked()
        assert not w._dirty
    finally:
        w._dirty = False
        w.close()
        w.deleteLater()


# ── 9. Low ─────────────────────────────────────────────────────────────────

def test_join_leaves_closed_curves_and_circles_as_they_are(win):
    ws = win._active_ws
    a = line([(0, 0), (10, 0)], layer=Layer.OUTLINE)
    b = line([(10, 0), (10, 10)], layer=Layer.OUTLINE)
    ring = closed_diamond(40, 0, 5, layer=Layer.OUTLINE)
    hole = circle(-30, 0, 3, layer=Layer.OUTLINE)
    for c in (a, b, ring, hole):
        ws.add_curve(c)
    _select(win)
    win._join_selected_curves()
    assert any(c is ring for c in ws.doc_curves) and ring.closed
    assert any(c is hole for c in ws.doc_curves)
    assert len(ws.doc_curves) == 3
    assert "closed curve(s) skipped" in win._status.currentMessage()


def test_a_typed_gizmo_move_follows_its_arrow_in_view_obverse(win):
    ws = win._active_ws
    c = circle(20, 0, 5, layer=Layer.LENS)
    ws.add_curve(c)
    _select(win)
    win.view.set_obverse(True, "posterior")
    win._show_move_gizmo()
    win._move_gizmo._hud_commit(5.0, 0.0)          # the arrow pointing right
    assert c.nodes[0].x == pytest.approx(15.0)     # right on screen is −x
    win._hide_move_gizmo()
    win.view.set_obverse(False)


def test_an_untouched_font_box_keeps_the_family_it_was_given():
    from framedraft.fontpicker import FontFilterCombo, font_families
    families = set(font_families())
    stem = next(f[:-1] for f in sorted(families) if len(f) > 3 and f[:-1] not in families)
    box = FontFilterCombo(family=stem)
    assert box.current_family() == stem
    box.deleteLater()


def test_undo_in_the_middle_of_a_drag_casts_no_ghost(win):
    ws = win._active_ws
    ws.add_curve(circle(20, 0, 5, layer=Layer.LENS))
    assert win._act_mirror.isChecked()
    _select(win)
    win._pre_move_selected()
    win._move_selected_by(1.0, 0.0)
    win._undo()
    win._move_selected_by(1.0, 0.0)
    live = {id(c) for c in ws.doc_curves}
    assert set(ws.scene._ghost_items) <= live


def test_a_group_across_a_hidden_or_locked_layer_moves_whole(win):
    """Selected by its visible member, a group moves, copies and deletes as
    one: its member on a hidden or locked layer rides along. (Holding such a
    group unselectable made every shipped hinge unpickable with REF hidden.)"""
    ws = win._active_ws
    pocket = closed_diamond(-20, 0, 3, layer=Layer.COMPONENT)
    guide = line([(-30, 0), (-10, 0)], layer=Layer.REF)
    pocket.group_id = guide.group_id = "g1"
    item = ws.add_curve(pocket)
    ws.add_curve(guide)
    for hide in (True, False):
        if hide:
            ws.scene.set_layer_visible(Layer.REF, False)
        else:
            ws.scene.set_layer_visible(Layer.REF, True)
            ws.scene.set_layer_locked(Layer.REF, True)
        win.scene.clearSelection()
        item.setSelected(True)
        assert item.isSelected()
        win._pre_move_selected()
        win._move_selected_by(5.0, 0.0)
        win._end_move_selected()
    assert guide.nodes[0].x == pytest.approx(-20.0)     # moved twice, with it
    win.scene.clearSelection()
    item.setSelected(True)
    win._duplicate_selected()
    assert sum(c.layer == Layer.REF for c in ws.doc_curves) == 2
    win.scene.clearSelection()
    item.setSelected(True)
    win._delete_selected()
    assert sum(c.group_id == "g1" for c in ws.doc_curves) == 0


def test_face_photos_keep_their_places_when_one_fails_to_decode(win, tmp_path):
    from framedraft.document import FaceImage
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    good = _png(tmp_path / "good.png")
    ws = win._active_ws
    win._load_ws_data(ws, {"face_images": [FaceImage(stored=True, path=str(broken), tx=1, ty=1),
                                           FaceImage(stored=True, path=good, tx=5, ty=7)]})
    item = ws.scene.get_face_item(0)
    assert (item.pos().x(), item.pos().y()) == (5.0, 7.0)


def test_a_save_keeps_the_file_and_its_previous_version(win, tmp_path):
    import os
    ws = win._active_ws
    for c in _front()["curves"]:
        ws.add_curve(c)
    path = str(tmp_path / "s.gdraw")
    assert win._do_save(path)
    assert win._do_save(path)
    assert os.path.isfile(path) and os.path.isfile(path + ".bak")
    assert not os.path.exists(path + ".tmp")


# ── Inefficiencies ─────────────────────────────────────────────────────────

def test_an_inlay_edit_rebuilds_only_the_inlay_fill(win, monkeypatch):
    ws = win._active_ws
    sc = ws.scene
    ws.add_curve(closed_diamond(10, -28, 3, layer=Layer.INLAY))
    assert sc.set_inlay_fill_visible(True) == "ok"
    rebuilt = []
    for name in ("rebuild_fill", "rebuild_lens_fill", "rebuild_inlay_fill"):
        monkeypatch.setattr(sc, name, lambda name=name: rebuilt.append(name))
    seat = closed_diamond(0, -28, 3, layer=Layer.INLAY)
    ws.add_curve(seat)
    sc._rebuild_dirty_overlays()
    assert rebuilt == ["rebuild_inlay_fill"]
    rebuilt.clear()
    seat.layer = Layer.LENS                         # a layer move: both fills
    sc.refresh_curve(seat)
    sc._rebuild_dirty_overlays()
    assert rebuilt == ["rebuild_fill", "rebuild_lens_fill", "rebuild_inlay_fill"]


def test_arrow_steps_in_the_weight_box_are_one_undo_step(win):
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 20, layer=Layer.OUTLINE))
    _select(win)
    depth = len(win._undo_stack)
    for _ in range(5):
        win._weight_spin.stepUp()
    assert len(win._undo_stack) == depth + 1
    win._undo()
    _select(win)                                  # Undo rebuilt the curves
    win._weight_spin.stepUp()
    assert len(win._undo_stack) == depth + 1      # a new run after the undo


def test_no_empty_undo_steps_for_explode_or_a_zero_move(win):
    ws = win._active_ws
    ws.add_curve(line([(0, 0), (10, 0)], layer=Layer.OUTLINE))
    _select(win)
    depth = len(win._undo_stack)
    win._explode_selected()
    assert len(win._undo_stack) == depth
    win._pm_curves, win._pm_dims = list(ws.doc_curves), []
    win._on_point_moved(0.0, 0.0)
    assert len(win._undo_stack) == depth


# ── Prints and the OMA trace show the Ghost the canvas shows ───────────────

def test_prints_and_the_oma_trace_add_only_the_twins_the_ghost_adds(win, monkeypatch,
                                                                    tmp_path):
    tmp_oma = [tmp_path / "trace.oma"]
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
              circle(-15, 0, 10, layer=Layer.LENS), circle(15, 0, 10, layer=Layer.LENS),
              circle(-22, 6, 0.7, layer=Layer.DRILL)):
        ws.add_curve(c)
    assert win._act_mirror.isChecked()
    win._save_ws_sidebar_state(ws)
    front = win._gather_template_components()["front"]["curves"]
    assert sum(c.layer == Layer.OUTLINE for c in front) == 1    # a whole outline
    assert sum(c.layer == Layer.LENS for c in front) == 2       # a drawn pair
    assert sum(c.layer == Layer.DRILL for c in front) == 2      # the hole's twin
    built = []
    monkeypatch.setattr(win, "_ask_oma_export_bevel", lambda d: 0.0)
    import framedraft.export.oma as oma_mod
    monkeypatch.setattr(oma_mod, "build_oma", lambda job: built.append(job) or "")
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_oma[0]), "")))
    win._export_oma()                    # a drawn pair: two lenses, not four
    [job] = built
    assert set(job.traces) == {"R", "L"}
    assert len(job.drills) == 2          # the hole and the Ghost's twin of it
