"""Drill holes — DRILL layer wiring, DXF export/mirror, drill-pattern library."""
import ezdxf

from framedraft.document import Layer, MACHINED_LAYERS, WORKSPACE_LAYERS
from framedraft.export.dxf import export_dxf, _MIRROR_LAYERS
from helpers import circle


def test_drill_layer_wiring():
    assert Layer.DRILL.value == "DRILL"
    assert Layer.DRILL in WORKSPACE_LAYERS["front"]
    assert Layer.DRILL not in WORKSPACE_LAYERS["temple_r"]
    assert Layer.DRILL in MACHINED_LAYERS
    assert Layer.DRILL in _MIRROR_LAYERS   # holes mirror with their lens


def test_drill_circle_exports_as_circle_on_drill_layer(tmp_path):
    hole = circle(-20, 5, 0.7, layer=Layer.DRILL)   # Ø1.4 mm
    path = tmp_path / "d.dxf"
    export_dxf([hole], str(path), mirror_on=False)
    msp = ezdxf.readfile(str(path)).modelspace()
    circles = [e for e in msp if e.dxftype() == "CIRCLE"]
    assert len(circles) == 1
    assert circles[0].dxf.layer == "DRILL"
    assert circles[0].dxf.center.y == -5    # Y negated on export


def test_drill_holes_mirror_with_lens(tmp_path):
    hole = circle(-20, 5, 0.7, layer=Layer.DRILL)
    path = tmp_path / "d.dxf"
    export_dxf([hole], str(path), mirror_on=True, axis_x=0.0)
    msp = ezdxf.readfile(str(path)).modelspace()
    circles = [e for e in msp if e.dxftype() == "CIRCLE"]
    assert len(circles) == 2
    assert sorted(round(c.dxf.center.x, 2) for c in circles) == [-20, 20]


def test_drill_library_roundtrip(tmp_path, monkeypatch):
    import framedraft.library as lib
    monkeypatch.setattr(lib, "_DRILLS_DIR", tmp_path)
    dl = lib.DrillLibrary()
    holes = [{"dx": 5.0, "dy": -3.0, "dia": 1.4},
             {"dx": -5.0, "dy": -3.0, "dia": 2.0}]
    p = dl.save_entry("temple-drill", holes)
    assert dl.load_entry(p) == holes
    assert "temple-drill" in [e["name"] for e in dl.list_entries()]


def test_drill_library_no_overwrite(tmp_path, monkeypatch):
    import framedraft.library as lib
    monkeypatch.setattr(lib, "_DRILLS_DIR", tmp_path)
    dl = lib.DrillLibrary()
    p1 = dl.save_entry("pat", [{"dx": 1, "dy": 2, "dia": 1.4}])
    p2 = dl.save_entry("pat", [{"dx": 3, "dy": 4, "dia": 1.4}])
    assert p1 != p2   # second save did not clobber the first
    assert len(dl.list_entries()) == 2
