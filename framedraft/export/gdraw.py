"""
.gdraw file format — ZIP archive containing:
    manifest.json       version / active_tab
    front.svg           Frame Front workspace (save_svg / load_svg format)
    temple_r.svg        Temple R workspace
    temple_l.svg        Temple L workspace
    component.svg       Component workspace (hinge.svg, the Hinge Pocket
                        workspace, before 2.0; read forever)
    images/…            the face photos the design stores (one member per
                        stored FaceImage) and the Frame Fill material swatch,
                        if one is set

A face photo is stored only when the maker stores it (the paperclip on the
Canvas tab; FaceImage.stored). One not stored is written as its place on the
canvas and a random id (image_links): no bytes, path or name, so a patient's
photo never leaves the computer in a design.

Stored photos are EMBEDDED: at save time each readable image file is copied
into the archive under ``images/<tab>_<i>_<basename>`` and the metadata
records only that member name — a shared .gdraw never carries the author's
absolute ``C:\\Users\\<name>\\…`` path (a privacy leak), and the recipient
sees the photo instead of a missing file.  At load time embedded images are
extracted to ``~/.guilddraw/imagecache/<doc-key>/<content-hash>/<basename>``,
under the photo's own name, and the FaceImage path is pointed there, so the
rest of the app keeps loading images by file path. The folder is named by the
image's bytes, so a photo keeps its path whatever its place in the list, and
a second open of the same design writes the same files. JPEG, PNG, WebP and
GIF are stored, not deflated: they are compressed already.

A path in the file is never followed outside the document's own folder: an
absolute one (from a file before 1.0, or a crafted one naming a local photo,
or on Windows a \\\\host\\share path that makes the open contact that host)
reads as its bare file name, looked for beside the document.

A photo or swatch the save cannot read (an offline share, a file made
unreadable) or no longer finds is carried over from the file being replaced
when that holds it, and otherwise named in the notes save_gdraw returns: it
blocked every save and autosave, or vanished from the next save unsaid.

Backward compat:
  - Old files with temple.svg (no temple_r.svg) load temple.svg into temple_r.
  - Files before 2.0 carry hinge.svg and may name "hinge" as the active tab:
    both read as the Component workspace, and its HINGE curves as COMPONENT
    (document.LAYER_ALIASES).
  - Plain .svg files still open as before (single Front workspace only).
  - Pre-1.2 files carry no Frame Fill swatch; the fill loads as a flat color.
  - Files before 2.0 say nothing of storing: every photo in them was stored,
    and reads as stored.
"""

import dataclasses
import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from . import svg as _svg_mod
from ..document import (
    WORKSPACE_ALIASES, Calibration, FormingMetadata, MachinedBridge, MirrorAxis,
)

_MANIFEST_VERSION = 1
_TAB_NAMES = ["front", "temple_r", "temple_l", "component"]

_IMAGE_PREFIX = "images/"
# Every member carries this time: the save time made an unchanged design's
# bytes differ at every save, and git and sync tools saw a change each time.
_MEMBER_TIME = (2020, 1, 1, 0, 0, 0)
# A tab carries at most this many photos into the image cache at an open: a
# few-KB file naming one large member forty times wrote gigabytes.
_MAX_PHOTOS_PER_TAB = 16
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
        "guides": None,
        "fill": None,
        "lens_fill": None,
        "inlay_fill": None,
        "texts": [],
        "bevel": None,
    }


def _cache_dir_for(doc_path: str) -> Path:
    """Per-document extraction folder for embedded images. Falls back to a
    temp directory when the home cache is unwritable (read-only or full
    home) so the photos still show instead of silently vanishing."""
    key = hashlib.sha1(os.path.abspath(doc_path).encode("utf-8")).hexdigest()[:12]
    d = Path(_IMAGE_CACHE_ROOT) / key
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return Path(tempfile.mkdtemp(prefix=f"guilddraw-{key}-"))


def _member_too_large(zf: zipfile.ZipFile, name: str, cap: int) -> bool:
    """True when the member's UNCOMPRESSED size exceeds *cap* — checked from
    the archive directory before anything is decompressed, so a small .gdraw
    that inflates to hundreds of MB is refused rather than read into memory."""
    try:
        return zf.getinfo(name).file_size > cap
    except KeyError:
        return False


