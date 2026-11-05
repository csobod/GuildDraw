"""2.0.1, after the hunt: the investigation for the offset's class of fault
(BUILDPLAN "The offset's cousins"). The fixes made in the main window, the
fitting engine, the OMA import and the small tools; the validator, Trim and
Split, the DXF and SVG imports and the canvas have their own test_v201_*
files. Each test names the finding it pins."""
import gc
import math
import random
import time
import zipfile

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGraphicsView

import framedraft.prefs as prefs_mod
from framedraft import geometry as G
from framedraft.document import Curve, Layer, SplineNode
from helpers import line, spline


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
    gc.collect()


def _trace(n, sigma, seed=1):
    """A 50 × 44 mm elliptical lens as an n-point OMA trace, radii rounded to
    the R records' 0.01 mm, with tracer noise of *sigma*."""
    random.seed(seed)
    return [round(25 * 22 / math.hypot(22 * math.cos(2 * math.pi * i / n),
                                       25 * math.sin(2 * math.pi * i / n))
                  + random.gauss(0, sigma), 2) for i in range(n)]


# ── item 0: the offset's refit, and lens traces with tracer noise ──────────

def test_the_fit_measures_its_deviation_without_a_quadratic_search():
    # 16 000 points: GEOS measured each against the whole polyline, 16 s.
    from framedraft.fitting import fit_curve
    random.seed(3)
    n = 16000
    pts = [(25 * math.cos(2 * math.pi * i / n) + random.gauss(0, .01),
            20 * math.sin(2 * math.pi * i / n) + random.gauss(0, .01)) for i in range(n)]
    t = time.perf_counter()
    fit_curve(pts, tol_mm=0.01, closed=True)
    assert time.perf_counter() - t < 6.0


def test_a_noisy_lens_trace_imports_smooth_and_its_bevel_shrinks():
    # One node a traced point, wiggling at each: the shrink folded at every
    # wiggle and was refused after 15 s for 2000 points.
    from framedraft.boxing import lens_bbox
    from framedraft.export.oma import trace_to_curve
    for n in (1000, 2000):
        c = trace_to_curve(_trace(n, 0.01))
        assert len(c.nodes) <= 80
        x0, y0, x1, y1 = lens_bbox(c)
        assert x1 - x0 == pytest.approx(50.0, abs=0.03)
        assert y1 - y0 == pytest.approx(44.0, abs=0.03)
        G.offset_curve(c, -0.5)                       # no OffsetOutOfRange


def test_a_clean_trace_is_fitted_as_before():
    from framedraft.export import oma
    radii = _trace(1000, 0.0)
    assert oma.trace_noise_mm(radii) < oma._TRACE_NOISE_MM
    c = oma.trace_to_curve(radii)
    smoothed = oma._smoothed
    try:
        oma._smoothed = lambda r, noise: pytest.fail("a clean trace was smoothed")
        again = oma.trace_to_curve(radii)
    finally:
        oma._smoothed = smoothed
    assert [(n.x, n.y) for n in c.nodes] == [(n.x, n.y) for n in again.nodes]


def test_the_untangle_counts_the_pairs_it_weighs(monkeypatch):
    # A trace's noise weighed 80 000 pairs a pass, uncounted: 40 passes, 17 s.
    monkeypatch.setattr(G, "_LOOP_MAX_PAIRS", 2)
    sq = Curve(kind="spline", layer=Layer.COMPONENT, closed=True,
               nodes=[SplineNode(x=x, y=y) for x, y in [(0, 0), (10, 0), (10, 6), (0, 6)]])
    with pytest.raises(G.OffsetOutOfRange):
        G.offset_curve(sq, -0.5)


def test_the_offset_tool_suggests_rebuild_for_a_dense_curve():
    from framedraft.canvas.scene import FrameScene
    from framedraft.tools.offset import OffsetTool
    zig = spline([(i * 2.0, 1.5 * (1 if i % 2 else -1)) for i in range(240)])
    scene = FrameScene()
    tool = OffsetTool()
    tool.activate(scene, QGraphicsView(scene), zig)
    _curve, why, out_of_range = tool._offset_for(5.0)
    assert out_of_range and "Rebuild" in why


