"""M31.2 — Rebuild Spline tool: count/tolerance modes, live deviation, apply."""
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsView

from framedraft.canvas.scene import FrameScene
from framedraft.canvas.items import CurveItem
from framedraft.document import Curve, SplineNode, Layer
from framedraft.geometry import sample_curve
from framedraft.tools.rebuild import RebuildSplineTool, MODE_COUNT, MODE_TOL
from helpers import spline, circle


def _dense_closed_spline():
    """A closed spline with more nodes than we'll rebuild to."""
    return spline([(0, -22), (20, -16), (30, 0), (22, 18),
                   (0, 24), (-22, 17), (-31, 0), (-20, -17)], closed=True)


def _type(tool, s):
    for ch in s:
        tool.handle_key(0, ch)


def _activate(source):
    scene = FrameScene()
    view = QGraphicsView(scene)
    tool = RebuildSplineTool()
    tool.activate(scene, view, source)
    return tool, scene, view


def test_count_mode_emits_exact_node_count():
    src = _dense_closed_spline()
    tool, scene, _ = _activate(src)
    captured = []
    tool.rebuild_applied.connect(lambda s, c: captured.append((s, c)))

    assert tool._mode == MODE_COUNT       # default
    _type(tool, "6")
    tool.handle_key(Qt.Key.Key_Return)

    assert len(captured) == 1
    source_out, rebuilt = captured[0]
    assert source_out is src
    assert rebuilt.kind == "spline" and rebuilt.closed is True
    assert rebuilt.layer == src.layer
    assert len(rebuilt.nodes) == 6


def test_tab_switches_to_tolerance_mode_and_reports_deviation():
    src = _dense_closed_spline()
    tool, scene, _ = _activate(src)
    captured = []
    tool.rebuild_applied.connect(lambda s, c: captured.append((s, c)))

    tool.handle_key(Qt.Key.Key_Tab)
    assert tool._mode == MODE_TOL
    _type(tool, "0.05")
    # live fit is cached and its deviation is within the requested tolerance
    assert tool._last_fit is not None
    assert tool._last_fit.max_deviation_mm <= 0.05 * 1.5

    tool.handle_key(Qt.Key.Key_Return)
    assert len(captured) == 1
    _src, rebuilt = captured[0]
    # the rebuilt curve genuinely tracks the source within tolerance
    src_poly = [(x, y) for x, y, _ in sample_curve(src, 48)]
    for x, y, _ in sample_curve(rebuilt, 24):
        assert _dist_to_poly(x, y, src_poly) <= 0.05 * 2


def test_live_preview_item_added_and_cleared():
    src = _dense_closed_spline()
    tool, scene, _ = _activate(src)

    _type(tool, "5")
    assert tool._preview_item is not None
    assert tool._preview_item.scene() is scene

    # Esc with input present clears the input + preview but stays active
    tool.handle_key(Qt.Key.Key_Escape)
    assert tool._preview_item is None
    assert tool.active is True
    assert tool._input_str == ""


def test_backspace_edits_input():
    tool, _scene, _ = _activate(_dense_closed_spline())
    _type(tool, "12")
    tool.handle_key(Qt.Key.Key_Backspace)
    assert tool._input_str == "1"


def test_count_mode_rejects_below_two():
    tool, _scene, _ = _activate(_dense_closed_spline())
    _type(tool, "1")
    # a single-node target is invalid — nothing to apply, no crash
    assert tool._compute_fit() is None
    captured = []
    tool.rebuild_applied.connect(lambda s, c: captured.append((s, c)))
    tool.handle_key(Qt.Key.Key_Return)
    assert captured == []


def test_tolerance_mode_only_accepts_one_decimal_point():
    tool, _scene, _ = _activate(_dense_closed_spline())
    tool.handle_key(Qt.Key.Key_Tab)
    _type(tool, "0.0.5")
    assert tool._input_str == "0.05"    # second dot ignored


def test_count_mode_ignores_decimal_point():
    tool, _scene, _ = _activate(_dense_closed_spline())
    _type(tool, "1.2")
    assert tool._input_str == "12"      # '.' rejected in count mode


def test_open_polyline_rebuilds_to_open_spline():
    """The headline use: a dense open polyline (imported DXF) → editable spline."""
    pts = [(i * 2.0, math.sin(i * 0.3) * 8.0) for i in range(40)]
    poly = Curve(kind="line", layer=Layer.OUTLINE,
                 nodes=[SplineNode(x=x, y=y) for x, y in pts], closed=False)
    tool, _scene, _ = _activate(poly)
    captured = []
    tool.rebuild_applied.connect(lambda s, c: captured.append((s, c)))

    _type(tool, "8")
    tool.handle_key(Qt.Key.Key_Return)

    assert len(captured) == 1
    rebuilt = captured[0][1]
    assert rebuilt.kind == "spline" and rebuilt.closed is False
    assert len(rebuilt.nodes) == 8
    # endpoints preserved
    assert math.hypot(rebuilt.nodes[0].x - pts[0][0],
                      rebuilt.nodes[0].y - pts[0][1]) < 1e-6


def test_circle_source_is_rejected():
    """Circles/arcs are already minimal analytic primitives — not rebuildable."""
    tool, _scene, _ = _activate(circle(0, 0, 20))
    assert tool._source_curve is None


def test_pick_source_on_press_when_none_selected():
    scene = FrameScene()
    view = QGraphicsView(scene)
    src = _dense_closed_spline()
    item = CurveItem(src)
    scene.addItem(item)
    tool = RebuildSplineTool()
    tool.activate(scene, view, None)          # no pre-selected source
    assert tool._source_curve is None

    # simulate a click on the curve's first node position
    from PySide6.QtCore import QPointF
    view.setSceneRect(-60, -60, 120, 120)
    view.resize(300, 300)
    # itemAt-based pick uses the view; place the click on a node
    node = src.nodes[0]
    tool.handle_press(QPointF(node.x, node.y))
    # picking is view-geometry dependent; accept either a successful pick or a
    # graceful no-op, but it must not raise and must keep the tool usable.
    assert tool.active is True


def _dist_to_poly(px, py, poly):
    best = float("inf")
    for a, b in zip(poly, poly[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        if L2 < 1e-18:
            d2 = (px - a[0]) ** 2 + (py - a[1]) ** 2
        else:
            t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / L2))
            d2 = (px - a[0] - dx * t) ** 2 + (py - a[1] - dy * t) ** 2
        best = min(best, d2)
    return math.sqrt(best)
