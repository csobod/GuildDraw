"""Shared PyInstaller analysis inputs for GuildDraw.

Imported by both ``framedraft.spec`` (one-folder build) and
``framedraft-onefile.spec`` (portable single exe) so the two builds can never
drift in their hidden imports, bundled data files, or excluded Qt modules.

Plain importable module — the ``collect_*`` helpers work fine outside the spec
namespace, and nothing here references the spec-only ``Analysis``/``EXE``
globals.
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# App icon, relative to the spec directory (repo root). PyInstaller resolves
# EXE(icon=...) relative to the spec, so the same string works in both specs.
ICON_PATH = "assets/icon.ico"

# framedraft modules reached only through lazy/conditional imports that
# PyInstaller's static analysis misses.
_HIDDEN_FRAMEDRAFT = [
    "framedraft.document",
    "framedraft.splash",
    "framedraft.calibration",
    "framedraft.construction",
    "framedraft.geometry",
    "framedraft.boxing",
    "framedraft.resize",
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
    "framedraft.export.dxf_import",
    "framedraft.export.png",
    "framedraft.export.validate",
    "framedraft.export.gdraw",
    "framedraft.export.oma",
    "framedraft.export.batch",
]

# Qt modules this app never touches — excluded to keep the bundle lean.
# NOTE: QtSvg / QtSvgWidgets are intentionally NOT excluded — QSvgRenderer
# renders the toolbar icons at runtime (and the app icon at build time).
_EXCLUDED_QT = [
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
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]


def analysis_inputs():
    """Return the kwargs shared by both specs' ``Analysis(...)`` calls."""
    ezdxf_datas = collect_data_files("ezdxf", excludes=["**/*.pyx", "**/*.pxd", "**/*.h"])
    ezdxf_hidden = collect_submodules("ezdxf")
    # Shapely is a binary extension (GEOS DLLs); collect_all ensures the DLLs
    # and any data files land correctly.
    shapely_datas, shapely_binaries, shapely_hidden = collect_all("shapely")
    framedraft_datas = [("framedraft/resources", "framedraft/resources")]
    return {
        "binaries": shapely_binaries,
        "datas": ezdxf_datas + shapely_datas + framedraft_datas,
        "hiddenimports": ezdxf_hidden + shapely_hidden + _HIDDEN_FRAMEDRAFT,
        "excludes": _EXCLUDED_QT,
    }