# Embedded images are bounded like the SVG members: a photo or swatch that
# inflates beyond this is skipped (the design still loads).
_MAX_IMAGE_BYTES = 64 * 1024 * 1024
# The manifest names a version and the active tab; anything larger is not one.
_MAX_MANIFEST_BYTES = 1024 * 1024

# Windows device names, which open the device whatever folder they are in.
_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}

# A face photo's member prefix: the tab and the photo's index at save time.
# The cache file was named after the member, prefix and all, so each save
# added a prefix, until the name passed the filename limit and the photo was
# lost (the 2.0 bug hunt). Stripped, repeatedly, so files saved that way
# heal; "component" is the tab's name since 2.0, "temple" before 1.0.
_FACE_PREFIX = re.compile(
    r"^(?:front|temple_r|temple_l|temple|hinge|component)_\d+_")

# Images already compressed: stored as they are, since deflating them again
# costs time and saves nothing. Anything else (BMP, TIFF) is deflated.
_STORED_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _compression_for(name: str) -> int:
    return (zipfile.ZIP_STORED if name.lower().endswith(_STORED_IMAGE_SUFFIXES)
            else zipfile.ZIP_DEFLATED)


def _safe_name(name: str) -> str:
    """*name* made safe to write in the image cache on any system: the
    characters a Windows path gives meaning to (and control characters)
    become "_", a device name ("aux.png") takes a leading "_", trailing dots
    and spaces go. A member name is the archive's to choose, and on Windows a
    colon names a stream or a drive and a backslash a folder. Refusing such a
    name lost a photo named for its time ("10:15:22.jpg") on Linux, where the
    name is an ordinary one."""
    out = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    if out in ("", ".", ".."):
        out = "image"
    if out.split(".")[0].upper() in _DEVICE_NAMES:
        out = "_" + out
    return out


def _member(zf: zipfile.ZipFile, name: str, data: bytes,
            compress_type: int = zipfile.ZIP_DEFLATED) -> None:
    """Write member *name* with the fixed _MEMBER_TIME."""
    info = zipfile.ZipInfo(name, date_time=_MEMBER_TIME)
    info.compress_type = compress_type
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


# The first bytes of the image formats a reference photo or a swatch can be.
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF87a", b"GIF89a",
                b"BM", b"II*\x00", b"MM\x00*")


