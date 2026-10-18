"""Shipped defaults — the component library's seed and its migration from
the flat hinge library (2.0), plus prefs consistency."""
import json

import pytest

from framedraft import library as _lib
from framedraft.canvas.snapping import SNAP_TYPE_KEYS
from framedraft.document import Layer
from framedraft.prefs import DEFAULTS

SHIPPED_HINGES = _lib._SHIPPED / "Hinges"


def test_shipped_snap_types_match_registry():
    # A key drifting from SNAP_TYPES would silently do nothing.
    assert set(DEFAULTS["snap_types"].keys()) == set(SNAP_TYPE_KEYS)


def test_shipped_hinges_exist():
    shipped = sorted(SHIPPED_HINGES.glob("*.svg"))
    assert len(shipped) >= 1, "starter hinge set missing from resources"
    assert _lib.SEEDED_FOLDERS == ("Hinges", "Bridges")


def _patch_dirs(tmp_path, monkeypatch):
    """A library of its own; returns the components folder."""
    root = tmp_path / "library"
    monkeypatch.setattr(_lib, "_LIBRARY_DIR", root)
    monkeypatch.setattr(_lib, "_COMPONENTS_DIR", root / "components")
    monkeypatch.setattr(_lib, "_HINGES_DIR", root / "hinges")
    monkeypatch.setattr(_lib, "_SEED_MANIFEST", root / "seeded.json")
    return root / "components"


def _shipped_names():
    return {p.stem for p in SHIPPED_HINGES.glob("*.svg")}


def test_a_new_library_has_hinges_and_bridges(tmp_path, monkeypatch):
    comps = _patch_dirs(tmp_path, monkeypatch)
    lib = _lib.ComponentLibrary()
    assert lib.folders() == ["Hinges", "Bridges"]
    tree = {g["folder"]: {e["name"] for e in g["entries"]} for g in lib.tree()}
    assert tree["Hinges"] == _shipped_names() and tree["Bridges"] == set()

    # A maker deletes a shipped hinge and the Bridges folder: neither comes back.
    victim = sorted((comps / "Hinges").glob("*.svg"))[0]
    victim.unlink()
    lib.delete_folder("Bridges")
    lib = _lib.ComponentLibrary()
    assert not victim.exists()
    assert lib.folders() == ["Hinges"]


def test_shipped_hinges_reach_a_library_with_the_makers_own(tmp_path, monkeypatch):
    """GitHub issue #2 — a library with the maker's own hinges must still
    receive the shipped starter set."""
    comps = _patch_dirs(tmp_path, monkeypatch)
    (comps / "Hinges").mkdir(parents=True)
    own = comps / "Hinges" / "My Custom Hinge.svg"
    own.write_text("<svg/>", encoding="utf-8")

    names = {e["name"] for e in _lib.ComponentLibrary().list_entries()}
    assert _shipped_names() <= names
    assert "My Custom Hinge" in names
    assert own.read_text(encoding="utf-8") == "<svg/>"   # never overwritten


def test_a_seed_collision_is_skipped_but_recorded(tmp_path, monkeypatch):
    """A maker's file that shares a shipped name is kept, never overwritten,
    and never retried."""
    comps = _patch_dirs(tmp_path, monkeypatch)
    (comps / "Hinges").mkdir(parents=True)
    clash = comps / "Hinges" / sorted(SHIPPED_HINGES.glob("*.svg"))[0].name
    clash.write_text("<svg/>", encoding="utf-8")

    _lib.ComponentLibrary()
    assert clash.read_text(encoding="utf-8") == "<svg/>"
    clash.unlink()
    _lib.ComponentLibrary()
    assert not clash.exists()


def test_the_flat_hinge_library_moves_into_hinges(tmp_path, monkeypatch):
    """The migration (2.0): a library holding the shipped set, a shipped hinge
    the maker deleted and the maker's own hinge. Everything moves into Hinges,
    nothing is left behind, and the deleted hinge stays deleted."""
    comps = _patch_dirs(tmp_path, monkeypatch)
    old = tmp_path / "library" / "hinges"
    old.mkdir(parents=True)
    shipped = sorted(SHIPPED_HINGES.glob("*.svg"))
    deleted = shipped[0].name
    for src in shipped[1:]:
        (old / src.name).write_bytes(src.read_bytes())
    (old / "My Own Hinge.svg").write_text("<svg/>", encoding="utf-8")
    manifest = tmp_path / "library" / "seeded.json"
    manifest.write_text(json.dumps([p.name for p in shipped]), encoding="utf-8")

    lib = _lib.ComponentLibrary()
    assert not old.exists()
    hinges = {p.name for p in (comps / "Hinges").glob("*.svg")}
    assert hinges == {p.name for p in shipped[1:]} | {"My Own Hinge.svg"}
    assert deleted not in hinges
    names = set(json.loads(manifest.read_text(encoding="utf-8")))
    assert f"Hinges/{deleted}" in names and "Hinges/" in names
    # The bare names stay too, for GuildDraw 1.3 (see the downgrade test).
    assert {n for n in names if "/" not in n} == {p.name for p in shipped}
    assert lib.folders() == ["Hinges", "Bridges"]      # Bridges is new to it

    _lib.ComponentLibrary()                            # and it stays so
    assert {p.name for p in (comps / "Hinges").glob("*.svg")} == hinges


