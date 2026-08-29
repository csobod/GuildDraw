"""Lens Fill overlay — one vertical gradient painted into each LENS aperture.

Runs against a real (offscreen) FrameScene because the fill is Qt path ops;
conftest provides the shared QApplication.
"""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

from framedraft.canvas.scene import (FrameScene, DEFAULT_LENS_FILL_TOP,
                                     DEFAULT_LENS_FILL_BOTTOM,
                                     LENS_FILL_INTENSITY_MAX,
                                     LENS_FILL_INTENSITY_MIN, deepen_tint,
                                     intensity_from_slider,
                                     slider_from_intensity)
from framedraft.document import Layer
from helpers import circle, closed_diamond, spline


def _scene(*curves):
    scene = FrameScene()
    for c in curves:
        scene.add_curve(c)
    return scene


def test_one_fill_item_per_lens():
    scene = _scene(circle(-15, 0, 8), circle(15, 0, 8))
    assert scene.set_lens_fill_visible(True) == "ok"
    assert len(scene._lens_fill_items) == 2


def test_fill_covers_the_lens_and_nothing_else():
    scene = _scene(circle(-15, 0, 8))
    scene.set_lens_fill_visible(True)
    path = scene._lens_fill_items[0].path()
    assert path.contains(QPointF(-15, 0))
    assert not path.contains(QPointF(15, 0))


