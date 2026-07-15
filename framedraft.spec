# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for GuildDraw (FrameDraft) — ONE-FOLDER build.
# Build:  python -m PyInstaller framedraft.spec --clean
# Output: dist/GuildDraw/GuildDraw.exe  (one-folder, Windows)
#         dist/GuildDraw.app            (bundle, macOS — see scripts/build_release_macos.sh)
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
    icon=(ICON_PATH if (sys.platform == "win32" and os.path.exists(ICON_PATH))
          else None),       # .ico is Windows-only; macOS gets .icns via BUNDLE
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

if sys.platform == "darwin":
    # framedraft/__init__.py is a bare version stamp — safe to import here.
    from framedraft import __version__ as _app_version

    app = BUNDLE(
        coll,
        name="GuildDraw.app",
        icon="assets/icon.icns" if os.path.exists("assets/icon.icns") else None,
        bundle_identifier="org.spectaclemakers.guilddraw",
        version=_app_version,
        info_plist={
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "GuildDraw Project",
                "CFBundleTypeExtensions": ["gdraw"],
                "CFBundleTypeRole": "Editor",
            }],
        },
    )
