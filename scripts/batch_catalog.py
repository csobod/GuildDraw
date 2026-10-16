#!/usr/bin/env python3
"""Batch Frame Fill + PDF-for-Catalog export for a GuildDraw frame library:
the command line of File ▸ Export ▸ Catalog PDFs for a Folder…, on the same
engine (``framedraft/export/batch_catalog.py``).

For every top-level ``*.gdraw`` in LIBRARY (subfolders such as ``bespoke/`` are
ignored) this:

  1. opens the file in a GuildDraw main window that is never shown (the
     app's own loader),
  2. turns the Frame Fill on in the front and both temple workspaces, at the
     color and opacity given (style "color"), and with --inlay-color the
     Inlay Fill on every tab with a closed INLAY seat, and saves the file
     back if that changed anything,
  3. writes ``<design name>.pdf`` with PDF for Catalog's own code, using your
     saved PDF preferences (paper, line weight, caption font, layers) with
     "Include fill" forced on for this run only.

Everything goes through GuildDraw's code (open, fill, save, catalog export),
so the results match what the app produces by hand. Your
~/.guilddraw/prefs.json is read but never written.

Safety
  * Before any file is changed, the originals that will change are copied to
    LIBRARY/_backup/<timestamp>/. The existing *.gdraw.bak files are left alone.
  * Files whose fill already matches are not rewritten (only re-exported).
  * A file that doesn't open cleanly, or whose outline doesn't close (so
    GuildDraw can't fill it), is reported and left unchanged.

Run with GuildDraw's own virtualenv, from anywhere:

    ~/Documents/Programs/GuildDraw/.venv/bin/python \\
        ~/Documents/Programs/GuildDraw/scripts/batch_catalog.py \\
        ~/Documents/"Frame Library" --color "#000000" --opacity 100

    --dry-run        report what would change; write nothing
    --no-pdf         update the fill only
    --no-save        export PDFs with the fill applied, but don't modify files
    --no-backup      skip the LIBRARY/_backup/<timestamp>/ copy
    --only "Pa*"     limit to file names matching a glob (repeatable)
    --out DIR        PDF folder (default LIBRARY/catalog)
    --tabs ...       workspaces to fill (default: front temple_r temple_l)
    --temple-ghost-off  switch off a mirror Ghost left on in a temple tab
                     (it prints a flipped second outline over the temple)
    --inlay-color "#3fb0a5"   set the Inlay Fill too, at this color
    --inlay-opacity 85        and this opacity, 0-100 percent (default 85)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

GUILDDRAW_ROOT = Path(__file__).resolve().parent.parent
TAB_NAMES = ("front", "temple_r", "temple_l", "hinge")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Turn on the Frame Fill and export catalog PDFs for every "
                    ".gdraw in a library folder.")
    p.add_argument("library", type=Path, help="folder holding the .gdraw files")
    p.add_argument("--color", default="#000000",
                   help="fill color as #rrggbb (default #000000)")
    p.add_argument("--opacity", type=float, default=100.0,
                   help="fill opacity, 0-100 percent (default 100)")
    p.add_argument("--tabs", nargs="+", default=["front", "temple_r", "temple_l"],
                   choices=TAB_NAMES, help="workspaces to fill")
    p.add_argument("--out", type=Path, default=None,
                   help="folder for the PDFs (default LIBRARY/catalog)")
    p.add_argument("--only", action="append", default=[],
                   help="only file names matching this glob (repeatable)")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would happen; write nothing")
    p.add_argument("--no-save", action="store_true",
                   help="don't modify the .gdraw files")
    p.add_argument("--no-pdf", action="store_true",
                   help="don't export catalog PDFs")
    p.add_argument("--temple-ghost-off", action="store_true",
                   help="switch the mirror Ghost off in the temple workspaces "
                        "(a Ghost left on there prints a flipped second "
                        "outline over the temple on the catalog page)")
    p.add_argument("--no-backup", action="store_true",
                   help="skip the LIBRARY/_backup/<timestamp>/ copy")
    p.add_argument("--inlay-color", default=None,
                   help="also set the Inlay Fill, at this #rrggbb color, on "
                        "every tab with a closed INLAY seat")
    p.add_argument("--inlay-opacity", type=float, default=85.0,
                   help="the Inlay Fill's opacity, 0-100 percent (default 85)")
    p.add_argument("--guilddraw", type=Path, default=GUILDDRAW_ROOT,
                   help="GuildDraw source folder (default: this script's repo)")
    a = p.parse_args(argv)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", a.color):
        p.error(f"--color must look like #rrggbb, got {a.color!r}")
    if not 0.0 <= a.opacity <= 100.0:
        p.error("--opacity is a percentage, 0-100")
    if a.inlay_color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}",
                                                     a.inlay_color):
        p.error(f"--inlay-color must look like #rrggbb, got {a.inlay_color!r}")
    if not 0.0 <= a.inlay_opacity <= 100.0:
        p.error("--inlay-opacity is a percentage, 0-100")
    a.color = a.color.lower()
    a.opacity = round(a.opacity / 100.0, 4)
    a.inlay_color = a.inlay_color.lower() if a.inlay_color else None
    a.inlay_opacity = round(a.inlay_opacity / 100.0, 4)
    if not a.library.is_dir():
        p.error(f"no such folder: {a.library}")
    return a


def install_dialog_guard():
    """A modal dialog in a headless run would wait forever for an answer.
    Turn every blocking entry point into an exception naming it instead."""
    from PySide6.QtWidgets import (QColorDialog, QDialog, QFileDialog,
                                   QInputDialog, QMenu, QMessageBox)

    class DialogRaised(RuntimeError):
        pass

    def refuse(owner, name):
        def blocked(*args, **_kw):
            text = " | ".join(str(a) for a in args if isinstance(a, str))
            raise DialogRaised(f"GuildDraw tried to open {owner.__name__}."
                               f"{name}(): {text}".rstrip(": "))
        return staticmethod(blocked)

    for owner, names in {
        QMessageBox: ("about", "critical", "information", "question",
                      "warning", "exec"),
        QFileDialog: ("getExistingDirectory", "getOpenFileName",
                      "getOpenFileNames", "getSaveFileName"),
        QColorDialog: ("getColor",),
        QInputDialog: ("getDouble", "getInt", "getItem", "getText"),
        QDialog: ("exec",),
        QMenu: ("exec",),
    }.items():
        for n in names:
            setattr(owner, n, refuse(owner, n))


def main(argv=None) -> int:
    args = parse_args(argv)
    sys.path.insert(0, str(args.guilddraw))

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("GuildDraw")
    app.setOrganizationName("Guild of American Spectacle Makers")

    import framedraft.prefs as prefs_mod
    prefs_mod.save = lambda *_a, **_k: None          # read the prefs, never write them
    install_dialog_guard()

    from framedraft import __version__ as gd_version
    from framedraft.app import MainWindow
    from framedraft.export.batch_catalog import (
        BatchCatalogOptions, library_files, run_batch_catalog,
    )

    files = library_files(args.library, args.only)
    if not files:
        print(f"No .gdraw files in {args.library}")
        return 1
    opts = BatchCatalogOptions(
        color=args.color, opacity=args.opacity, tabs=tuple(args.tabs),
        out=args.out, dry_run=args.dry_run, save=not args.no_save,
        pdf=not args.no_pdf, temple_ghost_off=args.temple_ghost_off,
        backup=not args.no_backup, only=tuple(args.only),
        inlay_color=args.inlay_color, inlay_opacity=args.inlay_opacity)

    win = MainWindow()                                # never shown
    cat_cfg = win._prefs.get("catalog_pdf", {})
    mode = "DRY RUN — nothing will be written" if args.dry_run else "live run"
    print(f"GuildDraw {gd_version}  ·  {len(files)} file(s)  ·  {mode}")
    print(f"Fill {args.color} @ {args.opacity * 100:g}% on {', '.join(args.tabs)}"
          + (f"; Inlay Fill {args.inlay_color} @ {args.inlay_opacity * 100:g}%"
             if args.inlay_color else ""))
    if not args.no_pdf:
        out = args.out or (args.library / "catalog")
        print(f"PDFs → {out}  (paper {cat_cfg.get('paper')}, "
              f"font {cat_cfg.get('caption_font')!r}, "
              f"line {cat_cfg.get('line_weight_mm')} mm)")
    print()

    report = run_batch_catalog(win, args.library, opts,
                               progress=lambda _i, _n, v: print("  " + v.line()))
    print()
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
