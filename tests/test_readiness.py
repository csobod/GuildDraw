"""Tests for the 'Ready for GuildCAM' readiness state machine (Qt-free)."""
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
    assert "Not ready for GuildCAM" in tip
    assert "LENS" in tip   # the named gap


def test_green_front_with_mirror_doubling():
    # OUTLINE x1 + one LENS; mirror doubling -> LENS x2. Contract met.
    outline = closed_diamond(cx=0.0, r=30.0, layer=Layer.OUTLINE)
    lens    = _front_lens(cx=-20.0)
    state, tip = readiness_state([outline, lens], mirror_on=True,
                                 workspace_type="front")
    assert state == GREEN
    assert "Ready for GuildCAM" in tip


def test_green_hinge():
    hinge = closed_diamond(cx=0.0, r=5.0, layer=Layer.HINGE)
    state, _ = readiness_state([hinge], mirror_on=False, workspace_type="hinge")
    assert state == GREEN


def test_amber_temple_with_lens():
    outline = closed_diamond(cx=0.0, r=40.0, layer=Layer.OUTLINE)
    lens    = _front_lens(cx=0.0)
    state, tip = readiness_state([outline, lens], mirror_on=False,
                                 workspace_type="temple_r")
    assert state == AMBER
    assert "LENS" in tip
