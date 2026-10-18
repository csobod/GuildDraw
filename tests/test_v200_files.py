"""The 2.0 polish round on files (BUILDPLAN Road to 2.0, item 14): what does
not read is left out and said while the rest opens, numbers that are not
numbers never reach the drawing or the file, and the OMA trace measures its
drill holes from the lenses."""
import gc
import os
import json
import math
import zipfile

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication, QMessageBox

import framedraft.prefs as prefs_mod
from framedraft import library as lib_mod
from framedraft.document import Curve, Layer, SplineNode
from helpers import circle, closed_diamond


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    root = tmp_path / "library"
    monkeypatch.setattr(lib_mod, "_LIBRARY_DIR", root)
    monkeypatch.setattr(lib_mod, "_COMPONENTS_DIR", root / "components")
    monkeypatch.setattr(lib_mod, "_HINGES_DIR", root / "hinges")
    monkeypatch.setattr(lib_mod, "_DRILLS_DIR", root / "drills")
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


def _svg(state: dict) -> str:
    return ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">'
            f'<metadata>{json.dumps(state)}</metadata></svg>')


def _curve(layer="OUTLINE", x=0.0):
    return {"kind": "line", "layer": layer,
            "nodes": [{"x": x, "y": 0}, {"x": x + 5, "y": 0}]}


# ── What does not read is left out, the rest opens ─────────────────────────

def test_a_curve_from_a_later_guilddraw_leaves_the_rest_of_the_tab(win, tmp_path,
                                                                    monkeypatch):
    p = tmp_path / "later.gdraw"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", '{"version": 1, "active_tab": "front"}')
        zf.writestr("front.svg", _svg({"curves": [_curve(), _curve(x=10),
                                                  _curve("SOMEDAY")]}))
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: told.append(a))
    assert win._open_gdraw(str(p), remember=False) == "errors"
    assert len(win._workspaces[0].doc_curves) == 2
    assert win._current_path is None and win._dirty     # Save asks for a name
    title, text = told[0][1], told[0][2]
    assert title == "Some of the Design Could Not Be Read"
    assert "Frame Front: 1 curve (a layer this GuildDraw does not know: 'SOMEDAY')" in text


def test_a_design_holding_a_nan_says_so_and_writes_nothing(win, tmp_path, monkeypatch):
    bad = Curve(kind="line", layer=Layer.REF,
                nodes=[SplineNode(x=0, y=0), SplineNode(x=float("nan"), y=0)])
    win._active_ws.add_curve(bad)
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: told.append(a))
    path = tmp_path / "nan.gdraw"
    assert not win._do_save(str(path))
    assert not path.exists()
    assert "a value that cannot be written" in told[0][2]


def test_svg_import_leaves_out_a_curve_that_overflows(tmp_path):
    from framedraft.export.svg_import import read_svg
    p = tmp_path / "logo.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
                 'viewBox="0 0 100 100"><path d="M 0 0 L 10 0 L 10 10 Z"/>'
                 '<g transform="scale(1e200)"><g transform="scale(1e200)">'
                 '<path d="M 0 0 L 10 0"/></g></g></svg>')
    doc = read_svg(str(p), Layer.REF)
    assert len(doc.curves) == 1
    assert any("not finite" in n for n in doc.notes)


def test_oma_fields_that_are_not_numbers_are_refused():
    from framedraft.export.oma import parse_oma
    job = parse_oma("DBL=nan\r\n")
    assert job.floats("DBL") is None
    with pytest.raises(ValueError, match="DRILLE"):
        parse_oma("DRILLE=R;C;inf;2;1.4\r\n")


def test_a_drill_pattern_hole_that_is_not_a_number_is_left_out(win, tmp_path):
    from framedraft.library import DrillLibrary
    p = tmp_path / "pattern.json"
    p.write_text('{"version": 2, "holes": [{"dx": NaN, "dy": 0, "dia": 1.4},'
                 ' {"dx": 3, "dy": 1, "dia": 1.4}]}')
    holes = DrillLibrary().load_entry(str(p))
    assert [h["dx"] for h in holes] == [3.0]


