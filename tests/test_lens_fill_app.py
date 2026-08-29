"""Lens Fill wiring in the app: link button, BPI reference, prefs, round-trip."""
import json

import pytest

from framedraft import bpi_tints
from framedraft.canvas.scene import (DEFAULT_LENS_FILL_TOP,
                                     DEFAULT_LENS_FILL_BOTTOM,
                                     DEFAULT_LENS_FILL_INTENSITY, deepen_tint,
                                     intensity_from_slider,
                                     slider_from_intensity)
from PySide6.QtGui import QColor

from framedraft.document import Layer
from framedraft.prefs import DEFAULTS
from helpers import circle, closed_diamond


@pytest.fixture(scope="module")
def win():
    from framedraft.app import MainWindow
    w = MainWindow()
    yield w
    for ws in w._workspaces:
        ws.scene.clearSelection()
    w._dirty = False


@pytest.fixture()
def fresh(win):
    win._dirty = False
    win._new()
    win._ws_tab_widget.setCurrentIndex(0)
    return win


# ------------------------------------------------------------- shipped table


def test_shipped_tint_table_is_usable():
    tints = bpi_tints.load_tints()
    assert len(tints) > 50
    for t in tints:
        assert t["hex"].startswith("#") and len(t["hex"]) == 7
        assert t["name"]


def test_tint_table_ships_no_images():
    """Only the numbers ship — the swatch JPEGs stay on the scrape machine."""
    from pathlib import Path
    res = Path(bpi_tints.__file__).parent / "resources"
    assert not list(res.glob("**/*.jpg"))
    assert not list(res.glob("**/*.png"))
    data = json.loads((res / "bpi_tints.json").read_text(encoding="utf-8"))
    assert "disclaimer" in data and "source" in data


# ------------------------------------------------------------------ the panel


def test_lens_fill_is_front_only(fresh):
    win = fresh
    assert not win._lens_fill_box.isHidden()
    win._ws_tab_widget.setCurrentIndex(1)          # Temple R
    assert win._lens_fill_box.isHidden()
    win._ws_tab_widget.setCurrentIndex(0)
    assert not win._lens_fill_box.isHidden()


def test_showing_with_no_lens_reverts_the_tick(fresh, monkeypatch):
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    win = fresh
    win._lens_fill_show_chk.setChecked(True)
    assert not win._lens_fill_show_chk.isChecked()
    assert win._active_ws.lens_fill_visible is False


def test_showing_with_a_lens_sticks(fresh):
    win = fresh
    win._active_ws.add_curve(circle(-15, 0, 8))
    win._lens_fill_show_chk.setChecked(True)
    assert win._lens_fill_show_chk.isChecked()
    assert win._active_ws.lens_fill_visible is True


def test_link_collapses_the_gradient_to_a_flat_tint(fresh):
    win = fresh
    ws = win._active_ws
    win._set_lens_fill_color("bottom", "#101010")
    assert ws.lens_fill_top != ws.lens_fill_bottom

    win._lens_link_btn.setChecked(True)
    assert ws.lens_fill_top == ws.lens_fill_bottom == DEFAULT_LENS_FILL_TOP


def test_linked_stops_track_each_other_both_ways(fresh):
    win = fresh
    ws = win._active_ws
    win._lens_link_btn.setChecked(True)

    win._set_lens_fill_color("bottom", "#204060")
    assert ws.lens_fill_top == ws.lens_fill_bottom == "#204060"
    win._set_lens_fill_color("top", "#a0b0c0")
    assert ws.lens_fill_top == ws.lens_fill_bottom == "#a0b0c0"


def test_unlinked_stops_stay_independent(fresh):
    win = fresh
    ws = win._active_ws
    win._lens_link_btn.setChecked(False)
    win._set_lens_fill_color("top", "#111111")
    win._set_lens_fill_color("bottom", "#222222")
    assert (ws.lens_fill_top, ws.lens_fill_bottom) == ("#111111", "#222222")


