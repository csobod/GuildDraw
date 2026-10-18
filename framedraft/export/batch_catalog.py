"""Catalog PDFs for a folder (BUILDPLAN *Road to 1.4*, item 3): the engine
behind File ▸ Export ▸ Catalog PDFs for a Folder… and ``scripts/batch_catalog.py``.

For every top-level ``*.gdraw`` in a library folder (subfolders such as
``bespoke/`` are left alone) a run opens the file in a GuildDraw window that is
never shown (the app's own loader), turns the Frame Fill on in the front and
both temple workspaces at one color and opacity (style "color"), and, when
asked, the Inlay Fill on every tab with a closed seat, saves the file
back when that changed anything — the originals that will change are copied to
``<library>/_backup/<timestamp>/`` first — and writes ``<design name>.pdf`` with
PDF for Catalog's own code, using the saved PDF preferences with *Include fill*
forced on for the run. Everything goes through the app's code, so the pages
match what the app makes by hand. The preferences are read, never written.

The Qt-free parts — which files, the backup copy, the fill record, the report
— are under test here; :func:`run_batch_catalog` drives a ``MainWindow`` the
caller builds and reports one verdict per file through a callback.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..document import Layer

TAB_NAMES = ("front", "temple_r", "temple_l", "component")
FILL_TABS = ("front", "temple_r", "temple_l")


@dataclass
class BatchCatalogOptions:
    color:    str = "#000000"      # #rrggbb, lower case
    opacity:  float = 1.0          # 0..1
    tabs:     tuple = FILL_TABS    # workspaces to fill
    out:      Path | None = None   # PDF folder; None = <library>/catalog
    dry_run:  bool = False         # report what would change; write nothing
    save:     bool = True          # write the fill back into the files
    pdf:      bool = True          # write the PDFs
    temple_ghost_off: bool = False # switch off a Ghost left on in a temple tab
    backup:   bool = True          # copy the originals that change first
    only:     tuple = ()           # file-name globs; empty = every file
    # The Inlay Fill too (2.0), on each tab with a closed INLAY seat: a
    # #rrggbb color, or None to leave every design's Inlay Fill as it is.
    inlay_color:   str | None = None
    inlay_opacity: float = 0.85    # 0..1


@dataclass
class FileVerdict:
    name:  str
    ok:    bool = True
    notes: list = field(default_factory=list)

    def line(self) -> str:
        mark = "ok  " if self.ok else "!!  "
        return f"{mark} {self.name}: " + "  ".join(self.notes)


@dataclass
class BatchCatalogReport:
    updated:     int = 0
    unchanged:   int = 0
    pdfs:        int = 0
    problems:    list = field(default_factory=list)   # "name: reason"
    ghost_files: list = field(default_factory=list)   # a Ghost on in a temple tab
    verdicts:    list = field(default_factory=list)   # FileVerdict, in order
    backup_dir:  Path | None = None
    out_dir:     Path | None = None                   # where the PDFs go
    dry_run:     bool = False
    stopped:     bool = False                         # canceled before the end

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        """In words: it read "updated 0, already set 8, PDFs 8, problems 0",
        and said nothing of where the PDFs went."""
        def n(k, one, many):
            return f"{k} {one if k == 1 else many}"
        where = f" to {self.out_dir}" if self.out_dir is not None else ""
        if self.dry_run:
            first = (f"Report only, nothing written: {n(self.pdfs, 'PDF', 'PDFs')} "
                     f"would go{where}; {n(self.updated, 'design', 'designs')} "
                     f"would be updated, {self.unchanged} already "
                     f"{'has' if self.unchanged == 1 else 'have'} the fill.")
        else:
            first = (f"{n(self.pdfs, 'PDF', 'PDFs')} written{where}. "
                     f"{n(self.updated, 'design', 'designs')} updated; "
                     f"{self.unchanged} already had the fill.")
        if self.stopped:
            first += " Stopped before the end."
        lines = [first, "No problems." if not self.problems else
                 f"{n(len(self.problems), 'file needs', 'files need')} attention:"]
        lines += ["  - " + m for m in self.problems]
        if self.backup_dir is not None and self.backup_dir.exists():
            lines.append(f"Originals backed up to {self.backup_dir}")
        if self.ghost_files:
            lines.append(
                f"{len(self.ghost_files)} file(s) have a temple half-drawn with the "
                "Ghost on, so their catalog page shows its mirrored other half. "
                "Run again with the Ghost switched off, or bake the halves.")
        return "\n".join(lines)


# ── Qt-free pieces ─────────────────────────────────────────────────────────

def library_files(library, only=()) -> list[Path]:
    """The top-level ``*.gdraw`` files of a folder, sorted by name; ``only``
    narrows them by file-name glob. Subfolders are not searched."""
    files = sorted(p for p in Path(library).glob("*.gdraw") if p.is_file())
    if only:
        files = [f for f in files
                 if any(fnmatch.fnmatch(f.name, g) for g in only)]
    return files


def backup_dir_for(library, now: float | None = None) -> Path:
    """``<library>/_backup/<timestamp>``: one folder per run, made on first use."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return Path(library) / "_backup" / stamp


