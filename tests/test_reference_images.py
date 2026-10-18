"""Reference images on the Canvas tab (2.0): rows like the Layers panel's, an
eye, a padlock, and a paperclip that stores the image in the design.

Not stored, an image is written to the file as its place and a random id;
the computer it was added on maps the id to the file (image_links). Stored,
it goes into the .gdraw as before 2.0, when every image was stored.
"""
import gc
import json
import zipfile

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox, QScrollArea, QStyle,
)

import framedraft.app as app_mod
import framedraft.export.gdraw as gdraw_mod
import framedraft.image_links as links
from framedraft.document import FaceImage
from framedraft.export.gdraw import load_gdraw, save_gdraw
from helpers import closed_diamond


@pytest.fixture()
def cache_root(tmp_path, monkeypatch):
    root = tmp_path / "imagecache"
    monkeypatch.setattr(gdraw_mod, "_IMAGE_CACHE_ROOT", root)
    return root


@pytest.fixture()
def table(tmp_path, monkeypatch):
    """This computer's table of where unstored images are."""
    monkeypatch.setattr(links, "_FILE", tmp_path / "links" / "image_links.json")
    monkeypatch.setattr(links, "_DIR", tmp_path / "links")
    return tmp_path / "links" / "image_links.json"


def another_computer(monkeypatch, tmp_path):
    """The same design opened where no table names its images."""
    monkeypatch.setattr(links, "_FILE", tmp_path / "elsewhere" / "image_links.json")


