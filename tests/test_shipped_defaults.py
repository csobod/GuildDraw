"""RC3a shipped defaults — starter hinge library seeding + prefs consistency."""
from framedraft import library as _lib
from framedraft.canvas.snapping import SNAP_TYPE_KEYS
from framedraft.prefs import DEFAULTS


def test_shipped_snap_types_match_registry():
    # A key drifting from SNAP_TYPES would silently do nothing.
    assert set(DEFAULTS["snap_types"].keys()) == set(SNAP_TYPE_KEYS)


def test_shipped_hinges_exist():
    shipped = sorted(_lib._SHIPPED_HINGES.glob("*.svg"))
    assert len(shipped) >= 1, "starter hinge set missing from resources"


def _patch_dirs(tmp_path, monkeypatch):
    user_dir = tmp_path / "hinges"
    monkeypatch.setattr(_lib, "_HINGES_DIR", user_dir)
    monkeypatch.setattr(_lib, "_SEED_MANIFEST", tmp_path / "seeded.json")
    return user_dir


def test_hinge_library_seeds_empty_library(tmp_path, monkeypatch):
    user_dir = _patch_dirs(tmp_path, monkeypatch)

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


def test_hinge_library_seeds_into_nonempty_library(tmp_path, monkeypatch):
    """GitHub issue #2 — a library with the maker's own hinges must still
    receive the shipped starter set."""
    user_dir = _patch_dirs(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True)
    own = user_dir / "My Custom Hinge.svg"
    own.write_text("<svg/>", encoding="utf-8")

    lib = _lib.HingeLibrary()
    names = {e["name"] for e in lib.list_entries()}
    shipped = {p.stem for p in _lib._SHIPPED_HINGES.glob("*.svg")}
    assert shipped <= names
    assert "My Custom Hinge" in names
    # The user's file was not overwritten.
    assert own.read_text(encoding="utf-8") == "<svg/>"


def test_hinge_seed_collision_skips_but_records(tmp_path, monkeypatch):
    """A user file that shares a shipped name is kept, never overwritten,
    and never retried."""
    user_dir = _patch_dirs(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True)
    shipped_name = sorted(_lib._SHIPPED_HINGES.glob("*.svg"))[0].name
    clash = user_dir / shipped_name
    clash.write_text("<svg/>", encoding="utf-8")

    _lib.HingeLibrary()
    assert clash.read_text(encoding="utf-8") == "<svg/>"

    # Deleting the user's file must not bring the shipped copy back later.
    clash.unlink()
    _lib.HingeLibrary()
    assert not clash.exists()


def test_hinge_seed_rc3a_upgrade_prefills_manifest(tmp_path, monkeypatch):
    """A pre-manifest library that already holds shipped names (RC3a's
    empty-library seed) is treated as fully offered — deletions stick."""
    user_dir = _patch_dirs(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True)
    shipped = sorted(_lib._SHIPPED_HINGES.glob("*.svg"))
    # Simulate RC3a: full set present, no manifest; maker then deleted one.
    for src in shipped[1:]:
        (user_dir / src.name).write_bytes(src.read_bytes())

    _lib.HingeLibrary()
    assert not (user_dir / shipped[0].name).exists(), (
        "deleted shipped hinge resurrected on upgrade")


def test_hinge_seeded_entries_load(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    lib = _lib.HingeLibrary()
    entries = lib.list_entries()
    curves, dims = lib.load_entry(entries[0]["path"])
    assert curves, "seeded hinge entry should contain geometry"
