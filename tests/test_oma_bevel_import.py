"""OMA import bevel reduction (V1 pre-release round).

OMA traces (and OMA export) describe the FINISHED lens — the drawn lens
grown outward by the bevel depth. Import now asks whether to shrink the
trace back to the drawn lens; at the export depth the round trip is exact
(closing the M15 open question: export→import used to grow by 2·depth).
"""
import math

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.document import Curve, Layer, SplineNode
from framedraft.export.oma import (OmaJob, OmaTrace, build_oma,
                                   points_to_trace, trace_to_curve)
from framedraft.boxing import finished_geometry, lens_bbox
from framedraft.geometry import offset_curve, sample_curve

_R = 24.0          # drawn lens radius (mm)
_DEPTH = 1.0       # bevel depth (mm)


def _circle(cx=0.0, cy=0.0, r=_R) -> Curve:
    return Curve(kind="circle", layer=Layer.LENS,
                 nodes=[SplineNode(cx, cy)], radius=r, closed=True)


def _radial_error(curve, r_expect) -> float:
    cx, cy = 0.0, 0.0
    bb = lens_bbox(curve)
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    return max(abs(math.hypot(x - cx, y - cy) - r_expect)
               for x, y, _t in sample_curve(curve, n_per_seg=24))


# --------------------------------------------------- Qt-free round trip

def test_export_import_round_trips_at_same_depth():
    """finished trace (export side) → shrink on import = the drawn lens."""
    _bb, outline = finished_geometry(_circle(cx=-30.0), _DEPTH)
    assert outline is not None
    radii = points_to_trace(outline)
    drawn = offset_curve(trace_to_curve(radii), -_DEPTH)
    assert _radial_error(drawn, _R) < 0.15
    assert drawn.layer == Layer.LENS and drawn.closed


def test_import_as_traced_keeps_finished_size():
    _bb, outline = finished_geometry(_circle(), _DEPTH)
    traced = trace_to_curve(points_to_trace(outline))
    assert _radial_error(traced, _R + _DEPTH) < 0.15


# --------------------------------------------------- app-level placement

@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    yield w
    # Tests dirty the document (imports); answer the unsaved-changes prompt
    # before it blocks teardown — on macOS even a never-shown window gets a
    # real closeEvent, and the modal QMessageBox would hang CI forever.
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _import_synthetic(win, tmp_path, monkeypatch, depth):
    """Drive _import_oma with a generated 2-lens file (finished r=25, DBL=18),
    answering the bevel dialog with *depth*."""
    radii = [_R + _DEPTH] * 128
    job = OmaJob(records=[("DBL", "18.00")],
                 traces={"R": OmaTrace("R", list(radii)),
                         "L": OmaTrace("L", list(radii))})
    oma = tmp_path / "lenses.oma"
    oma.write_text(build_oma(job), encoding="ascii")

    from framedraft import app as app_mod
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(oma), "")))
    monkeypatch.setattr(type(win), "_ask_oma_import_bevel",
                        lambda self, default: depth)
    win._import_oma()
    QApplication.processEvents()
    return [c for c in win._workspaces[0].doc_curves
            if c.layer == Layer.LENS and not c.mirrored]


def test_import_shrink_places_finished_edges_dbl_apart(win, tmp_path,
                                                       monkeypatch):
    lenses = _import_synthetic(win, tmp_path, monkeypatch, depth=_DEPTH)
    assert len(lenses) == 2
    bbs = sorted((lens_bbox(c) for c in lenses), key=lambda b: b[0])
    right, left = bbs                       # side R sits at negative x
    # Drawn lenses shrank to r=24 …
    for bb in bbs:
        assert bb[2] - bb[0] == pytest.approx(2 * _R, abs=0.2)
    # … and their nasal edges sit DBL + 2·depth apart, so the FINISHED
    # (traced) edges land exactly DBL apart.
    assert left[0] - right[2] == pytest.approx(18.0 + 2 * _DEPTH, abs=0.2)


def test_import_as_traced_keeps_dbl_and_size(win, tmp_path, monkeypatch):
    lenses = _import_synthetic(win, tmp_path, monkeypatch, depth=0.0)
    assert len(lenses) == 2
    bbs = sorted((lens_bbox(c) for c in lenses), key=lambda b: b[0])
    for bb in bbs:
        assert bb[2] - bb[0] == pytest.approx(2 * (_R + _DEPTH), abs=0.2)
    assert bbs[1][0] - bbs[0][2] == pytest.approx(18.0, abs=0.2)


# --------------------------------------------------- export-side dialog

def _export_synthetic(win, tmp_path, monkeypatch, depth):
    """Drive _export_oma on two drawn r=24 circle lenses (drawn DBL = 12),
    answering the bevel dialog with *depth*. Returns the parsed OmaJob."""
    from framedraft.export.oma import parse_oma
    from framedraft import app as app_mod
    front = win._workspaces[0]
    front.add_curve(_circle(cx=-30.0))
    front.add_curve(_circle(cx=30.0))
    win._act_mirror.setChecked(False)           # two explicit lenses
    out = tmp_path / "export.oma"
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(type(win), "_ask_oma_export_bevel",
                        lambda self, default: depth)
    win._export_oma()
    QApplication.processEvents()
    return parse_oma(out.read_text(encoding="ascii"))


def test_export_apply_increase_writes_finished_size(win, tmp_path,
                                                    monkeypatch):
    job = _export_synthetic(win, tmp_path, monkeypatch, depth=_DEPTH)
    assert job.floats("HBOX") == pytest.approx(
        [2 * (_R + _DEPTH)] * 2, abs=0.2)
    # Finished lenses grow toward the nose from both sides.
    assert job.floats("DBL")[0] == pytest.approx(12.0 - 2 * _DEPTH, abs=0.2)


def test_export_as_is_writes_drawn_lens_opening(win, tmp_path, monkeypatch):
    job = _export_synthetic(win, tmp_path, monkeypatch, depth=0.0)
    assert job.floats("HBOX") == pytest.approx([2 * _R] * 2, abs=0.2)
    assert job.floats("DBL")[0] == pytest.approx(12.0, abs=0.2)


def test_gui_export_import_round_trip(win, tmp_path, monkeypatch):
    """Export with the bevel increase, reimport with the matching reduction:
    the drawn lenses come back at their original size and DBL."""
    from framedraft import app as app_mod
    _export_synthetic(win, tmp_path, monkeypatch, depth=_DEPTH)
    front = win._workspaces[0]
    front.push_undo_snapshot()
    front.clear_geometry()
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(
                            lambda *a, **k: (str(tmp_path / "export.oma"), "")))
    monkeypatch.setattr(type(win), "_ask_oma_import_bevel",
                        lambda self, default: _DEPTH)
    win._import_oma()
    QApplication.processEvents()
    lenses = [c for c in front.doc_curves
              if c.layer == Layer.LENS and not c.mirrored]
    assert len(lenses) == 2
    bbs = sorted((lens_bbox(c) for c in lenses), key=lambda b: b[0])
    for bb in bbs:
        assert bb[2] - bb[0] == pytest.approx(2 * _R, abs=0.25)
    assert bbs[1][0] - bbs[0][2] == pytest.approx(12.0, abs=0.25)
