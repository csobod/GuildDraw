"""UI-review regressions for the canvas tools, snapping and PDF exports —
one test per defect that had a concrete repro."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsView

from framedraft.canvas.scene import FrameScene
from framedraft.document import Layer, TextObject
from helpers import closed_diamond, line


def _view(scene, zoom=1.0, center=(0.0, 0.0)):
    view = QGraphicsView(scene)
    view.resize(800, 600)
    view.scale(zoom, zoom)
    view.centerOn(*center)
    QApplication.processEvents()
    return view


def _scene_with(*curves):
    scene = FrameScene()
    for c in curves:
        scene.add_curve(c)
    return scene


# ═══════════════════════════════════════════ cursor tools pick the nearest curve


def _crossed_line():
    """A horizontal line with two verticals drawn AFTER it (so they sit on
    top), 4 mm apart around the click point (20, 0)."""
    h = line([(0, 0), (40, 0)])
    v1 = line([(18, -10), (18, 10)])
    v2 = line([(22, -10), (22, 10)])
    return h, v1, v2


def test_trim_acts_on_the_curve_under_the_cursor_not_the_topmost():
    from framedraft.tools.trim import TrimTool
    h, v1, v2 = _crossed_line()
    scene = _scene_with(h, v1, v2)
    # At 400 % the 8 px hit box reaches 2 mm either side: both verticals are in it.
    view = _view(scene, zoom=4.0, center=(20, 0))
    tool = TrimTool()
    got = []
    tool.trim_applied.connect(lambda orig, rest: got.append((orig, rest)))
    tool.activate(scene, view, lambda: [h, v1, v2])

    tool.handle_press(QPointF(20, 0))

    [(orig, rest)] = got
    assert orig is h, "trimmed a neighbor instead of the line clicked on"
    ends = sorted(round(n.x, 3) for c in rest for n in (c.nodes[0], c.nodes[-1]))
    assert ends == [0.0, 18.0, 22.0, 40.0]


@pytest.mark.parametrize("module, cls", [
    ("split", "SplitTool"), ("fillet", "FilletTool"),
    ("offset", "OffsetTool"), ("rebuild", "RebuildSplineTool"),
])
def test_every_cursor_tool_picks_the_nearest_curve(module, cls):
    import importlib
    h, v1, v2 = _crossed_line()
    scene = _scene_with(h, v1, v2)
    view = _view(scene, zoom=4.0, center=(20, 0))
    tool = getattr(importlib.import_module(f"framedraft.tools.{module}"), cls)()
    tool._view = view
    assert tool._item_at(QPointF(20, 0)).curve is h
    assert tool._item_at(QPointF(21.8, 1.0)).curve is v2


def test_tie_keeps_the_topmost_curve():
    from framedraft.tools.trim import curve_item_at
    a = line([(0, 0), (40, 0)])
    b = line([(0, 0), (40, 0)])          # drawn later, on top, same place
    scene = _scene_with(a, b)
    view = _view(scene, zoom=4.0, center=(20, 0))
    assert curve_item_at(view, QPointF(20, 0)).curve is b


def test_nearest_pick_skips_locked_layers():
    from framedraft.tools.trim import curve_item_at
    ref = line([(0, 0), (40, 0)], layer=Layer.REF)
    lens = line([(0, 0.5), (40, 0.5)], layer=Layer.LENS)
    scene = _scene_with(ref, lens)
    scene.set_layer_locked(Layer.REF, True)
    view = _view(scene, center=(20, 0))
    assert curve_item_at(view, QPointF(20, 0)).curve is lens


# ═══════════════════════════════════════════ split: only real, unlocked crossings


def _split(scene, curves, click):
    from framedraft.tools.split import SplitTool
    tool = SplitTool()
    got, msgs = [], []
    tool.split_applied.connect(got.append)
    tool.status_message.connect(msgs.append)
    tool.activate(scene, _view(scene, center=(30, 10)), lambda: curves)
    tool.handle_press(click)
    return got, msgs


def test_split_leaves_a_crossing_curve_on_a_locked_layer_whole():
    ref = line([(10, 10), (50, 10)], layer=Layer.REF)
    lens = line([(30, -10), (30, 30)], layer=Layer.LENS)
    scene = _scene_with(ref, lens)
    scene.set_layer_locked(Layer.LENS, True)

    [pairs], msgs = _split(scene, [ref, lens], QPointF(30.5, 10))

    assert [orig for orig, _ in pairs] == [ref]
    left, _right = pairs[0][1]
    assert left.nodes[-1].x == pytest.approx(30.0, abs=1e-3)   # still snapped
    assert "also split" not in msgs[-1]


def test_split_still_splits_an_unlocked_crossing_curve():
    ref = line([(10, 10), (50, 10)], layer=Layer.REF)
    lens = line([(30, -10), (30, 30)], layer=Layer.LENS)
    scene = _scene_with(ref, lens)

    [pairs], msgs = _split(scene, [ref, lens], QPointF(30.5, 10))

    assert {id(orig) for orig, _ in pairs} == {id(ref), id(lens)}
    assert "+1 intersecting curve also split" in msgs[-1]


def test_split_does_not_cut_a_parallel_neighbor():
    a = line([(10, 10), (50, 10)], layer=Layer.REF)
    b = line([(10, 11.2), (50, 11.2)], layer=Layer.REF)     # 1.2 mm away, no crossing
    scene = _scene_with(a, b)

    [pairs], msgs = _split(scene, [a, b], QPointF(30, 9.9))

    assert [orig for orig, _ in pairs] == [a]
    assert "also split" not in msgs[-1]


# ═══════════════════════════════════════════════════════════════ HUD states


def test_undoing_the_only_node_hides_the_length_hud():
    from framedraft.tools.draw import DrawTool
    scene = FrameScene()
    view = _view(scene)
    tool = DrawTool()
    tool.activate("line", Layer.REF, scene, view)
    tool.handle_press(QPointF(0, 0), use_snap=False)
    tool.handle_move(QPointF(10, 5), use_snap=False)
    assert not tool._hud.isHidden()

    assert tool.undo_last_point()
    assert tool._hud.isHidden()
    tool.handle_move(QPointF(20, 20), use_snap=False)
    assert tool._hud.isHidden(), "stale length came back on the next move"


def test_arc_step_back_to_the_radius_stage_restores_the_measure_bar():
    from framedraft.canvas.measure_bar import MeasureBar
    from framedraft.tools.circle import CircleTool
    scene = FrameScene()
    view = _view(scene)
    bar = MeasureBar(view)
    tool = CircleTool()
    tool.activate("arc", Layer.REF, scene, view, measure_bar=bar)

    tool.handle_press(QPointF(0, 0), use_snap=False)          # center
    assert not bar.isHidden()
    tool.handle_press(QPointF(10, 0), use_snap=False)         # start → end stage
    assert bar.isHidden()

    assert tool.handle_key(Qt.Key.Key_Escape)                  # back to radius stage
    assert tool._state == 1
    assert not bar.isHidden()
    tool.handle_move(QPointF(12, 3), use_snap=False)
    assert not bar.isHidden()


# ═══════════════════════════════════════════════ Edit Text round-trips values


@pytest.mark.parametrize("size, anchor_x, rotation", [
    (0.5, 1500.0, 0.0),        # below the old 1 mm floor, past the old ±1000
    (80.0, -2500.0, 30.0),     # above the old 50 mm cap
    (0.1875, 12.34567, 400.0), # finer than the spin shows; outside ±360
])
def test_edit_text_ok_without_changes_keeps_every_value(size, anchor_x, rotation):
    from framedraft.tools.text import TextDialog
    t = TextObject(text="AB", family="", size_mm=size, rotation=rotation,
                   anchor_x=anchor_x, anchor_y=-7.25, layer=Layer.ENGRAVING)
    v = TextDialog(None, t).values()
    assert (v["size_mm"], v["anchor_x"], v["anchor_y"], v["rotation"]) == \
           (size, anchor_x, -7.25, rotation)


def test_edit_text_takes_an_edited_value():
    from framedraft.tools.text import TextDialog
    t = TextObject(text="AB", family="", size_mm=0.1875, rotation=0.0,
                   anchor_x=0.0, anchor_y=0.0, layer=Layer.ENGRAVING)
    dlg = TextDialog(None, t)
    dlg._size_spin.setValue(0.4)
    assert dlg.values()["size_mm"] == pytest.approx(0.4)


# ═══════════════════════════════════════════ PDF exports fail loudly when unwritable


def test_template_pdf_to_an_unwritable_path_raises(tmp_path):
    from framedraft.export.template_print import export_template_pdf
    comps = {"front":    {"curves": [closed_diamond(0, 0, 20)], "texts": []},
             "temple_r": {"curves": [], "texts": []},
             "temple_l": {"curves": [], "texts": []}}
    out = tmp_path / "no-such-folder" / "templates.pdf"
    with pytest.raises(OSError, match="could not write"):
        export_template_pdf(str(out), comps, {"paper": "letter"}, "M")
    assert not out.exists()


def test_catalog_pdf_to_an_unwritable_path_raises(tmp_path):
    from framedraft.export.catalog_pdf import export_catalog_pdf
    comps = {"front": [closed_diamond(0, 0, 20, layer=Layer.OUTLINE)],
             "temple_r": [], "temple_l": []}
    out = tmp_path / "no-such-folder" / "catalog.pdf"
    with pytest.raises(OSError, match="could not write"):
        export_catalog_pdf(str(out), comps, {"paper": "a5"}, "M")
    assert not out.exists()


# ═══════════════════════════════════════════════════ the seam of a closed curve

def test_a_split_at_the_seam_opens_the_curve_without_a_sliver():
    """Opening at the seam used to concatenate a zero-length piece: two
    coincident nodes with degenerate handles (an OMA lens's seam sits on the
    datum line, so a Split snapped to that crossing hit it every time)."""
    from framedraft.geometry import split_curve_at_t
    from helpers import line
    sq = line([(0, 0), (60, 0), (60, 60), (0, 60)], closed=True)
    opened, other = split_curve_at_t(sq, 0.0)
    assert other is None and not opened.closed
    pts = [(round(n.x, 6), round(n.y, 6)) for n in opened.nodes]
    assert pts == [(0, 0), (60, 0), (60, 60), (0, 60), (0, 0)]
    assert all(a != b for a, b in zip(pts, pts[1:], strict=False))       # no repeated node


def test_the_nearest_point_on_the_closing_segment_is_found():
    """A point on the closing segment, near the seam, resolved to t = 0: a
    Split opened 0.9 mm from the click and a Trim cut the wrong side."""
    import math
    from framedraft.geometry import point_at_t, split_curve_at_t, t_nearest
    from helpers import line
    sq = line([(0, 0), (60, 0), (60, 60), (0, 60)], closed=True)
    t = t_nearest(sq, 0.0, 0.9)
    x, y = point_at_t(sq, t)
    assert math.isclose(x, 0.0, abs_tol=1e-6) and math.isclose(y, 0.9, abs_tol=1e-3)
    opened, _ = split_curve_at_t(sq, t)
    pts = [(round(n.x, 3), round(n.y, 3)) for n in opened.nodes]
    assert pts[0] == (0.0, 0.9) and pts[-1] == (0.0, 0.9)
    assert all(a != b for a, b in zip(pts, pts[1:], strict=False))


def test_a_circle_cut_at_its_zero_point_splits_opposite():
    """A datum line through a hole's center meets its circle at 0°, which the
    split treated as an endpoint and left the circle whole."""
    from framedraft.geometry import split_curve_at_t
    from helpers import circle
    a, b = split_curve_at_t(circle(30, 10, 5), 0.0)
    assert a is not None and b is not None
    assert {a.kind, b.kind} == {"arc"}
    assert sorted([a.start_angle, a.end_angle]) == [0.0, 180.0]
    assert sorted([b.start_angle, b.end_angle]) == [0.0, 180.0]


def test_hover_ranking_uses_the_coarse_grid():
    import time
    from framedraft.tools.trim import _curve_dist_mm
    from helpers import spline
    import math
    pts = [(50 * math.cos(i / 500 * 2 * math.pi), 30 * math.sin(i / 500 * 2 * math.pi))
           for i in range(500)]
    dense = spline(pts, closed=True)
    t0 = time.perf_counter()
    for _ in range(10):
        d = _curve_dist_mm(dense, 55.0, 0.0)
    per_call = (time.perf_counter() - t0) / 10
    assert abs(d - 5.0) < 0.05
    assert per_call < 0.02, per_call                        # was ~37 ms
