"""
framedraft/library.py — Personal hinge pocket library.

Storage layout:
    ~/.guilddraw/library/hinges/<name>.svg

Each entry is a standard GuildDraw SVG saved with save_svg (hinge pocket
workspace format).  The filename stem (minus .svg) is the display name.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re

_HINGES_DIR = pathlib.Path.home() / ".guilddraw" / "library" / "hinges"
_DRILLS_DIR = pathlib.Path.home() / ".guilddraw" / "library" / "drills"


def _safe_filename(name: str) -> str:
    """Strip characters that are illegal in Windows/macOS/Linux filenames."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    return safe or "hinge"


class HingeLibrary:
    """Local hinge pocket library backed by SVG files in ~/.guilddraw/library/hinges/."""

    def __init__(self) -> None:
        _HINGES_DIR.mkdir(parents=True, exist_ok=True)

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

    # ------------------------------------------------------------------
    # Thumbnail
    # ------------------------------------------------------------------

    def thumbnail_pixmap(self, curves: list, size: int = 64):
        """Render a *size*×*size* QPixmap preview of *curves*."""
        from PySide6.QtGui import QImage, QPainter, QPen, QColor, QPixmap
        from .canvas.items import build_path

        # Bounding box over all curve nodes
        from .geometry import arc_bbox
        xs: list[float] = []
        ys: list[float] = []
        for c in curves:
            if c.mirrored:
                continue
            if (c.kind == "arc" and c.radius and c.nodes
                    and c.start_angle is not None and c.end_angle is not None):
                bx0, by0, bx1, by1 = arc_bbox(c.nodes[0].x, c.nodes[0].y,
                                              c.radius, c.start_angle, c.end_angle)
                xs.extend([bx0, bx1])
                ys.extend([by0, by1])
            elif c.kind in ("circle", "arc") and c.radius and c.nodes:
                cx, cy, r = c.nodes[0].x, c.nodes[0].y, c.radius
                xs.extend([cx - r, cx + r])
                ys.extend([cy - r, cy + r])
            else:
                for n in c.nodes:
                    xs.append(n.x)
                    ys.append(n.y)

        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(0xFFFAF6EE)

        if xs:
            margin = max((max(xs) - min(xs)) * 0.12, 2.0)
            x0, y0 = min(xs) - margin, min(ys) - margin
            x1, y1 = max(xs) + margin, max(ys) + margin
            w, h   = x1 - x0, y1 - y0

            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if w > 0 and h > 0:
                scale = min(size / w, size / h) * 0.88
                p.translate((size - w * scale) / 2, (size - h * scale) / 2)
                p.scale(scale, scale)
                p.translate(-x0, -y0)

            pen = QPen(QColor("#1f1f1f"), 1.5)
            pen.setCosmetic(True)
            p.setPen(pen)
            for c in curves:
                if not c.mirrored:
                    p.drawPath(build_path(c))
            p.end()

        return QPixmap.fromImage(img)


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
