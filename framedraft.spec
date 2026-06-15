# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for GuildDraw (FrameDraft)
# Build:  python -m PyInstaller framedraft.spec --clean
# Output: dist/GuildDraw/GuildDraw.exe  (one-folder, Windows)
#
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

# ezdxf has no contrib hook; bundle its resource PNGs and submodules explicitly.
ezdxf_datas = collect_data_files("ezdxf", excludes=["**/*.pyx", "**/*.pxd", "**/*.h"])
ezdxf_hidden = collect_submodules("ezdxf")

# Shapely is a binary extension (uses GEOS DLLs); collect_all ensures the DLLs
# and any data files land correctly in dist.
shapely_datas, shapely_binaries, shapely_hidden = collect_all("shapely")

# Bundle the SVG toolbar/tool icons shipped inside the framedraft package.
framedraft_datas = [
    ("framedraft/resources", "framedraft/resources"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=shapely_binaries,
    datas=ezdxf_datas + shapely_datas + framedraft_datas,
    hiddenimports=ezdxf_hidden + shapely_hidden + [
        # framedraft modules — lazy/conditional imports missed by static analysis
        "framedraft.document",
        "framedraft.calibration",
        "framedraft.construction",
        "framedraft.geometry",
        "framedraft.prefs",
        "framedraft.library",
        "framedraft.textpath",
        "framedraft.canvas.items",
        "framedraft.canvas.mirror",
        "framedraft.canvas.scene",
        "framedraft.canvas.snapping",
        "framedraft.canvas.dim",
        "framedraft.canvas.measure_bar",
        "framedraft.canvas.move_gizmo",
        "framedraft.canvas.readiness_dot",
        "framedraft.tools.draw",
        "framedraft.tools.edit",
        "framedraft.tools.circle",
        "framedraft.tools.dim",
        "framedraft.tools.trim",
        "framedraft.tools.fillet",
        "framedraft.tools.split",
        "framedraft.tools.offset",
        "framedraft.tools.point_move",
        "framedraft.tools.text",
        "framedraft.export.svg",
        "framedraft.export.dxf",
        "framedraft.export.png",
        "framedraft.export.validate",
        "framedraft.export.gdraw",
        "framedraft.export.oma",
        "framedraft.export.batch",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt modules this app never touches
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtAxContainer",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtDBus",
        "PySide6.QtDesigner",
        "PySide6.QtGraphs",
        "PySide6.QtGraphsWidgets",
        "PySide6.QtHelp",
        "PySide6.QtHttpServer",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtNetworkAuth",
        "PySide6.QtNfc",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtPositioning",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialBus",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtStateMachine",
        # NOTE: QtSvg / QtSvgWidgets intentionally NOT excluded —
        # QSvgRenderer is used in app.py to render toolbar icons at runtime.
        "PySide6.QtTest",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "PySide6.QtXml",
    ],
    noarchive=False,
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
    upx=True,
    console=False,          # windowed — no terminal popup on Windows
    icon=None,              # replace with "assets/icon.ico" once an icon exists
    contents_directory=".", # flat layout: DLLs next to the exe (avoids _internal search failures on network drives)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GuildDraw",
)
