"""Snap palette (M19) — per-type gating, intersection snap, radius, widget.

The engine measures in screen px via view.mapFromScene; an unscaled
QGraphicsView has an identity transform, so px distances equal scene mm
(±1 px from integer mapping) and the tests can reason in mm.
"""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsView

from framedraft.canvas.scene import FrameScene
from framedraft.canvas.snapping import SnapEngine, SNAP_TYPE_KEYS
from framedraft.geometry import curve_intersections

from helpers import circle, line


def _engine(curves):
    scene = FrameScene()
    view = QGraphicsView(scene)
    eng = SnapEngine(scene)
    eng.set_doc_curves(list(curves))
    return scene, view, eng


def _only(*keys):
    return {k: (k in keys) for k in SNAP_TYPE_KEYS}


def test_endpoint_and_node_are_distinct_types():
    _s, view, eng = _engine([line([(0, 0), (10, 0), (20, 0)])])

    eng.set_enabled_types(_only("endpoint"))
    p = eng.snap(QPointF(0.4, 0.4), [], view)
    assert (p.x(), p.y()) == (0.0, 0.0)          # endpoint snaps

    p = eng.snap(QPointF(10.4, 0.4), [], view)
    assert (p.x(), p.y()) == (10.4, 0.4)         # interior node does NOT

    eng.set_enabled_types(_only("node"))
    p = eng.snap(QPointF(10.4, 0.4), [], view)
    assert (p.x(), p.y()) == (10.0, 0.0)         # …until node is enabled


def test_center_and_quadrant_types():
    _s, view, eng = _engine([circle(0, 0, 10)])

    eng.set_enabled_types(_only("center"))
    p = eng.snap(QPointF(0.5, 0.5), [], view)
    assert (p.x(), p.y()) == (0.0, 0.0)

    eng.set_enabled_types(_only("quadrant"))
    p = eng.snap(QPointF(9.6, 0.5), [], view)
    assert (p.x(), p.y()) == (10.0, 0.0)

    # With both off (and no fallbacks) the cursor passes through untouched.
    eng.set_enabled_types(_only())
    p = eng.snap(QPointF(0.5, 0.5), [], view)
    assert (p.x(), p.y()) == (0.5, 0.5)


def test_intersection_snap_finds_crossing():
    l1 = line([(0, 0), (10, 10)])
    l2 = line([(0, 10), (10, 0)])
    _s, view, eng = _engine([l1, l2])
    eng.set_enabled_types(_only("intersection"))

    p = eng.snap(QPointF(5.6, 5.3), [], view)
    assert (p.x(), p.y()) == pytest.approx((5.0, 5.0), abs=1e-6)
    assert eng._isect_cache                      # cached for the next move


def test_intersection_cache_invalidates_on_scene_revision():
    l1 = line([(0, 0), (10, 10)])
    l2 = line([(0, 10), (10, 0)])
    scene, view, eng = _engine([l1, l2])
    eng.set_enabled_types(_only("intersection"))
    eng.snap(QPointF(5.5, 5.5), [], view)
    assert eng._isect_cache

    # Move l2 so the crossing shifts; a revision bump must drop the cache.
    for n in l2.nodes:
        n.y += 4.0
    scene.revision += 1
    p = eng.snap(QPointF(7.4, 7.2), [], view)
    assert (p.x(), p.y()) == pytest.approx((7.0, 7.0), abs=1e-6)


def test_snap_radius_is_configurable():
    _s, view, eng = _engine([line([(0, 0), (20, 0)])])
    eng.set_enabled_types(_only("endpoint"))

    eng.set_radius_px(5)
    p = eng.snap(QPointF(8.0, 0.0), [], view)
    assert (p.x(), p.y()) == (8.0, 0.0)          # out of reach

    eng.set_radius_px(12)
    p = eng.snap(QPointF(8.0, 0.0), [], view)
    assert (p.x(), p.y()) == (0.0, 0.0)          # now within reach


def test_curve_intersections_helper():
    pts = curve_intersections(line([(0, 0), (10, 10)]),
                              line([(0, 10), (10, 0)]))
    assert len(pts) == 1
    assert pts[0] == pytest.approx((5.0, 5.0), abs=1e-6)
    assert curve_intersections(line([(0, 0), (1, 0)]),
                               line([(5, 5), (6, 5)])) == []


def test_snap_palette_widget_signals_and_state():
    from framedraft.snap_palette import SnapPalette
    pal = SnapPalette(None)

    got: list = []
    pal.types_changed.connect(got.append)
    pal._btns["midpoint"].setChecked(False)
    assert got and got[-1]["midpoint"] is False and got[-1]["endpoint"] is True

    # set_state installs without emitting.
    n = len(got)
    pal.set_state({"node": False}, 14)
    assert len(got) == n
    assert pal._btns["node"].isChecked() is False
    assert int(pal._radius.value()) == 14
    assert pal.state()["node"] is False
