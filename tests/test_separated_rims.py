"""Separated rims (BUILDPLAN *Road to 2.0*, item 9): a combination frame's
two rims, each holding its lens, handed off baked. The validator reads them
as bodies, says once that a rim drawn in pieces wants joining, and catches a
rim that only the Ghost draws; Frame Fill fills every rim, and the Ghost
previews a closed rim's twin until it is baked."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.canvas.scene import FrameScene
from framedraft.document import Layer
from framedraft.export.validate import validate
from helpers import arc, circle, closed_diamond, line, spline


def rim(cx, r=18.0):
    return closed_diamond(cx, 0, r, layer=Layer.OUTLINE)


def rim_in_pieces(side=-1.0):
    """A rim drawn as a spline round the lens and a straight line at the
    temple edge, their ends meeting, as a maker draws a combination rim."""
    s = side
    bow = spline([(40 * s, -10), (10 * s, -25), (5 * s, 0), (10 * s, 25),
                  (40 * s, 10)], closed=False, layer=Layer.OUTLINE)
    edge = line([(40 * s, 10), (40 * s, -10)], layer=Layer.OUTLINE)
    return [bow, edge]


# ── The validator ──────────────────────────────────────────────────────────

def test_two_rims_each_holding_a_lens_are_bodies_not_strays():
    curves = [rim(-24), rim(24), circle(-24, 0, 9), circle(24, 0, 9)]
    errors, warnings = validate(curves, mirror_on=False)
    assert errors == [] and warnings == []
    # A contour that holds no lens is still a stray.
    errors, warnings = validate(curves + [rim(90, 5)], mirror_on=False)
    assert errors == []
    assert any("fall outside the profile" in w for w in warnings)


def test_a_rim_drawn_in_pieces_asks_for_a_join_once():
    curves = rim_in_pieces() + [circle(-22, 0, 9)]
    errors, _ = validate(curves, mirror_on=False)
    assert sum("drawn in 2 pieces" in e for e in errors) == 1
    assert not any("endpoint gap" in e for e in errors)   # no gap per piece
    assert errors[0].startswith("OUTLINE contour is drawn in 2 pieces")


def test_pieces_that_do_not_meet_keep_their_gap_errors():
    bow, edge = rim_in_pieces()
    edge = line([(40 * -1, 14), (40 * -1, -10)], layer=Layer.OUTLINE)  # 4 mm short
    errors, _ = validate([bow, edge, circle(-22, 0, 9)], mirror_on=False)
    assert not any("pieces" in e for e in errors)
    assert any("endpoint gap" in e for e in errors)


def test_an_arc_and_a_line_meeting_are_pieces_too():
    # An arc's ends come from its angles; its one node is its center.
    half = arc(-30, 0, 15, 0, 180, layer=Layer.OUTLINE)
    chord = line([(-45, 0), (-15, 0)], layer=Layer.OUTLINE)
    errors, _ = validate([half, chord, circle(-30, -6, 4)], mirror_on=False)
    assert any("drawn in 2 pieces" in e for e in errors)


def test_a_rim_the_ghost_alone_draws_asks_for_a_bake():
    curves = [rim(-24), circle(-24, 0, 9)]
    errors, _ = validate(curves, mirror_on=True)
    assert errors == ["The other rim is the Ghost's only, and GuildModel reads "
                      "only the curves drawn: select the rim and its lens and "
                      "Mirror (bake) them, or turn the Ghost off for a monocle."]
    # Baked, the twin stands for itself.
    errors, _ = validate(curves + [rim(24), circle(24, 0, 9)], mirror_on=True)
    assert errors == []
    # A whole front crossing the axis is no rim, Ghost or not.
    errors, _ = validate([closed_diamond(0, 0, 45), circle(17, 0, 11)], mirror_on=True)
    assert not any("rim" in e for e in errors)


def test_separated_rims_with_one_lens_are_not_ready_with_the_ghost_on():
    # The second rim, drawn without its lens, is a stray to GuildModel; the
    # Ghost's lens lands in it and is never cut.
    curves = [rim(-24), rim(24), circle(-24, 0, 9)]
    errors, _ = validate(curves, mirror_on=True)
    assert any("other lens is the Ghost's only" in e for e in errors)


def test_a_lens_outside_every_body_is_an_error():
    curves = [rim(-24), rim(24), circle(-24, 0, 9), circle(70, 0, 9)]
    errors, _ = validate(curves, mirror_on=False)
    assert any("LENS 2 lies outside every OUTLINE body" in e for e in errors)


def test_a_seat_on_the_second_rim_lies_inside_the_part():
    curves = [rim(-24), rim(24), circle(-24, 0, 6), circle(24, 0, 6),
              closed_diamond(24, -12, 2, layer=Layer.INLAY)]
    errors, _ = validate(curves, mirror_on=False)
    assert errors == []


# ── The canvas ─────────────────────────────────────────────────────────────

def test_both_rims_fill():
    scene = FrameScene()
    for c in (rim(-24), rim(24), circle(-24, 0, 9), circle(24, 0, 9)):
        scene.add_curve(c)
    assert scene.set_fill_visible(True) == "ok"
    path = scene._fill_item.path()
    assert path.contains(QPointF(-24, -14)) and path.contains(QPointF(24, -14))
    assert not path.contains(QPointF(-24, 0)) and not path.contains(QPointF(24, 0))


def test_the_ghost_previews_a_closed_rim_beside_the_axis():
    scene = FrameScene()
    scene.init_mirror(horizontal=False)
    left, profile = rim(-24), closed_diamond(0, 60, 45)
    scene.add_curve(left)
    scene.add_curve(profile)
    assert id(left) in scene._ghost_items            # the twin rim, previewed
    assert id(profile) not in scene._ghost_items     # a whole front is drawn whole
    temple = FrameScene()
    temple.init_mirror(horizontal=True)
    arm = line([(0, 4), (120, 4), (120, 14), (0, 14)], closed=True,
               layer=Layer.OUTLINE)
    temple.add_curve(arm)
    assert id(arm) not in temple._ghost_items        # never on a temple


def test_the_previewed_twin_fills_with_its_lens():
    scene = FrameScene()
    scene.init_mirror(horizontal=False)
    for c in (rim(-24), circle(-24, 0, 9)):
        scene.add_curve(c)
    assert scene.set_fill_visible(True) == "ok"
    path = scene._fill_item.path()
    assert path.contains(QPointF(24, -14))           # the Ghost's rim
    assert not path.contains(QPointF(24, 0))         # and the Ghost's lens


# ── The flow in the app ────────────────────────────────────────────────────

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


def _select(win, layers=None):
    from framedraft.canvas.items import CurveItem
    win.scene.clearSelection()
    for it in win.scene.items():
        if isinstance(it, CurveItem) and (layers is None or it.curve.layer in layers):
            it.setSelected(True)


def test_join_then_bake_hands_off_both_rims(win):
    ws = win._active_ws
    for c in rim_in_pieces() + [circle(-22, 0, 9)]:
        ws.add_curve(c)
    win._act_mirror.setChecked(True)
    win._update_readiness()
    dot = win._readiness_dot
    assert dot.state() == "amber" and "drawn in 2 pieces" in dot.toolTip()

    _select(win, {Layer.OUTLINE})
    win._act_join.trigger()
    win._update_readiness()
    assert "Ghost's only" in dot.toolTip()

    _select(win)
    win._on_duplicate_mirror()
    win._update_readiness()
    assert dot.state() == "green"
    outlines = [c for c in ws.doc_curves if c.layer == Layer.OUTLINE]
    assert len(outlines) == 2 and all(c.closed for c in outlines)
    assert not win._act_mirror.isChecked()


# ── The bridge's seat across the gap ──────────────────────────────────────

@pytest.mark.parametrize("layer", [Layer.COMPONENT, Layer.INLAY])
def test_a_bridge_seat_spanning_the_gap_is_accepted(layer):
    # From behind on COMPONENT, from the front on INLAY: one shape across the
    # gap, reaching into each rim's nasal end, a step open at each edge.
    seat = line([(-10, -14), (10, -14), (10, -8), (-10, -8)], closed=True,
                layer=layer)
    curves = [rim(-24), rim(24), circle(-24, 0, 8), circle(24, 0, 8), seat]
    errors, warnings = validate(curves, mirror_on=False)
    assert errors == [] and warnings == []


def test_a_seat_off_the_part_is_still_an_error():
    seat = closed_diamond(0, -40, 3, layer=Layer.INLAY)   # in the air between
    curves = [rim(-24), rim(24), circle(-24, 0, 8), circle(24, 0, 8), seat]
    errors, _ = validate(curves, mirror_on=False)
    assert any("INLAY 1 lies off the part" in e for e in errors)
