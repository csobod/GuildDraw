# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for GuildDraw (FrameDraft) — ONE-FOLDER build.
# Build:  python -m PyInstaller framedraft.spec --clean
# Output: dist/GuildDraw/GuildDraw.exe  (one-folder, Windows)
#
# This is the build the Inno Setup installer (installer/GuildDraw.iss) packages.
# Analysis inputs (hidden imports, bundled data, Qt excludes) live in
# build_common.py so they stay in sync with framedraft-onefile.spec.
#
import os
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821 — SPECPATH is injected by PyInstaller
from build_common import ICON_PATH, analysis_inputs

a = Analysis(
    ["main.py"],
    pathex=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    **analysis_inputs(),
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GuildDraw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX packing trips AV/EDR heuristics — see BUILDPLAN "Security hardening"
    console=False,          # windowed — no terminal popup on Windows
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
    contents_directory=".", # flat layout: DLLs next to the exe (avoids _internal search failures on network drives)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,              # UPX packing trips AV/EDR heuristics — see BUILDPLAN "Security hardening"
    upx_exclude=[],
    name="GuildDraw",
)