@pytest.fixture()
def win(tmp_path, monkeypatch, cache_root, table):
    import framedraft.library as lib_mod
    import framedraft.prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    root = tmp_path / "library"
    monkeypatch.setattr(lib_mod, "_LIBRARY_DIR", root)
    monkeypatch.setattr(lib_mod, "_COMPONENTS_DIR", root / "components")
    monkeypatch.setattr(lib_mod, "_HINGES_DIR", root / "hinges")
    monkeypatch.setattr(lib_mod, "_DRILLS_DIR", root / "drills")
    monkeypatch.setattr(lib_mod, "_SEED_MANIFEST", root / "seeded.json")
    monkeypatch.setattr(app_mod.MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    w = app_mod.MainWindow()
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    gc.collect()


def _photo(folder, name="patient_jane_front.png", w=400, h=300, color="#a08060"):
    folder.mkdir(parents=True, exist_ok=True)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    path = folder / name
    img.save(str(path))
    return str(path)


def _add(win, monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    win._add_face()


def _click(win, row, column):
    """A click on a row's icon, through the tree's own signal."""
    win._face_tree.itemClicked.emit(win._face_tree.topLevelItem(row), column)


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


def _rewrite_faces(doc, change):
    """Rewrite the front's face records in *doc* as another program might:
    *change* edits the list of record dicts in place."""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(doc) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    root = ET.fromstring(members["front.svg"])
    meta = root.find("{http://www.w3.org/2000/svg}metadata")
    state = json.loads(meta.text)
    change(state["face_images"])
    meta.text = json.dumps(state)
    members["front.svg"] = ET.tostring(root)
    with zipfile.ZipFile(doc, "w") as zf:
        for n, b in members.items():
            zf.writestr(n, b)


def _front_state(doc) -> dict:
    with zipfile.ZipFile(doc) as zf:
        svg = zf.read("front.svg").decode()
        images = [n for n in zf.namelist() if n.startswith("images/")]
    meta = svg.split("<metadata>", 1)[1].split("</metadata>", 1)[0]
    return {"images": images, "meta": meta,
            "faces": json.loads(meta)["face_images"]}


# ── The file ────────────────────────────────────────────────────────────────

def test_an_unstored_image_leaves_only_its_place_and_an_id(tmp_path, cache_root):
    src = _photo(tmp_path / "Patients" / "Jane Doe")
    doc = tmp_path / "frame.gdraw"
    face = FaceImage(path=src, tx=3.0, ty=-2.0, opacity=0.5, link_id=links.new_id(),
                     visible=False, locked=False)
    save_gdraw({"front": {"face_images": [face]}}, str(doc))
    state = _front_state(doc)
    assert state["images"] == []                        # no bytes
    assert "Jane" not in state["meta"] and "patient" not in state["meta"]
    [rec] = state["faces"]
    assert rec["path"] == "" and rec["stored"] is False
    assert rec["link_id"] == face.link_id
    [back] = load_gdraw(str(doc))["front"]["face_images"]
    assert (back.path, back.stored, back.visible, back.locked, back.tx, back.opacity) \
        == ("", False, False, False, 3.0, 0.5)


def test_a_file_from_before_2_0_stored_every_image(tmp_path, cache_root):
    src = _photo(tmp_path / "photos", "face.png")
    doc = tmp_path / "old.gdraw"
    save_gdraw({"front": {"face_images": [FaceImage(stored=True, path=src)]}}, str(doc))
    # As 1.x wrote it: no word of storing, visibility or the lock.
    def as_1x(faces):
        for key in ("visible", "locked", "stored"):
            del faces[0][key]
    _rewrite_faces(doc, as_1x)
    [back] = load_gdraw(str(doc))["front"]["face_images"]
    assert back.stored and back.visible and back.locked
    assert back.path.startswith(str(cache_root))


def test_an_unstored_record_never_follows_a_path_in_the_file(tmp_path, cache_root):
    """A crafted file naming a private photo as an unstored image: the path is
    dropped, and only the id is looked up, in a table the file cannot
    write."""
    private = _photo(tmp_path / "private", "secret.png")
    doc = tmp_path / "crafted.gdraw"
    save_gdraw({"front": {"face_images": [FaceImage(stored=True, path=private)]}},
               str(doc))
    _rewrite_faces(doc, lambda faces: faces[0].update(stored=False, path=private))
    [back] = load_gdraw(str(doc))["front"]["face_images"]
    assert back.path == "" and not back.stored


# ── The window ──────────────────────────────────────────────────────────────

def test_an_added_image_reopens_here_where_it_was_left(win, tmp_path, monkeypatch):
    src = _photo(tmp_path / "Patients" / "Jane Doe")
    _add(win, monkeypatch, src)
    sc = win.scene
    assert not sc.face_stored(0) and not sc.face_is_locked(0)   # the defaults
    sc.get_face_item(0).setPos(12.0, -4.0)
    win._rotation_spin.setValue(7.5)
    _click(win, 0, 1)                                           # hide
    win._active_ws.add_curve(closed_diamond())
    doc = tmp_path / "design.gdraw"
    assert win._do_save(str(doc))
    assert _front_state(doc)["images"] == []

    win._open_gdraw(str(doc), remember=False)
    sc = win.scene
    assert sc.face_count() == 1 and sc.face_path(0) == src
    assert (sc.face_scene_pos(0), sc.face_rotation(0)) == ((12.0, -4.0), 7.5)
    assert not sc.face_visible(0) and not sc.face_is_locked(0)
    assert win._face_tree.topLevelItem(0).text(0) == "patient_jane_front.png"


def test_on_another_computer_it_is_listed_and_located(win, tmp_path, monkeypatch):
    src = _photo(tmp_path / "photos")
    _add(win, monkeypatch, src)
    win._apply_calibration(8.0, 0)
    win.scene.get_face_item(0).setPos(5.0, 6.0)
    win._active_ws.add_curve(closed_diamond())
    doc = tmp_path / "design.gdraw"
    assert win._do_save(str(doc))

    another_computer(monkeypatch, tmp_path)
    win._open_gdraw(str(doc), remember=False)
    assert win.scene.face_count() == 0
    assert win._face_tree.topLevelItem(0).text(0) == \
        "Reference 1 — not on this computer"            # never its name
    assert "not on this computer" in win._unshown_note()
    assert win._locate_img_btn.isEnabled()

    moved = _photo(tmp_path / "here", "front.png")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (moved, "")))
    win._locate_img_btn.click()
    sc = win.scene
    assert sc.face_count() == 1 and win._active_ws.unshown_faces == []
    assert sc.face_calibration(0) == 8.0 and sc.face_scene_pos(0) == (5.0, 6.0)
    assert links.find(sc.face_link(0)) == moved          # remembered here now
    assert not win._dirty                                # the file is unchanged


