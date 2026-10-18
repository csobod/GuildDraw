"""Tests for the 'Ready for GuildModel' readiness state machine (Qt-free)."""
from framedraft.canvas.readiness_dot import readiness_state, OFF, AMBER, GREEN
from framedraft.document import Layer

from helpers import closed_diamond, line


def _front_lens(cx):
    # A closed lens contour on the LENS layer at offset cx.
    return closed_diamond(cx=cx, cy=0.0, r=15.0, layer=Layer.LENS)


def test_off_when_empty():
    state, tip = readiness_state([], mirror_on=False, workspace_type="front")
    assert state == OFF
    assert "Nothing to hand off" in tip


def test_off_when_only_ref_geometry():
    # REF is not a machined layer — nothing to hand off.
    ref = line([(0, 0), (10, 0)], layer=Layer.REF)
    state, _ = readiness_state([ref], mirror_on=False, workspace_type="front")
    assert state == OFF


def test_amber_when_incomplete_front():
    # OUTLINE present but no LENS pair -> validator errors -> amber.
    outline = closed_diamond(cx=0.0, r=30.0, layer=Layer.OUTLINE)
    state, tip = readiness_state([outline], mirror_on=False,
                                 workspace_type="front")
    assert state == AMBER
    assert "Not ready for GuildModel" in tip
    assert "LENS" in tip   # the named gap


def test_amber_front_with_one_lens_and_the_ghost():
    # GuildModel never applies the Ghost: one lens drawn in an outline for two
    # is the other eye cut solid, Ghost or not.
    outline = closed_diamond(cx=0.0, r=30.0, layer=Layer.OUTLINE)
    lens    = _front_lens(cx=-20.0)
    for mirror_on in (True, False):
        state, tip = readiness_state([outline, lens], mirror_on=mirror_on,
                                     workspace_type="front")
        assert state == AMBER


def test_green_front_with_both_lenses_drawn():
    outline = closed_diamond(cx=0.0, r=40.0, layer=Layer.OUTLINE)
    lenses  = [_front_lens(cx=-20.0), _front_lens(cx=20.0)]
    for mirror_on in (True, False):
        state, tip = readiness_state([outline, *lenses], mirror_on=mirror_on,
                                     workspace_type="front")
        assert state == GREEN
        assert "Ready for GuildModel" in tip


def test_green_front_with_bridge_keyhole():
    # Aviator: perimeter + a second closed OUTLINE spline inside it (the
    # bridge keyhole) — multiple OUTLINE curves are GuildModel-ready now, so
    # the dot stays green (the openings note rides in the tooltip warning).
    outline = closed_diamond(cx=0.0, r=40.0, layer=Layer.OUTLINE)
    keyhole = closed_diamond(cx=0.0, cy=5.0, r=4.0, layer=Layer.OUTLINE)
    lenses  = [_front_lens(cx=-20.0), _front_lens(cx=20.0)]
    state, tip = readiness_state([outline, keyhole, *lenses], mirror_on=True,
                                 workspace_type="front")
    assert state == GREEN
    assert "Ready for GuildModel" in tip


def test_the_component_tab_never_says_ready_for_guildmodel():
    # GuildModel builds no part from this tab; a component reaches it placed
    # on the front or a temple.
    pocket = closed_diamond(cx=0.0, r=5.0, layer=Layer.COMPONENT)
    state, tip = readiness_state([pocket], mirror_on=False, workspace_type="component")
    assert state == OFF
    assert "does not read this tab" in tip
    opened = line([(0, 0), (5, 0), (5, 5)], layer=Layer.COMPONENT)
    state, tip = readiness_state([opened], mirror_on=False, workspace_type="component")
    assert state == AMBER
    assert "Ready for GuildModel" not in tip


def test_amber_temple_with_lens():
    outline = closed_diamond(cx=0.0, r=40.0, layer=Layer.OUTLINE)
    lens    = _front_lens(cx=0.0)
    state, tip = readiness_state([outline, lens], mirror_on=False,
                                 workspace_type="temple_r")
    assert state == AMBER
    assert "LENS" in tip


def test_green_with_a_warning_when_the_temple_is_off_the_core_line():
    # The origin rule (Road to 1.4, item 1) warns, never blocks: the dot stays
    # green and the tooltip names the gap.
    arm = line([(0, 7), (120, 7), (120, 17), (0, 17)], closed=True,
               layer=Layer.OUTLINE)
    state, tip = readiness_state([arm], mirror_on=False,
                                 workspace_type="temple_r", stock_mm=(170.0, 30.0))
    assert state == GREEN
    assert "To note:\n•" in tip and "core line" in tip