def test_bpi_hex_lands_in_the_chosen_stop(fresh):
    win = fresh
    tint = bpi_tints.load_tints()[0]
    win._lens_link_btn.setChecked(False)
    win._set_lens_fill_color("bottom", tint["hex"])
    assert win._active_ws.lens_fill_bottom == tint["hex"]
    assert win._active_ws.lens_fill_top == DEFAULT_LENS_FILL_TOP


# ------------------------------------------------------------------- prefs


def test_default_opacity_pref_ships_at_65():
    assert DEFAULTS["lens_fill_opacity_pct"] == 65


def test_default_opacity_pref_drives_a_new_document(fresh):
    win = fresh
    win._prefs["lens_fill_opacity_pct"] = 40
    win._new()
    assert win._active_ws.lens_fill_opacity == pytest.approx(0.40)
    win._prefs["lens_fill_opacity_pct"] = 65


def test_bad_opacity_pref_falls_back(fresh):
    win = fresh
    win._prefs["lens_fill_opacity_pct"] = "not a number"
    assert 0.0 <= win._default_lens_fill_opacity() <= 1.0
    win._prefs["lens_fill_opacity_pct"] = 65


# -------------------------------------------------------------- persistence


def test_lens_fill_survives_a_gdraw_round_trip(fresh, tmp_path):
    win = fresh
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 15, layer=Layer.LENS))
    win._lens_link_btn.setChecked(False)
    win._set_lens_fill_color("top", "#aabbcc")
    win._set_lens_fill_color("bottom", "#112233")
    win._lens_fill_opacity_slider.setValue(42)
    win._lens_fill_intensity_slider.setValue(70)
    win._lens_fill_show_chk.setChecked(True)
    saved_intensity = win._active_ws.lens_fill_intensity

    path = tmp_path / "tinted.gdraw"
    win._do_save_gdraw(str(path))
    win._dirty = False
    win._new()
    assert win._active_ws.lens_fill_top == DEFAULT_LENS_FILL_TOP   # really reset
    win._open_path(str(path))

    ws = win._active_ws
    assert ws.lens_fill_top == "#aabbcc"
    assert ws.lens_fill_bottom == "#112233"
    assert ws.lens_fill_opacity == pytest.approx(0.42)
    assert ws.lens_fill_intensity == pytest.approx(saved_intensity)
    assert win._lens_fill_intensity_slider.value() == 70
    assert ws.lens_fill_visible is True
    assert win._lens_fill_show_chk.isChecked()


def test_linked_flag_survives_a_round_trip(fresh, tmp_path):
    win = fresh
    win._active_ws.add_curve(closed_diamond(0, 0, 15, layer=Layer.LENS))
    win._lens_link_btn.setChecked(True)
    win._set_lens_fill_color("top", "#7f7f7f")

    path = tmp_path / "flat.gdraw"
    win._do_save_gdraw(str(path))
    win._dirty = False
    win._new()
    win._open_path(str(path))

    ws = win._active_ws
    assert ws.lens_fill_linked is True
    assert ws.lens_fill_top == ws.lens_fill_bottom == "#7f7f7f"
    assert win._lens_link_btn.isChecked()


def test_pre_1_2_file_loads_with_the_tint_off(fresh, tmp_path):
    """A .gdraw written before Lens Fill existed carries no lens_fill block."""
    win = fresh
    win._active_ws.add_curve(closed_diamond(0, 0, 15, layer=Layer.LENS))
    path = tmp_path / "legacy.gdraw"
    win._do_save_gdraw(str(path))

    import zipfile
    stripped = tmp_path / "stripped.gdraw"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(stripped, "w") as dst:
        for info in src.infolist():
            blob = src.read(info.filename)
            if info.filename.endswith(".svg"):
                text = blob.decode("utf-8")
                assert '"lens_fill"' in text
                obj = text.split('"lens_fill"')
                # crude but faithful: drop the key the old writer never wrote
                head, tail = obj[0], obj[1].split("},", 1)[1]
                blob = (head + tail.lstrip()).encode("utf-8")
            dst.writestr(info, blob)

    win._dirty = False
    win._new()
    win._open_path(str(stripped))
    ws = win._active_ws
    assert ws.lens_fill_visible is False
    assert ws.lens_fill_top == DEFAULT_LENS_FILL_TOP
    assert ws.lens_fill_bottom == DEFAULT_LENS_FILL_BOTTOM
    assert ws.lens_fill_intensity == pytest.approx(DEFAULT_LENS_FILL_INTENSITY)


