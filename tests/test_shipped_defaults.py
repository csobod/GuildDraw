"""RC3a shipped defaults — starter hinge library seeding + prefs consistency."""
import pytest

from framedraft import library as _lib
from framedraft.canvas.snapping import SNAP_TYPE_KEYS
from framedraft.prefs import DEFAULTS


def test_shipped_snap_types_match_registry():
    # A key drifting from SNAP_TYPES would silently do nothing.
    assert set(DEFAULTS["snap_types"].keys()) == set(SNAP_TYPE_KEYS)


def test_shipped_hinges_exist():
    shipped = sorted(_lib._SHIPPED_HINGES.glob("*.svg"))
    assert len(shipped) >= 1, "starter hinge set missing from resources"


def test_hinge_library_seeds_only_when_empty(tmp_path, monkeypatch):
    user_dir = tmp_path / "hinges"
    monkeypatch.setattr(_lib, "_HINGES_DIR", user_dir)

    # First run: empty user library gets the shipped starter set.
    lib = _lib.HingeLibrary()
    seeded = {e["name"] for e in lib.list_entries()}
    shipped = {p.stem for p in _lib._SHIPPED_HINGES.glob("*.svg")}
    assert seeded == shipped and seeded

    # A maker deletes one entry — it must NOT be resurrected next launch.
    victim = sorted(user_dir.glob("*.svg"))[0]
    victim.unlink()
    _lib.HingeLibrary()
    assert victim.name not in {p.name for p in user_dir.glob("*.svg")}


def test_hinge_seeded_entries_load(tmp_path, monkeypatch):
    user_dir = tmp_path / "hinges"
    monkeypatch.setattr(_lib, "_HINGES_DIR", user_dir)
    lib = _lib.HingeLibrary()
    entries = lib.list_entries()
    curves, dims = lib.load_entry(entries[0]["path"])
    assert curves, "seeded hinge entry should contain geometry"