def test_a_view_is_never_fitted_to_a_rectangle_that_is_not_one(win):
    view = win.view
    z = view.zoom()
    view.fit_view(QRectF(0, 0, float("nan"), 10))
    assert view.zoom() == z
    view.scale(float("nan"), float("nan"))
    view.zoom_by(1.0)                                # recovers instead of raising
    assert math.isfinite(view.zoom()) and view.zoom() > 0


def test_an_absurd_photo_calibration_reads_as_none(tmp_path):
    from framedraft.export.svg import load_svg
    p = tmp_path / "cal.svg"
    p.write_text(_svg({"calibration": {"px_per_mm": 4.6e307}}))
    assert not load_svg(str(p))["calibration"].is_set


# ── The OMA trace ──────────────────────────────────────────────────────────

def test_the_oma_trace_measures_drill_holes_from_the_lenses(win, monkeypatch, tmp_path):
    """On a front drawn 7 mm above the origin, a hole 5 mm above its lens went
    to the lab 12 mm above it."""
    from framedraft.export.oma import parse_oma
    ws = win._active_ws
    win._act_mirror.setChecked(False)
    for c in (closed_diamond(0, -7, 45, layer=Layer.OUTLINE),
              circle(-22, -7, 10, layer=Layer.LENS), circle(22, -7, 10, layer=Layer.LENS),
              circle(-22, -12, 0.7, layer=Layer.DRILL)):
        ws.add_curve(c)
    monkeypatch.setattr(win, "_ask_oma_export_bevel", lambda d: 0.0)
    out = tmp_path / "trace.oma"
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win._export_oma()
    [hole] = parse_oma(out.read_text()).drills
    assert (hole.x, hole.y) == pytest.approx((-22.0, 5.0), abs=1e-6)


def test_traced_lenses_replace_the_drawn_ones_when_asked(win, monkeypatch, tmp_path):
    from framedraft.export.oma import OmaJob, OmaTrace, build_oma
    ws = win._active_ws
    for c in (circle(-22, 0, 10, layer=Layer.LENS), circle(22, 0, 10, layer=Layer.LENS)):
        ws.add_curve(c)
    job = OmaJob()
    for side in ("R", "L"):
        job.traces[side] = OmaTrace(side=side, radii_mm=[20.0] * 360)
    src = tmp_path / "lab.oma"
    src.write_text(build_oma(job))
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(src), "")))
    monkeypatch.setattr(win, "_ask_oma_import_bevel", lambda d: 0.0)
    asked = []
    monkeypatch.setattr(win, "_ask_oma_import_mode",
                        lambda n: asked.append(n) or "replace")
    win._import_oma()
    lenses = [c for c in ws.doc_curves if c.layer == Layer.LENS]
    assert asked == [2] and len(lenses) == 2
    assert all(c.kind == "spline" for c in lenses)       # the traced pair only


# ── Crash recovery ─────────────────────────────────────────────────────────