def test_an_oma_lens_that_cannot_shrink_leaves_the_other_shrunk(win, tmp_path, monkeypatch):
    # One failure in the shared shrink sent both lenses in at traced size.
    from framedraft import app as app_mod
    from framedraft.boxing import lens_bbox
    from framedraft.export.oma import OmaJob, OmaTrace, build_oma
    job = OmaJob(records=[("DBL", "18.00")],
                 traces={"R": OmaTrace("R", [25.5] * 128),
                         "L": OmaTrace("L", [0.3] * 128)})   # no room for a bevel
    oma = tmp_path / "lenses.oma"
    oma.write_text(build_oma(job), encoding="ascii")
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(oma), "")))
    monkeypatch.setattr(type(win), "_ask_oma_import_bevel", lambda self, d, **_k: 0.5)
    warned = []
    monkeypatch.setattr(app_mod.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a[2])))
    win._import_oma()
    widths = sorted(lens_bbox(c)[2] - lens_bbox(c)[0] for c in win._workspaces[0].doc_curves
                    if c.layer == Layer.LENS and not c.mirrored)
    assert widths == pytest.approx([0.6, 50.0], abs=0.05)
    assert len(warned) == 1 and "L:" in warned[0] and "That lens is" in warned[0]


# ── item 3: Rebuild ────────────────────────────────────────────────────────

def _rebuild_tool(src):
    from framedraft.canvas.scene import FrameScene
    from framedraft.tools.rebuild import RebuildSplineTool
    scene = FrameScene()
    tool = RebuildSplineTool()
    tool._test_view = QGraphicsView(scene)
    tool.activate(scene, tool._test_view, src)
    return tool


def test_rebuild_fits_once_the_typing_pauses(monkeypatch):
    # Every digit was a full fit: "1000" four of them.
    import framedraft.fitting as fitting
    calls = []
    real = fitting.fit_curve
    monkeypatch.setattr(fitting, "fit_curve", lambda *a, **k: calls.append(k) or real(*a, **k))
    tool = _rebuild_tool(spline([(0, -22), (20, -16), (30, 0), (22, 18), (0, 24),
                                 (-22, 17), (-31, 0), (-20, -17)], closed=True))
    for ch in "12":
        tool.handle_key(0, ch)
    assert calls == [] and tool._fit_timer.isActive()
    tool._refit()
    assert len(calls) == 1 and tool._last_fit.n_nodes == 12


def test_rebuild_caps_the_count_at_what_the_curve_can_use():
    # "100000" on a 64-node spline: 4.5 s and 17 000 nodes, taken on Enter.
    src = spline([(30 * math.cos(2 * math.pi * i / 64), 20 * math.sin(2 * math.pi * i / 64))
                  for i in range(64)], closed=True)
    tool = _rebuild_tool(src)
    applied = []
    tool.rebuild_applied.connect(lambda s, c: applied.append(c))
    for ch in "100000":
        tool.handle_key(0, ch)
    tool._refit()                                   # the pause in the typing
    assert "the most for this curve" in tool._hud.text()
    tool.handle_key(Qt.Key.Key_Return)
    assert len(applied) == 1 and len(applied[0].nodes) <= 4 * 64


# ── items 1, 4, 9, 11: the main window ─────────────────────────────────────

def test_the_stock_size_boxes_commit_on_enter_not_each_keystroke(win):
    # Each keystroke ran the readiness check: 2 s for "175" on an exploded outline.
    assert not win._stock_w_spin.keyboardTracking()
    assert not win._stock_h_spin.keyboardTracking()


