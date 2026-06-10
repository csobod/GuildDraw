""".gdraw ZIP format — multi-workspace round-trip and corrupt-tab reporting."""
import zipfile

from framedraft.document import (
    Calibration, MirrorAxis, FormingMetadata, MachinedBridge, DimLine,
)
from framedraft.export.gdraw import save_gdraw, load_gdraw
from helpers import circle, closed_diamond, line


def ws(curves, dims=None):
    return {
        "curves": curves, "dims": dims or [],
        "calibration": Calibration(), "mirror": MirrorAxis(),
        "forming": FormingMetadata(), "machined_bridge": MachinedBridge(),
        "face_images": [], "bookmarks": [],
    }


def test_four_workspace_roundtrip(tmp_path):
    path = tmp_path / "proj.gdraw"
    save_gdraw({
        "front":    ws([closed_diamond(), circle(-15, 0, 10), circle(15, 0, 10)]),
        "temple_r": ws([line([(0, 0), (120, 0)])],
                       dims=[DimLine(x0=0, y0=0, x1=120, y1=0)]),
        "temple_l": ws([]),
        "hinge":    ws([circle(0, 0, 2)]),
    }, str(path), active_tab="temple_r")

    data = load_gdraw(str(path))
    assert data["errors"] == []
    assert data["active_tab"] == "temple_r"
    assert len(data["front"]["curves"]) == 3
    assert len(data["temple_r"]["curves"]) == 1
    assert len(data["temple_r"]["dims"]) == 1
    assert data["temple_l"]["curves"] == []
    assert len(data["hinge"]["curves"]) == 1


def test_corrupt_tab_is_reported_not_swallowed(tmp_path):
    bad = tmp_path / "bad.gdraw"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("manifest.json", '{"version": 1, "active_tab": "front"}')
        zf.writestr("front.svg", "<svg>not guilddraw data")
    data = load_gdraw(str(bad))
    assert data["errors"] and "front" in data["errors"][0]
    assert data["front"]["curves"] == []


def test_legacy_single_temple_maps_to_temple_r(tmp_path):
    # Build a modern file, then rewrite it with the legacy temple.svg name
    src = tmp_path / "modern.gdraw"
    save_gdraw({"front": ws([]), "temple_r": ws([line([(0, 0), (50, 0)])]),
                "temple_l": ws([]), "hinge": ws([])}, str(src))
    legacy = tmp_path / "legacy.gdraw"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(legacy, "w") as zout:
        for name in zin.namelist():
            if name == "temple_r.svg":
                zout.writestr("temple.svg", zin.read(name))
            elif name != "temple_l.svg":
                zout.writestr(name, zin.read(name))
    data = load_gdraw(str(legacy))
    assert data["errors"] == []
    assert len(data["temple_r"]["curves"]) == 1
    assert data["temple_l"]["curves"] == []