def _orphan_with(win, tmp_path, monkeypatch, *, front_svg=None, source=None,
                 saved_at="2026-01-01T10:00:00"):
    from framedraft.app import MainWindow
    monkeypatch.setattr(MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    win._AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
    rec = win._AUTOSAVE_DIR / "recovery-999999.gdraw"
    with zipfile.ZipFile(rec, "w") as zf:
        zf.writestr("manifest.json", '{"version": 1, "active_tab": "front"}')
        zf.writestr("front.svg", front_svg or _svg({"curves": [_curve()]}))
    rec.with_suffix(".json").write_text(json.dumps(
        {"source_path": source, "saved_at": saved_at}))
    return rec


def test_a_recovery_that_reads_only_in_part_keeps_its_file(win, tmp_path, monkeypatch):
    rec = _orphan_with(win, tmp_path, monkeypatch,
                       front_svg=_svg({"curves": [_curve(), _curve("SOMEDAY")]}))
    monkeypatch.setattr(win, "_ask_recovery", lambda *_a: "restore")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    assert win._offer_recovery() is True
    assert len(win._workspaces[0].doc_curves) == 1
    kept = list(win._AUTOSAVE_DIR.glob("failed-*.gdraw.bak"))
    assert len(kept) == 1 and not rec.exists()
    with zipfile.ZipFile(kept[0]) as zf:                  # the whole thing
        assert "SOMEDAY" in zf.read("front.svg").decode()
    assert str(kept[0]) in win._status.currentMessage()


def test_a_recovery_older_than_its_files_last_save_opens_without_the_path(
        win, tmp_path, monkeypatch):
    src = tmp_path / "frame.gdraw"
    src.write_bytes(b"newer")                             # saved after the crash
    _orphan_with(win, tmp_path, monkeypatch, source=str(src),
                 saved_at="2020-01-01T10:00:00")
    told = []
    monkeypatch.setattr(win, "_ask_recovery",
                        lambda text, detail: told.append(text) or "restore")
    assert win._offer_recovery() is True
    assert "was saved again after this autosave" in told[0]
    assert win._current_path is None                      # Ctrl+S asks for a name


# ── Saving ─────────────────────────────────────────────────────────────────

def _png(path, payload=b"x" * 64):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload)
    return path


@pytest.fixture()
def cache_root(tmp_path, monkeypatch):
    import framedraft.export.gdraw as gdraw_mod
    root = tmp_path / "imagecache"
    monkeypatch.setattr(gdraw_mod, "_IMAGE_CACHE_ROOT", root)
    return root


def _with_photo(tmp_path, name="face.png"):
    from framedraft.document import FaceImage
    img = _png(tmp_path / name)
    return img, {"front": {"face_images": [FaceImage(stored=True, path=str(img))]}}


def test_a_photo_the_save_cannot_read_comes_from_the_file_it_replaces(tmp_path,
                                                                      cache_root):
    from framedraft.export.gdraw import load_gdraw, save_gdraw
    img, data = _with_photo(tmp_path)
    doc = tmp_path / "frame.gdraw"
    assert save_gdraw(data, str(doc)) == []
    img.unlink()                                   # the cache cleared, a share offline
    out = tmp_path / "again.gdraw"
    assert save_gdraw(data, str(out), carry_from=str(doc)) == []
    with zipfile.ZipFile(out) as zf:
        assert zf.read("images/front_0_face.png").startswith(b"\x89PNG")
    notes = save_gdraw(data, str(tmp_path / "third.gdraw"))      # nothing to carry from
    assert notes == ["front: the reference image face.png is gone, and was not carried"]
    assert load_gdraw(str(out))["front"]["face_images"][0].path.endswith("face.png")


def test_a_photo_past_the_size_cap_is_carried_not_dropped(tmp_path, cache_root,
                                                         monkeypatch):
    import framedraft.export.gdraw as gdraw_mod
    from framedraft.export.gdraw import load_gdraw, save_gdraw
    _img, data = _with_photo(tmp_path)
    doc = tmp_path / "frame.gdraw"
    save_gdraw(data, str(doc))
    monkeypatch.setattr(gdraw_mod, "_MAX_IMAGE_BYTES", 16)   # now "too large"
    loaded = load_gdraw(str(doc))
    fi = loaded["front"]["face_images"][0]
    assert fi.path == "images/front_0_face.png"             # not extracted
    out = tmp_path / "next.gdraw"
    assert save_gdraw({"front": {"face_images": [fi]}}, str(out),
                      carry_from=str(doc)) == []
    with zipfile.ZipFile(out) as zf:
        assert "images/front_0_face.png" in zf.namelist()


