"""The INLAY layer (BUILDPLAN *Road to 2.0*, item 1): where it lives, what it
is, and that it travels to GuildModel under its own name."""
import ezdxf

from framedraft import theme
from framedraft.document import (
    Layer, MACHINED_LAYERS, MIRRORED_LAYERS, WORKSPACE_LAYERS,
)
from framedraft.export.dxf import export_dxf

from helpers import closed_diamond


def test_inlay_lives_on_the_front_and_the_temples_and_is_machined():
    for ws in ("front", "temple_r", "temple_l"):
        assert Layer.INLAY in WORKSPACE_LAYERS[ws], ws
    assert Layer.INLAY not in WORKSPACE_LAYERS["component"]
    assert Layer.INLAY in MACHINED_LAYERS
    # A seat is drawn where it is cut; a pair comes from Mirror (bake).
    assert Layer.INLAY not in MIRRORED_LAYERS


def test_inlay_has_its_own_color_in_both_modes():
    theme.set_dark(False)
    assert theme.layer_color(Layer.INLAY) == "#a67c00"
    theme.set_dark(True)
    assert theme.layer_color(Layer.INLAY) == "#e0b84c"
    theme.set_dark(False)


def test_inlay_reaches_the_dxf_under_its_own_layer_name(tmp_path):
    path = tmp_path / "front.dxf"
    export_dxf([closed_diamond(0, -30, 4, layer=Layer.INLAY)], str(path))
    doc = ezdxf.readfile(str(path))
    layers = [e.dxf.layer for e in doc.modelspace()]
    assert layers == ["INLAY"]                  # one entity, and no mirrored copy
