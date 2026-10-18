"""Where the reference images a design does not store are, on this computer.

A reference image the maker has not stored in the design (FaceImage.stored
False) is named in the .gdraw by a random id and nothing else: no path, no
file name, nothing worked out from the image, so a design sent elsewhere says
nothing about the photo it was drawn over. This table, kept beside the
preferences in ~/.guilddraw/image_links.json, maps each id to the image's
file. Only the maker's own actions write it (adding an image, Locate…, the
copy saved when an image stops being stored); a file can name an id, never a
path, so opening one cannot make GuildDraw read a file of its choosing.

On another computer the id is in no table, and the image is listed as not on
this computer until Locate… finds it.
"""

import json
import os
import pathlib
import re
import uuid

_DIR  = pathlib.Path.home() / ".guilddraw"
_FILE = _DIR / "image_links.json"

_ID = re.compile(r"^[0-9a-f]{32}$")


def new_id() -> str:
    """A fresh id for an image, unrelated to the image itself."""
    return uuid.uuid4().hex


def is_id(value) -> bool:
    """Whether *value* is an id as new_id makes them (read from a file)."""
    return isinstance(value, str) and bool(_ID.match(value))


def _read() -> dict:
    try:
        with open(_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    links = data.get("links") if isinstance(data, dict) else None
    if not isinstance(links, dict):
        return {}
    return {k: v for k, v in links.items()
            if is_id(k) and isinstance(v, str) and os.path.isabs(v)}


def find(link_id: str) -> str | None:
    """The file the image *link_id* names on this computer, if it is there."""
    if not is_id(link_id):
        return None
    path = _read().get(link_id)
    return path if path and os.path.isfile(path) else None


def remember(link_id: str, path: str) -> None:
    """Record that the image *link_id* is the file *path*. Written through a
    temporary file and one replace, as the preferences are; a failed write is
    silent, and the image is then found again with Locate…."""
    if not is_id(link_id) or not path:
        return
    links = _read()
    links[link_id] = os.path.abspath(path)
    tmp = _FILE.with_name(_FILE.name + ".tmp")
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": 1, "links": links}, indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _FILE)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
