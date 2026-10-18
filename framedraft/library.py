"""
framedraft/library.py — the component library and the drill-pattern library.

Storage layout:
    ~/.guilddraw/library/components/<folder>/<name>.svg
    ~/.guilddraw/library/components/folders.json    the folders' order
    ~/.guilddraw/library/seeded.json                 everything ever shipped
    ~/.guilddraw/library/drills/<name>.json

A component is anything mounted on the posterior that needs a pocket: a
hinge, a bridge, an endpiece, a bridge bar (the COMPONENT layer, HINGE before
2.0). Each entry is a standard GuildDraw SVG saved with save_svg (the
Component workspace's format); the filename stem is the display name. The
maker creates, names and orders the folders, and an entry sits in one of
them. The folder an entry is placed from is the kind its COMPONENT curves
carry (``Curve.component_kind``), so GuildModel can tell a bridge from a hinge.

Two folders are seeded: **Hinges**, with the starter set shipped in
``framedraft/resources/library/components/Hinges``, and **Bridges**, empty.
The manifest records every folder and entry ever offered, folder-relative
("Hinges/", "Hinges/Zoye TH-23 Front.svg"), so new shipped entries reach
existing libraries on upgrade while a folder or an entry the maker deleted
never comes back (GitHub issue #2). Before 2.0 the library was one flat
folder, ``~/.guilddraw/library/hinges/*.svg``, with bare names in the
manifest; ``_migrate_hinges`` moves it into Hinges once, keeping that rule.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import pathlib
import re
import shutil

_LIBRARY_DIR    = pathlib.Path.home() / ".guilddraw" / "library"
_COMPONENTS_DIR = _LIBRARY_DIR / "components"
_HINGES_DIR     = _LIBRARY_DIR / "hinges"       # before 2.0; migrated
_DRILLS_DIR     = _LIBRARY_DIR / "drills"
_SHIPPED        = pathlib.Path(__file__).parent / "resources" / "library" / "components"
_SEED_MANIFEST  = _LIBRARY_DIR / "seeded.json"
_ORDER_FILE     = "folders.json"                # in the components folder

# The folders a library starts with, in this order. Each is created once.
SEEDED_FOLDERS = ("Hinges", "Bridges")
# The folder the flat library of hinges before 2.0 moves into.
_MIGRATED_FOLDER = "Hinges"


# Windows device names, which open the device whatever folder they are in.
_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


def _safe_filename(name: str, fallback: str = "component") -> str:
    """Strip characters that are illegal in Windows/macOS/Linux filenames,
    with leading and trailing dots and spaces (Windows drops them, so "abc ."
    named a different file there), and keep a device name from naming the
    device."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if safe.split(".")[0].upper() in _DEVICE_NAMES:
        safe = "_" + safe
    return safe or fallback


def _entry_date(p: pathlib.Path) -> str:
    try:
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return "?"


def _unique_path(folder: pathlib.Path, stem: str, suffix: str = ".svg") -> pathlib.Path:
    """*folder*/*stem*.svg, or the first free *stem*_2, _3, … beside it."""
    path = folder / f"{stem}{suffix}"
    i = 2
    while path.exists():
        path = folder / f"{stem}_{i}{suffix}"
        i += 1
    return path