def backup_original(path, backup_dir) -> Path:
    """Copy ``path`` into ``backup_dir``, keeping its times."""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / Path(path).name
    shutil.copy2(path, dest)
    return dest


def fill_record(ws) -> dict:
    """The fill as a workspace shows it, for the before/after compare."""
    return {"visible": bool(ws.fill_visible),
            "color":   str(ws.fill_color).lower(),
            "opacity": round(float(ws.fill_opacity), 4),
            "style":   ws.fill_style}


def wanted_fill(opts: BatchCatalogOptions) -> dict:
    return {"visible": True, "color": opts.color.lower(),
            "opacity": round(float(opts.opacity), 4), "style": "color"}


def inlay_record(ws) -> dict:
    """The Inlay Fill as a workspace shows it (see fill_record)."""
    return {"visible": bool(ws.inlay_fill_visible),
            "color":   str(ws.inlay_fill_color).lower(),
            "opacity": round(float(ws.inlay_fill_opacity), 4),
            "style":   ws.inlay_fill_style}


# ── The run ────────────────────────────────────────────────────────────────

def prepare_window(win) -> dict:
    """Fit a MainWindow to drive a batch: it never writes preferences, not
    even as it closes, never autosaves, never offers crash recovery, and
    exports the fill. Returns the catalog settings for the run."""
    win._save_prefs = lambda *_a, **_k: None
    win._save_prefs_on_close = lambda *_a, **_k: None
    win._recovery_offered = True
    timer = getattr(win, "_autosave_timer", None)
    if timer is not None:
        timer.stop()
    cat_cfg = dict(win._prefs.get("catalog_pdf", {}))
    cat_cfg["include_fill"] = True
    win._prefs["catalog_pdf"] = cat_cfg     # _gather_catalog_fills reads it there
    return cat_cfg