def test_an_import_selects_its_curves_in_one_pass(win, tmp_path, monkeypatch):
    # One selection change a curve, each rescanning the selection: 20 000
    # DXF lines took 163 s.
    import ezdxf
    doc = ezdxf.new()
    for i in range(300):
        doc.modelspace().add_line((i * 0.2, 0), (i * 0.2, 10))
    path = tmp_path / "lines.dxf"
    doc.saveas(path)
    from framedraft import app as app_mod
    monkeypatch.setattr(app_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    changes = []
    win.scene.selectionChanged.connect(lambda: changes.append(1))
    win._import_dxf()
    QApplication.processEvents()
    assert len(win.scene.selectedItems()) == 300
    assert len(changes) <= 2


def _locked_front(win):
    ws = win._active_ws
    for x in (-30, 30):
        ws.add_curve(spline([(x - 25, 0), (x, -15), (x + 25, 0), (x, 15)],
                            closed=True, layer=Layer.LENS))
    ws.add_curve(spline([(-62, 0), (0, -22), (62, 0), (0, 22)],
                        closed=True, layer=Layer.OUTLINE))
    win._snap_box_chk.setChecked(True) if hasattr(win, "_snap_box_chk") else None
    return ws


def test_a_locked_lens_is_not_resized_to_nothing(win, monkeypatch):
    # A = 0, or "5" for "52" committed by leaving the field, shrank the lenses
    # to 0.5 mm and the outline from 164 to 40 mm, with the dot green.
    calls = []
    monkeypatch.setattr(type(win), "_resize_locked_lens",
                        lambda self, a, b: calls.append((a, b)))
    monkeypatch.setattr(type(win), "_finished_box_values",
                        lambda self: (50.0, 30.0, 18.0))
    win._locked_resize_from_field("a", 5.0)
    win._locked_resize_from_field("b", 0.0)
    assert calls == [] and "out of range" in win._status.currentMessage()
    win._locked_resize_from_field("a", 52.0)
    assert calls == [(52.0, None)]


def test_the_b_read_out_reaches_past_100_mm(win):
    # Chained to A = 120, B was 102.6 and the field showed its top, 100.0.
    assert win._boxing_b_spin.maximum() >= win._boxing_a_spin.maximum()


def test_a_tab_too_large_to_open_again_is_said_at_save(tmp_path, monkeypatch):
    # Each bookmark stores the drawing: a dense front with three saved a
    # 135 MB tab without a word, and the next open showed it empty.
    import framedraft.export.gdraw as gdraw_mod
    import framedraft.export.svg as svg_mod
    ws = {"front": {"curves": [spline([(i, (i % 7) * 0.3) for i in range(400)])]}}
    path = tmp_path / "big.gdraw"
    gdraw_mod.save_gdraw(ws, str(path))
    size = zipfile.ZipFile(path).getinfo("front.svg").file_size
    monkeypatch.setattr(svg_mod, "_MAX_SVG_BYTES", size // 2)   # a loose SVG's cap
    assert gdraw_mod.load_gdraw(str(path))["front"]["curves"]   # its own tab opens
    assert gdraw_mod.oversized_tabs(str(path)) == []
    monkeypatch.setattr(gdraw_mod, "_MAX_TAB_BYTES", size // 2)
    assert [t for t, _mb in gdraw_mod.oversized_tabs(str(path))] == ["front"]


def test_the_temple_endpiece_reading_samples_only_the_hinge_end():
    # The whole outline was sampled on every drag tick: 129 ms at 3000 nodes.
    from framedraft.app import _ys_left_of
    n = 3000
    temple = spline([(140 * i / n, 6 * math.sin(i / 40)) for i in range(n)]
                    + [(140 * (n - i) / n, 6 * math.sin((n - i) / 40) + 5)
                       for i in range(1, n)], closed=True)
    old = [y for x, y, _t in G.sample_curve(temple, 64) if x <= 14.0]
    calls = []
    real = G._bezier_eval
    G._bezier_eval = lambda *a: calls.append(1) or real(*a)
    try:
        new = _ys_left_of(temple, 14.0, 64)
    finally:
        G._bezier_eval = real
    assert (min(new), max(new)) == (min(old), max(old))
    assert len(calls) < 65 * 2 * n * 0.15


# ── item 9: small wrong answers ────────────────────────────────────────────

def test_a_fillet_that_takes_a_whole_leg_leaves_no_zero_length_line():
    from framedraft.canvas.scene import FrameScene
    from framedraft.tools.fillet import FilletTool
    a = line([(0, 0), (10, 0)], layer=Layer.OUTLINE)
    b = line([(10, 0), (10, 10)], layer=Layer.OUTLINE)
    tool = FilletTool()
    tool._scene = FrameScene()
    tool._line1, tool._line2 = a, b
    tool._radius_input = "10"
    out = tool._build_result(10.0)
    lines = [c for c in out if c.kind == "line"]
    assert all(math.dist((c.nodes[0].x, c.nodes[0].y), (c.nodes[-1].x, c.nodes[-1].y)) > 0.01
               for c in lines)
    assert [c.kind for c in out].count("arc") == 1


def test_a_lens_with_a_loop_measures_its_whole_width():
    from framedraft.boxing import lens_bbox
    c = spline([(-25, 0), (0, -10), (25, 0), (0, 10)], closed=True, layer=Layer.LENS)
    node = c.nodes[2]
    node.cp_in, node.cp_out = node.cp_out, node.cp_in      # a handle dragged through
    x0, _y0, x1, _y1 = lens_bbox(c)
    assert x1 - x0 == pytest.approx(50.0, abs=0.02)


def test_a_typed_length_past_ten_meters_is_refused():
    from framedraft.typed import parse_typed
    assert parse_typed("1e300") is None and parse_typed("-20000") is None
    assert parse_typed("9999,5") == 9999.5


def test_a_fillet_of_all_but_straight_legs_is_refused():
    # Legs bent by 1e-7°: the arc's sweep was stored as 0 and read back as a
    # full circle in the file.
    a = math.radians(1e-7)
    far2 = (10 + 10 * math.cos(a), 10 * math.sin(a))
    assert G.fillet_lines((10.0, 0.0), (0.0, 0.0), far2, 5.0) is None
    assert G.fillet_lines((10.0, 0.0), (0.0, 0.0), (10.0, 10.0), 5.0) is not None
