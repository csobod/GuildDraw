"""Catalog PDFs for a folder (BUILDPLAN *Road to 1.4*, item 3): the Qt-free
pieces, and a run through a window that is never shown."""
import os
import shutil
import time

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod
from framedraft.document import Layer
from framedraft.export.batch_catalog import (
    BatchCatalogOptions, BatchCatalogReport, FileVerdict, backup_dir_for,
    backup_original, library_files,
)

from helpers import circle, closed_diamond, line


# ── Qt-free ────────────────────────────────────────────────────────────────

def test_library_files_takes_the_top_level_only_sorted(tmp_path):
    for name in ("b.gdraw", "a.gdraw", "a.gdraw.bak", "notes.txt"):
        (tmp_path / name).write_text("")
    (tmp_path / "bespoke").mkdir()
    (tmp_path / "bespoke" / "c.gdraw").write_text("")
    assert [p.name for p in library_files(tmp_path)] == ["a.gdraw", "b.gdraw"]
    assert [p.name for p in library_files(tmp_path, only=("b*",))] == ["b.gdraw"]
    assert library_files(tmp_path / "bespoke" / "none") == []


def test_backup_dir_is_one_folder_per_run(tmp_path):
    d = backup_dir_for(tmp_path, now=time.mktime((2026, 10, 15, 9, 30, 5, 0, 0, -1)))
    assert d == tmp_path / "_backup" / "20261015-093005"
    assert not d.exists()                       # made on first use only


def test_backup_original_keeps_the_file_and_its_time(tmp_path):
    src = tmp_path / "a.gdraw"
    src.write_bytes(b"zip")
    os.utime(src, (1_000_000_000, 1_000_000_000))
    dest = backup_original(src, tmp_path / "_backup" / "x")
    assert dest.read_bytes() == b"zip"
    assert int(dest.stat().st_mtime) == 1_000_000_000
    assert src.exists()


def test_report_summary_names_what_needs_attention(tmp_path):
    r = BatchCatalogReport(updated=2, unchanged=1, pdfs=3,
                           problems=["x.gdraw: fill can't close"],
                           ghost_files=["y.gdraw"], backup_dir=tmp_path)
    s = r.summary()
    assert s.startswith("updated 2, already set 1, PDFs 3, problems 1")
    assert "Originals backed up to" in s and "Needs attention" in s
    assert "Ghost on in a temple tab" in s
    assert not r.ok
    assert BatchCatalogReport(dry_run=True).summary().startswith("would update 0")
    assert FileVerdict("a.gdraw", notes=["fill set", "→ a.pdf"]).line() == \
        "ok   a.gdraw: fill set  → a.pdf"
    assert FileVerdict("b.gdraw", ok=False, notes=["bad"]).line().startswith("!!   b.gdraw")


# ── The run ────────────────────────────────────────────────────────────────

@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path / "prefs")
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs" / "prefs.json")
    (tmp_path / "prefs").mkdir()
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


@pytest.fixture()
def library(win, tmp_path):
    """Two designs authored by the app: one whose outline closes, one whose
    outline does not (so the fill cannot). A copy in a subfolder is bait."""
    lib = tmp_path / "Frame Library"
    lib.mkdir()
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 40, layer=Layer.OUTLINE),
              circle(-15, 0, 10), circle(15, 0, 10)):
        ws.add_curve(c)
    assert win._do_save(str(lib / "a.gdraw"))
    win._new()
    win._active_ws.add_curve(line([(0, 0), (40, 0), (40, 30)], layer=Layer.OUTLINE))
    assert win._do_save(str(lib / "open.gdraw"))
    (lib / "bespoke").mkdir()
    shutil.copy2(lib / "a.gdraw", lib / "bespoke" / "a.gdraw")
    return lib


def test_a_run_fills_saves_backs_up_and_writes_the_pdfs(win, library):
    from framedraft.export.gdraw import load_gdraw
    before_open = (library / "open.gdraw").stat().st_mtime_ns
    report = win._run_catalog_batch(
        str(library), BatchCatalogOptions(color="#112233", opacity=0.5))
    assert (report.updated, report.unchanged, report.pdfs) == (1, 0, 1)
    assert len(report.problems) == 1 and report.problems[0].startswith("open.gdraw:")
    assert "fill can't close" in report.problems[0]
    assert [v.name for v in report.verdicts] == ["a.gdraw", "open.gdraw"]
    assert "(no outline in temple_r, temple_l)" in report.verdicts[0].notes
    # The PDF, beside the designs
    pdf = library / "catalog" / "a.pdf"
    assert pdf.stat().st_size > 0
    assert not (library / "catalog" / "open.pdf").exists()
    # The original, backed up, then the fill written into the file
    assert (report.backup_dir / "a.gdraw").exists()
    fill = load_gdraw(str(library / "a.gdraw"))["front"]["fill"]
    assert (fill["visible"], fill["color"], fill["opacity"], fill["style"]) == \
        (True, "#112233", 0.5, "color")
    # The file that could not be filled is exactly as it was
    assert (library / "open.gdraw").stat().st_mtime_ns == before_open
    assert not (report.backup_dir / "open.gdraw").exists()
    # The subfolder was never looked at
    assert not (library / "bespoke" / "catalog").exists()
    # The design open in the real window was never touched
    assert win._current_path == str(library / "open.gdraw")
    assert not win._dirty
    # A second run finds the fill already set and backs nothing up (the
    # two runs may share a timestamp; what matters is that no copy is made)
    copy_time = (report.backup_dir / "a.gdraw").stat().st_mtime_ns
    again = win._run_catalog_batch(
        str(library), BatchCatalogOptions(color="#112233", opacity=0.5))
    assert (again.updated, again.unchanged, again.pdfs) == (0, 1, 1)
    backups = [p for p in (library / "_backup").rglob("*.gdraw")]
    assert [p.name for p in backups] == ["a.gdraw"]
    assert backups[0].stat().st_mtime_ns == copy_time