# ------------------------------------------------------------------ intensity


def test_intensity_slider_starts_at_the_colour_as_picked(fresh):
    win = fresh
    assert win._active_ws.lens_fill_intensity == pytest.approx(1.0)
    assert (win._lens_fill_intensity_slider.value()
            == slider_from_intensity(1.0))


def test_dragging_intensity_deepens_the_painted_tint(fresh):
    win = fresh
    ws = win._active_ws
    ws.add_curve(circle(0, 0, 8))
    win._lens_fill_show_chk.setChecked(True)
    pale = ws.scene._lens_fill_items[0].brush().gradient().stops()[0][1].name()

    win._lens_fill_intensity_slider.setValue(80)
    deep = ws.scene._lens_fill_items[0].brush().gradient().stops()[0][1].name()
    assert deep != pale
    assert QColor(deep).lightness() < QColor(pale).lightness()


def test_intensity_leaves_the_picked_colour_alone(fresh):
    # The stop keeps the hex the maker chose; intensity is a render-time depth,
    # so winding the slider back recovers exactly what was picked.
    win = fresh
    win._set_lens_fill_color("top", "#cbeafc")
    win._lens_fill_intensity_slider.setValue(90)
    assert win._active_ws.lens_fill_top == "#cbeafc"
    win._lens_fill_intensity_slider.setValue(slider_from_intensity(1.0))
    assert win._active_ws.lens_fill_top == "#cbeafc"


