"""Face-photo path privacy (V1 pre-release round).

Shared files must never carry the author's absolute C:\\Users\\<name>\\…
image paths: .gdraw EMBEDS the photo as a zip member ("images/…") and
extracts it to ~/.guilddraw/imagecache/ on load; plain .svg stores a
document-relative path or bare basename. Old files with absolute paths
keep loading unchanged.
"""
import json
import os
import zipfile

import pytest

import framedraft.export.gdraw as gdraw_mod
from framedraft.document import FaceImage
from framedraft.export.gdraw import load_gdraw, save_gdraw
from framedraft.export.svg import portable_face_images, resolve_face_images

_PNG_BYTES = b"\x89PNG-fake-image-bytes-for-embedding-test"


@pytest.fixture()
def cache_root(tmp_path, monkeypatch):
    root = tmp_path / "imagecache"
    monkeypatch.setattr(gdraw_mod, "_IMAGE_CACHE_ROOT", root)
    return root


def _face_data(img_path: str) -> dict:
    return {"front": {
        "face_images": [FaceImage(path=img_path, tx=3.0, ty=-2.0,
                                  rotation=15.0, opacity=0.6)],
    }}


# ------------------------------------------------------------- .gdraw embed

def test_gdraw_embeds_photo_and_strips_source_path(tmp_path, cache_root):
    img = tmp_path / "secret_home" / "face.png"
    img.parent.mkdir()
    img.write_bytes(_PNG_BYTES)
    doc = tmp_path / "designs" / "frame.gdraw"
    doc.parent.mkdir()

    data = _face_data(str(img))
    save_gdraw(data, str(doc))

    with zipfile.ZipFile(doc) as zf:
        names = zf.namelist()
        members = [n for n in names if n.startswith("images/")]
        assert members == ["images/front_0_face.png"]
        assert zf.read(members[0]) == _PNG_BYTES
        svg_text = zf.read("front.svg").decode("utf-8")
    # The author's directory tree must not appear anywhere in the file.
    assert "secret_home" not in svg_text
    assert str(img) not in svg_text
    assert "images/front_0_face.png" in svg_text
    # The caller's FaceImage object is untouched (autosave reuses it).
    assert data["front"]["face_images"][0].path == str(img)

    loaded = load_gdraw(str(doc))
    fi = loaded["front"]["face_images"][0]
    assert os.path.isfile(fi.path)
    assert str(cache_root) in fi.path            # extracted under the cache
    with open(fi.path, "rb") as f:
        assert f.read() == _PNG_BYTES
    assert (fi.tx, fi.ty, fi.rotation, fi.opacity) == (3.0, -2.0, 15.0, 0.6)


def test_gdraw_vanished_source_stores_basename_only(tmp_path, cache_root):
    gone = tmp_path / "secret_home" / "gone.png"    # never created
    doc = tmp_path / "frame.gdraw"
    save_gdraw(_face_data(str(gone)), str(doc))

    with zipfile.ZipFile(doc) as zf:
        assert not [n for n in zf.namelist() if n.startswith("images/")]
        svg_text = zf.read("front.svg").decode("utf-8")
    assert "secret_home" not in svg_text
    state = json.loads(svg_text.split("<metadata>")[1].split("</metadata>")[0])
    assert state["face_images"][0]["path"] == "gone.png"

    # Loads without error; the unresolved name is simply not a file.
    loaded = load_gdraw(str(doc))
    assert not os.path.isfile(loaded["front"]["face_images"][0].path)


def test_gdraw_legacy_absolute_path_passes_through(tmp_path, cache_root):
    """Pre-1.0 files carry absolute paths; they must load unchanged."""
    from framedraft.export import svg as svg_mod
    from framedraft.document import (Calibration, FormingMetadata,
                                     MachinedBridge, MirrorAxis)
    img = tmp_path / "face.png"
    img.write_bytes(_PNG_BYTES)
    svg_file = tmp_path / "front.svg"
    svg_mod.save_svg(
        curves=[], path=str(svg_file), calibration=Calibration(),
        mirror=MirrorAxis(), forming=FormingMetadata(),
        machined_bridge=MachinedBridge(),
        face_images=[FaceImage(path=str(img))])
    doc = tmp_path / "legacy.gdraw"
    with zipfile.ZipFile(doc, "w") as zf:
        zf.write(svg_file, "front.svg")

    loaded = load_gdraw(str(doc))
    assert loaded["front"]["face_images"][0].path == str(img)


# ------------------------------------------------------- .svg path helpers

def test_portable_relative_inside_doc_dir(tmp_path):
    (tmp_path / "photos").mkdir()
    img = tmp_path / "photos" / "face.png"
    img.write_bytes(_PNG_BYTES)
    out = portable_face_images([FaceImage(path=str(img))],
                               str(tmp_path / "frame.svg"))
    assert out[0].path == "photos/face.png"


def test_portable_outside_doc_dir_is_basename(tmp_path):
    img = tmp_path / "secret_home" / "face.png"
    img.parent.mkdir()
    img.write_bytes(_PNG_BYTES)
    doc_dir = tmp_path / "designs"
    doc_dir.mkdir()
    out = portable_face_images([FaceImage(path=str(img))],
                               str(doc_dir / "frame.svg"))
    assert out[0].path == "face.png"
    assert "secret_home" not in out[0].path


def test_resolve_inside_doc_dir(tmp_path):
    (tmp_path / "photos").mkdir()
    img = tmp_path / "photos" / "face.png"
    img.write_bytes(_PNG_BYTES)
    fis = [FaceImage(path="photos/face.png")]
    resolve_face_images(fis, str(tmp_path / "frame.svg"))
    assert fis[0].path == str(img)


def test_resolve_rejects_traversal_outside_doc_dir(tmp_path):
    outside = tmp_path / "loot.png"
    outside.write_bytes(_PNG_BYTES)
    doc_dir = tmp_path / "designs"
    doc_dir.mkdir()
    fis = [FaceImage(path="../loot.png")]
    resolve_face_images(fis, str(doc_dir / "frame.svg"))
    assert fis[0].path == "../loot.png"          # left unresolved
