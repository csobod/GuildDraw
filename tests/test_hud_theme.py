"""RC4 M24 — HUD readability in light mode + the Dimmed viewport preset.

The app-level QSS paints ``QWidget { background-color: chrome.bg }`` under
every widget; HUD child labels that set only a text color inherited an opaque
amber box in light mode with near-white text on top. The HUDs now style
through theme.build_hud_qss, whose child rules always set an explicit
(transparent) background.
"""

from PySide6.QtWidgets import QApplication, QWidget

from framedraft import theme
from framedraft.canvas.measure_bar import MeasureBar
from framedraft.canvas.move_gizmo import _MoveHud
from framedraft.tools.point_move import _PointMoveHud


# ------------------------------------------------------------------ tokens


def test_hud_qss_child_rules_set_explicit_background():
    qss = theme.build_hud_qss("#x")
    assert "QLabel { background: transparent" in qss
    assert "QLineEdit { background:" in qss


def test_dimmed_preset_shipped_and_between_parchment_and_matte():
    vals = theme.VIEWPORT_PRESETS["dimmed"]
    assert set(vals) == {"canvas.bg", "geometry.ink", "canvas.cross"}
    lum = theme._luminance
    assert (lum(theme.VIEWPORT_PRESETS["matte"]["canvas.bg"])
            < lum(vals["canvas.bg"])
            < lum(theme.VIEWPORT_PRESETS["parchment"]["canvas.bg"]))


def test_dimmed_preset_overlays_both_modes():
    theme.set_overrides(None)
    try:
        theme.apply_viewport("dimmed")
        for dark in (False, True):
            theme.set_dark(dark)
            assert theme.color("canvas.bg") == "#d8d1c3"
            assert theme.color("geometry.ink") == "#1f1f1f"
    finally:
        theme.set_dark(False)
        theme.set_overrides(None)


# ------------------------------------------------- rendered-pixel regression


def _label_bg_is_dark(host: QWidget, hud: QWidget, label) -> bool:
    """Sample a corner pixel of *label* (background, not glyphs) in host coords."""
    img = host.grab().toImage()
    dpr = img.devicePixelRatio()   # grab() is in device px, geometry is logical
    top_left = label.mapTo(host, label.rect().topLeft())
    c = img.pixelColor(round((top_left.x() + 2) * dpr),
                       round((top_left.y() + 2) * dpr))
    return (c.red() + c.green() + c.blue()) < 300


def _light_mode_host():
    theme.set_dark(False)
    theme.set_overrides(None)
    QApplication.instance().setStyleSheet(theme.build_qss())
    host = QWidget()
    host.resize(560, 200)
    return host


def test_move_hud_labels_readable_in_light_mode():
    host = _light_mode_host()
    hud = _MoveHud(host)
    hud.show_for(1, 0, 40, 120, on_commit=lambda *_: None,
                 on_cancel=lambda: None)
    QApplication.processEvents()
    assert _label_bg_is_dark(host, hud, hud._label), (
        "Move HUD label sits on the app chrome background (amber in light "
        "mode) instead of the HUD chip")
    QApplication.instance().setStyleSheet("")


def test_point_move_hud_labels_readable_in_light_mode():
    host = _light_mode_host()
    hud = _PointMoveHud(host)
    hud.show_for(40, 120, 1.0, 2.0, on_commit=lambda *_: None,
                 on_cancel=lambda: None)
    QApplication.processEvents()
    labels = [w for w in hud.children() if w.metaObject().className() == "QLabel"]
    assert labels
    assert all(_label_bg_is_dark(host, hud, lbl) for lbl in labels), (
        "Point Move HUD labels sit on the app chrome background")
    QApplication.instance().setStyleSheet("")


def test_measure_bar_labels_readable_in_light_mode():
    host = _light_mode_host()
    bar = MeasureBar(host)
    bar.show_radius()
    QApplication.processEvents()
    assert _label_bg_is_dark(host, bar, bar._lbl_rad)
    assert _label_bg_is_dark(host, bar, bar._hint)
    QApplication.instance().setStyleSheet("")
