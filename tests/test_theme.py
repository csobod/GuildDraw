"""framedraft.theme — token resolution, overrides, layer fallback, QSS build.

The module is global-state (current mode + overrides), so every test restores
a clean light/no-overrides state via the fixture.
"""
import pytest

from framedraft import theme
from framedraft.document import Layer


def _reset():
    theme.set_dark(False)
    theme.set_overrides({})
    theme.set_dot_radius(4)


@pytest.fixture(autouse=True)
def _clean_theme():
    # Reset BEFORE too: other tests (a MainWindow built under the user's real
    # prefs) may have left the module-global theme in dark mode.
    _reset()
    yield
    _reset()


def test_mode_switch_resolves_token_pairs():
    assert theme.color("chrome.bg") == "#ffd580"
    theme.set_dark(True)
    assert theme.color("chrome.bg") == "#1a1a1a"
    assert theme.is_dark()


def test_unknown_token_raises():
    with pytest.raises(KeyError):
        theme.color("nope.nothing")


def test_overrides_apply_per_mode_and_clear():
    theme.set_overrides({"light": {"canvas.bg": "#123456"}})
    assert theme.color("canvas.bg") == "#123456"
    theme.set_dark(True)
    assert theme.color("canvas.bg") == "#1e1e1e"   # dark not overridden
    theme.set_dark(False)
    theme.set_override("canvas.bg", None)          # clear in current mode
    assert theme.color("canvas.bg") == "#faf6ee"


def test_default_color_ignores_overrides():
    theme.set_overrides({"light": {"chrome.ink": "#ff0000"}})
    assert theme.default_color("chrome.ink", dark=False) == "#1f1f1f"
    assert theme.color("chrome.ink") == "#ff0000"


def test_layer_color_fallback_chain():
    # Plain layers follow the shared geometry ink…
    assert theme.layer_color(Layer.OUTLINE) == theme.color("geometry.ink")
    # …special layers keep their own defaults…
    assert theme.layer_color(Layer.SCULPT) == "#8e44ad"
    theme.set_dark(True)
    assert theme.layer_color(Layer.SCULPT) == "#c39bd3"
    theme.set_dark(False)
    # …and a user override beats both.
    theme.set_override("layer.OUTLINE", "#00ff00")
    assert theme.layer_color(Layer.OUTLINE) == "#00ff00"
    assert theme.layer_color(Layer.LENS) == theme.color("geometry.ink")


def test_build_qss_embeds_current_chrome():
    qss = theme.build_qss()
    assert "#ffd580" in qss and "#1a1a1a" not in qss.replace("#1a3040", "")
    theme.set_dark(True)
    qss_d = theme.build_qss()
    assert "#1a1a1a" in qss_d
    theme.set_dark(False)
    theme.set_overrides({"light": {"chrome.bg": "#abcdef"}})
    assert "#abcdef" in theme.build_qss()


def test_viewport_preset_overlays_both_modes():
    theme.apply_viewport("blueprint")
    assert theme.color("canvas.bg") == "#16324f"
    assert theme.color("geometry.ink") == "#dce8f2"
    theme.set_dark(True)
    assert theme.color("canvas.bg") == "#16324f"   # same canvas either mode
    theme.set_dark(False)
    theme.apply_viewport("auto")                    # clears the overlay
    assert theme.color("canvas.bg") == "#faf6ee"


def test_viewport_preset_recolors_plain_layers():
    from framedraft.document import Layer
    theme.apply_viewport("blueprint")
    # Plain layers follow geometry.ink, so they turn legible on the blue.
    assert theme.layer_color(Layer.OUTLINE) == "#dce8f2"


def test_viewport_custom_derives_legible_ink():
    theme.apply_viewport("custom", "#101820")       # near-black canvas
    assert theme.color("geometry.ink") == "#d4cfc0" # light ink
    theme.apply_viewport("custom", "#f0ead2")       # pale canvas
    assert theme.color("geometry.ink") == "#1f1f1f" # dark ink


def test_dot_radius_clamped():
    theme.set_dot_radius(50)
    assert theme.dot_radius() == 10
    theme.set_dot_radius(0)
    assert theme.dot_radius() == 2
    theme.set_dot_radius(5)
    assert theme.dot_radius() == 5