def test_an_unshown_image_is_kept_until_removed(win, tmp_path, monkeypatch):
    _add(win, monkeypatch, _photo(tmp_path / "photos"))
    win._active_ws.add_curve(closed_diamond())
    doc = tmp_path / "design.gdraw"
    assert win._do_save(str(doc))
    another_computer(monkeypatch, tmp_path)
    win._open_gdraw(str(doc), remember=False)
    assert win._do_save(str(doc))                        # carried as it came
    assert len(_front_state(doc)["faces"]) == 1
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._remove_img_btn.click()
    assert win._face_tree.topLevelItemCount() == 0
    assert win._do_save(str(doc))
    assert _front_state(doc)["faces"] == []


def test_storing_asks_first_and_the_file_then_holds_the_image(win, tmp_path,
                                                              monkeypatch):
    _add(win, monkeypatch, _photo(tmp_path / "photos", "face.png"))
    asked = _answer(monkeypatch, "Cancel")
    _click(win, 0, 3)
    assert asked == ["Store face.png in the design?"]
    assert not win.scene.face_stored(0)

    _answer(monkeypatch, "Store in Design", tick=True)
    _click(win, 0, 3)
    assert win.scene.face_stored(0)
    assert win._prefs["prompt_store_image"] is False      # Don't ask again
    win._active_ws.add_curve(closed_diamond())
    doc = tmp_path / "design.gdraw"
    assert win._do_save(str(doc))
    assert _front_state(doc)["images"] == ["images/front_0_face.png"]

    # Kept on this computer only again: no question, the file it came from.
    src = win.scene.face_path(0)
    _click(win, 0, 3)
    assert not win.scene.face_stored(0) and win.scene.face_path(0) == src


def test_not_asking_again_stores_at_once(win, tmp_path, monkeypatch):
    win._prefs["prompt_store_image"] = False
    _add(win, monkeypatch, _photo(tmp_path / "photos"))
    _click(win, 0, 3)                     # the guard fails any message box
    assert win.scene.face_stored(0)


def test_unstoring_the_only_copy_saves_one_first(win, tmp_path, monkeypatch):
    src = _photo(tmp_path / "theirs", "face.png")
    doc = tmp_path / "from_a_colleague.gdraw"
    save_gdraw({"front": {"face_images": [FaceImage(stored=True, path=src)]}},
               str(doc))
    win._open_gdraw(str(doc), remember=False)
    assert win.scene.face_stored(0)
    _answer(monkeypatch, "Cancel")
    _click(win, 0, 3)
    assert win.scene.face_stored(0)                       # declined: still stored

    copy = tmp_path / "mine" / "face.png"
    copy.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(copy), "")))
    asked = _answer(monkeypatch, "Save Copy…")
    _click(win, 0, 3)
    assert asked == ["face.png is stored only inside this design."]
    assert copy.read_bytes() == open(src, "rb").read()
    sc = win.scene
    assert not sc.face_stored(0) and sc.face_path(0) == str(copy)
    assert links.find(sc.face_link(0)) == str(copy)
    assert win._do_save(str(doc))
    assert _front_state(doc)["images"] == []


