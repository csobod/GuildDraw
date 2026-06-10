"""M8 — text outlines (textpath) and fill/texts persistence.

QPainterPath.addText needs font metrics, which need a QGuiApplication
(no windows are created). The default platform plugin is used because the
offscreen one exposes NO system fonts — every glyph degrades to the box
fallback. Tests that depend on real glyph topology skip when no fonts
are available.
"""
import math

import pytest
from PySide6.QtGui import QFontDatabase, QGuiApplication

if QGuiApplication.instance() is None:
    _APP = QGuiApplication([])

_HAS_FONTS = bool(QFontDatabase.families())

from framedraft.document import Layer, TextObject  # noqa: E402
from framedraft.textpath import text_outline_path, text_to_curves  # noqa: E402
from framedraft.export.svg import save_svg, load_svg  # noqa: E402
from framedraft.document import (  # noqa: E402
    Calibration, MirrorAxis, FormingMetadata, MachinedBridge,
)


def _bbox(curves):
    xs, ys = [], []
    for c in curves:
        for n in c.nodes:
            xs.append(n.x)
            ys.append(n.y)
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# textpath
# ---------------------------------------------------------------------------

def test_text_to_curves_closed_splines_on_layer():
    t = TextObject(text="GUILD", family="Arial", size_mm=5.0)
    curves = text_to_curves(t)
    assert curves, "no curves produced"
    assert all(c.kind == "spline" and c.closed for c in curves)
    assert all(c.layer == Layer.ENGRAVING for c in curves)


def test_text_size_is_cap_height_mm():
    t = TextObject(text="HE", family="Arial", size_mm=5.0,
                   anchor_x=10.0, anchor_y=-3.0)
    x0, y0, x1, y1 = _bbox(text_to_curves(t))
    # cap-only string: glyph height == cap height == size_mm (±5 %)
    assert abs((y1 - y0) - 5.0) < 0.25, f"height {(y1 - y0):.3f}"
    # baseline-left anchor: text starts at anchor_x, sits on anchor_y (y-down)
    assert abs(x0 - 10.0) < 1.0
    assert abs(y1 - (-3.0)) < 0.25            # baseline
    assert abs(y0 - (-3.0 - 5.0)) < 0.25      # top = baseline − cap height


def test_text_rotation_ccw():
    flat = _bbox(text_to_curves(
        TextObject(text="HHH", family="Arial", size_mm=5.0)))
    rot = _bbox(text_to_curves(
        TextObject(text="HHH", family="Arial", size_mm=5.0, rotation=90.0)))
    w_flat, h_flat = flat[2] - flat[0], flat[3] - flat[1]
    w_rot,  h_rot  = rot[2] - rot[0],  rot[3] - rot[1]
    assert abs(w_rot - h_flat) < 0.01 and abs(h_rot - w_flat) < 0.01
    # +90° CCW from the anchor sends the text upward: scene y-down ⇒ y0 < 0
    assert rot[3] <= 0.01 and rot[1] < -w_flat / 2


@pytest.mark.skipif(not _HAS_FONTS, reason="no system fonts in this Qt platform")
def test_text_path_subpaths_match_curves():
    t = TextObject(text="O", family="Arial", size_mm=8.0)
    curves = text_to_curves(t)
    assert len(curves) == 2, "an 'O' is an outline plus a counter"
    # the counter must sit inside the outline
    outer = max(curves, key=lambda c: _bbox([c])[2] - _bbox([c])[0])
    inner = min(curves, key=lambda c: _bbox([c])[2] - _bbox([c])[0])
    ob, ib = _bbox([outer]), _bbox([inner])
    assert ob[0] < ib[0] and ib[2] < ob[2] and ob[1] < ib[1] and ib[3] < ob[3]


def test_outline_path_is_anchored():
    t = TextObject(text="E", family="Arial", size_mm=5.0,
                   anchor_x=25.0, anchor_y=7.0)
    br = text_outline_path(t).boundingRect()
    assert abs(br.left() - 25.0) < 1.0
    assert abs(br.bottom() - 7.0) < 0.25


# ---------------------------------------------------------------------------
# Persistence: "texts" and "fill" keys round-trip through SVG
# ---------------------------------------------------------------------------

def test_svg_roundtrip_texts_and_fill(tmp_path):
    path = str(tmp_path / "t.svg")
    texts = [TextObject(text="LEFT", family="Georgia", size_mm=4.5,
                        rotation=12.0, anchor_x=1.5, anchor_y=-2.25,
                        layer=Layer.ENGRAVING, line_weight=0.8)]
    fill = {"visible": True, "color": "#aa3366", "opacity": 0.35}
    save_svg(curves=[], path=path, calibration=Calibration(),
             mirror=MirrorAxis(), forming=FormingMetadata(),
             machined_bridge=MachinedBridge(), texts=texts, fill=fill)
    data = load_svg(path)
    assert data["fill"] == fill
    [t] = data["texts"]
    assert (t.text, t.family, t.layer) == ("LEFT", "Georgia", Layer.ENGRAVING)
    assert math.isclose(t.size_mm, 4.5) and math.isclose(t.rotation, 12.0)
    assert math.isclose(t.anchor_x, 1.5) and math.isclose(t.anchor_y, -2.25)
    assert math.isclose(t.line_weight, 0.8)


def test_svg_without_m8_keys_loads_with_defaults(tmp_path):
    path = str(tmp_path / "old.svg")
    save_svg(curves=[], path=path, calibration=Calibration(),
             mirror=MirrorAxis(), forming=FormingMetadata(),
             machined_bridge=MachinedBridge())
    data = load_svg(path)
    assert data["fill"] is None
    assert data["texts"] == []