def test_an_unchanged_design_saves_to_the_same_bytes(tmp_path, cache_root):
    import time
    from framedraft.export.gdraw import save_gdraw
    _img, data = _with_photo(tmp_path)
    a, b = tmp_path / "a.gdraw", tmp_path / "b.gdraw"
    save_gdraw(data, str(a))
    time.sleep(2.1)                                 # past the zip time's 2 s grain
    save_gdraw(data, str(b))
    assert a.read_bytes() == b.read_bytes()


def test_a_member_that_is_not_an_image_never_reaches_the_cache(tmp_path, cache_root):
    from framedraft.export.gdraw import load_gdraw
    doc = tmp_path / "odd.gdraw"
    with zipfile.ZipFile(doc, "w") as zf:
        zf.writestr("manifest.json", '{"version": 1, "active_tab": "front"}')
        zf.writestr("front.svg", _svg({"face_images": [
            {"path": "images/front_0_x.png"}]}))
        zf.writestr("images/front_0_x.png", b"#!/bin/sh\necho hi\n")
    fi = load_gdraw(str(doc))["front"]["face_images"][0]
    assert fi.path == "images/front_0_x.png"
    assert not cache_root.exists() or not any(p.is_file() for p in cache_root.rglob("*"))


def test_save_refuses_a_read_only_file(win, tmp_path, monkeypatch):
    p = tmp_path / "locked.gdraw"
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    assert win._do_save(str(p))
    p.chmod(0o444)
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: told.append(a))
    before = p.read_bytes()
    win._workspaces[0].add_curve(closed_diamond(50, 0, 10))
    assert not win._do_save(str(p))
    assert p.read_bytes() == before and told[0][1] == "File Is Read-Only"


def test_save_goes_through_a_link_and_keeps_the_files_mode(win, tmp_path):
    real = tmp_path / "synced" / "frame.gdraw"
    real.parent.mkdir()
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    assert win._do_save(str(real))
    real.chmod(0o664)
    link = tmp_path / "frame.gdraw"
    link.symlink_to(real)
    win._workspaces[0].add_curve(closed_diamond(50, 0, 10))
    assert win._do_save(str(link))
    assert link.is_symlink()                        # still a link …
    if os.name != "nt":                             # (Windows keeps no mode bits)
        assert (real.stat().st_mode & 0o777) == 0o664   # … the real file saved, shared
    assert (real.parent / "frame.gdraw.bak").exists()


def test_a_file_changed_on_disk_is_not_overwritten_unasked(win, tmp_path, monkeypatch):
    import os
    p = tmp_path / "shared.gdraw"
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    assert win._do_save(str(p))
    p.write_bytes(p.read_bytes() + b"\0")           # another window saved it
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    asked = []
    monkeypatch.setattr(win, "_ask_changed_on_disk",
                        lambda name: asked.append(name) or None)
    assert not win._do_save(str(p))
    assert asked == ["shared.gdraw"]
    monkeypatch.setattr(win, "_ask_changed_on_disk", lambda name: "overwrite")
    assert win._do_save(str(p))


def test_a_name_near_the_length_limit_saves(win, tmp_path):
    name = "□" * 81 + ".gdraw"                       # 249 bytes of name
    win._workspaces[0].add_curve(closed_diamond(0, 0, 20))
    assert win._do_save(str(tmp_path / name))


# ── Preferences and the open design ────────────────────────────────────────

def test_preferences_ask_before_changing_a_drawn_design(win, monkeypatch):
    import copy
    front = win._workspaces[0]
    front.add_curve(closed_diamond(0, 0, 40))
    win._dirty = False
    width = front.stock_w
    p = copy.deepcopy(win._prefs)
    p["stock_width_mm"] = width + 10
    p["temple_stock_width_mm"] = 190.0
    asked = []
    monkeypatch.setattr(win, "_ask_apply_to_open_design",
                        lambda: asked.append(1) or False)
    win._ws_tab_widget.setCurrentIndex(1)               # from a temple tab
    QApplication.processEvents()
    win._apply_settings(p)
    assert asked == [1]
    assert front.stock_w == width and not win._dirty     # new designs only
    assert win._workspaces[1].stock_w != 190.0
    p2 = copy.deepcopy(p)
    p2["stock_width_mm"] = width + 20
    monkeypatch.setattr(win, "_ask_apply_to_open_design", lambda: True)
    win._apply_settings(p2)
    assert front.stock_w == width + 20 and win._dirty    # applied, and unsaved