def _swatch_color(btn):
    """Centre pixel of a stop button's colour bar (inside the hairline border)."""
    from framedraft.app import _LENS_SWATCH_PX
    w, h = _LENS_SWATCH_PX
    return btn.icon().pixmap(w, h).toImage().pixelColor(w // 2, h // 2)


def test_swatch_button_previews_the_deepened_colour(fresh):
    win = fresh
    win._set_lens_fill_color("top", "#e4f5fd")
    win._lens_fill_intensity_slider.setValue(slider_from_intensity(1.0))
    as_picked = _swatch_color(win._lens_top_btn)
    assert as_picked.name() == "#e4f5fd"

    win._lens_fill_intensity_slider.setValue(85)
    deepened = _swatch_color(win._lens_top_btn)
    assert deepened.name() == deepen_tint(
        "#e4f5fd", intensity_from_slider(85)).name()
    assert deepened.lightness() < as_picked.lightness()


def test_stop_buttons_carry_no_redundant_caption(fresh):
    # The row label already says Top / Bottom; the button is the colour bar.
    win = fresh
    assert win._lens_top_btn.text() == ""
    assert win._lens_bottom_btn.text() == ""
    assert not win._lens_top_btn.icon().isNull()
    assert "#" in win._lens_top_btn.toolTip()


def test_default_intensity_pref_ships_at_one():
    assert DEFAULTS["lens_fill_intensity"] == 1.0


def test_default_intensity_pref_drives_a_new_document(fresh):
    win = fresh
    win._prefs["lens_fill_intensity"] = 3.0
    win._new()
    assert win._active_ws.lens_fill_intensity == pytest.approx(3.0)
    assert (win._lens_fill_intensity_slider.value()
            == slider_from_intensity(3.0))
    win._prefs["lens_fill_intensity"] = 1.0


def test_bad_intensity_pref_falls_back(fresh):
    win = fresh
    win._prefs["lens_fill_intensity"] = "deep"
    assert win._default_lens_fill_intensity() == DEFAULT_LENS_FILL_INTENSITY
    win._prefs["lens_fill_intensity"] = 1.0


def test_out_of_range_intensity_pref_is_clamped(fresh):
    win = fresh
    win._prefs["lens_fill_intensity"] = 500.0
    assert win._default_lens_fill_intensity() <= 8.0
    win._prefs["lens_fill_intensity"] = 1.0


# --------------------------------------------- pre-1.2 regressions (see below)


def test_intensity_survives_a_tab_switch_unrounded(fresh):
    """Slider position is a lossy encoding of intensity — it must not be the
    round-trip path. Re-deriving the value from the widget on every workspace
    change nudged a loaded document off its saved depth (3.0 came back 3.03)."""
    win = fresh
    ws = win._active_ws
    ws.lens_fill_intensity = 3.0
    ws.scene.set_lens_fill_intensity(3.0)

    win._ws_tab_widget.setCurrentIndex(1)     # away…
    win._ws_tab_widget.setCurrentIndex(0)     # …and back
    assert win._workspaces[0].lens_fill_intensity == 3.0


def test_intensity_is_stable_over_many_tab_switches(fresh):
    win = fresh
    win._workspaces[0].lens_fill_intensity = 2.5
    for _ in range(6):
        win._ws_tab_widget.setCurrentIndex(1)
        win._ws_tab_widget.setCurrentIndex(0)
    assert win._workspaces[0].lens_fill_intensity == 2.5


def test_dragging_the_slider_still_writes_the_intensity(fresh):
    # The flip side of the fix: the handler is now the sole writer, so it had
    # better fire.
    win = fresh
    win._lens_fill_intensity_slider.setValue(70)
    assert win._active_ws.lens_fill_intensity == pytest.approx(
        intensity_from_slider(70))


def test_tint_picker_is_freed_on_close(fresh):
    """The popup is rebuilt per open; without WA_DeleteOnClose each visit
    stranded 164 buttons and their pixmaps on the main window."""
    from PySide6.QtWidgets import QApplication
    win = fresh
    before = len(win.findChildren(bpi_tints.TintPicker))
    for _ in range(3):
        win._show_tint_picker("top")
        win.findChildren(bpi_tints.TintPicker)[-1].close()
        QApplication.processEvents()
    assert len(win.findChildren(bpi_tints.TintPicker)) == before


def test_picking_a_tint_applies_it_before_the_popup_goes_away(fresh):
    win = fresh
    win._lens_link_btn.setChecked(False)
    win._show_tint_picker("bottom")
    picker = win.findChildren(bpi_tints.TintPicker)[-1]
    tint = bpi_tints.load_tints()[3]
    picker._pick(tint["hex"])
    assert win._active_ws.lens_fill_bottom == tint["hex"]


# ------------------------------------------------- Frame Fill dirty-flag parity


def test_frame_fill_toggle_marks_the_document_dirty(fresh):
    win = fresh
    win._active_ws.add_curve(closed_diamond(0, 0, 40, layer=Layer.OUTLINE))
    win._clear_dirty()
    win._fill_show_chk.setChecked(True)
    assert win._fill_show_chk.isChecked()
    assert win._dirty


def test_frame_fill_opacity_marks_the_document_dirty(fresh):
    win = fresh
    win._clear_dirty()
    win._fill_opacity_slider.setValue(31)
    assert win._dirty


def test_lens_fill_toggle_marks_the_document_dirty(fresh):
    win = fresh
    win._active_ws.add_curve(circle(0, 0, 8))
    win._clear_dirty()
    win._lens_fill_show_chk.setChecked(True)
    assert win._lens_fill_show_chk.isChecked()
    assert win._dirty


def test_lens_fill_intensity_marks_the_document_dirty(fresh):
    win = fresh
    win._clear_dirty()
    win._lens_fill_intensity_slider.setValue(72)
    assert win._dirty


def test_refused_fill_toggle_leaves_the_document_clean(fresh, monkeypatch):
    # Nothing to fill: the tick reverts, so nothing was changed to save.
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    win = fresh
    win._clear_dirty()
    win._lens_fill_show_chk.setChecked(True)
    assert not win._lens_fill_show_chk.isChecked()
    assert not win._dirty


# ------------------------------------ loading must not clobber what it loaded


def test_loading_a_file_saved_on_another_tab_keeps_front_state(fresh, tmp_path):
    """Opening a .gdraw whose saved active tab isn't the one on screen switches
    tabs mid-load. The departing workspace's state was then written from
    widgets that still showed the OUTGOING document, silently overwriting the
    values just read from the file."""
    win = fresh
    ws = win._active_ws
    ws.add_curve(closed_diamond(0, 0, 15, layer=Layer.LENS))
    win._bridge_angle_spin.setValue(11.5)
    win._set_lens_fill_color("top", "#0a0b0c")
    win._lens_fill_opacity_slider.setValue(33)

    win._ws_tab_widget.setCurrentIndex(1)          # save with Temple R active
    path = tmp_path / "on_temple.gdraw"
    win._do_save_gdraw(str(path))

    # A different document on screen, sitting on Front with other values.
    win._dirty = False
    win._new()
    win._ws_tab_widget.setCurrentIndex(0)
    win._bridge_angle_spin.setValue(3.0)
    win._set_lens_fill_color("top", "#ffffff")
    win._lens_fill_opacity_slider.setValue(90)

    win._open_path(str(path))

    front = win._workspaces[0]
    assert front.bridge_angle == pytest.approx(11.5)
    assert front.lens_fill_top == "#0a0b0c"
    assert front.lens_fill_opacity == pytest.approx(0.33)


def test_loading_still_syncs_the_arriving_tab(fresh, tmp_path):
    # The guard must not suppress the restore — only the save-on-leave.
    win = fresh
    win._ws_tab_widget.setCurrentIndex(1)
    win._active_ws.add_curve(closed_diamond(0, 0, 15, layer=Layer.OUTLINE))
    win._fill_opacity_slider.setValue(21)
    path = tmp_path / "temple_active.gdraw"
    win._do_save_gdraw(str(path))

    win._dirty = False
    win._new()
    win._open_path(str(path))

    assert win._ws_tab_widget.currentIndex() == 1          # arrived on Temple R
    assert win._fill_opacity_slider.value() == 21          # …showing its values


def test_loading_leaves_the_flag_clear_even_on_a_bad_file(fresh, tmp_path, monkeypatch):
    import framedraft.app as app_mod
    monkeypatch.setattr(app_mod.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: None))
    win = fresh
    bad = tmp_path / "broken.gdraw"
    bad.write_bytes(b"not a zip")
    win._open_path(str(bad))
    assert win._loading is False


