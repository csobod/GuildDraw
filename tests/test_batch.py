"""Batch DXF export (M9) — path suffixing, all-or-nothing validation, writes."""
import ezdxf

from framedraft.document import Layer
from framedraft.export.batch import (
    BatchWorkspace, base_from_path, batch_paths, check_batch, write_batch,
)
from helpers import line, circle, closed_diamond


def front_item(mirror_on=True):
    """A valid Frame Front: OUTLINE ×1 + LENS ×1 doubled by the mirror."""
    return BatchWorkspace(
        workspace_type="front",
        curves=[closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
                circle(-15, 0, 10, layer=Layer.LENS)],
        mirror_on=mirror_on, axis_x=0.0)


def temple_item(ws_type="temple_r"):
    return BatchWorkspace(
        workspace_type=ws_type,
        curves=[closed_diamond(40, 0, 30, layer=Layer.OUTLINE)],
        mirror_on=False)


def hinge_item():
    return BatchWorkspace(
        workspace_type="hinge",
        curves=[circle(0, 0, 3, layer=Layer.HINGE)],
        mirror_on=False)


def test_base_from_path_strips_dxf_any_case():
    assert base_from_path(r"C:\x\frame.dxf") == r"C:\x\frame"
    assert base_from_path(r"C:\x\frame.DXF") == r"C:\x\frame"
    assert base_from_path(r"C:\x\frame")     == r"C:\x\frame"


def test_batch_paths_only_populated_workspaces():
    items = [front_item(), temple_item(),
             BatchWorkspace(workspace_type="hinge", curves=[])]
    paths = batch_paths("base", items)
    assert paths == {"front": "base_front.dxf",
                     "temple_r": "base_temple_r.dxf"}


def test_check_batch_skips_empty_and_passes_valid():
    items = [front_item(), temple_item(), temple_item("temple_l"),
             BatchWorkspace(workspace_type="hinge", curves=[])]
    report = check_batch(items)
    assert report.ok
    assert report.skipped == ["hinge"]
    assert not report.warnings


def test_check_batch_collects_errors_per_workspace():
    bad_front  = BatchWorkspace(          # no OUTLINE, only one LENS, no mirror
        workspace_type="front",
        curves=[circle(-15, 0, 10, layer=Layer.LENS)], mirror_on=False)
    bad_temple = BatchWorkspace(          # LENS forbidden in temples
        workspace_type="temple_r",
        curves=[closed_diamond(layer=Layer.OUTLINE),
                circle(0, 0, 5, layer=Layer.LENS)], mirror_on=False)
    report = check_batch([bad_front, bad_temple, hinge_item()])
    assert not report.ok
    assert set(report.errors) == {"front", "temple_r"}
    assert "hinge" not in report.errors


def test_check_batch_reports_warnings():
    open_lens = line([(-25, 0), (-15, 5), (-5, 0.05), (-25, 0.0)],
                     layer=Layer.LENS)
    open_lens.closed = False           # endpoints coincide → auto-close warning
    items = [BatchWorkspace(
        workspace_type="front",
        curves=[closed_diamond(0, 0, 40, layer=Layer.OUTLINE), open_lens],
        mirror_on=True)]
    report = check_batch(items)
    assert report.ok
    assert "front" in report.warnings


def test_write_batch_writes_one_file_per_populated_workspace(tmp_path):
    items = [front_item(), temple_item(), temple_item("temple_l"),
             BatchWorkspace(workspace_type="hinge", curves=[])]
    base = str(tmp_path / "myframe")
    written = write_batch(items, base)
    assert [p.replace(str(tmp_path), "") for p in written] == [
        r"\myframe_front.dxf", r"\myframe_temple_r.dxf",
        r"\myframe_temple_l.dxf"]
    # Front file: mirror doubling applied → 2 LENS circles, 1 OUTLINE spline.
    msp = ezdxf.readfile(written[0]).modelspace()
    assert len([e for e in msp if e.dxf.layer == "LENS"]) == 2
    assert len([e for e in msp if e.dxf.layer == "OUTLINE"]) == 1


def test_write_batch_temples_mirror_horizontally(tmp_path):
    item = BatchWorkspace(
        workspace_type="temple_r",
        curves=[closed_diamond(40, 0, 30, layer=Layer.OUTLINE),
                circle(15, 10, 4, layer=Layer.HINGE)],
        mirror_on=True, axis_x=0.0)
    written = write_batch([item], str(tmp_path / "f"))
    msp = ezdxf.readfile(written[0]).modelspace()
    centers = sorted((c.dxf.center.x, c.dxf.center.y)
                     for c in msp if c.dxftype() == "CIRCLE")
    assert centers == [(15, -10), (15, 10)]