# ── Reference photos ───────────────────────────────────────────────────────

def _photo(tmp_path, name, w, h):
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#808080"))
    p = tmp_path / name
    img.save(str(p))
    return str(p)


def test_each_photo_keeps_its_own_calibration(win, tmp_path, cache_root, monkeypatch):
    """Two photos at 10 and 2 px/mm: calibrating the second measured in the
    first's pixels and gave both one scale."""
    import framedraft.app as app_mod
    scene = win.scene
    for name in ("front.png", "side.png"):
        path = _photo(tmp_path, name, 400, 300)
        monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, path=path, **k: (path, "")))
        win._add_face()
    win._apply_calibration(10.0, 0)
    win._apply_calibration(2.0, 1)
    assert (scene.face_calibration(0), scene.face_calibration(1)) == (10.0, 2.0)
    assert scene.get_face_item(0).scale() == pytest.approx(0.1)
    assert scene.get_face_item(1).scale() == pytest.approx(0.5)
    # The tool measures the photo under its first click.
    item = scene.get_face_item(1)
    assert scene.face_index_at(item.sceneBoundingRect().center()) == 1
    doc = tmp_path / "two.gdraw"
    assert win._do_save(str(doc))
    win._open_gdraw(str(doc), remember=False)
    assert (win.scene.face_calibration(0), win.scene.face_calibration(1)) == (10.0, 2.0)
    assert win._calib_btn.isEnabled()
    win._new()
    assert not win._calib_btn.isEnabled() and not win._pxmm_spin.isEnabled()


# ── Exports ────────────────────────────────────────────────────────────────

def test_a_png_records_its_resolution_and_leaves_the_selection_out(win, tmp_path,
                                                                  monkeypatch):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    ws = win._active_ws
    item = ws.add_curve(closed_diamond(0, 0, 20))
    out = tmp_path / "front.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: (a[3][1], True)))   # 300 dpi
    win._export_png()
    plain = QImage(str(out))
    assert round(plain.dotsPerMeterX() * 0.0254) == 300
    item.setSelected(True)
    win._export_png()
    assert QImage(str(out)) == plain                  # no glow, no dots
    assert item.isSelected()                          # and it is given back


def test_an_empty_tab_exports_nothing_and_says_so(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "x.dxf"), "")))
    win._export_dxf()
    assert told and "empty" in told[0][2]
    assert not (tmp_path / "x.dxf").exists()


def test_a_suffix_added_after_the_dialog_still_asks_before_replacing(win, tmp_path,
                                                                     monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    (tmp_path / "front.dxf").write_text("hand edited")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "front"), "")))
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.No)
    win._export_dxf()
    assert asked and (tmp_path / "front.dxf").read_text() == "hand edited"


def test_dialogs_start_beside_the_design_with_a_name(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    doc = tmp_path / "aviator.gdraw"
    assert win._do_save(str(doc))
    starts = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: starts.append(a[2]) or ("", "")))
    win._export_dxf()
    assert starts == [str(tmp_path / "aviator_front.dxf")]


def test_export_every_tab_asks_before_replacing_its_files(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    (tmp_path / "frame_front.dxf").write_text("hand edited")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "frame.dxf"), "")))
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.No)
    win._export_all_dxf()
    assert asked and "frame_front.dxf" in asked[0][2]
    assert (tmp_path / "frame_front.dxf").read_text() == "hand edited"