def test_outline_is_not_tinted():
    # The frame body belongs to Frame Fill; Lens Fill only ever paints LENS.
    scene = _scene(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    assert scene.set_lens_fill_visible(True) == "empty"
    assert scene._lens_fill_items == []


def test_gradient_runs_top_to_bottom_within_each_lens():
    # Each lens gets its own run of the gradient, so a pair reads as two
    # matching tinted lenses rather than slices of one shared gradient.
    scene = _scene(circle(-15, -30, 8), circle(15, 40, 8))
    scene.set_lens_fill_visible(True)
    for item in scene._lens_fill_items:
        stops = item.brush().gradient().stops()
        rect  = item.path().boundingRect()
        grad  = item.brush().gradient()
        assert len(stops) == 2
        assert abs(grad.start().y() - rect.top()) < 1e-6
        assert abs(grad.finalStop().y() - rect.bottom()) < 1e-6
        assert stops[0][1].name() == DEFAULT_LENS_FILL_TOP
        assert stops[1][1].name() == DEFAULT_LENS_FILL_BOTTOM


def test_opacity_applies_to_both_stops():
    scene = _scene(circle(0, 0, 8))
    scene.set_lens_fill_opacity(0.4)
    scene.set_lens_fill_visible(True)
    stops = scene._lens_fill_items[0].brush().gradient().stops()
    assert all(abs(c.alphaF() - 0.4) < 1e-3 for _pos, c in stops)


def test_colors_round_trip_through_state():
    scene = _scene(circle(0, 0, 8))
    scene.set_lens_fill_colors("#112233", "#445566")
    scene.set_lens_fill_opacity(0.65)
    scene.set_lens_fill_visible(True)
    assert scene.lens_fill_state() == {
        "visible": True, "top": "#112233",
        "bottom": "#445566", "opacity": 0.65, "intensity": 1.0,
    }


def test_open_lens_reports_leak_and_stays_hidden():
    open_arc = spline([(0, 0), (10, -10), (20, 0)], closed=False, layer=Layer.LENS)
    scene = _scene(open_arc)
    assert scene.set_lens_fill_visible(True) == "leak"
    assert scene._lens_fill_items == []


def test_edit_that_opens_every_lens_turns_the_fill_off():
    lens = closed_diamond(0, 0, 12, layer=Layer.LENS)
    scene = _scene(lens)
    assert scene.set_lens_fill_visible(True) == "ok"
    seen = []
    scene.lens_fill_auto_disabled = seen.append

    lens.closed = False
    lens.nodes = lens.nodes[:2]      # a bare open segment encloses nothing
    scene.refresh_curve(lens)
    scene.rebuild_lens_fill()

    assert seen == ["leak"]
    assert scene.lens_fill_state()["visible"] is False
    assert scene._lens_fill_items == []


def test_hidden_lens_layer_is_not_tinted():
    scene = _scene(circle(0, 0, 8))
    scene.set_lens_fill_visible(True)
    scene.set_layer_visible(Layer.LENS, False)
    assert scene._lens_fill_items == []


def test_frame_fill_and_lens_fill_stack_without_fighting():
    # The lens apertures are punched out of the frame fill, and the lens tint
    # sits just above it, so the two overlays occupy the same hole cleanly.
    scene = _scene(closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
                   circle(-15, 0, 8), circle(15, 0, 8))
    assert scene.set_fill_visible(True) == "ok"
    assert scene.set_lens_fill_visible(True) == "ok"
    assert not scene._fill_item.path().contains(QPointF(-15, 0))
    assert scene._lens_fill_items[0].zValue() > scene._fill_item.zValue()
    assert scene._lens_fill_items[0].zValue() < 0


# ------------------------------------------------------------------ intensity


def test_intensity_of_one_is_the_colour_as_picked():
    assert deepen_tint("#cbeafc", 1.0).name() == "#cbeafc"


def test_raising_intensity_deepens_without_leaving_the_hue():
    pale = "#e4f5fd"                      # a BPI-style tint sampled over white
    deep = deepen_tint(pale, 4.0)
    base = QColor(pale)
    # Every channel darkens…
    assert (deep.red() < base.red() and deep.green() < base.green()
            and deep.blue() < base.blue())
    # …but the blue stays dominant: the channel that transmits most still does.
    assert deep.blue() > deep.green() > deep.red()
    assert abs(deep.hueF() - base.hueF()) < 0.02


def test_lowering_intensity_thins_the_tint():
    thin = deepen_tint("#4a9fd8", 0.5)
    base = QColor("#4a9fd8")
    assert thin.red() > base.red() and thin.blue() > base.blue()


def test_no_channel_ever_clamps():
    # The failure mode of scaling distance-from-white: a channel hits 0 and the
    # hue shifts. Beer-Lambert on transmission cannot leave 0…1.
    for hex_ in ("#b0a0cd", "#aaab9f", "#010203", "#ffffff", "#000000"):
        for k in (LENS_FILL_INTENSITY_MIN, 1.0, 4.0, LENS_FILL_INTENSITY_MAX):
            c = deepen_tint(hex_, k)
            assert all(0 <= v <= 255 for v in (c.red(), c.green(), c.blue()))


def test_intensity_is_clamped_to_the_supported_range():
    assert (deepen_tint("#808080", 99.0).name()
            == deepen_tint("#808080", LENS_FILL_INTENSITY_MAX).name())
    assert (deepen_tint("#808080", 0.0).name()
            == deepen_tint("#808080", LENS_FILL_INTENSITY_MIN).name())


def test_alpha_survives_deepening():
    c = QColor("#4a9fd8")
    c.setAlphaF(0.65)
    assert abs(deepen_tint(c, 3.0).alphaF() - 0.65) < 1e-3


def test_default_slider_position_is_the_colour_as_picked():
    assert intensity_from_slider(slider_from_intensity(1.0)) == pytest.approx(1.0)


def test_slider_spans_the_whole_range_monotonically():
    assert intensity_from_slider(0) == pytest.approx(LENS_FILL_INTENSITY_MIN)
    assert intensity_from_slider(100) == pytest.approx(LENS_FILL_INTENSITY_MAX)
    seq = [intensity_from_slider(p) for p in range(0, 101, 5)]
    assert all(b > a for a, b in zip(seq, seq[1:], strict=False))


def test_slider_round_trips_at_every_position():
    for pos in range(0, 101):
        assert slider_from_intensity(intensity_from_slider(pos)) == pos


def test_intensity_reaches_the_painted_gradient():
    scene = _scene(circle(0, 0, 8))
    scene.set_lens_fill_colors("#e4f5fd", "#e4f5fd")
    scene.set_lens_fill_opacity(1.0)
    scene.set_lens_fill_visible(True)
    before = scene._lens_fill_items[0].brush().gradient().stops()[0][1].name()

    scene.set_lens_fill_intensity(4.0)
    after = scene._lens_fill_items[0].brush().gradient().stops()[0][1].name()
    assert after == deepen_tint("#e4f5fd", 4.0).name()
    assert after != before


def test_intensity_and_opacity_are_independent():
    scene = _scene(circle(0, 0, 8))
    scene.set_lens_fill_opacity(0.4)
    scene.set_lens_fill_intensity(5.0)
    scene.set_lens_fill_visible(True)
    stops = scene._lens_fill_items[0].brush().gradient().stops()
    # Deepening changes the colour; it must not touch how much shows through.
    assert all(abs(c.alphaF() - 0.4) < 1e-3 for _pos, c in stops)
    assert stops[0][1].name() == deepen_tint(DEFAULT_LENS_FILL_TOP, 5.0).name()
