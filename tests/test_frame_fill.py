"""Frame Fill overlay — OUTLINE profile minus openings minus LENS apertures.

Runs against a real (offscreen) FrameScene because the fill is Qt boolean
path ops; conftest provides the shared QApplication.
"""
from PySide6.QtCore import QPointF

from framedraft.canvas.scene import FrameScene
from framedraft.document import Layer
from helpers import closed_diamond, circle, spline


def _fill_path(*curves):
    scene = FrameScene()
    for c in curves:
        scene.add_curve(c)
    scene.set_fill_visible(True)   # rebuilds synchronously
    return scene._fill_item.path()


def test_fill_covers_frame_and_excludes_lenses():
    outline = closed_diamond(0, 0, 40, layer=Layer.OUTLINE)
    path = _fill_path(outline, circle(-15, 0, 8), circle(15, 0, 8))
    assert path.contains(QPointF(0, -30))       # frame body above the lenses
    assert not path.contains(QPointF(-15, 0))   # lens aperture
    assert not path.contains(QPointF(60, 0))    # outside the frame


def test_outline_hole_punches_through_fill():
    # Aviator bridge keyhole: a second closed OUTLINE curve inside the
    # profile is a decorative opening — the fill must show it empty rather
    # than painting the union solid.
    outline = closed_diamond(0, 0, 40, layer=Layer.OUTLINE)
    keyhole = closed_diamond(0, 12, 6, layer=Layer.OUTLINE)
    path = _fill_path(outline, keyhole,
                      circle(-20, -5, 7), circle(20, -5, 7))
    assert not path.contains(QPointF(0, 12))    # keyhole interior is open
    assert path.contains(QPointF(0, 30))        # frame body below still filled
    assert path.contains(QPointF(0, -25))       # frame body above still filled


def test_stray_outline_outside_profile_is_ignored():
    # A closed OUTLINE curve outside the profile is a stray GuildModel
    # ignores — it must neither paint its own region nor eat the profile.
    outline = closed_diamond(0, 0, 40, layer=Layer.OUTLINE)
    stray   = closed_diamond(90, 0, 10, layer=Layer.OUTLINE)
    path = _fill_path(outline, stray, circle(0, 0, 8))
    assert path.contains(QPointF(0, -30))       # profile fill unaffected
    assert not path.contains(QPointF(90, 0))    # stray isn't painted


# ── Ghost mode: half a frame closed by its mirror image ──────────────────────

def _ghost_scene(*curves):
    """A FrameScene with a vertical mirror at x=0 (Ghost mode) and the given
    curves added — so open halves drawn against the axis cast live ghosts."""
    scene = FrameScene()
    scene.init_mirror(horizontal=False)
    for c in curves:
        scene.add_curve(c)
    return scene


def test_ghost_half_frame_fills():
    # Only the RIGHT half of the OUTLINE is drawn (open, endpoints on the
    # mirror line); its ghost completes the loop. Frame Fill must recognise
    # the stitched perimeter and fill both sides.
    half = spline([(0, -40), (35, -20), (40, 0), (35, 20), (0, 40)],
                  closed=False, layer=Layer.OUTLINE)
    scene = _ghost_scene(half, circle(18, 0, 7, layer=Layer.LENS))
    assert scene.set_fill_visible(True) == "ok"
    path = scene._fill_item.path()
    assert path.contains(QPointF(30, 0))     # right frame body
    assert path.contains(QPointF(-30, 0))    # left body via the ghost
    assert not path.contains(QPointF(18, 0))    # right lens aperture
    assert not path.contains(QPointF(-18, 0))   # left lens via the ghost


def test_ghost_half_frame_hole_punches_through():
    # Aviator: half the profile + half the bridge keyhole, both open against
    # the mirror line. Real+ghost stitch the profile and the hole; the hole
    # must read empty on both sides of the axis.
    half = spline([(0, -45), (40, -20), (45, 0), (40, 20), (0, 45)],
                  closed=False, layer=Layer.OUTLINE)
    hole = spline([(0, 12), (7, 6), (8, 0), (7, -6), (0, -12)],
                  closed=False, layer=Layer.OUTLINE)
    scene = _ghost_scene(half, hole, circle(24, 0, 8, layer=Layer.LENS))
    assert scene.set_fill_visible(True) == "ok"
    path = scene._fill_item.path()
    assert not path.contains(QPointF(0, 0))     # keyhole interior open
    assert path.contains(QPointF(0, 25))        # frame body above the keyhole
    assert path.contains(QPointF(35, 0))        # right body outside the lens
    assert path.contains(QPointF(-35, 0))       # ghost side body


def test_leak_when_half_endpoint_leaves_the_axis():
    # Pull the top endpoint off the mirror line: the real half and its ghost
    # no longer meet there, so the perimeter can't close → a leak, not a fill.
    half = spline([(0, -40), (35, -20), (40, 0), (35, 20), (6, 40)],
                  closed=False, layer=Layer.OUTLINE)
    scene = _ghost_scene(half, circle(18, 0, 7, layer=Layer.LENS))
    assert scene.outline_fill_status() == "leak"
    assert scene.set_fill_visible(True) == "leak"
    assert scene._fill_item is None or not scene._fill_item.isVisible()


def test_empty_status_when_no_outline():
    scene = FrameScene()
    scene.add_curve(circle(0, 0, 10, layer=Layer.LENS))   # lens, no outline
    assert scene.outline_fill_status() == "empty"
    assert scene.set_fill_visible(True) == "empty"


def test_breaking_perimeter_auto_disables_fill():
    # Fill is on over a closed frame; reopening the OUTLINE while it's visible
    # must turn the fill off and report the break via fill_auto_disabled.
    outline = closed_diamond(0, 0, 40, layer=Layer.OUTLINE)
    scene = FrameScene()
    scene.add_curve(outline)
    scene.add_curve(circle(0, 0, 8, layer=Layer.LENS))
    assert scene.set_fill_visible(True) == "ok"

    fired = []
    scene.fill_auto_disabled = lambda status: fired.append(status)
    outline.closed = False                 # break the perimeter
    scene.refresh_curve(outline)
    scene.rebuild_fill()                   # the debounced tick

    assert fired == ["leak"]
    assert not scene._fill_visible
    assert not scene._fill_item.isVisible()
