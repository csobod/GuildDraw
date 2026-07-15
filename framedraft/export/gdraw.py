"""
.gdraw file format — ZIP archive containing:
    manifest.json       version / active_tab
    front.svg           Frame Front workspace (save_svg / load_svg format)
    temple_r.svg        Temple R workspace
    temple_l.svg        Temple L workspace
    hinge.svg           Hinge Pocket workspace
    images/…            embedded face photos (one member per FaceImage)

Face photos are EMBEDDED: at save time each readable image file is copied
into the archive under ``images/<tab>_<i>_<basename>`` and the metadata
records only that member name — a shared .gdraw never carries the author's
absolute ``C:\\Users\\<name>\\…`` path (a privacy leak), and the recipient
sees the photo instead of a missing file.  At load time embedded images are
extracted to ``~/.guilddraw/imagecache/<doc-key>/`` and the FaceImage path
is pointed there, so the rest of the app keeps loading images by file path.

Backward compat:
  - Old files with absolute image paths keep loading (honored only if the
    file exists on this machine, exactly as before).
  - Old files with temple.svg (no temple_r.svg) load temple.svg into temple_r.
  - Plain .svg files still open as before (single Front workspace only).
"""

import dataclasses
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from . import svg as _svg_mod
from ..document import Calibration, FormingMetadata, MachinedBridge, MirrorAxis

_MANIFEST_VERSION = 1
_TAB_NAMES = ["front", "temple_r", "temple_l", "hinge"]

_IMAGE_PREFIX = "images/"
# Extraction root for embedded face photos; module-level so tests can
# redirect it away from the real home directory.
_IMAGE_CACHE_ROOT = Path.home() / ".guilddraw" / "imagecache"


def _empty_ws_data() -> dict:
    return {
        "curves": [],
        "dims": [],
        "calibration": Calibration(),
        "mirror": MirrorAxis(),
        "forming": FormingMetadata(),
        "machined_bridge": MachinedBridge(),
        "face_images": [],
        "bookmarks": [],
        "layers": {},
        "fill": None,
        "texts": [],
        "bevel": None,
    }


def _embed_face_images(zf: zipfile.ZipFile, tab: str, face_images: list) -> list:
    """Copy each readable face photo into *zf* and return FaceImage copies
    whose paths are archive member names (or a bare basename when the source
    file has vanished) — never an absolute path."""
    rewritten = []
    for i, fi in enumerate(face_images or []):
        src = fi.path
        if not src:
            rewritten.append(fi)
            continue
        if src.startswith(_IMAGE_PREFIX):
            # Already a member name (defensive; save data normally carries
            # resolved cache paths, not member names).
            rewritten.append(fi)
            continue
        base = os.path.basename(src)
        if os.path.isfile(src):
            member = f"{_IMAGE_PREFIX}{tab}_{i}_{base}"
            with open(src, "rb") as f:
                zf.writestr(member, f.read())
            rewritten.append(dataclasses.replace(fi, path=member))
        else:
            # Source gone — persist the basename so the name survives (and
            # can resolve if the image is later placed next to the document)
            # but the author's directory tree never enters the file.
            rewritten.append(dataclasses.replace(fi, path=base))
    return rewritten


def _extract_face_images(zf: zipfile.ZipFile, names: list, doc_path: str,
                         face_images: list) -> None:
    """Point embedded FaceImage paths at files extracted under the image
    cache; resolve bare relative names against the document's directory
    (only when the result stays inside it). Absolute paths pass through."""
    doc_dir = os.path.dirname(os.path.abspath(doc_path))
    cache_dir = None
    for fi in face_images or []:
        p = fi.path
        if not p or os.path.isabs(p):
            continue
        try:
            if p.startswith(_IMAGE_PREFIX):
                if p not in names:
                    continue                  # damaged archive — skip photo
                if cache_dir is None:
                    key = hashlib.sha1(
                        os.path.abspath(doc_path).encode("utf-8")).hexdigest()[:12]
                    cache_dir = Path(_IMAGE_CACHE_ROOT) / key
                    cache_dir.mkdir(parents=True, exist_ok=True)
                out = cache_dir / os.path.basename(p)
                out.write_bytes(zf.read(p))
                fi.path = str(out)
            else:
                # Bare/relative name: honor it only inside the document's
                # folder so a crafted file can't point at arbitrary local
                # images.
                cand = os.path.normpath(os.path.join(doc_dir, p))
                if cand.startswith(doc_dir + os.sep) and os.path.isfile(cand):
                    fi.path = cand
        except OSError:
            continue    # unwritable cache / unreadable member — photo only