def test_a_run_never_writes_the_preferences(win, library):
    # The hidden window forces "Include fill" on for the run and was never
    # shown; neither may reach the maker's prefs file, not even as it closes.
    prefs_mod.save(win._prefs)
    on_disk = prefs_mod._FILE.read_bytes()
    win._run_catalog_batch(str(library), BatchCatalogOptions(dry_run=True))
    assert prefs_mod._FILE.read_bytes() == on_disk
    assert win._prefs["catalog_pdf"]["include_fill"] is False


def test_a_dry_run_writes_nothing(win, library):
    stamp = (library / "a.gdraw").stat().st_mtime_ns
    report = win._run_catalog_batch(str(library), BatchCatalogOptions(dry_run=True))
    assert report.dry_run and report.updated == 1 and report.pdfs == 1
    assert not (library / "catalog").exists()
    assert not (library / "_backup").exists()
    assert (library / "a.gdraw").stat().st_mtime_ns == stamp
    assert report.summary().startswith("would update 1")


def test_the_pdfs_can_go_elsewhere_and_the_files_can_stay(win, library, tmp_path):
    out = tmp_path / "pages"
    stamp = (library / "a.gdraw").stat().st_mtime_ns
    report = win._run_catalog_batch(
        str(library), BatchCatalogOptions(out=out, save=False))
    assert (out / "a.pdf").stat().st_size > 0
    assert (library / "a.gdraw").stat().st_mtime_ns == stamp
    assert report.backup_dir is None
    assert "fill applied (not saved)" in report.verdicts[0].notes


def test_a_cancel_stops_before_the_next_file(win, library):
    seen = []
    report = win._run_catalog_batch(
        str(library), BatchCatalogOptions(dry_run=True),
        progress=lambda i, n, v: seen.append(v.name),
        should_stop=lambda: len(seen) >= 1)
    assert seen == ["a.gdraw"] and report.stopped
    assert "(stopped)" in report.summary()


# ── The dialogs ────────────────────────────────────────────────────────────

def test_the_options_dialog_hands_back_what_it_shows(tmp_path):
    from framedraft.batch_catalog_ui import BatchCatalogOptionsDialog
    last = {"color": "#445566", "opacity_pct": 80, "save_fill": False,
            "temple_ghost_off": True, "out": ""}
    dlg = BatchCatalogOptionsDialog(None, str(tmp_path), last)
    opts = dlg.options()
    assert (opts.color, opts.opacity, opts.save, opts.temple_ghost_off,
            opts.dry_run, opts.out) == ("#445566", 0.8, False, True, False, None)
    dlg._out_edit.setText(str(tmp_path / "pages"))
    dlg._dry_chk.setChecked(True)
    assert dlg.options().out == str(tmp_path / "pages")
    assert dlg.options().dry_run
    remembered = dlg.remembered()
    assert remembered["library"] == str(tmp_path)
    assert (remembered["color"], remembered["opacity_pct"]) == ("#445566", 80)
    dlg.deleteLater()


def test_the_progress_dialog_counts_logs_and_turns_cancel_into_close():
    from PySide6.QtWidgets import QDialogButtonBox
    from framedraft.batch_catalog_ui import BatchCatalogProgressDialog
    dlg = BatchCatalogProgressDialog(None, 3)
    assert not dlg.canceled()
    dlg.step(1, 3, FileVerdict("a.gdraw", notes=["fill set"]).line())
    assert dlg._bar.value() == 1 and "a.gdraw" in dlg._log.toPlainText()
    dlg._on_cancel()                              # Cancel while running
    assert dlg.canceled()
    dlg.finish("updated 1, already set 0, PDFs 1, problems 0 (stopped)")
    assert dlg._buttons.button(QDialogButtonBox.StandardButton.Close) is not None
    assert dlg._buttons.button(QDialogButtonBox.StandardButton.Cancel) is None
    assert "(stopped)" in dlg._log.toPlainText()
    dlg.deleteLater()


def test_closing_the_progress_window_mid_run_cancels_and_keeps_it_open():
    from PySide6.QtWidgets import QDialog
    from framedraft.batch_catalog_ui import BatchCatalogProgressDialog
    dlg = BatchCatalogProgressDialog(None, 2)
    dlg.show()
    dlg.reject()                                  # Esc, or the title bar's close
    dlg.reject()
    assert dlg.canceled() and dlg.isVisible()
    assert dlg._log.toPlainText().count("Stopping after this file") == 1
    dlg.finish("updated 0, already set 0, PDFs 0, problems 0 (stopped)")
    dlg.reject()                                  # now it is Close
    assert not dlg.isVisible()
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg.deleteLater()
