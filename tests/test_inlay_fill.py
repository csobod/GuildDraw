"""Inlay Fill in the scene (BUILDPLAN *Road to 2.0*, item 7): one item per
closed INLAY body, above the frame fill, a color or an image cropped to each
body, and Tumble bodies, which turns each body's copy of the image in a way
that is the same on every repaint and every reopening."""
import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage

from framedraft.canvas.scene import (
    DEFAULT_INLAY_FILL_COLOR, DEFAULT_INLAY_FILL_OPACITY, FrameScene,
    inlay_image_transform,
)
from framedraft.document import Layer
from helpers import circle, closed_diamond, line


def _image(path, w=300, h=200, color="#30c0b0"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return str(path)


def _seat(cx, cy, r=6.0):
    return closed_diamond(cx, cy, r, layer=Layer.INLAY)


def _front(*inlays):
    scene = FrameScene()
    for c in (closed_diamond(0, 0, 45), circle(-17, 0, 11), circle(17, 0, 11),
              *inlays):
        scene.add_curve(c)
    return scene


def _covers(t, rect, img_w, img_h) -> bool:
    """True when the image placed by *t* covers every corner of *rect*."""
    inv, ok = t.inverted()
    assert ok
    for corner in (rect.topLeft(), rect.topRight(),
                   rect.bottomLeft(), rect.bottomRight()):
        p = inv.map(corner)
        if not (-1e-6 <= p.x() <= img_w + 1e-6 and -1e-6 <= p.y() <= img_h + 1e-6):
            return False
    return True


# ── The bodies ─────────────────────────────────────────────────────────────

def test_one_item_per_body_above_the_frame_fill_below_the_lenses():
    scene = _front(_seat(-12, -30), _seat(12, -30))
    assert scene.set_fill_visible(True) == "ok"
    assert scene.set_lens_fill_visible(True) == "ok"
    assert scene.set_inlay_fill_visible(True) == "ok"
    items = scene._inlay_fill_items
    assert len(items) == 2 and scene.inlay_body_count() == 2
    for it in items:
        assert scene._fill_item.zValue() < it.zValue() < scene._lens_fill_items[0].zValue()
        assert it.zValue() < 0                      # under the line work
        # A color carries its alpha in the brush; the item stays opaque.
        assert it.brush().color().name() == DEFAULT_INLAY_FILL_COLOR
        assert it.brush().color().alphaF() == pytest.approx(
            DEFAULT_INLAY_FILL_OPACITY, abs=0.01)
        assert it.opacity() == 1.0


def test_a_step_is_two_bodies_that_never_overlap():
    scene = _front(_seat(0, 28, 8), _seat(0, 28, 3))
    assert scene.set_inlay_fill_visible(True) == "ok"
    paths = [it.path() for it in scene._inlay_fill_items]
    assert len(paths) == 2
    center = QPointF(0, 28)
    in_ring = QPointF(0, 28 - 5.5)                  # between the two curves
    holders = [p for p in paths if p.contains(center)]
    assert len(holders) == 1                        # only the inner piece
    assert sum(p.contains(in_ring) for p in paths) == 1
    assert not holders[0].contains(in_ring)


def test_nothing_to_fill_is_empty_and_an_open_seat_alone_a_leak():
    scene = _front()
    assert scene.set_inlay_fill_visible(True) == "empty"
    assert not scene._inlay_fill_visible
    open_seat = line([(-5, -30), (0, -35), (5, -30)], layer=Layer.INLAY)
    scene.add_curve(open_seat)
    assert scene.set_inlay_fill_visible(True) == "leak"
    # Beside a closed seat, an open one is a seat under construction.
    scene.add_curve(_seat(20, -30))
    assert scene.set_inlay_fill_visible(True) == "ok"
    assert len(scene._inlay_fill_items) == 1


def test_hiding_the_layer_hides_the_fill_and_showing_it_brings_it_back():
    scene = _front(_seat(0, -30))
    assert scene.set_inlay_fill_visible(True) == "ok"
    scene.set_layer_visible(Layer.INLAY, False)
    assert scene._inlay_fill_items == [] and scene._inlay_fill_visible
    assert scene.inlay_body_count() == 0
    scene.set_layer_visible(Layer.INLAY, True)
    assert len(scene._inlay_fill_items) == 1


def test_an_edit_that_leaves_nothing_closed_turns_the_fill_off():
    seat = _seat(0, -30)
    scene = _front(seat)
    seen = []
    scene.inlay_fill_auto_disabled = seen.append
    assert scene.set_inlay_fill_visible(True) == "ok"
    scene.remove_curve(seat)
    scene.add_curve(line([(-5, -30), (0, -35), (5, -30)], layer=Layer.INLAY))
    scene._rebuild_overlays()                       # what the timer runs
    assert seen == ["leak"]
    assert not scene._inlay_fill_visible and scene._inlay_fill_items == []


def test_the_inlay_is_never_mirrored_into_a_ghost_body():
    scene = _front(_seat(12, -30))
    scene.init_mirror()
    scene.set_mirror_display(True)
    assert scene.set_inlay_fill_visible(True) == "ok"
    assert len(scene._inlay_fill_items) == 1        # drawn where it is cut


# ── Color and image ────────────────────────────────────────────────────────

def test_color_and_opacity_restyle_the_bodies_in_place():
    scene = _front(_seat(-12, -30), _seat(12, -30))
    scene.set_inlay_fill_visible(True)
    paths = [it.path() for it in scene._inlay_fill_items]
    scene.set_inlay_fill_color("#aa3311")
    scene.set_inlay_fill_opacity(0.4)
    for it, path in zip(scene._inlay_fill_items, paths, strict=True):
        assert it.path() == path
        assert it.brush().color().name() == "#aa3311"
        assert it.brush().color().alphaF() == pytest.approx(0.4, abs=0.01)
    assert scene.inlay_fill_state()["color"] == "#aa3311"


def test_an_image_covers_each_body_centered_on_it(tmp_path):
    scene = _front(_seat(-12, -30), line([(-30, 20), (30, 20), (30, 26), (-30, 26)],
                                         closed=True, layer=Layer.INLAY))
    assert scene.set_inlay_fill_image(_image(tmp_path / "stone.png", 300, 200))
    assert scene.set_inlay_fill_visible(True) == "ok"
    for it in scene._inlay_fill_items:
        brush = it.brush()
        assert brush.style() == Qt.BrushStyle.TexturePattern
        rect = it.path().boundingRect()
        t = brush.transform()
        assert t.map(QPointF(150, 100)).x() == pytest.approx(rect.center().x())
        assert t.map(QPointF(150, 100)).y() == pytest.approx(rect.center().y())
        assert _covers(t, rect, 300, 200)
        # A texture has no alpha of its own: the item fades it.
        assert it.opacity() == pytest.approx(DEFAULT_INLAY_FILL_OPACITY)


def test_an_unreadable_image_leaves_the_color(tmp_path):
    scene = _front(_seat(0, -30))
    bad = tmp_path / "not-an-image.png"
    bad.write_text("no")
    assert not scene.set_inlay_fill_image(str(bad))
    assert not scene.has_inlay_fill_image()
    scene.set_inlay_fill_visible(True)
    assert scene._inlay_fill_items[0].brush().style() == Qt.BrushStyle.SolidPattern


def test_clearing_the_image_goes_back_to_the_color_as_picked(tmp_path):
    scene = _front(_seat(0, -30))
    scene.set_inlay_fill_color("#123456")
    scene.set_inlay_fill_image(_image(tmp_path / "stone.png"))
    scene.set_inlay_fill_visible(True)
    scene.clear_inlay_fill_image()
    brush = scene._inlay_fill_items[0].brush()
    assert brush.style() == Qt.BrushStyle.SolidPattern
    assert brush.color().name() == "#123456"
    assert scene._inlay_fill_items[0].opacity() == 1.0


# ── Tumble bodies ──────────────────────────────────────────────────────────

def test_tumble_turns_each_body_differently(tmp_path):
    scene = _front(_seat(-12, -30), _seat(12, -30), _seat(0, 30))
    scene.set_inlay_fill_image(_image(tmp_path / "stone.png"))
    scene.set_inlay_fill_visible(True)
    plain = [it.brush().transform() for it in scene._inlay_fill_items]
    scene.set_inlay_fill_tumble(True)
    tumbled = [it.brush().transform() for it in scene._inlay_fill_items]
    assert all(a != b for a, b in zip(plain, tumbled, strict=True))
    # Each copy differs from the others in more than its position: the
    # linear part (turn, mirror, scale) is distinct body to body.
    linear = {(round(t.m11(), 6), round(t.m12(), 6), round(t.m21(), 6),
               round(t.m22(), 6)) for t in tumbled}
    assert len(linear) == 3
    scene.set_inlay_fill_tumble(False)
    assert [it.brush().transform() for it in scene._inlay_fill_items] == plain


def test_tumble_is_the_same_for_the_same_drawing_whatever_the_order(tmp_path):
    img = _image(tmp_path / "stone.png")
    seats = [(-12, -30), (12, -30), (0, 30)]

    def transforms(order):
        scene = _front(*[_seat(*seats[i]) for i in order])
        scene.set_inlay_fill_image(img)
        scene.set_inlay_fill_tumble(True)
        scene.set_inlay_fill_visible(True)
        return {(round(it.path().boundingRect().center().x(), 3),
                 round(it.path().boundingRect().center().y(), 3)):
                it.brush().transform() for it in scene._inlay_fill_items}

    first = transforms([0, 1, 2])
    assert transforms([2, 0, 1]) == first           # a reload, or a redraw
    assert transforms([0, 1, 2]) == first


@pytest.mark.parametrize("w,h", [(12, 12), (60, 6), (6, 25), (3, 3), (40, 20)])
@pytest.mark.parametrize("img_w,img_h", [(300, 200), (200, 300), (256, 256)])
def test_a_tumbled_copy_always_covers_its_body(w, h, img_w, img_h):
    rect = QRectF(-w / 2 + 7, -h / 2 - 3, w, h)
    for rank in range(24):
        t = inlay_image_transform(rect, img_w, img_h, rank)
        assert _covers(t, rect, img_w, img_h), (rank, w, h)
    plain = inlay_image_transform(rect, img_w, img_h)
    assert _covers(plain, rect, img_w, img_h)


def test_every_other_tumbled_copy_is_mirrored():
    rect = QRectF(0, 0, 10, 10)
    dets = [inlay_image_transform(rect, 300, 200, r).determinant()
            for r in range(6)]
    assert [d > 0 for d in dets] == [True, False] * 3


def test_the_paint_spec_matches_the_canvas(tmp_path):
    scene = _front(_seat(-12, -30), _seat(12, -30))
    assert scene.inlay_fill_paint_spec() == []      # hidden: nothing to print
    scene.set_inlay_fill_visible(True)
    spec = scene.inlay_fill_paint_spec()
    assert [(p.boundingRect(), o) for p, _b, o in spec] == \
        [(it.path().boundingRect(), 1.0) for it in scene._inlay_fill_items]
    scene.set_inlay_fill_image(_image(tmp_path / "stone.png"))
    scene.set_inlay_fill_tumble(True)
    spec = scene.inlay_fill_paint_spec()
    assert [b.transform() for _p, b, _o in spec] == \
        [it.brush().transform() for it in scene._inlay_fill_items]
    assert all(o == pytest.approx(DEFAULT_INLAY_FILL_OPACITY) for _p, _b, o in spec)