# ------------------------------------------- damaged metadata must not crash


def _rewrite_lens_fill(src, dst, replacement):
    """Copy a .gdraw, swapping the lens_fill block in every workspace SVG."""
    import re
    import zipfile
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            blob = zin.read(info.filename)
            if info.filename.endswith(".svg"):
                text = blob.decode("utf-8")
                text = re.sub(r'"lens_fill": \{.*?\}', replacement, text,
                              flags=re.S)
                blob = text.encode("utf-8")
            zout.writestr(info, blob)


@pytest.mark.parametrize("block, why", [
    ('"lens_fill": {"opacity": "very"}',       "opacity is not a number"),
    ('"lens_fill": {"intensity": "deep"}',     "intensity is not a number"),
    ('"lens_fill": {"top": "chartreusey"}',    "colour Qt cannot parse"),
    ('"lens_fill": {"opacity": null}',         "null where a number belongs"),
    ('"lens_fill": {"intensity": 1e400}',      "overflows to infinity"),
    ('"lens_fill": {"opacity": 40}',           "percent where 0-1 belongs"),
])
def test_damaged_lens_fill_metadata_degrades_to_defaults(fresh, tmp_path,
                                                         block, why):
    win = fresh
    win._active_ws.add_curve(closed_diamond(0, 0, 15, layer=Layer.LENS))
    good = tmp_path / "good.gdraw"
    win._do_save_gdraw(str(good))
    bad = tmp_path / f"bad_{abs(hash(block))}.gdraw"
    _rewrite_lens_fill(good, bad, block)

    win._dirty = False
    win._new()
    win._open_path(str(bad))                       # must not raise

    ws = win._active_ws
    assert 0.0 <= ws.lens_fill_opacity <= 1.0, why
    assert 0.5 <= ws.lens_fill_intensity <= 8.0, why
    assert QColor(ws.lens_fill_top).isValid(), why
    assert QColor(ws.lens_fill_bottom).isValid(), why
    assert ws.doc_curves, "the drawing itself must still load"