def save_gdraw(workspace_data: dict, path: str, active_tab: str = "front") -> None:
    """Write a .gdraw ZIP.

    workspace_data: dict mapping tab name → {curves, dims, calibration, mirror,
    forming, machined_bridge, face_images, bookmarks}.

    Face photos are embedded as archive members (see module docstring); the
    caller's FaceImage objects are never mutated.
    """
    from framedraft import __version__
    manifest = {
        "version": _MANIFEST_VERSION,
        "guilddraw_version": __version__,
        "tabs": _TAB_NAMES,
        "active_tab": active_tab,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for tab in _TAB_NAMES:
            data = workspace_data.get(tab, _empty_ws_data())
            face_images = _embed_face_images(
                zf, tab, data.get("face_images", []))
            fd, tmp_path = tempfile.mkstemp(suffix=".svg")
            os.close(fd)
            try:
                _svg_mod.save_svg(
                    curves          = data.get("curves", []),
                    path            = tmp_path,
                    calibration     = data.get("calibration", Calibration()),
                    mirror          = data.get("mirror", MirrorAxis()),
                    forming         = data.get("forming", FormingMetadata()),
                    machined_bridge = data.get("machined_bridge", MachinedBridge()),
                    face_images     = face_images,
                    bookmarks       = data.get("bookmarks", []),
                    dims            = data.get("dims", []),
                    layers          = data.get("layers"),
                    fill            = data.get("fill"),
                    texts           = data.get("texts", []),
                    bevel           = data.get("bevel"),
                )
                zf.write(tmp_path, f"{tab}.svg")
            finally:
                os.unlink(tmp_path)


def load_gdraw(path: str) -> dict:
    """Read a .gdraw ZIP.

    Returns dict with keys: "active_tab", "front", "temple_r", "temple_l",
    "hinge" — each workspace value is the dict returned by load_svg (or an
    empty default).

    Backward compat: if the file contains temple.svg but not temple_r.svg,
    temple.svg is loaded into temple_r and temple_l is left empty.

    Per-tab parse failures do not abort the load; they are reported in
    result["errors"] (list of "tab: message" strings) and the affected tab
    is left empty.  Callers MUST surface these — silently treating a corrupt
    tab as empty lets the next save destroy it.
    """
    result: dict = {"active_tab": "front", "errors": []}
    for tab in _TAB_NAMES:
        result[tab] = _empty_ws_data()

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()

        if "manifest.json" in names:
            manifest = json.loads(zf.read("manifest.json").decode())
            active = manifest.get("active_tab", "front")
            # Remap old "temple" active_tab to "temple_r"
            if active == "temple":
                active = "temple_r"
            result["active_tab"] = active

        # Backward compat: old .gdraw files use temple.svg (single tab)
        load_targets = list(_TAB_NAMES)
        if "temple.svg" in names and "temple_r.svg" not in names:
            load_targets = ["front", "temple_r", "hinge"]
            _COMPAT_MAP = {"temple_r": "temple"}
        else:
            _COMPAT_MAP = {}

        for tab in load_targets:
            svg_stem = _COMPAT_MAP.get(tab, tab)
            svg_name = f"{svg_stem}.svg"
            if svg_name not in names:
                continue
            fd, tmp_path = tempfile.mkstemp(suffix=".svg")
            os.close(fd)
            try:
                with open(tmp_path, "wb") as f:
                    f.write(zf.read(svg_name))
                result[tab] = _svg_mod.load_svg(tmp_path)
                _extract_face_images(zf, names, path,
                                     result[tab].get("face_images", []))
            except Exception as exc:
                result["errors"].append(f"{tab}: {exc}")   # tab stays empty
            finally:
                os.unlink(tmp_path)

    return result
