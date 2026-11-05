"""2.0.1, OMA traces against a practice's 412 tracer files (500 points a lens,
frame and pattern traces). The files stay private; these tests rebuild what
they showed on synthetic shapes. Each test names the finding it pins."""
import math

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.document import Layer
from framedraft.export import oma
from framedraft.export.oma import (OmaJob, OmaTrace, build_oma, points_to_trace,
                                   trace_origin, trace_to_curve)


def _tracer_lens(n=500):
    """An asymmetric lens as a tracer writes it: n radii rounded to 0.01 mm,
    with a gentle bottom and a fuller upper temporal corner."""
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = (24.0 + 2.6 * math.cos(2 * a) + 0.7 * math.cos(4 * a)
             + 0.9 * math.sin(a + 0.4) * math.cos(a) + 0.3 * math.cos(3 * a - 1.0))
        out.append(round(r * 100) / 100.0)
    return out


def _exact_radii(outline, n):
    """Radii of a closed outline at n equal angles about its bbox center,
    y-up, by intersecting each ray with the polygon."""
    from shapely.geometry import LineString
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    ring = LineString(list(outline) + [outline[0]])
    radii = []
    for k in range(n):
        a = 2 * math.pi * k / n
        hit = ring.intersection(LineString(
            [(cx, cy), (cx + 100 * math.cos(a), cy - 100 * math.sin(a))]))
        pts = list(getattr(hit, "geoms", [hit]))
        radii.append(max(math.hypot(p.x - cx, p.y - cy) for p in pts))
    return radii


# ── the export's resampling ────────────────────────────────────────────────

def test_the_export_meets_a_straight_segment_exactly():
    # A radius interpolated linearly in angle bowed a straight side outward.
    square = [(10, 10), (-10, 10), (-10, -10), (10, -10)]
    radii = points_to_trace(square, n=72)
    for k, r in enumerate(radii):
        a = 2 * math.pi * k / 72
        assert r == pytest.approx(10 / max(abs(math.cos(a)), abs(math.sin(a))), abs=1e-9)


# ── the import's fit ───────────────────────────────────────────────────────

def test_a_tracer_lens_imports_in_few_nodes_within_two_hundredths():
    # The Catmull-Rom decimation took 72 to 256 nodes (median 108) for a
    # practice's clean 500-point traces; the cubic fit takes about 35.
    radii = _tracer_lens()
    n = len(radii)
    pts = [(r * math.cos(2 * math.pi * i / n), -r * math.sin(2 * math.pi * i / n))
           for i, r in enumerate(radii)]
    c = trace_to_curve(radii)
    assert c.closed and c.layer == Layer.LENS
    assert len(c.nodes) <= 40
    assert oma._worst_miss(c, pts) <= oma._TRACE_TOL_MM


def test_a_fit_that_misses_falls_back_to_the_catmull_decimation(monkeypatch):
    from framedraft.fitting import FitResult

    def wide_of_the_mark(pts, **kw):         # a 30 mm circle, sparse: no refit
        return FitResult(trace_to_curve([30.0] * 16, layer=kw["layer"]), 0.0)
    monkeypatch.setattr(oma, "fit_curve", wide_of_the_mark)
    radii = _tracer_lens()
    c = trace_to_curve(radii)
    assert len(c.nodes) >= oma._DEFAULT_NODES
    n = len(radii)
    pts = [(r * math.cos(2 * math.pi * i / n), -r * math.sin(2 * math.pi * i / n))
           for i, r in enumerate(radii)]
    assert oma._worst_miss(c, pts) <= oma._TRACE_TOL_MM


def test_the_fitter_refuses_crossed_handles_so_a_fitted_lens_exports():
    # Least squares gave a short span handles longer than itself (14 mm on a
    # 0.7 mm chord in a practice's trace): a loop the deviation cannot see,
    # and the OMA export refused 11 of 824 imported lenses as doubling back.
    from framedraft.export.oma import curve_to_trace
    from framedraft.fitting import fit_curve
    n = 500
    radii = [round((24.0 + 1.5 * math.cos(4 * math.pi * i / n) + 0.3 * math.cos(8 * math.pi * i / n)
                    + 0.3 * math.cos(6 * math.pi * i / n - 2.0)
                    + 0.8 * math.sin(2 * math.pi * i / n + 0.4) * math.cos(2 * math.pi * i / n)) * 100)
              / 100.0 for i in range(n)]
    pts = [(r * math.cos(2 * math.pi * i / n), -r * math.sin(2 * math.pi * i / n))
           for i, r in enumerate(radii)]
    c = fit_curve(pts, tol_mm=0.015, closed=True).curve
    for a, b in zip(c.nodes, c.nodes[1:] + c.nodes[:1], strict=True):
        ctrl = [(a.x, a.y), (a.cp_out.x, a.cp_out.y), (b.cp_in.x, b.cp_in.y), (b.x, b.y)]
        cx, cy = b.x - a.x, b.y - a.y
        q = [(ctrl[k + 1][0] - ctrl[k][0]) * cx + (ctrl[k + 1][1] - ctrl[k][1]) * cy
             for k in range(3)]
        along = min(q[0] * (1 - t) ** 2 + 2 * q[1] * t * (1 - t) + q[2] * t * t
                    for t in (i / 64 for i in range(65)))
        assert along >= -1e-9                          # no span runs backward
    curve_to_trace(c)                                  # raised "doubles back"
    curve_to_trace(trace_to_curve(radii))