def test_a_locked_image_keeps_its_place_turn_and_scale(win, tmp_path, monkeypatch):
    _add(win, monkeypatch, _photo(tmp_path / "photos"))
    # A new image starts unlocked, to be placed, turned and calibrated.
    assert win._rotation_spin.isEnabled() and win._pxmm_spin.isEnabled()
    _click(win, 0, 2)
    assert win.scene.face_is_locked(0)
    assert not win._rotation_spin.isEnabled() and not win._pxmm_spin.isEnabled()
    tool = win._active_ws.calib_tool
    tool.start(win.scene)
    tool.handle_press(QPointF(0, 0), win.scene)
    assert not tool.active                                # refused at once
    assert "is locked" in win._status.currentMessage()

    _click(win, 0, 2)
    assert win._rotation_spin.isEnabled() and win._pxmm_spin.isEnabled()
    tool.start(win.scene)
    tool.handle_press(QPointF(0, 0), win.scene)
    assert tool.active                                    # waits for the second
    tool.cancel(win.scene)


def test_a_hidden_image_is_found_by_no_click(win, tmp_path, monkeypatch):
    _add(win, monkeypatch, _photo(tmp_path / "photos"))
    assert win.scene.face_index_at(QPointF(0, 0)) == 0
    _click(win, 0, 1)
    assert not win.scene.get_face_item(0).isVisible()
    assert win.scene.face_index_at(QPointF(0, 0)) is None


def test_the_autosave_holds_no_unstored_image(win, tmp_path, monkeypatch):
    _add(win, monkeypatch, _photo(tmp_path / "photos"))
    win._active_ws.add_curve(closed_diamond())
    win._do_autosave()
    [rec] = (tmp_path / "autosave").glob("recovery-*.gdraw")
    assert _front_state(rec)["images"] == []


def test_preferences_turn_the_question_back_on(win):
    win._prefs["prompt_store_image"] = False
    dlg = app_mod.SettingsDialog({**win._prefs}, win)
    assert not dlg._prompt_store_chk.isChecked()
    dlg._prompt_store_chk.setChecked(True)
    assert dlg.to_prefs()["prompt_store_image"] is True
    dlg.deleteLater()


def test_clearing_the_image_cache_keeps_the_open_design_s_images(
        win, tmp_path, monkeypatch, cache_root):
    for name in ("one", "two"):
        src = _photo(tmp_path / name, f"{name}.png")
        doc = tmp_path / f"{name}.gdraw"
        save_gdraw({"front": {"face_images": [FaceImage(stored=True, path=src)]}},
                   str(doc))
        win._open_gdraw(str(doc), remember=False)   # "two" stays open
    shown = win.scene.face_path(0)
    assert gdraw_mod.image_cache_size() > 0
    dlg = app_mod.SettingsDialog({**win._prefs}, win,
                                 images_in_use=win._images_in_use)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg._clear_cache_btn.click()
    left = [p for p in cache_root.rglob("*") if p.is_file()]
    assert [str(p) for p in left] == [shown]       # one.png's copy is gone
    # The design open saves its image whole from the copy kept.
    assert win._do_save(str(tmp_path / "copy.gdraw"))
    assert _front_state(tmp_path / "copy.gdraw")["images"] == ["images/front_0_two.png"]
    dlg.deleteLater()


def test_every_dock_tab_fits_the_dock_at_its_least_width(win, tmp_path, monkeypatch):
    """Unwrapped, the Canvas tab's sentence for no image made the tab 430 px
    wide against the dock's 348, and it scrolled sideways."""
    win.show()                  # a hidden window's layouts keep stale sizes
    room = (win._prop_dock.minimumWidth()
            - win.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))

    def too_wide():
        tabs, out = win._side_tabs, []
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)      # a hidden page keeps its old sizes
            QApplication.processEvents()
            page = tabs.widget(i)
            inner = page.widget() if isinstance(page, QScrollArea) else page
            if inner.minimumSizeHint().width() > room:
                out.append((tabs.tabText(i), inner.minimumSizeHint().width()))
        return out

    win._show_calibration()                       # the no-image sentence
    assert too_wide() == []
    _add(win, monkeypatch, _photo(tmp_path / "photos",
                                  "IMG_20261018_143022_front_view_patient_copy.jpg"))
    win._active_ws.unshown_faces.append(FaceImage(link_id=links.new_id()))
    win._refresh_face_list()
    assert too_wide() == []
