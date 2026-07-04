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


def test_tangent_snap_from_anchor_to_circle():
    from framedraft.document import SplineNode
    _s, view, eng = _engine([circle(0, 0, 5)])
    eng.set_enabled_types(_only("tangent"))
    anchor = [SplineNode(10.0, 0.0)]           # d=10, r=5 → tangents at ±60°

    p = eng.snap(QPointF(2.9, 4.2), anchor, view)   # near the upper tangent pt
    assert (p.x(), p.y()) == pytest.approx((2.5, 4.3301), abs=1e-2)

    # No anchor (not mid-draw) → tangent produces nothing.
    p2 = eng.snap(QPointF(2.9, 4.2), [], view)
    assert (p2.x(), p2.y()) == (2.9, 4.2)

    # Anchor inside the circle → no tangent exists.
    p3 = eng.snap(QPointF(2.9, 4.2), [SplineNode(1.0, 0.0)], view)
    assert (p3.x(), p3.y()) == (2.9, 4.2)


def test_perpendicular_snap_from_anchor_to_line():
    from framedraft.document import SplineNode
    _s, view, eng = _engine([line([(0, 0), (0, 20)])])   # vertical line x=0
    eng.set_enabled_types(_only("perpendicular"))
    anchor = [SplineNode(8.0, 6.0)]                       # foot is (0, 6)

    p = eng.snap(QPointF(0.4, 6.3), anchor, view)
    assert (p.x(), p.y()) == pytest.approx((0.0, 6.0), abs=1e-6)


def test_perpendicular_snap_to_circle_is_radial():
    from framedraft.document import SplineNode
    _s, view, eng = _engine([circle(0, 0, 5)])
    eng.set_enabled_types(_only("perpendicular"))
    anchor = [SplineNode(10.0, 0.0)]           # radial feet at (5,0) and (-5,0)

    p = eng.snap(QPointF(5.3, 0.2), anchor, view)
    assert (p.x(), p.y()) == pytest.approx((5.0, 0.0), abs=1e-6)


def test_snap_palette_context_toggles_grey_out():
    from framedraft.snap_palette import SnapPalette
    pal = SnapPalette(None)
    assert pal._btns["tangent"].isEnabled() is False        # no draw at startup
    assert pal._btns["perpendicular"].isEnabled() is False
    pal.set_context_available(True)
    assert pal._btns["tangent"].isEnabled() is True
    # Disabling never loses the checked value — the engine just finds no target.
    assert pal.state()["tangent"] is True


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


def test_snap_palette_is_icon_only_with_named_tooltips():
    from framedraft.snap_palette import SnapPalette
    pal = SnapPalette(None)
    for key, btn in pal._btns.items():
        assert btn.text() == ""                 # icon only — no text on button
        assert not btn.icon().isNull()          # …but has an icon
        assert btn.toolTip()                    # …and the name lives in the tooltip
    # Endpoint's tooltip carries its label.
    assert pal._btns["endpoint"].toolTip().startswith("Endpoint")


def test_snap_palette_radius_field_has_no_arrows_and_clamps():
    from PySide6.QtWidgets import QAbstractSpinBox
    from framedraft.snap_palette import SnapPalette
    pal = SnapPalette(None)
    assert (pal._radius.buttonSymbols()
            == QAbstractSpinBox.ButtonSymbols.NoButtons)
    pal.set_state({}, 999)                       # unwieldy value clamps to max
    assert pal._radius.value() == 40
    assert pal._radius.maximum() == 40
