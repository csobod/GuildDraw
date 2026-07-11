"""
framedraft/library.py — Personal hinge pocket library.

Storage layout:
    ~/.guilddraw/library/hinges/<name>.svg

Each entry is a standard GuildDraw SVG saved with save_svg (hinge pocket
workspace format).  The filename stem (minus .svg) is the display name.

A starter set ships in ``framedraft/resources/library/hinges``. A manifest
(``~/.guilddraw/library/seeded.json``) records every shipped filename ever
offered, so new shipped hinges reach existing libraries on upgrade while a
maker who deletes a shipped hinge never has it resurrected (GitHub issue #2 —
the old rule "seed only an empty library" meant upgraders with their own
hinges never received the starter set at all).
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import shutil

_HINGES_DIR = pathlib.Path.home() / ".guilddraw" / "library" / "hinges"
_DRILLS_DIR = pathlib.Path.home() / ".guilddraw" / "library" / "drills"
_SHIPPED_HINGES = pathlib.Path(__file__).parent / "resources" / "library" / "hinges"
_SEED_MANIFEST  = pathlib.Path.home() / ".guilddraw" / "library" / "seeded.json"


def _safe_filename(name: str) -> str:
    """Strip characters that are illegal in Windows/macOS/Linux filenames."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    return safe or "hinge"


class HingeLibrary:
    """Local hinge pocket library backed by SVG files in ~/.guilddraw/library/hinges/."""

    def __init__(self) -> None:
        _HINGES_DIR.mkdir(parents=True, exist_ok=True)
        self._seed_shipped()

    @staticmethod
    def _seed_shipped() -> None:
        """Copy shipped starter hinges the user has never been offered.

        The manifest lists every shipped filename ever seeded; entries on it
        are never copied again, so deletions stick. A shipped name that
        collides with a user's own file is skipped but still recorded."""
        try:
            if not _SHIPPED_HINGES.is_dir():
                return
            shipped = sorted(p.name for p in _SHIPPED_HINGES.glob("*.svg"))
            if not shipped:
                return
            try:
                seeded = set(json.loads(
                    _SEED_MANIFEST.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                # No manifest yet. RC3a seeded the full set into an EMPTY
                # library — if any shipped name is already present, assume
                # that happened and mark the whole set as offered so hinges
                # the maker deleted since are not resurrected.
                if any((_HINGES_DIR / name).exists() for name in shipped):
                    seeded = set(shipped)
                else:
                    seeded = set()
            new = [n for n in shipped if n not in seeded]
            for name in new:
                dest = _HINGES_DIR / name
                if not dest.exists():   # collision with a user file → skip
                    shutil.copyfile(_SHIPPED_HINGES / name, dest)
                seeded.add(name)
            if new or not _SEED_MANIFEST.exists():
                _SEED_MANIFEST.write_text(
                    json.dumps(sorted(seeded), indent=2), encoding="utf-8")
        except OSError:
            pass   # seeding is best-effort; an empty library still works

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_entries(self) -> list[dict]:
        """Return list of dicts (name, path, date) sorted alphabetically."""
        entries = []
        for p in sorted(_HINGES_DIR.glob("*.svg"), key=lambda f: f.stem.lower()):
            try:
                ts   = p.stat().st_mtime
                date = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except OSError:
                date = "?"
            entries.append({"name": p.stem, "path": str(p), "date": date})
        return entries

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_entry(self, name: str, curves: list, dims: list) -> str:
        """Write *curves* + *dims* to a new SVG entry.  Returns the saved path."""
        from .export.svg import save_svg
        from .document import Calibration, MirrorAxis, FormingMetadata, MachinedBridge

        safe = _safe_filename(name)
        path = _HINGES_DIR / f"{safe}.svg"
        # Avoid silent overwrite — append _2, _3, … if name is taken
        if path.exists():
            i = 2
            while (_HINGES_DIR / f"{safe}_{i}.svg").exists():
                i += 1
            path = _HINGES_DIR / f"{safe}_{i}.svg"

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
        """Rename *old_path* to *new_name*.  Returns the new path string.
        Raises ValueError if the new name is already taken."""
        safe     = _safe_filename(new_name)
        new_path = _HINGES_DIR / f"{safe}.svg"
        if new_path.exists() and new_path != pathlib.Path(old_path):
            raise ValueError(f"'{safe}' already exists in the library.")
        pathlib.Path(old_path).rename(new_path)
        return str(new_path)

class DrillLibrary:
    """Local drill-hole-pattern library backed by JSON files in
    ~/.guilddraw/library/drills/.

    A pattern is a list of holes, each ``{"dx", "dy", "dia"}`` where (dx, dy) is
    the hole's offset from the lens boxing centre in scene mm (y-down) and *dia*
    is the hole diameter (mm).  Storing offsets from the boxing centre — the OMA
    datum — lets one pattern re-apply to any lens by re-centring."""

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
        safe = _safe_filename(name)
        path = _DRILLS_DIR / f"{safe}.json"
        if path.exists():
            i = 2
            while (_DRILLS_DIR / f"{safe}_{i}.json").exists():
                i += 1
            path = _DRILLS_DIR / f"{safe}_{i}.json"
        payload = {"version": 1, "holes": [
            {"dx": float(h["dx"]), "dy": float(h["dy"]), "dia": float(h["dia"])}
            for h in holes
        ]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(path)

    def load_entry(self, path: str) -> list[dict]:
        """Return the list of holes ({dx,dy,dia}) stored at *path*."""
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return [
            {"dx": float(h.get("dx", 0.0)), "dy": float(h.get("dy", 0.0)),
             "dia": float(h.get("dia", 1.4))}
            for h in data.get("holes", [])
        ]

    def delete_entry(self, path: str) -> None:
        try:
            pathlib.Path(path).unlink()
        except OSError:
            pass

    def rename_entry(self, old_path: str, new_name: str) -> str:
        safe     = _safe_filename(new_name)
        new_path = _DRILLS_DIR / f"{safe}.json"
        if new_path.exists() and new_path != pathlib.Path(old_path):
            raise ValueError(f"'{safe}' already exists in the drill library.")
        pathlib.Path(old_path).rename(new_path)
        return str(new_path)