def test_the_oma_export_goes_to_the_front_from_a_temple(win, monkeypatch, tmp_path):
    for c in (closed_diamond(0, 0, 45, layer=Layer.OUTLINE),
              circle(-20, 0, 10, layer=Layer.LENS), circle(20, 0, 10, layer=Layer.LENS)):
        win._workspaces[0].add_curve(c)
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    monkeypatch.setattr(win, "_ask_oma_export_bevel", lambda d: 0.0)
    out = tmp_path / "t.oma"
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win._export_oma()
    assert win._ws_tab_widget.currentIndex() == 0 and out.exists()


def test_removing_a_reference_image_asks_first(win, tmp_path, monkeypatch, cache_root):
    import framedraft.app as app_mod
    path = _photo(tmp_path, "face.png", 200, 100)
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    win._add_face()
    win._face_tree.setCurrentItem(win._face_tree.topLevelItem(0))
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: next(answers))
    win._remove_face()
    assert win.scene.face_count() == 1
    win._remove_face()
    assert win.scene.face_count() == 0


def test_a_dropped_file_opens_imports_or_adds(win, tmp_path, monkeypatch, cache_root):
    from PySide6.QtCore import QMimeData, QUrl
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    design = tmp_path / "drop.gdraw"
    assert win._do_save(str(design))
    import ezdxf
    doc = ezdxf.new("R2000")
    doc.units = 4
    doc.modelspace().add_line((0, 0), (5, 0))
    dxf = tmp_path / "part.dxf"
    doc.saveas(str(dxf))
    photo = _photo(tmp_path, "face.png", 100, 60)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(dxf))])
    # Qt names a local file with forward slashes on Windows, as its file
    # dialogs do; the same file either way.
    assert os.path.normpath(win._dropped_path(mime)) == str(dxf)
    before = len(win._active_ws.doc_curves)
    win._open_dropped(str(dxf))
    assert len(win._active_ws.doc_curves) == before + 1        # imported
    win._open_dropped(photo)
    assert win.scene.face_count() == 1                          # a reference photo
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: QMessageBox.StandardButton.Discard)
    win._open_dropped(str(design))
    assert win._current_path == str(design)                     # opened
    plain = QMimeData()
    plain.setUrls([QUrl.fromLocalFile(str(tmp_path / "notes.txt"))])
    assert win._dropped_path(plain) is None


def test_the_1to1_print_says_cropped_only_when_the_drawing_is(win, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    ws = win._active_ws
    item = ws.add_curve(closed_diamond(0, 0, 30))

    def render(source):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(tmp_path / "one.pdf"))
        return win._render_1to1(printer, source)

    # A view far larger than the page, the drawing well inside it: whole.
    assert render(QRectF(-400, -300, 800, 600)) is False
    ws.remove_curve(item.curve)
    ws.add_curve(closed_diamond(0, 0, 200))          # 400 mm across: not
    assert render(QRectF(-400, -300, 800, 600)) is True


def test_the_folder_run_starts_without_saving_and_opens_its_folder(win, tmp_path):
    from framedraft.batch_catalog_ui import (BatchCatalogOptionsDialog,
                                             BatchCatalogProgressDialog)
    dlg = BatchCatalogOptionsDialog(win, str(tmp_path), {})
    assert not dlg._save_chk.isChecked()                 # first run: nothing written
    dlg._dry_chk.setChecked(True)
    assert not dlg._save_chk.isEnabled()
    prog = BatchCatalogProgressDialog(win, 1)
    prog.finish("1 PDF written.", str(tmp_path))
    assert "Open Folder" in [b.text() for b in prog._buttons.buttons()]
    dlg.deleteLater()
    prog.deleteLater()


def test_the_demo_front_script_writes_a_ready_front(tmp_path):
    """It still passed the Ghost arguments export_dxf dropped in 2.0, and
    raised a TypeError."""
    import subprocess
    import sys
    from pathlib import Path
    from framedraft.export.dxf_import import import_dxf
    from framedraft.export.validate import validate
    out = tmp_path / "demo.dxf"
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "make_demo_front.py"),
                    str(out)], check=True, capture_output=True, timeout=120)
    curves, _notes = import_dxf(str(out), Layer.REF)
    assert validate(curves, False, "front") == ([], [])