class ComponentLibrary:
    """The component library: folders of SVG entries under
    ~/.guilddraw/library/components/."""

    def __init__(self) -> None:
        _COMPONENTS_DIR.mkdir(parents=True, exist_ok=True)
        self._migrate_hinges()
        self._seed_shipped()

    # ------------------------------------------------------------------
    # The manifest, the migration and the seed
    # ------------------------------------------------------------------

    @staticmethod
    def _read_manifest() -> set | None:
        """The names ever offered, or None when there is no readable manifest
        (utf-8-sig: a byte-order mark an editor added made it unreadable)."""
        try:
            data = json.loads(_SEED_MANIFEST.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return {n for n in data if isinstance(n, str)} if isinstance(data, list) else None

    @staticmethod
    def _write_manifest(names: set) -> None:
        """Write the manifest whole or not at all: a temporary file, then a
        rename. Each starter hinge's name is kept bare beside its folder-
        relative one: GuildDraw 1.3 reads the bare names, and a maker who
        opened 1.3 again got the whole starter set back in the old folder,
        which 2.0 then moved in as copies, deleted ones included."""
        names = set(names)
        names |= {n.split("/", 1)[1] for n in names
                  if n.startswith(f"{_MIGRATED_FOLDER}/") and n.count("/") == 1
                  and not n.endswith("/")}
        tmp = _SEED_MANIFEST.with_name(_SEED_MANIFEST.name + ".tmp")
        tmp.write_text(json.dumps(sorted(names), indent=2), encoding="utf-8")
        os.replace(tmp, _SEED_MANIFEST)

    @staticmethod
    def _shipped(folder: str) -> list[str]:
        d = _SHIPPED / folder
        return sorted(p.name for p in d.glob("*.svg")) if d.is_dir() else []

    def _migrate_hinges(self) -> None:
        """Move the flat library of hinges before 2.0 into the Hinges folder,
        once, leaving nothing behind, and make the manifest's bare names
        folder-relative, so a shipped hinge the maker deleted stays deleted."""
        try:
            manifest = self._read_manifest()
            old_files = (sorted(_HINGES_DIR.glob("*.svg")) if _HINGES_DIR.is_dir()
                         else [])
            # A manifest from before 2.0 holds bare names only; 2.0's keeps
            # them beside the folder-relative ones, with the folder's mark.
            old_format = (manifest is not None
                          and f"{_MIGRATED_FOLDER}/" not in manifest
                          and any("/" not in n for n in manifest))
            if not old_files and not old_format:
                if _HINGES_DIR.is_dir() and not any(_HINGES_DIR.iterdir()):
                    _HINGES_DIR.rmdir()               # an empty folder: gone too
                return
            if manifest is None:
                # No manifest: RC3a seeded the full set into an EMPTY library,
                # so a shipped name present means the whole set was offered.
                shipped = self._shipped(_MIGRATED_FOLDER)
                present = {p.name for p in old_files}
                manifest = set(shipped) if present & set(shipped) else set()
            manifest = {n if "/" in n else f"{_MIGRATED_FOLDER}/{n}" for n in manifest}
            manifest.add(f"{_MIGRATED_FOLDER}/")
            # A file where the folder should be (whatever put it there) must
            # not keep the old hinges out of sight: the first free name.
            dest, i = _COMPONENTS_DIR / _MIGRATED_FOLDER, 2
            while dest.exists() and not dest.is_dir():
                dest, i = _COMPONENTS_DIR / f"{_MIGRATED_FOLDER}_{i}", i + 1
            dest.mkdir(parents=True, exist_ok=True)
            for f in old_files:
                shutil.move(str(f), str(_unique_path(dest, f.stem)))
            self._write_manifest(manifest)
            if _HINGES_DIR.is_dir() and not any(_HINGES_DIR.iterdir()):
                _HINGES_DIR.rmdir()
        except OSError:
            pass   # best-effort; the old folder is tried again next time

    def _seed_shipped(self) -> None:
        """Create the seeded folders and copy shipped entries the maker has
        never been offered. A folder or an entry on the manifest is never
        offered again, so deletions stick; a shipped name that collides with
        the maker's own file is skipped but still recorded. A shipped entry
        whose folder the maker deleted waits, unrecorded, for a folder of
        that name."""
        try:
            manifest = self._read_manifest()
            if manifest is None and self._folder_dirs():
                # No readable manifest, in a library that has folders: the
                # manifest is lost or damaged, or the library was copied in
                # without it. No seeded folder comes back, and in each folder
                # one starter entry present means the set was offered, so one
                # the maker deleted stays deleted (RC3a's rule, per folder); a
                # folder with none of them gets the set (GitHub issue #2).
                manifest = {f"{f}/" for f in SEEDED_FOLDERS}
                for f in SEEDED_FOLDERS:
                    shipped = self._shipped(f)
                    if any((_COMPONENTS_DIR / f / n).exists() for n in shipped):
                        manifest |= {f"{f}/{n}" for n in shipped}
            manifest = manifest or set()
            before = set(manifest)
            for folder in SEEDED_FOLDERS:
                fdir = _COMPONENTS_DIR / folder
                try:
                    if f"{folder}/" not in manifest:
                        fdir.mkdir(exist_ok=True)
                        manifest.add(f"{folder}/")
                    if not fdir.is_dir():
                        continue
                    for name in self._shipped(folder):
                        key = f"{folder}/{name}"
                        if key in manifest:
                            continue
                        if not (fdir / name).exists():
                            shutil.copyfile(_SHIPPED / folder / name, fdir / name)
                        manifest.add(key)
                except OSError:
                    continue          # this folder only; the others still seed
            if manifest != before or not _SEED_MANIFEST.exists():
                self._write_manifest(manifest)
            # The seeded folders take their places in the order once, as they
            # are made (or moved into, by the migration); the maker's own
            # order is kept from then on.
            order = self._saved_order()
            new = [f for f in SEEDED_FOLDERS
                   if (_COMPONENTS_DIR / f).is_dir() and f not in order]
            if new:
                self.set_folder_order(order + new)
        except OSError:
            pass   # seeding is best-effort; an empty library still works

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    @staticmethod
    def _folder_dirs() -> list[pathlib.Path]:
        try:
            return [p for p in _COMPONENTS_DIR.iterdir()
                    if p.is_dir() and not p.name.startswith(".")]
        except OSError:
            return []

    @staticmethod
    def _saved_order() -> list[str]:
        try:
            order = json.loads((_COMPONENTS_DIR / _ORDER_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [n for n in order if isinstance(n, str)] if isinstance(order, list) else []

    def folders(self) -> list[str]:
        """The folders in the maker's order; any not in it follow, by name."""
        names = {p.name for p in self._folder_dirs()}
        ordered = [n for n in dict.fromkeys(self._saved_order()) if n in names]
        return ordered + sorted(names - set(ordered), key=str.lower)

    def set_folder_order(self, names: list[str]) -> None:
        """Keep *names* as the folders' order; folders it leaves out follow."""
        current = self.folders()
        order = [n for n in dict.fromkeys(names) if n in current]
        order += [n for n in current if n not in order]
        (_COMPONENTS_DIR / _ORDER_FILE).write_text(json.dumps(order, indent=2),
                                                   encoding="utf-8")

    @staticmethod
    def _folder_name(name: str) -> str:
        safe = _safe_filename(name, fallback="")
        if not safe:
            raise ValueError("A folder needs a name.")
        return safe

    def create_folder(self, name: str) -> str:
        """Create a folder at the end of the order; its name as stored."""
        safe = self._folder_name(name)
        path = _COMPONENTS_DIR / safe
        if path.exists():
            raise ValueError(f"'{safe}' already exists in the library.")
        path.mkdir()
        self.set_folder_order(self.folders() + [safe])
        return safe

    def rename_folder(self, old: str, new: str) -> str:
        safe = self._folder_name(new)
        if safe == old:
            return safe
        if (_COMPONENTS_DIR / safe).exists():
            raise ValueError(f"'{safe}' already exists in the library.")
        order = [safe if n == old else n for n in self.folders()]
        (_COMPONENTS_DIR / old).rename(_COMPONENTS_DIR / safe)
        self.set_folder_order(order)
        return safe

    def delete_folder(self, name: str) -> None:
        """Delete a folder and everything in it (the caller asks first)."""
        shutil.rmtree(_COMPONENTS_DIR / name, ignore_errors=True)
        self.set_folder_order([n for n in self.folders() if n != name])

    def folder_is_empty(self, name: str) -> bool:
        """True when the folder holds nothing at all: a datasheet or a
        subfolder the maker keeps there counts, so deleting it asks."""
        try:
            return not any((_COMPONENTS_DIR / name).iterdir())
        except OSError:
            return True

    # ------------------------------------------------------------------
    # Entries
    # ------------------------------------------------------------------

    @staticmethod
    def is_seeded_folder(name: str) -> bool:
        """True for a folder GuildDraw made (Hinges, Bridges): deleted, it
        never comes back, nor do its starter entries."""
        return name in SEEDED_FOLDERS

    @staticmethod
    def _entries_in(d: pathlib.Path) -> list[dict]:
        return [{"name": p.stem, "path": str(p), "date": _entry_date(p)}
                for p in sorted(d.glob("*.svg"), key=lambda f: f.stem.lower())]

    def tree(self) -> list[dict]:
        """``[{"folder": name, "entries": [...]}, …]`` in the folders' order,
        then the entries outside any folder under ``"folder": None``; each
        entry is ``{"name", "path", "date"}``."""
        out = [{"folder": f, "entries": self._entries_in(_COMPONENTS_DIR / f)}
               for f in self.folders()]
        loose = self._entries_in(_COMPONENTS_DIR)
        if loose:
            out.append({"folder": None, "entries": loose})
        return out

    def list_entries(self) -> list[dict]:
        """Every entry, folder by folder."""
        return [e for group in self.tree() for e in group["entries"]]

    @staticmethod
    def kind_of(path: str) -> str | None:
        """The top-level folder *path* sits in, as the maker named it: the
        kind a component placed from it carries. None outside any folder."""
        # Absolute, not resolved: a folder that is a link (a synced one, say)
        # resolved elsewhere, and its entries lost their kind.
        try:
            rel = pathlib.Path(os.path.abspath(path)).relative_to(
                os.path.abspath(_COMPONENTS_DIR))
        except ValueError:
            return None
        return rel.parts[0] if len(rel.parts) > 1 else None

    def entry_path(self, folder: str | None, name: str) -> pathlib.Path:
        """Where an entry *name* in *folder* is kept, taken or not."""
        d = _COMPONENTS_DIR / self._folder_name(folder) if folder else _COMPONENTS_DIR
        return d / f"{_safe_filename(name)}.svg"

    def save_entry(self, folder: str | None, name: str, curves: list,
                   dims: list, replace: bool = False) -> str:
        """Write *curves* + *dims* as an entry in *folder* (created when it
        does not exist yet). Returns the saved path. A taken name gets _2, _3,
        unless *replace*, which writes over the entry of that name."""
        from .export.svg import save_svg
        from .document import Calibration, MirrorAxis, FormingMetadata, MachinedBridge

        if folder:
            folder = self._folder_name(folder)
            if not (_COMPONENTS_DIR / folder).is_dir():
                self.create_folder(folder)
            d = _COMPONENTS_DIR / folder
        else:
            d = _COMPONENTS_DIR
        path = (d / f"{_safe_filename(name)}.svg" if replace
                else _unique_path(d, _safe_filename(name)))
        save_svg(
            curves          = [c for c in curves if not c.mirrored],
            path            = str(path),
            calibration     = Calibration(),
            mirror          = MirrorAxis(enabled=False),
            forming         = FormingMetadata(),
            machined_bridge = MachinedBridge(),
            dims            = dims or [],
        )
        return str(path)

    def load_entry(self, path: str) -> tuple[list, list]:
        """Load entry at *path*.  Returns (curves, dims)."""
        from .export.svg import load_svg
        data = load_svg(path)
        return data.get("curves", []), data.get("dims", [])

    def delete_entry(self, path: str) -> None:
        try:
            pathlib.Path(path).unlink()
        except OSError:
            pass

    def rename_entry(self, old_path: str, new_name: str) -> str:
        """Rename *old_path* to *new_name* in its folder.  Returns the new path
        string.  Raises ValueError if the new name is already taken."""
        old = pathlib.Path(old_path)
        safe = _safe_filename(new_name)
        new_path = old.parent / f"{safe}.svg"
        if new_path.exists() and new_path != old:
            raise ValueError(f"'{safe}' already exists in the library.")
        old.rename(new_path)
        return str(new_path)

    def move_entry(self, path: str, folder: str | None) -> str:
        """Move an entry into *folder* (None: outside any), under the same
        name or the first free one beside it. Returns the new path."""
        src = pathlib.Path(path)
        d = _COMPONENTS_DIR / folder if folder else _COMPONENTS_DIR
        if src.parent.resolve() == d.resolve():
            return str(src)
        dest = _unique_path(d, src.stem)
        shutil.move(str(src), str(dest))
        return str(dest)


class DrillLibrary:
    """Local drill-hole-pattern library backed by JSON files in
    ~/.guilddraw/library/drills/.

    A pattern is a list of holes, each ``{"dx", "dy", "dia"}`` where (dx, dy) is
    the hole's offset from the lens boxing center in scene mm (y-down) and *dia*
    is the hole diameter (mm).  Storing offsets from the boxing center — the OMA
    datum — lets one pattern re-apply to any lens by re-centering.

    Version 2 (GuildDraw 1.3) measures dx on the OD lens, positive toward the
    nose, so a pattern lands the same way on a frame drawn on either side.
    Version 1 files hold dx as drawn, and are placed as drawn; ``load_entry``
    tells the caller which (``od_frame``)."""

    def __init__(self) -> None:
        _DRILLS_DIR.mkdir(parents=True, exist_ok=True)

    def list_entries(self) -> list[dict]:
        entries = []
        for p in sorted(_DRILLS_DIR.glob("*.json"), key=lambda f: f.stem.lower()):
            try:
                ts   = p.stat().st_mtime
                date = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except OSError:
                date = "?"
            entries.append({"name": p.stem, "path": str(p), "date": date})
        return entries

    def save_entry(self, name: str, holes: list[dict]) -> str:
        """Write *holes* (list of {dx,dy,dia}) to a new JSON entry."""
        safe = _safe_filename(name, "pattern")
        path = _DRILLS_DIR / f"{safe}.json"
        if path.exists():
            i = 2
            while (_DRILLS_DIR / f"{safe}_{i}.json").exists():
                i += 1
            path = _DRILLS_DIR / f"{safe}_{i}.json"
        payload = {"version": 2, "holes": [
            {"dx": float(h["dx"]), "dy": float(h["dy"]), "dia": float(h["dia"])}
            for h in holes
        ]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(path)

    def load_entry(self, path: str) -> list[dict]:
        """Return the list of holes ({dx,dy,dia}) stored at *path*. A hole
        whose numbers are not finite (JSON's NaN, "inf") is left out: one
        drew nothing and failed every readiness check after it."""
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
        od_frame = int(data.get("version", 1)) >= 2
        holes = []
        for h in data.get("holes", []):
            try:
                hole = {"dx": float(h.get("dx", 0.0)), "dy": float(h.get("dy", 0.0)),
                        "dia": float(h.get("dia", 1.4)), "od_frame": od_frame}
            except (TypeError, ValueError, AttributeError):
                continue
            if all(math.isfinite(hole[k]) for k in ("dx", "dy", "dia")) and hole["dia"] > 0:
                holes.append(hole)
        return holes

    def delete_entry(self, path: str) -> None:
        try:
            pathlib.Path(path).unlink()
        except OSError:
            pass

    def rename_entry(self, old_path: str, new_name: str) -> str:
        safe     = _safe_filename(new_name, "pattern")
        new_path = _DRILLS_DIR / f"{safe}.json"
        if new_path.exists() and new_path != pathlib.Path(old_path):
            raise ValueError(f"'{safe}' already exists in the drill library.")
        pathlib.Path(old_path).rename(new_path)
        return str(new_path)
