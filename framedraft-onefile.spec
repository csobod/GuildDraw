# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for GuildDraw (FrameDraft) — ONE-FILE portable build.
# Build:  python -m PyInstaller framedraft-onefile.spec --clean
# Output: dist/GuildDraw.exe  (single self-contained exe, Windows)
#
# A double-clickable portable binary — no install, no admin. Slower first
# launch than the one-folder build (it self-extracts to a temp dir on each run).
# Analysis inputs are shared with framedraft.spec via build_common.py.
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

# One-file: bundle binaries + datas directly into the EXE (no COLLECT step).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GuildDraw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX packing trips AV/EDR heuristics — see BUILDPLAN "Security hardening"
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed — no terminal popup on Windows
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)
