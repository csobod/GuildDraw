"""Preferences that do not read (2.0 bug hunt): a value of the wrong kind
falls back to its default instead of stopping the start, a damaged file is
kept aside instead of overwritten, and a save never leaves the file empty."""
import json

import pytest

import framedraft.prefs as prefs_mod


@pytest.fixture()
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    return tmp_path / "prefs.json"


def test_a_value_of_the_wrong_kind_reads_as_its_default(prefs_file):
    d = prefs_mod.DEFAULTS
    prefs_file.write_text(json.dumps({
        "stock_width_mm": "170", "mirror_on_startup": "false",
        "recent_files": 5, "hotkeys": {"line": 7, "circle": "Q"},
        "snap_radius_px": 12.0, "grid_spacing_mm": 3, "grid_major": float("inf"),
        "from_a_later_guilddraw": {"x": 1},
    }))
    p = prefs_mod.load()
    assert p["stock_width_mm"] == d["stock_width_mm"]
    assert p["mirror_on_startup"] is d["mirror_on_startup"]
    assert p["recent_files"] == []
    assert p["hotkeys"]["line"] == d["hotkeys"]["line"] and p["hotkeys"]["circle"] == "Q"
    assert p["snap_radius_px"] == 12 and isinstance(p["snap_radius_px"], int)
    assert p["grid_spacing_mm"] == 3.0
    assert p["grid_major"] == d["grid_major"]                # not a finite number
    assert p["from_a_later_guilddraw"] == {"x": 1}          # kept for it


def test_a_damaged_file_is_kept_aside_and_said(prefs_file):
    prefs_file.write_text('{"dark_mode": true, "recent_fi')   # cut short
    p = prefs_mod.load()
    assert p == prefs_mod.DEFAULTS
    aside = list(prefs_file.parent.glob("prefs.json.damaged-*"))
    assert len(aside) == 1 and not prefs_file.exists()
    assert aside[0].name in prefs_mod.LOAD_NOTE


def test_a_byte_order_mark_reads(prefs_file):
    prefs_file.write_text("﻿" + json.dumps({"dark_mode": True}), encoding="utf-8")
    assert prefs_mod.load()["dark_mode"] is True and prefs_mod.LOAD_NOTE is None


def test_a_save_replaces_the_file_whole(prefs_file, monkeypatch):
    prefs_mod.save({"dark_mode": True})
    assert json.loads(prefs_file.read_text())["dark_mode"] is True

    def fail(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(prefs_mod.json, "dumps", fail)
    prefs_mod.save({"dark_mode": False})                    # fails quietly
    assert json.loads(prefs_file.read_text())["dark_mode"] is True
    assert not (prefs_file.parent / "prefs.json.tmp").exists()


def test_a_window_starts_from_a_prefs_file_of_the_wrong_kinds(prefs_file):
    from PySide6.QtWidgets import QApplication
    prefs_file.write_text(json.dumps({"stock_width_mm": None, "pad_width_mm": "x",
                                      "mirror_on_startup": "no"}))
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    w._dirty = False
    w.close()
    w.deleteLater()