# ── what the file declares ─────────────────────────────────────────────────

def _job(kind="F", ftyp=None, kind_l=None):
    job = OmaJob(traces={"R": OmaTrace("R", [25.0] * 16, ttype=kind),
                         "L": OmaTrace("L", [25.0] * 16, ttype=kind_l or kind)})
    if ftyp is not None:
        job.set_record("FTYP", ftyp)
    return job


@pytest.mark.parametrize("kind, ftyp, kind_l, words", [
    ("P", "3", None, "a pattern trace (P) of a rimless frame (FTYP 3)"),
    ("F", "1", None, "a frame trace (F) of a plastic frame (FTYP 1)"),
    ("F", "2", None, "a frame trace (F) of a metal frame (FTYP 2)"),
    ("F", "4", None, "a frame trace (F), frame type 4 (FTYP)"),
    ("D", None, None, "a demo lens trace (D)"),
    ("F", "0", None, "a frame trace (F)"),
    ("X", None, None, "a trace of type X"),
    ("F", None, "P", "traces of types F and P"),
])
def test_the_file_says_what_it_traced(kind, ftyp, kind_l, words):
    # A practice's 31 pattern traces were all rimless frames; the dialog said
    # every trace followed a bevel groove. It now reports what the file says
    # and leaves the shrink to the user.
    assert trace_origin(_job(kind, ftyp, kind_l)) == words


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


def _shifted(c, dx):
    for nd in c.nodes:
        for p in (nd, nd.cp_in, nd.cp_out):
            if p is not None:
                p.x += dx
    return c


def test_a_bevel_grown_export_lies_on_the_finished_outline(win, tmp_path, monkeypatch):
    # 2.0.1 flattens a lens to 0.01 mm, leaving chords up to 4 mm long on a
    # gentle stretch: the export bowed them 0.09 mm outward, and met exactly
    # it put the lens up to 0.01 mm inside (B -0.18 mm over ten round trips).
    import shapely
    from framedraft import app as app_mod
    from framedraft.export.oma import parse_oma
    from framedraft.geometry import sample_curve
    front = win._workspaces[0]
    od = _shifted(trace_to_curve(_tracer_lens()), -30.0)
    front.add_curve(od)
    front.add_curve(_shifted(trace_to_curve(_tracer_lens()), 30.0))
    win._act_mirror.setChecked(False)
    out = tmp_path / "export.oma"
    monkeypatch.setattr(app_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(type(win), "_ask_oma_export_bevel", lambda self, default: 1.0)
    win._export_oma()
    got = parse_oma(out.read_text(encoding="ascii")).traces["R"].radii_mm
    dense = shapely.Polygon([(x, y) for x, y, _t in sample_curve(od, 200)])
    truth = dense.buffer(1.0, quad_segs=64).exterior.coords[:-1]
    want = _exact_radii(truth, len(got))
    assert max(abs(g - w) for g, w in zip(got, want, strict=True)) < 0.006   # R's 0.01 rounding


def test_the_import_dialog_shows_the_declaration_and_asks(win, tmp_path, monkeypatch):
    from framedraft import app as app_mod
    job = _job("P", "3")
    path = tmp_path / "rimless.oma"
    path.write_text(build_oma(job), encoding="ascii")
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    asked = []
    monkeypatch.setattr(type(win), "_ask_oma_bevel",
                        lambda self, title, note, depth, *a: asked.append(note) or 0.0)
    win._import_oma()
    assert len(asked) == 1
    assert "This file declares a pattern trace (P) of a rimless frame (FTYP 3)." in asked[0]
    assert "demo lens" in asked[0] and "drill-mount" in asked[0]