def test_a_font_this_computer_lacks_is_named(win):
    from framedraft.textpath import font_stand_in
    from framedraft.tools.text import TextDialog
    from framedraft.document import TextObject
    missing = "Guild No Such Face 2"
    assert font_stand_in(missing)                      # drawn in a stand-in
    t = TextObject(text="GUILD", family=missing, size_mm=5.0, layer=Layer.ENGRAVING)
    dlg = TextDialog(win, t)
    assert not dlg._font_note.isHidden()
    assert missing in dlg._font_note.text()
    dlg.deleteLater()


def test_an_exported_svg_draws_its_text_and_hairlines(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from framedraft.document import TextObject
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    ws = win._active_ws
    ws.add_curve(closed_diamond(70, 0, 20))
    ws.add_text(TextObject(text="GUILD", family="DejaVu Sans", size_mm=4.0,
                           anchor_x=60, anchor_y=0, layer=Layer.ENGRAVING))
    out = tmp_path / "temple.svg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win._export_svg()
    text = out.read_text()
    assert 'data-kind="text"' in text
    assert 'vector-effect="non-scaling-stroke"' in text


def test_a_svg_save_says_what_images_it_does_not_hold(win, tmp_path, monkeypatch,
                                                      cache_root):
    import framedraft.app as app_mod
    (tmp_path / "photos").mkdir()
    path = _photo(tmp_path / "photos", "face.png", 120, 80)
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    win._add_face()
    win._active_ws.add_curve(closed_diamond(0, 0, 20))
    (tmp_path / "designs").mkdir()
    # Not stored, the image is the file's to forget: the .svg never names it.
    assert win._do_save(str(tmp_path / "designs" / "front.svg"))
    assert "not beside it" not in win._status.currentMessage()
    win.scene.set_face_stored(0, True)
    assert win._do_save(str(tmp_path / "designs" / "front.svg"))
    assert "not beside it" in win._status.currentMessage()


# ── SVG import ─────────────────────────────────────────────────────────────

def _read(tmp_path, text, name="in.svg"):
    from framedraft.export.svg_import import read_svg
    p = tmp_path / name
    p.write_text(text)
    return read_svg(str(p), Layer.REF)


def test_svg_import_takes_a_nested_viewbox_and_css_hidden_shapes(tmp_path):
    doc = _read(tmp_path, '''<svg xmlns="http://www.w3.org/2000/svg" width="100mm"
      height="100mm" viewBox="0 0 100 100">
      <style>.guide, .x { display: none }</style>
      <svg x="10" y="10" width="20" height="20" viewBox="0 0 200 200">
        <rect x="0" y="0" width="200" height="100"/>
      </svg>
      <rect class="guide" x="0" y="0" width="50" height="50"/>
    </svg>''')
    assert len(doc.curves) == 1                       # the hidden one stays out
    assert (doc.width_mm, doc.height_mm) == pytest.approx((20.0, 10.0))


def test_svg_import_reads_illustrator_at_72_and_notes_percent(tmp_path):
    ai = _read(tmp_path, '''<?xml version="1.0"?>
    <!-- Generator: Adobe Illustrator 27.0.0, SVG Export Plug-In -->
    <svg xmlns="http://www.w3.org/2000/svg" width="72px" height="72px"
      viewBox="0 0 72 72"><rect x="0" y="0" width="72" height="36"/></svg>''')
    assert ai.width_mm == pytest.approx(25.4)         # an inch, as drawn
    assert any("Illustrator" in n for n in ai.notes)
    pct = _read(tmp_path, '''<svg xmlns="http://www.w3.org/2000/svg" width="100%"
      height="100%" viewBox="0 0 96 96"><rect width="96" height="48"/></svg>''',
                "pct.svg")
    assert any("percent" in n for n in pct.notes)