def test_a_library_from_before_the_manifest_migrates_without_resurrecting(
        tmp_path, monkeypatch):
    """RC3a seeded the full set into an empty library and kept no manifest:
    a shipped name present means the whole set was offered."""
    comps = _patch_dirs(tmp_path, monkeypatch)
    old = tmp_path / "library" / "hinges"
    old.mkdir(parents=True)
    shipped = sorted(SHIPPED_HINGES.glob("*.svg"))
    for src in shipped[1:]:
        (old / src.name).write_bytes(src.read_bytes())

    _lib.ComponentLibrary()
    assert not (comps / "Hinges" / shipped[0].name).exists(), (
        "deleted shipped hinge resurrected on upgrade")


def test_a_seeded_entry_loads_as_component_curves(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    lib = _lib.ComponentLibrary()
    curves, _dims = lib.load_entry(lib.list_entries()[0]["path"])
    assert curves, "seeded hinge entry should contain geometry"
    # The shipped files say HINGE, as every file before 2.0 does.
    assert {c.layer for c in curves} <= {Layer.COMPONENT, Layer.REF}
    assert any(c.layer == Layer.COMPONENT for c in curves)


def test_folders_are_made_named_ordered_and_deleted(tmp_path, monkeypatch):
    comps = _patch_dirs(tmp_path, monkeypatch)
    lib = _lib.ComponentLibrary()
    assert lib.create_folder("Endpieces") == "Endpieces"
    assert lib.folders() == ["Hinges", "Bridges", "Endpieces"]
    lib.set_folder_order(["Endpieces", "Hinges"])
    assert lib.folders() == ["Endpieces", "Hinges", "Bridges"]
    assert lib.rename_folder("Endpieces", "End pieces") == "End pieces"
    assert lib.folders() == ["End pieces", "Hinges", "Bridges"]
    try:
        lib.create_folder("Hinges")
        raise AssertionError("a taken name was accepted")
    except ValueError:
        pass
    assert lib.folder_is_empty("Bridges") and not lib.folder_is_empty("Hinges")
    lib.delete_folder("End pieces")
    assert not (comps / "End pieces").exists()
    assert lib.folders() == ["Hinges", "Bridges"]


def test_an_entry_moves_between_folders_and_names_its_kind(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    lib = _lib.ComponentLibrary()
    path = lib.list_entries()[0]["path"]
    assert lib.kind_of(path) == "Hinges"
    moved = lib.move_entry(path, "Bridges")
    assert lib.kind_of(moved) == "Bridges"
    loose = lib.move_entry(moved, None)
    assert lib.kind_of(loose) is None
    assert any(g["folder"] is None for g in lib.tree())
    saved = lib.save_entry("Bar Bridges", "Saddle", [], [])
    assert lib.kind_of(saved) == "Bar Bridges"         # a new folder, made
    assert "Bar Bridges" in lib.folders()


def _seed_like_1_3(old_dir, manifest):
    """GuildDraw 1.3's seeding rule, as it ran: a shipped name not on the
    manifest is copied into the flat folder."""
    seeded = set(json.loads(manifest.read_text(encoding="utf-8")))
    old_dir.mkdir(parents=True, exist_ok=True)
    for src in SHIPPED_HINGES.glob("*.svg"):
        if src.name not in seeded:
            (old_dir / src.name).write_bytes(src.read_bytes())


def test_a_downgrade_to_1_3_and_back_neither_copies_nor_resurrects(tmp_path, monkeypatch):
    comps = _patch_dirs(tmp_path, monkeypatch)
    _lib.ComponentLibrary()
    victim = sorted((comps / "Hinges").glob("*.svg"))[0]
    victim.unlink()
    _lib.ComponentLibrary()
    old_dir = tmp_path / "library" / "hinges"
    _seed_like_1_3(old_dir, tmp_path / "library" / "seeded.json")   # 1.3 runs
    assert not list(old_dir.glob("*.svg"))
    _lib.ComponentLibrary()                                          # 2.0 again
    names = sorted(p.name for p in (comps / "Hinges").glob("*.svg"))
    assert victim.name not in names and not any("_2" in n for n in names)


@pytest.mark.parametrize("damage", ["truncated", "bom", "missing"])
def test_a_damaged_manifest_brings_nothing_back(tmp_path, monkeypatch, damage):
    comps = _patch_dirs(tmp_path, monkeypatch)
    lib = _lib.ComponentLibrary()
    victim = sorted((comps / "Hinges").glob("*.svg"))[0]
    victim.unlink()
    lib.delete_folder("Bridges")
    manifest = tmp_path / "library" / "seeded.json"
    text = manifest.read_text(encoding="utf-8")
    if damage == "truncated":
        manifest.write_text(text[: len(text) // 2], encoding="utf-8")
    elif damage == "bom":
        manifest.write_text("\ufeff" + text, encoding="utf-8")
    else:
        manifest.unlink()
    lib = _lib.ComponentLibrary()
    assert not victim.exists()
    assert lib.folders() == ["Hinges"]


def test_names_and_folders_the_library_takes(tmp_path, monkeypatch):
    comps = _patch_dirs(tmp_path, monkeypatch)
    assert _lib._safe_filename("con") == "_con"
    assert _lib._safe_filename("abc .") == "abc"
    assert _lib._safe_filename("..") == "component"
    lib = _lib.ComponentLibrary()
    (comps / "Bridges" / "datasheet.pdf").write_bytes(b"%PDF")
    assert not lib.folder_is_empty("Bridges")         # it asks before deleting
