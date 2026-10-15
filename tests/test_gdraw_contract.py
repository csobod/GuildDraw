"""The ``.gdraw`` keys GuildModel reads (BUILDPLAN §2, the 2026-10-15
addendum), pinned on this side: a rename fails here before it fails there.

The file is read raw, the way GuildModel's ``core/io_import/gdraw.py`` reads
it — the ZIP members, the manifest, the JSON in each SVG's ``<metadata>`` —
never through GuildDraw's own loader, which would forgive a rename on both
sides at once.
"""
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.document import Layer, TextObject

from helpers import arc, circle, closed_diamond, line

_SVG_NS = "http://www.w3.org/2000/svg"
TABS = ("front", "temple_r", "temple_l", "hinge")

# What GuildModel's reader takes, by name. "texts" is written only when a
# workspace has text, and read with an empty default, so it is pinned on the
# temple that carries one (below), not here.
WORKSPACE_KEYS = {"curves", "forming", "mirror"}
CURVE_KEYS     = {"kind", "layer", "closed", "nodes"}
NODE_KEYS      = {"x", "y"}            # plus cp_in / cp_out, each {x, y}, on a spline
CIRCLE_KEYS    = {"radius"}
ARC_KEYS       = {"radius", "start_angle", "end_angle"}
TEXT_KEYS      = {"text", "family", "size_mm", "rotation", "anchor_x", "anchor_y", "layer"}
FORMING_KEYS   = {"apical_radius_mm", "bridge_angle_deg"}
MIRROR_KEYS    = {"x", "enabled"}
LAYER_NAMES    = {layer.value for layer in Layer}
# Written for GuildModel to seed a new project's blank (Road to 2.0, item 3);
# pinned here before its reader takes them, so the names are settled.
GUIDE_KEYS     = {"width_mm", "height_mm"}


def _state(zf: zipfile.ZipFile, member: str) -> dict:
    root = ET.fromstring(zf.read(member))
    meta = root.find(f"{{{_SVG_NS}}}metadata")
    assert meta is not None and meta.text and meta.text.strip(), member
    return json.loads(meta.text)


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


@pytest.fixture()
def written(win, tmp_path):
    """A file the app wrote, with one curve of every kind on the front and a
    temple with an engraving curve and an engraving text."""
    front, temple = win._workspaces[0], win._workspaces[1]
    for c in (closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
              circle(-15, 0, 10), circle(15, 0, 10),
              arc(0, -30, 5, 0, 90, layer=Layer.REF),
              line([(0, 0), (10, 0)], layer=Layer.REF),
              closed_diamond(0, -30, 4, layer=Layer.INLAY)):
        front.add_curve(c)
    temple.add_curve(line([(0, -5), (120, -5), (120, 5), (0, 5)], closed=True,
                          layer=Layer.OUTLINE))
    temple.add_curve(closed_diamond(60, 0, 3, layer=Layer.ENGRAVING))
    temple.add_text(TextObject(text="GUILD", family="DejaVu Sans", size_mm=4.0,
                               rotation=0.0, anchor_x=20.0, anchor_y=1.5,
                               layer=Layer.ENGRAVING))
    path = tmp_path / "contract.gdraw"
    win._do_save_gdraw(str(path))
    win._dirty = False
    return path


def test_the_archive_members_and_the_manifest(written):
    with zipfile.ZipFile(written) as zf:
        names = set(zf.namelist())
        assert {f"{t}.svg" for t in TABS} <= names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["active_tab"] in TABS


def test_every_workspace_carries_the_keys_guildmodel_reads(written):
    with zipfile.ZipFile(written) as zf:
        for tab in TABS:
            state = _state(zf, f"{tab}.svg")
            assert WORKSPACE_KEYS <= set(state), tab
            assert FORMING_KEYS <= set(state["forming"]), tab
            assert MIRROR_KEYS <= set(state["mirror"]), tab


def test_every_curve_kind_is_spelled_the_way_guildmodel_reads_it(written):
    with zipfile.ZipFile(written) as zf:
        front = _state(zf, "front.svg")
    by_kind = {}
    for c in front["curves"]:
        assert CURVE_KEYS <= set(c), c.get("kind")
        assert c["layer"] in LAYER_NAMES
        assert all(NODE_KEYS <= set(n) for n in c["nodes"])
        by_kind.setdefault(c["kind"], c)
    assert set(by_kind) == {"spline", "circle", "arc", "line"}
    assert CIRCLE_KEYS <= set(by_kind["circle"])
    assert ARC_KEYS <= set(by_kind["arc"])
    spline = by_kind["spline"]
    assert spline["closed"] is True
    for n in spline["nodes"]:
        assert {"x", "y"} <= set(n["cp_in"]) and {"x", "y"} <= set(n["cp_out"])
    # The 2.0 layer travels under its own name, closed, for GuildModel's
    # inlay feature to find.
    inlays = [c for c in front["curves"] if c["layer"] == "INLAY"]
    assert len(inlays) == 1 and inlays[0]["closed"] is True


def test_text_stays_text_with_the_fields_guildmodel_engraves_from(written):
    with zipfile.ZipFile(written) as zf:
        temple = _state(zf, "temple_r.svg")
    assert len(temple["texts"]) == 1
    t = temple["texts"][0]
    assert TEXT_KEYS <= set(t)
    assert (t["layer"], t["text"]) == ("ENGRAVING", "GUILD")
    # The drawn engraving rides beside it on the same layer, closed: a
    # filled shape to GuildModel.
    eng = [c for c in temple["curves"] if c["layer"] == "ENGRAVING"]
    assert len(eng) == 1 and eng[0]["closed"] is True


def test_every_workspace_carries_its_guide_sizes(win, written):
    with zipfile.ZipFile(written) as zf:
        states = {tab: _state(zf, f"{tab}.svg") for tab in TABS}
    for tab, ws in zip(TABS, win._workspaces, strict=True):
        guides = states[tab]["guides"]
        assert set(guides) == ({"stock", "pad"} if tab == "front" else {"stock"}), tab
        assert set(guides["stock"]) == GUIDE_KEYS
        assert (guides["stock"]["width_mm"], guides["stock"]["height_mm"]) == \
            (ws.stock_w, ws.stock_h)
    pad = states["front"]["guides"]["pad"]
    assert set(pad) == GUIDE_KEYS
    assert (states["temple_r"]["guides"]["stock"]["width_mm"],
            states["temple_r"]["guides"]["stock"]["height_mm"]) == (170.0, 30.0)
