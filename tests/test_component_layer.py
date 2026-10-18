"""HINGE becomes COMPONENT (2.0, HANDOFF-GuildDraw-2026-10-17, item 3).

The layer carries anything mounted on the posterior that needs a pocket.
Every old file keeps working: a .gdraw, a library entry and a DXF that say
HINGE all read as COMPONENT, and only COMPONENT is written. The Component
tab is written as component.svg. A component placed from the library
carries its folder's name as its kind ("component_kind" in the file), which
copy, mirror, undo and the library keep, and a curve that leaves the layer
drops."""
import gc
import json
import zipfile
from xml.etree import ElementTree as ET

import ezdxf
import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft import library as lib_mod
from framedraft.canvas.items import CurveItem
from framedraft.document import (
    ALL_LAYER_NAMES, LAYER_ALIASES, WORKSPACE_LAYERS, Layer,
)
from helpers import circle, closed_diamond

_SVG_NS = "http://www.w3.org/2000/svg"


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


def _select(win, layers=None):
    win.scene.clearSelection()
    for it in win.scene.items():
        if isinstance(it, CurveItem) and (layers is None or it.curve.layer in layers):
            it.setSelected(True)


def _svg(state: dict) -> str:
    return ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">'
            f'<metadata>{json.dumps(state)}</metadata></svg>')


def _state(zf, member):
    meta = ET.fromstring(zf.read(member)).find(f"{{{_SVG_NS}}}metadata")
    return json.loads(meta.text)


_OLD_POCKET = {"kind": "circle", "layer": "HINGE", "closed": True, "radius": 2.0,
               "nodes": [{"x": 0.0, "y": 0.0}]}


# ── The layer and its alias ────────────────────────────────────────────────

def test_hinge_reads_as_component_and_only_component_is_written():
    assert Layer("HINGE") is Layer.COMPONENT
    assert LAYER_ALIASES == {"HINGE": "COMPONENT"}
    assert "HINGE" in ALL_LAYER_NAMES and "COMPONENT" in ALL_LAYER_NAMES
    assert "HINGE" not in {layer.value for layer in Layer}
    assert set(WORKSPACE_LAYERS) == {"front", "temple_r", "temple_l", "component"}
    assert Layer.COMPONENT in WORKSPACE_LAYERS["front"]


def test_an_old_gdraw_opens_with_its_hinge_tab_as_the_component_tab(win, tmp_path):
    path = tmp_path / "old.gdraw"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"version": 1, "active_tab": "hinge"}))
        zf.writestr("front.svg", _svg({
            "curves": [dict(_OLD_POCKET, nodes=[{"x": 30.0, "y": 0.0}])],
            "layers": {"HINGE": {"visible": False}}}))
        zf.writestr("hinge.svg", _svg({"curves": [_OLD_POCKET]}))
    assert win._open_gdraw(str(path), remember=False) == "ok"
    front, comp = win._workspaces[0], win._workspaces[3]
    assert comp.workspace_type == "component" and win._active_ws is comp
    assert [c.layer for c in comp.doc_curves] == [Layer.COMPONENT]
    assert [c.layer for c in front.doc_curves] == [Layer.COMPONENT]
    assert not front.scene.is_layer_visible(Layer.COMPONENT)   # its flag too

    out = tmp_path / "new.gdraw"
    win._do_save_gdraw(str(out))
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "component.svg" in names and "hinge.svg" not in names
        assert json.loads(zf.read("manifest.json"))["active_tab"] == "component"
        assert [c["layer"] for c in _state(zf, "component.svg")["curves"]] == ["COMPONENT"]
        front_state = _state(zf, "front.svg")
        assert "HINGE" not in json.dumps(front_state)


def test_a_library_svg_and_a_dxf_saying_hinge_read_as_component(tmp_path):
    from framedraft.export.dxf_import import import_dxf
    from framedraft.export.svg import load_svg
    p = tmp_path / "entry.svg"
    p.write_text(_svg({"curves": [_OLD_POCKET]}))
    assert [c.layer for c in load_svg(str(p))["curves"]] == [Layer.COMPONENT]

    doc = ezdxf.new("R2000")
    doc.modelspace().add_circle((0, 0), 2.0, dxfattribs={"layer": "HINGE"})
    dxf = tmp_path / "old.dxf"
    doc.saveas(dxf)
    curves, _notes = import_dxf(str(dxf), Layer.REF, "temple_r")
    assert [c.layer for c in curves] == [Layer.COMPONENT]