def _looks_like_image(data: bytes) -> bool:
    """Whether *data* starts like an image (WebP: RIFF....WEBP). Checked
    before a member is written to the cache: anything the archive held was."""
    return (data.startswith(_IMAGE_MAGIC)
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def _outside_name(p: str) -> str | None:
    """The bare file name of *p* when *p* points outside the document's
    folder (absolute, a drive, a UNC or // path), else None."""
    if (os.path.isabs(p) or p.startswith(("\\\\", "//"))
            or re.match(r"^[A-Za-z]:", p)):
        return re.split(r"[\\\\/]", p)[-1] or None
    return None


def _write_into(folder: Path, name: str, data: bytes) -> Path | None:
    """Write *data* as *folder*/*name* (made safe), provided the result stays
    directly in *folder*; None otherwise."""
    out = folder / _safe_name(name)
    if out.resolve().parent != folder.resolve():
        return None
    if not (out.is_file() and out.stat().st_size == len(data)
            and out.read_bytes() == data):
        out.write_bytes(data)
    return out


def _content_dir(doc_path: str, data: bytes) -> Path:
    """The cache folder for an image with these bytes: named by them, so the
    path does not move when the photo's place in the list does (the folder
    named by that place was pruned under a photo still in use)."""
    d = _cache_dir_for(doc_path) / hashlib.sha1(data).hexdigest()[:16]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_image(src: str) -> tuple[bytes | None, str | None]:
    """(bytes, None) of the image file *src*, or (None, why not)."""
    try:
        if os.path.getsize(src) > _MAX_IMAGE_BYTES:
            return None, f"is larger than {_MAX_IMAGE_BYTES // (1024 * 1024)} MB"
        with open(src, "rb") as f:
            return f.read(), None
    except OSError:
        return None, "could not be read"


def _as_member(name: str) -> str:
    """*name*, a member as a file records it, as zipfile lists it here: on
    Windows it reads a backslash in a stored name as a slash, so a photo
    named with one on a Mac or Linux was not found and did not show."""
    return name.replace("\\", "/") if os.sep == "\\" else name


def _carry(zf: zipfile.ZipFile, old: zipfile.ZipFile | None, member: str) -> bool:
    """Copy *member* from the archive being replaced into *zf*, streamed;
    False when it holds none."""
    member = _as_member(member)
    if old is None or member not in old.namelist():
        return False
    info = zipfile.ZipInfo(member, date_time=_MEMBER_TIME)
    info.compress_type = _compression_for(member)
    info.external_attr = 0o644 << 16
    with old.open(member) as src, zf.open(info, "w") as dst:
        while chunk := src.read(1 << 20):
            dst.write(chunk)
    return True


def _old_member_for(old: zipfile.ZipFile | None, base: str,
                    prefixes: tuple) -> str | None:
    """The member of the archive being replaced that held *base* under any
    of *prefixes* ("front_", "front_fill_"), or None."""
    if old is None:
        return None
    for name in old.namelist():
        if not name.startswith(_IMAGE_PREFIX):
            continue
        member = name[len(_IMAGE_PREFIX):]
        for prefix in prefixes:
            if (member.startswith(prefix)
                    and (_photo_name(member) == base or member[len(prefix):] == base)):
                return name
    return None


def _embed_fill_image(zf: zipfile.ZipFile, tab: str, fill: dict | None,
                      kind: str = "fill", old: zipfile.ZipFile | None = None,
                      notes: list | None = None) -> dict | None:
    """Copy the Frame Fill material swatch into *zf*, returning a fill dict
    whose ``image`` is the archive member name. Same contract as the face
    photos: the author's absolute path never enters a shared file, and the
    recipient sees the material rather than a broken reference. *kind*
    "inlay_fill" does the same for the Inlay Fill's image; *old* and *notes*
    as for _embed_face_images."""
    if not fill or not fill.get("image"):
        return fill
    src = fill["image"]
    out = dict(fill)
    base = os.path.basename(src)
    member = f"{_IMAGE_PREFIX}{tab}_{kind}_{base}"
    if src.startswith(_IMAGE_PREFIX):
        # A member name that never got extracted (unwritable cache, too
        # large): its bytes are in the file being replaced, if anywhere.
        out["image"] = src if _carry(zf, old, src) else base
        return out
    data, why = _read_image(src) if os.path.isfile(src) else (None, "is gone")
    if data is not None:
        _member(zf, member, data, _compression_for(base))
        out["image"] = member
        return out
    # Unreadable, too large or gone: the copy in the file being replaced,
    # else the bare name, never a member name with no bytes behind it.
    was = _old_member_for(old, base, (f"{tab}_{kind}_",))
    if was is not None and _carry(zf, old, was):
        out["image"] = was
        return out
    out["image"] = base
    if notes is not None:
        notes.append(f"{tab}: the {'inlay ' if kind == 'inlay_fill' else ''}fill "
                     f"image {base} {why}, and was not carried")
    return out


def _extract_fill_image(zf: zipfile.ZipFile, names: list, doc_path: str,
                        tab: str, fill: dict | None, kind: str = "fill") -> None:
    """Point an embedded Frame Fill swatch at a file under the image cache,
    in place; resolve a bare name against the document's folder (only when the
    result stays inside it). Absolute paths pass through.

    Unlike a face photo, the swatch's filename is what names the *material* in
    the sidebar ("UB-0614.jpeg"), so it is extracted into a per-tab subfolder
    under its original name rather than under the prefixed member name.
    *kind* as for _embed_fill_image."""
    if not fill:
        return
    p = fill.get("image")
    if not isinstance(p, str):
        fill["image"] = ""                    # not a name: the color fill
        return
    if not p:
        return
    outside = _outside_name(p)
    if outside is not None:
        p = fill["image"] = outside           # looked for beside the document
    try:
        if p.startswith(_IMAGE_PREFIX):
            p = _as_member(p)
            if p not in names or _member_too_large(zf, p, _MAX_IMAGE_BYTES):
                fill["image"] = ""            # damaged archive — color fill
                return
            member = os.path.basename(p)
            base   = member
            for t in (tab, *(old for old, new in WORKSPACE_ALIASES.items()
                             if new == tab)):
                prefix = f"{t}_{kind}_"
                if member.startswith(prefix) and len(member) > len(prefix):
                    base = member[len(prefix):]
                    break
            data = zf.read(p)
            if not _looks_like_image(data):
                fill["image"] = ""            # not an image: the color fill
                return
            out = _write_into(_content_dir(doc_path, data), base, data)
            fill["image"] = str(out) if out is not None else ""
        else:
            doc_dir = os.path.dirname(os.path.abspath(doc_path))
            cand = os.path.normpath(os.path.join(doc_dir, p))
            fill["image"] = (cand if cand.startswith(doc_dir + os.sep)
                             and os.path.isfile(cand) else "")
    except Exception:
        # Unwritable cache, an unreadable or corrupt member: the color fill
        # only. A display value never fails the tab it decorates.
        fill["image"] = ""


def _embed_face_images(zf: zipfile.ZipFile, tab: str, face_images: list,
                       old: zipfile.ZipFile | None = None,
                       notes: list | None = None) -> list:
    """Copy each readable face photo into *zf* and return FaceImage copies
    whose paths are archive member names (or a bare basename when no bytes
    could be had) — never an absolute path.

    *old* is the file being replaced, open for reading: a photo the save
    cannot read, or whose cache copy is gone (the cache cleared under an
    open design), is copied from there; one still named by its member
    (never extracted: too large, or the cache unwritable) too. What is not
    carried is said in *notes*."""
    rewritten = []
    tabs = (tab, *(o for o, n in WORKSPACE_ALIASES.items() if n == tab))
    for i, fi in enumerate(face_images or []):
        src = fi.path
        if not fi.stored:
            # Never read, never copied: the file keeps its place and its id.
            rewritten.append(dataclasses.replace(fi, path=""))
            continue
        if not src:
            rewritten.append(fi)
            continue
        base = _photo_name(os.path.basename(src))
        if src.startswith(_IMAGE_PREFIX):
            if _carry(zf, old, src):
                rewritten.append(fi)
            else:
                rewritten.append(dataclasses.replace(fi, path=base))
                if notes is not None:
                    notes.append(f"{tab}: the reference image {base} was not "
                                 "carried (its bytes were not to be had)")
            continue
        data, why = _read_image(src) if os.path.isfile(src) else (None, "is gone")
        if data is not None:
            member = f"{_IMAGE_PREFIX}{tab}_{i}_{base}"
            _member(zf, member, data, _compression_for(base))
            rewritten.append(dataclasses.replace(fi, path=member))
            continue
        was = _old_member_for(old, base, tuple(f"{t}_" for t in tabs))
        if was is not None and _carry(zf, old, was):
            rewritten.append(dataclasses.replace(fi, path=was))
            continue
        # Persist the basename so the name survives (and can resolve if the
        # image is later placed next to the document) but the author's
        # directory tree never enters the file.
        rewritten.append(dataclasses.replace(fi, path=base))
        if notes is not None:
            notes.append(f"{tab}: the reference image {base} {why}, and was not "
                         "carried")
    return rewritten


def _photo_name(name: str) -> str:
    """A face photo's own name, every member prefix stripped (see
    _FACE_PREFIX); the name itself when nothing is left."""
    out = name
    while (m := _FACE_PREFIX.match(out)) and len(out) > m.end():
        out = out[m.end():]
    return out


def _extract_face_images(zf: zipfile.ZipFile, names: list, doc_path: str,
                         face_images: list) -> None:
    """Point embedded FaceImage paths at files extracted under the image
    cache, in a folder named by the photo's bytes (_content_dir) under its
    own name, so a save names the member as the last one did; resolve bare
    relative names against the document's directory (only when the result
    stays inside it). Absolute paths pass through."""
    doc_dir = os.path.dirname(os.path.abspath(doc_path))
    extracted = 0
    for fi in face_images or []:
        p = fi.path
        if not p:
            continue
        outside = _outside_name(p)
        if outside is not None:
            p = fi.path = outside             # looked for beside the document
        try:
            if p.startswith(_IMAGE_PREFIX):
                p = _as_member(p)
                if (p not in names or extracted >= _MAX_PHOTOS_PER_TAB
                        or _member_too_large(zf, p, _MAX_IMAGE_BYTES)):
                    continue                  # left as the member: not shown,
                                              # carried by the next save
                data = zf.read(p)
                if not _looks_like_image(data):
                    continue                  # not an image: never cached
                out = _write_into(_content_dir(doc_path, data),
                                  _photo_name(os.path.basename(p)), data)
                if out is None:
                    continue                  # a name no cache may write
                extracted += 1
                fi.path = str(out)
            else:
                # Bare/relative name: honor it only inside the document's
                # folder so a crafted file can't point at arbitrary local
                # images.
                cand = os.path.normpath(os.path.join(doc_dir, p))
                if cand.startswith(doc_dir + os.sep) and os.path.isfile(cand):
                    fi.path = cand
        except Exception:
            continue    # unwritable cache, an unreadable or corrupt member


def image_cache_size() -> int:
    """Bytes held in the image cache (Preferences ▸ General ▸ Image Cache)."""
    total = 0
    for dirpath, _dirs, files in os.walk(_IMAGE_CACHE_ROOT):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def clear_image_cache(keep=()) -> int:
    """Delete the image cache but the files in *keep* (the images a design
    open now shows: a Save As takes a stored image from its copy here), and
    the folders left empty. Returns the bytes freed. Every copy is one: a
    design unpacks its stored images again when it is next opened."""
    root = os.path.abspath(_IMAGE_CACHE_ROOT)
    kept = {os.path.abspath(p) for p in keep if p}
    freed = 0
    for dirpath, _dirs, files in os.walk(root, topdown=False):
        for f in files:
            p = os.path.join(dirpath, f)
            if p in kept:
                continue
            try:
                size = os.path.getsize(p)
                os.unlink(p)
                freed += size
            except OSError:
                pass
        if dirpath != root:
            try:
                os.rmdir(dirpath)              # only when nothing was kept
            except OSError:
                pass
    return freed


def _prune_cache(doc_path: str) -> None:
    """Delete the copies GuildDraw 1.x left in the document's image cache:
    files directly in its folder, each under a longer name (a copy per open,
    never pruned). Only those: a folder named by an image's bytes may hold a
    photo another open of the same design still shows, and deleting one
    made that design's next save drop the photo."""
    key = hashlib.sha1(os.path.abspath(doc_path).encode("utf-8")).hexdigest()[:12]
    root = Path(_IMAGE_CACHE_ROOT) / key
    try:
        flat = [p for p in root.iterdir() if p.is_file()]
    except OSError:
        return
    for f in flat:
        try:
            f.unlink()
        except OSError:
            pass


def save_gdraw(workspace_data: dict, path: str, active_tab: str = "front",
               carry_from: str | None = None) -> list[str]:
    """Write a .gdraw ZIP. Returns notes on the images it could not carry
    ("tab: …"), empty when every one went in.

    workspace_data: dict mapping tab name → {curves, dims, calibration, mirror,
    forming, machined_bridge, face_images, bookmarks}.

    Face photos are embedded as archive members (see module docstring); the
    caller's FaceImage objects are never mutated. *carry_from* is the file
    this save replaces, if it is a .gdraw: an image that cannot be read now is
    copied from it.
    """
    old = None
    if carry_from and os.path.isfile(carry_from):
        try:
            old = zipfile.ZipFile(carry_from, "r")
        except (OSError, zipfile.BadZipFile):
            old = None
    try:
        return _save_gdraw(workspace_data, path, active_tab, old)
    finally:
        if old is not None:
            old.close()


def _save_gdraw(workspace_data: dict, path: str, active_tab: str,
                old: zipfile.ZipFile | None) -> list[str]:
    from framedraft import __version__
    manifest = {
        "version": _MANIFEST_VERSION,
        "guilddraw_version": __version__,
        "tabs": _TAB_NAMES,
        "active_tab": active_tab,
    }
    notes: list[str] = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        _member(zf, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        for tab in _TAB_NAMES:
            data = workspace_data.get(tab, _empty_ws_data())
            face_images = _embed_face_images(
                zf, tab, data.get("face_images", []), old, notes)
            fill = _embed_fill_image(zf, tab, data.get("fill"), old=old,
                                     notes=notes)
            inlay_fill = _embed_fill_image(zf, tab, data.get("inlay_fill"),
                                           kind="inlay_fill", old=old, notes=notes)
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
                    guides          = data.get("guides"),
                    fill            = fill,
                    lens_fill       = data.get("lens_fill"),
                    inlay_fill      = inlay_fill,
                    texts           = data.get("texts", []),
                    bevel           = data.get("bevel"),
                )
                with open(tmp_path, "rb") as f:
                    _member(zf, f"{tab}.svg", f.read())
            finally:
                os.unlink(tmp_path)
    return notes


def load_gdraw(path: str) -> dict:
    """Read a .gdraw ZIP.

    Returns dict with keys: "active_tab", "front", "temple_r", "temple_l",
    "component" — each workspace value is the dict returned by load_svg (or
    an empty default).

    Backward compat: if the file contains temple.svg but not temple_r.svg,
    temple.svg is loaded into temple_r and temple_l is left empty.

    Per-tab parse failures do not abort the load; they are reported in
    result["errors"] (list of "tab: message" strings) and the affected tab
    is left empty.  Callers MUST surface these — silently treating a corrupt
    tab as empty lets the next save destroy it.
    """
    result: dict = {"active_tab": "front", "errors": [], "left_out": []}
    for tab in _TAB_NAMES:
        result[tab] = _empty_ws_data()

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()

        manifest = {}
        if ("manifest.json" in names
                and not _member_too_large(zf, "manifest.json", _MAX_MANIFEST_BYTES)):
            # utf-8-sig: a byte-order mark, which an editor may add, made a
            # good file unopenable.
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8-sig"))
            except ValueError:
                manifest = {}
            if not isinstance(manifest, dict):
                manifest = {}
        if manifest:
            active = manifest.get("active_tab", "front")
            if not isinstance(active, str):
                active = "front"                     # not a tab's name
            # Remap old "temple" active_tab to "temple_r", and "hinge" to
            # "component" (2.0)
            if active == "temple":
                active = "temple_r"
            result["active_tab"] = WORKSPACE_ALIASES.get(active, active)

        # Backward compat: old .gdraw files use temple.svg (single tab), and
        # every file before 2.0 hinge.svg for the component tab
        load_targets = list(_TAB_NAMES)
        _COMPAT_MAP = {}
        if "temple.svg" in names and "temple_r.svg" not in names:
            load_targets = ["front", "temple_r", "component"]
            _COMPAT_MAP["temple_r"] = "temple"
        if "component.svg" not in names and "hinge.svg" in names:
            _COMPAT_MAP["component"] = "hinge"

        for tab in load_targets:
            svg_stem = _COMPAT_MAP.get(tab, tab)
            svg_name = f"{svg_stem}.svg"
            if svg_name not in names:
                continue
            if _member_too_large(zf, svg_name, _svg_mod._MAX_SVG_BYTES):
                # Same cap load_svg applies, enforced BEFORE decompression.
                result["errors"].append(
                    f"{tab}: Refusing to open — {svg_name} inflates to "
                    f"{zf.getinfo(svg_name).file_size // (1024 * 1024)} MB "
                    f"(limit {_svg_mod._MAX_SVG_BYTES // (1024 * 1024)} MB).")
                continue
            fd, tmp_path = tempfile.mkstemp(suffix=".svg")
            os.close(fd)
            try:
                with open(tmp_path, "wb") as f:
                    f.write(zf.read(svg_name))
                result[tab] = _svg_mod.load_svg(tmp_path)
                result["left_out"] += [f"{tab}: {what}" for what in
                                       result[tab].get("left_out", [])]
                _extract_face_images(zf, names, path,
                                     result[tab].get("face_images", []))
                _extract_fill_image(zf, names, path, tab,
                                    result[tab].get("fill"))
                _extract_fill_image(zf, names, path, tab,
                                    result[tab].get("inlay_fill"),
                                    kind="inlay_fill")
            except Exception as exc:
                result["errors"].append(f"{tab}: {exc}")   # tab stays empty
            finally:
                os.unlink(tmp_path)

    _prune_cache(path)
    return result