def run_batch_catalog(win, library, opts: BatchCatalogOptions,
                      progress=None, should_stop=None) -> BatchCatalogReport:
    """Run the batch through ``win`` (a MainWindow the caller built and never
    shows). ``progress(i, n, verdict)`` is called after each file;
    ``should_stop()`` is asked before each one. One bad file never stops the
    run: it is reported and left unchanged."""
    from PySide6.QtGui import QColor
    from .catalog_pdf import export_catalog_pdf

    library = Path(library)
    files = library_files(library, opts.only)
    out = Path(opts.out) if opts.out else library / "catalog"
    cat_cfg = prepare_window(win)
    report = BatchCatalogReport(dry_run=opts.dry_run)
    report.out_dir = out if opts.pdf else None
    if not files:
        return report
    want = wanted_fill(opts)
    if opts.save and opts.backup and not opts.dry_run:
        report.backup_dir = backup_dir_for(library)
    if opts.pdf and not opts.dry_run:
        out.mkdir(parents=True, exist_ok=True)
    tab_ws = dict(zip(TAB_NAMES, win._workspaces, strict=True))

    for i, path in enumerate(files, 1):
        if should_stop is not None and should_stop():
            report.stopped = True
            break
        verdict = FileVerdict(path.name)
        try:
            # The open keeps the previous document's photo calibration when
            # the next file has none, and the save then writes it into that
            # file. Clear it first so nothing carries over.
            for ws in win._workspaces:
                ws.image_px_per_mm = None
            status = win._open_gdraw(str(path), remember=False, quiet=True)
            if status != "ok":
                raise RuntimeError(
                    f"did not open cleanly ({status or 'unreadable'}); left untouched")
            before = {t: fill_record(tab_ws[t]) for t in opts.tabs}
            before_inlay = {t: inlay_record(tab_ws[t]) for t in opts.tabs}
            lens_on = [t for t in FILL_TABS if tab_ws[t].lens_fill_visible]
            # Only a Ghost that adds to the print: a closed temple outline casts
            # none since 2.0, and the warning sent every file back for nothing.
            ghost_on = [t for t in ("temple_r", "temple_l")
                        if tab_ws[t].mirror_enabled and win._ghost_twins(
                            tab_ws[t], [c for c in tab_ws[t].doc_curves
                                        if not c.mirrored])]
            ghost_cleared = False
            if ghost_on and opts.temple_ghost_off:
                # What the Ghost toggle does, applied to a tab that may not
                # be the active one (see MainWindow._on_mirror_toggled).
                for t in ghost_on:
                    ws = tab_ws[t]
                    ws.mirror_enabled = False
                    if ws.scene.mirror:
                        ws.scene.mirror.set_enabled(False)
                    ws.scene.set_mirror_display(False)
                    ws.snap.set_mirror(ws.scene.mirror.x if ws.scene.mirror else 0.0,
                                       False, horizontal=True)
                    ws.boxing_guide.set_mirror(False)
                ghost_cleared = True

            # Exactly what the Frame Fill panel does. A tab with no OUTLINE
            # (a front-only design's temples) has nothing to fill and is left
            # as it is; one whose outline does not close is a problem.
            failed, empty, filled = [], [], []
            for t in opts.tabs:
                ws = tab_ws[t]
                if not any(c.layer == Layer.OUTLINE for c in ws.doc_curves):
                    empty.append(t)
                    continue
                filled.append(t)
                ws.fill_style = "color"
                ws.fill_color = want["color"]
                ws.fill_opacity = want["opacity"]
                ws.scene.set_fill_color(QColor(want["color"]))
                ws.scene.set_fill_opacity(want["opacity"])
                win._apply_fill_material(ws)
                result = ws.scene.set_fill_visible(True)
                if result == "ok":
                    ws.fill_visible = True
                else:
                    ws.fill_visible = False
                    failed.append(f"{t}: outline {result}")
            # The Inlay Fill, as its panel sets it, on the tabs that have a
            # closed seat; a tab without one is left as it is.
            inlaid = []
            if opts.inlay_color:
                for t in opts.tabs:
                    ws = tab_ws[t]
                    if ws.scene.inlay_body_count() == 0:
                        continue
                    inlaid.append(t)
                    ws.inlay_fill_style = "color"
                    ws.inlay_fill_color = opts.inlay_color.lower()
                    ws.inlay_fill_opacity = round(float(opts.inlay_opacity), 4)
                    ws.scene.set_inlay_fill_color(QColor(ws.inlay_fill_color))
                    ws.scene.set_inlay_fill_opacity(ws.inlay_fill_opacity)
                    win._apply_inlay_fill_material(ws)
                    ws.inlay_fill_visible = (
                        ws.scene.set_inlay_fill_visible(True) == "ok")
            # Push the new state into the sidebar so the save path's sidebar
            # flush reads it back instead of the old values.
            win._restore_ws_sidebar_state(win._active_ws)
            before = {t: before[t] for t in filled}
            after = {t: fill_record(tab_ws[t]) for t in filled}
            inlay_changed = any(inlay_record(tab_ws[t]) != before_inlay[t]
                                for t in inlaid)
            if failed:
                raise RuntimeError("fill can't close — " + "; ".join(failed)
                                   + " (left untouched)")

            changed = before != after or ghost_cleared or inlay_changed
            if changed and opts.save and not opts.dry_run:
                if report.backup_dir is not None:
                    backup_original(path, report.backup_dir)
                tmp = str(path) + ".tmp"
                try:
                    not_carried = win._do_save_gdraw(tmp, carry_from=str(path)) or []
                    with open(tmp, "r+b") as f:
                        os.fsync(f.fileno())       # on disk before the swap
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                verdict.notes += [f"image not carried ({n})" for n in not_carried]
            if changed:
                report.updated += 1
                verdict.notes.append("fill set" if opts.save
                                     else "fill applied (not saved)")
            else:
                report.unchanged += 1
                verdict.notes.append("fill already set")

            if opts.pdf:
                pdf = out / f"{win._design_name()}.pdf"
                if not opts.dry_run:
                    components = win._gather_catalog_components()
                    if not any(components.values()):
                        raise RuntimeError("no geometry on the catalog layers")
                    export_catalog_pdf(str(pdf), components, cat_cfg,
                                       win._design_name(),
                                       win._gather_catalog_fills())
                report.pdfs += 1
                verdict.notes.append(f"→ {pdf.name}")
            if ghost_cleared:
                verdict.notes.append(f"(Ghost switched off: {', '.join(ghost_on)})")
            elif ghost_on:
                verdict.notes.append(f"(Ghost on in {', '.join(ghost_on)})")
                report.ghost_files.append(path.name)
            if inlaid:
                verdict.notes.append(f"(inlay fill: {', '.join(inlaid)})")
            if lens_on:
                verdict.notes.append(f"(lens fill on: {', '.join(lens_on)})")
            if empty:
                verdict.notes.append(f"(no outline in {', '.join(empty)})")
        except Exception as e:                  # one bad file never stops the run
            verdict.ok = False
            verdict.notes = [str(e)]
            report.problems.append(f"{path.name}: {e}")
        report.verdicts.append(verdict)
        if progress is not None:
            progress(i, len(files), verdict)

    win._dirty = False                          # no "save changes?" on close
    return report