def test_an_svg_layer_named_hinge_reads_as_component(tmp_path):
    from framedraft.export.svg_import import import_svg
    p = tmp_path / "drawing.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" '
                 'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
                 'width="100mm" height="100mm" viewBox="0 0 100 100">'
                 '<g inkscape:label="HINGE"><circle cx="10" cy="10" r="2"/></g></svg>')
    curves, _notes = import_svg(str(p), Layer.REF, "front")
    assert [c.layer for c in curves] == [Layer.COMPONENT]


def test_the_dxf_writes_component_and_the_batch_names_the_tab(tmp_path):
    from framedraft.export.batch import WORKSPACE_SUFFIXES
    from framedraft.export.dxf import export_dxf
    path = tmp_path / "c.dxf"
    export_dxf([circle(0, 0, 2, layer=Layer.COMPONENT)], str(path))
    assert [e.dxf.layer for e in ezdxf.readfile(str(path)).modelspace()] == ["COMPONENT"]
    assert WORKSPACE_SUFFIXES["component"] == "component"


def test_a_layer_color_and_the_catalog_choice_saved_as_hinge_carry_over(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(json.dumps({
        "theme": {"light": {"layer.HINGE": "#123456"}},
        "catalog_pdf": {"front_layers": ["OUTLINE", "HINGE"]}}))
    p = prefs_mod.load()
    assert p["theme"]["light"] == {"layer.COMPONENT": "#123456"}
    assert p["catalog_pdf"]["front_layers"] == ["OUTLINE", "COMPONENT"]


# ── The kind ───────────────────────────────────────────────────────────────

def _place_from_library(win, folder="Hinges"):
    from framedraft.library import ComponentLibrary
    entry = next(e for g in ComponentLibrary().tree() if g["folder"] == folder
                 for e in g["entries"])
    win._refresh_library_panel(select=("entry", entry["path"]))
    win._import_from_library()
    return [c for c in win._active_ws.doc_curves if c.layer == Layer.COMPONENT]


def test_a_component_placed_from_a_folder_carries_its_name(win, tmp_path):
    placed = _place_from_library(win)
    assert placed and {c.component_kind for c in placed} == {"Hinges"}
    path = tmp_path / "kind.gdraw"
    win._do_save_gdraw(str(path))
    with zipfile.ZipFile(path) as zf:
        curves = _state(zf, "front.svg")["curves"]
    comp = [c for c in curves if c["layer"] == "COMPONENT"]
    assert comp and all(c["component_kind"] == "Hinges" for c in comp)
    # "kind" stays the curve's type, which GuildModel's reader takes.
    assert all(c["kind"] in ("line", "spline", "circle", "arc") for c in curves)
    assert not any("component_kind" in c for c in curves if c["layer"] != "COMPONENT")

    win._dirty = False
    win._open_gdraw(str(path), remember=False)
    reopened = [c for c in win._workspaces[0].doc_curves if c.layer == Layer.COMPONENT]
    assert {c.component_kind for c in reopened} == {"Hinges"}


def test_a_component_drawn_by_hand_has_no_kind(win, tmp_path):
    win._active_ws.add_curve(closed_diamond(30, 0, 3, layer=Layer.COMPONENT))
    path = tmp_path / "hand.gdraw"
    win._do_save_gdraw(str(path))
    with zipfile.ZipFile(path) as zf:
        [c] = _state(zf, "front.svg")["curves"]
    assert "component_kind" not in c


def test_copy_mirror_and_undo_keep_the_kind(win):
    placed = _place_from_library(win)
    n = len(placed)
    _select(win, {Layer.COMPONENT})
    win._duplicate_selected()                       # copy
    comps = [c for c in win._active_ws.doc_curves if c.layer == Layer.COMPONENT]
    assert len(comps) == 2 * n and {c.component_kind for c in comps} == {"Hinges"}

    win._undo()
    win._undo()                                     # back to nothing placed
    win._redo()                                     # undo and redo rebuild it
    comps = [c for c in win._active_ws.doc_curves if c.layer == Layer.COMPONENT]
    assert len(comps) == n and {c.component_kind for c in comps} == {"Hinges"}

    for c in comps:                                 # off the axis, for a twin
        for nd in c.nodes:
            nd.x += 40.0
            for h in (nd.cp_in, nd.cp_out):
                if h is not None:
                    h.x += 40.0
        win.scene.refresh_curve(c)
    _select(win, {Layer.COMPONENT})
    win._on_duplicate_mirror()                      # mirror (bake)
    comps = [c for c in win._active_ws.doc_curves if c.layer == Layer.COMPONENT]
    assert len(comps) == 2 * n and {c.component_kind for c in comps} == {"Hinges"}


def test_a_curve_that_leaves_the_layer_drops_its_kind(win):
    placed = _place_from_library(win)
    items = [win.scene._curve_items[id(c)] for c in placed]
    win._move_curve_items_to_layer(items, Layer.REF)
    assert all(c.component_kind is None for c in placed)
    win._move_curve_items_to_layer(items, Layer.COMPONENT)
    assert all(c.component_kind is None for c in placed)   # not resurrected


def test_the_library_keeps_a_kind_through_save_and_load(win, monkeypatch):
    from framedraft.library import ComponentLibrary
    comp_ws = win._workspaces[3]
    win._ws_tab_widget.setCurrentIndex(3)
    QApplication.processEvents()
    c = closed_diamond(0, 0, 3, layer=Layer.COMPONENT)
    c.component_kind = "Bridges"
    comp_ws.add_curve(c)
    monkeypatch.setattr(win, "_ask_library_save", lambda default: ("Saddle", "Bridges"))
    win._save_to_library()
    [entry] = [e for g in ComponentLibrary().tree() if g["folder"] == "Bridges"
               for e in g["entries"]]
    curves, _dims = ComponentLibrary().load_entry(entry["path"])
    assert [k.component_kind for k in curves] == ["Bridges"]


# ── The library panel ──────────────────────────────────────────────────────

def _tree_rows(win):
    tree = win._lib_tree
    rows = []
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        rows.append(top.text(0))
        rows += ["  " + top.child(j).text(0).split("  ·")[0]
                 for j in range(top.childCount())]
    return rows


def test_the_panel_is_a_tree_of_folders(win):
    rows = _tree_rows(win)
    assert rows[0] == "Hinges" and "Bridges" in rows
    assert rows.index("Bridges") > rows.index("Hinges")
    assert all(r.startswith("  ") for r in rows[1:rows.index("Bridges")])
    assert win._lib_component_actions.isHidden()             # front tab
    win._ws_tab_widget.setCurrentIndex(3)
    QApplication.processEvents()
    assert not win._lib_component_actions.isHidden()


def test_folders_are_made_renamed_moved_into_and_deleted(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from framedraft.library import ComponentLibrary
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Endpieces", True))
    win._new_library_folder()
    assert ComponentLibrary().folders()[-1] == "Endpieces"
    assert win._lib_selected() == ("folder", "Endpieces")

    entry = ComponentLibrary().tree()[0]["entries"][0]["path"]
    win._move_library_entry(entry, "Endpieces")
    sel = win._lib_selected()
    assert sel[0] == "entry" and ComponentLibrary.kind_of(sel[1]) == "Endpieces"

    win._refresh_library_panel(select=("folder", "Endpieces"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("End pieces", True))
    win._rename_library_entry()
    assert "End pieces" in ComponentLibrary().folders()

    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.No)
    win._refresh_library_panel(select=("folder", "End pieces"))
    win._delete_library_entry()                     # not empty: asks, No
    assert asked and "End pieces" in ComponentLibrary().folders()

    win._refresh_library_panel(select=("folder", "Bridges"))
    asked.clear()
    win._delete_library_entry()                     # a starter folder: asks
    assert asked and "will not come back" in asked[0][2]
    assert "Bridges" in ComponentLibrary().folders()
    assert asked[0][4] == QMessageBox.StandardButton.No      # No is the default

    ComponentLibrary().create_folder("Spare")
    win._refresh_library_panel(select=("folder", "Spare"))
    asked.clear()
    win._delete_library_entry()                     # empty and the maker's own
    assert not asked and "Spare" not in ComponentLibrary().folders()

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._refresh_library_panel(select=("folder", "Bridges"))
    win._delete_library_entry()
    assert "Bridges" not in ComponentLibrary().folders()

    win._reorder_library_folders(["End pieces", "Hinges"])
    assert _tree_rows(win)[0] == "End pieces"
