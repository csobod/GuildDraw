"""PDF-for-Catalog export: component gathering, layout render, PDF write."""
import os

from PySide6.QtGui import QImage, QPainter, QColor

from framedraft.document import Curve, SplineNode, Layer
from framedraft.geometry import compute_catmull_handles
from framedraft.export.catalog_pdf import (
    paint_catalog, export_catalog_pdf, _content_bbox, PAPER_MM,
)


def _spline(pts, layer, closed=True):
    ns = [SplineNode(x=x, y=y) for x, y in pts]
    compute_catmull_handles(ns, closed)
    return Curve(kind="spline", layer=layer, nodes=ns, closed=closed)


def _sample_components():
    front = [_spline([(8, 0), (24, -16), (42, 0), (24, 17)], Layer.OUTLINE),
             _spline([(10, 0), (24, -13), (39, 0), (24, 14)], Layer.LENS)]
    temple = [_spline([(0, 0), (60, -3), (145, 2), (145, 10), (60, 9), (0, 8)],
                      Layer.OUTLINE)]
    return {"front": front, "temple_r": temple, "temple_l": list(temple)}


_SETTINGS = {
    "paper": "a5", "line_weight_mm": 0.6, "caption": True,
    "caption_font": "Courier New", "show_scale": False,
    "front_layers": ["OUTLINE", "LENS"], "temple_layers": ["OUTLINE"],
}


def _render(components, settings, caption, ink_probe=True):
    pw, ph = PAPER_MM["a5"][1], PAPER_MM["a5"][0]   # landscape
    ppm = 150 / 25.4
    img = QImage(round(pw * ppm), round(ph * ppm), QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    paint_catalog(p, pw, ph, ppm, components, caption, settings)
    p.end()
    return img


def _ink_count(img):
    return sum(1 for x in range(0, img.width(), 6) for y in range(0, img.height(), 6)
               if img.pixelColor(x, y) != QColor("#ffffff"))


def test_content_bbox_covers_geometry():
    c = _spline([(0, 0), (10, -5), (20, 0), (10, 8)], Layer.OUTLINE)
    bb = _content_bbox([c])
    assert bb is not None
    assert bb[0] <= 0 and bb[2] >= 20 and bb[1] <= -5 and bb[3] >= 8


def test_content_bbox_none_when_empty():
    assert _content_bbox([]) is None


def test_paint_draws_all_components_and_caption():
    img = _render(_sample_components(), _SETTINGS, "ACETATE-52-18-145")
    # a good amount of ink (three components + caption)
    assert _ink_count(img) > 200
    # caption is in the lower-right quadrant → that region has ink
    w, h = img.width(), img.height()
    lower_right = sum(
        1 for x in range(w * 3 // 4, w, 4) for y in range(h * 4 // 5, h, 4)
        if img.pixelColor(x, y) != QColor("#ffffff"))
    assert lower_right > 0, "no caption ink in the lower-right corner"


def test_paint_empty_components_is_noop():
    img = _render({"front": [], "temple_r": [], "temple_l": []}, _SETTINGS, "x")
    assert _ink_count(img) == 0


def test_caption_off_removes_lower_right_ink():
    s = {**_SETTINGS, "caption": False}
    img = _render(_sample_components(), s, "SHOULD-NOT-APPEAR")
    w, h = img.width(), img.height()
    lower_right = sum(
        1 for x in range(w * 3 // 4, w, 4) for y in range(h * 9 // 10, h, 4)
        if img.pixelColor(x, y) != QColor("#ffffff"))
    assert lower_right == 0


def test_export_writes_a_pdf(tmp_path):
    out = tmp_path / "catalog.pdf"
    export_catalog_pdf(str(out), _sample_components(), _SETTINGS, "MODEL-A")
    assert out.exists() and os.path.getsize(out) > 1000
    assert out.read_bytes()[:5] == b"%PDF-"


def test_export_half_letter(tmp_path):
    out = tmp_path / "hl.pdf"
    export_catalog_pdf(str(out), _sample_components(),
                       {**_SETTINGS, "paper": "half_letter"}, "MODEL-B")
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"


def _ink_centroid_y(img):
    total = wsum = 0
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            if img.pixelColor(x, y) != QColor("#ffffff"):
                total += 1
                wsum += y
    return (wsum / total) if total else 0.0


def test_content_offset_shifts_drawing_down_not_caption():
    """The vertical offset moves the drawing (front + temples) down the page;
    the caption stays pinned to the corner."""
    comps = _sample_components()
    centred = _render(comps, {**_SETTINGS, "content_offset_mm": 0.0}, "NAME")
    shifted = _render(comps, {**_SETTINGS, "content_offset_mm": 20.0}, "NAME")
    # ink overall moves down; a +20 mm shift at 150 dpi ≈ +118 px
    assert _ink_centroid_y(shifted) > _ink_centroid_y(centred) + 30
    # caption still present in the lower-right corner in both
    for img in (centred, shifted):
        w, h = img.width(), img.height()
        lr = sum(1 for x in range(w * 3 // 4, w, 4) for y in range(h * 4 // 5, h, 4)
                 if img.pixelColor(x, y) != QColor("#ffffff"))
        assert lr > 0
