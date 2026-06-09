"""
.gdraw file format — ZIP archive containing:
    manifest.json       version / active_tab
    front.svg           Frame Front workspace (save_svg / load_svg format)
    temple_r.svg        Temple R workspace
    temple_l.svg        Temple L workspace
    hinge.svg           Hinge Pocket workspace

Backward compat:
  - Old files with temple.svg (no temple_r.svg) load temple.svg into temple_r.
  - Plain .svg files still open as before (single Front workspace only).
"""

import json
import os
import tempfile
import zipfile

from . import svg as _svg_mod
from ..document import Calibration, FaceImage, FormingMetadata, MachinedBridge, MirrorAxis

_MANIFEST_VERSION = 1
_TAB_NAMES = ["front", "temple_r", "temple_l", "hinge"]


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
    }


def save_gdraw(workspace_data: dict, path: str, active_tab: str = "front") -> None:
    """Write a .gdraw ZIP.

    workspace_data: dict mapping tab name → {curves, dims, calibration, mirror,
    forming, machined_bridge, face_images, bookmarks}.
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
                    face_images     = data.get("face_images", []),
                    bookmarks       = data.get("bookmarks", []),
                    dims            = data.get("dims", []),
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
    """
    result: dict = {"active_tab": "front"}
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
            except Exception:
                pass   # leave as empty default
            finally:
                os.unlink(tmp_path)

    return result
