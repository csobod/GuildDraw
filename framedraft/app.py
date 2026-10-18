import copy
import dataclasses
import datetime
import json
import math
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from . import __version__
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStatusBar,
    QGraphicsView, QDockWidget, QWidget, QVBoxLayout, QGridLayout,
    QFormLayout, QGroupBox, QPushButton, QSlider, QLabel, QToolButton,
    QDoubleSpinBox, QFileDialog, QComboBox, QMessageBox,
    QDialog, QCheckBox, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem,
    QScrollArea, QTabWidget, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QColorDialog, QAbstractItemView, QRubberBand, QDialogButtonBox,
    QSizePolicy,
)
from PySide6.QtCore import (
    Qt, QByteArray, QEvent, QObject, QPointF, QSize, QTimer, Signal, QRect, QRectF,
    QPoint,
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QBrush, QFontMetrics, QIcon, QPainter,
    QPen, QPixmap, QTransform,
)

from . import theme
from .canvas.items import CurveItem
from .canvas.dim import DimItem
from .canvas.measure_bar import MeasureBar
from .canvas.obverse_badge import CanvasHint, ObverseBadge, QuietFaceLabel
from .collapsible import CollapsibleBox
from .canvas.readiness_dot import ReadinessDot, readiness_state
from .canvas.scene import (FrameScene, TextItem, DEFAULT_LENS_FILL_TOP,
                           DEFAULT_LENS_FILL_BOTTOM, DEFAULT_LENS_FILL_OPACITY,
                           DEFAULT_LENS_FILL_INTENSITY, DEFAULT_INLAY_FILL_COLOR,
                           DEFAULT_INLAY_FILL_OPACITY, deepen_tint,
                           intensity_from_slider, slider_from_intensity,
                           LENS_FILL_INTENSITY_MIN, LENS_FILL_INTENSITY_MAX)
from .canvas.snapping import SnapEngine
from .calibration import CalibTool
from .construction import ConstructionGuides, BoxingGuide, RectGuide
from . import prefs as _prefs_mod
from . import bpi_tints as _bpi_tints
from . import image_links
from .document import (
    Layer, Calibration, MirrorAxis, FormingMetadata, MachinedBridge, FaceImage,
    Curve, SplineNode, ControlPoint, DimLine, WORKSPACE_LAYERS,
    BevelSpec, BEVEL_PRESETS,
)
from .geometry import (mirror_curve, circle_to_spline, arc_to_spline, sample_curve,
                       drop_end_handles)
from .tools.draw import DrawTool
from .tools.edit import EditTool
from .tools.dim import DimTool
from .tools.circle import CircleTool
from .tools.trim import TrimTool
from .tools.fillet import FilletTool
from .tools.split import SplitTool
from .tools.offset import OffsetTool
from .tools.rebuild import RebuildSplineTool
from .tools.point_move import PointMoveTool
from .tools.text import TextTool, TextDialog
from .pinnable_toolbar import PinnableToolBar
from .tooltips import TooltipFilter
from .icons import ICONS_DIR as _ICONS_DIR, make_icon as _make_icon


# Color-bar size (px) inside the Lens Fill stop buttons.
_LENS_SWATCH_PX = (64, 14)


# Saved documents are ordinary files a maker can edit, share, or damage, and
# _load_ws_data runs outside the open-time try/except — so a malformed value in
# the metadata took the app down on open rather than degrading to a default.
def _hex_or(value, fallback: str) -> str:
    """*value* if it is a color Qt can parse, else *fallback*."""
    if isinstance(value, str) and QColor(value).isValid():
        return QColor(value).name()
    return fallback


def _num_or(value, fallback: float, lo: float, hi: float) -> float:
    """*value* as a float clamped to [lo, hi], else *fallback*."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    if out != out or out in (float("inf"), float("-inf")):   # NaN / ±inf
        return fallback
    return max(lo, min(hi, out))


def _curves_bbox(curves, layers=None, x_lo=None, x_hi=None):
    """Return (min_x, min_y, max_x, max_y) over matched curves, or None if empty.

    layers: set of Layer values to include; None = all layers.
    x_lo / x_hi: filter curves by node-centroid x to isolate one side of the mirror.
    """
    matched = []
    for c in curves:
        if layers and c.layer not in layers:
            continue
        if c.nodes and (x_lo is not None or x_hi is not None):
            cx = sum(n.x for n in c.nodes) / len(c.nodes)
            if x_lo is not None and cx < x_lo:
                continue
            if x_hi is not None and cx > x_hi:
                continue
        matched.append(c)
    if not matched:
        return None
    # Exact drawn extents (path bounds), not the control polygon: handles
    # pushed a 150 mm temple to "200 mm" in the Measurements panel.
    from .canvas.items import build_path
    rect = QRectF()
    for c in matched:
        if c.nodes:
            rect = rect.united(build_path(c).boundingRect())
    if rect.isNull():
        return None
    return (rect.left(), rect.top(), rect.right(), rect.bottom())


# Application stylesheet + canvas colors come from framedraft.theme
# (single palette source; the old hardcoded QSS / QSS_DARK pair lives there
# as one token-driven template).

_DOCK_WIDTH = 270

# The toolbar's buttons in its own order and sections, as Preferences ▸
# Toolbar lists them. Tuple: (prefs_key, display_label, user_hideable).
_TOOLBAR_SECTIONS = [
    ("Drawing Tools", [
        ("select",       "Select",                  False),
        ("line",         "Line",                    True),
        ("spline",       "Spline",                  True),
        ("circle",       "Circle",                  True),
        ("arc",          "Arc",                     True),
        ("arc_sec",      "Arc (Start–End–Center)",  True),
        ("fillet",       "Fillet",                  True),
        ("dim",          "Dim",                     True),
        ("text",         "Text",                    True),
        ("trim",         "Trim",                    True),
        ("split_curve",  "Split Curve",             True),
        ("offset",       "Offset",                  True),
        ("rebuild",      "Rebuild Spline",          True),
        ("point_move",   "Point Move",              True),
    ]),
    ("Guides and Snapping", [
        ("ghost",        "Ghost",                   True),
        ("guides",       "Construction Guides",     True),
        ("snap",         "Snap",                    True),
        ("snap_palette", "Snap Palette",            True),
        ("grid",         "Grid",                    True),
        ("smooth",       "Smooth Handles",          True),
        ("boxing",       "Boxing Guide",            True),
        ("stock",        "Stock Guide",             True),
        ("pad",          "Pad Guide",               True),
        ("obverse",      "View Obverse",            True),
    ]),
    ("Operations", [
        ("mirror",       "Mirror (Bake)",           True),
        ("mirror_close", "Mirror Close",            True),
        ("copy_temple",  "Temple Copy",             True),
        ("join",         "Join",                    True),
        ("snap_node",    "Snap Node to Endpoint",   True),
        ("split",        "Split at Node",           True),
        ("explode",      "Explode",                 True),
        ("fit",          "Fit",                     True),
    ]),
]
_TOOLBAR_ACTION_DEFS = [e for _section, entries in _TOOLBAR_SECTIONS for e in entries]

# Toolbar buttons that only make sense in some workspaces — hidden elsewhere
# whatever the prefs say (MainWindow._apply_toolbar_visibility).
_WS_ONLY_ACTIONS = {
    "guides":      ("front",),
    "boxing":      ("front",),
    "pad":         ("front",),
    "copy_temple": ("temple_r", "temple_l"),
    # A front or a temple has two faces to see; a component is cut, and
    # drawn, from one side only.
    "obverse":     ("front", "temple_r", "temple_l"),
    # ENGRAVING only exists in temple workspaces (WORKSPACE_LAYERS)
    "text":        ("temple_r", "temple_l"),
}

# What each layer becomes in GuildModel, on the Layers panel's layer rows
# (Road to 1.4, item 4; the USER-GUIDE's Layers panel section says the same).
_LAYER_TIPS = {
    Layer.OUTLINE: (
        "The profile GuildModel cuts. The largest closed curve is the profile; "
        "a closed curve inside it is a decorative opening (Hole1…); one outside "
        "it is ignored, unless it holds a lens: a combination frame's separated "
        "rim. Never mirrored: draw the whole contour, and bake both rims."),
    Layer.LENS: (
        "The lens apertures (Frame Front): two, or one for a monocle. The Ghost "
        "previews the other eye, but GuildModel reads only the lenses drawn: "
        "bake a twin with Mirror."),
    Layer.DRILL: (
        "Drill-mount holes (Frame Front): circles, written to an OMA trace as "
        "DRILLE and paired there across the Ghost axis. GuildModel does not "
        "read them."),
    Layer.SCULPT: (
        "Back-surface section cuts for GuildModel's sculpting. The Ghost "
        "previews them across the axis; GuildModel reads only those drawn."),
    Layer.COMPONENT: (
        "A pocket for what mounts on the posterior: a hinge, a bridge, an "
        "endpiece, a bridge bar. GuildModel cuts each closed curve as a "
        "pocket. Place one from the Library; the Ghost previews its twin, and "
        "GuildModel reads only those drawn. HINGE before 2.0."),
    Layer.ENGRAVING: (
        "What GuildModel engraves on a temple (1.8.1 and later). A closed drawn "
        "curve is a filled shape; a closed curve inside it is an island left "
        "standing, so an O is two circles; an open curve is traced as a "
        "stroke; text is engraved as stroke centerlines and stays editable "
        "text in the .gdraw."),
    Layer.INLAY: (
        "A seat for a plaque, a laminate or a metal plate (GuildModel 2.0). "
        "GuildModel cuts it to a depth and on a face it keeps per inlay, the "
        "visible face by default; on a temple that is the anterior, which "
        "View Obverse shows. An inlay inside another is a step; inside "
        "a COMPONENT curve, a step in the pocket's floor; past the part's "
        "edge, a step open there (a front-mounted bridge). It never crosses "
        "a LENS, DRILL or COMPONENT curve or a decorative opening, and two inlays "
        "nest or stay apart. Not mirrored: draw each seat, or Mirror (bake) a "
        "pair."),
    Layer.REF: "Reference geometry: never exported, and GuildModel ignores it.",
}

# View Obverse (Road to 2.0, item 8): the face toward the viewer once a tab's
# view is turned. A front is drawn facing the anterior, as its reference
# photo is; a temple is drawn from the posterior, the skin side, so engraved
# text reads naturally there.
_OBVERSE_FACE = {"front": "posterior", "temple_r": "anterior",
                 "temple_l": "anterior"}
# …and the face each tab is drawn from, for the quiet label of the default view.
_DEFAULT_FACE = {"front": "anterior", "temple_r": "posterior",
                 "temple_l": "posterior"}

# Shortcuts bound outside the hotkey table (menus and window QShortcuts).
# Preferences ▸ Hotkeys lists every one, and SettingsDialog._RESERVED_KEYS —
# which refuses them as hotkeys — is built from this list.
_FIXED_SHORTCUTS = [
    ("New",         ("Ctrl+N",)),
    ("Open",        ("Ctrl+O",)),
    ("Save",        ("Ctrl+S",)),
    ("Save As",     ("Ctrl+Shift+S",)),
    ("Undo",        ("Ctrl+Z",)),
    ("Redo",        ("Ctrl+Y", "Ctrl+Shift+Z")),
    ("Copy",        ("Ctrl+C",)),
    ("Paste",       ("Ctrl+V",)),
    ("Duplicate",   ("Ctrl+D",)),
    ("Select All",  ("Ctrl+A",)),
    ("Transform",   ("Ctrl+T",)),
    ("Group",       ("Ctrl+G",)),
    ("Ungroup",     ("Ctrl+Shift+G",)),
    ("Zoom In",     ("Ctrl++", "Ctrl+=")),
    ("Zoom Out",    ("Ctrl+-",)),
    ("Fit",         ("Ctrl+0",)),
    ("Preferences", ("Ctrl+,",)),
    ("Quit",        ("Ctrl+Q",)),
    ("Delete",      ("Del", "Backspace")),
    ("Cancel",      ("Esc",)),
]

# Keys the tools read while a value is being typed into the canvas (a Line
# length, a Fillet radius): a hotkey on one fired mid-number — bound to "1",
# typing a 15 mm length switched tools on the first digit.
_TYPING_KEYS = frozenset([*"0123456789", ".", ",", "-", "Return", "Enter",
                          "Tab", "Backtab"])

# Ordered hotkey action definitions used by SettingsDialog.
# Tuple: (prefs_key, display_label)
_HOTKEY_ACTION_DEFS = [
    ("line",         "Line tool"),
    ("spline",       "Spline tool"),
    ("circle",       "Circle tool"),
    ("arc",          "Arc tool"),
    ("arc_sec",      "Arc (Start–End–Center) tool"),
    ("fillet",       "Fillet tool"),
    ("dim",          "Dim tool"),
    ("trim",         "Trim tool"),
    ("split_curve",  "Split Curve tool"),
    ("offset",       "Offset tool"),
    ("rebuild",      "Rebuild Spline tool"),
    ("point_move",   "Point Move tool"),
    ("text",         "Text tool"),
    ("snap_node_ep", "Snap Node to Endpoint"),
    ("move_gizmo",   "Move gizmo"),
    ("join",         "Join curves"),
    ("obverse",      "View Obverse"),
    ("bookmark",     "Bookmark revision"),
    ("insert_square", "Insert □ (size notation)"),
]

# A hotkey as a tooltip names it, "(O)" or "(Ctrl+B)", after the tool's name.
_TIP_KEY = re.compile(r"\s*\((?:(?:Ctrl|Shift|Alt|Meta)\+)*[A-Z0-9][A-Za-z0-9]*\)\s*$")


# The workspaces' names as their tabs show them, by workspace type.
_TAB_TITLES = {"front": "Frame Front", "temple_r": "Temple R",
               "temple_l": "Temple L", "component": "Component"}


def _and_list(names) -> str:
    """'A', 'A and B', 'A, B and C': a list said in a sentence."""
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _open_error_text(path: str, reason) -> str:
    """What to say when *path* cannot be opened: which file, the likely
    cause, the version a save kept beside it when there is one, and the
    reader's own words last."""
    import datetime
    name = os.path.basename(path)
    text = (f"{name} could not be opened. It is not a GuildDraw design, or it "
            "is damaged: a copy that was cut short, for example.")
    bak = path + ".bak"
    if os.path.isfile(bak):
        when = datetime.datetime.fromtimestamp(
            os.path.getmtime(bak)).strftime("%Y-%m-%d %H:%M")
        text += (f"\n\nThe version before its last save is kept beside it as "
                 f"{name}.bak ({when}). To use it, copy it, rename the copy to "
                 f"end in {os.path.splitext(name)[1]}, and open that.")
    return text + f"\n\nTechnical detail: {reason}"


def _write_error_text(what: str, path: str, reason) -> str:
    """What to say when *what* ("save", "export the DXF") could not be
    written to *path*: nothing on disk changed, the likely cause, the way
    on, and the system's own words last."""
    folder = os.path.dirname(os.path.abspath(path)) or path
    if isinstance(reason, ValueError):
        # Not the folder: the writer refused a value (a NaN from an import).
        cause = ("The design holds a value that cannot be written (a number "
                 "that is not a number, perhaps from an import): undo the "
                 "change that brought it in, then try again.")
    else:
        cause = ("The folder may be read-only, full, or not yours to write "
                 "to: choose another folder.")
    return (f"GuildDraw could not {what} as {os.path.basename(path)} in "
            f"{folder}. Nothing there was changed.\n\n{cause}"
            f"\n\nTechnical detail: {reason}")


def _slider_row(slider, fmt) -> "QWidget":
    """*slider* with its value beside it, as *fmt*(value) says it: no slider
    in the panel showed its value."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    label = QLabel(fmt(slider.value()))
    label.setMinimumWidth(label.fontMetrics().horizontalAdvance("100%  "))
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: label.setText(fmt(v)))
    lay.addWidget(slider, 1)
    lay.addWidget(label)
    slider.value_label = label           # for tests and enabled state
    return row


def _is_guilddraw_svg(path: str) -> bool:
    """Whether *path* is a GuildDraw drawing (it carries the metadata block)
    rather than an SVG from another program, to import."""
    try:
        with open(path, "rb") as f:
            head = f.read(1 << 16)
    except OSError:
        return False
    return b"<metadata" in head and b'"curves"' in head


def _sibling_tmp(path: str) -> str:
    """A new, empty temporary file beside *path*, under a short name: the
    "<name>.tmp" sibling of a name near the 255-byte limit was too long, and
    the save blamed the folder."""
    import tempfile
    folder = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".guilddraw-", suffix=".tmp")
    os.close(fd)
    return tmp


def _give_default_mode(path: str) -> None:
    """The mode a new file gets from the umask: mkstemp makes it 0600."""
    if os.name != "posix":
        return
    mask = os.umask(0)
    os.umask(mask)
    try:
        os.chmod(path, 0o666 & ~mask)
    except OSError:
        pass


def _fsync_folder(path: str) -> None:
    """POSIX: the rename that put *path* in place, on disk."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        fd = os.open(os.path.dirname(os.path.abspath(path)),
                     os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_copy(src: str, dst: str) -> None:
    """Copy *src* over *dst* through a temporary file and one replace."""
    tmp = _sibling_tmp(dst)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _atomic_write_result(path: str, write):
    """_atomic_write, handing back what *write* returned."""
    out = []
    _atomic_write(path, lambda tmp: out.append(write(tmp)))
    return out[0] if out else None


def _atomic_write(path: str, write) -> None:
    """Have *write(tmp_path)* write a file, then put it at *path* in one
    replace, fsynced: an export that failed half-way left a cut-short file
    over the good one."""
    target = os.path.realpath(path)
    tmp = _sibling_tmp(target)
    try:
        write(tmp)
        with open(tmp, "r+b") as f:
            os.fsync(f.fileno())
        if os.path.exists(target):
            try:
                shutil.copymode(target, tmp)
            except OSError:
                pass
        else:
            _give_default_mode(tmp)
        os.replace(tmp, target)
        _fsync_folder(target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _tip_with_key(tip: str, key: str) -> str:
    """`tip` with the hotkey after the name that heads it ("Offset (O): …"),
    replacing any key written there before; no key, no parentheses. The keys
    were typed into the tooltips by hand, so a rebound tool kept naming its
    old one, and most tools named none."""
    head, sep, rest = tip.partition(":")
    if not sep:
        return tip
    head = _TIP_KEY.sub("", head)
    return f"{head} ({key}):{rest}" if key else f"{head}:{rest}"


# Hotkeys that INSERT INTO text fields. Unlike every other binding (which the
# _hotkey_dispatch guard silences while a text widget has focus), these only
# mean something while typing — they bypass the guard and use application
# scope so they reach modal dialogs (bookmark names, library saves, the
# engraving text dialog).
_TEXT_FIELD_HOTKEYS = {"insert_square"}


def _insert_text_into(widget, text: str) -> bool:
    """Type *text* at the cursor of a Qt text-entry widget; False if *widget*
    isn't one (the hotkey is then a silent no-op)."""
    from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
    if isinstance(widget, QLineEdit):
        widget.insert(text)
        return True
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        widget.insertPlainText(text)
        return True
    return False


def _matches_key_event(seq, event) -> bool:
    """True when a KeyPress *event* is exactly the bound sequence *seq*."""
    from PySide6.QtGui import QKeySequence
    if seq is None or seq.isEmpty():
        return False
    return (QKeySequence(event.keyCombination()).matches(seq)
            == QKeySequence.SequenceMatch.ExactMatch)


class CanvasView(QGraphicsView):
    """QGraphicsView: wheel-zoom, pan (middle- or right-drag, or Space with
    the left button), tool event routing."""

    zoom_changed = Signal(int)  # current zoom as integer percent (100 = 100%)
    released     = Signal()     # after any mouse release: a drag, if any, is over

    _MIN_ZOOM = 0.01    # 1%
    _MAX_ZOOM = 100.0   # 10,000%

    def __init__(self, scene: FrameScene, status_bar: QStatusBar):
        super().__init__(scene)
        self._status_bar = status_bar
        # The pointer's coordinates have a field of their own (MainWindow's
        # "coordsLabel"): written as the bar's message they replaced every
        # tool's prompt on the first mouse move.
        self._coords_label = status_bar.findChild(QLabel, "coordsLabel")
        self._calib_tool: CalibTool | None = None
        self._draw_tool:  DrawTool  | None = None
        self._dim_tool    = None
        self._pan_active = False
        self._pan_button = Qt.MouseButton.NoButton   # the button that pans
        self._pan_start = QPointF()
        self._space_held = False     # Space down: the left button pans
        # The last press went to a tool. The second half of a double-click
        # whose first press finished the tool (a Line closed on its first
        # node, an Arc's last click) arrived in Select mode and inserted a
        # node into the curve under it.
        self._press_to_tool = False
        self._delete_callback = None
        self._insert_node_callback = None
        self._snap_to_endpoint_callback = None
        self._move_pre_cb   = None   # () -> None, called once on drag-move start
        self._move_cb       = None   # (dx_mm, dy_mm) -> None
        self._move_end_cb   = None   # () -> None, called when drag-move ends
        self._escape_cb     = None   # () -> None, called on Esc with no active tool
        self._drag_move_start: QPointF | None = None
        self._drag_move_items: list = []   # pre-click selected items captured at press
        self._drag_moving      = False
        self._drag_pre_called  = False
        # Manual rubber-band selection (plain left-drag). Qt's built-in band is
        # suppressed once the press lands on an item, which made box-select
        # impossible over dense geometry; we drive our own band so a drag from
        # anywhere — empty space or on top of a curve — selects everything it
        # encloses/crosses.
        self._rb_origin: QPoint | None = None     # viewport press point
        self._rb_band:  QRubberBand | None = None
        self._rb_press_item = None                # CurveItem under press (click-select)
        self._rb_dragging   = False
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(theme.color("canvas.bg"))))
        # Vignette overlay (Preferences ▸ Appearance): 0 = off; the gradient
        # pixmap is cached per viewport size so painting is one blit.
        self._vignette: int = 0
        self._vignette_pm: QPixmap | None = None
        # Grid overlay (drawn in drawBackground, scene coords). Off by
        # default; fallbacks mirror prefs.DEFAULTS (2 mm, major every 10 mm).
        self._grid_visible: bool  = False
        self._grid_spacing: float = 2.0    # mm
        self._grid_major:   int   = 5      # every Nth line is heavier
        self._grid_minor_color: str | None = None   # None = theme token
        self._grid_major_color: str | None = None   # None = theme token
        self._grid_major_width: float = 1.0          # device px, cosmetic

        self.measure_bar = MeasureBar(self)
        # With `self` as context: a bare singleShot outlives the view and
        # fired into a deleted MeasureBar.
        QTimer.singleShot(0, self, self._reposition_measure_bar)
        # View Obverse's corner chip: a child of the view, never of the
        # viewport, whose scroll would carry it off with the drawing. The
        # quiet label names the face in the default view, in the same corner.
        self.obverse_badge = ObverseBadge(self)
        self.face_label = QuietFaceLabel(self)
        self.empty_hint = CanvasHint(self)
        self._default_face = ""

    # ------------------------------------------------------------------
    # Grid overlay (mm grid with major/minor divisions, drawn behind all)
    # ------------------------------------------------------------------

    def set_grid(self, visible: bool | None = None, spacing_mm: float | None = None,
                 major: int | None = None, minor_color: str | None = None,
                 major_color: str | None = None,
                 major_width: float | None = None):
        """Update grid config; color arguments use "" to fall back to the
        theme tokens (None leaves the current value untouched)."""
        if visible is not None:
            self._grid_visible = bool(visible)
        if spacing_mm is not None and spacing_mm > 0:
            self._grid_spacing = float(spacing_mm)
        if major is not None and major >= 1:
            self._grid_major = int(major)
        if minor_color is not None:
            self._grid_minor_color = minor_color or None
        if major_color is not None:
            self._grid_major_color = major_color or None
        if major_width is not None and major_width > 0:
            self._grid_major_width = float(major_width)
        self.viewport().update()

    _GRID_MIN_PX = 4.0   # hide a line level once its screen spacing drops below this

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)   # fills the canvas background
        if not self._grid_visible or self._grid_spacing <= 0:
            return
        sp    = self._grid_spacing
        major = max(1, self._grid_major)
        scale = abs(self.transform().m11())
        draw_minor = sp * scale >= self._GRID_MIN_PX
        draw_major = sp * major * scale >= self._GRID_MIN_PX
        if not draw_major:
            return   # too far zoomed out — even major lines would be a smear

        minor_col = self._grid_minor_color or theme.color("canvas.grid_minor")
        major_col = self._grid_major_color or theme.color("canvas.grid_major")
        minor_pen = QPen(QColor(minor_col), 0)
        minor_pen.setCosmetic(True)
        major_pen = QPen(QColor(major_col), self._grid_major_width)
        major_pen.setCosmetic(True)

        i0 = math.floor(rect.left()   / sp)
        i1 = math.ceil(rect.right()  / sp)
        j0 = math.floor(rect.top()    / sp)
        j1 = math.ceil(rect.bottom() / sp)
        top, bot, left, right = rect.top(), rect.bottom(), rect.left(), rect.right()

        for i in range(i0, i1 + 1):
            is_major = (i % major == 0)
            if is_major:
                painter.setPen(major_pen)
            elif draw_minor:
                painter.setPen(minor_pen)
            else:
                continue
            x = i * sp
            painter.drawLine(QPointF(x, top), QPointF(x, bot))
        for j in range(j0, j1 + 1):
            is_major = (j % major == 0)
            if is_major:
                painter.setPen(major_pen)
            elif draw_minor:
                painter.setPen(minor_pen)
            else:
                continue
            y = j * sp
            painter.drawLine(QPointF(left, y), QPointF(right, y))

    # ------------------------------------------------------------------
    # Vignette (viewport-space radial darkening, intensity 0–100)
    # ------------------------------------------------------------------

    def set_vignette(self, intensity: int):
        self._vignette = max(0, min(100, int(intensity)))
        self._vignette_pm = None
        self.viewport().update()

    def _render_vignette(self) -> QPixmap:
        from PySide6.QtGui import QRadialGradient
        size = self.viewport().size()
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        w, h = size.width(), size.height()
        g = QRadialGradient(w / 2.0, h / 2.0, math.hypot(w, h) / 2.0)
        g.setColorAt(0.0, QColor(0, 0, 0, 0))
        g.setColorAt(0.55, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 0, 0, round(self._vignette / 100.0 * 140)))
        p = QPainter(pm)
        p.fillRect(0, 0, w, h, QBrush(g))
        p.end()
        return pm

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self._vignette <= 0:
            return
        if (self._vignette_pm is None
                or self._vignette_pm.size() != self.viewport().size()):
            self._vignette_pm = self._render_vignette()
        painter.save()
        painter.resetTransform()
        painter.drawPixmap(0, 0, self._vignette_pm)
        painter.restore()

    def set_delete_callback(self, cb):
        self._delete_callback = cb

    def set_insert_node_callback(self, cb):
        self._insert_node_callback = cb

    def set_snap_to_endpoint_callback(self, cb):
        self._snap_to_endpoint_callback = cb

    def set_move_callbacks(self, pre_cb, move_cb, end_cb=None):
        self._move_pre_cb = pre_cb
        self._move_cb     = move_cb
        self._move_end_cb = end_cb

    def set_escape_callback(self, cb):
        self._escape_cb = cb

    def set_face_moved_callback(self, cb):
        """Called after a drag moved an unlocked reference photo: its place is
        saved with the design, and the drag left the design looking clean."""
        self._face_moved_cb = cb

    def _face_positions(self) -> list:
        return [it.pos() for it in getattr(self.scene(), "_face_items", [])]

    def set_calib_tool(self, tool: CalibTool):
        self._calib_tool = tool

    def set_draw_tool(self, tool: DrawTool | None):
        self._draw_tool = tool
        if tool is None and self._dim_tool is None:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        elif tool is not None:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        # Disable scene item selection while drawing; on return to Select,
        # re-enable only what layer visibility/locking allows.
        sc = self.scene()
        for item in sc.items():
            if isinstance(item, CurveItem):
                allowed = (tool is None
                           and sc.is_layer_visible(item.curve.layer)
                           and not sc.is_layer_locked(item.curve.layer))
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, allowed)
            elif isinstance(item, TextItem):
                allowed = (tool is None
                           and sc.is_layer_visible(item.text_obj.layer)
                           and not sc.is_layer_locked(item.text_obj.layer))
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, allowed)
                # Never ItemIsMovable: a text moves through the app's own drag
                # (snapshot, gizmo, measurements), as TextItem says. Setting it
                # here after any tool switch let Qt drag text on its own — a
                # jittery click moved it with no undo step and no star.

    def set_dim_tool(self, tool):
        self._dim_tool = tool
        if tool is not None:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif self._draw_tool is None:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def _reposition_measure_bar(self):
        self.measure_bar.reposition()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def focusNextPrevChild(self, next: bool) -> bool:
        # Suppress Tab focus traversal while a drawing tool is active so Tab can
        # be forwarded to the tool's handle_key for field switching.
        if self._draw_tool and self._draw_tool.active:
            return False
        return super().focusNextPrevChild(next)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_measure_bar()
        self.obverse_badge.reposition()
        self.face_label.reposition()
        self.empty_hint.reposition()
        self._ensure_scroll_room()

    def _ensure_scroll_room(self):
        """Grow this view's sceneRect so panning always reaches the geometry.

        The FrameScene pins its own sceneRect to the face image / default
        extents; left alone, the scrollbars clamp to that rect and you can't
        pan out to geometry drawn beyond it once zoomed in (and AnchorUnderMouse
        zoom drifts off the cursor when it hits that clamp). We give the *view*
        a generous sceneRect = (content ∪ visible area ∪ scene rect) padded by
        one viewport on every side, leaving the scene's own rect untouched for
        face/PNG/print rendering.
        """
        sc = self.scene()
        if sc is None:
            return
        vis = self.mapToScene(self.viewport().rect()).boundingRect()
        rect = sc.itemsBoundingRect()
        if rect.isNull():
            rect = vis
        else:
            rect = rect.united(vis)
        rect = rect.united(sc.sceneRect())
        # One-viewport pad so the user can always drag a full screen past content.
        rect.adjust(-vis.width(), -vis.height(), vis.width(), vis.height())
        self.setSceneRect(rect)

    def zoom(self) -> float:
        """The zoom (screen pixels per scene mm), whether or not the view is
        mirrored: View Obverse makes the transform's m11 negative."""
        return abs(self.transform().m11())

    def zoom_by(self, factor: float):
        """Scale the view by *factor*, clamped to [_MIN_ZOOM, _MAX_ZOOM]."""
        current = self.zoom()
        if not (math.isfinite(current) and current > 0.0):
            # A view a non-finite rectangle was fitted to: back to 1 px/mm
            # (round(NaN) raised here, and every later open in the window too).
            self.resetTransform()
            current = 1.0
        if not math.isfinite(factor) or factor <= 0.0:
            factor = 1.0
        target  = max(self._MIN_ZOOM, min(self._MAX_ZOOM, current * factor))
        f = target / current
        if abs(f - 1.0) > 1e-9:
            self.scale(f, f)
        self.zoom_changed.emit(round(self.zoom() * 100))

    def is_obverse(self) -> bool:
        return self.transform().m11() < 0.0

    def set_obverse(self, on: bool, face: str = ""):
        """View Obverse (BUILDPLAN *Road to 2.0*, item 8): mirror the view left
        to right, x → −x, to show the drawing from its other face. A view
        transform only, so the scene, snapping and every export are
        untouched. The scene point in the middle of the viewport stays there:
        the drawing turns in place. *face* is the face then toward the
        viewer, for the corner badge."""
        if on != self.is_obverse():
            vp = QRectF(self.viewport().rect())
            center = self.viewportTransform().inverted()[0].map(vp.center())
            flipped = QTransform(self.transform())
            flipped.scale(-1.0, 1.0)
            self.setTransform(flipped)
            self._ensure_scroll_room()
            self.centerOn(center)
        self.obverse_badge.set_face(face)
        self.obverse_badge.setVisible(on)
        if on:
            self.obverse_badge.reposition()
        self._sync_face_label()

    def set_default_face(self, face: str):
        """The face the drawing is seen from in the default view, for the
        quiet label ("" for a tab with no face to name)."""
        self._default_face = face
        self._sync_face_label()

    def _sync_face_label(self):
        show = bool(self._default_face) and not self.is_obverse()
        self.face_label.setText(self._default_face)
        self.face_label.setVisible(show)
        if show:
            self.face_label.reposition()

    def refresh_face_marks(self):
        """The badge's and the quiet label's colors, after a theme change."""
        self.obverse_badge.refresh_theme()
        self.face_label.refresh_theme()
        self.empty_hint.refresh_theme()

    def set_empty_hint(self, text: str | None):
        """Show *text* centered on the canvas, or hide the hint (None)."""
        if text:
            self.empty_hint.setText(text)
            self.empty_hint.show()
            self.empty_hint.reposition()
        else:
            self.empty_hint.hide()

    def fit_view(self, rect):
        """fitInView, then re-clamp into the wheel-zoom bounds — a tiny (or
        huge) scene rect must not land outside [_MIN_ZOOM, _MAX_ZOOM]."""
        if not all(math.isfinite(v) for v in (rect.x(), rect.y(),
                                               rect.width(), rect.height())):
            return                       # nothing a view can be fitted to
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_by(1.0)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return   # horizontal wheel tilt — not a zoom request
        # Ensure scroll room first so the anchor restore below has scrollbar
        # range to work with instead of drifting when it hits the old clamp.
        self._ensure_scroll_room()
        # Anchor manually. AnchorUnderMouse trusts QGraphicsView's internally
        # tracked mouse position, which only updates in the base
        # mouseMoveEvent — while a tool consumes moves that position goes
        # stale and every wheel tick yanked the viewport toward it (issue #3).
        vp_pos       = event.position()
        anchor_scene = self.mapToScene(vp_pos.toPoint())
        self.zoom_by(1.15 if delta > 0 else 1 / 1.15)
        self._ensure_scroll_room()
        after = self.mapFromScene(anchor_scene)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + round(after.x() - vp_pos.x()))
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + round(after.y() - vp_pos.y()))
        event.accept()

    def _pans(self, event) -> bool:
        """Whether a press pans: the middle or right button (GuildModel pans
        with either; a trackpad has no middle button), or the left one while
        Space is held."""
        b = event.button()
        return (b in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton)
                or (b == Qt.MouseButton.LeftButton and self._space_held))

    def _end_pan(self):
        self._pan_active = False
        self._pan_button = Qt.MouseButton.NoButton
        if self._space_held:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        self._faces_at_press = self._face_positions()
        self._press_to_tool = False
        # A release lost to a modal dialog (a hotkey mid-drag) must not leave
        # a band or a pan armed for the next press.
        if self._rb_origin is not None:
            if self._rb_band is not None:
                self._rb_band.hide()
            self._rb_origin = None
            self._rb_press_item = None
            self._rb_dragging = False
        if self._pan_active and event.button() != self._pan_button:
            self._end_pan()
        if self._pans(event):
            # A right-click with no drag pans nowhere and leaves the selection
            # alone: it reached Qt's own handler, which cleared the selection
            # and box-selected on a right-drag.
            self._pan_active = True
            self._pan_button = event.button()
            self._pan_start = event.position()
            self._ensure_scroll_room()   # once per pan, not per mouse move
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif (event.button() != Qt.MouseButton.LeftButton
                and ((self._calib_tool and self._calib_tool.active)
                     or (self._dim_tool and self._dim_tool.active)
                     or (self._draw_tool and self._draw_tool.active))):
            # A tool answers the left button only: a right-click split or
            # trimmed the curve under it, or placed a node, like a left one.
            event.accept()
        elif event.button() != Qt.MouseButton.LeftButton:
            event.accept()               # the back and forward buttons
        elif self._calib_tool and self._calib_tool.active:
            self._press_to_tool = True
            pos = self.mapToScene(event.position().toPoint())
            self._calib_tool.handle_press(pos, self.scene())
            event.accept()
        elif self._dim_tool and self._dim_tool.active:
            self._press_to_tool = True
            pos      = self.mapToScene(event.position().toPoint())
            mods     = event.modifiers()
            use_snap = not (mods & Qt.KeyboardModifier.ControlModifier)
            self._dim_tool.handle_press(pos, use_snap)
            event.accept()
        elif self._draw_tool and self._draw_tool.active:
            self._press_to_tool = True
            pos       = self.mapToScene(event.position().toPoint())
            mods      = event.modifiers()
            use_snap  = not (mods & Qt.KeyboardModifier.ControlModifier)
            constrain = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self._draw_tool.handle_press(pos, use_snap, constrain)
            event.accept()
        else:
            # Alt+click: cycle through overlapping selectable items in Z-order.
            # self.items(QPoint) tests against item shapes, returns highest-Z first.
            if (event.button() == Qt.MouseButton.LeftButton
                    and event.modifiers() & Qt.KeyboardModifier.AltModifier):
                vp_pos = event.position().toPoint()
                candidates = [it for it in self._items_near(vp_pos)
                              if self._rb_selectable(it)]
                if len(candidates) >= 2:
                    selected_ids = {id(it) for it in self.scene().selectedItems()}
                    current_idx = next(
                        (i for i, it in enumerate(candidates) if id(it) in selected_ids),
                        -1,
                    )
                    next_idx = (current_idx + 1) % len(candidates)
                    self.scene().clearSelection()
                    candidates[next_idx].setSelected(True)
                    self._status_bar.showMessage(
                        f"Alt+click: item {next_idx + 1} of {len(candidates)} overlapping"
                    )
                    event.accept()
                    return
            # Track potential drag-to-move (plain left-click, no modifiers)
            mods = event.modifiers()
            if (event.button() == Qt.MouseButton.LeftButton
                    and not (mods & Qt.KeyboardModifier.ControlModifier)
                    and not (mods & Qt.KeyboardModifier.ShiftModifier)
                    and not (mods & Qt.KeyboardModifier.AltModifier)):
                vp_pos    = event.position().toPoint()
                scene_pos = self.mapToScene(vp_pos)
                # Dots, gizmo arrows and dims take the press themselves (a dim
                # runs its own offset-drag; intercepting it would translate
                # the anchors instead). Curves and texts are picked with a
                # screen-pixel tolerance so they stay clickable at any zoom.
                top_item = self._top_pick(vp_pos)
                hit_selected = any(it.isSelected() for it in self._items_near(vp_pos)
                                   if isinstance(it, (CurveItem, DimItem, TextItem)))
                self._drag_moving     = False
                self._drag_pre_called = False
                if isinstance(top_item, (CurveItem, TextItem)) and hit_selected:
                    # Press on an ALREADY-SELECTED item → drag to move it (a
                    # text rides the same path as curves and dims, so a mixed
                    # selection moves as one). Capture the pre-click selection
                    # now — super() may reselect only the topmost item.
                    self._drag_move_items = [
                        it for it in self.scene().selectedItems()
                        if isinstance(it, (CurveItem, DimItem, TextItem))
                    ]
                    self._drag_move_start = scene_pos
                    super().mousePressEvent(event)
                elif top_item is None or isinstance(top_item, (CurveItem, TextItem)):
                    # Empty space or an UNSELECTED curve/text → manual
                    # rubber-band (drag) or click-select (no drag). We take
                    # over selection so a box-drag works even when it starts
                    # on top of a curve.
                    self._drag_move_items = []
                    self._drag_move_start = None
                    self._rb_origin     = vp_pos
                    self._rb_press_item = top_item
                    self._rb_dragging   = False
                    event.accept()
                    return
                else:
                    # NodeDot, HandleDot, gizmo arrow, DimItem — default handling.
                    self._drag_move_items = []
                    self._drag_move_start = None
                    super().mousePressEvent(event)
            else:
                self._drag_move_items = []
                self._drag_move_start = None
                if (event.button() == Qt.MouseButton.LeftButton
                        and mods == Qt.KeyboardModifier.ControlModifier):
                    # Ctrl+click toggles with the same pixel tolerance as a
                    # plain click; Qt's own hit test wanted the pointer on
                    # the stroke itself, so it missed at low zoom.
                    top_item = self._top_pick(event.position().toPoint())
                    if top_item is not None and self._rb_selectable(top_item):
                        self._toggle_selected(top_item)
                        event.accept()
                        return
                super().mousePressEvent(event)

    def _toggle_selected(self, item):
        """Ctrl+click: a curve in a group takes its whole group in or out of
        the selection. Toggling the member alone was undone at once, as
        selecting any member selects its group."""
        gid = getattr(getattr(item, "curve", None), "group_id", None)
        if not gid:
            item.setSelected(not item.isSelected())
            return
        sc = self.scene()
        members = [it for it in sc.items()
                   if isinstance(it, CurveItem) and it.curve.group_id == gid
                   and self._rb_selectable(it)]
        if item.isSelected():
            out = {id(it) for it in members}
            keep = [it for it in sc.selectedItems() if id(it) not in out]
            sc.select_items(keep)
        else:
            sc.select_items(members, clear=False)

    def mouseDoubleClickEvent(self, event):
        if self._pans(event):
            # A quick second pan stroke arrives as a double-click only.
            self.mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return
        tool_active = ((self._draw_tool and self._draw_tool.active)
                       or (self._dim_tool and self._dim_tool.active)
                       or (self._calib_tool and self._calib_tool.active))
        if self._press_to_tool and not tool_active:
            # Its first press finished the tool: the second half belongs to
            # that tool too, not to Select mode (see _press_to_tool).
            event.accept()
            return
        if self._draw_tool and self._draw_tool.active:
            pos       = self.mapToScene(event.position().toPoint())
            mods      = event.modifiers()
            use_snap  = not (mods & Qt.KeyboardModifier.ControlModifier)
            constrain = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self._draw_tool.handle_dbl_click(pos, use_snap, constrain)
            event.accept()
        elif ((self._dim_tool and self._dim_tool.active)
                or (self._calib_tool and self._calib_tool.active)):
            # The press already placed a point; a double-click must not fall
            # through to select-mode node insertion on the curve underneath.
            event.accept()
        else:
            # Double-click on a CurveItem in select mode → insert node
            vp_pos    = event.position().toPoint()
            scene_pos = self.mapToScene(vp_pos)
            item = self._top_pick(vp_pos)
            # Selectable only: a curve on a locked (or hidden) layer took a
            # new node from a double-click, with an undo step and a star.
            if (isinstance(item, CurveItem) and self._rb_selectable(item)
                    and self._insert_node_callback):
                self._insert_node_callback(item.curve, scene_pos)
                event.accept()
                return
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        if self._coords_label is not None:
            self._coords_label.setText(self._fmt(scene_pos))
        else:
            self._status_bar.showMessage(self._fmt(scene_pos))
        if self._pan_active and not event.buttons() & self._pan_button:
            self._end_pan()              # its release went to another widget
        if self._pan_active:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
        elif self._calib_tool and self._calib_tool.active:
            self._calib_tool.handle_move(scene_pos, self.scene())
        elif self._dim_tool and self._dim_tool.active:
            mods     = event.modifiers()
            use_snap = not (mods & Qt.KeyboardModifier.ControlModifier)
            self._dim_tool.handle_move(scene_pos, use_snap)
        elif self._draw_tool and self._draw_tool.active:
            mods      = event.modifiers()
            use_snap  = not (mods & Qt.KeyboardModifier.ControlModifier)
            constrain = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self._draw_tool.handle_move(scene_pos, use_snap, constrain)
        elif (self._rb_origin is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            # Manual rubber-band selection in progress.
            cur = event.position().toPoint()
            if not self._rb_dragging:
                if (cur - self._rb_origin).manhattanLength() > 4:
                    self._rb_dragging = True
                    if self._rb_band is None:
                        self._rb_band = QRubberBand(
                            QRubberBand.Shape.Rectangle, self.viewport())
            if self._rb_dragging:
                self._rb_band.setGeometry(
                    QRect(self._rb_origin, cur).normalized())
                self._rb_band.show()
                event.accept()
        else:
            # Drag-to-move selected items
            if (self._drag_move_start is not None
                    and event.buttons() & Qt.MouseButton.LeftButton):
                if not self._drag_moving:
                    vp_start = self.mapFromScene(self._drag_move_start)
                    vp_cur   = event.position().toPoint()
                    dist = math.hypot(vp_cur.x() - vp_start.x(),
                                      vp_cur.y() - vp_start.y())
                    if dist > 4:
                        self._drag_moving = True
                if self._drag_moving:
                    if not self._drag_pre_called and self._move_pre_cb:
                        self._drag_pre_called = True
                        self._move_pre_cb()
                    prev = self._drag_move_start
                    self._drag_move_start = scene_pos
                    if self._move_cb:
                        self._move_cb(scene_pos.x() - prev.x(),
                                      scene_pos.y() - prev.y())
                    event.accept()
                    return
            super().mouseMoveEvent(event)

    def abandon_drag(self):
        """Drop a drag-to-move in progress without ending it: the curves it
        holds are gone (Undo or Redo rebuilt the document)."""
        self._drag_move_start = None
        self._drag_moving     = False
        self._drag_pre_called = False
        self._drag_move_items = []

    def mouseReleaseEvent(self, event):
        if self._pan_active and event.button() == self._pan_button:
            self._end_pan()
            event.accept()
            return
        if event.button() in (Qt.MouseButton.MiddleButton,
                              Qt.MouseButton.RightButton):
            event.accept()
            return
        if (self._rb_origin is not None
                and event.button() == Qt.MouseButton.LeftButton):
            self._finish_rubber_band()
            event.accept()
            return
        was_moving = self._drag_moving
        self._drag_move_start = None
        self._drag_moving     = False
        self._drag_pre_called = False
        if was_moving and self._move_end_cb:
            self._move_end_cb()
        super().mouseReleaseEvent(event)
        # Never let a press-time capture leak into a later operation —
        # stale captures made gizmo/point moves act on the wrong curves.
        self._drag_move_items = []
        cb = getattr(self, "_face_moved_cb", None)
        if cb is not None and getattr(self, "_faces_at_press", None) is not None \
                and self._face_positions() != self._faces_at_press:
            cb()
        self._faces_at_press = None
        self.released.emit()

    @staticmethod
    def _rb_selectable(it) -> bool:
        if not isinstance(it, (CurveItem, DimItem, TextItem)):
            return False
        return bool(it.flags() & it.GraphicsItemFlag.ItemIsSelectable)

    _PICK_PX = 4   # half-size of the pick box, screen px (zoom-independent)

    def _items_near(self, vp_pos) -> list:
        """Curves, dims and texts under a small screen-pixel box around the
        cursor, topmost first. A curve's own hit stroke is 2 mm, which is
        half a pixel at 25 % zoom; the box keeps a hairline clickable at any
        zoom without claiming the interior of closed shapes."""
        r = self._PICK_PX
        rect = QRect(vp_pos.x() - r, vp_pos.y() - r, 2 * r + 1, 2 * r + 1)
        return [it for it in self.items(rect)
                if isinstance(it, (CurveItem, DimItem, TextItem))]

    def _top_pick(self, vp_pos):
        """What a press at *vp_pos* is aimed at: interactive chrome exactly
        under the cursor (node/handle dots, gizmo arrows, a dim, an unlocked
        face photo) wins, then the topmost curve/text within the pick box,
        else None. Display-only items in between (the guides, the fills, the
        Ghost, the axis) are looked through: the stock and pad guides cover
        the face, and a photo under them could not be dragged."""
        for it in self.items(vp_pos):
            if isinstance(it, (CurveItem, TextItem)):
                break                     # curves are picked with tolerance below
            flags = it.flags()
            if isinstance(it, DimItem):
                # A curve in the pick box beats a dim the cursor only grazes:
                # a dim usually sits on what it measures, and a drag on the
                # selected curve moved the dim's offset instead.
                miss_px = (it.hit_distance(self.mapToScene(vp_pos))
                           * self.zoom())
                if miss_px > self._PICK_PX:
                    for near in self._items_near(vp_pos):
                        if isinstance(near, (CurveItem, TextItem)):
                            return near
                return it
            if (flags & it.GraphicsItemFlag.ItemIgnoresTransformations
                    or flags & it.GraphicsItemFlag.ItemIsMovable):
                # Screen-sized chrome (node/handle dots, gizmo arrows) or an
                # unlocked face photo: each runs its own press handling.
                return it
        for it in self._items_near(vp_pos):
            if isinstance(it, (CurveItem, TextItem)):
                return it
        return None

    def _finish_rubber_band(self):
        """Resolve a manual rubber-band press: box-select on drag, click-select
        (single item, or clear on empty) on a plain click."""
        dragging   = self._rb_dragging
        band       = self._rb_band
        press_item = self._rb_press_item
        self._rb_origin     = None
        self._rb_press_item = None
        self._rb_dragging   = False
        sc = self.scene()
        if dragging and band is not None:
            rect = band.geometry()
            band.hide()
            picked = [it for it in self.items(rect) if self._rb_selectable(it)]
            sc.select_items(picked)
            n = len(picked)
            self._status_bar.showMessage(
                f"Box selected {n} item{'s' if n != 1 else ''}")
        else:
            if band is not None:
                band.hide()
            # Plain click: select the pressed curve, or clear if empty.
            sc.clearSelection()
            if press_item is not None and self._rb_selectable(press_item):
                press_item.setSelected(True)

    def keyPressEvent(self, event):
        key = event.key()

        if (key == Qt.Key.Key_Space and not event.isAutoRepeat()
                and not event.modifiers()):
            # Space held: the left button pans, as in most drawing apps.
            self._space_held = True
            if not self._pan_active:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return

        # Delete / Backspace: remove selected curves (select mode only)
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            tool_busy = ((self._draw_tool and self._draw_tool.active)
                         or (self._dim_tool and self._dim_tool.active)
                         or (self._calib_tool and self._calib_tool.active))
            if not tool_busy:
                if self._delete_callback:
                    self._delete_callback()
                event.accept()
                return

        if key == Qt.Key.Key_Escape:
            if self._calib_tool and self._calib_tool.active:
                self._calib_tool.cancel(self.scene())
                event.accept()
                return
            if self._dim_tool and self._dim_tool.active:
                self._dim_tool.handle_key(key)
                event.accept()
                return
            if self._draw_tool and self._draw_tool.active:
                self._draw_tool.handle_key(key, event.text())
                event.accept()
                return
            if self._escape_cb:
                self._escape_cb()
                event.accept()
                return
        elif self._dim_tool and self._dim_tool.active:
            if self._dim_tool.handle_key(key):
                event.accept()
                return
        elif self._draw_tool and self._draw_tool.active:
            if self._draw_tool.handle_key(key, event.text()):
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            if not self._pan_active:
                self.unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        # A Space released over another window never reaches us.
        self._space_held = False
        if not self._pan_active:
            self.unsetCursor()
        super().focusOutEvent(event)

    def _fmt(self, p: QPointF) -> str:
        # y up, as the Holes fields, the DXF and GuildModel have it: the scene
        # is y-down, and the readout said 27.75 mm below the origin.
        return f"x: {p.x():.2f} mm  y: {-p.y():.2f} mm"


class WorkspaceState:
    """All per-workspace runtime state: document, canvas, tools, and guides.

    One instance exists per workspace tab (front / temple / component).
    MainWindow holds a list[WorkspaceState] and exposes the active one via
    proxy properties so existing methods need no rewriting.
    """

    def __init__(self, workspace_type: str, status_bar, parent_win):
        self.workspace_type = workspace_type
        # Active drawing layer (what new curves are created on); driven by
        # the Layers panel in the Properties tab.
        self.active_layer: Layer = WORKSPACE_LAYERS[workspace_type][0]

        # ── Document state ────────────────────────────────────────────────
        self.doc_curves: list = []
        self.doc_dims:   list = []
        self.doc_texts:  list = []   # TextObject (ENGRAVING, M8)
        self.bookmarks:  list = []
        self.undo_stack: list = []
        self.redo_stack: list = []
        self.image_px_per_mm: float | None = None

        # ── Canvas ────────────────────────────────────────────────────────
        self.scene = FrameScene()
        self.scene.init_mirror(horizontal=(workspace_type in ("temple_r", "temple_l")))
        self.snap  = SnapEngine(self.scene)
        # Register the LIVE curve list once — in-place mutation keeps it
        # current forever. Previously only draw tools called set_doc_curves
        # on activation, so Point Move had zero snap targets until a draw
        # tool had been used in the workspace (the "can't place an imported
        # hinge point-to-point" bug).
        self.snap.set_doc_curves(self.doc_curves)
        self.view  = CanvasView(self.scene, status_bar)

        # ── Tools ─────────────────────────────────────────────────────────
        self.calib_tool  = CalibTool(parent_win)
        self.draw_tool   = DrawTool(parent_win)
        self.circle_tool = CircleTool(parent_win)
        self.edit_tool   = EditTool(self.scene, parent_win)
        self.dim_tool    = DimTool(parent_win)
        self.trim_tool   = TrimTool(parent_win)
        self.fillet_tool = FilletTool(parent_win)
        self.split_tool  = SplitTool(parent_win)
        self.offset_tool     = OffsetTool(parent_win)
        self.rebuild_tool    = RebuildSplineTool(parent_win)
        self.point_move_tool = PointMoveTool(parent_win)
        self.text_tool       = TextTool(parent_win)

        # ── Guides ────────────────────────────────────────────────────────
        self.const_guides = ConstructionGuides(self.scene)
        self.boxing_guide = BoxingGuide(self.scene)
        # Locked boxing derives its boxes from this workspace's live LENS curves.
        self.boxing_guide.set_lens_provider(
            lambda: [c for c in self.doc_curves if c.layer == Layer.LENS])
        self.stock_guide  = RectGuide(self.scene, "guide.stock")
        self.pad_guide    = RectGuide(self.scene, "guide.pad",
                                      width_mm=45.0, height_mm=45.0)

        # ── Move gizmo state ──────────────────────────────────────────────
        self.move_gizmo             = None
        self.move_gizmo_center      = QPointF(0, 0)
        self.drag_moving_curves:list = []
        self.drag_moving_dims:  list = []
        self.drag_moving_texts: list = []

        # ── Sidebar state saved/restored on tab switch ────────────────────
        _CG = ConstructionGuides
        self.mirror_enabled: bool  = True
        self.snap_enabled:   bool  = True
        self.smooth_handles: bool  = True
        self.guides_visible: bool  = True
        self.boxing_visible: bool  = False
        self.stock_visible:  bool  = False
        self.pad_visible:    bool  = False
        self.bridge_angle:   float = _CG.DEFAULT_BRIDGE_ANGLE_DEG
        self.apical_radius:  float = _CG.DEFAULT_APICAL_RADIUS_MM
        self.crest_height:   float = 0.0
        self.arm_spread:     float = 4.0
        self.arm_drop:       float = 0.0
        self.boxing_a:       float = 52.0
        self.boxing_b:       float = 30.0
        self.boxing_dbl:     float = 18.0
        self.boxing_snapped: bool  = False       # boxing guide snapped to lens (M11/M12)
        # Boxing visibility to restore when the snap is switched back off.
        # Snapping force-shows the guide (the bevel outline rides on it); a
        # maker who had it hidden should get it hidden back, not a default-sized
        # box parked over their drawing. None = nothing to restore.
        self.boxing_visible_pre_snap: bool | None = None
        self.shape_locked:   bool  = False       # lens spline frozen; resize via A/B (M12)
        self.boxing_chain:   bool  = False       # A/B resize proportionally (M12)
        self.outline_locked: bool  = False       # OUTLINE co-resizes with the lens (M12)
        self.bevel_preset:   str   = "acetate"   # flat|horn_metal|acetate|custom
        self.bevel_depth:    float = BEVEL_PRESETS["acetate"]
        self.stock_w:        float = 170.0
        self.stock_h:        float = 85.0
        self.pad_w:          float = 45.0
        self.pad_h:          float = 45.0
        self.fill_visible:   bool  = False        # frame fill overlay (M8)
        self.fill_color:     str   = "#2a6099"
        self.fill_opacity:   float = 0.50
        self.fill_style:     str   = "color"      # "color" | "image" (v1.2)
        self.fill_image:     str   = ""           # material swatch, kept even
                                                  # while the color is showing
        self.lens_fill_visible: bool  = False     # lens tint overlay (v1.2)
        self.lens_fill_top:     str   = DEFAULT_LENS_FILL_TOP
        self.lens_fill_bottom:  str   = DEFAULT_LENS_FILL_BOTTOM
        self.lens_fill_linked:  bool  = False     # both stops held equal (flat tint)
        self.lens_fill_opacity: float = DEFAULT_LENS_FILL_OPACITY
        self.lens_fill_intensity: float = DEFAULT_LENS_FILL_INTENSITY
        # Inlay fill overlay (2.0): the front's and each temple's own.
        self.inlay_fill_visible: bool  = False
        self.inlay_fill_color:   str   = DEFAULT_INLAY_FILL_COLOR
        self.inlay_fill_opacity: float = DEFAULT_INLAY_FILL_OPACITY
        self.inlay_fill_style:   str   = "color"   # "color" | "image"
        self.inlay_fill_image:   str   = ""        # kept while the color shows
        self.inlay_fill_tumble:  bool  = False     # turn each body's copy
        self.obverse:        bool  = False       # View Obverse: the view only
        # The Canvas tab's selected row: a shown photo's scene index, or past
        # them one of unshown_faces.
        self.selected_face_idx: int       = -1
        # Photos the file names that were not shown (not on this computer,
        # too large, damaged, past the cap): kept so the next save carries
        # them, and listed after the shown ones for Locate… or Remove.
        # Unshown, they were dropped from it.
        self.unshown_faces:     list      = []
        self.fitted:            bool      = False   # True once fitInView has been called

        # Wire endpoint drag-snap using the workspace's own mutable list and view.
        # snap_enabled_fn is set by MainWindow after the toolbar is built.
        self.edit_tool.set_endpoint_snap_context(self.doc_curves, self.view)
        # 'Lock lens shape' freezes LENS spline editing (still selectable/movable).
        self.edit_tool.set_node_edit_blocked_fn(
            lambda c: self.shape_locked and c.layer == Layer.LENS)

    # ------------------------------------------------------------------
    # Document mutation primitives
    #
    # Single source of truth for the snapshot shape and for keeping
    # doc_curves/doc_dims in sync with the scene. MainWindow and any
    # cross-workspace operation (Temple Copy, file load) must go through
    # these — hand-rolled list+scene updates are how the Mirror Copy
    # undo-corruption bug happened.
    # ------------------------------------------------------------------

    MAX_UNDO = 100

    # Set by MainWindow; called after any curve/dim add/remove/clear so the
    # Layers panel (and any future observer) can refresh.
    on_document_changed = None
    on_mirror_restored = None     # fn(bool): an undo step brought a Ghost state back

    def _notify(self):
        if self.on_document_changed:
            self.on_document_changed()

    def take_snapshot(self) -> dict:
        return {
            "curves": copy.deepcopy(self.doc_curves),
            "dims":   copy.deepcopy(self.doc_dims),
            "texts":  copy.deepcopy(self.doc_texts),
        }

    def push_undo_snapshot(self):
        """Push current state; wipes the redo future. Call BEFORE mutating."""
        self.push_undo_state(self.take_snapshot())

    def push_undo_state(self, snapshot: dict):
        """Push a previously-taken snapshot; wipes the redo future.

        For operations that may turn out to be no-ops: take the snapshot,
        attempt the mutation, and push only on success — pushing eagerly and
        popping on failure would still have destroyed the redo stack."""
        self.undo_stack.append(snapshot)
        self.redo_stack.clear()
        if len(self.undo_stack) > self.MAX_UNDO:
            self.undo_stack.pop(0)

    @property
    def face_image_paths(self) -> list[str]:
        """The shown photos' files, in the scene's order."""
        return [self.scene.face_path(i) for i in range(self.scene.face_count())]

    def add_curve(self, curve):
        """Append to the document and the scene; returns the CurveItem."""
        self.doc_curves.append(curve)
        item = self.scene.add_curve(curve)
        self._notify()
        return item

    @staticmethod
    def _remove_identity(lst: list, obj) -> None:
        # Curves/dims/texts are dataclasses, so ``in`` / ``list.remove`` compare
        # by VALUE: deleting one of two identical curves (a double paste, a
        # duplicate DXF entity) removed the other from the document while the
        # scene dropped this one — the survivor on screen was no longer saved.
        for i, x in enumerate(lst):
            if x is obj:
                del lst[i]
                return

    def remove_curve(self, curve):
        self._remove_identity(self.doc_curves, curve)
        self.scene.remove_curve(curve)
        self._notify()

    def add_dim(self, dim):
        self.doc_dims.append(dim)
        item = self.scene.add_dim(dim)
        self._notify()
        return item

    def remove_dim(self, dim):
        self._remove_identity(self.doc_dims, dim)
        self.scene.remove_dim(dim)
        self._notify()

    def add_text(self, text_obj):
        self.doc_texts.append(text_obj)
        item = self.scene.add_text(text_obj)
        self._notify()
        return item

    def remove_text(self, text_obj):
        self._remove_identity(self.doc_texts, text_obj)
        self.scene.remove_text(text_obj)
        self._notify()

    def clear_geometry(self):
        """Remove every curve, dim, and text. Undo stacks are left untouched."""
        self.edit_tool.clear()
        self.scene.clearSelection()
        for c in list(self.doc_curves):
            self.scene.remove_curve(c)
        self.doc_curves.clear()
        for d in list(self.doc_dims):
            self.scene.remove_dim(d)
        self.doc_dims.clear()
        for t in list(self.doc_texts):
            self.scene.remove_text(t)
        self.doc_texts.clear()
        self._notify()

    def clear_document(self):
        """Clear geometry AND history — File > New / file load.
        Layer visibility/locks reset to defaults with the document."""
        self.clear_geometry()
        self.scene.reset_layer_states()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.reset_session_state()

    def reset_session_state(self):
        """Per-document session state that is NOT in the file and must not
        leak from the previous document into the next: the boxing snap and
        the lens/outline locks derive from geometry that is gone, the bevel,
        forming and photo-calibration values are stored in the file (or
        default), and the active layer starts over. Called by clear_document,
        so File > New and every file load share it. The calibration leaked:
        a file with none was saved with the previous one's scale."""
        self.image_px_per_mm = None
        self.boxing_snapped = False
        self.shape_locked   = False
        self.outline_locked = False
        self.boxing_chain   = False
        self.boxing_visible_pre_snap = None
        self.boxing_guide.set_locked(False)
        self.bevel_preset = "acetate"
        self.bevel_depth  = BEVEL_PRESETS["acetate"]
        self.bridge_angle  = ConstructionGuides.DEFAULT_BRIDGE_ANGLE_DEG
        self.apical_radius = ConstructionGuides.DEFAULT_APICAL_RADIUS_MM
        self.active_layer  = WORKSPACE_LAYERS[self.workspace_type][0]

    def restore_snapshot(self, snapshot: dict):
        self.clear_geometry()
        for c in snapshot["curves"]:
            self.add_curve(c)
        for d in snapshot["dims"]:
            self.add_dim(d)
        for t in snapshot.get("texts", []):   # absent in pre-M8 bookmarks
            self.add_text(t)

    # A snapshot may carry "mirror": the Ghost state that belongs with it.
    # Mirror (bake) switches Ghost off as part of the operation, and only the
    # geometry came back on Undo — the design showed half a frame until Ghost
    # was switched on by hand. The step's counterpart on the other stack
    # records the state being left, so Redo switches it off again.

    def _step_across(self, source: list, target: list) -> None:
        snapshot = source.pop()
        current = self.take_snapshot()
        if "mirror" in snapshot:
            current["mirror"] = bool(getattr(self, "mirror_enabled", False))
        target.append(current)
        self.restore_snapshot(snapshot)
        if "mirror" in snapshot and self.on_mirror_restored:
            self.on_mirror_restored(bool(snapshot["mirror"]))

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self._step_across(self.undo_stack, self.redo_stack)
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self._step_across(self.redo_stack, self.undo_stack)
        return True


def _run_modal(dlg) -> int:
    """exec() a dialog built for one use, then let it go. Parented to the
    window and never deleted, every Preferences, Transform or Edit Text left a
    live dialog behind, and each stylesheet pass re-polished them all (four
    Preferences opens took an apply from 0.5 s to 1.4 s). deleteLater waits
    for this handler to return, so the dialog's values stay readable here."""
    result = dlg.exec()
    dlg.deleteLater()
    return result


class _WheelGuard(QObject):
    """Installed on the spin boxes, combos and sliders of a scrolling panel:
    the wheel changes one only once it has focus, and otherwise scrolls the
    panel. Scrolling the Guides tab with the pointer over A (width) resized a
    locked lens and pushed an undo step per notch; over Frontal angle it
    changed the saved design."""

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore()          # unaccepted, it goes on to the scroll area
            return True
        return False

    def guard(self, root: QWidget) -> None:
        from PySide6.QtWidgets import QAbstractSlider, QAbstractSpinBox, QScrollBar
        for w in root.findChildren(QWidget):
            # Never a scroll bar (a QAbstractSlider too): a scroll area hands
            # it the wheel by sendEvent, which does not propagate, so guarding
            # one stopped every panel and list from scrolling at all.
            if isinstance(w, QScrollBar):
                continue
            if isinstance(w, (QAbstractSpinBox, QComboBox, QAbstractSlider)):
                # Wheel focus would hand the widget focus on the first notch.
                w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                w.installEventFilter(self)


class KeyCaptureEdit(QLineEdit):
    """QLineEdit that records the next key press as a hotkey string instead of inserting text."""

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            event.accept()
            return
        from PySide6.QtGui import QKeySequence
        # keyCombination() carries modifiers+key as one value; int(modifiers())
        # raised TypeError on current PySide6 (flags enum isn't int()-able),
        # which broke hotkey recording with a console error per keypress.
        seq = QKeySequence(event.keyCombination())
        self.setText(seq.toString())
        event.accept()


class LayerTree(QTreeWidget):
    """Layer-panel tree with drag-and-drop reassignment.

    Object rows can be dragged onto a layer row (or among its children) to
    move those curves to that layer. Qt's default item relocation is
    suppressed: the drop is translated into a document edit via the
    curves_dropped signal and MainWindow rebuilds the panel afterwards.
    """

    curves_dropped   = Signal(list, object)   # ([id(curve), ...], Layer)
    delete_requested = Signal()               # Del/Backspace on object rows

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDropIndicatorShown(True)

    def has_object_rows_selected(self) -> bool:
        for it in self.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] in ("curve", "text"):
                return True
        return False

    def keyPressEvent(self, event):
        # Delete works from the panel too: the rows picked here are already
        # mirrored onto the canvas selection, so the same delete applies.
        # Focus sits in this tree after a row click, which is why the
        # canvas's own Delete handling never saw the key.
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.has_object_rows_selected():
                self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _drop_target_layer(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return None
        kind, payload = data
        if kind == "layer":
            return payload
        parent = item.parent()
        pdata = parent.data(0, Qt.ItemDataRole.UserRole) if parent else None
        return pdata[1] if pdata else None

    def dropEvent(self, event):
        layer = self._drop_target_layer(event.position().toPoint())
        curve_ids = []
        for it in self.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] in ("curve", "text"):
                curve_ids.append(data[1])
        # Never let the view move/delete rows itself; report IgnoreAction so
        # InternalMove's source-row cleanup is skipped, then apply the edit
        # after the drag machinery has fully unwound.
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if layer is not None and curve_ids:
            QTimer.singleShot(
                0, self, lambda: self.curves_dropped.emit(curve_ids, layer))


class ComponentTree(QTreeWidget):
    """The component library as folders of entries, with drag and drop.

    An entry dropped on a folder, or on an entry in one, moves into that
    folder; a folder dropped on another moves to just above it, or below it
    when dropped on the lower edge. As in LayerTree, Qt's own row moves are
    suppressed: the drop is reported by a signal and MainWindow rebuilds the
    tree from the library on disk."""

    entry_dropped     = Signal(str, object)   # (entry path, folder or None)
    folders_reordered = Signal(list)          # the folders' new order

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDropIndicatorShown(True)

    @staticmethod
    def item_data(item):
        """``("folder", name)`` or ``("entry", path)``, or None."""
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def folder_names(self) -> list[str]:
        out = []
        for i in range(self.topLevelItemCount()):
            data = self.item_data(self.topLevelItem(i))
            if data and data[0] == "folder":
                out.append(data[1])
        return out

    def _folder_of(self, item):
        """The folder *item* is or sits in; None outside any."""
        data = self.item_data(item)
        if data and data[0] == "folder":
            return data[1]
        parent = item.parent() if item is not None else None
        pdata = self.item_data(parent)
        return pdata[1] if pdata and pdata[0] == "folder" else None

    def dropEvent(self, event):
        moved = self.item_data(self.currentItem())
        target = self.itemAt(event.position().toPoint())
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if not moved or target is None:
            return
        folder = self._folder_of(target)
        if moved[0] == "entry":
            path = moved[1]
            QTimer.singleShot(0, self, lambda: self.entry_dropped.emit(path, folder))
            return
        if folder is None or folder == moved[1]:
            return
        order = [n for n in self.folder_names() if n != moved[1]]
        below = (self.dropIndicatorPosition()
                 == QAbstractItemView.DropIndicatorPosition.BelowItem
                 or self.item_data(target)[0] == "entry")
        order.insert(order.index(folder) + (1 if below else 0), moved[1])
        QTimer.singleShot(0, self, lambda: self.folders_reordered.emit(order))


def _available_screen(widget):
    """The usable area of the screen `widget` (or its parent) will show on —
    what a pop-up's size is bounded by. Falls back to the primary screen, and
    to a plain rectangle when there is no screen at all (a headless import).
    GuildModel's, shared."""
    from PySide6.QtCore import QRect
    parent = widget.parentWidget() if widget is not None else None
    screen = None
    try:
        screen = ((parent.screen() if parent is not None else None)
                  or QApplication.primaryScreen())
    except Exception:
        screen = None
    return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)


class SettingsDialog(QDialog):
    """Application-wide preferences: General / Appearance / Layers / Toolbar /
    Hotkeys / Print & PDF.

    Laid out as GuildModel's PrefsDialog is: every tab scrolls, so no tab
    dictates the dialog's size; it opens at its content's size within the
    screen, or at the size the maker last left it (`prefs_dialog_size`); the
    guidance under a group is a short hint, and the rest is in tooltips."""

    def __init__(self, prefs: dict, parent=None, images_in_use=None):
        """*images_in_use*: the image files the open design shows, which
        Clear Image Cache keeps."""
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        # Narrower, four pages took horizontal scroll bars and the Print & PDF
        # tab needed the tab bar's arrows.
        self.setMinimumWidth(520)
        # Bounded by the screen: on a short panel with the OS scale up a fixed
        # floor would put the OK row under the screen's edge.
        self.setMinimumHeight(min(480, _available_screen(self).height()))
        self.setSizeGripEnabled(True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        tabs = QTabWidget()
        self._tabs = tabs
        root_layout.addWidget(tabs)

        # ── OK / Cancel buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 8, 16, 16)
        self._ok_btn   = QPushButton("OK")
        cancel_btn     = QPushButton("Cancel")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(cancel_btn)
        root_layout.addLayout(btn_row)

        # ── Helpers ───────────────────────────────────────────────────────
        def _spinbox(lo, hi, step, val, suffix=" mm", decimals=1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            s.setSuffix(suffix)
            s.setValue(val)
            return s

        def _page(title: str, spacing: int = 12) -> QVBoxLayout:
            inner = QWidget()
            lay = QVBoxLayout(inner)
            lay.setSpacing(spacing)
            lay.setContentsMargins(16, 16, 16, 12)
            tabs.addTab(self._scrolled(inner), title)
            return lay

        # ═══════════════════════════════════════════════════════════════════
        # General
        # ═══════════════════════════════════════════════════════════════════
        gen_lay = _page("General")

        draw_box  = QGroupBox("Drawing")
        draw_form = QFormLayout(draw_box)
        self._weight_spin = _spinbox(0.25, 10.0, 0.25, prefs["default_line_weight"],
                                     suffix=" px", decimals=2)
        self._weight_spin.setToolTip("Line weight of a new curve, in screen pixels.")
        draw_form.addRow("Default line weight:", self._weight_spin)
        gen_lay.addWidget(draw_box)

        # Two columns: the drawing aids, then the Frame Front's guides.
        start_box  = QGroupBox("On for New Designs")
        start_grid = QGridLayout(start_box)
        start_grid.setHorizontalSpacing(24)
        self._mirror_chk = QCheckBox("Ghost axis")
        self._snap_chk   = QCheckBox("Snap")
        self._smooth_chk = QCheckBox("Smooth handles")
        self._guides_chk = QCheckBox("Construction guides")
        self._boxing_chk = QCheckBox("Boxing guide")
        self._stock_chk  = QCheckBox("Stock guide")
        self._pad_chk    = QCheckBox("Pad guide")
        for chk, key in ((self._mirror_chk, "mirror_on_startup"),
                         (self._snap_chk,   "snap_on_startup"),
                         (self._smooth_chk, "smooth_handles"),
                         (self._guides_chk, "guides_on_startup"),
                         (self._boxing_chk, "boxing_on_startup"),
                         (self._stock_chk,  "stock_on_startup"),
                         (self._pad_chk,    "pad_on_startup")):
            chk.setChecked(prefs[key])
        for chk in (self._guides_chk, self._boxing_chk, self._stock_chk,
                    self._pad_chk):
            chk.setToolTip("Frame Front only. The temples start with their "
                           "stock guide shown and the others hidden.")
        for row, chk in enumerate((self._mirror_chk, self._snap_chk,
                                   self._smooth_chk)):
            start_grid.addWidget(chk, row, 0)
        for row, chk in enumerate((self._guides_chk, self._boxing_chk,
                                   self._stock_chk, self._pad_chk)):
            start_grid.addWidget(chk, row, 1)
        start_grid.setColumnStretch(2, 1)
        gen_lay.addWidget(start_box)

        # The guide sizes, one row per guide (width × height): the Frame
        # Front's, and the temple blank shared by both temple tabs.
        size_box  = QGroupBox("Guide Sizes for New Designs")
        size_grid = QGridLayout(size_box)
        size_grid.setHorizontalSpacing(6)
        self._box_a   = _spinbox(30.0, 80.0,  0.5, prefs["boxing_a_mm"])
        self._box_b   = _spinbox(15.0, 60.0,  0.5, prefs["boxing_b_mm"])
        self._box_dbl = _spinbox(8.0,  40.0,  0.5, prefs["boxing_dbl_mm"])
        self._stock_w = _spinbox(50.0, 400.0, 1.0, prefs["stock_width_mm"])
        self._stock_h = _spinbox(20.0, 200.0, 1.0, prefs["stock_height_mm"])
        self._pad_w   = _spinbox(10.0, 200.0, 0.5, prefs["pad_width_mm"])
        self._pad_h   = _spinbox(10.0, 200.0, 0.5, prefs["pad_height_mm"])
        self._temple_stock_w = _spinbox(50.0, 400.0, 1.0,
                                        prefs["temple_stock_width_mm"])
        self._temple_stock_h = _spinbox(10.0, 200.0, 1.0,
                                        prefs["temple_stock_height_mm"])
        boxing_tip = ("The dashed lens boxes: A is a box's width, B its height, "
                      "and DBL the distance between the two boxes.")
        for row, (label, first, second, tip) in enumerate((
                ("Boxing A × B:", self._box_a, self._box_b, boxing_tip),
                ("DBL:", self._box_dbl, None, boxing_tip),
                ("Stock blank:", self._stock_w, self._stock_h,
                 "The green dashed rectangle, centered at the origin: the "
                 "blank the front is cut from (width × height)."),
                ("Pad block:", self._pad_w, self._pad_h,
                 "The purple dashed rectangle, centered at the origin "
                 "(width × height)."),
                ("Temple blank:", self._temple_stock_w, self._temple_stock_h,
                 "The green dashed rectangle on both temple tabs: the blank "
                 "a temple is cut from (length × width), with the core line "
                 "along its middle. GuildModel's default temple blank is "
                 "170 × 30 mm."))):
            lbl = QLabel(label)
            size_grid.addWidget(lbl, row, 0)
            size_grid.addWidget(first, row, 1)
            if second is not None:
                size_grid.addWidget(QLabel("×"), row, 2)
                size_grid.addWidget(second, row, 3)
            for w in (lbl, first, second):
                if w is not None:
                    w.setToolTip(tip)
        size_grid.setColumnStretch(1, 1)
        size_grid.setColumnStretch(3, 1)
        gen_lay.addWidget(size_box)

        lens_box  = QGroupBox("Lens Fill")
        lens_form = QFormLayout(lens_box)
        self._lens_opacity_spin = _spinbox(
            0, 100, 5, prefs.get("lens_fill_opacity_pct", 65),
            suffix=" %", decimals=0)
        self._lens_opacity_spin.setToolTip(
            "The opacity a lens tint starts at. The tint colors themselves "
            "are saved with each design.")
        lens_form.addRow("Default opacity:", self._lens_opacity_spin)
        self._lens_intensity_spin = _spinbox(
            0.5, 8.0, 0.25, prefs.get("lens_fill_intensity", 1.0),
            suffix=" ×", decimals=2)
        self._lens_intensity_spin.setToolTip(
            "The tint depth a lens fill starts at. 1.00 shows a color as "
            "picked; higher deepens it, as a longer dye time would.")
        lens_form.addRow("Default intensity:", self._lens_intensity_spin)
        gen_lay.addWidget(lens_box)

        inlay_box  = QGroupBox("Inlay Fill")
        inlay_form = QFormLayout(inlay_box)
        self._inlay_default_color = _hex_or(prefs.get("inlay_fill_color"),
                                            DEFAULT_INLAY_FILL_COLOR)
        self._inlay_color_btn = QPushButton("Color…")
        self._inlay_color_btn.setToolTip(
            "The color an inlay fill starts at. Each design keeps its own "
            "fill, image and tumble.")
        self._inlay_color_btn.clicked.connect(self._pick_inlay_default_color)
        self._update_inlay_default_swatch()
        inlay_form.addRow("Default color:", self._inlay_color_btn)
        self._inlay_opacity_spin = _spinbox(
            0, 100, 5, prefs.get("inlay_fill_opacity_pct", 85),
            suffix=" %", decimals=0)
        self._inlay_opacity_spin.setToolTip(
            "The opacity an inlay fill starts at.")
        inlay_form.addRow("Default opacity:", self._inlay_opacity_spin)
        gen_lay.addWidget(inlay_box)

        # The questions GuildDraw asks with a "Don't ask again" on the box
        # itself; this is where a silenced one is turned back on (as
        # GuildModel's Prompts group).
        prompt_box = QGroupBox("Prompts")
        prompt_form = QFormLayout(prompt_box)
        self._prompt_store_chk = QCheckBox(
            "Explain storing a reference image in the design")
        self._prompt_store_chk.setChecked(bool(prefs.get("prompt_store_image", True)))
        self._prompt_store_chk.setToolTip(
            "Asked when the paperclip on the Canvas tab stores an image: the "
            "design file then carries it to every computer that opens it.")
        prompt_form.addRow(self._prompt_store_chk)
        gen_lay.addWidget(prompt_box)

        # The copies of stored images unpacked from opened designs. Cleared
        # here at once, not on OK: it is a deletion, with its own question.
        cache_box = QGroupBox("Image Cache")
        cache_lay = QVBoxLayout(cache_box)
        self._images_in_use = images_in_use or (lambda: ())
        self._cache_size_lbl = QLabel()
        self._cache_size_lbl.setWordWrap(True)
        cache_lay.addWidget(self._cache_size_lbl)
        clear_row = QHBoxLayout()
        self._clear_cache_btn = QPushButton("Clear Image Cache…")
        self._clear_cache_btn.setToolTip(
            "Delete the copies GuildDraw unpacked of the images stored in the "
            "designs you opened. Each design still holds its images and "
            "unpacks them again when opened; the open design's are kept.")
        self._clear_cache_btn.clicked.connect(lambda: self._clear_image_cache())
        clear_row.addWidget(self._clear_cache_btn)
        clear_row.addStretch()
        cache_lay.addLayout(clear_row)
        cache_lay.addWidget(self._hint(
            "Stored images are unpacked here when a design opens."))
        self._show_cache_size()
        gen_lay.addWidget(cache_box)

        gen_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Appearance (mode / viewport / editing dots / grid)
        # ═══════════════════════════════════════════════════════════════════
        ap_lay = _page("Appearance")

        mode_box  = QGroupBox("Mode")
        mode_form = QFormLayout(mode_box)
        self._dark_check = QCheckBox("Dark mode")
        self._dark_check.setChecked(prefs["dark_mode"])
        mode_form.addRow(self._dark_check)
        self._compact_check = QCheckBox("Compact toolbar")
        self._compact_check.setChecked(prefs.get("compact_toolbar", False))
        self._compact_check.setToolTip(
            "Less padding and slightly smaller icons on the toolbar, for "
            "more drawing room.")
        mode_form.addRow(self._compact_check)
        ap_lay.addWidget(mode_box)

        vp = prefs.get("viewport") or {}
        vp_box  = QGroupBox("Viewport")
        vp_form = QFormLayout(vp_box)

        # (key, label) — a preset overlays the canvas tokens in BOTH UI modes;
        # "auto" follows the UI theme as before.
        self._vp_choices = [
            ("auto",      "Follow UI theme"),
            ("parchment", "Parchment"),
            ("dimmed",    "Dimmed"),
            ("blueprint", "Blueprint"),
            ("matte",     "Matte Dark"),
            ("white",     "Plain White"),
            ("custom",    "Custom"),
        ]
        self._vp_combo = QComboBox()
        for _key, label in self._vp_choices:
            self._vp_combo.addItem(label)
        cur_preset = vp.get("preset", "auto")
        self._vp_combo.setCurrentIndex(next(
            (i for i, (k, _l) in enumerate(self._vp_choices) if k == cur_preset),
            0))
        self._vp_combo.setToolTip(
            "The canvas backdrop and drawing ink, independent of the UI mode. "
            "Follow UI theme is Parchment in light mode and Matte Dark in "
            "dark mode.")
        self._vp_combo.currentIndexChanged.connect(self._on_vp_preset_changed)

        # The custom color sits beside the preset it belongs to.
        self._vp_custom_color = vp.get("custom_bg", "#faf6ee")
        self._vp_color_btn = QPushButton("Color…")
        self._vp_color_btn.setToolTip(
            "The canvas color for the Custom preset; the drawing ink is "
            "derived from it.")
        self._vp_color_btn.clicked.connect(self._pick_vp_color)
        self._vp_color_btn.setEnabled(cur_preset == "custom")
        self._update_vp_swatch()
        canvas_row = QWidget()
        cr_lay = QHBoxLayout(canvas_row)
        cr_lay.setContentsMargins(0, 0, 0, 0)
        cr_lay.setSpacing(6)
        cr_lay.addWidget(self._vp_combo, 1)
        cr_lay.addWidget(self._vp_color_btn)
        vp_form.addRow("Canvas:", canvas_row)

        vig_row = QWidget()
        vig_lay = QHBoxLayout(vig_row)
        vig_lay.setContentsMargins(0, 0, 0, 0)
        vig_lay.setSpacing(8)
        self._vignette_slider = QSlider(Qt.Orientation.Horizontal)
        self._vignette_slider.setRange(0, 100)
        self._vignette_slider.setValue(int(vp.get("vignette", 0)))
        self._vignette_slider.setToolTip(
            "Darkens the edges of the canvas to focus the eye. Display only; "
            "never printed or exported.")
        self._vignette_lbl = QLabel(f"{self._vignette_slider.value()}%")
        self._vignette_lbl.setMinimumWidth(
            self._vignette_lbl.fontMetrics().horizontalAdvance("100%"))
        self._vignette_lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                                        | Qt.AlignmentFlag.AlignVCenter)
        self._vignette_slider.valueChanged.connect(
            lambda v: self._vignette_lbl.setText(f"{v}%"))
        vig_lay.addWidget(self._vignette_slider, 1)
        vig_lay.addWidget(self._vignette_lbl)
        vp_form.addRow("Vignette:", vig_row)
        ap_lay.addWidget(vp_box)

        dots_box  = QGroupBox("Editing Dots")
        dots_form = QFormLayout(dots_box)
        self._dot_spin = _spinbox(2, 10, 1, float(prefs.get("dot_radius_px", 4)),
                                  suffix=" px", decimals=0)
        self._dot_spin.setToolTip(
            "Radius of the node dots on a selected curve; handles draw one "
            "pixel smaller. Larger helps on a high-DPI display.")
        dots_form.addRow("Node dot radius:", self._dot_spin)
        ap_lay.addWidget(dots_box)

        grid_box  = QGroupBox("Grid")
        grid_form = QFormLayout(grid_box)
        self._grid_spacing_spin = _spinbox(
            0.5, 100.0, 0.5, float(prefs.get("grid_spacing_mm", 2.0)),
            suffix=" mm", decimals=1)
        self._grid_spacing_spin.setToolTip(
            "The distance between grid lines. The Grid button shows the grid; "
            "the Grid snap in the snap palette snaps to its intersections.")
        grid_form.addRow("Spacing:", self._grid_spacing_spin)
        from PySide6.QtWidgets import QSpinBox as _QSpinBox
        self._grid_major_spin = _QSpinBox()
        self._grid_major_spin.setRange(1, 20)
        self._grid_major_spin.setSuffix(" lines")
        self._grid_major_spin.setValue(int(prefs.get("grid_major", 5)))
        self._grid_major_spin.setToolTip(
            "Every Nth line is drawn heavier. At 2 mm spacing, 5 puts a major "
            "line every 10 mm.")
        grid_form.addRow("Major line every:", self._grid_major_spin)

        self._grid_width_spin = _spinbox(
            0.5, 4.0, 0.5, float(prefs.get("grid_major_width_px", 1.0)),
            suffix=" px", decimals=1)
        self._grid_width_spin.setToolTip(
            "Line weight of the major grid lines, in screen pixels.")
        grid_form.addRow("Major line width:", self._grid_width_spin)

        # Grid line colors: "" = follow the theme tokens. Swatch buttons
        # mirror the custom canvas color above.
        self._grid_minor_color = str(prefs.get("grid_minor_color", "") or "")
        self._grid_major_color = str(prefs.get("grid_major_color", "") or "")
        self._grid_minor_btn = QPushButton("Minor…")
        self._grid_minor_btn.setToolTip("Color of the minor grid lines.")
        self._grid_minor_btn.clicked.connect(lambda: self._pick_grid_color("minor"))
        self._grid_major_btn = QPushButton("Major…")
        self._grid_major_btn.setToolTip("Color of the major grid lines.")
        self._grid_major_btn.clicked.connect(lambda: self._pick_grid_color("major"))
        grid_reset = QPushButton("Reset")
        grid_reset.setToolTip("Clear both grid colors; the grid follows the "
                              "theme again.")
        grid_reset.clicked.connect(self._reset_grid_colors)
        grid_colors_row = QWidget()
        gc_lay = QHBoxLayout(grid_colors_row)
        gc_lay.setContentsMargins(0, 0, 0, 0)
        gc_lay.setSpacing(6)
        gc_lay.addWidget(self._grid_minor_btn)
        gc_lay.addWidget(self._grid_major_btn)
        gc_lay.addWidget(grid_reset)
        gc_lay.addStretch()
        grid_form.addRow("Colors:", grid_colors_row)
        self._update_grid_swatches()
        ap_lay.addWidget(grid_box)

        ap_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Layers (per-layer light/dark color overrides)
        # ═══════════════════════════════════════════════════════════════════
        lc_lay = _page("Layers", spacing=10)
        lc_lay.addWidget(self._hint(
            "Each layer's drawing color in light and dark mode. Most layers "
            "use the shared ink until you pick a color; SCULPT, ENGRAVING "
            "and INLAY have their own."))

        # Only layer.* overrides are edited here; _collect_theme preserves
        # any other tokens already present in the prefs["theme"] dicts.
        base_theme = prefs.get("theme") or {}
        self._base_theme = {
            "light": dict(base_theme.get("light") or {}),
            "dark":  dict(base_theme.get("dark") or {}),
        }
        self._layer_over = {
            mode: {tok: v for tok, v in self._base_theme[mode].items()
                   if tok.startswith("layer.")}
            for mode in ("light", "dark")
        }

        lc_grid = QGridLayout()
        lc_grid.setHorizontalSpacing(8)
        lc_grid.setVerticalSpacing(6)
        for col, title in ((0, "Layer"), (1, "Light"), (2, "Dark")):
            hdr = QLabel(title)
            f = hdr.font()
            f.setBold(True)
            hdr.setFont(f)
            lc_grid.addWidget(hdr, 0, col)

        self._layer_btns: dict = {}   # (layer name, mode) -> QPushButton
        # The layers a tab can hold: BRIDGE is reserved for GuildModel's
        # bridge path and no tab offers it yet.
        _in_use = {layer for layers in WORKSPACE_LAYERS.values() for layer in layers}
        for row, layer in enumerate([lyr for lyr in Layer if lyr in _in_use], start=1):
            name = layer.value
            lc_grid.addWidget(QLabel(name), row, 0)
            for col, mode in ((1, "light"), (2, "dark")):
                btn = QPushButton()
                btn.setFixedWidth(96)
                btn.clicked.connect(
                    lambda _=False, n=name, m=mode: self._pick_layer_color(n, m))
                self._layer_btns[(name, mode)] = btn
                lc_grid.addWidget(btn, row, col)
            rst = QToolButton()
            rst.setText("↺")
            rst.setToolTip(f"Reset {name} to its default colors.")
            rst.clicked.connect(
                lambda _=False, n=name: self._reset_layer_color(n))
            lc_grid.addWidget(rst, row, 3)
            self._refresh_layer_btn(name)
        lc_grid.setColumnStretch(4, 1)
        lc_lay.addLayout(lc_grid)

        lc_reset_all = QPushButton("Reset All Layer Colors")
        lc_reset_all.clicked.connect(self._reset_all_layer_colors)
        lc_reset_row = QHBoxLayout()
        lc_reset_row.addWidget(lc_reset_all)
        lc_reset_row.addStretch()
        lc_lay.addLayout(lc_reset_row)
        lc_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Toolbar (button visibility), grouped as the toolbar is
        # ═══════════════════════════════════════════════════════════════════
        tb_lay = _page("Toolbar")
        tb_lay.addWidget(self._hint(
            "Uncheck a button to hide it. A hidden tool still answers its "
            "hotkey, and every button stays in the menus (View, and "
            "Edit ▸ Modify)."))

        toolbar_prefs = prefs.get("toolbar", {})
        self._tb_checks: dict[str, QCheckBox] = {}
        for section, entries in _TOOLBAR_SECTIONS:
            box  = QGroupBox(section)
            grid = QGridLayout(box)
            grid.setHorizontalSpacing(24)
            rows = (len(entries) + 1) // 2          # two columns, down then across
            for i, (key, label, hideable) in enumerate(entries):
                default_on = _prefs_mod.DEFAULTS["toolbar"].get(key, True)
                chk = QCheckBox(label)
                chk.setChecked(toolbar_prefs.get(key, default_on))
                if not hideable:
                    chk.setEnabled(False)
                    chk.setToolTip("Select is always shown.")
                elif key in _WS_ONLY_ACTIONS:
                    shown_on = _WS_ONLY_ACTIONS[key]
                    chk.setToolTip(
                        "Shown on the Frame Front only." if shown_on == ("front",)
                        else "Shown on the temples only." if "front" not in shown_on
                        else "Shown on the Frame Front and the temples.")
                self._tb_checks[key] = chk
                grid.addWidget(chk, i % rows, i // rows)
            grid.setColumnStretch(2, 1)
            tb_lay.addWidget(box)
        show_all = QPushButton("Show All Buttons")
        show_all.clicked.connect(
            lambda: [chk.setChecked(True) for chk in self._tb_checks.values()
                     if chk.isEnabled()])
        show_all_row = QHBoxLayout()
        show_all_row.addWidget(show_all)
        show_all_row.addStretch()
        tb_lay.addLayout(show_all_row)
        tb_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Hotkeys
        # ═══════════════════════════════════════════════════════════════════
        hk_lay = _page("Hotkeys", spacing=10)
        hk_lay.addWidget(self._hint(
            "Click a field, then press the key or combination. Esc clears "
            "the field; ↺ puts back the default."))

        # Up here, under the hint: below the list it was out of view, and OK
        # went gray with no reason in sight.
        self._conflict_label = QLabel()
        self._conflict_label.setWordWrap(True)
        # Dark red vanishes on the dark chrome — brighten it there.
        self._conflict_label.setStyleSheet(
            f"color: {'#ff6b6b' if theme.is_dark() else '#cc0000'};")
        self._conflict_label.hide()
        hk_lay.addWidget(self._conflict_label)

        hk_form = QFormLayout()
        hk_form.setSpacing(6)
        hk_lay.addLayout(hk_form)

        hotkey_prefs = prefs.get("hotkeys", {})
        self._key_edits: list[KeyCaptureEdit] = []
        self._hk_keys:   list[str]            = []
        defaults = _prefs_mod.DEFAULTS["hotkeys"]
        for key, label in _HOTKEY_ACTION_DEFS:
            edit = KeyCaptureEdit()
            edit.setPlaceholderText("none")
            edit.setMaximumWidth(140)
            edit.setText(hotkey_prefs.get(key, defaults.get(key, "")))
            edit.textChanged.connect(self._check_conflicts)
            self._key_edits.append(edit)
            self._hk_keys.append(key)
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            row_l.addWidget(edit)
            rst = QToolButton()
            rst.setText("↺")
            default = defaults.get(key, "")
            rst.setToolTip(f"Reset to the default ({default})" if default
                           else "Reset to the default (none)")
            rst.clicked.connect(lambda _=False, e=edit, d=default: e.setText(d))
            row_l.addWidget(rst)
            row_l.addStretch()
            hk_form.addRow(label + ":", row_w)

        hk_reset_all = QPushButton("Reset All Hotkeys")
        hk_reset_all.clicked.connect(
            lambda: [e.setText(defaults.get(k, ""))
                     for e, k in zip(self._key_edits, self._hk_keys, strict=True)])
        hk_reset_row = QHBoxLayout()
        hk_reset_row.addWidget(hk_reset_all)
        hk_reset_row.addStretch()
        hk_lay.addLayout(hk_reset_row)

        # Every shortcut a hotkey may not take, listed in full — the conflict
        # check refuses all of them, so all of them are shown.
        fixed_box  = QGroupBox("Fixed Shortcuts")
        fixed_grid = QGridLayout(fixed_box)
        fixed_grid.setHorizontalSpacing(10)
        fixed_grid.setVerticalSpacing(3)
        half = (len(_FIXED_SHORTCUTS) + 1) // 2
        for i, (name, keys) in enumerate(_FIXED_SHORTCUTS):
            row, col = i % half, (i // half) * 3
            fixed_grid.addWidget(QLabel(name), row, col)
            k = QLabel(" / ".join(keys))
            k.setObjectName("hintLabel")
            fixed_grid.addWidget(k, row, col + 1)
        fixed_grid.setColumnMinimumWidth(2, 12)
        fixed_grid.setColumnStretch(5, 1)
        hk_lay.addWidget(fixed_box)
        hk_lay.addStretch()

        # ═══════════════════════════════════════════════════════════════════
        # Print & PDF — one group per export, saying which it drives
        # ═══════════════════════════════════════════════════════════════════
        from .fontpicker import FontFilterCombo
        from .document import WORKSPACE_LAYERS as _WS_LAYERS
        from .export.template_print import PAPER_SIZES as _TP_PAPER

        pdf_lay = _page("Print && PDF")

        cat_cfg = {**_prefs_mod.DEFAULTS["catalog_pdf"],
                   **(prefs.get("catalog_pdf") or {})}
        tp_cfg = {**_prefs_mod.DEFAULTS["template_print"],
                  **(prefs.get("template_print") or {})}

        # Print Front + Temples / PDF Front + Temples
        tp_box  = QGroupBox("Front + Temples (1:1 Templates)")
        tp_box.setToolTip("File ▸ Print Front + Temples and "
                          "Export ▸ PDF Front + Temples.")
        tp_form = QFormLayout(tp_box)

        self._tp_paper = QComboBox()
        for _k, (_lbl, _w, _h) in _TP_PAPER.items():
            self._tp_paper.addItem(_lbl, _k)
        self._tp_paper.setCurrentIndex(
            max(0, self._tp_paper.findData(tp_cfg["paper"])))
        self._tp_paper.setToolTip(
            "The paper the pieces are laid out on, at true size. Pieces that "
            "don't fit spill onto further pages; the print dialog can still "
            "change the size.")
        tp_form.addRow("Paper size:", self._tp_paper)

        self._tp_orient = QComboBox()
        for _k, _lbl in (("auto", "Automatic (fewest pages)"),
                         ("portrait", "Portrait"), ("landscape", "Landscape")):
            self._tp_orient.addItem(_lbl, _k)
        self._tp_orient.setCurrentIndex(
            max(0, self._tp_orient.findData(tp_cfg["orientation"])))
        tp_form.addRow("Orientation:", self._tp_orient)

        self._tp_lw = _spinbox(0.1, 3.0, 0.05, float(tp_cfg["line_weight_mm"]),
                               decimals=2)
        self._tp_lw.setToolTip(
            "Stroke width on paper. A fine line (0.25–0.35 mm) is easiest to "
            "saw to; a heavier one reads better through tracing paper.")
        tp_form.addRow("Line weight:", self._tp_lw)

        self._tp_labels_chk = QCheckBox("Label each piece")
        self._tp_labels_chk.setToolTip(
            "Print Frame Front, Temple R and Temple L beside the pieces.")
        self._tp_labels_chk.setChecked(bool(tp_cfg["labels"]))
        tp_form.addRow(self._tp_labels_chk)
        tp_form.addRow(self._hint(
            "Prints each workspace as it shows: visible layers, the Ghost "
            "and engraving. Every page carries a ruler to check the scale."))
        pdf_lay.addWidget(tp_box)

        # Shared by the 1:1 print, the 1:1 PDF and the catalog sheet
        lw_box  = QGroupBox("1:1 Print, 1:1 PDF and Catalog")
        lw_form = QFormLayout(lw_box)
        self._cat_lw = _spinbox(0.1, 3.0, 0.1, float(cat_cfg["line_weight_mm"]),
                                decimals=2)
        self._cat_lw.setToolTip("Stroke width on paper.")
        lw_form.addRow("Line weight:", self._cat_lw)
        self._cat_offset = _spinbox(
            -100.0, 100.0, 1.0, float(cat_cfg.get("content_offset_mm", 0.0)))
        self._cat_offset.setToolTip(
            "Moves the drawing down (+) or up (−) on the page; the caption "
            "stays put. Clears a binding margin when pages are bound into a "
            "catalog. 0 = centered.")
        lw_form.addRow("Vertical offset:", self._cat_offset)
        pdf_lay.addWidget(lw_box)

        # PDF for Catalog only
        cat_box  = QGroupBox("Catalog PDF")
        cat_box.setToolTip("Export ▸ PDF for Catalog: the front and both "
                           "temples on one sheet.")
        cat_form = QFormLayout(cat_box)

        self._cat_paper = QComboBox()
        self._cat_paper_choices = [("a5", "A5 (landscape)"),
                                   ("half_letter", "Half-Letter (landscape)")]
        for _k, _lbl in self._cat_paper_choices:
            self._cat_paper.addItem(_lbl, _k)
        self._cat_paper.setCurrentIndex(
            next((i for i, (k, _l) in enumerate(self._cat_paper_choices)
                  if k == cat_cfg["paper"]), 0))
        cat_form.addRow("Paper size:", self._cat_paper)

        self._cat_font = FontFilterCombo(family=cat_cfg["caption_font"])
        self._cat_font.setToolTip(
            "Type to filter: the list narrows to the families that match. "
            "The arrow shows the current family's siblings.")
        cat_form.addRow("Caption font:", self._cat_font)

        self._cat_caption_chk = QCheckBox("Print the file name as a caption")
        self._cat_caption_chk.setChecked(bool(cat_cfg["caption"]))
        cat_form.addRow(self._cat_caption_chk)

        self._cat_scale_chk = QCheckBox("Print the scale")
        self._cat_scale_chk.setToolTip(
            "Prints “Scale 1:1” in a corner, or the reduction when the "
            "drawing had to shrink to fit the page.")
        self._cat_scale_chk.setChecked(bool(cat_cfg["show_scale"]))
        cat_form.addRow(self._cat_scale_chk)

        self._cat_fill_chk = QCheckBox("Print frame, inlay and lens fills")
        self._cat_fill_chk.setChecked(bool(cat_cfg.get("include_fill", False)))
        self._cat_fill_chk.setToolTip(
            "Lays the Frame Fill, Inlay Fill and Lens Fill under the line "
            "work, as each workspace shows them. A workspace with its fill "
            "off, or whose outline doesn't close, prints line work only.\n\n"
            "Off is the cutting-room sheet; on is the showroom page.")
        cat_form.addRow(self._cat_fill_chk)

        def _layer_checks(ws_key, selected) -> tuple[QWidget, dict]:
            row = QWidget()
            grid = QGridLayout(row)
            layer_grids.append(grid)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(2)
            checks = {}
            for i, layer in enumerate(_WS_LAYERS[ws_key]):
                cb = QCheckBox(layer.value)
                cb.setChecked(layer.value in selected)
                grid.addWidget(cb, i // 3, i % 3)
                checks[layer.value] = cb
            grid.setColumnStretch(3, 1)
            return row, checks

        layer_grids: list[QGridLayout] = []
        front_row, self._cat_front_layers = _layer_checks(
            "front", cat_cfg["front_layers"])
        cat_form.addRow("Front layers:", front_row)
        temple_row, self._cat_temple_layers = _layer_checks(
            "temple_r", cat_cfg["temple_layers"])
        cat_form.addRow("Temple layers:", temple_row)
        # Two grids, one set of columns: the widest name sets every column.
        col_w = max(cb.sizeHint().width() for cb in
                    (*self._cat_front_layers.values(),
                     *self._cat_temple_layers.values()))
        for grid in layer_grids:
            for col in range(3):
                grid.setColumnMinimumWidth(col, col_w)
        pdf_lay.addWidget(cat_box)
        pdf_lay.addStretch()

        self._check_conflicts()

        # A typed number settles when the typing is done, as in GuildModel;
        # and the wheel scrolls the tab unless a field has focus.
        from PySide6.QtWidgets import QAbstractSpinBox
        for box in self.findChildren(QAbstractSpinBox):
            box.setKeyboardTracking(False)
        self._wheel_guard = _WheelGuard(self)
        self._wheel_guard.guard(tabs)

        # Open at the size the maker left it, else at the content's own size,
        # within the screen (see _initial_size).
        self.resize(self._initial_size(prefs))

    @staticmethod
    def _scrolled(inner: QWidget) -> QScrollArea:
        """Wrap a tab's column so no tab dictates the dialog's minimum size."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    @staticmethod
    def _hint(text: str) -> QLabel:
        """A short line of guidance in the muted hint style (theme
        `QLabel#hintLabel`); anything longer belongs in a tooltip."""
        lbl = QLabel(text)
        lbl.setObjectName("hintLabel")
        lbl.setWordWrap(True)
        return lbl

    def _initial_size(self, prefs: dict) -> QSize:
        """The remembered size (`prefs_dialog_size`), else the widest and
        tallest tab content plus the scroll bar and the chrome; either way no
        more than 80 % of the screen the dialog will show on, and never under
        the minimums."""
        from PySide6.QtWidgets import QStyle
        avail = _available_screen(self)
        max_w, max_h = int(avail.width() * 0.8), int(avail.height() * 0.8)
        floor_w, floor_h = self.minimumWidth(), self.minimumHeight()
        saved = prefs.get("prefs_dialog_size")
        if (isinstance(saved, (list, tuple)) and len(saved) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) and v > 0 for v in saved)):
            return QSize(max(min(int(saved[0]), max_w), floor_w),
                         max(min(int(saved[1]), max_h), floor_h))
        w = h = 0
        for i in range(self._tabs.count()):
            page = self._tabs.widget(i)
            inner = page.widget() if isinstance(page, QScrollArea) else page
            hint = inner.sizeHint()
            w, h = max(w, hint.width()), max(h, hint.height())
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        chrome = self._tabs.tabBar().sizeHint().height() + 72     # tab bar + OK row
        return QSize(max(min(w + bar + 8, max_w), floor_w),
                     max(min(h + chrome, max_h), floor_h))

    # ------------------------------------------------------------------
    # Layers & Colors helpers
    # ------------------------------------------------------------------

    def _layer_resolved(self, name: str, mode: str) -> tuple[str, bool]:
        """(hex, is_override) for a layer's color in one mode."""
        ov = self._layer_over[mode].get(f"layer.{name}")
        if ov:
            return ov, True
        return theme.default_layer_color(name, mode == "dark"), False

    def _refresh_layer_btn(self, name: str):
        for mode in ("light", "dark"):
            hexv, overridden = self._layer_resolved(name, mode)
            btn = self._layer_btns[(name, mode)]
            pm = QPixmap(14, 14)
            pm.fill(QColor(hexv))
            btn.setIcon(QIcon(pm))
            btn.setText(hexv if overridden else "default")

    def _pick_layer_color(self, name: str, mode: str):
        cur, _ = self._layer_resolved(name, mode)
        c = QColorDialog.getColor(QColor(cur), self,
                                  f"{name} color ({mode} mode)")
        if c.isValid():
            self._layer_over[mode][f"layer.{name}"] = c.name()
            self._refresh_layer_btn(name)

    def _reset_layer_color(self, name: str):
        for mode in ("light", "dark"):
            self._layer_over[mode].pop(f"layer.{name}", None)
        self._refresh_layer_btn(name)

    def _show_cache_size(self):
        from .export.gdraw import image_cache_size
        mb = image_cache_size() / (1024 * 1024)
        self._cache_size_lbl.setText(
            "Empty." if mb == 0 else
            f"{mb:.1f} MB of copies of stored images." if mb >= 0.1 else
            "Under 0.1 MB of copies of stored images.")
        self._clear_cache_btn.setEnabled(mb > 0)

    def _clear_image_cache(self):
        from .export.gdraw import clear_image_cache
        r = QMessageBox.question(
            self, "Clear Image Cache",
            "Delete the copies of the stored images unpacked from the designs "
            "you opened? Each design still holds its images and unpacks them "
            "again when it is opened. The open design's images are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes:
            return
        clear_image_cache(keep=self._images_in_use())
        self._show_cache_size()

    def _reset_all_layer_colors(self):
        for mode in ("light", "dark"):
            self._layer_over[mode].clear()
        # The grid's rows, not every Layer: BRIDGE has none, and reaching it
        # raised before the rows after it were redrawn.
        for name in dict.fromkeys(n for n, _ in self._layer_btns):
            self._refresh_layer_btn(name)

    def _collect_theme(self) -> dict:
        """prefs["theme"] value: non-layer tokens preserved from the incoming
        prefs, layer.* tokens replaced by this dialog's state."""
        out = {"light": {}, "dark": {}}
        for mode in ("light", "dark"):
            for tok, v in self._base_theme[mode].items():
                if not tok.startswith("layer."):
                    out[mode][tok] = v
            out[mode].update(self._layer_over[mode])
        return out

    # ------------------------------------------------------------------
    # Appearance-tab helpers
    # ------------------------------------------------------------------

    def _pick_inlay_default_color(self):
        c = QColorDialog.getColor(QColor(self._inlay_default_color), self,
                                  "Inlay fill color")
        if c.isValid():
            self._inlay_default_color = c.name()
            self._update_inlay_default_swatch()

    def _update_inlay_default_swatch(self):
        pm = QPixmap(16, 16)
        pm.fill(QColor(self._inlay_default_color))
        self._inlay_color_btn.setIcon(QIcon(pm))

    def _on_vp_preset_changed(self, idx: int):
        self._vp_color_btn.setEnabled(self._vp_choices[idx][0] == "custom")

    def _pick_vp_color(self):
        c = QColorDialog.getColor(QColor(self._vp_custom_color), self,
                                  "Canvas color")
        if c.isValid():
            self._vp_custom_color = c.name()
            self._update_vp_swatch()

    def _update_vp_swatch(self):
        pm = QPixmap(16, 16)
        pm.fill(QColor(self._vp_custom_color))
        self._vp_color_btn.setIcon(QIcon(pm))

    def _pick_grid_color(self, which: str):
        current = (self._grid_minor_color if which == "minor"
                   else self._grid_major_color)
        fallback = theme.color(f"canvas.grid_{which}")
        c = QColorDialog.getColor(QColor(current or fallback), self,
                                  f"Grid {which} line color")
        if c.isValid():
            if which == "minor":
                self._grid_minor_color = c.name()
            else:
                self._grid_major_color = c.name()
            self._update_grid_swatches()

    def _reset_grid_colors(self):
        self._grid_minor_color = ""
        self._grid_major_color = ""
        self._update_grid_swatches()

    def _update_grid_swatches(self):
        for value, which, btn in (
                (self._grid_minor_color, "minor", self._grid_minor_btn),
                (self._grid_major_color, "major", self._grid_major_btn)):
            pm = QPixmap(16, 16)
            pm.fill(QColor(value or theme.color(f"canvas.grid_{which}")))
            btn.setIcon(QIcon(pm))

    # ------------------------------------------------------------------

    # Bound elsewhere as fixed shortcuts; a hotkey on one of these makes Qt
    # treat the sequence as ambiguous and fire NEITHER — Undo simply died.
    # "Delete" / "Escape" are the long spellings of the same two keys.
    _RESERVED_KEYS = ({k for _name, keys in _FIXED_SHORTCUTS for k in keys}
                      | {"Delete", "Escape"})

    def _check_conflicts(self):
        texts = [e.text().strip() for e in self._key_edits]
        non_empty = [t for t in texts if t]
        conflict_keys = {t for t in non_empty if non_empty.count(t) > 1}
        reserved = {t for t in non_empty if t in self._RESERVED_KEYS}
        typing = {t for t in non_empty if t in _TYPING_KEYS}
        conflict_keys |= reserved | typing
        for edit in self._key_edits:
            txt = edit.text().strip()
            if txt and txt in conflict_keys:
                # Explicit ink: the theme's light-on-dark text is unreadable
                # on the pink highlight in dark mode.
                edit.setStyleSheet("background: #ffcccc; color: #1f1f1f;")
            else:
                edit.setStyleSheet("")
        has_conflict = bool(conflict_keys)
        self._ok_btn.setEnabled(not has_conflict)
        self._ok_btn.setToolTip(
            "Resolve the hotkey conflict on the Hotkeys tab first."
            if has_conflict else "")
        if has_conflict:
            parts = []
            dupes = sorted(conflict_keys - reserved - typing)
            if dupes:
                parts.append(f"{', '.join(dupes)} assigned to multiple actions")
            if reserved:
                parts.append(f"{', '.join(sorted(reserved))} reserved for a "
                             "fixed shortcut (listed below)")
            if typing:
                parts.append(f"{', '.join(sorted(typing))} reserved for typing "
                             "values in the tools")
            self._conflict_label.setText("Conflict: " + "; ".join(parts) + ".")
            self._conflict_label.show()
        else:
            self._conflict_label.hide()

    # ------------------------------------------------------------------

    def to_prefs(self) -> dict:
        """Return a prefs dict reflecting the current dialog state."""
        toolbar = {key: chk.isChecked() for key, chk in self._tb_checks.items()}
        hotkeys = {
            key: self._key_edits[i].text().strip()
            for i, key in enumerate(self._hk_keys)
        }
        return {
            "dark_mode":            self._dark_check.isChecked(),
            "theme":                self._collect_theme(),
            "viewport": {
                "preset":    self._vp_choices[self._vp_combo.currentIndex()][0],
                "custom_bg": self._vp_custom_color,
                "vignette":  self._vignette_slider.value(),
            },
            "dot_radius_px":        int(self._dot_spin.value()),
            "compact_toolbar":      self._compact_check.isChecked(),
            "grid_spacing_mm":      self._grid_spacing_spin.value(),
            "grid_major":           self._grid_major_spin.value(),
            "grid_minor_color":     self._grid_minor_color,
            "grid_major_color":     self._grid_major_color,
            "grid_major_width_px":  self._grid_width_spin.value(),
            "default_line_weight":  self._weight_spin.value(),
            "mirror_on_startup":    self._mirror_chk.isChecked(),
            "guides_on_startup":    self._guides_chk.isChecked(),
            "snap_on_startup":      self._snap_chk.isChecked(),
            "smooth_handles":       self._smooth_chk.isChecked(),
            "boxing_on_startup":    self._boxing_chk.isChecked(),
            "boxing_a_mm":          self._box_a.value(),
            "boxing_b_mm":          self._box_b.value(),
            "boxing_dbl_mm":        self._box_dbl.value(),
            "stock_on_startup":     self._stock_chk.isChecked(),
            "stock_width_mm":       self._stock_w.value(),
            "stock_height_mm":      self._stock_h.value(),
            "temple_stock_width_mm":  self._temple_stock_w.value(),
            "temple_stock_height_mm": self._temple_stock_h.value(),
            "pad_on_startup":       self._pad_chk.isChecked(),
            "pad_width_mm":         self._pad_w.value(),
            "pad_height_mm":        self._pad_h.value(),
            "lens_fill_opacity_pct": int(self._lens_opacity_spin.value()),
            "lens_fill_intensity":   self._lens_intensity_spin.value(),
            "inlay_fill_color":       self._inlay_default_color,
            "inlay_fill_opacity_pct": int(self._inlay_opacity_spin.value()),
            "prompt_store_image":   self._prompt_store_chk.isChecked(),
            "toolbar":              toolbar,
            "hotkeys":              hotkeys,
            "catalog_pdf": {
                "paper":          self._cat_paper.currentData(),
                "line_weight_mm": self._cat_lw.value(),
                "content_offset_mm": self._cat_offset.value(),
                "caption":        self._cat_caption_chk.isChecked(),
                "caption_font":   self._cat_font.current_family(),
                "show_scale":     self._cat_scale_chk.isChecked(),
                "include_fill":   self._cat_fill_chk.isChecked(),
                "front_layers":   [n for n, cb in self._cat_front_layers.items()
                                   if cb.isChecked()],
                "temple_layers":  [n for n, cb in self._cat_temple_layers.items()
                                   if cb.isChecked()],
            },
            "template_print": {
                "paper":          self._tp_paper.currentData(),
                "orientation":    self._tp_orient.currentData(),
                "line_weight_mm": self._tp_lw.value(),
                "labels":         self._tp_labels_chk.isChecked(),
            },
        }


class TransformDialog(QDialog):
    """Exact numeric Scale / Rotate for the current selection."""

    def __init__(self, parent=None, obverse: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Transform Selection")
        form = QFormLayout(self)

        def _pct():
            s = QDoubleSpinBox()
            s.setRange(1.0, 10000.0)
            s.setDecimals(2)
            s.setSingleStep(5.0)
            s.setSuffix(" %")
            s.setValue(100.0)
            return s

        self._sx = _pct()
        self._sy = _pct()
        self._lock = QCheckBox("Lock aspect ratio")
        self._lock.setChecked(True)
        self._sy.setEnabled(False)
        self._lock.toggled.connect(
            lambda on: (self._sy.setEnabled(not on),
                        self._sy.setValue(self._sx.value()) if on else None))
        self._sx.valueChanged.connect(
            lambda v: self._sy.setValue(v) if self._lock.isChecked() else None)

        self._rot = QDoubleSpinBox()
        self._rot.setRange(-360.0, 360.0)
        self._rot.setDecimals(2)
        self._rot.setSingleStep(5.0)
        self._rot.setSuffix("°")
        self._rot.setValue(0.0)
        # The Text dialog's convention, and CAD's: until 1.3 a positive angle
        # here turned the selection clockwise while the Text dialog's turned
        # it counter-clockwise.
        self._rot.setToolTip("Positive rotates counter-clockwise.")

        self._pivot = QComboBox()
        self._pivot.addItems(["Selection center", "Drawing origin (0, 0)"])

        form.addRow("Scale X:", self._sx)
        form.addRow("Scale Y:", self._sy)
        form.addRow(self._lock)
        form.addRow("Rotation:", self._rot)
        form.addRow("Pivot:", self._pivot)

        note = QLabel(
            ("Positive rotation is counter-clockwise as the screen shows it, "
             "in View Obverse too. " if obverse else
             "Positive rotation is counter-clockwise. ")
            + "A non-uniform scale turns circles and arcs into splines.")
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        form.addRow(note)

        btns = QHBoxLayout()
        ok = QPushButton("Apply")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        form.addRow(btns)

    def values(self):
        """(sx, sy, rotation_deg, pivot_is_origin)"""
        return (self._sx.value() / 100.0,
                self._sy.value() / 100.0,
                self._rot.value(),
                self._pivot.currentIndex() == 1)


class MainWindow(QMainWindow):
    # ── Phase 14: proxy properties — all delegate to the active WorkspaceState ──

    @property
    def _active_ws(self) -> "WorkspaceState":
        return self._workspaces[self._ws_tab_widget.currentIndex()]

    # Document
    @property
    def _doc_curves(self): return self._active_ws.doc_curves
    @_doc_curves.setter
    def _doc_curves(self, v): self._active_ws.doc_curves = v

    @property
    def _doc_dims(self): return self._active_ws.doc_dims
    @_doc_dims.setter
    def _doc_dims(self, v): self._active_ws.doc_dims = v

    @property
    def _bookmarks(self): return self._active_ws.bookmarks
    @_bookmarks.setter
    def _bookmarks(self, v): self._active_ws.bookmarks = v

    @property
    def _undo_stack(self): return self._active_ws.undo_stack
    @_undo_stack.setter
    def _undo_stack(self, v): self._active_ws.undo_stack = v

    @property
    def _redo_stack(self): return self._active_ws.redo_stack
    @_redo_stack.setter
    def _redo_stack(self, v): self._active_ws.redo_stack = v

    @property
    def _image_px_per_mm(self): return self._active_ws.image_px_per_mm
    @_image_px_per_mm.setter
    def _image_px_per_mm(self, v): self._active_ws.image_px_per_mm = v

    # Canvas
    @property
    def scene(self): return self._active_ws.scene
    @property
    def view(self): return self._active_ws.view
    @property
    def _snap(self): return self._active_ws.snap

    # Tools
    @property
    def _calib_tool(self): return self._active_ws.calib_tool
    @property
    def _draw_tool(self): return self._active_ws.draw_tool
    @property
    def _circle_tool(self): return self._active_ws.circle_tool
    @property
    def _edit_tool(self): return self._active_ws.edit_tool
    @property
    def _dim_tool(self): return self._active_ws.dim_tool
    @property
    def _trim_tool(self): return self._active_ws.trim_tool
    @property
    def _fillet_tool(self): return self._active_ws.fillet_tool
    @property
    def _split_tool(self): return self._active_ws.split_tool
    @property
    def _offset_tool(self): return self._active_ws.offset_tool
    @property
    def _rebuild_tool(self): return self._active_ws.rebuild_tool
    @property
    def _point_move_tool(self): return self._active_ws.point_move_tool
    @property
    def _text_tool(self): return self._active_ws.text_tool

    # Guides
    @property
    def _guides(self): return self._active_ws.const_guides
    @property
    def _boxing_guide(self): return self._active_ws.boxing_guide
    @property
    def _stock_guide(self): return self._active_ws.stock_guide
    @property
    def _pad_guide(self): return self._active_ws.pad_guide

    # Move gizmo
    @property
    def _move_gizmo(self): return self._active_ws.move_gizmo
    @_move_gizmo.setter
    def _move_gizmo(self, v): self._active_ws.move_gizmo = v

    @property
    def _move_gizmo_center(self): return self._active_ws.move_gizmo_center
    @_move_gizmo_center.setter
    def _move_gizmo_center(self, v): self._active_ws.move_gizmo_center = v

    @property
    def _drag_moving_curves(self): return self._active_ws.drag_moving_curves
    @_drag_moving_curves.setter
    def _drag_moving_curves(self, v): self._active_ws.drag_moving_curves = v

    @property
    def _drag_moving_dims(self): return self._active_ws.drag_moving_dims
    @_drag_moving_dims.setter
    def _drag_moving_dims(self, v): self._active_ws.drag_moving_dims = v
    @property
    def _drag_moving_texts(self): return self._active_ws.drag_moving_texts
    @_drag_moving_texts.setter
    def _drag_moving_texts(self, v): self._active_ws.drag_moving_texts = v

    # Sidebar face-image selection index
    @property
    def _selected_face_idx(self): return self._active_ws.selected_face_idx
    @_selected_face_idx.setter
    def _selected_face_idx(self, v): self._active_ws.selected_face_idx = v

    # ────────────────────────────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GuildDraw {__version__}")

        # Load persistent preferences first
        self._prefs = _prefs_mod.load()
        # The size and place the maker left the window at (GuildModel's key);
        # the first time, 1440×860 within the screen — on a 1366×768 laptop
        # the fixed size opened larger than the screen.
        _geo = self._prefs.get("main_window_geometry")
        _avail = _available_screen(self)
        if not (isinstance(_geo, str) and _geo
                and self.restoreGeometry(QByteArray.fromBase64(_geo.encode()))):
            self.resize(min(1440, int(_avail.width() * 0.95)),
                        min(860, int(_avail.height() * 0.95)))
        # Theme overrides + viewport preset must land before any workspace/
        # canvas is built so every painter resolves user colors from the
        # start; re-render the chrome in case saved overrides retint it
        # (main() styled defaults).
        theme.set_overrides(self._prefs.get("theme"))
        _vp_prefs = self._prefs.get("viewport") or {}
        theme.apply_viewport(_vp_prefs.get("preset", "auto"),
                             _vp_prefs.get("custom_bg"))
        theme.set_dot_radius(self._prefs.get("dot_radius_px", 4))
        theme.set_compact(self._prefs.get("compact_toolbar", False))
        QApplication.instance().setStyleSheet(theme.build_qss())
        # Tooltips: wrapped to a readable width app-wide, and off altogether
        # when the maker says so — the ? at the foot of the toolbar
        # (framedraft/tooltips.py; GuildModel's, shared).
        self._tooltip_filter = TooltipFilter(
            enabled=bool(self._prefs.get("tooltips", True)), parent=self)
        QApplication.instance().installEventFilter(self._tooltip_filter)

        # ── Global (non-workspace) state ──────────────────────────────────
        self._dark_mode            = self._prefs["dark_mode"]
        self._updating_weight_spin = False
        self._syncing_selection = False   # guards tree↔canvas selection sync
        self._default_line_weight: float = self._prefs["default_line_weight"]
        self._current_path: str | None = None   # .gdraw file path (or single SVG)
        self._dirty = False                     # unsaved changes (any workspace)
        self._pm_curves: list = []              # Point Move: captured selection
        self._pm_dims:   list = []
        self._layer_refresh_pending = False
        self._recent_files: list[str] = [
            p for p in self._prefs.get("recent_files", []) if isinstance(p, str)
        ]

        # Status bar must exist before WorkspaceState creates CanvasView instances
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._coords_label = QLabel()
        self._coords_label.setObjectName("coordsLabel")
        self._coords_label.setContentsMargins(0, 0, 8, 0)
        self._coords_label.setMinimumWidth(self._coords_label.fontMetrics()
                                           .horizontalAdvance("x: -000.00 mm  y: -000.00 mm"))
        self._status.addPermanentWidget(self._coords_label)
        self._info_label = QLabel()
        self._info_label.setContentsMargins(0, 0, 8, 0)
        self._status.addPermanentWidget(self._info_label)
        # "Ready for GuildModel" readiness dot (mirrors GuildModel's M5.2 traffic
        # light): green when the active workspace meets the export contract,
        # amber when it doesn't, gray when there's nothing to hand off.
        self._readiness_dot = ReadinessDot()
        self._status.addPermanentWidget(self._readiness_dot)

        # ── Phase 14: create per-workspace state containers ───────────────
        # _ws_tab_widget must be created before any proxy property access.
        self._ws_tab_widget = QTabWidget()
        self._ws_tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self._workspaces: list = []
        for ws_type, label in [
            ("front",    "Frame Front"),
            ("temple_r", "Temple R"),
            ("temple_l", "Temple L"),
            ("component", "Component"),
        ]:
            ws = WorkspaceState(ws_type, self._status, self)
            self._workspaces.append(ws)
            self._ws_tab_widget.addTab(ws.view, label)

        self.setCentralWidget(self._ws_tab_widget)
        # Tab-change handler wired after toolbar+panel are built (needs toolbar actions).

        # From here on, proxy properties (self.scene, self.view, self._snap, …) all
        # resolve to _workspaces[0] (Frame Front) since the tab widget starts at 0.

        # Connect the calib tool for each workspace
        _vign = int(_vp_prefs.get("vignette", 0))
        for ws in self._workspaces:
            ws.view.set_vignette(_vign)
            ws.view.set_calib_tool(ws.calib_tool)
            ws.calib_tool.calibrated.connect(self._apply_calibration)
            # A locked or hidden photo keeps its scale (the Canvas tab's rows).
            ws.calib_tool.refusal = (
                lambda i, ws=ws: self._calibration_refusal(ws, i))
            ws.calib_tool.status_message.connect(self._status.showMessage)
            ws.draw_tool.curve_added.connect(self._on_curve_added)
            ws.draw_tool.status_message.connect(self._status.showMessage)
            ws.draw_tool.canceled.connect(self._on_draw_canceled)
            ws.circle_tool.curve_added.connect(self._on_curve_added)
            ws.circle_tool.status_message.connect(self._status.showMessage)
            ws.circle_tool.canceled.connect(self._on_draw_canceled)
            ws.dim_tool.dim_added.connect(self._on_dim_added)
            ws.dim_tool.status_message.connect(self._status.showMessage)
            ws.dim_tool.canceled.connect(self._on_draw_canceled)
            ws.trim_tool.trim_applied.connect(self._on_trim_applied)
            ws.trim_tool.status_message.connect(self._status.showMessage)
            ws.trim_tool.canceled.connect(self._on_trim_canceled)
            ws.fillet_tool.fillet_applied.connect(self._on_fillet_applied)
            ws.fillet_tool.status_message.connect(self._status.showMessage)
            ws.fillet_tool.canceled.connect(self._on_trim_canceled)
            ws.split_tool.split_applied.connect(self._on_split_applied)
            ws.split_tool.status_message.connect(self._status.showMessage)
            ws.split_tool.canceled.connect(self._on_split_canceled)
            ws.offset_tool.offset_applied.connect(self._on_offset_applied)
            ws.offset_tool.status_message.connect(self._status.showMessage)
            ws.offset_tool.canceled.connect(self._on_offset_canceled)
            ws.rebuild_tool.rebuild_applied.connect(self._on_rebuild_applied)
            ws.rebuild_tool.status_message.connect(self._status.showMessage)
            ws.rebuild_tool.canceled.connect(self._on_rebuild_canceled)
            ws.point_move_tool.moved.connect(self._on_point_moved)
            ws.point_move_tool.status_message.connect(self._status.showMessage)
            ws.text_tool.text_added.connect(self._on_text_added)
            ws.text_tool.canceled.connect(self._on_text_canceled)
            ws.text_tool.status_message.connect(self._status.showMessage)
            ws.point_move_tool.canceled.connect(self._on_point_move_canceled)

        self._build_toolbar()
        self._build_side_panel()
        _panel_act = self._prop_dock.toggleViewAction()
        _panel_act.setText("Panel")
        _panel_act.setToolTip("Show / hide the Properties panel")
        self._toolbar.addSeparator()
        self._toolbar.addAction(_panel_act)
        self._act_panel = _panel_act
        self._apply_toolbar_icons(False)
        self._build_menus()

        # ── Toolbar visibility and hotkey prefs ───────────────────────────
        _tb_defaults = _prefs_mod.DEFAULTS["toolbar"]
        _hk_defaults = _prefs_mod.DEFAULTS["hotkeys"]
        self._toolbar_prefs: dict = {**_tb_defaults, **self._prefs.get("toolbar", {})}
        self._hotkey_prefs:  dict = {**_hk_defaults, **self._prefs.get("hotkeys", {})}
        self._shortcuts:     dict = {}
        self._hotkey_targets: dict = {
            "line":         self._act_line.trigger,
            "spline":       self._act_spline.trigger,
            "circle":       self._act_circle.trigger,
            "arc":          self._act_arc.trigger,
            "arc_sec":      self._act_arc_sec.trigger,
            "fillet":       self._act_fillet.trigger,
            "dim":          self._act_dim.trigger,
            "trim":         self._act_trim.trigger,
            "split_curve":  self._act_split_curve.trigger,
            "offset":       self._act_offset.trigger,
            "rebuild":      self._act_rebuild.trigger,
            "point_move":   self._act_point_move.trigger,
            "text":         self._act_text.trigger,
            "snap_node_ep": self._snap_selected_node_to_endpoint,
            "move_gizmo":   self._toggle_move_gizmo,
            "join":         self._act_join.trigger,
            "obverse":      self._act_obverse.trigger,
            "bookmark":     self._add_bookmark,
            "insert_square": self._insert_square_char,
        }
        self._apply_toolbar_visibility(self._toolbar_prefs)
        self._apply_hotkeys(self._hotkey_prefs)
        # The insert-□ binding is matched by eventFilter, which must see key
        # presses in every window (modal dialogs included) — app-level filter.
        QApplication.instance().installEventFilter(self)

        # Pinned toolbar overflow pop-out (durable, global) — restore + persist.
        self._toolbar.set_pinned(
            bool(self._prefs.get("toolbar_pinned", False)), persist=False)
        self._toolbar.pin_changed.connect(self._on_toolbar_pin_changed)

        # ── Snap palette (per-type snap toggles + radius) ─────────────────
        from .snap_palette import SnapPalette
        from .canvas.snapping import SNAP_TYPE_KEYS
        # prefs.load() deep-merges DEFAULTS["snap_types"], so the dict is
        # complete; the all-True base only covers a hand-edited prefs file.
        snap_types = {k: True for k in SNAP_TYPE_KEYS}
        snap_types.update({k: bool(v) for k, v in
                           (self._prefs.get("snap_types") or {}).items()
                           if k in snap_types})
        snap_radius = int(self._prefs.get("snap_radius_px", 10))
        for ws in self._workspaces:
            ws.snap.set_enabled_types(snap_types)
            ws.snap.set_radius_px(snap_radius)
        self._snap_palette = SnapPalette(self)
        self._snap_palette.set_state(snap_types, snap_radius)
        self._snap_palette.types_changed.connect(self._on_snap_types_changed)
        self._snap_palette.radius_changed.connect(self._on_snap_radius_changed)
        self._act_snap_palette.toggled.connect(self._toggle_snap_palette)

        self._act_obverse.toggled.connect(self._on_obverse_toggled)

        # ── Grid overlay (global) ─────────────────────────────────────────
        self._act_grid.blockSignals(True)
        self._act_grid.setChecked(bool(self._prefs.get("grid_visible", False)))
        self._act_grid.blockSignals(False)
        self._act_grid.toggled.connect(self._on_grid_toggled)
        self._apply_grid_config()

        # ── Per-workspace post-toolbar wiring ─────────────────────────────
        snap_fn = lambda: self._act_snap.isChecked()
        for ws in self._workspaces:
            ws.edit_tool.set_endpoint_snap_context(
                ws.doc_curves, ws.view, snap_enabled_fn=snap_fn
            )
            ws.edit_tool.about_to_modify.connect(self._pre_edit_snapshot)
            ws.edit_tool.node_selection_changed.connect(self._act_snap_ep.setEnabled)
            ws.edit_tool.node_selection_changed.connect(self._update_split_enabled)
            ws.scene.selectionChanged.connect(self._on_selection_changed)
            ws.scene.selectionChanged.connect(
                lambda ws=ws: self._drop_orphan_gizmo(ws))
            ws.scene.selectionChanged.connect(self._update_split_enabled)
            ws.scene.selectionChanged.connect(self._update_explode_enabled)
            ws.view.zoom_changed.connect(lambda _, _ws=ws: (
                self._update_info_label() if _ws is self._active_ws else None
            ))
            ws.view.set_delete_callback(self._delete_selected)
            ws.view.set_insert_node_callback(self._insert_node)
            ws.view.set_snap_to_endpoint_callback(self._snap_selected_node_to_endpoint)
            ws.view.set_move_callbacks(
                self._pre_move_selected,
                self._move_selected_by,
                self._end_move_selected,
            )
            ws.view.set_escape_callback(self._hide_move_gizmo)
            ws.view.set_face_moved_callback(self._mark_dirty)
            ws.view.measure_bar.commit_radius.connect(self._on_measure_commit_radius)
            ws.scene.set_dim_drag_callback(self._pre_edit_snapshot)
            ws.scene.set_text_edit_callback(self._edit_text_object)
            ws.on_document_changed = (
                lambda ws=ws: self._schedule_layer_panel_refresh(ws))
            ws.on_mirror_restored = (
                lambda on, ws=ws: self._act_mirror.setChecked(on)
                if ws is self._active_ws else setattr(ws, "mirror_enabled", on))
            ws.view.released.connect(self._flush_deferred_readiness)
            ws.scene.geometry_changed = (
                lambda _curve=None, ws=ws: self._schedule_boxing_follow(ws))
            ws.scene.fill_auto_disabled = (
                lambda status, ws=ws: self._on_fill_auto_disabled(status, ws))
            ws.scene.lens_fill_auto_disabled = (
                lambda status, ws=ws: self._on_lens_fill_auto_disabled(status, ws))
            ws.scene.inlay_fill_auto_disabled = (
                lambda status, ws=ws: self._on_inlay_fill_auto_disabled(status, ws))
            ws.view.set_default_face(_DEFAULT_FACE.get(ws.workspace_type, ""))

        # ── Toggle actions wired to dispatch helpers (lambdas evaluate _active_ws) ─
        self._act_mirror.toggled.connect(self._on_mirror_toggled)
        self._act_guides.toggled.connect(lambda v: self._guides.set_visible(v))
        self._act_snap.toggled.connect(lambda v: self._snap.set_enabled(v))
        self._act_smooth.toggled.connect(lambda v: self._edit_tool.set_smooth_mode(v))
        self._act_boxing.toggled.connect(self._on_boxing_visible_toggled)
        self._act_stock.toggled.connect(lambda v: self._stock_guide.set_visible(v))
        self._act_pad.toggled.connect(lambda v: self._pad_guide.set_visible(v))

        # ── Apply prefs to toolbar / spinboxes (before connecting _save_prefs) ──
        p = self._prefs
        self._act_mirror.setChecked(p["mirror_on_startup"])
        self._act_guides.setChecked(p["guides_on_startup"])
        self._act_snap.setChecked(p["snap_on_startup"])
        self._act_smooth.setChecked(p["smooth_handles"])
        self._act_boxing.setChecked(p["boxing_on_startup"])
        self._act_stock.setChecked(p["stock_on_startup"])
        self._act_pad.setChecked(p["pad_on_startup"])
        self._boxing_a_spin.setValue(p["boxing_a_mm"])
        self._boxing_b_spin.setValue(p["boxing_b_mm"])
        self._boxing_dbl_spin.setValue(p["boxing_dbl_mm"])
        self._stock_w_spin.setValue(p["stock_width_mm"])
        self._stock_h_spin.setValue(p["stock_height_mm"])
        self._pad_w_spin.setValue(p["pad_width_mm"])
        self._pad_h_spin.setValue(p["pad_height_mm"])
        self._sync_weight_spin([])

        # Sync initial mirror state + guide visibility for every workspace
        for ws in self._workspaces:
            horizontal = (ws.workspace_type in ("temple_r", "temple_l"))
            if ws.scene.mirror:
                ws.scene.mirror.set_enabled(p["mirror_on_startup"])
            ws.scene.set_mirror_display(p["mirror_on_startup"])
            ws.snap.set_mirror(0.0, p["mirror_on_startup"], horizontal=horizontal)
            ws.boxing_guide.set_mirror(p["mirror_on_startup"])
            ws.boxing_guide.set_visible(p["boxing_on_startup"])
            ws.stock_guide.set_visible(p["stock_on_startup"])
            ws.pad_guide.set_visible(p["pad_on_startup"])
            ws.const_guides.set_visible(p["guides_on_startup"])
            ws.snap.set_enabled(p["snap_on_startup"])
            ws.edit_tool.set_smooth_mode(p["smooth_handles"])

        # Save sidebar state into each workspace state so tab-switch restores correctly
        for ws in self._workspaces:
            ws.mirror_enabled = p["mirror_on_startup"]
            ws.snap_enabled   = p["snap_on_startup"]
            ws.smooth_handles = p["smooth_handles"]
            ws.guides_visible = p["guides_on_startup"]
            ws.boxing_visible = p["boxing_on_startup"]
            ws.stock_visible  = p["stock_on_startup"]
            ws.pad_visible    = p["pad_on_startup"]
            ws.boxing_a       = p["boxing_a_mm"]
            ws.boxing_b       = p["boxing_b_mm"]
            ws.boxing_dbl     = p["boxing_dbl_mm"]
            ws.stock_w        = p["stock_width_mm"]
            ws.stock_h        = p["stock_height_mm"]
            ws.pad_w          = p["pad_width_mm"]
            ws.pad_h          = p["pad_height_mm"]
            ws.lens_fill_opacity = self._default_lens_fill_opacity()
            ws.lens_fill_intensity = self._default_lens_fill_intensity()
            ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
            ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
            ws.inlay_fill_color   = self._default_inlay_fill_color()
            ws.inlay_fill_opacity = self._default_inlay_fill_opacity()
            ws.scene.set_inlay_fill_color(QColor(ws.inlay_fill_color))
            ws.scene.set_inlay_fill_opacity(ws.inlay_fill_opacity)
        front0 = self._workspaces[0]
        self._lens_fill_opacity_slider.blockSignals(True)
        self._lens_fill_opacity_slider.setValue(round(front0.lens_fill_opacity * 100))
        self._lens_fill_opacity_slider.blockSignals(False)
        self._lens_fill_intensity_slider.blockSignals(True)
        self._lens_fill_intensity_slider.setValue(
            slider_from_intensity(front0.lens_fill_intensity))
        self._lens_fill_intensity_slider.blockSignals(False)
        self._update_lens_fill_swatches(front0.lens_fill_top,
                                        front0.lens_fill_bottom,
                                        front0.lens_fill_intensity)
        self._inlay_fill_opacity_slider.blockSignals(True)
        self._inlay_fill_opacity_slider.setValue(
            round(front0.inlay_fill_opacity * 100))
        self._inlay_fill_opacity_slider.blockSignals(False)
        self._update_inlay_fill_swatch(front0.inlay_fill_color)

        # Workspace-specific default overrides (override prefs for non-front tabs)
        # The temple blank is its own preference; the guide carries the core
        # line (y = 0), where the wire runs and where GuildModel places the
        # temple's zero.
        for temple in (self._workspaces[1], self._workspaces[2]):  # temple_r, temple_l
            temple.guides_visible = False
            temple.boxing_visible = False
            temple.pad_visible    = False
            temple.stock_visible  = True
            temple.stock_w        = p["temple_stock_width_mm"]
            temple.stock_h        = p["temple_stock_height_mm"]
            temple.const_guides.set_visible(False)
            temple.boxing_guide.set_visible(False)
            temple.pad_guide.set_visible(False)
            temple.stock_guide.set_core_line(True)
            temple.stock_guide.set_visible(True)
            temple.stock_guide.set_width(temple.stock_w)
            temple.stock_guide.set_height(temple.stock_h)

        component = self._workspaces[3]
        component.guides_visible = False
        component.boxing_visible = False
        component.pad_visible    = False
        component.stock_visible  = True
        component.stock_w        = 10.0
        component.stock_h        = 20.0
        component.const_guides.set_visible(False)
        component.boxing_guide.set_visible(False)
        component.pad_guide.set_visible(False)
        component.stock_guide.set_visible(True)
        component.stock_guide.set_width(10.0)
        component.stock_guide.set_height(20.0)

        # Toolbar toggles and guide spinboxes are SESSION state (per-workspace,
        # saved/restored on tab switch). They deliberately do NOT write prefs:
        # startup defaults are only changed via Settings > Preferences.

        # Undo/redo keyboard shortcuts (window-scope)
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._handle_undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self._redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self._redo)
        QShortcut(QKeySequence("Ctrl+G"), self).activated.connect(self._group_selected)
        QShortcut(QKeySequence("Ctrl+Shift+G"), self).activated.connect(self._ungroup_selected)
        # Clipboard/select/transform shortcuts go through the focus guard so
        # they stay inert while a HUD text field has focus.
        for seq, target in [("Ctrl+C", self._copy_selected),
                            ("Ctrl+V", self._paste),
                            ("Ctrl+D", self._duplicate_selected),
                            ("Ctrl+A", self._select_all),
                            ("Ctrl+T", self._transform_selected)]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(
                lambda t=target: self._hotkey_dispatch(t))

        # Wire workspace tab-change now that all actions exist
        self._last_ws_idx = 0
        self._ws_tab_widget.currentChanged.connect(self._on_workspace_changed)
        self._show_guide_sections("front")
        self._apply_boxing_field_modes()
        self._refresh_library_panel()
        self._refresh_layer_panel()

        self._status.showMessage(
            "Ready  |  Right-drag (or Space+drag) to pan  |  Scroll to zoom"
        )
        self.setAcceptDrops(True)        # a design, drawing, trace or photo (B29)
        if _prefs_mod.LOAD_NOTE:
            # Said once, after the window is up: the preferences file did not
            # read and was kept aside (prefs.load).
            note = _prefs_mod.LOAD_NOTE
            _prefs_mod.LOAD_NOTE = None
            QTimer.singleShot(0, self, lambda: self._status.showMessage(note, 20000))
        self._update_info_label()

        # Apply dark mode from prefs (must be after all widgets are built)
        if self._dark_mode:
            self._act_dark.setChecked(True)
            self._toggle_dark_mode(True)

        # Defer fit until the window has its final painted size
        def _initial_fit():
            self._fit_view()
            self._workspaces[0].fitted = True
        QTimer.singleShot(0, self, _initial_fit)
        self._update_readiness()      # the dot's tip from the document, at once
        for ws in self._workspaces:
            self._sync_empty_hint(ws)
        # The fill widgets' enabled state for the style they open on: under
        # Color, Choose…, ✕ and Tumble were live until the first tab switch.
        self._sync_fill_style_widgets(self._active_ws)
        self._sync_inlay_fill_style_widgets(self._active_ws)

        # ── Autosave + crash recovery ─────────────────────────────────────
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(self._AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._autosave_timer.start()
        QTimer.singleShot(400, self, self._offer_recovery)

        # Start-up applies Preferences through the handlers, and some mark the
        # design dirty (a Ghost off at start-up did): a fresh window holds
        # nothing unsaved.
        self._dirty = False
        self._update_title()

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = PinnableToolBar("Tools")
        self._toolbar = tb
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        _tb_px = theme.toolbar_icon_px()
        tb.setIconSize(QSize(_tb_px, _tb_px))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)

        tool_group = QActionGroup(self)
        tool_group.setExclusive(True)

        self._act_select = QAction("Select", self, checkable=True, checked=True)
        self._act_select.setToolTip(
            "Select: click a curve to select it and show its nodes.\n"
            "Alt+click cycles through overlapping items at the same position."
        )
        self._act_line   = QAction("Line",   self, checkable=True)
        self._act_line.setToolTip(
            "Line: click to place nodes; double-click or Enter to finish.\n"
            "Type a length (mm) to lock radius; Tab to switch to angle lock."
        )
        self._act_spline = QAction("Spline", self, checkable=True)
        self._act_spline.setToolTip(
            "Spline: click to place nodes (Catmull-Rom smooth curve); double-click or Enter to finish.\n"
            "Type a length (mm) to lock radius; Tab to switch to angle lock."
        )
        self._act_circle = QAction("Circle", self, checkable=True)
        self._act_circle.setToolTip(
            "Circle: click to place center, click again to set radius.\n"
            "Snaps to existing nodes and quadrant points.")
        self._act_arc    = QAction("Arc",    self, checkable=True)
        self._act_arc.setToolTip(
            "Arc: click center, click start point (sets radius), click end point.\n"
            "Arc sweeps clockwise from start to end.")
        self._act_arc_sec = QAction("Arc\n3-pt", self, checkable=True)
        self._act_arc_sec.setToolTip(
            "Arc (start-end-center): click the start point, the end point, then\n"
            "the center. The center snaps to the chord's perpendicular bisector\n"
            "for a true circular arc; place it on either side to flip the bulge.")
        self._act_fillet = QAction("Fillet", self, checkable=True)
        self._act_fillet.setToolTip(
            "Fillet: click two connected lines, then type a radius (mm) + Enter\n"
            "to round the corner with a tangent arc (legs trimmed to the tangents).\n"
            "Esc to cancel.")
        self._act_dim    = QAction("Dim",    self, checkable=True)
        self._act_dim.setToolTip(
            "Dim: click two points to place a dimension annotation (mm).\n"
            "Snaps to curve nodes. Never exported.")

        self._act_trim = QAction("Trim", self, checkable=True)
        self._act_trim.setToolTip(
            "Trim: click a curve to remove the segment between its two nearest\n"
            "intersections with all other curves.  Stay in trim mode to trim more.\n"
            "Esc to cancel."
        )
        self._act_split_curve = QAction("Split\nCurve", self, checkable=True)
        self._act_split_curve.setToolTip(
            "Split Curve: click anywhere on a curve to split it into two open curves\n"
            "at that point.  Click near an intersection to split both curves at once.\n"
            "Esc to cancel."
        )

        self._act_offset = QAction("Offset", self, checkable=True)
        self._act_offset.setToolTip(
            "Offset (O): select a curve, then type a distance (mm) and press Enter\n"
            "to create a parallel curve at that offset.\n"
            "Closed shapes: positive = outward, negative = inward.\n"
            "Esc to cancel."
        )

        self._act_rebuild = QAction("Rebuild", self, checkable=True)
        self._act_rebuild.setToolTip(
            "Rebuild Spline (R): select a spline or polyline, then type a target\n"
            "node count (Tab switches to a tolerance in mm) and press Enter to\n"
            "rebuild it with fewer, cleaner nodes. The HUD shows the resulting\n"
            "max deviation live. Ideal for tidying imported DXF outlines.\n"
            "Esc to cancel."
        )

        self._act_point_move = QAction("Point\nMove", self, checkable=True)
        self._act_point_move.setToolTip(
            "Point Move (G): click a grab point on the selection, then click\n"
            "the destination (or type X Y coordinates) to move the selection\n"
            "so the grab point lands exactly on the destination.\n"
            "Esc to cancel."
        )

        self._act_text = QAction("Text", self, checkable=True)
        self._act_text.setToolTip(
            "Text (I): click an anchor point to place engraving text\n"
            "(any installed font, true mm cap height, rotatable).\n"
            "Lands on the ENGRAVING layer; converted to outlines at DXF export.\n"
            "Double-click placed text to edit it."
        )

        self._act_select.triggered.connect(self._set_tool_select)
        self._act_line.triggered.connect(self._set_tool_line)
        self._act_spline.triggered.connect(self._set_tool_spline)
        self._act_circle.triggered.connect(self._set_tool_circle)
        self._act_arc.triggered.connect(self._set_tool_arc)
        self._act_arc_sec.triggered.connect(self._set_tool_arc_sec)
        self._act_fillet.triggered.connect(self._set_tool_fillet)
        self._act_dim.triggered.connect(self._set_tool_dim)
        self._act_trim.triggered.connect(self._set_tool_trim)
        self._act_split_curve.triggered.connect(self._set_tool_split_curve)
        self._act_offset.triggered.connect(self._set_tool_offset)
        self._act_rebuild.triggered.connect(self._set_tool_rebuild)
        self._act_point_move.triggered.connect(self._set_tool_point_move)
        self._act_text.triggered.connect(self._set_tool_text)

        for act in (self._act_select, self._act_line, self._act_spline,
                    self._act_circle, self._act_arc, self._act_arc_sec,
                    self._act_fillet, self._act_dim,
                    self._act_text,
                    self._act_trim, self._act_split_curve, self._act_offset,
                    self._act_rebuild,
                    self._act_point_move):
            tool_group.addAction(act)
            tb.addAction(act)

        tb.addSeparator()

        self._act_mirror = QAction("Ghost", self, checkable=True, checked=True)
        self._act_mirror.setToolTip(
            "Ghost: preview each curve's mirrored twin across the axis (the\n"
            "bridge center on a front, the core line on a temple). A drawing aid\n"
            "only: the file and every export carry the curves drawn, and\n"
            "GuildModel reads only those. Bake a twin with Mirror.")
        self._act_guides = QAction("Guides", self, checkable=True, checked=True)
        self._act_guides.setToolTip(
            "Construction Guides: show the frontal angle and apical radius\n"
            "lines. Set them on the Guides tab.")
        self._act_snap   = QAction("Snap",   self, checkable=True, checked=True)
        self._act_snap.setToolTip("Snap: toggle node/handle snapping (hold Ctrl to suspend).")
        self._act_snap_palette = QAction("Snap\nTypes", self, checkable=True,
                                         checked=False)
        self._act_snap_palette.setToolTip(
            "Snap palette: choose WHICH targets snap (endpoint, midpoint,\n"
            "intersection, …) and set the snap radius. The Snap button stays\n"
            "the master on/off; holding Ctrl still suspends snapping.")
        self._act_grid = QAction("Grid", self, checkable=True, checked=False)
        self._act_grid.setToolTip(
            "Grid: show a millimeter grid overlay (spacing + divisions in\n"
            "Preferences ▸ Appearance). Enable the Grid snap in the snap\n"
            "palette to snap to its intersections.")
        self._act_smooth = QAction("Smooth\nHandles", self, checkable=True, checked=True)
        self._act_smooth.setToolTip(
            "Smooth Handles: when checked, moving one Bézier handle mirrors "
            "the opposite handle through the node (tangent-lock)."
        )
        self._act_boxing = QAction("Boxing", self, checkable=True, checked=True)
        self._act_boxing.setToolTip(
            "Boxing Guide: show the A × B lens boxes and the DBL between them\n"
            "as a dashed overlay. Set A, B and DBL on the Guides tab."
        )
        self._act_stock = QAction("Stock", self, checkable=True, checked=False)
        self._act_stock.setToolTip(
            "Stock Guide: show raw blank stock size as a dashed green rectangle centered at origin.\n"
            "On the temples it carries the core line at y = 0, where the wire runs.\n"
            "GuildModel centers its blank on the origin and places the part as drawn;\n"
            "the readiness dot warns when the OUTLINE leaves the guide.\n"
            "Set its size on the Guides tab; new designs start at the size in\n"
            "Preferences ▸ General."
        )
        self._act_pad = QAction("Pad", self, checkable=True, checked=False)
        self._act_pad.setToolTip(
            "Pad Guide: show the pad block as a dashed purple rectangle centered\n"
            "on the origin. Set its size on the Guides tab; new designs start at\n"
            "the size in Preferences ▸ General."
        )
        self._act_obverse = QAction("View\nObverse", self, checkable=True,
                                    checked=False)
        self._act_obverse.setToolTip(
            "View Obverse: see the drawing from its other face, mirrored left\n"
            "to right. A front is drawn facing the anterior, as its photo is; a\n"
            "temple from the posterior, the skin side, so engraved text reads.\n"
            "The badge in the canvas corner names the face toward you. A view\n"
            "only: snapping, the file and every export keep the drawing as drawn.")
        tb.addAction(self._act_mirror)
        tb.addAction(self._act_guides)
        tb.addAction(self._act_snap)
        tb.addAction(self._act_snap_palette)
        tb.addAction(self._act_grid)
        tb.addAction(self._act_smooth)
        tb.addAction(self._act_boxing)
        tb.addAction(self._act_stock)
        tb.addAction(self._act_pad)
        tb.addAction(self._act_obverse)

        tb.addSeparator()

        self._act_mirror_close = QAction("Mirror\nClose", self)
        self._act_mirror_close.setToolTip(
            "Mirror Close: join the selected open half to its mirror image in\n"
            "one closed shape. Its two ends move onto the mirror axis."
        )
        self._act_mirror_close.triggered.connect(self._copy_across_mirror)
        tb.addAction(self._act_mirror_close)

        self._act_dup_mirror = QAction("Mirror", self)
        self._act_dup_mirror.setToolTip(
            "Mirror: bake the Ghost, making real mirrored copies of the\n"
            "selected curves across the axis. A curve whose twin is drawn\n"
            "already, or would lie on itself, is skipped. Join or Mirror Close\n"
            "then connects halves into closed shapes."
        )
        self._act_dup_mirror.triggered.connect(self._on_duplicate_mirror)
        tb.addAction(self._act_dup_mirror)

        self._act_copy_temple = QAction("Temple\nCopy", self)
        self._act_copy_temple.setToolTip(
            "Temple Copy: send a mirrored copy of this temple's content into\n"
            "the other temple workspace (R → L or L → R).\n"
            "Asks for confirmation — it replaces everything in the target\n"
            "workspace (Ctrl+Z there restores it)."
        )
        self._act_copy_temple.setVisible(False)  # shown only in temple_r / temple_l
        self._act_copy_temple.triggered.connect(self._copy_temple_to_other)
        tb.addAction(self._act_copy_temple)

        self._act_join = QAction("Join", self)
        self._act_join.setToolTip(
            "Join: merge 2+ selected open curves into one curve by connecting "
            "their nearest endpoints (within 2 mm).\n"
            "Result is closed if the chain's ends also meet."
        )
        self._act_join.triggered.connect(self._join_selected_curves)
        tb.addAction(self._act_join)

        self._act_snap_ep = QAction("Snap\nNode", self)
        self._act_snap_ep.setEnabled(False)
        self._act_snap_ep.setToolTip(
            "Snap Node to Endpoint (E):\n"
            "Move the selected node (red) to the nearest endpoint of any other open curve.\n"
            "Select a curve, click a node to turn it red, then press this button."
        )
        self._act_snap_ep.triggered.connect(self._snap_selected_node_to_endpoint)
        tb.addAction(self._act_snap_ep)

        self._act_split = QAction("Split", self)
        self._act_split.setEnabled(False)
        self._act_split.setToolTip(
            "Split: break a curve at the selected node (red) into two open curves.\n"
            "For a closed curve, splitting produces one open curve.\n"
            "Select a curve, click a node to turn it red, then press Split."
        )
        self._act_split.triggered.connect(self._split_at_node)
        tb.addAction(self._act_split)

        self._act_explode = QAction("Explode", self)
        self._act_explode.setEnabled(False)
        self._act_explode.setToolTip(
            "Explode: break selected curve(s) into individual 2-node segments.\n"
            "Each segment preserves the original handles (spline shapes intact)."
        )
        self._act_explode.triggered.connect(self._explode_selected)
        tb.addAction(self._act_explode)

        self._act_fit = QAction("Fit", self)
        self._act_fit.setToolTip("Fit (Ctrl+0): zoom to the drawing.")
        self._act_fit.triggered.connect(self._fit_view)
        tb.addAction(self._act_fit)

        # The tooltip switch: a ? at the foot of the bar, outside the
        # customizable set and out of the ⋯ overflow's reach, as GuildModel's
        # sits at the end of its toolbar. Its own tooltip shows even when
        # tooltips are off, or nobody could find out what it does.
        self._act_tooltips = QAction("Tooltips", self, checkable=True)
        self._act_tooltips.setChecked(bool(self._prefs.get("tooltips", True)))
        self._act_tooltips.toggled.connect(self._on_tooltips_toggled)
        # The readiness dot is color only: its reason is its tooltip, so the
        # tooltip switch never silences it (as the ? button's own).
        self._tooltip_filter.set_exempt([tb.set_trailing_action(self._act_tooltips),
                                         self._readiness_dot])
        self._on_tooltips_toggled(self._act_tooltips.isChecked(), announce=False)

        # Map prefs keys → QAction objects (used by visibility and hotkey systems)
        self._toolbar_actions: dict[str, QAction] = {
            "select":       self._act_select,
            "line":         self._act_line,
            "spline":       self._act_spline,
            "circle":       self._act_circle,
            "arc":          self._act_arc,
            "arc_sec":      self._act_arc_sec,
            "fillet":       self._act_fillet,
            "dim":          self._act_dim,
            "trim":         self._act_trim,
            "split_curve":  self._act_split_curve,
            "offset":       self._act_offset,
            "rebuild":      self._act_rebuild,
            "point_move":   self._act_point_move,
            "text":         self._act_text,
            "ghost":        self._act_mirror,
            "guides":       self._act_guides,
            "snap":         self._act_snap,
            "snap_palette": self._act_snap_palette,
            "grid":         self._act_grid,
            "smooth":       self._act_smooth,
            "boxing":       self._act_boxing,
            "stock":        self._act_stock,
            "pad":          self._act_pad,
            "obverse":      self._act_obverse,
            "mirror":       self._act_dup_mirror,
            "mirror_close": self._act_mirror_close,
            "copy_temple":  self._act_copy_temple,
            "join":         self._act_join,
            "snap_node":    self._act_snap_ep,
            "split":        self._act_split,
            "explode":      self._act_explode,
            "fit":          self._act_fit,
        }

    # ------------------------------------------------------------------
    # Side panel (dock)
    # ------------------------------------------------------------------

    def _build_side_panel(self):
        self._prop_dock = QDockWidget("Properties", self)
        self._prop_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self._prop_dock.setTitleBarWidget(QWidget())
        self._prop_dock.setMinimumWidth(_DOCK_WIDTH)

        tabs = QTabWidget()
        tabs.tabBar().setExpanding(False)
        # Every section folds under its header, as GuildModel's dock does
        # (Road to 2.0, item 5); prefs["dock_folds"] remembers the ones the
        # maker turned from how they open.
        self._folds: dict[str, CollapsibleBox] = {}
        self._fold_defaults: dict[str, bool] = {}

        # ── Tab 0: Curve ──────────────────────────────────────────────────
        curve_w = QWidget()
        curve_lay = QVBoxLayout(curve_w)
        curve_lay.setContentsMargins(8, 8, 8, 8)
        curve_lay.setSpacing(12)

        draw_box = self._fold_box("Drawing")
        draw_lay = QFormLayout(draw_box.body)
        draw_lay.setSpacing(6)

        self._weight_spin = QDoubleSpinBox()
        self._weight_spin.setRange(0.25, 10.0)
        self._weight_spin.setDecimals(2)
        self._weight_spin.setSingleStep(0.25)
        self._weight_spin.setValue(1.5)
        # Commit on Enter/blur, not per keystroke — each change pushes an
        # undo snapshot, so typing "2.5" must not create three undo steps.
        self._weight_spin.setKeyboardTracking(False)
        self._weight_spin.setSuffix(" px")
        self._weight_spin.valueChanged.connect(self._on_weight_spin_changed)
        draw_lay.addRow("Line weight:", self._weight_spin)

        curve_lay.addWidget(draw_box)

        # ── Layers (the single home for everything layer-related) ─────────
        from PySide6.QtWidgets import QHeaderView
        layers_box = self._fold_box("Layers")
        layers_lay = QVBoxLayout(layers_box.body)
        layers_lay.setContentsMargins(4, 4, 4, 4)

        self._layer_tree = LayerTree()
        self._layer_tree.setHeaderHidden(True)
        self._layer_tree.setColumnCount(3)
        hdr = self._layer_tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._layer_tree.setColumnWidth(1, 28)
        self._layer_tree.setColumnWidth(2, 28)
        self._layer_tree.setMinimumHeight(170)
        self._layer_tree.setToolTip(
            "Layers and the objects on them.\n"
            "Click a layer name to make it the active drawing layer (bold).\n"
            "Click the eye to show/hide; hidden layers offer no snap targets.\n"
            "Click the padlock to lock/unlock; locked layers stay visible and\n"
            "snappable but cannot be selected or modified.\n"
            "Click an object to select it on the canvas; Ctrl/Shift-click\n"
            "for several, then Delete removes them.\n"
            "Drag an object onto another layer to move it there.\n"
            "Right-click for: select all on layer, move selection to layer."
        )
        self._layer_tree_expanded: dict = {}    # ws_type -> {Layer: bool}
        self._layer_tree.itemClicked.connect(self._on_layer_tree_clicked)
        self._layer_tree.itemExpanded.connect(
            lambda it: self._on_layer_row_expanded(it, True))
        self._layer_tree.itemCollapsed.connect(
            lambda it: self._on_layer_row_expanded(it, False))
        self._layer_tree.itemSelectionChanged.connect(
            self._on_layer_tree_selection_changed)
        self._layer_tree.curves_dropped.connect(self._on_layer_tree_drop)
        self._layer_tree.delete_requested.connect(self._delete_selected)
        self._layer_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._layer_tree.customContextMenuRequested.connect(
            self._on_layer_tree_menu)
        layers_lay.addWidget(self._layer_tree)
        # The tree takes the panel's spare height: it scrolled with a quarter
        # of the panel empty below Measurements.
        curve_lay.addWidget(layers_box, 1)

        # ── Measurements: Frame Front ──────────────────────────────────────
        meas_front_box = self._fold_box("Measurements", key="Measurements · front")
        meas_front_lay = QFormLayout(meas_front_box.body)
        meas_front_lay.setSpacing(6)

        self._meas_frame_width_lbl = QLabel("—")
        meas_front_lay.addRow("Frame width:", self._meas_frame_width_lbl)

        self._meas_frame_height_lbl = QLabel("—")
        meas_front_lay.addRow("Frame height:", self._meas_frame_height_lbl)

        self._meas_dbl_lbl = QLabel("—")
        meas_front_lay.addRow("DBL:", self._meas_dbl_lbl)

        self._meas_od_a_lbl  = QLabel("—")
        self._meas_od_b_lbl  = QLabel("—")
        self._meas_od_ed_lbl = QLabel("—")
        meas_front_lay.addRow("OD A:", self._meas_od_a_lbl)
        meas_front_lay.addRow("OD B:", self._meas_od_b_lbl)
        meas_front_lay.addRow("OD ED:", self._meas_od_ed_lbl)

        self._meas_os_a_lbl  = QLabel("—")
        self._meas_os_b_lbl  = QLabel("—")
        self._meas_os_ed_lbl = QLabel("—")
        meas_front_lay.addRow("OS A:", self._meas_os_a_lbl)
        meas_front_lay.addRow("OS B:", self._meas_os_b_lbl)
        meas_front_lay.addRow("OS ED:", self._meas_os_ed_lbl)
        for lbl in (self._meas_od_ed_lbl, self._meas_os_ed_lbl):
            lbl.setToolTip("Effective diameter: twice the longest radius from "
                           "the boxing center, on the finished lens.")

        # No Refresh button: every document change, node drag and layer move
        # refreshes these (the 2026-09-29 review checked each path).

        curve_lay.addWidget(meas_front_box)
        self._meas_front_box = meas_front_box

        # ── Measurements: Temple ───────────────────────────────────────────
        meas_temple_box = self._fold_box("Measurements", key="Measurements · temple")
        meas_temple_lay = QFormLayout(meas_temple_box.body)
        meas_temple_lay.setSpacing(6)

        self._meas_temple_length_lbl = QLabel("—")
        meas_temple_lay.addRow("Temple length:", self._meas_temple_length_lbl)

        self._meas_endpiece_lbl = QLabel("—")
        meas_temple_lay.addRow("Endpiece width:", self._meas_endpiece_lbl)

        curve_lay.addWidget(meas_temple_box)
        self._meas_temple_box = meas_temple_box

        curve_lay.addStretch()
        # Scrolled like Guides and Canvas: unscrolled, this tab and Library
        # held the window at 619 px or taller, and on a short laptop panel the
        # status bar and the ? fell off the screen.
        tabs.addTab(SettingsDialog._scrolled(curve_w), "Properties")

        # ── Tab 1: Guides (scrollable) ────────────────────────────────────
        guides_inner = QWidget()
        guides_lay = QVBoxLayout(guides_inner)
        guides_lay.setContentsMargins(8, 8, 8, 8)
        guides_lay.setSpacing(12)

        guide_box = self._fold_box("Construction (Forming)")
        guide_lay = QFormLayout(guide_box.body)
        guide_lay.setSpacing(6)

        from .construction import ConstructionGuides as _CG
        self._bridge_angle_spin = QDoubleSpinBox()
        self._bridge_angle_spin.setRange(0, 45)
        self._bridge_angle_spin.setSuffix("°")
        self._bridge_angle_spin.setSingleStep(0.5)
        self._bridge_angle_spin.setValue(_CG.DEFAULT_BRIDGE_ANGLE_DEG)
        # lambdas so each call dispatches to the CURRENT active workspace's guides
        self._bridge_angle_spin.valueChanged.connect(
            lambda v: self._guides.set_bridge_angle(v))
        # bridge angle + apical radius persist in the file (forming metadata)
        self._bridge_angle_spin.valueChanged.connect(
            lambda _: self._mark_dirty())
        guide_lay.addRow("Frontal angle:", self._bridge_angle_spin)

        self._apical_spin = QDoubleSpinBox()
        self._apical_spin.setRange(2.0, 24.0)
        self._apical_spin.setSuffix(" mm")
        self._apical_spin.setSingleStep(0.5)
        self._apical_spin.setValue(_CG.DEFAULT_APICAL_RADIUS_MM)
        self._apical_spin.valueChanged.connect(
            lambda v: self._guides.set_apical_radius(v))
        self._apical_spin.valueChanged.connect(
            lambda _: self._mark_dirty())
        guide_lay.addRow("Apical radius:", self._apical_spin)

        self._guide_crest_height_spin = QDoubleSpinBox()
        self._guide_crest_height_spin.setRange(-50.0, 50.0)
        self._guide_crest_height_spin.setSuffix(" mm")
        self._guide_crest_height_spin.setSingleStep(0.5)
        self._guide_crest_height_spin.setValue(0.0)
        self._guide_crest_height_spin.setToolTip(
            "Height of the crest, the apical arc's top, above the datum line: "
            "positive above it, negative below, as the optical convention "
            "measures it.")
        self._guide_crest_height_spin.valueChanged.connect(
            lambda v: self._guides.set_crest_height(v))
        self._guide_crest_height_spin.valueChanged.connect(self._guide_edited)
        guide_lay.addRow("Crest height:", self._guide_crest_height_spin)

        self._guide_spread_spin = QDoubleSpinBox()
        self._guide_spread_spin.setRange(0.0, 100.0)
        self._guide_spread_spin.setSuffix(" mm")
        self._guide_spread_spin.setSingleStep(0.5)
        self._guide_spread_spin.setValue(4.0)
        self._guide_spread_spin.setToolTip(
            "Half the crest's width: from the mirror axis to each arm's pivot. "
            "0 = both arms meet at the arc's top; the apical radius = the arms "
            "start at the arc's quadrants.")
        self._guide_spread_spin.valueChanged.connect(
            lambda v: self._guides.set_spread(v))
        self._guide_spread_spin.valueChanged.connect(self._guide_edited)
        guide_lay.addRow("Crest width:", self._guide_spread_spin)

        self._guide_drop_spin = QDoubleSpinBox()
        self._guide_drop_spin.setRange(-50.0, 100.0)
        self._guide_drop_spin.setSuffix(" mm")
        self._guide_drop_spin.setSingleStep(0.5)
        self._guide_drop_spin.setValue(0.0)
        self._guide_drop_spin.setToolTip(
            "How far below the arc's top the arms' pivots sit (0 = at the top). "
            "The apical radius starts the arms at the arc's quadrants.")
        self._guide_drop_spin.valueChanged.connect(
            lambda v: self._guides.set_pivot_y(v))
        self._guide_drop_spin.valueChanged.connect(self._guide_edited)
        guide_lay.addRow("Angle height:", self._guide_drop_spin)

        guides_lay.addWidget(guide_box)
        self._construction_guide_box = guide_box   # ref for section show/hide

        boxing_box = self._fold_box("Boxing System")
        boxing_lay = QFormLayout(boxing_box.body)
        boxing_lay.setSpacing(6)

        # A and B share a chain (aspect-link) toggle that spans both rows.
        # keyboardTracking off → a typed value commits on Enter/blur (not every
        # digit), and stepping commits instantly — so locked-resize fires once
        # per real change instead of mid-typing.
        self._boxing_a_spin = QDoubleSpinBox()
        self._boxing_a_spin.setRange(0.0, 120.0)   # wide: read-outs too
        self._boxing_a_spin.setSuffix(" mm")
        self._boxing_a_spin.setSingleStep(0.5)
        self._boxing_a_spin.setDecimals(1)
        self._boxing_a_spin.setKeyboardTracking(False)
        self._boxing_a_spin.setValue(50.0)
        self._boxing_a_spin.valueChanged.connect(self._on_boxing_a_value)

        self._boxing_b_spin = QDoubleSpinBox()
        self._boxing_b_spin.setRange(0.0, 100.0)
        self._boxing_b_spin.setSuffix(" mm")
        self._boxing_b_spin.setSingleStep(0.5)
        self._boxing_b_spin.setDecimals(1)
        self._boxing_b_spin.setKeyboardTracking(False)
        self._boxing_b_spin.setValue(30.0)
        self._boxing_b_spin.valueChanged.connect(self._on_boxing_b_value)

        self._chain_btn = QToolButton()
        self._chain_btn.setCheckable(True)
        self._chain_btn.setIcon(_make_icon(
            "link-chain", theme.color("chrome.ink"),
            theme.color("chrome.checked_ink")))
        self._chain_btn.setToolTip(
            "Link A and B: while locked, resizing one scales the other to keep\n"
            "the lens aspect ratio. Off = resize A and B independently.")
        self._chain_btn.toggled.connect(self._on_chain_toggled)

        ab_w = QWidget()
        ab_grid = QGridLayout(ab_w)
        ab_grid.setContentsMargins(0, 0, 0, 0)
        ab_grid.setHorizontalSpacing(6)
        ab_grid.setVerticalSpacing(6)
        ab_grid.addWidget(QLabel("A (width):"), 0, 0)
        ab_grid.addWidget(self._boxing_a_spin,  0, 1)
        ab_grid.addWidget(QLabel("B (height):"), 1, 0)
        ab_grid.addWidget(self._boxing_b_spin,  1, 1)
        ab_grid.addWidget(self._chain_btn,      0, 2, 2, 1)
        ab_grid.setColumnStretch(1, 1)
        boxing_lay.addRow(ab_w)

        self._boxing_dbl_spin = QDoubleSpinBox()
        self._boxing_dbl_spin.setRange(0.0, 60.0)
        self._boxing_dbl_spin.setSuffix(" mm")
        self._boxing_dbl_spin.setSingleStep(0.5)
        self._boxing_dbl_spin.setDecimals(1)
        # As A and B: with the lens locked every value moves the lenses (and
        # pushes an undo step), so typing 17.5 went through 17 and was then
        # rewritten mid-typing to "17.0 mm", dropping the ".5".
        self._boxing_dbl_spin.setKeyboardTracking(False)
        self._boxing_dbl_spin.setValue(18.0)
        self._boxing_dbl_spin.valueChanged.connect(self._on_boxing_dbl_value)
        boxing_lay.addRow("DBL:", self._boxing_dbl_spin)

        # ── Snap / Lock to lens + bevel (M11/M12) ───────────────────────
        self._boxing_snap_chk = QCheckBox("Snap to lens shape")
        self._boxing_snap_chk.setToolTip(
            "Fit the boxing box + bevel outline to the actual LENS path.\n"
            "A/B/DBL then show the live finished-lens measurements; editing\n"
            "or moving the lens updates them in real time.")
        self._boxing_snap_chk.toggled.connect(self._on_boxing_snap_toggled)
        boxing_lay.addRow(self._boxing_snap_chk)

        self._lock_shape_chk = QCheckBox("Lock lens shape")
        self._lock_shape_chk.setEnabled(False)   # only available once snapped
        self._lock_shape_chk.setToolTip(
            "Freeze the lens spline: it can still be moved (changing DBL), but\n"
            "its size changes only by typing new A / B values, which restretch\n"
            "the shape accurately. Draw once, offer many sizes.")
        self._lock_shape_chk.toggled.connect(self._on_lock_shape_toggled)
        boxing_lay.addRow(self._lock_shape_chk)

        self._outline_lock_chk = QCheckBox("Lock outline to lens")
        self._outline_lock_chk.setEnabled(False)   # only while the shape is locked
        self._outline_lock_chk.setToolTip(
            "Co-resize the frame OUTLINE with the lens, keeping a constant\n"
            "eyewire wall (flats and corners preserved). Open outlines grow\n"
            "from the bridge side; closed (finished) frames grow symmetrically.")
        self._outline_lock_chk.toggled.connect(self._on_outline_lock_toggled)
        boxing_lay.addRow(self._outline_lock_chk)

        self._bevel_combo = QComboBox()
        # (label, preset-key) — order matches the BEVEL_PRESETS intent
        self._bevel_choices = [
            ("Flat / Rimless", "flat"),
            ("Horn / Metal",   "horn_metal"),
            ("Acetate",        "acetate"),
            ("Custom",         "custom"),
        ]
        for label, _key in self._bevel_choices:
            self._bevel_combo.addItem(label)
        self._bevel_combo.setCurrentIndex(2)   # Acetate
        self._bevel_combo.currentIndexChanged.connect(self._on_bevel_preset_changed)
        boxing_lay.addRow("Bevel:", self._bevel_combo)

        self._bevel_depth_spin = QDoubleSpinBox()
        self._bevel_depth_spin.setRange(0.0, 5.0)
        self._bevel_depth_spin.setSuffix(" mm")
        self._bevel_depth_spin.setSingleStep(0.1)
        self._bevel_depth_spin.setDecimals(2)
        self._bevel_depth_spin.setValue(BEVEL_PRESETS["acetate"])
        self._bevel_depth_spin.setEnabled(False)   # only editable for Custom
        self._bevel_depth_spin.setToolTip(
            "Outward offset of the finished (beveled) lens beyond the lens shape.")
        self._bevel_depth_spin.valueChanged.connect(self._on_bevel_depth_changed)
        boxing_lay.addRow("Bevel depth:", self._bevel_depth_spin)

        guides_lay.addWidget(boxing_box)
        self._boxing_guide_box = boxing_box   # ref for section show/hide

        stock_box = self._fold_box("Stock Blank")
        stock_lay = QFormLayout(stock_box.body)
        stock_lay.setSpacing(6)

        self._stock_w_spin = QDoubleSpinBox()
        self._stock_w_spin.setRange(5.0, 400.0)
        self._stock_w_spin.setSuffix(" mm")
        self._stock_w_spin.setSingleStep(1.0)
        self._stock_w_spin.setValue(170.0)
        self._stock_w_spin.setToolTip(
            "Width of raw stock blank (mm). Toggle visibility with the Stock button.\n"
            "The readiness dot warns when the OUTLINE leaves the guide.")
        self._stock_w_spin.valueChanged.connect(self._on_stock_width_changed)
        stock_lay.addRow("Width:", self._stock_w_spin)

        self._stock_h_spin = QDoubleSpinBox()
        self._stock_h_spin.setRange(5.0, 200.0)
        self._stock_h_spin.setSuffix(" mm")
        self._stock_h_spin.setSingleStep(1.0)
        self._stock_h_spin.setValue(85.0)
        self._stock_h_spin.setToolTip("Height of raw stock blank (mm).")
        self._stock_h_spin.valueChanged.connect(self._on_stock_height_changed)
        stock_lay.addRow("Height:", self._stock_h_spin)

        guides_lay.addWidget(stock_box)
        self._stock_guide_box = stock_box   # ref for section show/hide

        pad_box = self._fold_box("Pad Block")
        pad_lay = QFormLayout(pad_box.body)
        pad_lay.setSpacing(6)

        self._pad_w_spin = QDoubleSpinBox()
        self._pad_w_spin.setRange(10.0, 200.0)
        self._pad_w_spin.setSuffix(" mm")
        self._pad_w_spin.setSingleStep(0.5)
        self._pad_w_spin.setValue(45.0)
        self._pad_w_spin.setToolTip("Width of pad block (mm). Toggle visibility with the Pad button.")
        self._pad_w_spin.valueChanged.connect(
            lambda v: self._on_pad_size_changed(width=v))
        pad_lay.addRow("Width:", self._pad_w_spin)

        self._pad_h_spin = QDoubleSpinBox()
        self._pad_h_spin.setRange(10.0, 200.0)
        self._pad_h_spin.setSuffix(" mm")
        self._pad_h_spin.setSingleStep(0.5)
        self._pad_h_spin.setValue(45.0)
        self._pad_h_spin.setToolTip("Height of pad block (mm).")
        self._pad_h_spin.valueChanged.connect(
            lambda v: self._on_pad_size_changed(height=v))
        pad_lay.addRow("Height:", self._pad_h_spin)

        guides_lay.addWidget(pad_box)
        self._pad_guide_box = pad_box   # ref for section show/hide

        # ── Frame Fill (display-only render overlay, M8) ─────────────────
        fill_box = self._fold_box("Frame Fill")
        fill_lay = QFormLayout(fill_box.body)
        fill_lay.setSpacing(6)

        self._fill_show_chk = QCheckBox("Show fill")
        self._fill_show_chk.setToolTip(
            "Fill the frame interior (OUTLINE minus LENS apertures) with a\n"
            "translucent color over the face photo. Display-only — never\n"
            "exported to DXF/SVG geometry."
        )
        self._fill_show_chk.toggled.connect(self._on_fill_visible_toggled)
        fill_lay.addRow(self._fill_show_chk)

        # Color or material swatch. A supplier's acetate sample sheet scaled
        # onto the blank shows the frame in the material it will be cut from —
        # the thing a flat color can't do for a laminate or a tortoise.
        self._fill_style_combo = QComboBox()
        self._fill_style_combo.addItem("Color", "color")
        self._fill_style_combo.addItem("Image",  "image")
        self._fill_style_combo.setToolTip(
            "Color: a flat translucent tint.\n"
            "Image: a material swatch, scaled to span the Stock Blank width\n"
            "and centered on the origin — the piece of sheet under the frame."
        )
        self._fill_style_combo.currentIndexChanged.connect(
            self._on_fill_style_changed)
        fill_lay.addRow("Style:", self._fill_style_combo)

        self._fill_color_btn = QPushButton("Color…")
        self._fill_color_btn.clicked.connect(self._on_fill_color_clicked)
        self._update_fill_swatch("#2a6099")
        fill_lay.addRow("Color:", self._fill_color_btn)

        self._swatch_btn_texts: dict = {}   # image button -> its full label
        img_row, self._fill_image_btn, self._fill_image_clear_btn = (
            self._swatch_row(self._on_fill_image_clicked,
                             self._on_fill_image_cleared,
                             "Forget the swatch and go back to the color."))
        fill_lay.addRow("Image:", img_row)

        self._fill_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_opacity_slider.setRange(0, 100)
        self._fill_opacity_slider.setValue(50)
        self._fill_opacity_slider.valueChanged.connect(self._on_fill_opacity_changed)
        self._fill_opacity_slider.setToolTip(
            "How much the fill covers what is behind it, the face photo among "
            "them. A swatch image is shown at this opacity too.")
        fill_lay.addRow("Opacity:", _slider_row(self._fill_opacity_slider,
                                                lambda v: f"{v}%"))

        guides_lay.addWidget(fill_box)
        self._fill_box = fill_box   # ref for section show/hide

        # ── Inlay Fill (display-only render overlay, Road to 2.0 item 7) ──
        inlay_box = self._fold_box("Inlay Fill")
        inlay_lay = QFormLayout(inlay_box.body)
        inlay_lay.setSpacing(6)

        self._inlay_fill_show_chk = QCheckBox("Show inlay fill")
        self._inlay_fill_show_chk.setToolTip(
            "Fill each closed INLAY body with a color or an image, over the\n"
            "frame fill: an inlay sits on the anterior. Display-only — never\n"
            "exported to DXF/SVG geometry."
        )
        self._inlay_fill_show_chk.toggled.connect(
            self._on_inlay_fill_visible_toggled)
        inlay_lay.addRow(self._inlay_fill_show_chk)

        self._inlay_fill_style_combo = QComboBox()
        self._inlay_fill_style_combo.addItem("Color", "color")
        self._inlay_fill_style_combo.addItem("Image", "image")
        self._inlay_fill_style_combo.setToolTip(
            "Color: a flat tint.\n"
            "Image: a photo of the material (a turquoise stone, a shell, a\n"
            "wood), scaled to cover each body and centered on it."
        )
        self._inlay_fill_style_combo.currentIndexChanged.connect(
            self._on_inlay_fill_style_changed)
        inlay_lay.addRow("Style:", self._inlay_fill_style_combo)

        self._inlay_fill_color_btn = QPushButton("Color…")
        self._inlay_fill_color_btn.clicked.connect(
            self._on_inlay_fill_color_clicked)
        self._update_inlay_fill_swatch(DEFAULT_INLAY_FILL_COLOR)
        inlay_lay.addRow("Color:", self._inlay_fill_color_btn)

        inlay_img_row, self._inlay_fill_image_btn, self._inlay_fill_image_clear_btn = (
            self._swatch_row(self._on_inlay_fill_image_clicked,
                             self._on_inlay_fill_image_cleared,
                             "Forget the image and go back to the color."))
        inlay_lay.addRow("Image:", inlay_img_row)

        self._inlay_fill_tumble_chk = QCheckBox("Tumble bodies")
        self._inlay_fill_tumble_chk.setToolTip(
            "Turn each body's copy of the image differently, so one photo\n"
            "reads as several stones; the same way each time the file opens.\n"
            "For an image on two or more closed INLAY bodies."
        )
        self._inlay_fill_tumble_chk.toggled.connect(
            self._on_inlay_fill_tumble_toggled)
        inlay_lay.addRow(self._inlay_fill_tumble_chk)

        self._inlay_fill_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._inlay_fill_opacity_slider.setRange(0, 100)
        self._inlay_fill_opacity_slider.setValue(
            round(DEFAULT_INLAY_FILL_OPACITY * 100))
        self._inlay_fill_opacity_slider.valueChanged.connect(
            self._on_inlay_fill_opacity_changed)
        self._inlay_fill_opacity_slider.setToolTip(
            "How much each inlay covers the frame fill and the photo behind it.")
        inlay_lay.addRow("Opacity:", _slider_row(self._inlay_fill_opacity_slider,
                                                 lambda v: f"{v}%"))

        guides_lay.addWidget(inlay_box)
        self._inlay_fill_box = inlay_box   # ref for section show/hide

        # ── Lens Fill (display-only render overlay, v1.2) ─────────────────
        lens_fill_box = self._fold_box("Lens Fill")
        lens_fill_lay = QFormLayout(lens_fill_box.body)
        lens_fill_lay.setSpacing(6)

        self._lens_fill_show_chk = QCheckBox("Show lens fill")
        self._lens_fill_show_chk.setToolTip(
            "Tint each LENS aperture with a vertical two-color gradient, the\n"
            "way a dyed lens runs dark to light. Display-only — never exported\n"
            "to DXF/SVG geometry."
        )
        self._lens_fill_show_chk.toggled.connect(self._on_lens_fill_visible_toggled)
        lens_fill_lay.addRow(self._lens_fill_show_chk)

        # Swatch-only buttons — the row label already says which stop it is, so
        # a "Top…" caption inside the button would only crowd the color bar.
        self._lens_top_btn = QPushButton()
        self._lens_top_btn.setIconSize(QSize(*_LENS_SWATCH_PX))
        self._lens_top_btn.clicked.connect(lambda: self._on_lens_fill_color_clicked("top"))
        self._lens_bottom_btn = QPushButton()
        self._lens_bottom_btn.setIconSize(QSize(*_LENS_SWATCH_PX))
        self._lens_bottom_btn.clicked.connect(lambda: self._on_lens_fill_color_clicked("bottom"))

        self._lens_top_bpi_btn = QToolButton()
        self._lens_top_bpi_btn.setText("BPI")
        self._lens_top_bpi_btn.setToolTip(
            "Pick the top color from the BPI tint reference.")
        self._lens_top_bpi_btn.clicked.connect(lambda: self._show_tint_picker("top"))
        self._lens_bottom_bpi_btn = QToolButton()
        self._lens_bottom_bpi_btn.setText("BPI")
        self._lens_bottom_bpi_btn.setToolTip(
            "Pick the bottom color from the BPI tint reference.")
        self._lens_bottom_bpi_btn.clicked.connect(lambda: self._show_tint_picker("bottom"))

        self._lens_link_btn = QToolButton()
        self._lens_link_btn.setCheckable(True)
        self._lens_link_btn.setIcon(_make_icon(
            "link-chain", theme.color("chrome.ink"),
            theme.color("chrome.checked_ink")))
        self._lens_link_btn.setToolTip(
            "Link top and bottom: while locked both stops stay the same color,\n"
            "so the lens takes a flat tint. Off = a true vertical gradient.")
        self._lens_link_btn.toggled.connect(self._on_lens_fill_link_toggled)

        lens_grid_w = QWidget()
        lens_grid = QGridLayout(lens_grid_w)
        lens_grid.setContentsMargins(0, 0, 0, 0)
        lens_grid.setHorizontalSpacing(6)
        lens_grid.setVerticalSpacing(6)
        lens_grid.addWidget(QLabel("Top:"),           0, 0)
        lens_grid.addWidget(self._lens_top_btn,       0, 1)
        lens_grid.addWidget(self._lens_top_bpi_btn,   0, 2)
        lens_grid.addWidget(QLabel("Bottom:"),        1, 0)
        lens_grid.addWidget(self._lens_bottom_btn,    1, 1)
        lens_grid.addWidget(self._lens_bottom_bpi_btn, 1, 2)
        lens_grid.addWidget(self._lens_link_btn,      0, 3, 2, 1)
        lens_grid.setColumnStretch(1, 1)
        lens_fill_lay.addRow(lens_grid_w)

        if not _bpi_tints.load_tints():
            # No shipped table (stripped build) — hide the entry points rather
            # than offering a picker with nothing in it.
            self._lens_top_bpi_btn.setVisible(False)
            self._lens_bottom_bpi_btn.setVisible(False)

        self._lens_fill_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self._lens_fill_intensity_slider.setRange(0, 100)
        self._lens_fill_intensity_slider.setValue(
            slider_from_intensity(DEFAULT_LENS_FILL_INTENSITY))
        self._lens_fill_intensity_slider.setToolTip(
            "How deeply the dye reads — the tint's own strength, as opposed to\n"
            "Opacity, which is how much of the drawing behind it shows through.\n\n"
            "Reference swatches (BPI's included) show a dye at one modest depth\n"
            "over white, so a color picked from one usually needs deepening to\n"
            "look like the lens you mean. The default sits a quarter along, at\n"
            "the color exactly as picked; drag right for a deeper dye.")
        self._lens_fill_intensity_slider.valueChanged.connect(
            self._on_lens_fill_intensity_changed)
        lens_fill_lay.addRow("Intensity:", _slider_row(
            self._lens_fill_intensity_slider,
            lambda v: f"×{intensity_from_slider(v):.2f}"))

        self._lens_fill_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._lens_fill_opacity_slider.setRange(0, 100)
        self._lens_fill_opacity_slider.setValue(
            int(round(DEFAULT_LENS_FILL_OPACITY * 100)))
        self._lens_fill_opacity_slider.setToolTip(
            "How much the tint covers what is behind it — the face photo, the\n"
            "frame fill. For the tint's own strength, use Intensity.")
        self._lens_fill_opacity_slider.valueChanged.connect(
            self._on_lens_fill_opacity_changed)
        lens_fill_lay.addRow("Opacity:", _slider_row(self._lens_fill_opacity_slider,
                                                     lambda v: f"{v}%"))

        guides_lay.addWidget(lens_fill_box)
        self._lens_fill_box = lens_fill_box   # ref for section show/hide
        self._update_lens_fill_swatches(DEFAULT_LENS_FILL_TOP,
                                        DEFAULT_LENS_FILL_BOTTOM,
                                        DEFAULT_LENS_FILL_INTENSITY)
        guides_lay.addStretch()

        guides_scroll = QScrollArea()
        guides_scroll.setWidgetResizable(True)
        guides_scroll.setFrameShape(guides_scroll.Shape.NoFrame)
        guides_scroll.setWidget(guides_inner)
        tabs.addTab(guides_scroll, "Guides")

        # ── Tab 2: Image (scrollable) ─────────────────────────────────────
        image_inner = QWidget()
        image_lay = QVBoxLayout(image_inner)
        image_lay.setContentsMargins(8, 8, 8, 8)
        image_lay.setSpacing(12)

        img_box = self._fold_box("Reference Images")
        img_vlay = QVBoxLayout(img_box.body)
        img_vlay.setSpacing(6)

        # Add / Locate / Remove buttons
        img_btn_row = QHBoxLayout()
        add_img_btn = QPushButton("Add Image…")
        add_img_btn.setToolTip(
            "Load a JPEG or PNG as a reference background layer. It stays "
            "where it is on this computer until you store it in the design "
            "(the paperclip).")
        # Not connected bare: clicked passes checked=False, which _add_face
        # took for its path, so the button opened no dialog and did nothing.
        add_img_btn.clicked.connect(lambda: self._add_face())
        self._locate_img_btn = QPushButton("Locate…")
        self._locate_img_btn.setEnabled(False)
        self._locate_img_btn.setToolTip(
            "Find the selected image on this computer: one the design does not "
            "store, opened on another computer or moved since.")
        self._locate_img_btn.clicked.connect(lambda: self._locate_face())
        self._remove_img_btn = QPushButton("Remove")
        self._remove_img_btn.setEnabled(False)
        self._remove_img_btn.setToolTip("Remove the selected reference image.")
        self._remove_img_btn.clicked.connect(self._remove_face)
        img_btn_row.addWidget(add_img_btn)
        img_btn_row.addWidget(self._locate_img_btn)
        img_btn_row.addWidget(self._remove_img_btn)
        img_vlay.addLayout(img_btn_row)

        # The images, as the Layers panel shows layers: name, eye, padlock,
        # and the paperclip of an image stored in the design.
        self._face_tree = QTreeWidget()
        self._face_tree.setHeaderHidden(True)
        self._face_tree.setRootIsDecorated(False)
        self._face_tree.setColumnCount(4)
        hdr = self._face_tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self._face_tree.setColumnWidth(col, 28)
        self._face_tree.setFixedHeight(96)
        # Fixed, not the tree's own Expanding: a fixed-height list that says
        # it expands made its section claim the tab's spare height as gaps.
        self._face_tree.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Fixed)
        self._face_tree.setToolTip(
            "Reference images, the last added on top.\n"
            "Click the eye to show or hide one; hidden, it is left out of PNG "
            "export and printing.\n"
            "Click the padlock to lock or unlock its place, turn and scale.\n"
            "Click the paperclip to store it in the design, so it shows on any "
            "computer that opens the file.")
        self._face_tree.currentItemChanged.connect(
            lambda cur, _prev: self._on_face_row_changed(
                self._face_tree.indexOfTopLevelItem(cur) if cur else -1))
        self._face_tree.itemClicked.connect(self._on_face_tree_clicked)
        img_vlay.addWidget(self._face_tree)

        # Per-image controls (disabled until an image is selected)
        img_ctrl_lay = QFormLayout()
        img_ctrl_lay.setSpacing(6)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(70)
        self._opacity_slider.setEnabled(False)
        self._opacity_slider.valueChanged.connect(self._on_face_opacity_changed)
        self._opacity_slider.setToolTip("How strongly the selected reference "
                                        "image shows under the drawing.")
        img_ctrl_lay.addRow("Opacity:", _slider_row(self._opacity_slider,
                                                    lambda v: f"{v}%"))

        self._rotation_spin = QDoubleSpinBox()
        self._rotation_spin.setRange(-180, 180)
        self._rotation_spin.setSuffix("°")
        self._rotation_spin.setSingleStep(0.5)
        self._rotation_spin.setEnabled(False)
        self._rotation_spin.valueChanged.connect(self._on_face_rotation_changed)
        self._rotation_spin.setToolTip(
            "Turn the selected image. Unlock it first (the padlock).")
        img_ctrl_lay.addRow("Rotation:", self._rotation_spin)
        img_vlay.addLayout(img_ctrl_lay)

        image_lay.addWidget(img_box)

        calib_box = self._fold_box("Calibration")
        calib_lay = QFormLayout(calib_box.body)
        calib_lay.setSpacing(6)

        self._calib_label = QLabel("Not set")
        # Wrapped: unwrapped, the no-image sentence made the Canvas tab 430 px
        # wide, past the dock's minimum, and the tab scrolled sideways.
        self._calib_label.setWordWrap(True)
        calib_lay.addRow("Status:", self._calib_label)

        calib_btn = QPushButton("Calibrate (2-point)…")
        calib_btn.setToolTip(
            "Click two landmarks on a reference image, then enter their real "
            "distance (mm): the image is scaled to match. Each image keeps its "
            "own calibration.")
        calib_btn.clicked.connect(self._start_calibration)
        calib_btn.setEnabled(False)          # until there is an image
        self._calib_btn = calib_btn
        calib_lay.addRow(calib_btn)

        self._pxmm_spin = QDoubleSpinBox()
        self._pxmm_spin.setRange(0.01, 9999.0)
        self._pxmm_spin.setDecimals(4)
        self._pxmm_spin.setSuffix(" px/mm")
        self._pxmm_spin.setValue(1.0)
        self._pxmm_spin.setEnabled(False)
        self._pxmm_spin.setToolTip(
            "The selected reference image's pixels per real millimeter: type "
            "it, or use the 2-point calibration above.")
        self._pxmm_spin.editingFinished.connect(self._apply_manual_calib)
        calib_lay.addRow("Scale:", self._pxmm_spin)

        image_lay.addWidget(calib_box)
        image_lay.addStretch()

        image_scroll = QScrollArea()
        image_scroll.setWidgetResizable(True)
        image_scroll.setFrameShape(image_scroll.Shape.NoFrame)
        image_scroll.setWidget(image_inner)
        tabs.addTab(image_scroll, "Canvas")

        # ── Tab 3: History ────────────────────────────────────────────────
        history_w = QWidget()
        history_lay = QVBoxLayout(history_w)
        history_lay.setContentsMargins(8, 8, 8, 8)
        history_lay.setSpacing(6)

        btn_add = QPushButton("Bookmark Current State…")
        btn_add.setToolTip(
            "Save a named snapshot of this tab's drawing as a revision point.\n"
            "Bookmarks are saved with the design; the hotkey adds one too.")
        btn_add.clicked.connect(self._add_bookmark)
        history_lay.addWidget(btn_add)
        history_lay.addWidget(SettingsDialog._hint(
            "Bookmarks are named snapshots of this tab's drawing, kept with the "
            "design. Double-click one to go back to it."))

        self._timeline_list = QListWidget()
        self._timeline_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._timeline_list.setAlternatingRowColors(True)
        self._timeline_list.setToolTip("Double-click a bookmark to restore that state.")
        self._timeline_list.itemDoubleClicked.connect(lambda _: self._restore_bookmark())
        self._timeline_list.itemSelectionChanged.connect(self._on_timeline_selection)
        history_lay.addWidget(self._timeline_list)

        btn_row = QHBoxLayout()
        self._btn_bm_restore = QPushButton("Restore")
        self._btn_bm_rename  = QPushButton("Rename…")
        self._btn_bm_delete  = QPushButton("Delete")
        for btn in (self._btn_bm_restore, self._btn_bm_rename, self._btn_bm_delete):
            btn.setEnabled(False)
            btn_row.addWidget(btn)
        self._btn_bm_restore.setToolTip("Restore the selected bookmark (adds an undo step)")
        self._btn_bm_restore.clicked.connect(self._restore_bookmark)
        self._btn_bm_rename.clicked.connect(self._rename_bookmark)
        self._btn_bm_delete.clicked.connect(self._delete_bookmark)
        history_lay.addLayout(btn_row)

        tabs.addTab(history_w, "History")

        # ── Tab 4: Library (Pockets / Holes) ──────────────────────────────
        lib_tabs = QTabWidget()
        pockets_w = QWidget()
        lib_lay = QVBoxLayout(pockets_w)
        lib_lay.setContentsMargins(8, 8, 8, 8)
        lib_lay.setSpacing(6)

        self._lib_tree = ComponentTree()
        self._lib_tree.setAlternatingRowColors(True)
        self._lib_tree.setToolTip(
            "The component library: folders of hinges, bridges and whatever "
            "else mounts on the posterior.\n"
            "Double-click or press Import to place one in the current workspace.\n"
            "On the Component tab, drag an entry into another folder, or a "
            "folder to reorder them."
        )
        self._lib_tree.itemSelectionChanged.connect(self._on_lib_selection_changed)
        self._lib_tree.itemDoubleClicked.connect(self._on_lib_double_clicked)
        self._lib_tree.entry_dropped.connect(self._move_library_entry)
        self._lib_tree.folders_reordered.connect(self._reorder_library_folders)
        lib_lay.addWidget(self._lib_tree)

        self._btn_lib_import = QPushButton("Import into Workspace")
        self._btn_lib_import.setEnabled(False)
        self._btn_lib_import.setToolTip(
            "Insert the selected component into this tab as one group,\n"
            "centered on the origin. GuildModel cuts its COMPONENT curves as\n"
            "pockets. They carry the folder's name too, which a later\n"
            "GuildModel will read to tell a bridge from a hinge."
        )
        self._btn_lib_import.clicked.connect(self._import_from_library)
        lib_lay.addWidget(self._btn_lib_import)

        # Component workspace only: the library is kept where its entries are
        # drawn.
        self._lib_component_actions = QWidget()
        comp_btn_lay = QVBoxLayout(self._lib_component_actions)
        comp_btn_lay.setContentsMargins(0, 4, 0, 0)
        comp_btn_lay.setSpacing(4)

        self._btn_lib_save = QPushButton("Save Current Component…")
        self._btn_lib_save.setToolTip(
            "Save this Component workspace's geometry to a library folder."
        )
        self._btn_lib_save.clicked.connect(self._save_to_library)
        comp_btn_lay.addWidget(self._btn_lib_save)

        comp_mgmt_row = QHBoxLayout()
        self._btn_lib_new_folder = QPushButton("New Folder…")
        self._btn_lib_new_folder.setToolTip(
            "A folder for one kind of component, such as Hinges or Bridges. A "
            "component placed from it carries the folder's name; a later "
            "GuildModel will read a name with \"hinge\" in it as a hinge, and "
            "any other as a mount.")
        self._btn_lib_new_folder.clicked.connect(self._new_library_folder)
        self._btn_lib_rename = QPushButton("Rename…")
        self._btn_lib_rename.setEnabled(False)
        self._btn_lib_rename.clicked.connect(self._rename_library_entry)
        self._btn_lib_delete = QPushButton("Delete")
        self._btn_lib_delete.setEnabled(False)
        self._btn_lib_delete.clicked.connect(self._delete_library_entry)
        comp_mgmt_row.addWidget(self._btn_lib_new_folder)
        comp_mgmt_row.addWidget(self._btn_lib_rename)
        comp_mgmt_row.addWidget(self._btn_lib_delete)
        comp_btn_lay.addLayout(comp_mgmt_row)

        self._btn_lib_move = QPushButton("Move to Folder…")
        self._btn_lib_move.setEnabled(False)
        self._btn_lib_move.setToolTip("Move the selected entry into another folder.")
        self._btn_lib_move.clicked.connect(self._move_library_entry_to_folder)
        comp_btn_lay.addWidget(self._btn_lib_move)

        lib_lay.addWidget(self._lib_component_actions)
        lib_lay.addStretch()
        lib_tabs.addTab(pockets_w, "Components")

        lib_tabs.addTab(self._build_holes_panel(), "Holes")
        self._lib_tabs = lib_tabs          # Holes is shown on the Frame Front only
        tabs.addTab(SettingsDialog._scrolled(lib_tabs), "Library")

        self._side_tabs = tabs
        self._side_tabs.currentChanged.connect(
            lambda idx: self._refresh_measurements() if idx == 0 else None)
        # The dock is as wide as its five tabs, with room for a two-digit
        # bookmark count on History and for the bold of the selected tab.
        # At the old 270 px floor the bar scrolled "Library" off the edge.
        bar = tabs.tabBar()
        bar.setObjectName("sideTabs")
        bar.style().unpolish(bar)                  # measure with its own padding
        bar.style().polish(bar)
        bar.setTabText(3, "History (99)")
        fit = bar.sizeHint().width() + 10
        bar.setTabText(3, "History")
        self._prop_dock.setMinimumWidth(max(_DOCK_WIDTH, fit))
        # Room for the canvas beside the dock: at the old minimum it was
        # 110 px wide next to a 350 px panel.
        self.setMinimumWidth(max(self._prop_dock.minimumWidth() + 480, 820))
        self._wheel_guard = _WheelGuard(self)
        self._wheel_guard.guard(tabs)
        self._set_fold_state(self._prefs.get("dock_folds"))
        self._prop_dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._prop_dock)

    def _fold_box(self, title: str, key: str | None = None) -> CollapsibleBox:
        """A dock section that folds under its header, registered under *key*
        (the title unless two sections share one) for prefs["dock_folds"].
        The caller lays out its ``body`` as it laid out a QGroupBox."""
        box = CollapsibleBox(title)
        key = key or title
        self._folds[key] = box
        self._fold_defaults[key] = box.is_expanded()
        return box

    def _fold_state(self) -> dict:
        """The sections folded or opened away from how they first open, by
        key — only those, so a section added later opens as it was built to,
        and a fold the maker never touched is not written down."""
        return {key: box.is_expanded() for key, box in self._folds.items()
                if box.is_expanded() != self._fold_defaults[key]}

    def _set_fold_state(self, state: dict | None):
        """Fold or open the sections *state* names; the rest as built."""
        state = state if isinstance(state, dict) else {}
        for key, box in self._folds.items():
            box.set_expanded(bool(state.get(key, self._fold_defaults[key])))

    # ------------------------------------------------------------------
    # Layers panel
    # ------------------------------------------------------------------

    def _schedule_layer_panel_refresh(self, ws: "WorkspaceState"):
        """Coalesce document-change notifications into one panel rebuild."""
        if ws is not self._active_ws:
            return
        if not self._layer_refresh_pending:
            self._layer_refresh_pending = True
            QTimer.singleShot(0, self, self._do_layer_panel_refresh)

    # What a fresh tab says until something is on it (CanvasView.set_empty_hint).
    _EMPTY_HINTS = {
        "front": ("Draw the frame's OUTLINE with Line or Spline, add a reference "
                  "photo (File ▸ Add Reference Image…), or open a design (Ctrl+O)."),
        "temple_r": ("Draw the temple's OUTLINE across the core line, or send the "
                     "other temple here with Temple Copy."),
        "temple_l": ("Draw the temple's OUTLINE across the core line, or send the "
                     "other temple here with Temple Copy."),
        "component": ("Draw a component on COMPONENT, a hinge's pocket or a "
                      "bridge, to save to the library."),
    }

    def _sync_empty_hint(self, ws: "WorkspaceState | None" = None):
        ws = ws or self._active_ws
        empty = not (ws.doc_curves or ws.doc_texts or ws.doc_dims
                     or ws.scene.face_count())
        ws.view.set_empty_hint(self._EMPTY_HINTS.get(ws.workspace_type)
                               if empty else None)

    def _do_layer_panel_refresh(self):
        self._layer_refresh_pending = False
        self._sync_empty_hint()
        self._apply_boxing_field_modes()          # Lock follows the lenses
        self._refresh_layer_panel()
        self._update_readiness()
        self._sync_inlay_tumble_enabled()   # follows the INLAY body count
        # Live measurements in the Properties tab track the geometry on every
        # document change (add/remove/undo/load) — no manual Refresh needed.
        self._refresh_measurements()
        # A snapped boxing guide also tracks the live lens geometry.
        if self._active_ws.boxing_snapped:
            self._active_ws.boxing_guide.refresh()
            self._sync_boxing_readouts()

    @staticmethod
    def _curve_label(c: Curve, group_no: int | None = None) -> str:
        """A Layers-panel row: the curve's kind and size, led by its group as
        a number in this tab ("group 2"), or by its component's kind
        ("Hinges 2"). The group's internal id meant nothing to the maker."""
        if c.kind in ("circle", "arc") and c.radius is not None:
            label = f"{c.kind}  r={c.radius:.1f}"
        else:
            label = f"{c.kind}  ·  {len(c.nodes)} nodes"
            if c.closed:
                label += "  (closed)"
        if c.component_kind or c.group_id:
            lead = c.component_kind or "group"
            label = (f"{lead} {group_no}" if group_no else lead) + "  ·  " + label
        return label

    @staticmethod
    def _text_label(t) -> str:
        """Layer-tree label for an engraving TextObject (re-editable, exported
        as outline paths at DXF time)."""
        s = t.text if len(t.text) <= 16 else t.text[:15] + "…"
        return f'text  ·  "{s}"'

    def _layer_icon(self, name: str) -> QIcon:
        """Theme-aware cached icon for the eye/padlock tree cells."""
        color = theme.color("chrome.ink")
        on_row = theme.color("chrome.checked_ink")     # a selected row's ink
        cache = getattr(self, "_layer_icon_cache", None)
        if cache is None:
            cache = self._layer_icon_cache = {}
        key = (name, color, on_row)
        if key not in cache:
            cache[key] = _make_icon(name, color, color, selected_color=on_row)
        return cache[key]

    def _refresh_layer_panel(self):
        """Full rebuild of the layer tree (document change / tab switch)."""
        ws   = self._active_ws
        tree = self._layer_tree
        expanded = self._layer_tree_expanded.setdefault(ws.workspace_type, {})
        tree.blockSignals(True)
        tree.clear()
        self._layer_tree_rows: dict = {}        # id(curve) -> row item
        self._layer_tree_text_rows: dict = {}   # id(TextObject) -> row item
        self._layer_tree_layer_rows: dict = {}  # Layer -> top-level row
        group_no: dict = {}                     # group id -> 1, 2, … in draw order
        for c in ws.doc_curves:
            if c.group_id and c.group_id not in group_no:
                group_no[c.group_id] = len(group_no) + 1
        from .tooltips import format_tooltip
        from PySide6.QtWidgets import QToolTip
        tip_metrics = QFontMetrics(QToolTip.font())
        for layer in WORKSPACE_LAYERS[ws.workspace_type]:
            curves = [c for c in ws.doc_curves if c.layer == layer]
            texts  = [t for t in ws.doc_texts if t.layer == layer]
            count  = len(curves) + len(texts)
            locked = ws.scene.is_layer_locked(layer)
            top = QTreeWidgetItem([f"{layer.value}  ({count})", "", ""])
            if layer in _LAYER_TIPS:
                # Wrapped as every other tip is: an item's own tip skips the
                # app's tooltip filter.
                top.setToolTip(0, format_tooltip(_LAYER_TIPS[layer], tip_metrics))
            top.setToolTip(1, f"Show or hide {layer.value}")
            top.setToolTip(2, f"Lock or unlock {layer.value}")
            top.setIcon(1, self._layer_icon(
                "layer-show" if ws.scene.is_layer_visible(layer) else "layer-hide"))
            top.setIcon(2, self._layer_icon(
                "layer-lock" if locked else "layer-unlock"))
            top.setData(0, Qt.ItemDataRole.UserRole, ("layer", layer))
            # Layer rows are drop targets, never drag sources.
            top.setFlags(Qt.ItemFlag.ItemIsEnabled
                         | Qt.ItemFlag.ItemIsSelectable
                         | Qt.ItemFlag.ItemIsDropEnabled)
            tree.addTopLevelItem(top)
            self._layer_tree_layer_rows[layer] = top
            # Curve rows are drag sources (unless their layer is locked),
            # never drop targets.
            child_flags = (Qt.ItemFlag.ItemIsEnabled
                           | Qt.ItemFlag.ItemIsSelectable)
            if not locked:
                child_flags |= Qt.ItemFlag.ItemIsDragEnabled
            for c in curves:
                child = QTreeWidgetItem(
                    [self._curve_label(c, group_no.get(c.group_id)), "", ""])
                child.setData(0, Qt.ItemDataRole.UserRole, ("curve", id(c)))
                child.setFlags(child_flags)
                top.addChild(child)
                self._layer_tree_rows[id(c)] = child
            # Engraving TextObjects live on their layer too.
            for t in texts:
                child = QTreeWidgetItem([self._text_label(t), "", ""])
                child.setData(0, Qt.ItemDataRole.UserRole, ("text", id(t)))
                child.setFlags(child_flags)
                top.addChild(child)
                self._layer_tree_text_rows[id(t)] = child
            # A layer the maker expanded or collapsed stays that way across
            # rebuilds (every document change rebuilds); otherwise auto.
            top.setExpanded(expanded.get(layer, bool(count) and count <= 12))
        tree.blockSignals(False)
        self._sync_layer_panel_active()
        # The rebuild dropped the row highlight; put the canvas selection back.
        self._sync_layer_panel_row()

    def _sync_layer_panel_row(self):
        """Highlight the row of a single selected curve/text (no rebuild)."""
        if self._syncing_selection:
            return
        sel = self.scene.selectedItems()
        rows = getattr(self, "_layer_tree_rows", {})
        trows = getattr(self, "_layer_tree_text_rows", {})
        row = None
        curves = [i for i in sel if isinstance(i, CurveItem)]
        texts  = [i for i in sel if isinstance(i, TextItem)]
        if len(curves) == 1 and not texts:
            row = rows.get(id(curves[0].curve))
        elif len(texts) == 1 and not curves:
            row = trows.get(id(texts[0].text_obj))
        if row is not None:
            self._syncing_selection = True
            try:
                self._layer_tree.setCurrentItem(row)
            finally:
                self._syncing_selection = False

    def _on_layer_row_expanded(self, item, expanded: bool):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "layer":
            per_ws = self._layer_tree_expanded.setdefault(
                self._active_ws.workspace_type, {})
            per_ws[data[1]] = expanded

    def _sync_layer_panel_active(self):
        """Bold the active layer row. No tree rebuild — safe inside handlers."""
        ws = self._active_ws
        for layer, top in getattr(self, "_layer_tree_layer_rows", {}).items():
            f = top.font(0)
            f.setBold(layer is ws.active_layer)
            top.setFont(0, f)

    def _set_active_layer(self, layer: Layer):
        """Make *layer* the drawing layer; live-update any active draw tool."""
        self._active_ws.active_layer = layer
        if self._draw_tool.active:
            self._draw_tool.set_layer(layer)
        if self._circle_tool.active:
            self._circle_tool.set_layer(layer)
        self._sync_layer_panel_active()
        self._update_info_label()
        self._status.showMessage(f"Active layer → {layer.value}")

    def _on_layer_tree_clicked(self, item, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind == "layer":
            layer = payload
            if column == 1:
                vis = not self.scene.is_layer_visible(layer)
                self.scene.set_layer_visible(layer, vis)
                item.setIcon(1, self._layer_icon(
                    "layer-show" if vis else "layer-hide"))
                self._mark_dirty()
            elif column == 2:
                locked = not self.scene.is_layer_locked(layer)
                self.scene.set_layer_locked(layer, locked)
                item.setIcon(2, self._layer_icon(
                    "layer-lock" if locked else "layer-unlock"))
                self._mark_dirty()
                # Child rows carry the drag flag per lock state — refresh it.
                self._refresh_layer_panel()
            else:
                self._set_active_layer(layer)
            return
        # Object rows: canvas selection is driven by the tree's own selection
        # (see _on_layer_tree_selection_changed), so a Ctrl/Shift multi-row
        # pick selects all those curves on canvas — across layers — which is
        # what Join / Mirror need.

    def _on_layer_tree_selection_changed(self):
        """Mirror the tree's selected object rows onto the canvas selection.

        Lets the maker multi-select curves in the panel (Ctrl/Shift) across
        different layers and then Join/Mirror them. The `_syncing_selection`
        guard stops this from fighting the canvas→tree row sync in
        `_on_selection_changed`. Scene signals are deliberately NOT blocked:
        each setSelected must reach EditTool (so node dots update) and the view
        (so the selection highlight repaints) — blocking them was why only a
        stale single curve appeared highlighted."""
        if self._syncing_selection:
            return
        ids, text_ids = [], []
        for it in self._layer_tree.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue
            if data[0] == "curve":
                ids.append(data[1])
            elif data[0] == "text":
                text_ids.append(data[1])
        if not ids and not text_ids:
            return   # a layer row (or nothing) selected — leave canvas as-is
        if self.view._draw_tool is not None or self._dim_tool.active:
            # A live draw tool strips the selectable flag from every item;
            # picking rows would silently select nothing.
            self._act_select.setChecked(True)
            self._set_tool_select()
        self._syncing_selection = True
        skipped = False
        try:
            picked = []
            for cid in ids:
                ci = self.scene._curve_items.get(cid)
                if ci is None:
                    continue
                lyr = ci.curve.layer
                if (self.scene.is_layer_visible(lyr)
                        and not self.scene.is_layer_locked(lyr)):
                    picked.append(ci)
                else:
                    skipped = True
            for tid in text_ids:
                ti = self.scene._text_items.get(tid)
                if ti is None:
                    continue
                lyr = ti.text_obj.layer
                if (self.scene.is_layer_visible(lyr)
                        and not self.scene.is_layer_locked(lyr)):
                    picked.append(ti)
                else:
                    skipped = True
            self.scene.select_items(picked)
        finally:
            self._syncing_selection = False
        if skipped:
            self._status.showMessage(
                "Some rows are on hidden/locked layers — not selected")

    def _on_layer_tree_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self._layer_tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        has_sel = any(isinstance(i, (CurveItem, TextItem))
                      for i in self.scene.selectedItems())
        menu = QMenu(self)
        if kind == "layer":
            layer = payload
            menu.addAction(f"Draw on {layer.value}",
                           lambda: self._set_active_layer(layer))
            menu.addAction(f"Select All on {layer.value}",
                           lambda: self._select_all_on_layer(layer))
            act = menu.addAction(f"Move Selection to {layer.value}",
                                 lambda: self._move_selection_to_layer(layer))
            act.setEnabled(has_sel)
        else:
            # The right-click already selected the row (and so the object).
            menu.addAction("Delete", self._delete_selected)
        menu.exec(self._layer_tree.viewport().mapToGlobal(pos))

    def _select_all_on_layer(self, layer: Layer):
        if not self.scene.is_layer_visible(layer) or self.scene.is_layer_locked(layer):
            self._status.showMessage(
                f"{layer.value} is hidden or locked — nothing selected")
            return
        picked = [it for it in self.scene._curve_items.values()
                  if it.curve.layer == layer]
        picked += [it for it in self.scene._text_items.values()
                   if it.text_obj.layer == layer]
        self.scene.select_items(picked)
        self._status.showMessage(f"Selected {len(picked)} object(s) on {layer.value}")

    def _move_selection_to_layer(self, layer: Layer):
        """Reassign the selected curves/texts to *layer*."""
        targets = [i for i in self.scene.selectedItems()
                   if isinstance(i, (CurveItem, TextItem))]
        if not targets:
            self._status.showMessage("Move to layer: nothing selected")
            return
        self._move_curve_items_to_layer(targets, layer)

    def _on_layer_tree_drop(self, obj_ids: list, layer: Layer):
        """A drag-and-drop in the layer panel landed on *layer*."""
        items = [self.scene._curve_items.get(i) or self.scene._text_items.get(i)
                 for i in obj_ids]
        self._move_curve_items_to_layer([it for it in items if it is not None],
                                        layer)

    @staticmethod
    def _item_layer(it):
        return it.text_obj.layer if isinstance(it, TextItem) else it.curve.layer

    def _move_curve_items_to_layer(self, items: list, layer: Layer):
        """Shared by the context menu and layer-panel drag-and-drop; takes
        CurveItems and TextItems. Locked layers keep their objects."""
        locked = [it for it in items if self.scene.is_layer_locked(self._item_layer(it))]
        # A text stays engraving or reference: moved to OUTLINE it went out as
        # letter-shaped cut-outs in the DXF, while GuildModel's .gdraw read
        # dropped it, and the readiness dot checked neither.
        texts_kept = ([it for it in items if isinstance(it, TextItem)]
                      if layer not in (Layer.ENGRAVING, Layer.REF) else [])
        items = [it for it in items
                 if self._item_layer(it) is not layer and it not in locked
                 and it not in texts_kept]
        if not items:
            self._status.showMessage(
                "Move to layer: a text stays on ENGRAVING or REF" if texts_kept
                else f"Move to layer: {'layer is locked' if locked else 'already on ' + layer.value}")
            return
        self._push_undo_snapshot()
        for it in items:
            if isinstance(it, TextItem):
                it.text_obj.layer = layer
                it.refresh()
                self.scene._apply_layer_state_to_text(it)
            else:
                it.curve.layer = layer
                if layer != Layer.COMPONENT:
                    it.curve.component_kind = None   # a kind is a component's
                self.scene._apply_layer_state_to_item(it)
                # Through refresh_curve, not the item alone: the ghost, both
                # fills, a snapped boxing guide and the Measurements read the
                # layer too. Repainting the item left a lens moved to REF
                # still measured as a lens and still punched out of the fill.
                self.scene.refresh_curve(it.curve)
        self._refresh_layer_panel()
        self._update_readiness()
        self._refresh_measurements()
        msg = f"Moved {len(items)} object{'s' if len(items) != 1 else ''} → {layer.value}"
        if locked:
            msg += f"  ({len(locked)} on a locked layer left alone)"
        if texts_kept:
            msg += (f"  ({len(texts_kept)} text{'s' if len(texts_kept) != 1 else ''}"
                    " left alone: a text stays on ENGRAVING or REF)")
        self._status.showMessage(msg)

    # ------------------------------------------------------------------
    # Status bar info label (layer + zoom)
    # ------------------------------------------------------------------

    def _update_info_label(self):
        # Readiness is NOT recomputed here: it depends only on the document
        # and the mirror (both have their own hooks), and this runs on every
        # selection change and wheel tick — the validator in that path made
        # select-all on a few hundred curves take seconds.
        layer = self._active_ws.active_layer.value
        # Screen pixels per mm, as GuildModel shows it: "324%" was px/mm
        # times 100, which a true-scale drafting tool must not call a percent.
        z = self.view.zoom()
        zoom = f"{z:.2f}" if z < 1.0 else f"{z:.1f}"
        self._info_label.setText(f"Layer: {layer}  |  Zoom: {zoom} px/mm")

    _readiness_deferred = False

    def _flush_deferred_readiness(self):
        """After a mouse release: the readiness a drag put off."""
        if self._readiness_deferred:
            self._readiness_deferred = False
            self._update_readiness()

    def _update_readiness(self):
        """Recompute the 'Ready for GuildModel' dot for the active workspace."""
        dot = getattr(self, "_readiness_dot", None)
        if dot is None:
            return
        ws = self._active_ws
        mirror_on = bool(ws.scene.mirror and ws.scene.mirror.enabled)
        state, tip = readiness_state(ws.doc_curves, mirror_on, ws.workspace_type,
                                     stock_mm=self._stock_mm(ws))
        dot.set_dark_mode(self._dark_mode)
        dot.set_readiness(state, tip)

    # ------------------------------------------------------------------
    # Workspace tab switching (Phase 14)
    # ------------------------------------------------------------------

    # True only while a file load is repopulating the workspaces; see the
    # save-on-leave guard in _on_workspace_changed.
    _loading = False

    def _on_workspace_changed(self, idx: int):
        """Called by _ws_tab_widget.currentChanged. Saves departing sidebar
        state into the old WorkspaceState; restores arriving workspace state."""
        ws = self._workspaces[idx]

        # Save sidebar state into the workspace we're leaving; explicitly
        # cancel any in-progress drawing there (it cannot be carried across,
        # and silently discarding it confused makers).
        discarded = False
        if self._last_ws_idx != idx:
            old_ws = self._workspaces[self._last_ws_idx]
            if old_ws.draw_tool.active or old_ws.circle_tool.active:
                discarded = bool(getattr(old_ws.draw_tool, "_nodes", None)
                                 or old_ws.circle_tool.active)
                old_ws.draw_tool.deactivate()
                old_ws.circle_tool.deactivate()
                old_ws.view.set_draw_tool(None)
            # Not during a load. Opening a file whose saved active tab is not
            # the one on screen switches tabs while the widgets still show the
            # OUTGOING document, so saving them here wrote the old document's
            # guide/fill/forming values straight over the freshly loaded ones.
            if not self._loading:
                self._save_ws_sidebar_state(old_ws)
        self._last_ws_idx = idx

        # Return to Select mode
        self._act_select.setChecked(True)
        self._set_tool_select()

        # Restore arriving workspace state into sidebar
        self._restore_ws_sidebar_state(ws)
        self._show_guide_sections(ws.workspace_type)
        self._refresh_timeline_list()
        self._refresh_measurements()
        if ws.boxing_snapped:
            self._sync_boxing_readouts()
        # (No library refresh: the list is global, and every save, rename and
        # delete refreshes it. Re-reading the disk per tab switch cleared the
        # maker's selection in it.)
        self._refresh_layer_panel()
        self._refresh_mirror_icons()
        self._update_info_label()
        self._update_readiness()
        self._update_undo_actions()    # the menu shows THIS tab's history
        # Selection-driven buttons follow THIS tab's selection: a curve picked
        # on the Front left Explode lit on an empty Temple R.
        self._update_split_enabled()
        self._update_explode_enabled()
        self._act_snap_ep.setEnabled(self._edit_tool.has_selected_node())

        self._sync_empty_hint(ws)
        # Fit the view the first time this workspace is shown — to the
        # geometry as well as the scene rect, so a loaded temple longer than
        # the default extents isn't half off-screen.
        if not ws.fitted:
            self.view.fit_view(self._fit_rect(ws))
            ws.fitted = True
            self._update_info_label()
        if discarded:
            # After the Select-mode message, or it would be overwritten.
            self._status.showMessage(
                "Workspace switched — the in-progress drawing was discarded",
                5000)

    def _save_ws_sidebar_state(self, ws: "WorkspaceState"):
        """Write current sidebar widget values into *ws* for later restore."""
        ws.mirror_enabled = self._act_mirror.isChecked()
        ws.snap_enabled   = self._act_snap.isChecked()
        ws.smooth_handles = self._act_smooth.isChecked()
        ws.guides_visible = self._act_guides.isChecked()
        ws.boxing_visible = self._act_boxing.isChecked()
        ws.stock_visible  = self._act_stock.isChecked()
        ws.pad_visible    = self._act_pad.isChecked()
        ws.bridge_angle   = self._bridge_angle_spin.value()
        ws.apical_radius  = self._apical_spin.value()
        ws.crest_height   = self._guide_crest_height_spin.value()
        ws.arm_spread     = self._guide_spread_spin.value()
        ws.arm_drop       = self._guide_drop_spin.value()
        ws.boxing_snapped = self._boxing_snap_chk.isChecked()
        ws.shape_locked   = self._lock_shape_chk.isChecked()
        ws.boxing_chain   = self._chain_btn.isChecked()
        ws.outline_locked = self._outline_lock_chk.isChecked()
        # When snapped the A/B/DBL fields hold read-outs, not the free-box values
        # — preserve the stored free-box targets so they return on un-snap.
        if not ws.boxing_snapped:
            ws.boxing_a   = self._boxing_a_spin.value()
            ws.boxing_b   = self._boxing_b_spin.value()
            ws.boxing_dbl = self._boxing_dbl_spin.value()
        ws.bevel_preset   = self._bevel_choices[self._bevel_combo.currentIndex()][1]
        ws.bevel_depth    = self._current_bevel_depth()
        ws.stock_w        = self._stock_w_spin.value()
        ws.stock_h        = self._stock_h_spin.value()
        ws.pad_w          = self._pad_w_spin.value()
        ws.pad_h          = self._pad_h_spin.value()
        ws.fill_visible   = self._fill_show_chk.isChecked()
        ws.fill_opacity   = self._fill_opacity_slider.value() / 100.0
        # (fill_color is written by _on_fill_color_clicked directly, and
        #  fill_style / fill_image by the style combo and image picker)
        ws.lens_fill_visible = self._lens_fill_show_chk.isChecked()
        ws.lens_fill_linked  = self._lens_link_btn.isChecked()
        ws.lens_fill_opacity = self._lens_fill_opacity_slider.value() / 100.0
        ws.inlay_fill_visible = self._inlay_fill_show_chk.isChecked()
        ws.inlay_fill_opacity = self._inlay_fill_opacity_slider.value() / 100.0
        ws.inlay_fill_tumble  = self._inlay_fill_tumble_chk.isChecked()
        # (inlay_fill_color, _style and _image are written by their handlers)
        # NOT re-derived from the intensity slider: that mapping is geometric,
        # so position is a lossy encoding of the value (3.0 comes back 3.03) and
        # every tab switch would nudge a loaded document off its saved depth.
        # _on_lens_fill_intensity_changed is the sole writer.
        # (the two stop colors are written by _set_lens_fill_color directly)
        # (the images live in the scene, and selected_face_idx is written by
        # the Canvas tab's row handler)

    def _restore_ws_sidebar_state(self, ws: "WorkspaceState"):
        """Read values from *ws* into sidebar widgets (block signals to avoid
        cascading; apply to the workspace's guide objects directly)."""
        # ── Toggle actions ──────────────────────────────────────────────
        for act, val in [
            (self._act_mirror,  ws.mirror_enabled),
            (self._act_snap,    ws.snap_enabled),
            (self._act_smooth,  ws.smooth_handles),
            (self._act_guides,  ws.guides_visible),
            (self._act_boxing,  ws.boxing_visible),
            (self._act_stock,   ws.stock_visible),
            (self._act_pad,     ws.pad_visible),
            (self._act_obverse, ws.obverse),
        ]:
            act.blockSignals(True)
            act.setChecked(val)
            act.blockSignals(False)

        # Apply guide object states directly
        ws.const_guides.set_visible(ws.guides_visible)
        ws.boxing_guide.set_visible(ws.boxing_visible)
        ws.stock_guide.set_visible(ws.stock_visible)
        ws.pad_guide.set_visible(ws.pad_visible)
        ws.snap.set_enabled(ws.snap_enabled)
        ws.edit_tool.set_smooth_mode(ws.smooth_handles)
        if ws.scene.mirror:
            ws.scene.mirror.set_enabled(ws.mirror_enabled)
        if ws.scene.mirror_display() != ws.mirror_enabled:
            # Only on a change: every tab arrival rebuilt each Ghost and all
            # three fills, a quarter second on a dense outline (the 2.0 hunt).
            ws.scene.set_mirror_display(ws.mirror_enabled)
        ws.snap.set_mirror(0.0, ws.mirror_enabled, horizontal=(ws.workspace_type in ("temple_r", "temple_l")))
        ws.boxing_guide.set_mirror(ws.mirror_enabled)

        # ── Spinboxes ───────────────────────────────────────────────────
        for spin, val in [
            (self._bridge_angle_spin,        ws.bridge_angle),
            (self._apical_spin,              ws.apical_radius),
            (self._guide_crest_height_spin,  ws.crest_height),
            (self._guide_spread_spin,        ws.arm_spread),
            (self._guide_drop_spin,          ws.arm_drop),
            (self._boxing_a_spin,     ws.boxing_a),
            (self._boxing_b_spin,     ws.boxing_b),
            (self._boxing_dbl_spin,   ws.boxing_dbl),
            (self._stock_w_spin,      ws.stock_w),
            (self._stock_h_spin,      ws.stock_h),
            (self._pad_w_spin,        ws.pad_w),
            (self._pad_h_spin,        ws.pad_h),
        ]:
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

        # Apply spinbox values to the workspace's guide objects directly
        ws.const_guides.set_bridge_angle(ws.bridge_angle)
        ws.const_guides.set_apical_radius(ws.apical_radius)
        ws.const_guides.set_crest_height(ws.crest_height)
        ws.const_guides.set_spread(ws.arm_spread)
        ws.const_guides.set_pivot_y(ws.arm_drop)
        ws.boxing_guide.set_a(ws.boxing_a)
        ws.boxing_guide.set_b(ws.boxing_b)
        ws.boxing_guide.set_dbl(ws.boxing_dbl)

        # ── Bevel + snap/lock-to-lens (M11/M12) ─────────────────────────
        self._bevel_depth_spin.blockSignals(True)
        self._bevel_depth_spin.setValue(ws.bevel_depth)
        self._bevel_depth_spin.setEnabled(ws.bevel_preset == "custom")
        self._bevel_depth_spin.blockSignals(False)
        idx = next((i for i, (_lbl, k) in enumerate(self._bevel_choices)
                    if k == ws.bevel_preset), 2)
        self._bevel_combo.blockSignals(True)
        self._bevel_combo.setCurrentIndex(idx)
        self._bevel_combo.blockSignals(False)
        self._boxing_snap_chk.blockSignals(True)
        self._boxing_snap_chk.setChecked(ws.boxing_snapped)
        self._boxing_snap_chk.blockSignals(False)
        self._lock_shape_chk.blockSignals(True)
        self._lock_shape_chk.setChecked(ws.shape_locked)
        self._lock_shape_chk.blockSignals(False)
        self._chain_btn.blockSignals(True)
        self._chain_btn.setChecked(ws.boxing_chain)
        self._chain_btn.blockSignals(False)
        self._outline_lock_chk.blockSignals(True)
        self._outline_lock_chk.setChecked(ws.outline_locked)
        self._outline_lock_chk.blockSignals(False)
        ws.boxing_guide.set_bevel_depth(ws.bevel_depth)
        ws.boxing_guide.set_locked(ws.boxing_snapped)
        self._apply_boxing_field_modes(ws)
        ws.stock_guide.set_width(ws.stock_w)
        ws.stock_guide.set_height(ws.stock_h)
        ws.pad_guide.set_width(ws.pad_w)
        ws.pad_guide.set_height(ws.pad_h)

        # ── Frame fill ──────────────────────────────────────────────────
        self._fill_opacity_slider.blockSignals(True)
        self._fill_opacity_slider.setValue(round(ws.fill_opacity * 100))
        self._fill_opacity_slider.blockSignals(False)
        self._update_fill_swatch(ws.fill_color)
        ws.scene.set_fill_color(QColor(ws.fill_color))
        ws.scene.set_fill_opacity(ws.fill_opacity)
        self._apply_fill_material(ws)
        self._sync_fill_style_widgets(ws)
        status = ws.scene.set_fill_visible(ws.fill_visible)
        if ws.fill_visible and status != "ok":
            ws.fill_visible = False   # saved fill-on no longer encloses a region
        self._fill_show_chk.blockSignals(True)
        self._fill_show_chk.setChecked(ws.fill_visible)
        self._fill_show_chk.blockSignals(False)

        # ── Inlay fill ──────────────────────────────────────────────────
        self._inlay_fill_opacity_slider.blockSignals(True)
        self._inlay_fill_opacity_slider.setValue(round(ws.inlay_fill_opacity * 100))
        self._inlay_fill_opacity_slider.blockSignals(False)
        self._inlay_fill_tumble_chk.blockSignals(True)
        self._inlay_fill_tumble_chk.setChecked(ws.inlay_fill_tumble)
        self._inlay_fill_tumble_chk.blockSignals(False)
        self._update_inlay_fill_swatch(ws.inlay_fill_color)
        ws.scene.set_inlay_fill_color(QColor(ws.inlay_fill_color))
        ws.scene.set_inlay_fill_opacity(ws.inlay_fill_opacity)
        self._apply_inlay_fill_material(ws)
        status = ws.scene.set_inlay_fill_visible(ws.inlay_fill_visible)
        if ws.inlay_fill_visible and status != "ok":
            ws.inlay_fill_visible = False   # saved fill-on no longer encloses
        self._sync_inlay_fill_style_widgets(ws)
        self._inlay_fill_show_chk.blockSignals(True)
        self._inlay_fill_show_chk.setChecked(ws.inlay_fill_visible)
        self._inlay_fill_show_chk.blockSignals(False)

        # ── Lens fill ───────────────────────────────────────────────────
        self._lens_fill_opacity_slider.blockSignals(True)
        self._lens_fill_opacity_slider.setValue(round(ws.lens_fill_opacity * 100))
        self._lens_fill_opacity_slider.blockSignals(False)
        self._lens_link_btn.blockSignals(True)
        self._lens_link_btn.setChecked(ws.lens_fill_linked)
        self._lens_link_btn.blockSignals(False)
        self._lens_fill_intensity_slider.blockSignals(True)
        self._lens_fill_intensity_slider.setValue(
            slider_from_intensity(ws.lens_fill_intensity))
        self._lens_fill_intensity_slider.blockSignals(False)
        self._update_lens_fill_swatches(ws.lens_fill_top, ws.lens_fill_bottom,
                                        ws.lens_fill_intensity)
        ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
        ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
        lens_status = ws.scene.set_lens_fill_visible(ws.lens_fill_visible)
        if ws.lens_fill_visible and lens_status != "ok":
            ws.lens_fill_visible = False   # saved fill-on no longer encloses
        self._lens_fill_show_chk.blockSignals(True)
        self._lens_fill_show_chk.setChecked(ws.lens_fill_visible)
        self._lens_fill_show_chk.blockSignals(False)

        # (Layer list/active layer are per-workspace; _refresh_layer_panel is
        # called by _on_workspace_changed right after this restore.)

        # ── Calibration display ─────────────────────────────────────────
        self._show_calibration(ws)

        # ── Reference images ────────────────────────────────────────────
        self._refresh_face_list(ws)

    def _on_stock_width_changed(self, mm: float):
        """The blank guide's width is also the width a Frame Fill swatch spans,
        so a maker who corrects their sheet size sees the material rescale with
        it — showing/hiding the guide itself has no bearing on the fill."""
        ws = self._active_ws
        ws.stock_w = mm
        ws.stock_guide.set_width(mm)
        ws.scene.set_fill_blank_width(mm)
        self._update_readiness()   # the fit warning follows the guide
        self._mark_dirty()         # the guide sizes are saved with the design

    def _on_stock_height_changed(self, mm: float):
        ws = self._active_ws
        ws.stock_h = mm
        ws.stock_guide.set_height(mm)
        self._update_readiness()
        self._mark_dirty()

    def _on_pad_size_changed(self, width: float | None = None,
                             height: float | None = None):
        ws = self._active_ws
        if width is not None:
            ws.pad_w = width
            ws.pad_guide.set_width(width)
        if height is not None:
            ws.pad_h = height
            ws.pad_guide.set_height(height)
        self._mark_dirty()

    # ── Frame fill controls ─────────────────────────────────────────────

    def _update_fill_swatch(self, color_hex: str):
        pm = QPixmap(16, 16)
        pm.fill(QColor(color_hex))
        self._fill_color_btn.setIcon(QIcon(pm))

    def _on_fill_visible_toggled(self, on: bool):
        ws = self._active_ws
        if on:
            status = ws.scene.set_fill_visible(True)
            if status != "ok":
                # Nothing enclosable to fill — revert the tick and explain.
                self._fill_show_chk.blockSignals(True)
                self._fill_show_chk.setChecked(False)
                self._fill_show_chk.blockSignals(False)
                ws.fill_visible = False
                if status == "leak":
                    QMessageBox.information(
                        self, "Frame Fill",
                        "The frame outline has a gap somewhere: its ends don't "
                        "close around a region, so there is nothing to fill.\n\n"
                        "Close the OUTLINE, or, with the Ghost on, snap the open "
                        "half's ends onto the mirror line, then turn Frame Fill "
                        "on again.")
                else:  # "empty"
                    QMessageBox.information(
                        self, "Frame Fill",
                        "There's no frame outline to fill yet. Draw the OUTLINE "
                        "first, then turn Frame Fill on.")
                return
            ws.fill_visible = True
        else:
            ws.fill_visible = False
            ws.scene.set_fill_visible(False)
        self._mark_dirty()   # the fill is saved with the design

    def _on_fill_auto_disabled(self, status: str, ws):
        """A geometry edit opened the OUTLINE while the fill was on: the scene
        paused the fill until the outline closes again. The box stays ticked;
        the status bar says why (quietly — no modal mid-edit)."""
        if ws is self._active_ws:
            self._status.showMessage(
                "Frame Fill paused: the outline does not close (a half drawn "
                "against the axis needs the Ghost on). It returns when the "
                "outline closes." if status == "leak" else
                "Frame Fill paused: there is no OUTLINE to fill.", 6000)

    def _on_fill_color_clicked(self):
        ws = self._active_ws
        c = QColorDialog.getColor(QColor(ws.fill_color), self, "Frame fill color")
        if not c.isValid():
            return
        ws.fill_color = c.name()
        ws.scene.set_fill_color(c)
        self._update_fill_swatch(ws.fill_color)
        self._mark_dirty()

    def _on_fill_opacity_changed(self, value: int):
        ws = self._active_ws
        ws.fill_opacity = value / 100.0
        ws.scene.set_fill_opacity(ws.fill_opacity)
        self._mark_dirty()

    # ── Frame fill from a material swatch (v1.2) ────────────────────────

    def _apply_fill_material(self, ws: "WorkspaceState") -> bool:
        """Push ws.fill_style / ws.fill_image onto its scene, and keep the
        swatch scaled to that workspace's own blank width. Returns False when
        an image style was asked for but the file couldn't be read — the caller
        decides whether that deserves a modal or a silent fall back to color;
        ws.fill_style is left on "color" either way."""
        ws.scene.set_fill_blank_width(ws.stock_w)
        if ws.fill_style == "image" and ws.fill_image:
            if ws.scene.set_fill_image(ws.fill_image):
                return True
            ws.fill_style = "color"      # unreadable — show the color instead
            ws.scene.clear_fill_image()
            return False
        # An Image style with nothing behind it is not a state worth keeping —
        # it would show the color under a combo that claims otherwise.
        ws.fill_style = "color"
        ws.scene.clear_fill_image()
        return True

    def _sync_fill_style_widgets(self, ws: "WorkspaceState"):
        """Combo, image button label and per-style enablement, from *ws*."""
        idx = self._fill_style_combo.findData(ws.fill_style)
        self._fill_style_combo.blockSignals(True)
        self._fill_style_combo.setCurrentIndex(max(0, idx))
        self._fill_style_combo.blockSignals(False)
        is_image = (ws.fill_style == "image")
        self._fill_color_btn.setEnabled(not is_image)
        self._fill_image_btn.setEnabled(is_image)
        self._fill_image_clear_btn.setEnabled(is_image and bool(ws.fill_image))
        if ws.fill_image:
            self._set_swatch_btn_text(self._fill_image_btn,
                                      os.path.basename(ws.fill_image))
            self._fill_image_btn.setToolTip(ws.fill_image)
        else:
            self._set_swatch_btn_text(self._fill_image_btn, "Choose…")
            self._fill_image_btn.setToolTip(
                "Pick a material swatch — a supplier's acetate sample sheet.")

    def _swatch_row(self, on_choose, on_clear, clear_tip: str):
        """A fill's image row: a Choose… button and a square ✕ that forgets
        the image. Returns ``(row, choose, clear)``."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        choose = QPushButton("Choose…")
        # Swatch names run long ("TORTOISE-DEMI-AMBER-3MM-SHEET.png"); let the
        # button take whatever the row leaves it and elide what won't fit,
        # rather than dragging the whole sidebar wider.
        choose.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._swatch_btn_texts[choose] = "Choose…"
        choose.installEventFilter(self)
        choose.clicked.connect(on_choose)
        clear = QPushButton("✕")
        # The app stylesheet gives every QPushButton min-width: 54px, which Qt
        # promotes over a plain setFixedWidth — the clear button came out 76px
        # wide and ate the filename beside it. Pin it square in a local rule
        # instead: a stylesheet width is re-applied over the widget's own
        # minimum, so setFixedWidth alone gets overruled and a bare
        # `min-width: 0` lets a narrow panel squeeze the button to a sliver.
        # The rule sizes the CONTENT box, so the theme's 1px border on each
        # side comes off the target — see build_qss.
        box = max(8, choose.sizeHint().height() - 2)
        clear.setStyleSheet(
            f"QPushButton {{ min-width: {box}px; max-width: {box}px;"
            f" min-height: {box}px; max-height: {box}px; padding: 0px; }}")
        clear.setToolTip(clear_tip)
        clear.clicked.connect(on_clear)
        lay.addWidget(choose, 1)
        lay.addWidget(clear)
        return row, choose, clear

    def _set_swatch_btn_text(self, btn, text: str):
        """Label an image button, middle-eliding a name too long for the
        row so the extension stays readable (full path in the tooltip)."""
        self._swatch_btn_texts[btn] = text
        self._elide_swatch_btn(btn)

    def _elide_swatch_btn(self, btn):
        avail = btn.width() - 12          # the frame the label sits inside
        text  = self._swatch_btn_texts.get(btn, "")
        if avail > 0:
            text = QFontMetrics(btn.font()).elidedText(
                text, Qt.TextElideMode.ElideMiddle, avail)
        # Reached from the app-wide filter on every resize of this button, so
        # don't hand Qt a fresh layout request for a label that hasn't changed.
        if btn.text() != text:
            btn.setText(text)

    def _on_fill_style_changed(self, _index: int):
        ws = self._active_ws
        ws.fill_style = self._fill_style_combo.currentData() or "color"
        # Switching to Image with nothing chosen yet: open the picker rather
        # than leaving the maker on a style that shows the color anyway.
        if ws.fill_style == "image" and not ws.fill_image:
            self._sync_fill_style_widgets(ws)
            self._on_fill_image_clicked()
            return
        if not self._apply_fill_material(ws):
            self._fill_image_missing(ws)
        self._sync_fill_style_widgets(ws)
        self._mark_dirty()

    def _on_fill_image_clicked(self):
        ws = self._active_ws
        start = os.path.dirname(ws.fill_image) if ws.fill_image else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Frame Fill Material Swatch", start,
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)")
        def back_to_color_if_empty():
            # Leaving the auto-opened picker without a swatch — canceled, or
            # a file that won't decode — puts the style back, so the combo
            # doesn't sit on Image (and save "image") with nothing behind it.
            if not ws.fill_image:
                ws.fill_style = "color"
                self._apply_fill_material(ws)
                self._sync_fill_style_widgets(ws)
        if not path or self._image_too_large(path):
            back_to_color_if_empty()
            return
        ws.scene.set_fill_blank_width(ws.stock_w)
        if not ws.scene.set_fill_image(path, reload=True):   # picked again: re-read it
            QMessageBox.warning(
                self, "Frame Fill",
                f"{os.path.basename(path)} couldn't be read as an image.")
            back_to_color_if_empty()
            return
        ws.fill_image = path
        ws.fill_style = "image"
        self._sync_fill_style_widgets(ws)
        self._mark_dirty()
        self._status.showMessage(
            f"Frame Fill material: {os.path.basename(path)}"
            f"  ·  scaled to the {ws.stock_w:g} mm blank", 5000)

    def _on_fill_image_cleared(self):
        ws = self._active_ws
        ws.fill_image = ""
        ws.fill_style = "color"
        self._apply_fill_material(ws)
        self._sync_fill_style_widgets(ws)
        self._mark_dirty()

    def _fill_image_missing(self, ws: "WorkspaceState"):
        """The saved swatch is gone (a .svg pointing at a file that didn't
        travel with it). Say so once and leave the color showing."""
        self._status.showMessage(
            f"Frame Fill: {os.path.basename(ws.fill_image) or 'the material swatch'}"
            " couldn't be read — showing the color instead.", 6000)

    # ── Inlay fill controls (Road to 2.0, item 7) ───────────────────────

    def _default_inlay_fill_color(self) -> str:
        """Preferred starting color for an inlay fill (Preferences ▸ General)."""
        return _hex_or(self._prefs.get("inlay_fill_color"),
                       DEFAULT_INLAY_FILL_COLOR)

    def _default_inlay_fill_opacity(self) -> float:
        """Preferred starting opacity for an inlay fill, 0…1."""
        pct = self._prefs.get("inlay_fill_opacity_pct",
                              round(DEFAULT_INLAY_FILL_OPACITY * 100))
        try:
            return max(0.0, min(1.0, float(pct) / 100.0))
        except (TypeError, ValueError):
            return DEFAULT_INLAY_FILL_OPACITY

    def _update_inlay_fill_swatch(self, color_hex: str):
        pm = QPixmap(16, 16)
        pm.fill(QColor(color_hex))
        self._inlay_fill_color_btn.setIcon(QIcon(pm))

    def _on_inlay_fill_visible_toggled(self, on: bool):
        ws = self._active_ws
        if on:
            status = ws.scene.set_inlay_fill_visible(True)
            if status != "ok":
                # Nothing enclosable to fill — revert the tick and explain.
                self._inlay_fill_show_chk.blockSignals(True)
                self._inlay_fill_show_chk.setChecked(False)
                self._inlay_fill_show_chk.blockSignals(False)
                ws.inlay_fill_visible = False
                if status == "leak":
                    QMessageBox.information(
                        self, "Inlay Fill",
                        "No INLAY curve closes into a body, so there's "
                        "nothing to fill.\n\nClose the seat — select it and "
                        "press Join to fuse its ends — then turn Inlay Fill "
                        "on again.")
                else:  # "empty"
                    QMessageBox.information(
                        self, "Inlay Fill",
                        "There are no inlays to fill yet. Draw a closed seat "
                        "on the INLAY layer first, then turn Inlay Fill on.")
                return
            ws.inlay_fill_visible = True
        else:
            ws.inlay_fill_visible = False
            ws.scene.set_inlay_fill_visible(False)
        self._mark_dirty()   # the fill is saved with the design

    def _on_inlay_fill_auto_disabled(self, status: str, ws):
        """An edit opened every INLAY body while the fill was on: the scene
        paused it until one closes again. The box stays ticked."""
        if ws is self._active_ws:
            self._status.showMessage(
                "Inlay Fill paused: no inlay closes. It returns when one does.",
                6000)

    def _on_inlay_fill_color_clicked(self):
        ws = self._active_ws
        c = QColorDialog.getColor(QColor(ws.inlay_fill_color), self,
                                  "Inlay fill color")
        if not c.isValid():
            return
        ws.inlay_fill_color = c.name()
        ws.scene.set_inlay_fill_color(c)
        self._update_inlay_fill_swatch(ws.inlay_fill_color)
        self._mark_dirty()

    def _on_inlay_fill_opacity_changed(self, value: int):
        ws = self._active_ws
        ws.inlay_fill_opacity = value / 100.0
        ws.scene.set_inlay_fill_opacity(ws.inlay_fill_opacity)
        self._mark_dirty()

    def _on_inlay_fill_tumble_toggled(self, on: bool):
        ws = self._active_ws
        ws.inlay_fill_tumble = on
        ws.scene.set_inlay_fill_tumble(on)
        self._mark_dirty()

    def _apply_inlay_fill_material(self, ws: "WorkspaceState") -> bool:
        """Push ws.inlay_fill_style / _image / _tumble onto its scene. False
        when an image was asked for but the file couldn't be read; the style
        is left on "color" either way (see _apply_fill_material)."""
        ws.scene.set_inlay_fill_tumble(ws.inlay_fill_tumble)
        if ws.inlay_fill_style == "image" and ws.inlay_fill_image:
            if ws.scene.set_inlay_fill_image(ws.inlay_fill_image):
                return True
            ws.inlay_fill_style = "color"
            ws.scene.clear_inlay_fill_image()
            return False
        ws.inlay_fill_style = "color"
        ws.scene.clear_inlay_fill_image()
        return True

    def _sync_inlay_fill_style_widgets(self, ws: "WorkspaceState"):
        """Combo, image button label and per-style enablement, from *ws*."""
        idx = self._inlay_fill_style_combo.findData(ws.inlay_fill_style)
        self._inlay_fill_style_combo.blockSignals(True)
        self._inlay_fill_style_combo.setCurrentIndex(max(0, idx))
        self._inlay_fill_style_combo.blockSignals(False)
        is_image = (ws.inlay_fill_style == "image")
        self._inlay_fill_color_btn.setEnabled(not is_image)
        self._inlay_fill_image_btn.setEnabled(is_image)
        self._inlay_fill_image_clear_btn.setEnabled(
            is_image and bool(ws.inlay_fill_image))
        if ws.inlay_fill_image:
            self._set_swatch_btn_text(self._inlay_fill_image_btn,
                                      os.path.basename(ws.inlay_fill_image))
            self._inlay_fill_image_btn.setToolTip(ws.inlay_fill_image)
        else:
            self._set_swatch_btn_text(self._inlay_fill_image_btn, "Choose…")
            self._inlay_fill_image_btn.setToolTip(
                "Pick a photo of the inlay's material — a turquoise stone, a "
                "shell, a wood.")
        self._sync_inlay_tumble_enabled(ws)

    def _sync_inlay_tumble_enabled(self, ws: "WorkspaceState | None" = None):
        """Tumble bodies has something to do only for an image on two or
        more bodies. Its tick is kept while it is disabled."""
        ws = ws or self._active_ws
        if Layer.INLAY not in WORKSPACE_LAYERS[ws.workspace_type]:
            return
        self._inlay_fill_tumble_chk.setEnabled(
            ws.inlay_fill_style == "image" and ws.scene.inlay_body_count() > 1)

    def _on_inlay_fill_style_changed(self, _index: int):
        ws = self._active_ws
        ws.inlay_fill_style = self._inlay_fill_style_combo.currentData() or "color"
        # Switching to Image with nothing chosen yet: open the picker (see
        # _on_fill_style_changed).
        if ws.inlay_fill_style == "image" and not ws.inlay_fill_image:
            self._sync_inlay_fill_style_widgets(ws)
            self._on_inlay_fill_image_clicked()
            return
        if not self._apply_inlay_fill_material(ws):
            self._inlay_fill_image_missing(ws)
        self._sync_inlay_fill_style_widgets(ws)
        self._mark_dirty()

    def _on_inlay_fill_image_clicked(self):
        ws = self._active_ws
        start = os.path.dirname(ws.inlay_fill_image) if ws.inlay_fill_image else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Inlay Fill Image", start,
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)")
        def back_to_color_if_empty():
            # Leaving the auto-opened picker without an image puts the style
            # back (see _on_fill_image_clicked).
            if not ws.inlay_fill_image:
                ws.inlay_fill_style = "color"
                self._apply_inlay_fill_material(ws)
                self._sync_inlay_fill_style_widgets(ws)
        if not path or self._image_too_large(path):
            back_to_color_if_empty()
            return
        if not ws.scene.set_inlay_fill_image(path, reload=True):
            QMessageBox.warning(
                self, "Inlay Fill",
                f"{os.path.basename(path)} couldn't be read as an image.")
            back_to_color_if_empty()
            return
        ws.inlay_fill_image = path
        ws.inlay_fill_style = "image"
        self._sync_inlay_fill_style_widgets(ws)
        self._mark_dirty()
        self._status.showMessage(
            f"Inlay Fill image: {os.path.basename(path)}", 5000)

    def _on_inlay_fill_image_cleared(self):
        ws = self._active_ws
        ws.inlay_fill_image = ""
        ws.inlay_fill_style = "color"
        self._apply_inlay_fill_material(ws)
        self._sync_inlay_fill_style_widgets(ws)
        self._mark_dirty()

    def _inlay_fill_image_missing(self, ws: "WorkspaceState"):
        """The saved image is gone; say so once and leave the color showing."""
        self._status.showMessage(
            f"Inlay Fill: {os.path.basename(ws.inlay_fill_image) or 'the image'}"
            " couldn't be read — showing the color instead.", 6000)

    # ── Lens fill controls ──────────────────────────────────────────────

    def _default_lens_fill_opacity(self) -> float:
        """Preferred starting opacity for a lens tint, 0…1."""
        pct = self._prefs.get("lens_fill_opacity_pct",
                              round(DEFAULT_LENS_FILL_OPACITY * 100))
        try:
            return max(0.0, min(1.0, float(pct) / 100.0))
        except (TypeError, ValueError):
            return DEFAULT_LENS_FILL_OPACITY

    def _default_lens_fill_intensity(self) -> float:
        """Preferred starting tint intensity (see deepen_tint)."""
        raw = self._prefs.get("lens_fill_intensity", DEFAULT_LENS_FILL_INTENSITY)
        try:
            return max(LENS_FILL_INTENSITY_MIN,
                       min(LENS_FILL_INTENSITY_MAX, float(raw)))
        except (TypeError, ValueError):
            return DEFAULT_LENS_FILL_INTENSITY

    def _update_lens_fill_swatches(self, top_hex: str, bottom_hex: str,
                                   intensity: float):
        """Repaint the two color bars.

        They show the color *as painted* — deepened by the current intensity —
        because that is what the maker is judging; the picker still opens on
        the base color, and the tooltip names both so the two never get
        confused."""
        w, h = _LENS_SWATCH_PX
        for btn, hex_, label in ((self._lens_top_btn, top_hex, "Top"),
                                 (self._lens_bottom_btn, bottom_hex, "Bottom")):
            shown = deepen_tint(hex_, intensity)
            pm = QPixmap(w, h)
            pm.fill(shown)
            p = QPainter(pm)
            p.setPen(QPen(QColor(0, 0, 0, 70)))
            p.drawRect(0, 0, w - 1, h - 1)
            p.end()
            btn.setIcon(QIcon(pm))
            tip = f"{label} gradient stop for every lens.\nColor: {hex_}"
            if shown.name() != QColor(hex_).name():
                tip += f"  ·  shown at intensity: {shown.name()}"
            btn.setToolTip(tip + "\nClick to pick a color.")

    def _on_lens_fill_visible_toggled(self, on: bool):
        ws = self._active_ws
        if on:
            status = ws.scene.set_lens_fill_visible(True)
            if status != "ok":
                # Nothing enclosable to tint — revert the tick and explain.
                self._lens_fill_show_chk.blockSignals(True)
                self._lens_fill_show_chk.setChecked(False)
                self._lens_fill_show_chk.blockSignals(False)
                ws.lens_fill_visible = False
                if status == "leak":
                    QMessageBox.information(
                        self, "Lens Fill",
                        "No lens aperture closes into an enclosed region, so "
                        "there's nothing to tint.\n\nClose the LENS shape — "
                        "select it and press Join to fuse its ends — or, with "
                        "the Ghost on, snap the open half's ends onto the "
                        "mirror line, then turn Lens Fill on again.")
                else:  # "empty"
                    QMessageBox.information(
                        self, "Lens Fill",
                        "There are no lenses to tint yet. Draw a LENS shape "
                        "first, then turn Lens Fill on.")
                return
            ws.lens_fill_visible = True
        else:
            ws.lens_fill_visible = False
            ws.scene.set_lens_fill_visible(False)
        self._mark_dirty()   # the tint is saved with the design

    def _on_lens_fill_auto_disabled(self, status: str, ws):
        """An edit opened every lens aperture while the fill was on: the scene
        paused it until one closes again. The box stays ticked."""
        if ws is self._active_ws:
            self._status.showMessage(
                "Lens Fill paused: no lens closes. It returns when one does.",
                6000)

    def _set_lens_fill_color(self, which: str, color_hex: str):
        """Write one gradient stop (and its twin while the link is on)."""
        ws = self._active_ws
        if which == "top" or ws.lens_fill_linked:
            ws.lens_fill_top = color_hex
        if which == "bottom" or ws.lens_fill_linked:
            ws.lens_fill_bottom = color_hex
        ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
        self._update_lens_fill_swatches(ws.lens_fill_top, ws.lens_fill_bottom,
                                        ws.lens_fill_intensity)
        self._mark_dirty()

    def _on_lens_fill_color_clicked(self, which: str):
        ws = self._active_ws
        current = ws.lens_fill_top if which == "top" else ws.lens_fill_bottom
        label = "Lens tint — top" if which == "top" else "Lens tint — bottom"
        c = QColorDialog.getColor(QColor(current), self, label)
        if not c.isValid():
            return
        self._set_lens_fill_color(which, c.name())

    def _show_tint_picker(self, which: str):
        """Open the BPI tint reference; the chosen hex lands in *which* stop."""
        picker = _bpi_tints.TintPicker(
            self,
            title=("BPI tint reference — top stop" if which == "top"
                   else "BPI tint reference — bottom stop"))
        picker.tint_picked.connect(
            lambda hex_, w=which: self._set_lens_fill_color(w, hex_))
        picker.show_under(self._lens_top_bpi_btn if which == "top"
                          else self._lens_bottom_bpi_btn)

    def _on_lens_fill_link_toggled(self, on: bool):
        ws = self._active_ws
        if on:
            # Collapse to a flat tint on the top stop — the primary of the
            # pair — keeping the bottom stop to give back on unlink: it stayed
            # the top's color, and the gradient had to be picked again.
            ws.lens_fill_bottom_kept = ws.lens_fill_bottom
            ws.lens_fill_linked = True
            self._set_lens_fill_color("top", ws.lens_fill_top)
        else:
            ws.lens_fill_linked = False
            kept = getattr(ws, "lens_fill_bottom_kept", None)
            if kept:
                self._set_lens_fill_color("bottom", kept)
            ws.lens_fill_bottom_kept = None
        self._mark_dirty()

    def _on_lens_fill_intensity_changed(self, value: int):
        ws = self._active_ws
        ws.lens_fill_intensity = intensity_from_slider(value)
        ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        self._update_lens_fill_swatches(ws.lens_fill_top, ws.lens_fill_bottom,
                                        ws.lens_fill_intensity)
        self._mark_dirty()

    def _on_lens_fill_opacity_changed(self, value: int):
        ws = self._active_ws
        ws.lens_fill_opacity = value / 100.0
        ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
        self._mark_dirty()

    def _show_guide_sections(self, ws_type: str):
        """Show/hide Guides-tab group boxes based on workspace type."""
        is_front  = (ws_type == "front")
        is_temple = (ws_type in ("temple_r", "temple_l"))
        is_component = (ws_type == "component")
        self._construction_guide_box.setVisible(is_front)
        self._boxing_guide_box.setVisible(is_front)
        self._stock_guide_box.setVisible(True)   # all workspaces have a stock rect
        self._pad_guide_box.setVisible(is_front) # pad block only meaningful for front
        self._fill_box.setVisible(is_front or is_temple)  # fill needs an OUTLINE
        self._inlay_fill_box.setVisible(is_front or is_temple)  # the INLAY layer's tabs
        self._lens_fill_box.setVisible(is_front)          # only the front has lenses
        # Toolbar buttons: combined prefs + workspace rules in one place
        self._apply_toolbar_visibility(self._toolbar_prefs, ws_type)
        self._meas_front_box.setVisible(is_front)
        self._meas_temple_box.setVisible(is_temple)
        lib_tabs = getattr(self, "_lib_tabs", None)
        if lib_tabs is not None:
            # Holes are the front's drill patterns: elsewhere Add Hole jumped
            # to the Front to place one.
            lib_tabs.setTabVisible(1, is_front)
        if is_temple:
            label = "Temple R" if ws_type == "temple_r" else "Temple L"
            self._meas_temple_box.set_title(f"Measurements — {label}")
        # Library tab: save, folders, rename, move and delete only in the
        # Component workspace, and drag and drop with them: elsewhere a
        # double-click that slipped moved an entry, and so changed its kind.
        self._lib_component_actions.setVisible(is_component)
        self._lib_tree.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove if is_component
            else QAbstractItemView.DragDropMode.NoDragDrop)

    def _refresh_measurements(self):
        """Recompute and display workspace measurements in the Properties tab.
        Also stashes the representative finished A/B/DBL for the snapped boxing
        read-outs (_snap_a/_snap_b/_snap_dbl)."""
        ws = self._active_ws
        _FRONT_LAYERS  = {Layer.OUTLINE, Layer.LENS}
        _TEMPLE_LAYERS = {Layer.OUTLINE}
        self._snap_a = self._snap_b = self._snap_dbl = None

        if ws.workspace_type == "front":
            # Front view: positive x = OS (patient's left), negative x = OD (patient's right).
            mirror_x = getattr(ws.scene.mirror, '_x', 0.0) if ws.scene.mirror else 0.0
            curves = ws.doc_curves

            ghost = bool(ws.mirror_enabled and ws.scene.mirror is not None)
            tol = 0.1

            def _side(bb):
                """+1 for a box wholly on the OS side of the axis (+x), -1 on
                the OD side, 0 for one across it."""
                if bb[0] > mirror_x + tol:
                    return 1
                if bb[2] < mirror_x - tol:
                    return -1
                return 0

            # ── Frame width: OUTLINE layer ─────────────────────────────
            # What is drawn, except a half on one side with the Ghost on,
            # which the Ghost completes: the old split by node centroid
            # doubled an asymmetric whole outline, and a monocle's rim with
            # the Ghost off (GuildModel reads only the curves drawn).
            all_out = [c for c in curves if c.layer == Layer.OUTLINE and c.nodes]
            ob = _curves_bbox(all_out) if all_out else None
            fw = None
            if ob is not None:
                side = _side(ob)
                if ghost and side > 0:
                    fw = 2.0 * (ob[2] - mirror_x)
                elif ghost and side < 0:
                    fw = 2.0 * (mirror_x - ob[0])
                else:
                    fw = ob[2] - ob[0]
            self._meas_frame_width_lbl.setText(f"{fw:.1f} mm" if fw is not None else "—")
            self._meas_frame_height_lbl.setText(
                f"{ob[3] - ob[1]:.1f} mm" if ob else "—")

            # ── Lens boxing: LENS layer ────────────────────────────────
            # Use the SAMPLED bbox (same basis as the boxing guide + resizer) so
            # the read-out, the drawn box, and the typed resize target all agree.
            # Boxing measures the FINISHED (beveled) lens.
            from .boxing import finished_geometry, lens_polygon, union_bbox
            bevel_d = max(0.0, ws.bevel_depth)
            os_len, od_len = [], []
            for c in curves:
                if c.layer != Layer.LENS or not c.nodes:
                    continue
                bb = union_bbox([c])
                if bb is None:
                    continue
                cx = 0.5 * (bb[0] + bb[2])
                (os_len if cx > mirror_x else od_len if cx < mirror_x else []).append(c)

            def _eye(lenses):
                """(A, B, ED, finished box) of one eye's finished lens, or Nones.
                ED, the effective diameter: twice the longest radius from the
                box center, as GuildModel and the OMA trace's FED take it (the
                panel showed the box's diagonal, 10 to 16 mm more)."""
                boxes, pts = [], []
                for c in lenses:
                    box, outline = finished_geometry(c, bevel_d)
                    if box is None:
                        continue
                    boxes.append(box)
                    if outline is None:
                        poly = lens_polygon(c)
                        outline = list(poly.exterior.coords) if not poly.is_empty else []
                    pts += outline
                if not boxes:
                    return None, None, None, None
                bx0 = min(b[0] for b in boxes); by0 = min(b[1] for b in boxes)
                bx1 = max(b[2] for b in boxes); by1 = max(b[3] for b in boxes)
                cx, cy = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
                ed = 2.0 * max((math.hypot(x - cx, y - cy) for x, y in pts),
                               default=0.0)
                return bx1 - bx0, by1 - by0, ed, (bx0, by0, bx1, by1)

            os_a, os_b, os_ed, os_fb = _eye(os_len)
            od_a, od_b, od_ed, od_fb = _eye(od_len)
            # One eye drawn: with the Ghost on its twin is that eye mirrored;
            # with it off this is a monocle, and the other eye has no numbers.
            if ghost and os_a is not None and od_a is None:
                od_a, od_b, od_ed = os_a, os_b, os_ed
            elif ghost and od_a is not None and os_a is None:
                os_a, os_b, os_ed = od_a, od_b, od_ed

            def _set_lens(a_lbl, b_lbl, ed_lbl, a, b, ed):
                if a is None:
                    for lbl in (a_lbl, b_lbl, ed_lbl):
                        lbl.setText("—")
                else:
                    a_lbl.setText(f"{a:.1f} mm")
                    b_lbl.setText(f"{b:.1f} mm")
                    ed_lbl.setText(f"{ed:.1f} mm")

            _set_lens(self._meas_os_a_lbl, self._meas_os_b_lbl, self._meas_os_ed_lbl,
                      os_a, os_b, os_ed)
            _set_lens(self._meas_od_a_lbl, self._meas_od_b_lbl, self._meas_od_ed_lbl,
                      od_a, od_b, od_ed)

            # DBL — distance between the nasal edges of the two finished
            # boxes; with one eye and the Ghost on, twice its nasal edge's
            # distance from the axis (an estimate, marked ≈); a monocle has none.
            dbl = None
            dbl_est = False
            if os_fb and od_fb:
                dbl = os_fb[0] - od_fb[2]
            elif ghost and os_fb:
                dbl, dbl_est = 2.0 * (os_fb[0] - mirror_x), True
            elif ghost and od_fb:
                dbl, dbl_est = 2.0 * (mirror_x - od_fb[2]), True

            # Stash representative finished A/B/DBL for the snapped boxing read-outs.
            self._snap_a   = od_a if od_a is not None else os_a
            self._snap_b   = od_b if od_b is not None else os_b
            self._snap_dbl = dbl

            if dbl is not None:
                self._meas_dbl_lbl.setText(f"≈ {dbl:.1f} mm" if dbl_est else f"{dbl:.1f} mm")
                self._meas_dbl_lbl.setToolTip(
                    "An estimate: one lens is drawn, and the Ghost previews the "
                    "other." if dbl_est else "")
            else:
                self._meas_dbl_lbl.setText("—")
                self._meas_dbl_lbl.setToolTip("")

        elif ws.workspace_type in ("temple_r", "temple_l"):
            curves = ws.doc_curves
            bbox = _curves_bbox(curves, layers=_TEMPLE_LAYERS)

            if bbox is None:
                self._meas_temple_length_lbl.setText("—")
                self._meas_endpiece_lbl.setText("—")
                return

            min_x, min_y, max_x, max_y = bbox
            x_span = max_x - min_x
            self._meas_temple_length_lbl.setText(f"{x_span:.1f} mm")

            # Endpiece width = the outline's height across the hinge-end band
            # (the first tenth of the length), measured on the drawn path.
            # Filtering whole curves by where their nodes cluster left a
            # normal one-piece temple reading "—", and doubled it with the
            # ghost on even when both halves were drawn.
            from .geometry import sample_curve
            ep_threshold = min_x + max(x_span * 0.1, 2.0)
            # 64 samples a segment: 16 read up to 0.3 mm short at a corner.
            ys = [y for c in curves if c.layer in _TEMPLE_LAYERS and c.nodes
                  for x, y, _t in sample_curve(c, 64) if x <= ep_threshold]
            if ys and ws.mirror_enabled and ws.scene.mirror is not None:
                axis = ws.scene.mirror.x         # a temple's axis is horizontal
                if all(y <= axis + 1e-6 for y in ys) or all(y >= axis - 1e-6 for y in ys):
                    ys += [2.0 * axis - y for y in ys]       # a half: the ghost completes it
            if ys:
                self._meas_endpiece_lbl.setText(f"{max(ys) - min(ys):.1f} mm")
            else:
                self._meas_endpiece_lbl.setText("—")

    # ------------------------------------------------------------------
    # Boxing snap / lock + bevel (M11 / M12)
    # ------------------------------------------------------------------

    def _current_bevel_depth(self) -> float:
        key = self._bevel_choices[self._bevel_combo.currentIndex()][1]
        if key == "custom":
            return self._bevel_depth_spin.value()
        return BEVEL_PRESETS.get(key, 0.0)

    def _apply_boxing_field_modes(self, ws=None):
        """A/B/DBL editability per mode: free = inputs; snapped = read-outs;
        locked = inputs again — A/B resize the lens, DBL moves the pair."""
        ws = ws or self._active_ws
        snapped, locked = ws.boxing_snapped, ws.shape_locked
        self._boxing_a_spin.setEnabled((not snapped) or locked)
        self._boxing_b_spin.setEnabled((not snapped) or locked)
        self._boxing_dbl_spin.setEnabled((not snapped) or locked)
        if not snapped:
            for spin in (self._boxing_a_spin, self._boxing_b_spin,
                         self._boxing_dbl_spin):
                spin.setSpecialValueText("")       # free: every value is one
        # A shape to lock needs a lens: with none it was offered all the same.
        has_lens = any(c.layer == Layer.LENS and not c.mirrored
                       for c in ws.doc_curves)
        self._lock_shape_chk.setEnabled(snapped and (has_lens or locked))
        self._outline_lock_chk.setEnabled(locked)
        # The A–B link acts only on a locked lens; lit otherwise, it looked
        # like it did something.
        self._chain_btn.setEnabled(locked)

    # A/B fields: drive the free box when not snapped; live-resize the locked
    # lens when locked (read-outs while snapped-but-unlocked never user-fire).
    def _guide_edited(self, *_args):
        """A guide value saved with the design changed: star it. Not while
        Preferences pushes its values in (_apply_settings stars a drawn
        design itself, and an empty one has nothing to lose)."""
        if not getattr(self, "_applying_settings", False):
            self._mark_dirty()

    def _on_boxing_a_value(self, v: float):
        ws = self._active_ws
        if not ws.boxing_snapped:
            self._boxing_guide.set_a(v)
            self._guide_edited()
        elif ws.shape_locked:
            self._locked_resize_from_field("a", v)

    def _on_boxing_b_value(self, v: float):
        ws = self._active_ws
        if not ws.boxing_snapped:
            self._boxing_guide.set_b(v)
            self._guide_edited()
        elif ws.shape_locked:
            self._locked_resize_from_field("b", v)

    def _on_boxing_dbl_value(self, v: float):
        ws = self._active_ws
        if not ws.boxing_snapped:
            self._boxing_guide.set_dbl(v)
            self._guide_edited()
        elif ws.shape_locked:
            self._set_dbl_by_move(v)

    def _on_chain_toggled(self, on: bool):
        self._active_ws.boxing_chain = on      # session state — not saved

    def _on_outline_lock_toggled(self, on: bool):
        self._active_ws.outline_locked = on
        self._status.showMessage(
            "Outline locked to lens — it co-resizes (constant wall)."
            if on else "Outline unlocked.")

    def _set_dbl_by_move(self, target_dbl: float):
        """Locked-mode DBL edit → translate the lens(es) along X to hit the
        target finished DBL.  Each lens moves away-from / toward the mirror axis
        by half the delta; a locked OPEN (half) outline rides along to keep the
        wall.  Closed (finished) frames are left in place (DBL is internal)."""
        ws = self._active_ws
        cur = self._finished_box_values()
        if not cur or cur[2] is None:
            return
        delta = target_dbl - cur[2]
        if abs(delta) < 0.02:
            return
        axis_x = ws.scene.mirror.x if ws.scene.mirror else 0.0
        lenses = [c for c in ws.doc_curves
                  if c.layer == Layer.LENS and not c.mirrored and c.nodes]
        if not lenses:
            return
        out_curves = [c for c in ws.doc_curves
                      if c.layer == Layer.OUTLINE and not c.mirrored and c.nodes]
        move_outline = (ws.outline_locked and out_curves
                        and self._outline_is_half(out_curves, axis_x))
        self._push_undo_snapshot()
        self._edit_tool.clear()
        for c in lenses:
            cx = sum(n.x for n in c.nodes) / len(c.nodes)
            self._translate_curve(c, (1.0 if cx >= axis_x else -1.0) * delta / 2.0, 0.0)
            self.scene.refresh_curve(c)
        if move_outline:
            ocx = (lambda b: (b[0] + b[2]) / 2)(_curves_bbox(out_curves))
            for c in out_curves:
                self._translate_curve(c, (1.0 if ocx >= axis_x else -1.0) * delta / 2.0, 0.0)
                self.scene.refresh_curve(c)
        ws.boxing_guide.refresh()
        self._refresh_measurements()
        self._sync_boxing_readouts()
        self._mark_dirty()

    @staticmethod
    def _outline_is_half(out_curves, axis_x: float) -> bool:
        """True if the outline is a single mirrored half (lies to one side of the
        axis); False if it straddles the axis as a finished full frame."""
        from .boxing import union_bbox
        ob = union_bbox(out_curves)
        if ob is None:
            return False
        w = ob[2] - ob[0]
        if w <= 1e-9:
            return False
        left, right = axis_x - ob[0], ob[2] - axis_x
        straddles = left > w * 0.25 and right > w * 0.25
        return not straddles

    def _outline_resize_plan(self, out_curves, axis_x, dW: float, dH: float):
        """Affine-scale plan for the OUTLINE that grows the eyewire wall by the
        same mm as the lens (constant wall), preserving flats/corners.  Open
        halves anchor on the nasal (bridge) edge; closed full frames scale
        symmetrically about the axis."""
        from .boxing import union_bbox
        from .resize import scale_curve_about
        ob = union_bbox(out_curves)
        if ob is None:
            return []
        out_w, out_h = ob[2] - ob[0], ob[3] - ob[1]
        piv_y = (ob[1] + ob[3]) / 2
        sy = (out_h + dH) / out_h if out_h > 1e-9 else 1.0
        if self._outline_is_half(out_curves, axis_x):
            out_cx = (ob[0] + ob[2]) / 2
            piv_x = ob[0] if out_cx >= axis_x else ob[2]      # nasal (bridge) edge
            sx = (out_w + dW) / out_w if out_w > 1e-9 else 1.0
        else:
            piv_x = axis_x                                     # symmetric full frame
            sx = (out_w + 2 * dW) / out_w if out_w > 1e-9 else 1.0
        if abs(sx - 1.0) < 1e-9 and abs(sy - 1.0) < 1e-9:
            return []
        out = []
        for c in out_curves:
            nc = scale_curve_about(c, piv_x, piv_y, sx, sy)
            nc.layer = c.layer
            nc.group_id = c.group_id
            out.append((c, nc))
        return out

    def _locked_resize_from_field(self, changed: str, v: float):
        """Live-resize the locked lens when A or B is edited.  Only the edited
        axis is targeted (the other is left untouched) unless the chain is on,
        in which case the other axis scales proportionally to keep the aspect."""
        cur = self._finished_box_values()
        if not cur or cur[0] is None or cur[1] is None:
            return
        cur_a, cur_b = cur[0], cur[1]
        chained = self._chain_btn.isChecked()
        if changed == "a":
            if abs(v - cur_a) < 0.02:
                return
            target_a = v
            target_b = cur_b * (v / cur_a) if (chained and cur_a) else None
        else:
            if abs(v - cur_b) < 0.02:
                return
            target_b = v
            target_a = cur_a * (v / cur_b) if (chained and cur_b) else None
        self._resize_locked_lens(target_a, target_b)

    def _on_boxing_visible_toggled(self, on: bool):
        """Boxing toolbar button. While snapped, a deliberate toggle also
        replaces the pre-snap memory — the maker's latest word is what
        un-snapping should restore."""
        ws = self._active_ws
        ws.boxing_guide.set_visible(on)
        if ws.boxing_snapped and not self._boxing_snap_syncing:
            ws.boxing_visible_pre_snap = on

    _boxing_snap_syncing = False

    def _on_boxing_snap_toggled(self, on: bool):
        ws = self._active_ws
        ws.boxing_snapped = on
        if not on and ws.shape_locked:
            ws.shape_locked = False              # leaving snap releases the lock
            self._lock_shape_chk.blockSignals(True)
            self._lock_shape_chk.setChecked(False)
            self._lock_shape_chk.blockSignals(False)
            self._edit_tool.refresh_for_selection()
        # Push the current bevel depth so the bevel outline appears immediately.
        ws.bevel_depth = self._current_bevel_depth()
        ws.boxing_guide.set_bevel_depth(ws.bevel_depth)
        ws.boxing_guide.set_locked(on)
        if on:
            # Snapping implies showing the guide — remember whether the maker
            # had it up, so un-snapping can put it back the way they left it.
            if ws.boxing_visible_pre_snap is None:
                ws.boxing_visible_pre_snap = self._act_boxing.isChecked()
            if not self._act_boxing.isChecked():
                self._boxing_snap_syncing = True
                try:
                    self._act_boxing.setChecked(True)
                finally:
                    self._boxing_snap_syncing = False
        self._apply_boxing_field_modes()
        if not on:
            # Restore the free-box A/B/DBL targets the read-outs overwrote.
            for spin, val in ((self._boxing_a_spin, ws.boxing_a),
                              (self._boxing_b_spin, ws.boxing_b),
                              (self._boxing_dbl_spin, ws.boxing_dbl)):
                spin.blockSignals(True)
                spin.setValue(max(spin.minimum(), min(spin.maximum(), val)))
                spin.blockSignals(False)
            ws.boxing_guide.set_a(ws.boxing_a)
            ws.boxing_guide.set_b(ws.boxing_b)
            ws.boxing_guide.set_dbl(ws.boxing_dbl)
            # Hide the guide again if it only appeared because we snapped —
            # otherwise the free box springs back at its default size and
            # position, which reads as the app forgetting what it was told.
            if ws.boxing_visible_pre_snap is False:
                self._boxing_snap_syncing = True
                try:
                    self._act_boxing.setChecked(False)
                finally:
                    self._boxing_snap_syncing = False
            ws.boxing_visible_pre_snap = None
        ws.boxing_guide.refresh()
        self._refresh_measurements()
        if on:
            self._sync_boxing_readouts()
        # No _mark_dirty: snap and lock are session state (reset_session_state),
        # never written to the file — a snap and unsnap left a clean design
        # starred and asking to be saved unchanged.

    def _on_lock_shape_toggled(self, on: bool):
        ws = self._active_ws
        if on and not ws.boxing_snapped:
            return                               # lock only meaningful while snapped
        ws.shape_locked = on
        self._apply_boxing_field_modes()
        self._edit_tool.refresh_for_selection()  # show/hide node dots for the lens
        if on:
            self._sync_boxing_readouts()
        self._status.showMessage(
            "Lens shape locked — type A/B to resize, or DBL to move the lenses."
            if on else "Lens shape unlocked — spline editing re-enabled.")

    def _resize_locked_lens(self, target_a, target_b):
        """Resize every LENS curve to the given finished target(s); a None target
        leaves that axis untouched.  Pure-computes first so a no-op never pushes
        an undo step."""
        ws = self._active_ws
        from .resize import size_to_finished_ab
        from .boxing import lens_bbox
        lenses = [c for c in ws.doc_curves
                  if c.layer == Layer.LENS and not c.mirrored and c.nodes]
        if not lenses:
            return
        axis_x = ws.scene.mirror.x if ws.scene.mirror else 0.0
        depth = ws.bevel_depth

        # Bare-shape width/height change of the representative lens — drives the
        # outline's constant-wall co-resize.
        rep_bb = lens_bbox(lenses[0])
        dW = (target_a - 2 * depth - (rep_bb[2] - rep_bb[0])) if target_a is not None else 0.0
        dH = (target_b - 2 * depth - (rep_bb[3] - rep_bb[1])) if target_b is not None else 0.0

        plans = []
        for c in lenses:
            new_c = size_to_finished_ab(c, target_a, target_b, depth, axis_x)
            if new_c is not None:
                plans.append((c, new_c))

        out_plans = []
        if ws.outline_locked and (abs(dW) > 1e-9 or abs(dH) > 1e-9):
            out_curves = [c for c in ws.doc_curves
                          if c.layer == Layer.OUTLINE and not c.mirrored and c.nodes]
            if out_curves:
                out_plans = self._outline_resize_plan(out_curves, axis_x, dW, dH)

        if not plans and not out_plans:
            return
        self._push_undo_snapshot()
        self._edit_tool.clear()
        new_sel = []
        for old_c, new_c in plans:
            new_c.layer    = old_c.layer
            new_c.group_id = old_c.group_id
            self._active_ws.remove_curve(old_c)
            new_sel.append(self._active_ws.add_curve(new_c))
        for old_c, new_c in out_plans:
            self._active_ws.remove_curve(old_c)
            self._active_ws.add_curve(new_c)
        self.scene.clearSelection()
        for it in new_sel:
            it.setSelected(True)
        ws.boxing_guide.refresh()
        self._refresh_measurements()
        self._sync_boxing_readouts()
        self._mark_dirty()

    def _finished_box_values(self):
        """(A, B, DBL) finished values stashed by the last _refresh_measurements."""
        a = getattr(self, "_snap_a", None)
        if a is None:
            return None
        return (a, getattr(self, "_snap_b", None), getattr(self, "_snap_dbl", None))

    def _sync_boxing_readouts(self):
        """Push the stashed finished A/B/DBL into the spinboxes (read-out display).
        Caller must have run _refresh_measurements first."""
        vals = self._finished_box_values() or (None, None, None)
        for spin, val in zip(
                (self._boxing_a_spin, self._boxing_b_spin, self._boxing_dbl_spin),
                vals, strict=True):
            spin.blockSignals(True)
            if val is None:
                # Nothing to read: "—", not the free box's values, which the
                # gray fields went on showing with no lens drawn.
                spin.setSpecialValueText("—")
                spin.setValue(spin.minimum())
            else:
                spin.setSpecialValueText("")
                spin.setValue(max(spin.minimum(), min(spin.maximum(), val)))
            spin.blockSignals(False)

    def _schedule_boxing_follow(self, ws):
        """Coalesce live geometry changes (node edits, moves) into one update.

        Drives the live Properties-tab measurements on every edit, and — when
        boxing is snapped — also the guide that follows the lens geometry."""
        if ws is not self._active_ws:
            return
        if not getattr(self, "_boxing_follow_pending", False):
            self._boxing_follow_pending = True
            QTimer.singleShot(0, self, self._do_boxing_follow)

    def _do_boxing_follow(self):
        self._boxing_follow_pending = False
        ws = self._active_ws
        # Live measurements track node drags / moves regardless of snap state,
        # and so does the readiness dot (closing an outline's gap by dragging
        # its end node left the dot amber with the old gap in its tooltip).
        # The validator waits for the button's release, though: it ran on
        # every drag tick, 14-24 ms a tick on a dense drawing.
        self._refresh_measurements()
        # Deferred only while the canvas holds the mouse (a drag there): a
        # press held elsewhere, on a spin box's arrow say, never reached the
        # canvas's release, and the dot kept its old color.
        grabber = QWidget.mouseGrabber()
        on_canvas = grabber is not None and grabber in (self.view, self.view.viewport())
        if on_canvas and QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self._readiness_deferred = True
        else:
            self._update_readiness()
        if ws.boxing_snapped:
            ws.boxing_guide.refresh()
            self._sync_boxing_readouts()

    def _on_bevel_preset_changed(self, idx: int):
        ws = self._active_ws
        key = self._bevel_choices[idx][1]
        ws.bevel_preset = key
        is_custom = (key == "custom")
        self._bevel_depth_spin.setEnabled(is_custom)
        if not is_custom:
            self._bevel_depth_spin.blockSignals(True)
            self._bevel_depth_spin.setValue(BEVEL_PRESETS.get(key, 0.0))
            self._bevel_depth_spin.blockSignals(False)
        ws.bevel_depth = self._current_bevel_depth()
        ws.boxing_guide.set_bevel_depth(ws.bevel_depth)
        self._refresh_measurements()
        if ws.boxing_snapped:
            self._sync_boxing_readouts()
        self._mark_dirty()

    def _on_bevel_depth_changed(self, v: float):
        ws = self._active_ws
        ws.bevel_depth = v
        ws.boxing_guide.set_bevel_depth(v)
        self._refresh_measurements()
        if ws.boxing_snapped:
            self._sync_boxing_readouts()
        self._mark_dirty()

    def _translate_curve(self, curve, dx: float, dy: float):
        """Translate all nodes (and their control points) of *curve* by (dx, dy) mm."""
        for node in curve.nodes:
            node.x += dx
            node.y += dy
            if node.cp_in:
                node.cp_in  = ControlPoint(node.cp_in.x  + dx, node.cp_in.y  + dy)
            if node.cp_out:
                node.cp_out = ControlPoint(node.cp_out.x + dx, node.cp_out.y + dy)

    def _translate_dim(self, dim, dx: float, dy: float):
        """Translate a DimLine by (dx, dy) and refresh its scene item."""
        dim.x0 += dx;  dim.y0 += dy
        dim.x1 += dx;  dim.y1 += dy
        item = self.scene._dim_items.get(id(dim))
        if item:
            item.prepareGeometryChange()
            item.update()

    def _pre_move_selected(self):
        """Called once when a drag-to-move starts (threshold exceeded)."""
        self._push_undo_snapshot()
        self._edit_tool.clear()
        # Prefer items captured at press time: super().mousePressEvent() may have
        # reselected the topmost item (e.g. outline) even though the user's intent was
        # to move an alt-clicked lower item (e.g. lens). If the press captured an
        # explicit pre-click selection, use that; otherwise fall back to current selection.
        items = self.view._drag_move_items or self.scene.selectedItems()
        self._drag_moving_curves = self._with_group_members(
            [it.curve for it in items if isinstance(it, CurveItem)])
        self._drag_moving_dims   = [it.dim      for it in items
                                    if isinstance(it, DimItem)]
        self._drag_moving_texts  = [it.text_obj for it in items
                                    if isinstance(it, TextItem)]

    def _move_selected_by(self, dx: float, dy: float):
        """Translate the currently tracked selected geometry by (dx, dy) mm."""
        for curve in self._drag_moving_curves:
            self._translate_curve(curve, dx, dy)
            self.scene.refresh_curve(curve)
        for dim in self._drag_moving_dims:
            self._translate_dim(dim, dx, dy)
        for t in self._drag_moving_texts:
            t.anchor_x += dx
            t.anchor_y += dy
            self.scene.move_text(t)      # translation only — no glyph rebuild
        # Keep the gizmo centered on the moving geometry
        if self._move_gizmo is not None:
            new_c = QPointF(self._move_gizmo_center.x() + dx,
                            self._move_gizmo_center.y() + dy)
            self._move_gizmo_center = new_c
            self._move_gizmo.set_center(new_c)

    def _end_move_selected(self):
        """Rebuild edit handles after drag-to-move; restore the moved items as selection."""
        # Collect the scene items that correspond to the curves that were actually moved.
        moved_items = [self.scene._curve_items.get(id(c))
                       for c in self._drag_moving_curves]
        moved_items += [self.scene._dim_items.get(id(d))
                        for d in self._drag_moving_dims]
        moved_items += [self.scene._text_items.get(id(t))
                        for t in self._drag_moving_texts]
        moved_items = [it for it in moved_items if it is not None]

        # Re-select the moved curves. Qt may have reselected the topmost item during
        # the initial press; blockSignals prevents redundant _on_selection_changed calls.
        if moved_items:
            self.scene.blockSignals(True)
            self.scene.clearSelection()
            for it in moved_items:
                it.setSelected(True)
            self.scene.blockSignals(False)

        # Rebuild edit handles only for a single moved curve — a multi-curve
        # selection stays rigid (no node dots), matching EditTool._on_selection
        # so a follow-up drag can't grab and endpoint-snap a node.
        self._edit_tool.clear()
        if len(moved_items) == 1 and isinstance(moved_items[0], CurveItem):
            self._edit_tool._add_curve_items(moved_items[0])

        self._drag_moving_curves = []
        self._drag_moving_dims   = []
        self._drag_moving_texts  = []

        # Sync the Layers panel row and info label with the restored selection.
        if moved_items:
            self._on_selection_changed()

    def _gizmo_center_from_selection(self) -> QPointF | None:
        """Return the gizmo origin: bounding-box center of the selected
        curves and text objects."""
        xs, ys = [], []
        for it in self.scene.selectedItems():
            if isinstance(it, CurveItem):
                for node in it.curve.nodes:
                    xs.append(node.x)
                    ys.append(node.y)
            elif isinstance(it, TextItem):
                r = it.sceneBoundingRect()
                xs += [r.left(), r.right()]
                ys += [r.top(), r.bottom()]
        if not xs:
            return None
        return QPointF((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def _show_move_gizmo(self):
        """Show the move gizmo at the current selection center (no-op if nothing selected)."""
        center = self._gizmo_center_from_selection()
        if center is None:
            self._status.showMessage("Move gizmo: nothing selected")
            return
        self._hide_move_gizmo()   # remove any existing gizmo first
        from .canvas.move_gizmo import MoveGizmo
        self._move_gizmo_center = center
        self._move_gizmo = MoveGizmo(
            self.scene, self.view, center,
            on_pre_move = self._pre_move_selected,
            on_move     = self._move_selected_by,
            on_move_end = self._end_move_selected,
        )
        mk = self._hotkey_prefs.get("move_gizmo", "").strip()
        self._status.showMessage(
            "Move gizmo active  |  drag arrow to move  |  click arrow for exact "
            f"distance  |  {mk + ' or Esc' if mk else 'Esc'} to dismiss")

    def _hide_move_gizmo(self):
        if self._move_gizmo is not None:
            self._move_gizmo.remove()
            self._move_gizmo = None

    def _drop_orphan_gizmo(self, ws: "WorkspaceState"):
        """A tab's gizmo goes with its selection, the tab active or not:
        Temple Copy, New and Open clear another tab's selection, and its gizmo
        stayed up over nothing, where a typed move pushed an empty undo step
        and starred the design. (_on_selection_changed serves the active tab.)"""
        if ws is self._active_ws or ws.move_gizmo is None:
            return
        if not any(isinstance(i, (CurveItem, DimItem, TextItem))
                   for i in ws.scene.selectedItems()):
            ws.move_gizmo.remove()
            ws.move_gizmo = None

    def _toggle_move_gizmo(self):
        if self._move_gizmo is not None:
            self._hide_move_gizmo()
        else:
            self._show_move_gizmo()

    # Toolbar visibility + hotkey management
    # ------------------------------------------------------------------

    # Actions restricted to certain workspaces. Final visibility is the AND
    # of the user's toolbar pref and this rule.
    _WS_ONLY_ACTIONS = _WS_ONLY_ACTIONS

    def _apply_toolbar_visibility(self, toolbar_prefs: dict, ws_type: str | None = None):
        """Show/hide toolbar actions: user prefs AND per-workspace rules.

        Both inputs must be applied together — applying prefs alone (the old
        Settings-dialog path) resurrected workspace-hidden buttons (e.g.
        Mirror Copy on Front) until the next tab switch, and applying
        workspace rules alone resurrected pref-hidden buttons on tab switch.
        """
        if ws_type is None:
            ws_type = self._active_ws.workspace_type
        for key, act in self._toolbar_actions.items():
            if key == "select":
                act.setVisible(True)
                continue
            visible = toolbar_prefs.get(key, True)
            allowed = self._WS_ONLY_ACTIONS.get(key)
            if allowed is not None:
                visible = visible and (ws_type in allowed)
            act.setVisible(visible)

    def _hotkey_dispatch(self, target):
        """Run a hotkey target unless a text-entry widget has focus.

        Hotkeys are single letters (L, S, E, …) with window-wide scope; without
        this guard they fire while the user is typing in a HUD line edit
        (MeasureBar, Point Move X/Y, Move gizmo distance).
        """
        from PySide6.QtWidgets import QAbstractSpinBox
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QAbstractSpinBox)):
            return
        target()

    def _apply_hotkeys(self, hotkey_prefs: dict):
        """Tear down existing hotkey QShortcuts and rebuild from hotkey_prefs."""
        from PySide6.QtGui import QShortcut, QKeySequence
        for sc in self._shortcuts.values():
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()
        self._square_seq = None
        self._refresh_hotkey_tooltips(hotkey_prefs)
        for key, target in self._hotkey_targets.items():
            key_str = hotkey_prefs.get(key, "").strip()
            if not key_str:
                continue
            if key_str in SettingsDialog._RESERVED_KEYS or key_str in _TYPING_KEYS:
                # An older prefs file can hold a key that is now fixed (Ctrl+O)
                # or read by the tools: bound twice, Qt fires neither.
                continue
            if key in _TEXT_FIELD_HOTKEYS:
                # NOT a QShortcut: application-context shortcuts go dead
                # while a modal dialog blocks their parent window, and this
                # binding is needed exactly there (bookmark names, library
                # saves, the engraving text dialog). The QApplication event
                # filter (eventFilter below) matches the sequence instead.
                self._square_seq = QKeySequence(key_str)
                continue
            sc = QShortcut(QKeySequence(key_str), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(
                lambda t=target: self._hotkey_dispatch(t))
            self._shortcuts[key] = sc

    def _refresh_hotkey_tooltips(self, hotkey_prefs: dict):
        for key, act in (("line", self._act_line), ("spline", self._act_spline),
                         ("circle", self._act_circle), ("arc", self._act_arc),
                         ("arc_sec", self._act_arc_sec), ("fillet", self._act_fillet),
                         ("dim", self._act_dim), ("trim", self._act_trim),
                         ("split_curve", self._act_split_curve),
                         ("offset", self._act_offset), ("rebuild", self._act_rebuild),
                         ("point_move", self._act_point_move), ("text", self._act_text),
                         ("snap_node_ep", self._act_snap_ep), ("join", self._act_join),
                         ("obverse", self._act_obverse)):
            key_str = hotkey_prefs.get(key, "").strip()
            if key_str in SettingsDialog._RESERVED_KEYS or key_str in _TYPING_KEYS:
                key_str = ""                      # not bound (see _apply_hotkeys)
            # Built from the tooltip as written (its typed "(X)" dropped once),
            # never from the last result: a key like "/" or "Num+5" that the
            # pattern cannot strip otherwise piled up one more per OK.
            bases = self.__dict__.setdefault("_tip_bases", {})
            base = bases.setdefault(key, _tip_with_key(act.toolTip(), ""))
            act.setToolTip(_tip_with_key(base, key_str))

    def eventFilter(self, obj, event):
        """App-wide filter — installed on the QApplication, so this runs for
        every event the app delivers. A single Settings apply pushes ~12,000
        events through it, so it must stay one event.type() and an early
        fall-through.

        Never import inside this function. `from PySide6...` here runs
        shiboken's import hook on every one of those events; that is what hung
        the macOS Intel runner for the whole 120s test timeout, with the
        traceback parked in shibokensupport feature_imported underneath
        setStyleSheet re-polishing every widget. The import shipped in v1.1.0
        and only ever cost throughput until a slow runner turned it into a
        stall.
        """
        etype = event.type()
        if etype == QEvent.Type.KeyPress:
            # □ insertion (see _apply_hotkeys for why this is not a QShortcut).
            # getattr: the swatch button installs this filter while the side
            # panel is built, before _apply_hotkeys binds the sequence.
            if (_matches_key_event(getattr(self, "_square_seq", None), event)
                    and self._insert_square_char()):
                return True
        elif (etype == QEvent.Type.Resize
                and obj in getattr(self, "_swatch_btn_texts", ())):
            self._elide_swatch_btn(obj)
        return super().eventFilter(obj, event)

    def _insert_square_char(self) -> bool:
        """Type "□" (U+25A1) into the focused text field — the boxing square
        of frame-size notation A□DBL-TempleLength (e.g. 49□27-145).
        Returns True when inserted (eventFilter consumes the key press)."""
        fw = QApplication.focusWidget()
        # The hotkey-recording field must SEE the combo, not get a □ typed.
        if isinstance(fw, KeyCaptureEdit):
            return False
        return _insert_text_into(fw, "□")

    # ------------------------------------------------------------------
    # Toolbar icon refresh (called on build and on theme change)
    # ------------------------------------------------------------------

    def _apply_toolbar_icons(self, dark: bool):
        normal_c  = theme.color("chrome.ink")
        checked_c = theme.color("chrome.checked_ink")
        pairs = [
            (self._act_select,       "tool-select"),
            (self._act_line,         "tool-line"),
            (self._act_spline,       "tool-spline"),
            (self._act_circle,       "tool-circle"),
            (self._act_arc,          "tool-arc"),
            (self._act_arc_sec,      "tool-arc-sec"),
            (self._act_fillet,       "op-fillet"),
            (self._act_dim,          "tool-dim"),
            (self._act_mirror,       "toggle-mirror"),
            (self._act_guides,       "toggle-guides"),
            (self._act_snap,         "toggle-snap"),
            (self._act_snap_palette, "toggle-snap-palette"),
            (self._act_grid,         "toggle-grid"),
            (self._act_smooth,       "toggle-smooth"),
            (self._act_boxing,       "toggle-boxing"),
            (self._act_stock,        "toggle-stock"),
            (self._act_pad,          "toggle-pad"),
            (self._act_obverse,      "view-obverse"),
            (self._act_mirror_close, "op-mirror-close"),
            (self._act_dup_mirror,   "op-dup-mirror"),
            (self._act_copy_temple,  "op-copy-temple"),
            (self._act_join,         "op-join"),
            (self._act_snap_ep,      "op-snap-node"),
            (self._act_split,        "op-split"),
            (self._act_explode,      "op-explode"),
            (self._act_fit,          "op-fit"),
            (self._act_trim,         "tool-trim"),
            (self._act_split_curve,  "tool-split-curve"),
            (self._act_offset,       "tool-offset"),
            (self._act_rebuild,      "tool-rebuild"),
            (self._act_point_move,   "tool-point-move"),
            (self._act_text,         "tool-text"),
            (self._act_panel,        "view-sidebar"),
            (self._act_tooltips,     "toggle-tooltips"),
        ]
        for act, name in pairs:
            svg = _ICONS_DIR / f"{name}.svg"
            if svg.exists():
                act.setIcon(_make_icon(name, normal_c, checked_c))
        if (_ICONS_DIR / "link-chain.svg").exists():
            for attr in ("_chain_btn", "_lens_link_btn"):
                btn = getattr(self, attr, None)
                if btn is not None:
                    btn.setIcon(_make_icon("link-chain", normal_c, checked_c))
        self._refresh_mirror_icons()

    def _refresh_mirror_icons(self):
        """Re-render ghost and mirror-close icons rotated 90° for temple workspaces."""
        normal_c  = theme.color("chrome.ink")
        checked_c = theme.color("chrome.checked_ink")
        ws_type = self._active_ws.workspace_type if self._workspaces else "front"
        rot = 90 if ws_type in ("temple_r", "temple_l") else 0
        if (_ICONS_DIR / "toggle-mirror.svg").exists():
            self._act_mirror.setIcon(
                _make_icon("toggle-mirror", normal_c, checked_c, rotation=rot))
        if (_ICONS_DIR / "op-mirror-close.svg").exists():
            self._act_mirror_close.setIcon(
                _make_icon("op-mirror-close", normal_c, checked_c, rotation=rot))

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def _build_menus(self):
        mb = self.menuBar()

        from PySide6.QtGui import QKeySequence
        file_menu = mb.addMenu("&File")
        # New / Open / Quit and the zooms had no shortcuts at all. Kept on
        # self: a text+slot addAction's wrapper is Python-owned (see Ctrl+,).
        self._act_new = file_menu.addAction("New", self._new)
        self._act_new.setShortcut(QKeySequence("Ctrl+N"))
        self._act_open = file_menu.addAction("Open…", self._open)
        self._act_open.setShortcut(QKeySequence("Ctrl+O"))
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._recent_menu.setToolTipsVisible(True)
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        # Real shortcuts (not tab-text like Undo/Redo) so the menu shows the
        # key AND the binding works window-wide through Qt's action system.
        act_save = file_menu.addAction("Save", self._save)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save_as = file_menu.addAction("Save As…", self._save_as)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction("Add Reference Image…", self._add_face)
        file_menu.addSeparator()
        imp = file_menu.addMenu("Import")
        imp.addAction("DXF…", self._import_dxf)
        imp.addAction("SVG…", self._import_svg)
        imp.addAction("OMA Lens Trace…", self._import_oma)
        exp = file_menu.addMenu("Export")
        # "This Tab" / "Every Tab": the first three export the tab in view
        # only, and the menu used not to say so.
        exp.addAction("DXF of This Tab…", self._export_dxf)
        exp.addAction("DXF of Every Tab…", self._export_all_dxf)
        exp.addAction("SVG of This Tab…", self._export_svg)
        exp.addAction("PNG of This Tab…", self._export_png)
        exp.addAction("OMA Lens Trace…", self._export_oma)
        exp.addSeparator()
        exp.addAction("PDF (1:1 Scale)…", self._export_pdf_1to1)
        exp.addAction("PDF Front + Temples (1:1 Templates)…",
                      self._export_pdf_templates)
        exp.addAction("PDF for Catalog…", self._export_pdf_catalog)
        exp.addAction("Catalog PDFs for a Folder…", self._export_catalog_folder)
        file_menu.addSeparator()
        file_menu.addAction("Print at 1:1 Scale…", self._print_1to1)
        file_menu.addAction("Print Front + Temples (1:1 Templates)…",
                            self._print_templates)
        file_menu.addSeparator()
        self._act_quit = file_menu.addAction("Quit", self.close)
        self._act_quit.setShortcut(QKeySequence("Ctrl+Q"))

        edit_menu = mb.addMenu("&Edit")
        self._act_undo = edit_menu.addAction("Undo\tCtrl+Z", self._handle_undo)
        self._act_undo.setEnabled(False)
        self._act_redo = edit_menu.addAction("Redo\tCtrl+Y", self._redo)
        self._act_redo.setEnabled(False)
        edit_menu.addSeparator()
        edit_menu.addAction("Copy\tCtrl+C",        self._copy_selected)
        edit_menu.addAction("Paste\tCtrl+V",       self._paste)
        edit_menu.addAction("Duplicate\tCtrl+D",   self._duplicate_selected)
        edit_menu.addAction("Delete\tDel",        self._delete_selected)
        edit_menu.addAction("Select All\tCtrl+A",  self._select_all)
        edit_menu.addAction("Transform…\tCtrl+T",  self._transform_selected)
        self._menu_move_gizmo = edit_menu.addAction("Move Gizmo",
                                                    self._toggle_move_gizmo)
        edit_menu.addSeparator()
        edit_menu.addAction("Group\tCtrl+G", self._group_selected)
        edit_menu.addAction("Ungroup\tCtrl+Shift+G", self._ungroup_selected)
        edit_menu.addSeparator()
        # Every operation on the tool bar, here too: a button hidden in
        # Preferences ▸ Toolbar left Mirror, Split and the rest with no way to
        # reach them. Each entry follows its button (enabled, per-tab rules).
        modify = edit_menu.addMenu("Modify")
        self._modify_menu = modify        # kept, as _recent_menu is
        self._modify_menu_ops: dict[str, tuple[QAction, QAction]] = {}
        for key, label, act in (
                ("mirror",       "Mirror (Bake the Ghost)", self._act_dup_mirror),
                ("mirror_close", "Mirror Close",            self._act_mirror_close),
                ("copy_temple",  "Temple Copy",             self._act_copy_temple),
                ("join",         "Join",                    self._act_join),
                ("snap_node",    "Snap Node to Endpoint",   self._act_snap_ep),
                ("split",        "Split at Node",           self._act_split),
                ("explode",      "Explode",                 self._act_explode)):
            proxy = QAction(label, self)
            proxy.setToolTip(act.toolTip())
            proxy.triggered.connect(lambda _checked=False, a=act: a.trigger())
            modify.addAction(proxy)
            self._modify_menu_ops[key] = (proxy, act)
        modify.aboutToShow.connect(self._sync_modify_menu)
        edit_menu.aboutToShow.connect(self._sync_edit_menu)

        view_menu = mb.addMenu("&View")
        self._act_zoom_in = view_menu.addAction(
            "Zoom In", lambda: self.view.zoom_by(1.2))
        self._act_zoom_in.setShortcuts([QKeySequence("Ctrl++"),
                                        QKeySequence("Ctrl+=")])
        self._act_zoom_out = view_menu.addAction(
            "Zoom Out", lambda: self.view.zoom_by(1 / 1.2))
        self._act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self._act_fit_menu = view_menu.addAction("Fit to Drawing", self._fit_view)
        self._act_fit_menu.setShortcut(QKeySequence("Ctrl+0"))
        view_menu.addSeparator()
        # The menu's own entries for the toggles, following the toolbar's
        # each time the menu opens. Sharing the toolbar's QActions meant that
        # hiding the button in Preferences ▸ Toolbar hid the menu entry too —
        # and Ghost has no hotkey, so nothing could switch it any more. Every
        # toggle on the bar is here, for the same reason.
        self._view_menu_toggles: dict[str, tuple[QAction, QAction]] = {}
        for key, label, act in (
                ("ghost",        "Ghost",               self._act_mirror),
                ("obverse",      "View Obverse",        self._act_obverse),
                (None, None, None),
                ("guides",       "Construction Guides", self._act_guides),
                ("boxing",       "Boxing Guide",        self._act_boxing),
                ("stock",        "Stock Guide",         self._act_stock),
                ("pad",          "Pad Guide",           self._act_pad),
                ("grid",         "Grid",                self._act_grid),
                (None, None, None),
                ("snap",         "Snap",                self._act_snap),
                ("snap_palette", "Snap Types",          self._act_snap_palette),
                ("smooth",       "Smooth Handles",      self._act_smooth)):
            if key is None:
                view_menu.addSeparator()
                continue
            proxy = QAction(label, self, checkable=True)
            proxy.setToolTip(act.toolTip())
            proxy.triggered.connect(lambda checked, a=act: a.setChecked(checked))
            view_menu.addAction(proxy)
            self._view_menu_toggles[key] = (proxy, act)
        view_menu.aboutToShow.connect(self._sync_view_menu_toggles)
        view_menu.addSeparator()
        view_menu.addAction(
            "Revision History",
            lambda: (self._prop_dock.show(), self._side_tabs.setCurrentIndex(3)),
        )
        # Its own entry, with a check mark: the dock's toggle action carries
        # the toolbar's icon, which a menu draws in place of the check.
        self._menu_panel = QAction("Properties Panel", self, checkable=True)
        # Through a lambda: bound straight to the dock's C++ setVisible,
        # PySide6 picked triggered's no-argument overload, and every click
        # raised a TypeError and left the panel as it was.
        self._menu_panel.triggered.connect(
            lambda on: self._prop_dock.setVisible(on))
        view_menu.addAction(self._menu_panel)

        settings_menu = mb.addMenu("&Settings")
        self._act_dark = QAction("Dark Mode", self, checkable=True, checked=False)
        self._act_dark.triggered.connect(self._toggle_dark_mode)
        settings_menu.addAction(self._act_dark)
        settings_menu.addSeparator()
        # Ctrl+, — the ecosystem-wide Preferences shortcut (GuildSend set the
        # convention; GuildDraw and GuildModel now match). Kept on self: a
        # text+slot addAction's wrapper is Python-owned in PySide6, and losing
        # the last reference deletes the underlying QAction.
        self._act_prefs = settings_menu.addAction(
            "Preferences…", self._open_settings)
        self._act_prefs.setShortcut(QKeySequence("Ctrl+,"))

        help_menu = mb.addMenu("&Help")
        self._act_about = help_menu.addAction("&About GuildDraw", self._on_about)

    def _on_about(self):
        """Help ▸ About GuildDraw, as GuildModel's Help ▸ About GuildModel."""
        QMessageBox.about(
            self, "About GuildDraw",
            f"<b>GuildDraw</b> v{__version__}<br><br>"
            "Free, open-source 2D drafting for acetate and horn eyewear, at "
            "true millimeters: a frame front, its temples and the components "
            "they carry, checked against a calibrated face photo.<br><br>"
            "Companion to GuildModel, which turns a GuildDraw design into "
            "toolpaths. The two never start each other: the hand-off is the "
            ".gdraw file you open.<br><br>"
            "GPLv3 — see LICENSE for details.")

    # The hotkey a menu entry shows, by its key in prefs["hotkeys"].
    _MENU_HOTKEYS = {"obverse": "obverse", "join": "join",
                     "snap_node": "snap_node_ep"}

    def _menu_label(self, proxy: QAction, key: str) -> None:
        """Show the entry's current hotkey after a tab, as Qt lays out a
        shortcut, without binding it twice (the QShortcut owns the key)."""
        base = proxy.text().split("\t")[0]
        hk = self._MENU_HOTKEYS.get(key)
        key_str = getattr(self, "_hotkey_prefs", {}).get(hk, "").strip() if hk else ""
        proxy.setText(f"{base}\t{key_str}" if key_str else base)

    def _sync_modify_menu(self):
        ws_type = self._active_ws.workspace_type
        for key, (proxy, _act) in self._modify_menu_ops.items():
            proxy.setEnabled(self._op_available(key))
            allowed = _WS_ONLY_ACTIONS.get(key)
            proxy.setVisible(allowed is None or ws_type in allowed)
            self._menu_label(proxy, key)

    def _on_obverse_toggled(self, on: bool):
        """View Obverse turns the active tab's view only: a front and a temple
        may be seen from opposite faces at once."""
        ws = self._active_ws
        face = _OBVERSE_FACE.get(ws.workspace_type)
        if face is None:
            # The Component tab's button is hidden, but its hotkey still
            # triggers the action: a component has no other face to show.
            self._act_obverse.blockSignals(True)
            self._act_obverse.setChecked(False)
            self._act_obverse.blockSignals(False)
            return
        ws.obverse = on
        ws.view.set_obverse(on, face)

    def _sync_view_menu_toggles(self):
        ws_type = self._active_ws.workspace_type
        for key, (proxy, act) in self._view_menu_toggles.items():
            proxy.blockSignals(True)
            proxy.setChecked(act.isChecked())
            proxy.blockSignals(False)
            allowed = _WS_ONLY_ACTIONS.get(key)
            proxy.setVisible(allowed is None or ws_type in allowed)
            self._menu_label(proxy, key)
        self._menu_panel.setChecked(self._prop_dock.isVisible())

    def _sync_edit_menu(self):
        mk = getattr(self, "_hotkey_prefs", {}).get("move_gizmo", "").strip()
        self._menu_move_gizmo.setText(f"Move Gizmo\t{mk}" if mk else "Move Gizmo")

    # ------------------------------------------------------------------
    # Tool switching
    # ------------------------------------------------------------------

    def _current_layer(self) -> Layer:
        return self._active_ws.active_layer

    def _deactivate_cursor_tools(self):
        """Deactivate the cursor tools (trim, fillet, split, offset, rebuild,
        point move) and clear their state."""
        self._trim_tool.deactivate()
        self._fillet_tool.deactivate()
        self._split_tool.deactivate()
        self._offset_tool.deactivate()
        self._rebuild_tool.deactivate()
        self._point_move_tool.deactivate()

    def _teardown_tools(self, clear_selection: bool):
        """Single teardown path for ALL tool switches.

        Every _set_tool_* must call this first. The per-setter teardown
        dances drifted apart repeatedly (stale Offset HUD, undeactivated
        tools) — never deactivate tools individually in a setter again.

        clear_selection=False for tools that operate on the current
        selection (Select keeps it for inspection; Offset/Point Move
        consume it).
        """
        self._draw_tool.deactivate()
        self.view.set_draw_tool(None)
        self._circle_tool.deactivate()
        self._dim_tool.deactivate()
        self.view.set_dim_tool(None)
        self._text_tool.deactivate()
        self._deactivate_cursor_tools()
        # Calibration too: armed, it outranks every tool in the view's press
        # handler, so after pressing L the next clicks still calibrated.
        if self._calib_tool.active:
            self._calib_tool.cancel(self.scene)
        self.view.measure_bar.hide_bar()
        if clear_selection:
            self._edit_tool.clear()
            self.scene.clearSelection()
        # The draw tool just deactivated — gray out the context snaps. A
        # line/spline setter re-enables them right after (below).
        self._update_snap_context()

    def _set_tool_select(self):
        self._teardown_tools(clear_selection=False)
        self._status.showMessage("Select: click a curve to select and show nodes")

    def _ask_to_act(self, title: str, text: str, act: str) -> bool:
        """A question with one action button, the default, and Cancel."""
        box = QMessageBox(QMessageBox.Icon.Question, title, text,
                          QMessageBox.StandardButton.Cancel, self)
        go = box.addButton(act, QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(go)
        box.exec()
        return box.clickedButton() is go

    def _layer_ready_to_draw(self, layer: Layer) -> bool:
        """A drawing tool on a hidden or locked layer asks first: a circle
        drawn on hidden LENS vanished on finish, and a line drawn on locked
        OUTLINE could never be selected. The answer shows or unlocks the
        layer; Cancel goes back to Select."""
        hidden = not self.scene.is_layer_visible(layer)
        locked = self.scene.is_layer_locked(layer)
        if not hidden and not locked:
            return True
        name = layer.value
        if hidden and locked:
            title, act = "Layer Hidden and Locked", "Show and Unlock"
            text = (f"{name} is hidden and locked: a curve drawn on it would "
                    f"not show, and could not be selected. Show and unlock "
                    f"{name} to draw on it?")
        elif hidden:
            title, act = "Layer Hidden", f"Show {name}"
            text = (f"{name} is hidden: a curve drawn on it would not show. "
                    f"Show {name} to draw on it?")
        else:
            title, act = "Layer Locked", f"Unlock {name}"
            text = (f"{name} is locked: a curve drawn on it could not be "
                    f"selected or edited. Unlock {name} to draw on it?")
        if not self._ask_to_act(title, text, act):
            self._back_to_select(f"{name} is {'hidden' if hidden else 'locked'}: "
                                 "nothing drawn")
            return False
        if hidden:
            self.scene.set_layer_visible(layer, True)
        if locked:
            self.scene.set_layer_locked(layer, False)
        self._mark_dirty()                 # the layer flags are saved
        self._refresh_layer_panel()
        return True

    def _set_tool_line(self):
        if not self._layer_ready_to_draw(self._current_layer()):
            return
        self._teardown_tools(clear_selection=True)
        self._draw_tool.activate("line", self._current_layer(), self.scene,
                                 self.view, snap=self._snap,
                                 all_curves=self._doc_curves)
        self.view.set_draw_tool(self._draw_tool)
        self._update_snap_context()

    def _set_tool_spline(self):
        if not self._layer_ready_to_draw(self._current_layer()):
            return
        self._teardown_tools(clear_selection=True)
        self._draw_tool.activate("spline", self._current_layer(), self.scene,
                                 self.view, snap=self._snap,
                                 all_curves=self._doc_curves)
        self.view.set_draw_tool(self._draw_tool)
        self._update_snap_context()

    def _set_tool_circle(self):
        if not self._layer_ready_to_draw(self._current_layer()):
            return
        self._teardown_tools(clear_selection=True)
        self._circle_tool.activate("circle", self._current_layer(), self.scene,
                                   self.view, snap=self._snap,
                                   all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_arc(self):
        if not self._layer_ready_to_draw(self._current_layer()):
            return
        self._teardown_tools(clear_selection=True)
        self._circle_tool.activate("arc", self._current_layer(), self.scene,
                                   self.view, snap=self._snap,
                                   all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_arc_sec(self):
        if not self._layer_ready_to_draw(self._current_layer()):
            return
        self._teardown_tools(clear_selection=True)
        self._circle_tool.activate("arc_sec", self._current_layer(), self.scene,
                                   self.view, snap=self._snap,
                                   all_curves=self._doc_curves,
                                   measure_bar=self.view.measure_bar)
        self.view.set_draw_tool(self._circle_tool)

    def _set_tool_fillet(self):
        self._teardown_tools(clear_selection=True)
        self._fillet_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._fillet_tool)

    def _set_tool_dim(self):
        self._teardown_tools(clear_selection=True)
        self._dim_tool.activate(self.scene, self.view,
                                snap=self._snap, all_curves=self._doc_curves)
        self.view.set_dim_tool(self._dim_tool)

    def _set_tool_text(self):
        # ENGRAVING is a temple-workspace layer (toolbar hides the button
        # elsewhere, but the hotkey can still fire).
        if Layer.ENGRAVING not in WORKSPACE_LAYERS[self._active_ws.workspace_type]:
            self._back_to_select(
                "Text engraving is available in the Temple workspaces.")
            return
        if not self._layer_ready_to_draw(Layer.ENGRAVING):
            return
        self._teardown_tools(clear_selection=True)
        self._text_tool.activate(Layer.ENGRAVING, self.scene, self.view,
                                 self._active_ws.snap)
        self.view.set_draw_tool(self._text_tool)

    def _on_text_added(self, text_obj):
        self._push_undo_snapshot()
        self._active_ws.add_text(text_obj)
        self._act_select.setChecked(True)
        self._set_tool_select()
        self._status.showMessage(
            f"Text placed on {text_obj.layer.value} — drag to move, "
            "double-click to edit, Del to remove."
        )

    def _on_text_canceled(self):
        self._back_to_select()

    def _back_to_select(self, message: str | None = None):
        """Put the view and toolbar back in Select mode, keeping `message` —
        or, when None, whatever the tool last said — on show. Select's own
        prompt otherwise replaced a refusal ("select something first") or a
        tool's "canceled" the moment it appeared."""
        msg = self._status.currentMessage() if message is None else message
        self._act_select.setChecked(True)
        self._set_tool_select()
        if msg:
            self._status.showMessage(msg, 4000)

    def _on_draw_canceled(self):
        """Esc in Line/Spline/Circle/Arc/Dim: the tool has deactivated
        itself; put the view and toolbar back in Select mode (they used to
        keep routing to the dead tool, so nothing was selectable until the
        Select button was clicked). Keep the tool's own message on show."""
        self._back_to_select()

    def _edit_text_object(self, text_obj):
        """Double-click on a TextItem — re-open the dialog pre-filled."""
        dlg = TextDialog(self, text_obj, obverse=self.view.is_obverse())
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        if not v["text"].strip():
            self._status.showMessage(
                "Edit Text: empty text ignored — use Delete to remove the object.")
            return
        # Only what changed: OK on an untouched dialog pushed an undo step and
        # starred the design. TextDialog hands back the stored value of any
        # field left alone, so an exact comparison is the right one.
        changes = {k: v[k] for k in ("text", "family", "size_mm", "rotation",
                                     "anchor_x", "anchor_y")
                   if v[k] != getattr(text_obj, k)}
        if not changes:
            return
        self._push_undo_snapshot()
        for k, val in changes.items():
            setattr(text_obj, k, val)
        self.scene.refresh_text(text_obj)
        self._refresh_layer_panel()   # label shows the (now-changed) string
        self._status.showMessage("Text updated.")

    def _set_tool_trim(self):
        self._teardown_tools(clear_selection=True)
        self._trim_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._trim_tool)

    def _set_tool_split_curve(self):
        self._teardown_tools(clear_selection=True)
        self._split_tool.activate(self.scene, self.view, lambda: self._doc_curves)
        self.view.set_draw_tool(self._split_tool)

    # Why a shape tool leaves a placed component alone, as Insert Node does: a
    # group is one rigid part, and Trim, Split and Rebuild broke its members
    # out of it, dropping the group and the kind.
    _GROUPED_REFUSAL = ("the curve belongs to a group (a placed component); "
                        "ungroup it first (Ctrl+Shift+G)")

    def _on_trim_applied(self, original, remaining: list):
        if original.group_id:
            self._status.showMessage(f"Trim: {self._GROUPED_REFUSAL}", 6000)
            return
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self._active_ws.remove_curve(original)
        for c in remaining:
            self._active_ws.add_curve(c)

    def _on_split_applied(self, pairs: list):
        """Apply all splits from one click — [(original, [parts]), ...] —
        as a single undo step (an intersection split breaks several curves)."""
        if any(original.group_id for original, _parts in pairs):
            self._status.showMessage(f"Split: {self._GROUPED_REFUSAL}", 6000)
            return
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        for original, parts in pairs:
            self._active_ws.remove_curve(original)
            for c in parts:
                self._active_ws.add_curve(c)

    def _on_fillet_applied(self, line1, line2, new_curves: list):
        if line1.group_id or line2.group_id:
            self._status.showMessage(f"Fillet: {self._GROUPED_REFUSAL}", 6000)
            return
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self._active_ws.remove_curve(line1)
        self._active_ws.remove_curve(line2)
        for c in new_curves:
            self._active_ws.add_curve(c)

    def _on_trim_canceled(self):
        self._back_to_select()

    def _on_split_canceled(self):
        self._back_to_select()

    # ------------------------------------------------------------------
    # Offset tool
    # ------------------------------------------------------------------

    def _set_tool_offset(self):
        # Capture selection before teardown (deactivation may clear it)
        selected_curves = [
            item.curve for item in self.scene.selectedItems()
            if isinstance(item, CurveItem) and not item.curve.mirrored
        ]
        source = selected_curves[0] if len(selected_curves) == 1 else None

        self._teardown_tools(clear_selection=False)
        self._offset_tool.activate(self.scene, self.view, source)
        self.view.set_draw_tool(self._offset_tool)

    def _on_offset_applied(self, source_curve, offset_curve):
        # The offset belongs with its source: a clearance outline of a placed
        # hinge moves with the hinge and is of its kind.
        offset_curve.group_id = source_curve.group_id
        offset_curve.component_kind = (source_curve.component_kind
                                       if offset_curve.layer == Layer.COMPONENT
                                       else None)
        self._push_undo_snapshot()
        self._active_ws.add_curve(offset_curve)
        # Return to Select mode first (re-enables ItemIsSelectable on all items)
        self._act_select.setChecked(True)
        self._set_tool_select()
        # Now selection is possible — clear and select the new curve
        self.scene.clearSelection()
        item = self.scene._curve_items.get(id(offset_curve))
        if item is not None:
            item.setSelected(True)
        self._status.showMessage(
            f"Offset {offset_curve.layer.value} curve created — select + edit nodes to refine"
        )

    def _on_offset_canceled(self):
        self._back_to_select()

    # ------------------------------------------------------------------
    # Rebuild Spline tool (M31.2)
    # ------------------------------------------------------------------

    def _set_tool_rebuild(self):
        # Capture selection before teardown (deactivation may clear it).
        selected = [
            item.curve for item in self.scene.selectedItems()
            if isinstance(item, CurveItem) and not item.curve.mirrored
        ]
        source = selected[0] if len(selected) == 1 else None
        if source is not None and source.group_id:
            self._back_to_select(f"Rebuild: {self._GROUPED_REFUSAL}")
            return

        self._teardown_tools(clear_selection=False)
        self._rebuild_tool.activate(self.scene, self.view, source)
        self.view.set_draw_tool(self._rebuild_tool)

    def _on_rebuild_applied(self, source_curve, rebuilt_curve):
        # Rebuild REPLACES the source: the whole point is to swap a dense/heavy
        # curve for the clean one at the same place. Undoable, so Ctrl+Z brings
        # the original back.
        rebuilt_curve.component_kind = source_curve.component_kind
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()
        self._active_ws.remove_curve(source_curve)
        self._active_ws.add_curve(rebuilt_curve)
        # Return to Select mode (re-enables ItemIsSelectable), then select the new curve.
        self._act_select.setChecked(True)
        self._set_tool_select()
        self.scene.clearSelection()
        item = self.scene._curve_items.get(id(rebuilt_curve))
        if item is not None:
            item.setSelected(True)
        self._status.showMessage(
            f"Rebuilt to {len(rebuilt_curve.nodes)} nodes — select + edit to refine"
        )

    def _on_rebuild_canceled(self):
        self._back_to_select()

    # ------------------------------------------------------------------
    # Point Move tool
    # ------------------------------------------------------------------

    def _set_tool_point_move(self):
        # Capture the selection NOW: set_draw_tool() strips ItemIsSelectable
        # from every item, which clears the Qt selection out from under us.
        # Relying on the live selection (or on the view's stale drag-capture
        # list) is why Point Move only worked intermittently.
        sel = self.scene.selectedItems()
        self._pm_curves = self._with_group_members(
            [it.curve for it in sel if isinstance(it, CurveItem)])
        self._pm_dims   = [it.dim for it in sel if isinstance(it, DimItem)]
        self._pm_texts  = [it.text_obj for it in sel if isinstance(it, TextItem)]
        if not self._pm_curves and not self._pm_dims and not self._pm_texts:
            # Back to Select: a previous tool must not stay live.
            self._back_to_select("Point Move: select something first")
            return
        self._teardown_tools(clear_selection=False)
        self._point_move_tool.activate(self.scene, self.view,
                                        self._active_ws.snap)
        self.view.set_draw_tool(self._point_move_tool)

    def _on_point_moved(self, dx: float, dy: float):
        """Translate the selection captured at tool activation by (dx, dy)."""
        if dx == 0.0 and dy == 0.0:
            # No step to undo for a move of nothing.
            self._back_to_select("Point Move: the two points coincide; nothing moved")
            return
        self._push_undo_snapshot()
        self._edit_tool.clear()
        self._drag_moving_curves = list(self._pm_curves)
        self._drag_moving_dims   = list(self._pm_dims)
        self._drag_moving_texts  = list(getattr(self, "_pm_texts", []))
        self._move_selected_by(dx, dy)
        # Restore Select mode first so ItemIsSelectable is True before
        # _end_move_selected calls setSelected(True) on the moved items.
        self._act_select.setChecked(True)
        self._set_tool_select()
        self._end_move_selected()
        self._status.showMessage(
            f"Moved  Δx {dx:+.3f} mm  Δy {dy:+.3f} mm"
        )

    def _on_point_move_canceled(self):
        self._back_to_select()

    def _on_dim_added(self, dim: DimLine):
        self._push_undo_snapshot()
        self._active_ws.add_dim(dim)
        self._act_select.setChecked(True)
        self._set_tool_select()
        dist = math.hypot(dim.x1 - dim.x0, dim.y1 - dim.y0)
        self._status.showMessage(
            f"Dim placed: {dist:.2f} mm  (select + Del to remove)"
        )

    def _on_measure_commit_radius(self, radius_mm: float):
        """MeasureBar Enter: confirm circle radius or lock arc radius."""
        if not self._circle_tool.active:
            return
        self._circle_tool.set_radius_and_advance(radius_mm)
        self.view.setFocus()

    def _toggle_snap_palette(self, on: bool):
        if on:
            anchor = self._toolbar.widgetForAction(self._act_snap_palette)
            panel = self._toolbar.visible_panel()
            if panel is not None and (anchor is None or not anchor.isVisible()):
                anchor = panel.button_for(self._act_snap_palette) or anchor
            self._snap_palette.reposition(self._toolbar, anchor)
            if panel is not None:
                # Beside the pinned pop-out, not under it: both anchor at the
                # toolbar's edge, and the pop-out re-raises on every refresh.
                right = panel.geometry().right() + 4
                if self._snap_palette.x() < right:
                    self._snap_palette.move(right, self._snap_palette.y())
            self._update_snap_context()
            self._snap_palette.show()
            self._snap_palette.raise_()
        else:
            self._snap_palette.hide()

    def _update_snap_context(self):
        """Enable the palette's context snaps (tangent/perpendicular) only while
        a line/spline draw is active — they need a point being drawn."""
        pal = getattr(self, "_snap_palette", None)
        if pal is not None:
            pal.set_context_available(self._draw_tool.active)

    # ------------------------------------------------------------------
    # Grid overlay (global — same grid on every workspace)
    # ------------------------------------------------------------------

    def _apply_grid_config(self, save: bool = False):
        """Push grid visibility + spacing + appearance from prefs onto every
        view and every snap engine (grid snap uses the overlay spacing)."""
        visible     = bool(self._prefs.get("grid_visible", False))
        spacing     = float(self._prefs.get("grid_spacing_mm", 2.0))
        major       = int(self._prefs.get("grid_major", 5))
        minor_color = str(self._prefs.get("grid_minor_color", "") or "")
        major_color = str(self._prefs.get("grid_major_color", "") or "")
        major_width = float(self._prefs.get("grid_major_width_px", 1.0))
        for ws in self._workspaces:
            ws.view.set_grid(visible=visible, spacing_mm=spacing, major=major,
                             minor_color=minor_color, major_color=major_color,
                             major_width=major_width)
            # Grid snap only while the grid shows: shipped on with the grid
            # hidden, it pulled most clicks in empty space onto an invisible
            # 2 mm lattice.
            ws.snap.set_grid_spacing(spacing if visible else 0.0)
        if save:
            _prefs_mod.save(self._prefs)

    def _on_grid_toggled(self, on: bool):
        self._prefs["grid_visible"] = bool(on)
        spacing = float(self._prefs.get("grid_spacing_mm", 2.0))
        for ws in self._workspaces:
            ws.view.set_grid(visible=on)
            ws.snap.set_grid_spacing(spacing if on else 0.0)   # see above
        _prefs_mod.save(self._prefs)

    def _on_snap_types_changed(self, types: dict):
        """Palette toggles apply to every workspace and persist immediately."""
        for ws in self._workspaces:
            ws.snap.set_enabled_types(types)
        self._prefs["snap_types"] = dict(types)
        _prefs_mod.save(self._prefs)

    def _on_snap_radius_changed(self, px: int):
        for ws in self._workspaces:
            ws.snap.set_radius_px(px)
        self._prefs["snap_radius_px"] = int(px)
        _prefs_mod.save(self._prefs)

    def _on_mirror_toggled(self, on: bool):
        if self.scene.mirror:
            self.scene.mirror.set_enabled(on)
        self.scene.set_mirror_display(on)
        axis_x     = self.scene.mirror.x if self.scene.mirror else 0.0
        horizontal = (self._active_ws.workspace_type in ("temple_r", "temple_l"))
        self._snap.set_mirror(axis_x, on, horizontal=horizontal)
        self._boxing_guide.set_mirror(on)
        self._boxing_guide.set_axis_x(axis_x)
        # Keep the workspace flag live (measurements read it) — it used to be
        # written only when leaving the tab. mirror.enabled is saved with the
        # document, so this is an unsaved change.
        self._active_ws.mirror_enabled = on
        self._mark_dirty()
        self._update_readiness()   # the Ghost's twins are checked when it is on
        self._refresh_measurements()   # a half's width and DBL lean on the Ghost

    def _on_curve_added(self, curve):
        curve.line_weight = self._default_line_weight
        self._push_undo_snapshot()        # snapshot BEFORE the curve is added
        self._active_ws.add_curve(curve)  # (measurements refresh via _notify)
        # Return to select mode so the user can immediately inspect the new curve
        self._act_select.setChecked(True)
        self._set_tool_select()
        # The layer was switched mid-tool to a hidden or locked one (the tool
        # asked when it started): say so rather than lose the curve from view.
        if not self.scene.is_layer_visible(curve.layer):
            self._status.showMessage(
                f"The curve is on {curve.layer.value}, which is hidden: show "
                "it in the Layers panel to see it.", 8000)
        elif self.scene.is_layer_locked(curve.layer):
            self._status.showMessage(
                f"The curve is on {curve.layer.value}, which is locked: unlock "
                "it in the Layers panel to select it.", 8000)

    # ------------------------------------------------------------------
    # Layer re-labeling for selected curves
    # ------------------------------------------------------------------

    def _with_group_members(self, curves: list) -> list:
        """*curves* and every other curve of their groups: a group moves,
        turns, copies and deletes as one, its members on a hidden or locked
        layer too (they cannot be selected, and were left behind, splitting
        the group)."""
        gids = {c.group_id for c in curves if c.group_id}
        if not gids:
            return list(curves)
        have = {id(c) for c in curves}
        return list(curves) + [c for c in self._doc_curves
                               if c.group_id in gids and id(c) not in have]

    def _expand_selection_to_groups(self):
        """Selecting any member of a group selects the whole group.

        Runs with scene signals blocked so the expansion does not recurse;
        callers continue with the (now expanded) selection.
        """
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        gids = {i.curve.group_id for i in selected if i.curve.group_id}
        if not gids:
            return
        # Members on a hidden or locked layer cannot be selected; they ride
        # along with every whole-group operation instead (_with_group_members).
        # Holding such a group unselectable made every placed shipped hinge
        # (its pocket grouped with REF guide lines) unpickable while REF was
        # hidden or locked.
        to_add = [it for it in self.scene._curve_items.values()
                  if it.curve.group_id in gids and not it.isSelected()
                  and self.scene.is_layer_visible(it.curve.layer)
                  and not self.scene.is_layer_locked(it.curve.layer)]
        if not to_add:
            return
        self.scene.blockSignals(True)
        for it in to_add:
            it.setSelected(True)
        self.scene.blockSignals(False)
        # Repaint: blocked signals suppressed the view's selection-highlight update.
        self.view.viewport().update()

    def _sync_weight_spin(self, selected: list):
        """The Line weight box edits the selected curves, so it is live only
        with one selected; with none it shows, grayed, the weight a new curve
        takes. Typed with nothing selected, a weight did nothing, and the box
        went on showing it."""
        self._updating_weight_spin = True
        try:
            self._weight_spin.setValue(selected[0].curve.line_weight if selected
                                       else self._default_line_weight)
        finally:
            self._updating_weight_spin = False
        self._weight_spin.setEnabled(bool(selected))
        self._weight_spin.setToolTip(
            "Line weight of the selected curves, in screen pixels (display "
            "only; it is not cut)." if selected else
            "Select a curve to change its line weight. A new curve takes the "
            "default in Preferences ▸ General.")

    def _on_selection_changed(self):
        """Reflect the selected curve's layer and weight in the UI (Select mode)."""
        if self._draw_tool.active or self._circle_tool.active:
            self._sync_weight_spin([])
            return
        self._expand_selection_to_groups()
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if len(selected) == 1:
            # Selecting a curve makes its layer the active drawing layer
            # (preserves the old combo behavior) and highlights its row.
            sel_layer = selected[0].curve.layer
            if sel_layer is not self._active_ws.active_layer:
                self._active_ws.active_layer = sel_layer
                self._sync_layer_panel_active()
            # Reflect a single canvas selection in the tree's current row, but
            # NOT while we're syncing FROM the tree (that would clear the user's
            # multi-row pick mid-loop).
            if not self._syncing_selection:
                row = getattr(self, "_layer_tree_rows", {}).get(id(selected[0].curve))
                if row is not None:
                    self._syncing_selection = True
                    self._layer_tree.setCurrentItem(row)
                    self._syncing_selection = False
        self._sync_weight_spin(selected)
        # A single selected engraving text highlights its panel row too.
        texts = [i for i in self.scene.selectedItems() if isinstance(i, TextItem)]
        if not selected and len(texts) == 1 and not self._syncing_selection:
            row = getattr(self, "_layer_tree_text_rows", {}).get(id(texts[0].text_obj))
            if row is not None:
                self._syncing_selection = True
                self._layer_tree.setCurrentItem(row)
                self._syncing_selection = False
        # Reposition gizmo on selection change, or hide if nothing selected
        if self._move_gizmo is not None:
            center = self._gizmo_center_from_selection()
            if center is not None:
                self._move_gizmo_center = center
                self._move_gizmo.set_center(center)
            else:
                self._hide_move_gizmo()
        self._update_info_label()

    def _on_weight_spin_changed(self, value: float):
        """Apply line-weight spinbox changes to selected curves or store for new curves."""
        if self._updating_weight_spin:
            return
        if self._draw_tool.active:
            return
        targets = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not targets or all(abs(i.curve.line_weight - value) < 1e-9 for i in targets):
            return
        # One undo step for a run of arrow steps on one selection: each step
        # pushed a deep copy, and a few dozen flooded the 100-step history.
        # The run ends when the selection changes or another step lands on the
        # stack (an undo, or any other edit), so the step is still ours on top.
        ids = tuple(id(i.curve) for i in targets)
        top = self._undo_stack[-1] if self._undo_stack else None
        last_ids, last_top = self._weight_edit_key or ((), None)
        if ids != last_ids or top is None or top is not last_top:
            self._push_undo_snapshot()
        self._weight_edit_key = (ids, self._undo_stack[-1] if self._undo_stack else None)
        for item in targets:
            item.curve.line_weight = value
            item.refresh()
        # Every step stars the design, not only the one that pushed: a weight
        # set right after a save left it clean, and closing lost it unasked.
        self._mark_dirty()
        self._status.showMessage(f"Line weight → {value:.2f} px")

    # (curve ids, its undo step) of the last weight edit; see _on_weight_spin_changed.
    _weight_edit_key: tuple | None = None

    # ------------------------------------------------------------------
    # Undo / redo  (snapshot-based: full deep-copy of curves + dims)
    # ------------------------------------------------------------------

    def _take_snapshot(self) -> dict:
        """Deep copy of the active workspace's curves and dims."""
        return self._active_ws.take_snapshot()

    def _push_undo_snapshot(self):
        """Snapshot the active workspace, then sync UI + dirty state."""
        self._active_ws.push_undo_snapshot()
        self._update_undo_actions()
        self._mark_dirty()   # every snapshot precedes a document mutation

    def _pre_edit_snapshot(self):
        """Called by EditTool just before any node or handle drag begins."""
        self._push_undo_snapshot()

    def _restore_snapshot(self, snapshot: dict):
        """Rebuild the active workspace's canvas from a snapshot."""
        self._active_ws.restore_snapshot(snapshot)

    def _end_operations_holding_curves(self):
        """Undo and redo rebuild every Curve object. A tool mid-operation —
        Rebuild, Fillet, Offset, Point Move — still holds the old ones and
        then applies to curves no longer in the document: Fillet left both
        originals beside their trimmed copies, Point Move reported a move
        that never happened. End it first."""
        if any(t.active for t in (self._rebuild_tool, self._fillet_tool,
                                  self._offset_tool, self._point_move_tool)):
            self._act_select.setChecked(True)
            self._set_tool_select()
        # A drag-to-move holds its curves too: Ctrl+Z mid-drag kept moving the
        # old ones, and each move cast a Ghost for a curve no longer drawn.
        if self._drag_moving_curves or self._drag_moving_dims or self._drag_moving_texts:
            self.view.abandon_drag()
            self._drag_moving_curves = []
            self._drag_moving_dims   = []
            self._drag_moving_texts  = []

    def _undo(self):
        self._end_operations_holding_curves()
        if not self._active_ws.undo():
            self._status.showMessage("Nothing to undo")
            return
        self._update_undo_actions()
        self._mark_dirty()
        n = len(self._undo_stack)
        self._status.showMessage(
            f"Undo — {n} step{'s' if n != 1 else ''} remaining")

    def _redo(self):
        self._end_operations_holding_curves()
        if not self._active_ws.redo():
            self._status.showMessage("Nothing to redo")
            return
        self._update_undo_actions()
        self._mark_dirty()
        n = len(self._redo_stack)
        self._status.showMessage(
            f"Redo — {n} step{'s' if n != 1 else ''} remaining")

    def _handle_undo(self):
        """Ctrl+Z: undo last draw-point when drawing, else canvas undo — also
        when the Line tool is up with no point placed (Ctrl+Z did nothing)."""
        if self._draw_tool.active and self._draw_tool.undo_last_point():
            self._status.showMessage("Undo: last point removed")
            return
        self._undo()

    def _update_undo_actions(self):
        u, r = len(self._undo_stack), len(self._redo_stack)
        self._act_undo.setEnabled(bool(u))
        self._act_redo.setEnabled(bool(r))
        self._act_undo.setText(f"Undo ({u})\tCtrl+Z" if u else "Undo\tCtrl+Z")
        self._act_redo.setText(f"Redo ({r})\tCtrl+Y" if r else "Redo\tCtrl+Y")

    def _delete_selected(self):
        # If a node is selected, delete the node (not the whole curve)
        if self._edit_tool.has_selected_node():
            self._push_undo_snapshot()
            curve = self._edit_tool.delete_selected_node()
            if curve is None:
                # Curve would have <2 nodes — delete the whole curve instead
                selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
                for item in selected:
                    self._active_ws.remove_curve(item.curve)
                self._status.showMessage("Node delete: curve too short, removed curve")
            else:
                self.scene.refresh_curve(curve)
                # Rebuild the edit handles so indices stay consistent
                items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
                self._edit_tool.clear()
                for it in items:
                    self._edit_tool._add_curve_items(it)
                self._status.showMessage(
                    f"Deleted node — {len(curve.nodes)} nodes remain")
            return

        selected_curves = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        selected_dims   = [i for i in self.scene.selectedItems() if isinstance(i, DimItem)]
        selected_texts  = [i for i in self.scene.selectedItems() if isinstance(i, TextItem)]

        if not selected_curves and not selected_dims and not selected_texts:
            self._status.showMessage("Nothing selected to delete")
            return

        self._push_undo_snapshot()

        for item in selected_dims:
            self._active_ws.remove_dim(item.dim)
        for item in selected_texts:
            self._active_ws.remove_text(item.text_obj)

        doc_ids = {id(c) for c in self._doc_curves}
        to_remove = [c for c in self._with_group_members(
                         [item.curve for item in selected_curves])
                     if id(c) in doc_ids]
        if to_remove:
            self.scene.clearSelection()
            for curve in to_remove:
                self._active_ws.remove_curve(curve)
            n = len(to_remove)
            self._status.showMessage(f"Deleted {n} curve{'s' if n > 1 else ''}")
        elif selected_texts:
            n = len(selected_texts)
            self._status.showMessage(f"Deleted {n} text object{'s' if n > 1 else ''}")
        elif selected_dims:
            n = len(selected_dims)
            self._status.showMessage(f"Deleted {n} dimension{'s' if n > 1 else ''}")

    def _insert_node(self, curve: Curve, scene_pos):
        """Insert a node at the nearest point on *curve* to *scene_pos*."""
        if self._active_ws.shape_locked and curve.layer == Layer.LENS:
            self._status.showMessage(
                "Lens shape is locked — unlock it to add nodes")
            return
        if curve.group_id:
            self._status.showMessage(
                "Curve is grouped — Ctrl+Shift+G to ungroup before editing nodes")
            return
        snapshot = self._active_ws.take_snapshot()
        if self._edit_tool.insert_node_at(curve, scene_pos):
            # Push only now that something changed — pushing before the
            # attempt would wipe the redo stack even on a failed insert.
            self._active_ws.push_undo_state(snapshot)
            self._update_undo_actions()
            self._mark_dirty()
            self.scene.refresh_curve(curve)
            # Rebuild edit handles so the new dot appears
            items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
            self._edit_tool.clear()
            for it in items:
                self._edit_tool._add_curve_items(it)
            self._status.showMessage(
                f"Inserted node — {len(curve.nodes)} nodes total")

    # ------------------------------------------------------------------
    # Copy / Paste / Duplicate / Select All
    # ------------------------------------------------------------------

    _PASTE_OFFSET_MM = 5.0

    def _selection_payload(self):
        """(curves, dims, texts) behind the current canvas selection."""
        sel = self.scene.selectedItems()
        curves = self._with_group_members(
            [it.curve for it in sel if isinstance(it, CurveItem)])
        dims   = [it.dim      for it in sel if isinstance(it, DimItem)]
        texts  = [it.text_obj for it in sel if isinstance(it, TextItem)]
        return curves, dims, texts

    @staticmethod
    def _payload_summary(verb: str, curves, dims, texts) -> str:
        """'Copied 3 curves, 1 text' — only the kinds that are present."""
        parts = []
        for n, noun in ((len(curves), "curve"), (len(dims), "dim"),
                        (len(texts), "text")):
            if n:
                parts.append(f"{n} {noun}{'s' if n != 1 else ''}")
        return f"{verb} " + ", ".join(parts)

    def _copy_selected(self):
        curves, dims, texts = self._selection_payload()
        if not curves and not dims and not texts:
            self._status.showMessage("Copy: nothing selected")
            return
        # In-memory clipboard — survives workspace switches, so curves can be
        # copied between tabs.
        self._clipboard = {"curves": copy.deepcopy(curves),
                           "dims":   copy.deepcopy(dims),
                           "texts":  copy.deepcopy(texts)}
        self._paste_count = 0
        self._status.showMessage(
            self._payload_summary("Copied", curves, dims, texts))

    # Pastes of the one clipboard so far: each lands one offset further on, as
    # a second Ctrl+V landed exactly on the first and nothing flagged it.
    _paste_count = 0

    def _paste(self):
        clip = getattr(self, "_clipboard", None)
        if not clip or not any(clip.get(k) for k in ("curves", "dims", "texts")):
            self._status.showMessage("Paste: clipboard is empty")
            return
        self._paste_count += 1
        self._paste_payload(copy.deepcopy(clip["curves"]),
                            copy.deepcopy(clip["dims"]),
                            copy.deepcopy(clip.get("texts", [])),
                            steps=self._paste_count)

    def _duplicate_selected(self):
        curves, dims, texts = self._selection_payload()
        if not curves and not dims and not texts:
            self._status.showMessage("Duplicate: nothing selected")
            return
        self._paste_payload(copy.deepcopy(curves), copy.deepcopy(dims),
                            copy.deepcopy(texts))

    def _paste_payload(self, curves: list, dims: list, texts: list = (),
                       steps: int = 1):
        """Insert deep-copied curves/dims/texts *steps* × 5 mm off and select
        them."""
        self._push_undo_snapshot()
        allowed = set(WORKSPACE_LAYERS[self._active_ws.workspace_type])
        gid_map: dict = {}
        remapped = 0
        new_items = []
        off = self._PASTE_OFFSET_MM * max(1, steps)
        for c in curves:
            self._translate_curve(c, off, off)
            if c.layer not in allowed:
                # Layer doesn't exist in this workspace (cross-tab paste) —
                # land on REF so the curve stays visible and non-machined.
                c.layer = Layer.REF
                c.component_kind = None
                remapped += 1
            if c.group_id:
                # Fresh group ids: the paste must not merge with the original
                c.group_id = gid_map.setdefault(c.group_id, uuid.uuid4().hex[:8])
            new_items.append(self._active_ws.add_curve(c))
        for d in dims:
            d.x0 += off; d.y0 += off
            d.x1 += off; d.y1 += off
            new_items.append(self._active_ws.add_dim(d))
        for t in texts:
            t.anchor_x += off
            t.anchor_y += off
            if t.layer not in allowed:
                t.layer = Layer.REF
                remapped += 1
            new_items.append(self._active_ws.add_text(t))
        self.scene.select_items(new_items)
        msg = self._payload_summary("Pasted", curves, dims, texts)
        if remapped:
            msg += f"  ({remapped} moved to REF — layer not in this workspace)"
        layers = {c.layer for c in curves} | {t.layer for t in texts}
        hidden = sorted(lay.value for lay in layers
                        if not self.scene.is_layer_visible(lay))
        locked = sorted(lay.value for lay in layers
                        if self.scene.is_layer_visible(lay)
                        and self.scene.is_layer_locked(lay))
        if hidden:
            msg += (f"  ({_and_list(hidden)} hidden: show "
                    f"{'it' if len(hidden) == 1 else 'them'} to see the paste)")
        if locked:
            msg += (f"  ({_and_list(locked)} locked: unlock "
                    f"{'it' if len(locked) == 1 else 'them'} to move the paste)")
        self._status.showMessage(msg)

    def _select_all(self):
        """Select every visible, unlocked curve and dim (Ctrl+A)."""
        if self.view._draw_tool is not None or self._dim_tool.active:
            self._act_select.setChecked(True)
            self._set_tool_select()
        picked = [it for group in (self.scene._curve_items, self.scene._dim_items,
                                   self.scene._text_items)
                  for it in group.values()
                  if it.isVisible()
                  and bool(it.flags() & it.GraphicsItemFlag.ItemIsSelectable)]
        self.scene.select_items(picked)
        self._status.showMessage(f"Selected {len(picked)} object(s)")

    # ------------------------------------------------------------------
    # Transform (scale / rotate)
    # ------------------------------------------------------------------

    def _transform_selected(self):
        sel = self.scene.selectedItems()
        items = [i for i in sel if isinstance(i, CurveItem)]
        text_items = [i for i in sel if isinstance(i, TextItem)]
        # Dims ride along: Ctrl+A then Transform scaled the drawing and left
        # its dimensions measuring the old one (and said nothing of them).
        dims = [i.dim for i in sel if isinstance(i, DimItem)]
        if not items and not text_items and not dims:
            self._status.showMessage("Transform: select curves or text first")
            return
        obverse = self.view.is_obverse()
        dlg = TransformDialog(self, obverse=obverse)
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        sx, sy, rot, pivot_origin = dlg.values()
        if sx == 1.0 and sy == 1.0 and rot == 0.0:
            return
        if obverse:
            # The angle is the one on screen, as the Move gizmo's distances
            # are: View Obverse mirrors the screen, and +30° turned the
            # selection 30° clockwise there. Scene terms from here on.
            rot = -rot

        curves = self._with_group_members([i.curve for i in items])
        if pivot_origin:
            px = py = 0.0
        else:
            xs, ys = [], []
            bb = _curves_bbox(curves) if curves else None
            if bb is not None:              # None when nothing samples
                xs += [bb[0], bb[2]]; ys += [bb[1], bb[3]]
            for ti in text_items:
                r = ti.sceneBoundingRect()
                xs += [r.left(), r.right()]; ys += [r.top(), r.bottom()]
            for d in dims:
                xs += [d.x0, d.x1]; ys += [d.y0, d.y1]
            if not xs:
                self._status.showMessage(
                    "Transform: the selection draws nothing to transform")
                return
            px, py = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

        # The dialog's angle is counter-clockwise on screen; the scene is
        # y-down, where a positive angle turns clockwise — hence the minus.
        cos_t = math.cos(math.radians(-rot))
        sin_t = math.sin(math.radians(-rot))

        def xf(x: float, y: float):
            dx, dy = (x - px) * sx, (y - py) * sy
            return (px + dx * cos_t - dy * sin_t,
                    py + dx * sin_t + dy * cos_t)

        self._push_undo_snapshot()
        self._edit_tool.clear()
        uniform = abs(sx - sy) < 1e-9
        final_curves = []
        for curve in curves:
            if curve.kind in ("circle", "arc") and not uniform:
                # Ellipse result — not representable; convert to spline first
                repl = (circle_to_spline(curve) if curve.kind == "circle"
                        else arc_to_spline(curve))
                self._active_ws.remove_curve(curve)
                for n in repl.nodes:
                    n.x, n.y = xf(n.x, n.y)
                    if n.cp_in:
                        n.cp_in = ControlPoint(*xf(n.cp_in.x, n.cp_in.y))
                    if n.cp_out:
                        n.cp_out = ControlPoint(*xf(n.cp_out.x, n.cp_out.y))
                self._active_ws.add_curve(repl)
                final_curves.append(repl)
            elif curve.kind in ("circle", "arc"):
                c0 = curve.nodes[0]
                c0.x, c0.y = xf(c0.x, c0.y)
                curve.radius = (curve.radius or 0.0) * abs(sx)
                if (curve.kind == "arc" and rot and curve.start_angle is not None
                        and curve.end_angle is not None):
                    # Rotation shifts both angles equally (same atan2 space,
                    # scene y-down, so a counter-clockwise turn subtracts)
                    curve.start_angle = (curve.start_angle - rot) % 360
                    curve.end_angle   = (curve.end_angle - rot) % 360
                self.scene.refresh_curve(curve)
                final_curves.append(curve)
            else:
                for n in curve.nodes:
                    n.x, n.y = xf(n.x, n.y)
                    if n.cp_in:
                        n.cp_in = ControlPoint(*xf(n.cp_in.x, n.cp_in.y))
                    if n.cp_out:
                        n.cp_out = ControlPoint(*xf(n.cp_out.x, n.cp_out.y))
                self.scene.refresh_curve(curve)
                final_curves.append(curve)

        # Text objects: the anchor rides the same transform; the glyphs
        # themselves scale by size (uniform only — lettering has no
        # stretched form) and turn with the rotation. The dialog's angle and
        # TextObject.rotation are both counter-clockwise.
        from .textpath import normalize_rotation
        text_note = ""
        for ti in text_items:
            t = ti.text_obj
            t.anchor_x, t.anchor_y = xf(t.anchor_x, t.anchor_y)
            if uniform:
                t.size_mm = max(0.1, t.size_mm * abs(sx))
            elif sx != 1.0 or sy != 1.0:
                text_note = "  (text size unchanged — non-uniform scale)"
            if rot:
                t.rotation = normalize_rotation(t.rotation + rot)
            self.scene.refresh_text(t)

        for d in dims:
            d.x0, d.y0 = xf(d.x0, d.y0)
            d.x1, d.y1 = xf(d.x1, d.y1)
            if uniform:
                d.offset *= abs(sx)
            item = self.scene._dim_items.get(id(d))
            if item:
                item.prepareGeometryChange()
                item.update()

        picked = [self.scene._curve_items.get(id(c)) for c in final_curves]
        picked = [it for it in picked if it is not None] + text_items
        picked += [it for it in (self.scene._dim_items.get(id(d)) for d in dims)
                   if it is not None]
        self.scene.select_items(picked)
        self._refresh_measurements()
        self._status.showMessage(
            self._payload_summary("Transformed", final_curves, dims,
                                  [ti.text_obj for ti in text_items])
            + f"  (scale {sx * 100:.0f}% × {sy * 100:.0f}%, rotate {rot:+.1f}°)"
            + text_note)

    # ------------------------------------------------------------------
    # Group / Ungroup
    # ------------------------------------------------------------------

    def _group_selected(self):
        """Bind the selected curves into a rigid group (Ctrl+G)."""
        curves = [it.curve for it in self.scene.selectedItems()
                  if isinstance(it, CurveItem)]
        if len(curves) < 2:
            self._status.showMessage("Group: select 2 or more curves first")
            return
        self._push_undo_snapshot()
        gid = uuid.uuid4().hex[:8]
        for c in curves:
            c.group_id = gid
        # Grouped curves expose no node dots — rebuild the edit handles
        self._edit_tool.clear()
        self._on_selection_changed()
        self._refresh_layer_panel()
        self._status.showMessage(
            f"Grouped {len(curves)} curves — moves as one unit "
            "(Ctrl+Shift+G to ungroup)")

    def _ungroup_selected(self):
        """Dissolve the group(s) in the current selection (Ctrl+Shift+G)."""
        curves = [it.curve for it in self.scene.selectedItems()
                  if isinstance(it, CurveItem) and it.curve.group_id]
        if not curves:
            self._status.showMessage("Ungroup: no grouped curves selected")
            return
        self._push_undo_snapshot()
        for c in curves:
            c.group_id = None
        # Node dots are allowed again — rebuild edit handles for the selection
        self._edit_tool._on_selection()
        self._refresh_layer_panel()
        self._status.showMessage(f"Ungrouped {len(curves)} curves")

    # ------------------------------------------------------------------
    # Copy-across-mirror (Mirror Close)
    # ------------------------------------------------------------------

    def _copy_across_mirror(self):
        """Combine a selected open half-curve with its mirror image into one
        closed curve.  The two endpoints are snapped to the mirror axis before
        combining, so the halves join cleanly even if they were placed slightly
        off-axis.

        Every hand-tuned Bézier handle is preserved: the kept half keeps its
        handles verbatim and the mirrored half gets their exact reflections
        (handles were previously recomputed wholesale, which discarded the
        maker's shaping)."""
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if len(selected) != 1:
            self._status.showMessage("Mirror Close: select exactly one open curve first")
            return

        curve = selected[0].curve

        if curve.closed:
            self._status.showMessage("Mirror Close: curve is already closed")
            return
        if len(curve.nodes) < 2:
            self._status.showMessage("Mirror Close: need at least 2 nodes")
            return

        is_horiz = bool(self.scene.mirror and getattr(self.scene.mirror, '_horizontal', False))
        axis_x   = self.scene.mirror.x if self.scene.mirror else 0.0

        # A half reaches the axis at both ends and stays on one side of it.
        # Any end was pulled onto the axis however far off it was, and a
        # curve across the axis was reshaped, under a message of success.
        def side(x: float, y: float) -> float:
            return -y if is_horiz else x - axis_x

        far = max(abs(side(n.x, n.y)) for n in (curve.nodes[0], curve.nodes[-1]))
        if far > self._MIRROR_CLOSE_REACH_MM:
            self._status.showMessage(
                f"Mirror Close: an end is {far:.1f} mm from the axis. Bring both "
                f"ends onto the axis (within {self._MIRROR_CLOSE_REACH_MM:g} mm; "
                "the axis snap puts them on it), then try again.", 8000)
            return
        sides = [side(x, y) for x, y, _t in sample_curve(curve)]
        if (max(sides, default=0.0) > self._MIRROR_CLOSE_REACH_MM
                and min(sides, default=0.0) < -self._MIRROR_CLOSE_REACH_MM):
            self._status.showMessage(
                "Mirror Close: the curve crosses the axis. It closes a half "
                "drawn on one side with its mirror image.", 8000)
            return

        self._push_undo_snapshot()

        def mp(x: float, y: float) -> tuple:
            return (x, -y) if is_horiz else (2.0 * axis_x - x, y)

        def copy_node(n: SplineNode) -> SplineNode:
            nn = SplineNode(x=n.x, y=n.y)
            if n.cp_in:
                nn.cp_in  = ControlPoint(n.cp_in.x,  n.cp_in.y)
            if n.cp_out:
                nn.cp_out = ControlPoint(n.cp_out.x, n.cp_out.y)
            return nn

        def mirror_node(n: SplineNode) -> SplineNode:
            """Reflected copy traversed in REVERSE order: cp_in/cp_out swap."""
            nn = SplineNode(*mp(n.x, n.y))
            if n.cp_out:
                nn.cp_in  = ControlPoint(*mp(n.cp_out.x, n.cp_out.y))
            if n.cp_in:
                nn.cp_out = ControlPoint(*mp(n.cp_in.x, n.cp_in.y))
            return nn

        # Kept half: snap the two end nodes onto the axis, translating their
        # handles with the node (exactly what dragging the node would do).
        original = [copy_node(n) for n in curve.nodes]
        for end in (0, -1):
            n = original[end]
            dx, dy = (0.0, -n.y) if is_horiz else (axis_x - n.x, 0.0)
            n.x += dx
            n.y += dy
            if n.cp_in:
                n.cp_in  = ControlPoint(n.cp_in.x + dx,  n.cp_in.y + dy)
            if n.cp_out:
                n.cp_out = ControlPoint(n.cp_out.x + dx, n.cp_out.y + dy)

        # Traversal: A (=original[0]) → kept half → B (=original[-1]) →
        # mirrored interior (reversed) → back to A.
        new_nodes = original + [mirror_node(n) for n in reversed(original[1:-1])]

        # Seam handles: A and B sit on the axis; the closed loop enters/leaves
        # them from the mirrored half, so the handle on that side is the exact
        # reflection of the kept-side handle — a mirror-symmetric join.
        node_a, node_b = original[0], original[-1]
        if node_a.cp_out:
            node_a.cp_in  = ControlPoint(*mp(node_a.cp_out.x, node_a.cp_out.y))
        if node_b.cp_in:
            node_b.cp_out = ControlPoint(*mp(node_b.cp_in.x, node_b.cp_in.y))

        new_curve = Curve(
            kind        = curve.kind,
            layer       = curve.layer,
            nodes       = new_nodes,
            closed      = True,
            line_weight = curve.line_weight,
            component_kind = curve.component_kind,
        )

        # Replace the open half with the new closed shape
        self.scene.clearSelection()
        self._active_ws.remove_curve(curve)
        self._active_ws.add_curve(new_curve)
        self._status.showMessage(
            f"Mirror Close: closed into a {len(new_nodes)}-node "
            f"{new_curve.layer.value} curve")

    # How far off the axis an end may be for Mirror Close to put it on.
    _MIRROR_CLOSE_REACH_MM = 2.0

    # ------------------------------------------------------------------
    # Mirror — bake the Ghost into real geometry
    # ------------------------------------------------------------------

    def _on_duplicate_mirror(self):
        """Create real mirrored copies of all selected curves across the mirror axis.

        After this operation both the originals and copies are independent
        geometry.  The mirror toggle is turned off so the live ghost does not
        sit on the copies. A curve whose twin is already drawn, or would lie on
        itself, is skipped (``validate.bake_skips``): Ctrl+A then Mirror on a
        whole outline used to bake a second outline over the first.
        """
        from .export.validate import bake_skips
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not selected:
            self._status.showMessage(
                "Mirror: select one or more curves first"
            )
            return

        is_horiz = bool(self.scene.mirror and getattr(self.scene.mirror, '_horizontal', False))
        axis_x   = self.scene.mirror.x if self.scene.mirror else 0.0

        gid_map: dict = {}
        copies = []
        reasons: dict = {}                # why each skipped curve was skipped
        drawn = [c for c in self._doc_curves if not c.mirrored]
        traces: dict = {}                 # one trace per curve for the whole bake
        # A group is baked whole, its members on a hidden or locked layer too.
        sources = self._with_group_members([item.curve for item in selected])
        for src in sources:
            c = mirror_curve(src, axis_x, horizontal=is_horiz)
            why = bake_skips(src, c, drawn + copies, horizontal=is_horiz,
                             cache=traces)
            if why:
                reasons[why] = reasons.get(why, 0) + 1
                continue
            if src.group_id:          # the copy is its own rigid group
                c.group_id = gid_map.setdefault(src.group_id, uuid.uuid4().hex[:8])
            copies.append(c)
        skipped = len(sources) - len(copies)
        said = {"drawn already": "twin drawn already",
                "on itself": "twin on the curve itself",
                "overlaps itself": "across the axis, its twin over itself"}
        why_text = "; ".join(f"{n} {said[k]}" for k, n in reasons.items())
        if not copies:
            self._status.showMessage(f"Mirror: nothing to bake ({why_text})")
            return

        self._push_undo_snapshot()
        # This step turns Ghost off below; Undo puts it back (see undo()).
        self._undo_stack[-1]["mirror"] = self._act_mirror.isChecked()
        self.scene.clearSelection()
        for c in copies:
            self._active_ws.add_curve(c)

        # Turn off live mirror so the originals no longer cast a ghost over
        # their baked twins.
        self._act_mirror.setChecked(False)

        n = len(copies)
        msg = f"Mirror: {n} curve{'s' if n != 1 else ''} baked"
        if skipped:
            msg += f"; {skipped} skipped ({why_text})"
        self._status.showMessage(msg + ". Join or Mirror Close connects halves.")

    # ------------------------------------------------------------------
    # Mirror Copy: temple_r ↔ temple_l
    # ------------------------------------------------------------------

    def _copy_temple_to_other(self):
        """Flip all content from the current temple workspace into the other.

        Both directions reflect through the horizontal axis (y = 0): the
        temples are drawn hinge-left, so the other side is the same arm
        flipped brow-edge-for-brow-edge. Curves and dims reflect exactly;
        engraving text lands on the reflected footprint but stays readable
        (see textpath.mirror_text), so the maker only has to change the
        words. Confirms before overwriting a non-empty target; pushes an
        undo snapshot in the target.
        """
        ws_type = self._active_ws.workspace_type
        if ws_type not in ("temple_r", "temple_l"):
            return

        # Identify source and target workspace objects
        tab_names = ["front", "temple_r", "temple_l", "component"]
        src_ws = self._active_ws
        if not (src_ws.doc_curves or src_ws.doc_dims or src_ws.doc_texts):
            self._status.showMessage(
                "Temple Copy: this temple is empty — nothing to copy")
            return
        target_type = "temple_l" if ws_type == "temple_r" else "temple_r"
        tgt_ws = self._workspaces[tab_names.index(target_type)]

        # Always confirm — a mis-click must never silently wipe a workspace.
        label = "Temple L" if target_type == "temple_l" else "Temple R"
        has_content = bool(tgt_ws.doc_curves or tgt_ws.doc_dims
                           or tgt_ws.doc_texts)
        detail = (f"This will REPLACE everything currently in {label}."
                  if has_content else f"{label} is currently empty.")
        r = QMessageBox.question(
            self, "Temple Copy",
            f"Send a mirrored copy of this temple to {label}?\n\n{detail}\n"
            f"(Ctrl+Z in {label} restores its previous content.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if r != QMessageBox.StandardButton.Yes:
            return

        def flip_dim(d: DimLine) -> DimLine:
            # The offset is measured along the dim's own normal, which the
            # y-flip reverses — negate it so the line stays on the same side
            # of the reflected geometry.
            return DimLine(x0=d.x0, y0=-d.y0,
                           x1=d.x1, y1=-d.y1,
                           offset=-d.offset)

        # Snapshot target for undo, replace its geometry with the flipped copy.
        tgt_ws.push_undo_snapshot()
        tgt_ws.clear_geometry()
        gid_map: dict = {}
        for c in src_ws.doc_curves:
            m = mirror_curve(c, 0.0, horizontal=True)
            if c.group_id:      # a grouped component stays a group on the other side
                m.group_id = gid_map.setdefault(c.group_id, uuid.uuid4().hex[:8])
            tgt_ws.add_curve(m)
        for d in src_ws.doc_dims:
            tgt_ws.add_dim(flip_dim(d))
        from .textpath import mirror_text
        for t in src_ws.doc_texts:
            tgt_ws.add_text(mirror_text(t, 0.0, horizontal=True))

        # Switch to target tab
        self._ws_tab_widget.setCurrentIndex(tab_names.index(target_type))
        self._mark_dirty()
        self._update_undo_actions()   # the promised Ctrl+Z is on THIS tab now
        self._status.showMessage(
            self._payload_summary("Temple Copy:", tgt_ws.doc_curves,
                                  tgt_ws.doc_dims, tgt_ws.doc_texts)
            + f" copied to {label}.")

    # ------------------------------------------------------------------
    # Join curves
    # ------------------------------------------------------------------

    _JOIN_TOL = 2.0  # mm — max endpoint distance to consider curves connectable

    def _close_single_curve(self, source):
        """Join applied to one curve: fuse its own two ends into a closed loop.

        This is the shape that comes back from importing a lens trace (OMA/DXF)
        and rebuilding it — one spline that reads as closed but is still an open
        path, so it never counts as a finished LENS. Chaining can't help: there
        is no second curve to connect to.
        """
        from .document import SplineNode, Curve as _Curve

        curve = arc_to_spline(source) if source.kind == "arc" else source
        if curve.kind == "circle" or curve.closed:
            self._status.showMessage("Join: that curve is already closed.")
            return
        if len(curve.nodes) < 2:
            self._status.showMessage("Join: not enough nodes to close a loop.")
            return

        head, tail = curve.nodes[0], curve.nodes[-1]
        gap = math.hypot(tail.x - head.x, tail.y - head.y)
        if gap > self._JOIN_TOL:
            self._status.showMessage(
                f"Join: the curve's two ends are {gap:.2f} mm apart — snap one "
                f"onto the other (within {self._JOIN_TOL} mm) to close it, or "
                f"select a second curve to chain onto.")
            return

        # Fuse tail into head exactly as a multi-curve chain does when it comes
        # back round: the head keeps its position and outgoing handle, and
        # inherits the tail's incoming handle so the wrap segment curves the
        # way the drawn tail did.
        nodes = [SplineNode(x=n.x, y=n.y, cp_in=n.cp_in, cp_out=n.cp_out)
                 for n in curve.nodes]
        nodes[0] = SplineNode(x=head.x, y=head.y,
                              cp_in=tail.cp_in, cp_out=head.cp_out)
        nodes.pop()
        if len(nodes) < 3:
            self._status.showMessage(
                "Join: a closed curve needs at least 3 nodes.")
            return

        self._push_undo_snapshot()
        closed_curve = _Curve(
            kind=curve.kind,
            layer=curve.layer,
            nodes=nodes,
            closed=True,
            line_weight=curve.line_weight,
            group_id=source.group_id,
            component_kind=source.component_kind,
        )
        self.scene.clearSelection()
        self._active_ws.remove_curve(source)
        item = self._active_ws.add_curve(closed_curve)
        item.setSelected(True)
        note = f"  (ends were {gap:.2f} mm apart)" if gap > 1e-6 else ""
        self._status.showMessage(
            f"Closed {curve.kind} ({len(nodes)} nodes){note}")

    def _join_selected_curves(self):
        """Chain 2+ selected open curves into one by connecting nearest endpoints.

        With exactly one curve selected, Join closes that curve onto itself
        instead — see _close_single_curve."""
        from .document import SplineNode, Curve as _Curve

        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not selected_items:
            self._status.showMessage(
                "Join: select one curve to close it, or 2+ curves to chain them")
            return

        # The original curves are what we remove from the document at the end.
        originals = [item.curve for item in selected_items]

        if len(originals) == 1:
            self._close_single_curve(originals[0])
            return

        # Arcs store only their center node, so their endpoints can't be read
        # from nodes[0]/nodes[-1] — convert them to splines (with real endpoint
        # nodes) before chaining. Circles and closed curves have no endpoints
        # to join to, so they're left out of the join, untouched, with a note
        # (Join used to open a closed curve, and delete the circles it said it
        # skipped).
        curves = []
        joined = []                      # the originals the join replaces
        skipped_circles = skipped_closed = 0
        for c in originals:
            if c.kind == "circle":
                skipped_circles += 1
            elif c.closed:
                skipped_closed += 1
            elif c.kind == "arc":
                curves.append(arc_to_spline(c))
                joined.append(c)
            else:
                curves.append(c)
                joined.append(c)

        if len(curves) < 2:
            if skipped_circles or skipped_closed:
                self._status.showMessage(
                    "Join: circles and closed curves have no endpoints — trim or "
                    "split one open first, then join. Need 2+ joinable curves.")
            else:
                self._status.showMessage("Join: select 2 or more joinable curves")
            return
        layers = sorted({c.layer.value for c in curves})
        if len(layers) > 1:
            # The joined curve took the layer of whichever curve headed the
            # chain: REF + OUTLINE became REF, and a machined half stopped
            # being cut, without a word.
            self._status.showMessage(
                f"Join: the curves are on {_and_list(layers)}; move them to one "
                "layer first (right-click ▸ Move Selection to…)", 8000)
            return

        def ep_dist(a, b):
            return math.hypot(a.x - b.x, a.y - b.y)

        def reversed_nodes(c):
            """Nodes in reverse order with cp_in/cp_out swapped (path reversal)."""
            return [SplineNode(x=n.x, y=n.y, cp_in=n.cp_out, cp_out=n.cp_in)
                    for n in reversed(c.nodes)]

        # Build chain: list of (curve, forward: bool)
        chain = [(curves[0], True)]
        remaining = list(curves[1:])
        max_gap = 0.0          # the widest junction closed (the geometry moves)

        while remaining:
            c0, fwd0 = chain[0]
            cN, fwdN = chain[-1]
            chain_head = c0.nodes[0]  if fwd0  else c0.nodes[-1]
            chain_tail = cN.nodes[-1] if fwdN  else cN.nodes[0]

            best_d    = float("inf")
            best_c    = None
            best_mode = None   # 'tail_fwd' | 'tail_rev' | 'head_cend' | 'head_cstart'

            for c in remaining:
                for d, mode in [
                    (ep_dist(chain_tail, c.nodes[0]),  "tail_fwd"),
                    (ep_dist(chain_tail, c.nodes[-1]), "tail_rev"),
                    (ep_dist(chain_head, c.nodes[-1]), "head_cend"),
                    (ep_dist(chain_head, c.nodes[0]),  "head_cstart"),
                ]:
                    if d < best_d:
                        best_d, best_c, best_mode = d, c, mode

            if best_d > self._JOIN_TOL:
                break
            max_gap = max(max_gap, best_d)
            remaining.remove(best_c)
            if   best_mode == "tail_fwd":    chain.append((best_c, True))
            elif best_mode == "tail_rev":    chain.append((best_c, False))
            elif best_mode == "head_cend":   chain.insert(0, (best_c, True))
            else:                            chain.insert(0, (best_c, False))

        if remaining:
            self._status.showMessage(
                f"Join: {len(remaining)} curve(s) couldn't connect — "
                f"endpoints must be within {self._JOIN_TOL} mm")
            return

        self._push_undo_snapshot()

        # Determine result properties
        result_kind   = "spline" if any(c.kind == "spline" for c, _ in chain) else "line"
        result_layer  = chain[0][0].layer
        result_weight = chain[0][0].line_weight

        # Build merged node list; handle cp_in/cp_out at each junction
        result_nodes = []
        for i, (c, fwd) in enumerate(chain):
            seg = list(c.nodes) if fwd else reversed_nodes(c)
            if i == 0:
                result_nodes.extend(seg)
            else:
                # Merge junction: keep chain tail pos/cp_in, take cp_out from seg head
                jn = result_nodes[-1]
                sh = seg[0]
                result_nodes[-1] = SplineNode(
                    x=jn.x, y=jn.y,
                    cp_in=jn.cp_in,
                    cp_out=sh.cp_out,
                )
                result_nodes.extend(seg[1:])

        # Check if chain forms a closed loop
        close_gap = ep_dist(result_nodes[0], result_nodes[-1])
        is_closed = close_gap < self._JOIN_TOL
        if is_closed:
            max_gap = max(max_gap, close_gap)
            # Merge tail into head: head takes cp_in from tail
            tail = result_nodes[-1]
            head = result_nodes[0]
            result_nodes[0] = SplineNode(
                x=head.x, y=head.y,
                cp_in=tail.cp_in,
                cp_out=head.cp_out,
            )
            result_nodes.pop()

        # A group and a kind the curves all share carry over (both were lost).
        gids = {c.group_id for c in joined}
        kinds = {c.component_kind for c in joined}
        new_curve = _Curve(
            kind=result_kind,
            layer=result_layer,
            nodes=result_nodes,
            closed=is_closed,
            line_weight=result_weight,
            group_id=gids.pop() if len(gids) == 1 else None,
            component_kind=kinds.pop() if len(kinds) == 1 else None,
        )

        self.scene.clearSelection()
        for c in joined:
            self._active_ws.remove_curve(c)

        item = self._active_ws.add_curve(new_curve)
        item.setSelected(True)
        skipped = [f"{n} {what} skipped" for n, what in
                   ((skipped_circles, "circle(s)"), (skipped_closed, "closed curve(s)"))
                   if n]
        note = f"  ({', '.join(skipped)})" if skipped else ""
        if max_gap > 0.01:
            # Ends up to _JOIN_TOL apart are brought together, which moves the
            # geometry there: the one-curve close reported its gap, this did not.
            note += f"  (ends up to {max_gap:.2f} mm apart were brought together)"
        self._status.showMessage(
            f"Joined {len(curves)} curves{note} → "
            f"{'closed' if is_closed else 'open'} {result_kind} "
            f"({len(result_nodes)} nodes)", 8000)

    # ------------------------------------------------------------------
    # Snap selected node to nearest endpoint
    # ------------------------------------------------------------------

    def _snap_selected_node_to_endpoint(self):
        """Move the selected (red) NodeDot onto the nearest free end of another
        open curve on a visible layer, within reach (_snap_node_reach_mm)."""
        from .geometry import open_ends
        dot = self._edit_tool.selected_dot
        if dot is None:
            self._status.showMessage(
                "Snap Node: select a curve, then click a node to highlight it red, then press E")
            return

        curve    = dot._curve
        node_idx = dot.node_index
        node     = curve.nodes[node_idx]
        sx, sy   = node.x, node.y

        best_x, best_y = None, None
        best_d         = float("inf")
        reach = self._snap_node_reach_mm()

        # A free end only (an arc's on its rim, not its center), on a shown
        # layer, within reach: E moved a node 117 mm, onto a hidden SCULPT end.
        for c in self._doc_curves:
            if c is curve or not self.scene.is_layer_visible(c.layer):
                continue
            for ex, ey, _node in open_ends(c):
                d = math.hypot(ex - sx, ey - sy)
                if d < best_d:
                    best_d, best_x, best_y = d, ex, ey

        if best_x is None or best_d > reach:
            self._status.showMessage(
                f"Snap Node: no free end of another open curve within "
                f"{reach:.1f} mm of this node (the snap reach at this zoom)", 6000)
            return
        if best_d < 1e-9:
            self._status.showMessage("Snap Node: the node is on that end already")
            return

        self._push_undo_snapshot()

        dx, dy = best_x - node.x, best_y - node.y
        if node.cp_in:
            node.cp_in  = ControlPoint(node.cp_in.x  + dx, node.cp_in.y  + dy)
        if node.cp_out:
            node.cp_out = ControlPoint(node.cp_out.x + dx, node.cp_out.y + dy)
        node.x, node.y = best_x, best_y

        self.scene.refresh_curve(curve)

        # Rebuild edit handles from the updated data model; re-select the same node
        items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        self._edit_tool.clear()
        for it in items:
            self._edit_tool._add_curve_items(it)
        for ndot in self._edit_tool._dots:
            if ndot.node_index == node_idx:
                self._edit_tool._on_node_clicked(ndot)
                break

        self._status.showMessage(
            f"Snapped node to endpoint ({best_x:.2f}, {-best_y:.2f}) mm  "
            f"[moved {best_d:.2f} mm]"
        )

    def _snap_node_reach_mm(self) -> float:
        """How far E reaches: the snap radius at this zoom, and never less
        than 2 mm, the gap a near-miss join leaves."""
        px = float(self._prefs.get("snap_radius_px", 10))
        return max(2.0, px / max(self.view.zoom(), 1e-6))

    # ------------------------------------------------------------------
    # Split / Explode  (Phase 10b)
    # ------------------------------------------------------------------

    def _op_available(self, key: str) -> bool:
        """Whether the operation *key* can run on the current selection.
        Asked of the selection, not of the button: Qt reports a hidden action
        as disabled, which grayed the Modify menu's entry for a button hidden
        in Preferences ▸ Toolbar."""
        if key == "split":
            curves = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
            return (len(curves) == 1 and self._edit_tool.has_selected_node()
                    and self._split_refusal() is None)
        if key == "explode":
            return any(isinstance(i, CurveItem) for i in self.scene.selectedItems())
        if key == "snap_node":
            return self._edit_tool.has_selected_node()
        return True

    def _update_split_enabled(self, _=None):
        self._act_split.setEnabled(self._op_available("split"))

    def _split_refusal(self) -> str | None:
        """Why Split cannot break the curve at the selected node, or None when
        it can. A circle's or an arc's one node is its center, and splitting
        there made a circle with no radius, or two arcs with no angles, which
        vanished from the canvas and the DXF; an open curve's end node made a
        one-node curve (the 2.0 bug hunt)."""
        curve, idx = self._edit_tool.selected_node_info()
        if curve is None:
            return None
        if curve.kind in ("circle", "arc"):
            return (f"a {curve.kind}'s one node is its center; convert it to a "
                    "spline to split it")
        if len(curve.nodes) < 2:
            return "the curve has a single node"
        if not curve.closed and idx in (0, len(curve.nodes) - 1):
            return "an end node already ends the curve"
        return None

    def _update_explode_enabled(self):
        self._act_explode.setEnabled(self._op_available("explode"))

    def _split_at_node(self):
        """Break the selected curve at the selected (red) node into two open curves."""
        curve, idx = self._edit_tool.selected_node_info()
        if curve is None or not any(c is curve for c in self._doc_curves):
            self._status.showMessage("Split: select a node first")
            return
        refusal = self._split_refusal()
        if refusal:
            self._status.showMessage(f"Split: {refusal}")
            return

        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()

        if curve.closed:
            # Rotate node list so idx is both first and last → one open curve.
            # The seam node appears twice; deepcopy the slices SEPARATELY so
            # its two copies are independent objects (one deepcopy of the
            # combined list memoizes them into a single shared node, and
            # dragging one endpoint would silently move the other).
            rotated = (copy.deepcopy(curve.nodes[idx:])
                       + copy.deepcopy(curve.nodes[:idx + 1]))
            results = [
                Curve(kind=curve.kind, layer=curve.layer,
                      nodes=rotated, closed=False, line_weight=curve.line_weight,
                      component_kind=curve.component_kind)
            ]
        else:
            left_nodes  = copy.deepcopy(curve.nodes[:idx + 1])
            right_nodes = copy.deepcopy(curve.nodes[idx:])
            results = [
                Curve(kind=curve.kind, layer=curve.layer,
                      nodes=left_nodes,  closed=False, line_weight=curve.line_weight,
                      component_kind=curve.component_kind),
                Curve(kind=curve.kind, layer=curve.layer,
                      nodes=right_nodes, closed=False, line_weight=curve.line_weight,
                      component_kind=curve.component_kind),
            ]

        for c in results:
            drop_end_handles(c)       # the split node's far-side handles
        self._active_ws.remove_curve(curve)
        self.scene.select_items([self._active_ws.add_curve(c) for c in results])

        n = len(results)
        self._status.showMessage(f"Split → {n} curve{'s' if n > 1 else ''}")

    def _explode_selected(self):
        """Break each selected curve into individual 2-node segments."""
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)]
        if not selected_items:
            self._status.showMessage("Explode: select one or more curves first")
            return

        # A circle or arc has one (center) node and no segments to break
        # into — exploding it deleted the arc and left a radius-less ghost
        # for the circle.
        round_items = [i for i in selected_items if i.curve.kind in ("circle", "arc")]
        selected_items = [i for i in selected_items if i not in round_items]
        if not selected_items:
            self._status.showMessage(
                "Explode: circles and arcs have no segments to break apart")
            return
        # An open curve of two nodes is one segment already: exploding it
        # changed nothing and pushed an empty undo step.
        selected_items = [i for i in selected_items
                          if i.curve.closed or len(i.curve.nodes) > 2]
        if not selected_items:
            self._status.showMessage(
                "Explode: each selected curve is a single segment already")
            return

        self._push_undo_snapshot()
        self._edit_tool.clear()
        self.scene.clearSelection()

        total_segs = 0
        new_items = []
        for item in selected_items:
            curve  = item.curve
            nodes  = curve.nodes
            n      = len(nodes)
            pairs  = range(n) if curve.closed else range(n - 1)

            segments = []
            for i in pairs:
                a   = copy.copy(nodes[i])
                b   = copy.copy(nodes[(i + 1) % n])
                seg = Curve(kind=curve.kind, layer=curve.layer,
                            nodes=[a, b], closed=False, line_weight=curve.line_weight,
                            component_kind=curve.component_kind)
                segments.append(drop_end_handles(seg))

            self._active_ws.remove_curve(curve)
            new_items += [self._active_ws.add_curve(seg) for seg in segments]
            total_segs += len(segments)
        self.scene.select_items(new_items)

        n_orig = len(selected_items)
        msg = f"Explode: {n_orig} curve{'s' if n_orig > 1 else ''} → {total_segs} segments"
        if round_items:
            msg += f"  ({len(round_items)} circle/arc left whole)"
        self._status.showMessage(msg)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self):
        # Pre-populate from stored prefs (startup defaults), with the durable
        # live values (theme, weight, toolbar, hotkeys) overlaid.
        current = {
            **self._prefs,
            "dark_mode":           self._dark_mode,
            "default_line_weight": self._default_line_weight,
            "toolbar":             dict(self._toolbar_prefs),
            "hotkeys":             dict(self._hotkey_prefs),
        }
        dlg = SettingsDialog(current, self, images_in_use=self._images_in_use)
        accepted = _run_modal(dlg) == QDialog.DialogCode.Accepted
        # The size the maker left it at is theirs to keep, Cancel or OK.
        self._prefs["prefs_dialog_size"] = [int(dlg.width()), int(dlg.height())]
        if not accepted:
            _prefs_mod.save(self._prefs)
            return
        self._apply_settings(dlg.to_prefs())

    def _ask_apply_to_open_design(self) -> bool:
        """Whether the changed guide sizes and startup choices go into the
        open design as well as the ones that follow."""
        box = QMessageBox(
            QMessageBox.Icon.Question, "Apply to the Open Design?",
            "The guide sizes and the switches under “On for New Designs” start "
            "each new design. Apply the changes to the open design too? Its "
            "blank and pad sizes are saved with it.",
            QMessageBox.StandardButton.NoButton, self)
        apply = box.addButton("Apply to This Design", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("New Designs Only", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(later)
        box.setEscapeButton(later)
        box.exec()
        return box.clickedButton() is apply

    def _apply_settings(self, p: dict) -> None:
        self._applying_settings = True          # see _guide_edited
        try:
            self._apply_settings_now(p)
        finally:
            self._applying_settings = False

    def _apply_settings_now(self, p: dict) -> None:
        """Apply an accepted Settings-dialog prefs dict to the live session
        and persist it. Split from _open_settings so tests can exercise the
        apply logic without executing the modal dialog."""
        old_lens_opacity   = self._default_lens_fill_opacity()
        old_lens_intensity = self._default_lens_fill_intensity()
        old_inlay_color    = self._default_inlay_fill_color()
        old_inlay_opacity  = self._default_inlay_fill_opacity()
        old_prefs = dict(self._prefs)
        self._prefs.update(p)   # dialog is the sole writer of startup defaults

        # Theme + appearance first, so a mode toggle (or the explicit refresh
        # below) repaints with the new tokens in one pass. set_overrides
        # replaces the whole override set, so the viewport overlay must be
        # re-applied on top (same order as startup).
        theme.set_overrides(p["theme"])
        vp = p["viewport"]
        theme.apply_viewport(vp["preset"], vp.get("custom_bg"))
        theme.set_dot_radius(p["dot_radius_px"])
        theme.set_compact(p["compact_toolbar"])
        # The dots on show take the new size now, not at the next selection.
        for ws in self._workspaces:
            ws.edit_tool.refresh_for_selection()
        # Grid spacing/major changed in the dialog — re-push to views + engines
        # (visibility stays as the toolbar toggle left it).
        self._apply_grid_config()
        for ws in self._workspaces:
            ws.view.set_vignette(vp.get("vignette", 0))
        if p["dark_mode"] != self._dark_mode:
            self._act_dark.setChecked(p["dark_mode"])
            self._toggle_dark_mode(p["dark_mode"])
        else:
            self._refresh_theme_dependents()

        # Drawing: the box shows the selection's weight, or the new default
        # (_sync_weight_spin guards it so no curve takes the default).
        self._default_line_weight = p["default_line_weight"]
        self._sync_weight_spin(
            [i for i in self.scene.selectedItems() if isinstance(i, CurveItem)])

        # Startup toggles + guide dimensions — these prefs describe the Frame
        # Front workspace (temple/component have their own fixed stock defaults),
        # so apply them to the front workspace ONLY. Driving the live toolbar
        # widgets from any other tab pushed front stock/pad guides into that
        # workspace's session state (GitHub issue #4: saving Settings inside a
        # Temple workspace re-drew the temple stock as the frame-front stock
        # and stranded a pad guide with no button to remove it).
        #
        # And only the ones the maker CHANGED: OK re-applied every one, so
        # opening Preferences to switch dark mode turned Snap back on and put
        # the stock and boxing sizes back to their defaults. The Ghost axis is
        # never pushed into the open document — it is saved with the design
        # (an asymmetric one would have flipped, and saved, mirrored); the
        # startup value is for the documents that follow.
        changed = {k for k in (
            "guides_on_startup", "snap_on_startup", "smooth_handles",
            "boxing_on_startup", "stock_on_startup", "pad_on_startup",
            "boxing_a_mm", "boxing_b_mm", "boxing_dbl_mm",
            "stock_width_mm", "stock_height_mm", "pad_width_mm", "pad_height_mm",
        ) if p[k] != old_prefs.get(k)}
        temple_changed = {k for k in ("temple_stock_width_mm", "temple_stock_height_mm")
                          if k in p and p[k] != old_prefs.get(k)}
        # These start new designs. A design with something drawn keeps its own
        # sizes unless the maker says otherwise: they are saved with it since
        # 2.0, and OK rewrote them — silently from another tab — so the next
        # save wrote a blank the design was never drawn against.
        drawn = any(ws.doc_curves or ws.doc_texts or ws.doc_dims
                    for ws in self._workspaces)
        if (changed or temple_changed) and drawn:
            if self._ask_apply_to_open_design():
                self._mark_dirty()
            else:
                changed, temple_changed = set(), set()
        front = self._workspaces[0]
        if self._active_ws is front:
            # Widgets drive the active (= front) workspace via their signals.
            for key, act in (("guides_on_startup", self._act_guides),
                             ("snap_on_startup",   self._act_snap),
                             ("smooth_handles",    self._act_smooth),
                             ("boxing_on_startup", self._act_boxing),
                             ("stock_on_startup",  self._act_stock),
                             ("pad_on_startup",    self._act_pad)):
                if key in changed:
                    act.setChecked(p[key])
            if not front.boxing_snapped:
                # Snapped, the fields follow the lens (and with the shape
                # locked would RESIZE it to the startup A/B) — leave them.
                for key, spin in (("boxing_a_mm",   self._boxing_a_spin),
                                  ("boxing_b_mm",   self._boxing_b_spin),
                                  ("boxing_dbl_mm", self._boxing_dbl_spin)):
                    if key in changed:
                        spin.setValue(p[key])
            for key, spin in (("stock_width_mm",  self._stock_w_spin),
                              ("stock_height_mm", self._stock_h_spin),
                              ("pad_width_mm",    self._pad_w_spin),
                              ("pad_height_mm",   self._pad_h_spin)):
                if key in changed:
                    spin.setValue(p[key])
        else:
            # Write the front workspace's session state directly; the sidebar
            # widgets stay on the active workspace's values and the front tab
            # picks these up on activation (_restore_ws_sidebar_state).
            for key, attr in (("guides_on_startup", "guides_visible"),
                              ("snap_on_startup",   "snap_enabled"),
                              ("smooth_handles",    "smooth_handles"),
                              ("boxing_on_startup", "boxing_visible"),
                              ("stock_on_startup",  "stock_visible"),
                              ("pad_on_startup",    "pad_visible"),
                              ("boxing_a_mm",       "boxing_a"),
                              ("boxing_b_mm",       "boxing_b"),
                              ("boxing_dbl_mm",     "boxing_dbl"),
                              ("stock_width_mm",    "stock_w"),
                              ("stock_height_mm",   "stock_h"),
                              ("pad_width_mm",      "pad_w"),
                              ("pad_height_mm",     "pad_h")):
                if key in changed:
                    setattr(front, attr, p[key])

        # The temple blank is one preference for both temple tabs. The active
        # temple takes it through the sidebar widgets (they drive its guide
        # and the readiness dot); the other's session state is written
        # directly and surfaces on activation, as the front's does above.
        for temple in self._workspaces[1:3]:
            for key, attr, spin in (
                    ("temple_stock_width_mm",  "stock_w", self._stock_w_spin),
                    ("temple_stock_height_mm", "stock_h", self._stock_h_spin)):
                if key not in temple_changed:
                    continue
                if self._active_ws is temple:
                    spin.setValue(p[key])
                else:
                    setattr(temple, attr, p[key])

        # Lens Fill default opacity — a starting value, so it moves the live
        # slider only for workspaces that are still sitting on the old default
        # (a maker who has already dialed a tint in keeps their setting).
        # The values are saved with the design, so a design with content that
        # moves is marked unsaved — it used to change silently, leaving the
        # screen and the file disagreeing until the next save.
        moved_a_design = False
        new_opacity = self._default_lens_fill_opacity()
        if new_opacity != old_lens_opacity:
            for ws in self._workspaces:
                if abs(ws.lens_fill_opacity - old_lens_opacity) < 1e-9:
                    ws.lens_fill_opacity = new_opacity
                    ws.scene.set_lens_fill_opacity(new_opacity)
                    moved_a_design |= bool(ws.doc_curves)
            self._lens_fill_opacity_slider.blockSignals(True)
            self._lens_fill_opacity_slider.setValue(
                round(self._active_ws.lens_fill_opacity * 100))
            self._lens_fill_opacity_slider.blockSignals(False)
        new_intensity = self._default_lens_fill_intensity()
        if new_intensity != old_lens_intensity:
            for ws in self._workspaces:
                if abs(ws.lens_fill_intensity - old_lens_intensity) < 1e-9:
                    ws.lens_fill_intensity = new_intensity
                    ws.scene.set_lens_fill_intensity(new_intensity)
                    moved_a_design |= bool(ws.doc_curves)
            self._lens_fill_intensity_slider.blockSignals(True)
            self._lens_fill_intensity_slider.setValue(
                slider_from_intensity(self._active_ws.lens_fill_intensity))
            self._lens_fill_intensity_slider.blockSignals(False)
            self._update_lens_fill_swatches(self._active_ws.lens_fill_top,
                                            self._active_ws.lens_fill_bottom,
                                            self._active_ws.lens_fill_intensity)
        # Inlay Fill defaults: the same rule, for the color and the opacity.
        new_inlay_color = self._default_inlay_fill_color()
        if new_inlay_color != old_inlay_color:
            for ws in self._workspaces:
                if ws.inlay_fill_color == old_inlay_color:
                    ws.inlay_fill_color = new_inlay_color
                    ws.scene.set_inlay_fill_color(QColor(new_inlay_color))
                    moved_a_design |= bool(ws.doc_curves)
            self._update_inlay_fill_swatch(self._active_ws.inlay_fill_color)
        new_inlay_opacity = self._default_inlay_fill_opacity()
        if new_inlay_opacity != old_inlay_opacity:
            for ws in self._workspaces:
                if abs(ws.inlay_fill_opacity - old_inlay_opacity) < 1e-9:
                    ws.inlay_fill_opacity = new_inlay_opacity
                    ws.scene.set_inlay_fill_opacity(new_inlay_opacity)
                    moved_a_design |= bool(ws.doc_curves)
            self._inlay_fill_opacity_slider.blockSignals(True)
            self._inlay_fill_opacity_slider.setValue(
                round(self._active_ws.inlay_fill_opacity * 100))
            self._inlay_fill_opacity_slider.blockSignals(False)
        if moved_a_design:
            self._mark_dirty()

        # Toolbar visibility
        self._toolbar_prefs = p["toolbar"]
        self._apply_toolbar_visibility(self._toolbar_prefs)

        # Hotkeys
        self._hotkey_prefs = p["hotkeys"]
        self._apply_hotkeys(self._hotkey_prefs)

        self._save_prefs()

    # ------------------------------------------------------------------
    # Revision timeline (History tab)
    # ------------------------------------------------------------------

    def _on_timeline_selection(self):
        has = bool(self._timeline_list.selectedItems())
        self._btn_bm_restore.setEnabled(has)
        self._btn_bm_rename.setEnabled(has)
        self._btn_bm_delete.setEnabled(has)

    def _refresh_timeline_list(self):
        self._timeline_list.blockSignals(True)
        self._timeline_list.clear()
        for i, bm in enumerate(self._bookmarks):
            item = QListWidgetItem(f"{bm['name']}  ·  {bm['timestamp']}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            n = len(bm["snapshot"]["curves"])
            item.setToolTip(
                f"Created: {bm['timestamp']}\n{n} curve{'s' if n != 1 else ''}")
            self._timeline_list.addItem(item)
        self._timeline_list.blockSignals(False)
        self._on_timeline_selection()
        n = len(self._bookmarks)
        self._side_tabs.setTabText(3, f"History ({n})" if n else "History")

    def _add_bookmark(self):
        name, ok = QInputDialog.getText(
            self, "Bookmark Current State",
            "Revision name:",
            text=f"Revision {len(self._bookmarks) + 1}",
        )
        if not ok or not name.strip():
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        snapshot = self._take_snapshot()
        # The Ghost goes with it, as with an undo step: a bookmark taken
        # before a bake came back as half a frame with the Ghost off.
        snapshot["mirror"] = self._act_mirror.isChecked()
        self._bookmarks.append({
            "name":      name.strip(),
            "timestamp": ts,
            "snapshot":  snapshot,
        })
        self._refresh_timeline_list()
        self._timeline_list.setCurrentRow(len(self._bookmarks) - 1)
        self._mark_dirty()   # bookmarks are persisted in the file
        self._status.showMessage(f"Bookmarked: {name.strip()}")

    def _restore_bookmark(self):
        items = self._timeline_list.selectedItems()
        if not items:
            return
        self._end_operations_holding_curves()     # it rebuilds every Curve too
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        bm = self._bookmarks[idx]
        self._push_undo_snapshot()
        ghost = bm["snapshot"].get("mirror")      # absent in pre-2.0 bookmarks
        if ghost is not None:
            # Undo brings back the Ghost the restore leaves (_step_across).
            self._undo_stack[-1]["mirror"] = self._act_mirror.isChecked()
        # Deep-copy: _restore_snapshot installs the snapshot's objects as the
        # live document, and later in-place node edits would otherwise mutate
        # the stored bookmark.
        self._restore_snapshot(copy.deepcopy(bm["snapshot"]))
        if ghost is not None and bool(ghost) != self._act_mirror.isChecked():
            self._act_mirror.setChecked(bool(ghost))
        self._status.showMessage(f"Restored bookmark: {bm['name']}")

    def _rename_bookmark(self):
        items = self._timeline_list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        bm = self._bookmarks[idx]
        name, ok = QInputDialog.getText(
            self, "Rename Bookmark", "New name:", text=bm["name"])
        if ok and name.strip():
            bm["name"] = name.strip()
            self._refresh_timeline_list()
            self._timeline_list.setCurrentRow(idx)
            self._mark_dirty()

    def _delete_bookmark(self):
        items = self._timeline_list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        bm = self._bookmarks[idx]
        r = QMessageBox.question(
            self, "Delete Bookmark",
            f"Delete bookmark \u201c{bm['name']}\u201d?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self._bookmarks.pop(idx)
            self._refresh_timeline_list()
            self._mark_dirty()

    # ------------------------------------------------------------------
    # Component library
    # ------------------------------------------------------------------

    def _refresh_library_panel(self, select=None) -> None:
        """Rebuild the Library tree from disk: the folders in the maker's
        order, each with its entries, then any entry outside a folder.
        *select* is the ``("folder", name)`` or ``("entry", path)`` to select
        afterwards; by default the selection is kept."""
        from .library import ComponentLibrary
        from PySide6.QtWidgets import QStyle
        if select is None:
            select = ComponentTree.item_data(self._lib_tree.currentItem())
        tree = self._lib_tree
        tree.blockSignals(True)
        tree.clear()
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        picked = None
        for group in ComponentLibrary().tree():
            parent = tree
            if group["folder"] is not None:
                parent = QTreeWidgetItem(tree, [group["folder"]])
                parent.setIcon(0, folder_icon)
                parent.setData(0, Qt.ItemDataRole.UserRole, ("folder", group["folder"]))
                parent.setExpanded(True)
                if select == ("folder", group["folder"]):
                    picked = parent
            for e in group["entries"]:
                # The name only: a shipped entry's date was the day it was
                # copied in, the same on every row.
                item = QTreeWidgetItem(parent, [e["name"]])
                item.setToolTip(0, f"{e['name']}\nSaved {e['date']}")
                item.setData(0, Qt.ItemDataRole.UserRole, ("entry", e["path"]))
                if select == ("entry", e["path"]):
                    picked = item
        if picked is not None:
            tree.setCurrentItem(picked)
        tree.blockSignals(False)
        self._on_lib_selection_changed()

    def _lib_selected(self):
        """``("folder", name)``, ``("entry", path)`` or None."""
        return ComponentTree.item_data(self._lib_tree.currentItem())

    def _on_lib_selection_changed(self) -> None:
        sel = self._lib_selected()
        is_entry = bool(sel) and sel[0] == "entry"
        self._btn_lib_import.setEnabled(is_entry)
        self._btn_lib_rename.setEnabled(bool(sel))
        self._btn_lib_delete.setEnabled(bool(sel))
        self._btn_lib_move.setEnabled(is_entry)

    def _on_lib_double_clicked(self, item, _column=0) -> None:
        data = ComponentTree.item_data(item)
        if data and data[0] == "entry":
            self._import_from_library()

    def _import_from_library(self) -> None:
        sel = self._lib_selected()
        if not sel or sel[0] != "entry":
            return
        path = sel[1]
        try:
            from .library import ComponentLibrary
            curves, dims = ComponentLibrary().load_entry(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Import", str(exc))
            return
        if not curves:
            QMessageBox.information(self, "Empty Entry",
                                    "This library entry contains no geometry.")
            return

        # Translate bounding-box center to canvas origin.
        # _curves_bbox is radius-aware, so circles/arcs center correctly
        # (node-only bbox put a lone circle's *center point* at the origin).
        bb = _curves_bbox([c for c in curves if not c.mirrored])
        if bb:
            cx = (bb[0] + bb[2]) / 2
            cy = (bb[1] + bb[3]) / 2
            for c in curves:
                for nd in c.nodes:
                    nd.x -= cx;  nd.y -= cy
                    if nd.cp_in:
                        nd.cp_in.x  -= cx;  nd.cp_in.y  -= cy
                    if nd.cp_out:
                        nd.cp_out.x -= cx;  nd.cp_out.y -= cy
            for d in dims:
                d.x0 -= cx;  d.y0 -= cy
                d.x1 -= cx;  d.y1 -= cy

        # The kind: the folder placed from, as the maker named it. GuildModel
        # will read a kind with "hinge" in it as a hinge, any other as a
        # mount; a component outside any folder carries none.
        from .library import ComponentLibrary
        kind = ComponentLibrary.kind_of(path)
        self._push_undo_snapshot()
        # Import as a GROUP: the component moves as one rigid unit and exposes
        # no node dots, so its nodes can't be distorted by accidental node
        # drags snapping onto nearby frame geometry at the origin.
        gid = uuid.uuid4().hex[:8]
        # A layer this tab does not have lands on REF, as a paste's does: a
        # component saved from the front with LENS and DRILL curves, placed on
        # a temple, kept them, and the validator then refused the temple.
        allowed = set(WORKSPACE_LAYERS[self._active_ws.workspace_type])
        foreign = sorted({c.layer.value for c in curves if c.layer not in allowed})
        for c in curves:
            c.mirrored = False
            c.group_id = gid
            if c.layer not in allowed:
                c.layer = Layer.REF
            c.component_kind = kind if c.layer == Layer.COMPONENT else None
            self._active_ws.add_curve(c)
        for d in dims:
            self._active_ws.add_dim(d)

        name = os.path.splitext(os.path.basename(path))[0]
        note = (f"  ({_and_list(foreign)} moved to REF: not a layer of this tab)"
                if foreign else "")
        self._status.showMessage(
            f"Imported '{name}' as a group — {len(curves)} curve(s) at origin. "
            f"Drag or Point Move{self._key_hint('point_move')} to place; "
            "Ctrl+Shift+G to ungroup." + note, 8000)

    def _key_hint(self, key: str) -> str:
        """' (G)': the key bound to *key* now, for a message; '' if none."""
        key_str = getattr(self, "_hotkey_prefs", {}).get(key, "").strip()
        if key_str in SettingsDialog._RESERVED_KEYS or key_str in _TYPING_KEYS:
            key_str = ""
        return f" ({key_str})" if key_str else ""

    def _default_library_folder(self) -> str:
        """The folder a save goes to unless the maker picks another: the one
        selected, or the selected entry's, or the first."""
        from .library import ComponentLibrary
        sel = self._lib_selected()
        if sel and sel[0] == "folder":
            return sel[1]
        if sel and sel[0] == "entry":
            kind = ComponentLibrary.kind_of(sel[1])
            if kind:
                return kind
        folders = ComponentLibrary().folders()
        return folders[0] if folders else ""

    def _ask_library_save(self, default_folder: str):
        """``(name, folder)`` for a new entry, or None when canceled. The
        folder box lists the library's folders and takes a new name too."""
        from .library import ComponentLibrary
        dlg = QDialog(self)
        dlg.setWindowTitle("Save to Library")
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("For example, Zoye TH-23 Front")
        folder_box = QComboBox()
        folder_box.setEditable(True)
        folder_box.addItems(ComponentLibrary().folders())
        folder_box.setCurrentText(default_folder)
        folder_box.setToolTip("A folder of the library, or a new name for a new one.")
        form.addRow("Name:", name_edit)
        form.addRow("Folder:", folder_box)
        form.addRow("", SettingsDialog._hint(
            "Pick a folder, or type a new name to make one."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        # OK waits for a name: an empty OK used to do nothing at all.
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(False)
        name_edit.textChanged.connect(lambda t: ok.setEnabled(bool(t.strip())))
        form.addRow(buttons)
        name_edit.setFocus()
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return None
        return name_edit.text().strip(), folder_box.currentText().strip()

    def _ask_replace_entry(self, name: str, folder: str) -> str:
        """An entry of that name is in the folder already: "replace",
        "keep" (save beside it as name_2) or "cancel"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Replace the Entry?")
        where = folder or "The library"
        box.setText(f"{where} already holds \u201c{name}\u201d. Replace it?")
        replace = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Keep Both", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(keep)
        _run_modal(box)
        clicked = box.clickedButton()
        return ("replace" if clicked is replace
                else "keep" if clicked is keep else "cancel")

    def _save_to_library(self) -> None:
        if not self._doc_curves:
            QMessageBox.information(self, "Nothing to Save",
                                    "There is no geometry in this workspace to save.")
            return
        answer = self._ask_library_save(self._default_library_folder())
        if not answer or not answer[0]:
            return
        name, folder = answer
        try:
            from .library import ComponentLibrary
            lib = ComponentLibrary()
            replace = False
            if lib.entry_path(folder or None, name).exists():
                choice = self._ask_replace_entry(name, folder)
                if choice == "cancel":
                    return
                replace = choice == "replace"
            path = lib.save_entry(
                folder or None, name, self._doc_curves, self._doc_dims,
                replace=replace,
            )
            self._refresh_library_panel(select=("entry", path))
            where = f" in {folder}" if folder else ""
            self._status.showMessage(
                f"Saved to library{where}: {os.path.basename(path)}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Save to the Library", str(exc))

    def _new_library_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Name for the folder:")
        if not ok or not name.strip():
            return
        try:
            from .library import ComponentLibrary
            made = ComponentLibrary().create_folder(name.strip())
            self._refresh_library_panel(select=("folder", made))
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Make the Folder", str(exc))

    def _rename_library_entry(self) -> None:
        """Rename the selected folder or entry."""
        sel = self._lib_selected()
        if not sel:
            return
        from .library import ComponentLibrary
        if sel[0] == "folder":
            old_name = sel[1]
            title, label = "Rename Folder", "New name for the folder:"
        else:
            old_name = os.path.splitext(os.path.basename(sel[1]))[0]
            title, label = "Rename Library Entry", "New name:"
        new_name, ok = QInputDialog.getText(self, title, label, text=old_name)
        if not ok or not new_name.strip():
            return
        try:
            lib = ComponentLibrary()
            if sel[0] == "folder":
                select = ("folder", lib.rename_folder(old_name, new_name.strip()))
            else:
                select = ("entry", lib.rename_entry(sel[1], new_name.strip()))
            self._refresh_library_panel(select=select)
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Rename", str(exc))

    def _delete_library_entry(self) -> None:
        """Delete the selected entry, asking first, or the selected folder,
        asking first when it is not empty."""
        sel = self._lib_selected()
        if not sel:
            return
        from .library import ComponentLibrary
        lib = ComponentLibrary()
        # No is the default: Enter on the question used to delete.
        if sel[0] == "folder":
            seeded = lib.is_seeded_folder(sel[1])
            if not lib.folder_is_empty(sel[1]) or seeded:
                text = (f"Delete the folder \u201c{sel[1]}\u201d"
                        + ("" if lib.folder_is_empty(sel[1])
                           else " and every component in it") + "?")
                if seeded:
                    text += ("\n\nGuildDraw made this folder, and it will not "
                             "come back, nor will the starter components that "
                             "came in it.")
                r = QMessageBox.question(
                    self, "Delete Folder", text,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r != QMessageBox.StandardButton.Yes:
                    return
            lib.delete_folder(sel[1])
        else:
            name = os.path.splitext(os.path.basename(sel[1]))[0]
            r = QMessageBox.question(
                self, "Delete Library Entry",
                f"Delete \u201c{name}\u201d from the library?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
            lib.delete_entry(sel[1])
        self._refresh_library_panel(select=())

    def _move_library_entry(self, path: str, folder) -> None:
        """Move an entry into *folder* (None: outside any), as a drop does."""
        try:
            from .library import ComponentLibrary
            moved = ComponentLibrary().move_entry(path, folder)
            self._refresh_library_panel(select=("entry", moved))
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Move", str(exc))

    def _move_library_entry_to_folder(self) -> None:
        sel = self._lib_selected()
        if not sel or sel[0] != "entry":
            return
        from .library import ComponentLibrary
        folders = ComponentLibrary().folders()
        if not folders:
            self._status.showMessage("Move to Folder: make a folder first (New Folder…)")
            return
        current = ComponentLibrary.kind_of(sel[1])
        start = folders.index(current) if current in folders else 0
        folder, ok = QInputDialog.getItem(self, "Move to Folder", "Folder:",
                                          folders, start, False)
        if ok and folder:
            self._move_library_entry(sel[1], folder)

    def _reorder_library_folders(self, order: list) -> None:
        from .library import ComponentLibrary
        ComponentLibrary().set_folder_order(order)
        self._refresh_library_panel()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Drill holes (DRILL layer + pattern library, M13)
    # ------------------------------------------------------------------

    def _build_holes_panel(self) -> QWidget:
        """Drill-hole coordinate entry + pattern library (front workspace)."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        hint = QLabel("Holes go on the DRILL layer, offset from the lens boxing "
                      "center (the OMA datum).")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        entry = self._fold_box("Place Hole")
        form = QFormLayout(entry.body)
        form.setSpacing(6)
        self._drill_x = QDoubleSpinBox()
        self._drill_x.setRange(-60, 60); self._drill_x.setSuffix(" mm")
        self._drill_x.setDecimals(2); self._drill_x.setSingleStep(0.5)
        self._drill_y = QDoubleSpinBox()
        self._drill_y.setRange(-40, 40); self._drill_y.setSuffix(" mm")
        self._drill_y.setDecimals(2); self._drill_y.setSingleStep(0.5)
        self._drill_dia = QDoubleSpinBox()
        self._drill_dia.setRange(0.5, 6.0); self._drill_dia.setSuffix(" mm")
        self._drill_dia.setDecimals(2); self._drill_dia.setSingleStep(0.1)
        self._drill_dia.setValue(1.4)
        self._drill_x.setToolTip("Toward the nose is positive, on either lens.")
        self._drill_y.setToolTip("Above the lens center is positive, as in an "
                                 "OMA trace.")
        form.addRow("X (from center):", self._drill_x)
        form.addRow("Y (from center):", self._drill_y)
        form.addRow("Diameter:", self._drill_dia)
        btn_add = QPushButton("Add Hole")
        btn_add.setToolTip("Place a hole at this offset from the lens boxing center.")
        btn_add.clicked.connect(self._add_drill_hole_from_fields)
        form.addRow(btn_add)
        lay.addWidget(entry)

        lay.addWidget(QLabel("Saved patterns:"))
        self._drill_list = QListWidget()
        self._drill_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._drill_list.setAlternatingRowColors(True)
        self._drill_list.itemSelectionChanged.connect(self._on_drill_selection_changed)
        self._drill_list.itemDoubleClicked.connect(lambda _: self._import_drill_pattern())
        lay.addWidget(self._drill_list)

        self._btn_drill_import = QPushButton("Import Pattern onto Lens")
        self._btn_drill_import.setEnabled(False)
        self._btn_drill_import.clicked.connect(self._import_drill_pattern)
        lay.addWidget(self._btn_drill_import)

        self._btn_drill_save = QPushButton("Save Current Holes as Pattern…")
        self._btn_drill_save.clicked.connect(self._save_drill_pattern)
        lay.addWidget(self._btn_drill_save)

        drow = QHBoxLayout()
        self._btn_drill_rename = QPushButton("Rename…")
        self._btn_drill_rename.setEnabled(False)
        self._btn_drill_rename.clicked.connect(self._rename_drill_pattern)
        self._btn_drill_delete = QPushButton("Delete")
        self._btn_drill_delete.setEnabled(False)
        self._btn_drill_delete.clicked.connect(self._delete_drill_pattern)
        drow.addWidget(self._btn_drill_rename)
        drow.addWidget(self._btn_drill_delete)
        lay.addLayout(drow)
        lay.addStretch()

        self._refresh_drill_library_panel()
        return w

    def _lens_boxing_center(self):
        """(cx, cy) of the representative front LENS (sampled), or None."""
        front = self._workspaces[0]
        lenses = [c for c in front.doc_curves
                  if c.layer == Layer.LENS and not c.mirrored and c.nodes]
        if not lenses:
            return None
        from .boxing import lens_bbox
        boxes = [bb for bb in (lens_bbox(c) for c in lenses) if bb is not None]
        if not boxes:
            return None
        # With both lenses drawn the datum is the OD lens (smaller boxing-
        # center x, the OMA export's rule), not whichever was drawn first.
        bb = min(boxes, key=lambda b: (b[0] + b[2]) / 2.0)
        return ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)

    def _drill_datum(self):
        """(cx, cy, sx) for drill offsets: the datum lens's boxing center and
        the x sign that puts an offset in the OD lens's frame. A pattern's dx
        is measured on the OD lens (the OMA rule), so an offset taken from or
        placed on a lens drawn right of the axis (the OS side) is mirrored —
        before, a pattern saved on one side landed nasal-for-temporal on a
        frame drawn on the other. Either way +dx points toward the nose."""
        center = self._lens_boxing_center()
        if center is None:
            return None
        cx, cy = center
        front = self._workspaces[0]
        axis_x = front.scene.mirror.x if front.scene.mirror is not None else 0.0
        return cx, cy, (-1.0 if cx > axis_x else 1.0)

    def _place_drill_holes(self, holes, od_frame: bool = True) -> bool:
        """holes: list of (dx, dy, dia), dx in the OD lens's frame (see
        _drill_datum) — or, od_frame=False, as drawn (a version-1 pattern).
        Place DRILL circles relative to the lens boxing center on the front
        workspace; undo-safe + selected."""
        center = self._drill_datum()
        if center is None:
            QMessageBox.information(
                self, "No Lens",
                "Draw a LENS shape first — drill holes are placed relative to the "
                "lens boxing center.")
            return False
        cx, cy, sx = center
        if not od_frame:
            sx = 1.0
        self._ws_tab_widget.setCurrentIndex(0)   # holes live on the front
        self._push_undo_snapshot()
        self.scene.clearSelection()
        for dx, dy, dia in holes:
            c = Curve(kind="circle", layer=Layer.DRILL,
                      nodes=[SplineNode(cx + sx * dx, cy + dy)],
                      radius=max(0.05, dia / 2.0), closed=True)
            self._active_ws.add_curve(c).setSelected(True)
        return True

    def _add_drill_hole_from_fields(self):
        # The field reads y-up, as the hint's OMA datum does; the scene is
        # y-down. Typed as-is, a lab's "3 mm above" landed 3 mm below.
        if self._place_drill_holes([(self._drill_x.value(), -self._drill_y.value(),
                                     self._drill_dia.value())]):
            self._status.showMessage(
                f"Placed a {self._drill_dia.value():.2f} mm hole at "
                f"({self._drill_x.value():.2f}, {self._drill_y.value():.2f}) "
                "from the lens center.")

    def _current_drill_holes_relative(self):
        """Front DRILL circles → [(dx, dy, dia)] offsets from the boxing
        center, dx in the OD lens's frame (see _drill_datum)."""
        center = self._drill_datum()
        if center is None:
            return []
        cx, cy, sx = center
        holes = []
        for c in self._workspaces[0].doc_curves:
            if (c.layer == Layer.DRILL and not c.mirrored
                    and c.kind == "circle" and c.nodes):
                holes.append((sx * (c.nodes[0].x - cx), c.nodes[0].y - cy,
                              2.0 * (c.radius or 0.7)))
        return holes

    def _save_drill_pattern(self):
        holes = self._current_drill_holes_relative()
        if not holes:
            QMessageBox.information(
                self, "No Holes",
                "There are no DRILL holes on the front workspace to save.")
            return
        name, ok = QInputDialog.getText(self, "Save Drill Pattern",
                                        "Name for this hole pattern:")
        if not ok or not name.strip():
            return
        from .library import DrillLibrary
        DrillLibrary().save_entry(
            name.strip(),
            [{"dx": h[0], "dy": h[1], "dia": h[2]} for h in holes])
        self._refresh_drill_library_panel()
        self._status.showMessage(
            f"Saved drill pattern '{name.strip()}' ({len(holes)} hole(s)).")

    def _import_drill_pattern(self):
        item = self._drill_list.currentItem()
        if item is None:
            return
        from .library import DrillLibrary
        try:
            holes = DrillLibrary().load_entry(item.data(Qt.ItemDataRole.UserRole))
        except Exception as exc:        # a damaged pattern file did nothing, silently
            QMessageBox.warning(self, "Could Not Import",
                                f"The pattern could not be read.\n\n{exc}")
            return
        if holes and self._place_drill_holes(
                [(h["dx"], h["dy"], h["dia"]) for h in holes],
                od_frame=all(h.get("od_frame", True) for h in holes)):
            self._status.showMessage(
                f"Imported {len(holes)} hole(s) from "
                f"'{item.text().split('  ·')[0]}'.")

    def _refresh_drill_library_panel(self):
        from .library import DrillLibrary
        self._drill_list.clear()
        for e in DrillLibrary().list_entries():
            it = QListWidgetItem(f"{e['name']}  ·  {e['date']}")
            it.setData(Qt.ItemDataRole.UserRole, e["path"])
            self._drill_list.addItem(it)
        self._on_drill_selection_changed()

    def _on_drill_selection_changed(self):
        has = self._drill_list.currentItem() is not None
        self._btn_drill_import.setEnabled(has)
        self._btn_drill_rename.setEnabled(has)
        self._btn_drill_delete.setEnabled(has)

    def _rename_drill_pattern(self):
        item = self._drill_list.currentItem()
        if item is None:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename Pattern", "New name:",
            text=item.text().split("  ·")[0])
        if not ok or not new_name.strip():
            return
        from .library import DrillLibrary
        try:
            DrillLibrary().rename_entry(item.data(Qt.ItemDataRole.UserRole),
                                        new_name.strip())
        except ValueError as e:
            QMessageBox.warning(self, "Could Not Rename", str(e))
            return
        self._refresh_drill_library_panel()

    def _delete_drill_pattern(self):
        item = self._drill_list.currentItem()
        if item is None:
            return
        if QMessageBox.question(
                self, "Delete Pattern",
                f"Delete \u201c{item.text().split('  ·')[0]}\u201d?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            from .library import DrillLibrary
            DrillLibrary().delete_entry(item.data(Qt.ItemDataRole.UserRole))
            self._refresh_drill_library_panel()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def _start_calibration(self):
        self.view.setFocus()
        # The photo the tool measures when the first click misses every one.
        self._calib_tool.preferred_index = self._selected_photo()
        self._calib_tool.start(self.scene)

    def _selected_photo(self, ws: "WorkspaceState | None" = None) -> int:
        """The selected shown photo, else the first."""
        return max(0, self._shown_face(ws))

    def _show_calibration(self, ws: "WorkspaceState | None" = None):
        """The Canvas tab's calibration fields, for the selected photo."""
        ws = ws or self._active_ws
        has_photo = ws.scene.face_count() > 0
        index = self._selected_photo(ws)
        px = ws.scene.face_calibration(index) if has_photo else None
        self._pxmm_spin.blockSignals(True)
        self._pxmm_spin.setValue(px or 1.0)      # not the previous tab's value
        self._pxmm_spin.blockSignals(False)
        # The scale is the image's size: a locked image keeps it.
        self._pxmm_spin.setEnabled(has_photo and not ws.scene.face_is_locked(index))
        self._calib_btn.setEnabled(has_photo)
        self._calib_label.setText(
            f"{px:.4f} px/mm" if px else
            "Not set" if has_photo else
            "Add a reference image first (Add Image…), then calibrate.")

    def _apply_calibration(self, px_per_mm: float, index: int | None = None):
        """Scale reference photo *index* so px_per_mm of its pixels make one
        mm, or every photo (None: a file's one calibration for the design)."""
        self.scene.set_face_calibration(px_per_mm, index)
        # The design's own value, as files before 2.0 read it: the first
        # photo's (or the one set, before any photo).
        self._image_px_per_mm = self.scene.face_calibration(0) or px_per_mm
        self._mark_dirty()   # calibration is persisted in the file
        self._show_calibration()
        which = ""
        if index is not None and self.scene.face_count() > 1:
            which = f" ({os.path.basename(self._active_ws.face_image_paths[index])})" \
                if index < len(self._active_ws.face_image_paths) else ""
        self._status.showMessage(
            f"Reference image calibrated{which}: {px_per_mm:.4f} image pixels per mm")

    def _apply_manual_calib(self):
        v = self._pxmm_spin.value()
        index = self._selected_photo()
        current = self.scene.face_calibration(index)
        # editingFinished fires on a mere click away. Apply a change only:
        # leaving an uncalibrated photo's untouched 1.0 placeholder applied
        # 1 px/mm — a 3000 px photo became 3 m wide — and marked the design
        # changed.
        if v <= 0 or (current and abs(v - current) < 1e-9) \
                or (not current and v == 1.0):
            return
        self._apply_calibration(v, index)

    # ------------------------------------------------------------------
    # Dirty flag / window title
    # ------------------------------------------------------------------

    def _update_title(self):
        name = (os.path.basename(self._current_path)
                if self._current_path else "Untitled")
        star = "*" if self._dirty else ""
        self.setWindowTitle(f"GuildDraw {__version__} — {name}{star}")

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _clear_dirty(self):
        if self._dirty:
            self._dirty = False
        self._update_title()

    def _confirm_discard(self, action: str = "closing") -> bool:
        """If there are unsaved changes, offer Save / Don't Save / Cancel,
        naming the design and *action* ("closing", "opening another file",
        "starting a new design").

        Returns True when it is safe to proceed (saved, discarded, or clean).
        """
        if not self._dirty:
            return True
        name = (os.path.basename(self._current_path) if self._current_path
                else "this design")
        r = QMessageBox.warning(
            self, "Save Changes?",
            f"Save the changes to {name} before {action}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            if not self._save():
                return False         # canceled, or the failure already said so
            if self._dirty:
                # "Save Front Only" into a .svg: the rest is still unsaved, so
                # stay — and say why, or the window just refuses to close.
                # (It said so after a canceled save too, which saved nothing.)
                QMessageBox.information(
                    self, "Not All Saved",
                    f"The Frame Front was saved to "
                    f"{os.path.basename(self._current_path)}. "
                    f"{_and_list(self._other_workspaces_in_use())} are not "
                    "saved. To keep them, use File ▸ Save As… and choose a "
                    ".gdraw project; to drop them, choose Discard.")
                return False
            return True
        return True   # Discard

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self._save_prefs_on_close()
        # The app-wide filters go with the window. Left installed, a closed
        # window's two filters kept running on every event the app delivers —
        # one stylesheet pass is ~12,000 of them — and a test session's
        # closed windows piled them up until each new window took seconds.
        app = QApplication.instance()
        app.removeEventFilter(self._tooltip_filter)
        app.removeEventFilter(self)
        self._clear_autosave()
        for lock in [getattr(self, "_autosave_lock", None),
                     *getattr(self, "_orphan_locks", {}).values()]:
            if lock is not None:
                lock.unlock()
        # Teardown: destroying a scene deletes its items, and deleting a
        # selected item emits selectionChanged — into slots that would call
        # back into the half-destroyed scene (shiboken RuntimeError on quit).
        # Sever every selectionChanged connection (ours + each EditTool's)
        # now that no further UI updates can matter.
        # Once: a second close found nothing connected, and PySide warned.
        if not getattr(self, "_selection_severed", False):
            self._selection_severed = True
            for ws in self._workspaces:
                try:
                    ws.scene.selectionChanged.disconnect()
                except RuntimeError:
                    pass   # already disconnected / already gone
        super().closeEvent(event)

    def _save_prefs_on_close(self):
        """The window's geometry, then the preferences, as the window closes.
        A batch window replaces this with a no-op (export/batch_catalog.py,
        prepare_window): it was never shown, and its preferences carry the
        run's own settings."""
        self._prefs["main_window_geometry"] = bytes(
            self.saveGeometry().toBase64()).decode()
        self._prefs["dock_folds"] = self._fold_state()
        _prefs_mod.save(self._prefs)

    # ------------------------------------------------------------------
    # Autosave + crash recovery
    # ------------------------------------------------------------------

    _AUTOSAVE_MS  = 180_000   # 3 minutes
    _AUTOSAVE_DIR = Path.home() / ".guilddraw" / "autosave"

    # One recovery slot per running copy, "recovery-<pid>-<token>" (the token
    # so a crashed copy whose pid comes round again is never taken for this
    # one), owned through a QLockFile held while that copy runs. A slot whose lock can be taken
    # belongs to a copy that is gone — a crash's work, offered at startup.
    # Until 1.3 every copy shared one "recovery.gdraw": a second launch
    # offered the first copy's live work, and answering No deleted it.
    # (That legacy name is still offered once, as an orphan.)

    def _autosave_paths(self) -> tuple[Path, Path]:
        token = getattr(self, "_autosave_token", None)
        if token is None:
            token = self._autosave_token = uuid.uuid4().hex[:8]
        slot = self._AUTOSAVE_DIR / f"recovery-{os.getpid()}-{token}"
        return slot.with_suffix(".gdraw"), slot.with_suffix(".json")

    def _hold_autosave_slot(self) -> bool:
        """Take (once) the lock that marks this copy's slot as live."""
        lock = getattr(self, "_autosave_lock", None)
        if lock is None:
            from PySide6.QtCore import QLockFile
            self._AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
            rec, _meta = self._autosave_paths()
            lock = QLockFile(str(rec.with_suffix(".lock")))
            lock.setStaleLockTime(0)          # stale only when the owner is gone
            self._autosave_lock = lock
        return lock.isLocked() or lock.tryLock(0)

    def _orphan_slots(self) -> list[Path]:
        """Recovery files left by copies that are no longer running, newest
        first. Taking an orphan's lock keeps a second copy starting now from
        offering the same work; it is let go with the slot (_remove_slot)."""
        try:
            found = [p for p in self._AUTOSAVE_DIR.glob("recovery*.gdraw")
                     if p != self._autosave_paths()[0]]
        except OSError:
            return []
        from PySide6.QtCore import QLockFile
        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0
        self._sweep_leftover_locks()
        out = []
        for rec in sorted(found, key=_mtime, reverse=True):
            lock = QLockFile(str(rec.with_suffix(".lock")))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0) and lock.getLockInfo()[0] == 0 \
                    and _mtime(rec) < time.time() - 2 * self._AUTOSAVE_MS / 1000:
                # A lock cut short by a crash or a power cut names no owner, so
                # Qt can never call it stale. Its slot has not been written in
                # two autosave periods: nobody owns it.
                rec.with_suffix(".lock").unlink(missing_ok=True)
                lock.tryLock(0)
            if lock.isLocked():               # its owner is gone (or never locked)
                self._orphan_locks = {**getattr(self, "_orphan_locks", {}),
                                      rec: lock}
                out.append(rec)
        return out

    def _sweep_leftover_locks(self):
        """Delete the lock files of slots that no longer exist — a copy that
        crashed after a save, New or Open (which empty its slot) left one."""
        from PySide6.QtCore import QLockFile
        own = self._autosave_paths()[0].with_suffix(".lock")
        try:
            leftovers = [p for p in self._AUTOSAVE_DIR.glob("recovery*.lock")
                         if p != own and not p.with_suffix(".gdraw").exists()]
        except OSError:
            return
        for path in leftovers:
            lock = QLockFile(str(path))
            lock.setStaleLockTime(0)
            if lock.tryLock(0):               # stale: taking and letting go removes it
                lock.unlock()
            elif lock.getLockInfo()[0] == 0:
                # Unreadable (cut short by a crash). A minute old, it is not a
                # lock another copy is writing this instant.
                try:
                    if path.stat().st_mtime < time.time() - 60:
                        path.unlink()
                except OSError:
                    pass

    def _release_orphan(self, rec: Path):
        """Let go of an orphan's lock and leave its files for the next launch."""
        lock = getattr(self, "_orphan_locks", {}).pop(rec, None)
        if lock is not None:
            lock.unlock()

    def _remove_slot(self, rec: Path):
        for p in (rec, rec.with_suffix(".json"), rec.with_name(rec.name + ".tmp")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        lock = getattr(self, "_orphan_locks", {}).pop(rec, None)
        if lock is not None:
            lock.unlock()                     # removes the orphan's lock file

    def _do_autosave(self):
        """Timer tick: snapshot dirty work to the recovery slot.

        Must never interrupt the user — failures are silent; success shows a
        brief status note.
        """
        if not self._dirty:
            return
        rec, meta = self._autosave_paths()
        try:
            if not self._hold_autosave_slot():
                return
            tmp = str(rec) + ".tmp"
            # The design's own file stands in for an image that cannot be
            # read now, as in a save (_do_save_gdraw).
            src = self._current_path
            self._do_save_gdraw(tmp, carry_from=src if src and src.lower()
                                .endswith(".gdraw") else None)
            os.replace(tmp, rec)
            meta.write_text(json.dumps({
                "source_path": self._current_path,
                "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }), encoding="utf-8")
            # A brief note that hands the bar back: shown bare, it wiped the
            # active tool's instructions every three minutes.
            covered = self._status.currentMessage()
            self._status.showMessage("Autosaved", 2000)
            if covered:
                self._autosave_covered = covered
                QTimer.singleShot(2100, self, self._restore_after_autosave_note)
        except Exception:
            pass

    def _restore_after_autosave_note(self):
        msg, self._autosave_covered = getattr(self, "_autosave_covered", ""), ""
        if msg and not self._status.currentMessage():
            self._status.showMessage(msg)

    def _clear_autosave(self):
        """Empty this copy's own slot (after a save, New, Open or a clean
        close). Other copies' slots are never touched here."""
        self._remove_slot(self._autosave_paths()[0])

    def _offer_recovery(self, opening: str | None = None) -> bool:
        """On startup: offer to restore work a crashed copy left behind.
        Runs once. `opening` is a file named on the command line, which is
        opened only when the maker declines. Returns True when work was
        restored."""
        if getattr(self, "_recovery_offered", False):
            return False
        self._recovery_offered = True
        for rec in self._orphan_slots():
            if self._offer_one_recovery(rec, opening):
                return True
        return False

    def _ask_recovery(self, text: str, detail: str) -> str:
        """"restore", "later" (also Esc and the window's close box: the safe
        answer) or "discard"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Recover Unsaved Work?")
        box.setText(text)
        box.setInformativeText(detail)
        restore = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(restore)
        box.setEscapeButton(later)
        _run_modal(box)
        clicked = box.clickedButton()
        return ("restore" if clicked is restore
                else "discard" if clicked is discard else "later")

    def _offer_one_recovery(self, rec: Path, opening: str | None) -> bool:
        meta = rec.with_suffix(".json")
        source = None
        when   = "an unknown time"
        try:
            info   = json.loads(meta.read_text(encoding="utf-8"))
            source = info.get("source_path")
            when   = info.get("saved_at", when)
        except Exception:
            pass
        if not isinstance(source, str):
            source = None
        name = os.path.basename(source) if source else "an unsaved document"
        # Saved again after this autosave (in another window, or after a
        # restart the crash did not stop): restored under its path, the older
        # work went over the newer save at the next Ctrl+S.
        newer = False
        try:    # "2026-09-27T10:33:12" → "2026-09-27 at 10:33"
            stamp = datetime.datetime.fromisoformat(when)
            when = stamp.strftime("%Y-%m-%d at %H:%M")
            newer = bool(source and os.path.isfile(source)
                         and os.path.getmtime(source) > stamp.timestamp() + 2)
        except (TypeError, ValueError, OSError):
            pass
        text = f"GuildDraw found autosaved work from {when}\n({name})."
        if newer:
            text += (f"\n\n{name} was saved again after this autosave. "
                     "Restoring opens the older work as a new, unsaved design "
                     "and leaves the newer file alone.")
        later = "Later keeps it and asks again next time."
        if opening:
            # A file was double-clicked: say what happens to it, and never
            # steer toward the answer that throws the recovered work away.
            later = (f"Later opens {os.path.basename(opening)} now, and keeps "
                     "the autosaved work to ask about next time.")
        choice = self._ask_recovery(
            text, f"Restore it? {later} Discard deletes it.")
        if choice == "later":
            self._release_orphan(rec)
            return False
        if choice != "restore":
            self._remove_slot(rec)
            return False
        status = self._open_gdraw(str(rec), remember=False)
        if status is None:
            # Unreadable: keep it for manual salvage under another name so
            # the next launch does not ask (and fail) again.
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                rec.rename(rec.with_name(f"failed-{stamp}.gdraw.bak"))
            except OSError:
                pass
            self._remove_slot(rec)
            self._status.showMessage(
                f"Recovery file could not be read — kept as failed-{stamp}.gdraw.bak")
            return False
        if status == "ok":
            # The recovered content belongs to the original document, not
            # the recovery file: restore the real path and mark it unsaved.
            self._current_path = (source if source and os.path.isfile(source)
                                  and not newer else None)
            self._remember_disk_state(self._current_path)
        kept = None
        if status == "errors":
            # _open_gdraw dropped the path so Save asks for a new name — a
            # half-recovered file must never overwrite the original. And the
            # recovery file stays, whole: it is the only copy of what could
            # not be read, and it was deleted below once this copy's slot
            # held the part that could.
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            kept = rec.with_name(f"failed-{stamp}.gdraw.bak")
            try:
                rec.rename(kept)
            except OSError:
                kept = None
        self._mark_dirty()
        self._update_title()
        # The work is in this copy now: write it to this copy's own slot
        # before letting the dead copy's go, so a second crash loses nothing.
        self._do_autosave()
        if self._autosave_paths()[0].exists():
            self._remove_slot(rec)
        # Say what happened in the maker's words; _open_gdraw's own message
        # named the internal slot file.
        self._status.showMessage(
            f"Restored autosaved work from {when}"
            + (f"; the whole recovery file is kept as {kept}" if kept else "")
            + (f"; {os.path.basename(opening)} was not opened" if opening else ""))
        return True

    # ------------------------------------------------------------------
    # Recent files
    # ------------------------------------------------------------------

    _MAX_RECENT = 8

    def _add_recent(self, path: str):
        path = os.path.abspath(path)
        self._recent_files = ([path]
                              + [p for p in self._recent_files if p != path])
        del self._recent_files[self._MAX_RECENT:]
        self._prefs["recent_files"] = list(self._recent_files)
        _prefs_mod.save(self._prefs)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        m = self._recent_menu
        m.clear()
        if not self._recent_files:
            empty = m.addAction("(empty)")
            empty.setEnabled(False)
            return
        for p in self._recent_files:
            act = m.addAction(os.path.basename(p),
                              lambda checked=False, p=p: self._open_recent(p))
            act.setToolTip(p)
        m.addSeparator()
        m.addAction("Clear Recent", self._clear_recent)

    def _clear_recent(self):
        self._recent_files = []
        self._prefs["recent_files"] = []
        _prefs_mod.save(self._prefs)
        self._rebuild_recent_menu()

    def _open_recent(self, path: str):
        if not os.path.isfile(path):
            QMessageBox.warning(self, "File Not Found",
                                f"{path}\n\nno longer exists.")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._prefs["recent_files"] = list(self._recent_files)
            _prefs_mod.save(self._prefs)
            self._rebuild_recent_menu()
            return
        if not self._confirm_discard("opening another file"):
            return
        self._open_path(path)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _image_too_large(self, path: str) -> bool:
        """Whether *path* is past what a design carries (gdraw's
        _MAX_IMAGE_BYTES), said when it is: such an image showed, saved, and
        was gone at the next open."""
        from .export.gdraw import _MAX_IMAGE_BYTES
        try:
            size = os.path.getsize(path)
        except OSError:
            return False                   # the loader says what is wrong
        if size <= _MAX_IMAGE_BYTES:
            return False
        QMessageBox.warning(
            self, "Image Too Large",
            f"{os.path.basename(path)} is {size / (1024 * 1024):.0f} MB; a design "
            f"carries images of up to {_MAX_IMAGE_BYTES // (1024 * 1024)} MB. Use "
            "a smaller copy: a JPEG of a few MB is plenty to trace over.")
        return True

    def _add_face(self, path: str | None = None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Add Reference Image", self._dialog_dir("last_image_dir"),
                "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
            )
        if not path or self._image_too_large(path):
            return
        self._remember_dir(path, "last_image_dir")
        idx = self.scene.add_face(path)
        self._sync_empty_hint()
        if idx is not None:
            # Not stored: the design names it by an id this computer maps to
            # the file (image_links), until the maker stores it.
            link = image_links.new_id()
            self.scene.set_face_link(idx, link)
            image_links.remember(link, path)
            # Unlocked, to be placed, turned and calibrated; locked once set.
            self.scene.set_canvas_locked(idx, False)
            self._active_ws.selected_face_idx = idx
            self._refresh_face_list()
            if idx == 0:
                self.view.fit_view(self.scene.sceneRect())
            self._mark_dirty()
            self._status.showMessage(
                f"Loaded: {os.path.basename(path)}. Drag it into place, turn and "
                "calibrate it, then lock it (the padlock on the Canvas tab).")
        else:
            self._show_calibration()
            self._status.showMessage(f"Failed to load image: {path}")

    # The Canvas tab lists a row per image: the shown ones in the scene's
    # order, then those the file names that could not be shown
    # (WorkspaceState.unshown_faces), for Locate… or Remove.

    def _shown_face(self, ws: "WorkspaceState | None" = None) -> int:
        """The selected row's scene index, or -1: no row, or an unshown one."""
        ws = ws or self._active_ws
        row = ws.selected_face_idx
        return row if 0 <= row < ws.scene.face_count() else -1

    def _face_name(self, ws: "WorkspaceState", row: int) -> str:
        """A row's name: the image's own file name, or for one the design
        does not store and this computer does not have, its number. The
        file never names such an image."""
        from .export.gdraw import _photo_name
        n = ws.scene.face_count()
        if row < n:
            return _photo_name(os.path.basename(ws.scene.face_path(row)))
        fi = ws.unshown_faces[row - n]
        if fi.stored and fi.path:
            return _photo_name(os.path.basename(fi.path))
        return f"Reference {row + 1}"

    def _stored_icon(self, stored: bool) -> QIcon:
        """The paperclip: in ink when the design stores the image, faint
        when it stays on this computer."""
        color = theme.color("chrome.ink" if stored else "chrome.disabled_ink")
        # On a selected row too the faint one stays fainter.
        on_row = theme.color("chrome.checked_ink")
        if not stored:
            on_row = theme._mix(on_row, theme.color("chrome.checked_bg"), 0.55)
        cache = getattr(self, "_layer_icon_cache", None)
        if cache is None:
            cache = self._layer_icon_cache = {}
        key = ("image-stored", color, on_row)
        if key not in cache:
            cache[key] = _make_icon("image-stored", color, color,
                                    selected_color=on_row)
        return cache[key]

    def _refresh_face_list(self, ws: "WorkspaceState | None" = None):
        """Rebuild the Canvas tab's rows from *ws* and select its row."""
        ws = ws or self._active_ws
        if ws is not self._active_ws:
            return
        tree = self._face_tree
        tree.blockSignals(True)
        tree.clear()
        faint = QColor(theme.color("chrome.disabled_ink"))
        n = ws.scene.face_count()
        for row in range(n + len(ws.unshown_faces)):
            name = self._face_name(ws, row)
            if row < n:
                sc = ws.scene
                stored = sc.face_stored(row)
                item = QTreeWidgetItem([name, "", "", ""])
                item.setToolTip(0, name)
                item.setIcon(1, self._layer_icon(
                    "layer-show" if sc.face_visible(row) else "layer-hide"))
                item.setToolTip(1, f"Show or hide {name}")
                item.setIcon(2, self._layer_icon(
                    "layer-lock" if sc.face_is_locked(row) else "layer-unlock"))
                item.setToolTip(2, f"Lock or unlock {name}: its place, turn "
                                   "and scale")
                item.setIcon(3, self._stored_icon(stored))
                item.setToolTip(3, (
                    "Stored in the design: it shows on any computer that opens "
                    "the file. Click to keep it on this computer only."
                    if stored else
                    "On this computer only: the design keeps its place, not the "
                    "image. Click to store it in the design."))
            else:
                stored = ws.unshown_faces[row - n].stored
                why = "could not be shown" if stored else "not on this computer"
                item = QTreeWidgetItem([f"{name} — {why}", "", "", ""])
                item.setForeground(0, faint)
                item.setToolTip(0, (
                    "Stored in the design but not shown: too large, damaged or "
                    "not found. The next save keeps it. Locate… shows another "
                    "file in its place." if stored else
                    "The design does not store this image, and it is not on "
                    "this computer, or it has moved. Locate… finds it; its "
                    "place and calibration are kept."))
            tree.addTopLevelItem(item)
            if row >= n:
                item.setFirstColumnSpanned(True)    # no icons: the whole width
        row = ws.selected_face_idx
        if 0 <= row < tree.topLevelItemCount():
            tree.setCurrentItem(tree.topLevelItem(row))
        else:
            ws.selected_face_idx = -1
        tree.blockSignals(False)
        self._sync_face_controls()

    def _sync_face_controls(self):
        """Enable and fill the controls under the rows for the selected one."""
        ws = self._active_ws
        idx = self._shown_face(ws)
        has_row = 0 <= ws.selected_face_idx < self._face_tree.topLevelItemCount()
        self._remove_img_btn.setEnabled(has_row)
        self._locate_img_btn.setEnabled(has_row and idx < 0)
        self._opacity_slider.setEnabled(idx >= 0)
        self._rotation_spin.setEnabled(idx >= 0 and not ws.scene.face_is_locked(idx))
        if idx >= 0:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(int(ws.scene.face_opacity(idx) * 100))
            self._opacity_slider.blockSignals(False)
            self._rotation_spin.blockSignals(True)
            self._rotation_spin.setValue(ws.scene.face_rotation(idx))
            self._rotation_spin.blockSignals(False)
        self._show_calibration(ws)        # the selected photo's own

    def _on_face_row_changed(self, row: int):
        self._selected_face_idx = row
        self._sync_face_controls()

    def _on_face_tree_clicked(self, item, column: int):
        ws = self._active_ws
        row = self._face_tree.indexOfTopLevelItem(item)
        if column == 0 or not 0 <= row < ws.scene.face_count():
            return
        name = self._face_name(ws, row)
        if column == 1:
            on = not ws.scene.face_visible(row)
            ws.scene.set_face_visible(row, on)
            self._status.showMessage(
                f"{name} {'shown' if on else 'hidden: it is left out of PNG export and printing'}.")
        elif column == 2:
            locked = not ws.scene.face_is_locked(row)
            ws.scene.set_canvas_locked(row, locked)
            self._status.showMessage(
                f"{name} locked." if locked else
                f"{name} unlocked: drag it into place, turn it and calibrate "
                "it, then lock it again.")
        elif column == 3:
            if not self._set_face_stored(ws, row, not ws.scene.face_stored(row)):
                return
        ws.selected_face_idx = row
        self._refresh_face_list(ws)
        self._mark_dirty()

    def _set_face_stored(self, ws: "WorkspaceState", idx: int, stored: bool) -> bool:
        """Store the image *idx* in the design, or keep it on this computer
        only. Whether it changed: the maker may decline either."""
        name = self._face_name(ws, idx)
        if stored:
            if not self._confirm_store_image(name):
                return False
            ws.scene.set_face_stored(idx, True)
            self._status.showMessage(
                f"{name} is stored in the design: it shows on any computer that "
                "opens the file.")
            return True
        path = self._file_for_unstored(ws, idx, name)
        if path is None:
            return False
        link = ws.scene.face_link(idx) or image_links.new_id()
        ws.scene.set_face_link(idx, link)
        ws.scene.set_face_path(idx, path)
        image_links.remember(link, path)
        ws.scene.set_face_stored(idx, False)
        self._status.showMessage(
            f"{name} is no longer stored in the design; it stays at {path} on "
            "this computer.")
        return True

    def _confirm_store_image(self, name: str) -> bool:
        """Say what storing an image does before it is done, unless the maker
        has said not to ask (Preferences ▸ General ▸ Prompts turns it back
        on)."""
        if not self._prefs.get("prompt_store_image", True):
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Store Image in the Design?")
        box.setText(f"Store {name} in the design?")
        box.setInformativeText(
            "The image is copied into the design file, so it shows when the "
            "file is opened on another computer, and anyone you send the file "
            "to can see it.\n\nNot stored, it stays where it is on this "
            "computer: the file keeps only its place on the canvas, and other "
            "computers list it as not on this computer.")
        store = box.addButton("Store in Design", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(store)
        cb = QCheckBox("Don't ask again")
        box.setCheckBox(cb)
        box.exec()
        if box.clickedButton() is not store:
            return False
        if cb.isChecked():
            self._prefs["prompt_store_image"] = False
            _prefs_mod.save(self._prefs)
        return True

    def _file_for_unstored(self, ws: "WorkspaceState", idx: int,
                           name: str) -> str | None:
        """The file an image that stops being stored is found by on this
        computer: the one it was added from, or, when the design holds the
        only copy, a copy the maker saves now. None if they decline."""
        from .export import gdraw as _gdraw
        found = image_links.find(ws.scene.face_link(idx))
        if found:
            return found
        cur = ws.scene.face_path(idx)
        cache = os.path.abspath(_gdraw._IMAGE_CACHE_ROOT) + os.sep
        if os.path.isfile(cur) and not os.path.abspath(cur).startswith(cache):
            return cur        # beside the document, from a file before 2.0
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Keep a Copy on This Computer?")
        box.setText(f"{name} is stored only inside this design.")
        box.setInformativeText(
            "To stop storing it, save a copy on this computer: the design finds "
            "it there. Without one, the next save would lose the image.")
        save = box.addButton("Save Copy…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is not save:
            return None
        ext = os.path.splitext(name)[1] or ".png"
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save a Copy of the Image",
            os.path.join(self._dialog_dir("last_image_dir"), name),
            f"Images (*{ext})")
        if not dest:
            return None
        try:
            shutil.copyfile(cur, dest)
        except OSError as e:
            QMessageBox.warning(self, "Copy Not Saved",
                                f"The copy could not be saved: {e}")
            return None
        self._remember_dir(dest, "last_image_dir")
        return dest

    def _place_face(self, ws: "WorkspaceState", fi: FaceImage) -> int | None:
        """Show the photo *fi* names in *ws*, as the record has it (all but
        its calibration and place, which the caller sets once every photo is
        in). Its index, or None when it is not to be had."""
        if not (fi.path and os.path.isabs(fi.path) and os.path.isfile(fi.path)):
            return None
        idx = ws.scene.add_face(fi.path)
        if idx is None:
            return None
        sc = ws.scene
        sc.set_face_opacity(idx, fi.opacity)
        sc.set_face_rotation(idx, fi.rotation)
        sc.set_face_visible(idx, fi.visible)
        sc.set_canvas_locked(idx, fi.locked)
        sc.set_face_stored(idx, fi.stored)
        sc.set_face_link(idx, fi.link_id or image_links.new_id())
        return idx

    def _locate_face(self):
        """Find the selected unshown image on this computer and show it at
        the place and scale the design keeps for it."""
        ws = self._active_ws
        n = ws.scene.face_count()
        row = ws.selected_face_idx
        if not n <= row < n + len(ws.unshown_faces):
            return
        fi = ws.unshown_faces[row - n]
        path, _ = QFileDialog.getOpenFileName(
            self, "Locate Reference Image", self._dialog_dir("last_image_dir"),
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)")
        if not path or self._image_too_large(path):
            return
        self._remember_dir(path, "last_image_dir")
        idx = self._place_face(ws, dataclasses.replace(fi, path=path))
        if idx is None:
            self._status.showMessage(f"Failed to load image: {path}")
            return
        if fi.px_per_mm:
            ws.scene.set_face_calibration(fi.px_per_mm, idx)
        if fi.tx != 0.0 or fi.ty != 0.0:
            ws.scene.get_face_item(idx).setPos(fi.tx, fi.ty)
        image_links.remember(ws.scene.face_link(idx), path)
        ws.unshown_faces.pop(row - n)
        ws.selected_face_idx = idx
        self._refresh_face_list(ws)
        self._sync_empty_hint(ws)
        # A stored image now has other bytes to store, and one without an id
        # has a new one for the file.
        if fi.stored or ws.scene.face_link(idx) != fi.link_id:
            self._mark_dirty()
        self._status.showMessage(f"Found {self._face_name(ws, idx)}: {path}")

    def _remove_face(self):
        ws = self._active_ws
        n = ws.scene.face_count()
        total = n + len(ws.unshown_faces)
        row = ws.selected_face_idx
        if not 0 <= row < total:
            return
        # Asked first: the removal is not on the undo history, and the
        # image's place and calibration went with it.
        name = self._face_name(ws, row)
        r = QMessageBox.question(
            self, "Remove Reference Image",
            f"Remove {name} from the design? Its place and calibration go "
            "with it, and Undo does not bring it back.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes:
            return
        if row < n:
            ws.scene.remove_face(row)
        else:
            ws.unshown_faces.pop(row - n)
        ws.selected_face_idx = min(row, total - 2)
        self._refresh_face_list(ws)
        self._sync_empty_hint()
        self._mark_dirty()

    def _images_in_use(self) -> set[str]:
        """Every image file the open design shows or names, in every tab:
        Clear Image Cache keeps them (Preferences ▸ General)."""
        out = set()
        for ws in self._workspaces:
            out.update(ws.face_image_paths)
            out.update(fi.path for fi in ws.unshown_faces if fi.path)
            out.update(p for p in (ws.fill_image, ws.inlay_fill_image) if p)
        return out

    def _calibration_refusal(self, ws: "WorkspaceState", index: int) -> str | None:
        """Why the photo *index* may not be calibrated now, or None."""
        if not 0 <= index < ws.scene.face_count():
            return None                   # the tool says there is no photo
        name = self._face_name(ws, index)
        if not ws.scene.face_visible(index):
            return (f"{name} is hidden: show it (the eye on the Canvas tab) "
                    "to calibrate it.")
        if ws.scene.face_is_locked(index):
            return (f"{name} is locked: unlock it (the padlock on the Canvas "
                    "tab) to calibrate it.")
        return None

    def _on_face_opacity_changed(self, v: int):
        idx = self._shown_face()
        if idx >= 0:
            self.scene.set_face_opacity(idx, v / 100)
            self._mark_dirty()

    def _on_face_rotation_changed(self, v: float):
        idx = self._shown_face()
        if idx >= 0:
            self.scene.set_face_rotation(idx, v)
            self._mark_dirty()

    # ------------------------------------------------------------------
    # New / Open / Save (SVG as native format)
    # ------------------------------------------------------------------

    def _settle_before_replacing_document(self):
        """Before New or Open swaps the document: end any tool mid-operation
        (a half-drawn Line carried its nodes into the next document, and the
        next click continued it) and flush the panel into the active
        workspace as a tab switch does — the restore that follows otherwise
        reverted the edits made since the last switch, some fields and not
        others."""
        self._act_select.setChecked(True)
        self._set_tool_select()
        self._save_ws_sidebar_state(self._active_ws)
        # The next document is first seen from its default faces, and each
        # tab fitted to it on first sight: the inactive tabs kept the previous
        # document's zoom and pan, a temple at 2632 % on the old hinge.
        for ws in self._workspaces:
            ws.obverse = False
            ws.view.set_obverse(False)
            ws.fitted = False
        self._act_obverse.blockSignals(True)
        self._act_obverse.setChecked(False)
        self._act_obverse.blockSignals(False)

    def _guide_defaults(self, ws: "WorkspaceState") -> tuple:
        """``(stock_w, stock_h, pad_w, pad_h)`` a workspace starts at: the
        front's from Preferences, the temples' blank from its own preference,
        the component tab's fixed 10 × 20 mm, as __init__ sets them."""
        p = self._prefs
        if ws.workspace_type in ("temple_r", "temple_l"):
            stock = (p["temple_stock_width_mm"], p["temple_stock_height_mm"])
        elif ws.workspace_type == "component":
            stock = (10.0, 20.0)
        else:
            stock = (p["stock_width_mm"], p["stock_height_mm"])
        return (*stock, p["pad_width_mm"], p["pad_height_mm"])

    def _reset_measure_guides(self, ws: "WorkspaceState"):
        """The construction guide's crest and arms and the free boxing box as
        a new design starts them: they were the previous design's."""
        ws.crest_height, ws.arm_spread, ws.arm_drop = 0.0, 4.0, 0.0
        ws.boxing_a = self._prefs["boxing_a_mm"]
        ws.boxing_b = self._prefs["boxing_b_mm"]
        ws.boxing_dbl = self._prefs["boxing_dbl_mm"]
        ws.const_guides.set_crest_height(ws.crest_height)
        ws.const_guides.set_spread(ws.arm_spread)
        ws.const_guides.set_pivot_y(ws.arm_drop)
        if not ws.boxing_snapped:
            ws.boxing_guide.set_a(ws.boxing_a)
            ws.boxing_guide.set_b(ws.boxing_b)
            ws.boxing_guide.set_dbl(ws.boxing_dbl)

    def _set_guide_sizes(self, ws: "WorkspaceState", stock=None, pad=None):
        """Size the workspace's stock and pad guides, each a (width, height)
        or None to leave it."""
        if stock is not None:
            ws.stock_w, ws.stock_h = stock
            ws.stock_guide.set_width(ws.stock_w)
            ws.stock_guide.set_height(ws.stock_h)
        if pad is not None:
            ws.pad_w, ws.pad_h = pad
            ws.pad_guide.set_width(ws.pad_w)
            ws.pad_guide.set_height(ws.pad_h)

    def _set_ghost(self, ws: "WorkspaceState", on: bool):
        """The workspace's Ghost, on its scene, snap and boxing guide; the
        toolbar follows when the sidebar is restored."""
        ws.mirror_enabled = on
        if ws.scene.mirror:
            ws.scene.mirror.set_enabled(on)
        ws.scene.set_mirror_display(on)
        ws.snap.set_mirror(0.0, on, horizontal=(ws.workspace_type
                                                in ("temple_r", "temple_l")))
        ws.boxing_guide.set_mirror(on)

    def _reset_workspace(self, ws: "WorkspaceState"):
        """Empty *ws* as File > New leaves it: no geometry, history, photos or
        fills, and the Ghost and the guide sizes as Preferences start them.
        The Ghost and the guides used to come from the previous design."""
        ws.clear_document()
        ws.bookmarks.clear()
        ws.scene.clear_faces()
        ws.unshown_faces = []
        ws.selected_face_idx = -1
        # (snap/lock/bevel/forming/calibration state: reset by clear_document)
        self._set_ghost(ws, self._prefs["mirror_on_startup"])
        sw, sh, pw, ph = self._guide_defaults(ws)
        self._set_guide_sizes(ws, (sw, sh), (pw, ph))
        self._reset_measure_guides(ws)
        ws.fill_visible = False          # fill resets with the document
        ws.fill_color   = "#2a6099"
        ws.fill_opacity = 0.50
        ws.fill_style   = "color"
        ws.fill_image   = ""
        ws.scene.set_fill_color(QColor(ws.fill_color))
        ws.scene.set_fill_opacity(ws.fill_opacity)
        ws.scene.clear_fill_image()
        ws.scene.set_fill_visible(False)
        ws.inlay_fill_visible = False
        ws.inlay_fill_color   = self._default_inlay_fill_color()
        ws.inlay_fill_opacity = self._default_inlay_fill_opacity()
        ws.inlay_fill_style   = "color"
        ws.inlay_fill_image   = ""
        ws.inlay_fill_tumble  = False
        ws.scene.set_inlay_fill_color(QColor(ws.inlay_fill_color))
        ws.scene.set_inlay_fill_opacity(ws.inlay_fill_opacity)
        ws.scene.clear_inlay_fill_image()
        ws.scene.set_inlay_fill_tumble(False)
        ws.scene.set_inlay_fill_visible(False)
        ws.lens_fill_visible = False
        ws.lens_fill_top     = DEFAULT_LENS_FILL_TOP
        ws.lens_fill_bottom  = DEFAULT_LENS_FILL_BOTTOM
        ws.lens_fill_linked  = False
        ws.lens_fill_opacity = self._default_lens_fill_opacity()
        ws.lens_fill_intensity = self._default_lens_fill_intensity()
        ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
        ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
        ws.scene.set_lens_fill_visible(False)

    def _new(self):
        if not self._confirm_discard("starting a new design"):
            return
        self._settle_before_replacing_document()
        for ws in self._workspaces:
            self._reset_workspace(ws)
        # A new design starts on its front, wherever the last one was left.
        self._loading = True
        try:
            self._ws_tab_widget.setCurrentIndex(0)
        finally:
            self._loading = False
        self._restore_ws_sidebar_state(self._active_ws)
        self._refresh_timeline_list()
        self._update_undo_actions()
        self._current_path = None
        self._remember_disk_state(None)
        self._clear_autosave()
        self._clear_dirty()
        self._update_info_label()      # the layer shown was the old document's
        self._status.showMessage("New document")

    def _open(self):
        if not self._confirm_discard("opening another file"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GuildDraw File", self._dialog_dir(),
            "GuildDraw Files (*.gdraw *.svg);;GuildDraw Project (*.gdraw);;SVG Files (*.svg)"
        )
        if path:
            self._remember_dir(path)
        if not path:
            return
        self._open_path(path)

    # What a dropped file does, by suffix (B29: a drop did nothing, where
    # GuildModel opens what is dropped on it).
    _DROP_IMAGES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

    @staticmethod
    def _dropped_path(mime) -> str | None:
        """The first local file in a drag that GuildDraw takes, or None."""
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p) and p.lower().endswith(
                    (".gdraw", ".svg", ".dxf", ".oma", ".dcs",
                     *MainWindow._DROP_IMAGES)):
                return p
        return None

    def dragEnterEvent(self, event):
        if self._dropped_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._dropped_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        path = self._dropped_path(event.mimeData())
        if path is None:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        # After the drop returns: a modal (the unsaved prompt) inside a drop
        # handler holds the dragging program.
        QTimer.singleShot(0, self, lambda: self._open_dropped(path))

    def _open_dropped(self, path: str):
        """Open a design, import a drawing or a trace, or add a photo."""
        low = path.lower()
        if low.endswith(".gdraw") or (low.endswith(".svg") and _is_guilddraw_svg(path)):
            if self._confirm_discard("opening another file"):
                self._remember_dir(path)
                self._open_path(path)
        elif low.endswith(".svg"):
            self._import_svg(path)
        elif low.endswith(".dxf"):
            self._import_dxf(path)
        elif low.endswith((".oma", ".dcs")):
            self._import_oma(path)
        elif low.endswith(self._DROP_IMAGES):
            self._remember_dir(path, "last_image_dir")
            self._add_face(path)

    def _open_path(self, path: str):
        """Dispatch an open by extension. Caller handles the discard prompt."""
        if path.lower().endswith(".gdraw"):
            self._open_gdraw(path)
        else:
            self._open_svg(path)

    def _open_svg(self, path: str):
        """Load a single .svg into the active (Front) workspace."""
        try:
            from .export.svg import (load_svg, resolve_face_images,
                                     resolve_fill_image)
            data = load_svg(path)
            resolve_face_images(data.get("face_images", []), path)
            resolve_fill_image(data.get("fill"), path)
            resolve_fill_image(data.get("inlay_fill"), path)
        except Exception as e:
            QMessageBox.critical(self, "Could Not Open the File",
                                 _open_error_text(path, e))
            return
        self._settle_before_replacing_document()
        # A plain .svg is a single-workspace document: the temples and component
        # start empty, or the previous project's would ride along into the
        # next save.
        for ws in self._workspaces[1:]:
            self._reset_workspace(ws)
        try:
            self._load_ws_data(self._workspaces[0], data)
            # Switch to Front tab
            self._loading = True
            try:
                self._ws_tab_widget.setCurrentIndex(0)
            finally:
                self._loading = False
            # Pull the loaded state into the sidebar. The tab change above does
            # this via _on_workspace_changed — but only when the index actually
            # moves, so opening a file while already on Front left the widgets
            # (fill tick, tint colors, guide sizes) showing the previous document.
            self._restore_ws_sidebar_state(self._active_ws)
            self.view.fit_view(self._fit_rect(self._active_ws))
            self._active_ws.fitted = True
        except Exception as e:
            self._abandon_failed_open(path, e)
            return
        left_out = data.get("left_out") or []
        if left_out:
            self._warn_partial_open(path, [], left_out)
            self._current_path = None     # Save asks for a new name (above)
            self._dirty = True
            self._update_title()
            self._status.showMessage(f"Opened with errors: {os.path.basename(path)}")
            return
        self._current_path = path
        self._remember_disk_state(path)
        self._clear_dirty()
        self._clear_autosave()      # the recovery slot held the previous document
        self._add_recent(path)
        bm = self._workspaces[0].bookmarks
        self._status.showMessage(
            f"Opened: {os.path.basename(path)}"
            + (f"  ·  {len(bm)} bookmark(s)" if bm else "")
        )

    def _open_gdraw(self, path: str, remember: bool = True,
                    quiet: bool = False) -> str | None:
        """Load a .gdraw ZIP into all four workspaces.

        Returns "ok", "errors" (some tabs loaded empty; the path was NOT
        kept, so Save asks for a new name) or None (nothing was loaded).
        ``quiet`` reports those two without a dialog — for a batch run in a
        window nobody is watching (export/batch_catalog.py)."""
        try:
            from .export.gdraw import load_gdraw
            all_data = load_gdraw(path)
        except Exception as e:
            if not quiet:
                QMessageBox.critical(self, "Could Not Open the File",
                                     _open_error_text(path, e))
            return None
        self._settle_before_replacing_document()
        tab_names = ["front", "temple_r", "temple_l", "component"]
        try:
            for ws, tab in zip(self._workspaces, tab_names, strict=True):
                self._load_ws_data(ws, all_data[tab])
            # Switch to the active tab stored in the file. Inside the try, as
            # the filling is: a failure here (a calibration that made the zoom
            # NaN) left the previous design's path over this one's content.
            active = all_data.get("active_tab", "front")
            target_idx = tab_names.index(active) if active in tab_names else 0
            self._loading = True
            try:
                self._ws_tab_widget.setCurrentIndex(target_idx)
            finally:
                self._loading = False
            # See _open_svg: a no-op tab change fires no restore of its own.
            self._restore_ws_sidebar_state(self._active_ws)
            self.view.fit_view(self._fit_rect(self._active_ws))
            self._active_ws.fitted = True
        except Exception as e:
            self._abandon_failed_open(path, e, quiet=quiet)
            return None

        errors = all_data.get("errors") or []
        left_out = all_data.get("left_out") or []
        if errors or left_out:
            # A corrupt tab loaded empty, or parts of one were left out: do NOT
            # keep the path — Save would overwrite the original file with less
            # than it holds. Force Save As and flag the document as unsaved.
            if not quiet:
                self._warn_partial_open(path, errors, left_out)
            self._current_path = None
            self._remember_disk_state(None)
            self._dirty = True
            self._update_title()
            self._status.showMessage(
                f"Opened with errors: {os.path.basename(path)}")
            return "errors"

        self._current_path = path
        self._remember_disk_state(path)
        self._clear_dirty()
        if remember:
            self._add_recent(path)
            self._clear_autosave()  # the recovery slot held the previous document
        self._status.showMessage(f"Opened: {os.path.basename(path)}"
                                 + self._unshown_note() + self._stand_in_note(),
                                 15000)
        return "ok"

    def _stand_in_note(self) -> str:
        """'  (Arial shows as Liberation Sans here …)' for the engraving fonts
        this computer does not have, or ''."""
        from .textpath import font_stand_in
        seen = {}
        for ws in self._workspaces:
            for t in ws.doc_texts:
                shown = font_stand_in(t.family)
                if shown:
                    seen[t.family] = shown
        if not seen:
            return ""
        said = "; ".join(f"{f} shows as {s}" for f, s in seen.items())
        return (f"  ({said}: not installed here. GuildModel engraves with the "
                "fonts its own computer has.)")

    def _unshown_note(self) -> str:
        """'  (2 reference images could not be shown …)', or '' — the photos
        an open left out of view (WorkspaceState.unshown_faces)."""
        unshown = [fi for ws in self._workspaces for fi in ws.unshown_faces]
        away = sum(1 for fi in unshown if not fi.stored)
        bad = len(unshown) - away
        said = []
        if away:
            said.append(f"{away} reference image{'s' if away != 1 else ''} not "
                        "on this computer: Locate… on the Canvas tab finds "
                        f"{'them' if away != 1 else 'it'}")
        if bad:
            said.append(f"{bad} reference image{'s' if bad != 1 else ''} could "
                        "not be shown: too large, damaged or not found. "
                        f"{'It stays' if bad == 1 else 'They stay'} in the file")
        return f"  ({'; '.join(said)}.)" if said else ""

    def _warn_partial_open(self, path: str, errors: list, left_out: list):
        """Say what of *path* could not be read: whole tabs (*errors*,
        "tab: reason") and single parts left out of a tab (*left_out*,
        "tab: 2 curves (…)"; a plain .svg's carry no tab)."""
        def tab_and_text(entry: str):
            tab, sep, rest = entry.partition(": ")
            if sep and tab in _TAB_TITLES:
                return _TAB_TITLES[tab], rest
            return "", entry
        name = os.path.basename(path)
        parts = []
        if errors:
            broken = [tab_and_text(e) for e in errors]
            parts.append(f"{_and_list(t for t, _r in broken)} could not be read "
                         f"in {name} and opened empty.")
        if left_out:
            parts.append(f"Some parts of {name} could not be read and were left "
                         "out (one may come from a later GuildDraw):\n"
                         + "\n".join(f"• {t + ': ' if t else ''}{w}"
                                     for t, w in map(tab_and_text, left_out)))
        parts.append("The rest of the design opened as saved. The file itself "
                     "is untouched: saving asks for a new name, so the original "
                     "stays as it is.")
        if errors:
            parts.append("Technical detail:\n" + "\n".join(
                f"• {t}: {r}" for t, r in map(tab_and_text, errors)))
        QMessageBox.warning(
            self, "Some Tabs Could Not Be Read" if errors and not left_out
            else "Some of the Design Could Not Be Read", "\n\n".join(parts))

    def _abandon_failed_open(self, path: str, exc: Exception,
                             quiet: bool = False):
        """A file read but failed while filling the workspaces: leave an empty,
        unsaved document with no path, never the mixture. The front held the
        new file's curves and a temple the old one's, with the old path kept
        and the document clean, so Ctrl+S wrote the mixture over the previous
        file and the next save rotated its .bak away (the 2.0 bug hunt)."""
        for ws in self._workspaces:
            self._reset_workspace(ws)
        self._restore_ws_sidebar_state(self._active_ws)
        self._refresh_timeline_list()
        self._update_undo_actions()
        self._current_path = None       # Save asks for a name
        self._remember_disk_state(None)
        self._clear_dirty()             # nothing is left to lose
        self._status.showMessage(f"Open failed: {os.path.basename(path)}")
        if not quiet:
            QMessageBox.critical(
                self, "Could Not Open the File",
                _open_error_text(path, exc) + "\n\nNothing from it was kept, "
                "and the previous design is closed; its file is untouched.")

    def _load_ws_data(self, ws: "WorkspaceState", data: dict):
        """Populate a WorkspaceState from a load_svg result dict.  Clears first."""
        ws.clear_document()

        # Apply layer visibility/locks BEFORE adding curves so each new item
        # picks up its layer state on creation.
        for lname, flags in (data.get("layers") or {}).items():
            try:
                layer = Layer(lname)
            except ValueError:
                continue   # unknown layer name from a future version
            ws.scene.set_layer_visible(layer, flags.get("visible", True))
            ws.scene.set_layer_locked(layer, flags.get("locked", False))

        # Mirror ghost state is saved per workspace — restore it (before the
        # curves are added, so ghosts aren't built and immediately removed).
        mir = data.get("mirror")
        if mir is not None:
            ws.mirror_enabled = bool(getattr(mir, "enabled", True))
            horizontal = ws.workspace_type in ("temple_r", "temple_l")
            if ws.scene.mirror:
                ws.scene.mirror.set_enabled(ws.mirror_enabled)
            ws.scene.set_mirror_display(ws.mirror_enabled)
            ws.snap.set_mirror(0.0, ws.mirror_enabled, horizontal=horizontal)
            ws.boxing_guide.set_mirror(ws.mirror_enabled)
            if ws is self._active_ws:
                self._act_mirror.blockSignals(True)
                self._act_mirror.setChecked(ws.mirror_enabled)
                self._act_mirror.blockSignals(False)

        for curve in data.get("curves", []):
            ws.add_curve(curve)

        frm = data.get("forming", FormingMetadata())
        ws.bridge_angle  = frm.bridge_angle_deg
        ws.apical_radius = frm.apical_radius_mm

        bevel = data.get("bevel")
        if bevel is not None:
            ws.bevel_preset = bevel.preset
            ws.bevel_depth  = bevel.depth_mm
            ws.boxing_guide.set_bevel_depth(ws.bevel_depth)

        ws.scene.clear_faces()
        ws.unshown_faces = []
        ws.selected_face_idx = -1
        face_images_data = data.get("face_images", [])
        placed = []                 # (scene index, record) of the photos loaded
        for fi in face_images_data:
            if not fi.stored:
                # Found by its id on this computer, never by a path in the file.
                fi = dataclasses.replace(fi, path=image_links.find(fi.link_id) or "")
            idx = self._place_face(ws, fi)
            if idx is not None:
                placed.append((idx, fi))
            elif fi.path or fi.link_id:
                ws.unshown_faces.append(fi)

        cal = data.get("calibration", Calibration())
        if cal.is_set:
            ws.image_px_per_mm = cal.px_per_mm
            ws.scene.set_face_calibration(cal.px_per_mm)   # every photo, as before 2.0
        for idx, fi in placed:                             # then each its own
            if fi.px_per_mm:
                ws.scene.set_face_calibration(fi.px_per_mm, idx)
        if ws is self._active_ws:
            self._show_calibration(ws)

        # By the index each photo got: a photo that exists but fails to decode
        # gets none, and counting files moved every later photo to the
        # position of the one before it.
        for idx, fi in placed:
            if fi.tx != 0.0 or fi.ty != 0.0:
                item = ws.scene.get_face_item(idx)
                if item is not None:
                    item.setPos(fi.tx, fi.ty)

        for dim in data.get("dims", []):
            ws.add_dim(dim)

        for tobj in data.get("texts", []):
            ws.add_text(tobj)

        ws.bookmarks = list(data.get("bookmarks", []))

        # Guide sizes (2.0). Absent in older files, which take the sizes
        # Preferences start a workspace at: they used to keep the previous
        # document's, which the next save wrote into the file, and GuildModel
        # seeds a new project's blank from them. Out-of-range values are held
        # to the sidebar's.
        guides = data.get("guides")
        guides = guides if isinstance(guides, dict) else {}
        sw, sh, pw, ph = self._guide_defaults(ws)
        stock = guides.get("stock")
        if isinstance(stock, dict):
            sw = _num_or(stock.get("width_mm"), sw, 5.0, 400.0)
            sh = _num_or(stock.get("height_mm"), sh, 5.0, 200.0)
        pad = guides.get("pad")
        if isinstance(pad, dict):
            pw = _num_or(pad.get("width_mm"), pw, 10.0, 200.0)
            ph = _num_or(pad.get("height_mm"), ph, 10.0, 200.0)
        self._set_guide_sizes(ws, (sw, sh), (pw, ph))
        self._reset_measure_guides(ws)        # what an older file did not save
        cons = guides.get("construction")
        if isinstance(cons, dict):
            ws.crest_height = _num_or(cons.get("crest_height_mm"), ws.crest_height,
                                      -50.0, 50.0)
            ws.arm_spread = _num_or(cons.get("crest_width_mm"), ws.arm_spread, 0.0, 100.0)
            ws.arm_drop = _num_or(cons.get("angle_height_mm"), ws.arm_drop, -50.0, 100.0)
        box = guides.get("boxing")
        if isinstance(box, dict):
            ws.boxing_a = _num_or(box.get("a_mm"), ws.boxing_a, 0.0, 120.0)
            ws.boxing_b = _num_or(box.get("b_mm"), ws.boxing_b, 0.0, 100.0)
            ws.boxing_dbl = _num_or(box.get("dbl_mm"), ws.boxing_dbl, 0.0, 60.0)

        fill = data.get("fill") or {}
        ws.fill_visible = bool(fill.get("visible", False))
        ws.fill_color   = _hex_or(fill.get("color"), "#2a6099")
        ws.fill_opacity = _num_or(fill.get("opacity"), 0.50, 0.0, 1.0)
        # Absent in pre-1.2 files, and any unknown style from a future version
        # degrades to the color rather than blanking the fill.
        img = fill.get("image")
        ws.fill_image = img if isinstance(img, str) else ""
        ws.fill_style = "image" if fill.get("style") == "image" else "color"
        ws.scene.set_fill_color(QColor(ws.fill_color))
        ws.scene.set_fill_opacity(ws.fill_opacity)
        if not self._apply_fill_material(ws):
            self._fill_image_missing(ws)
        if ws.scene.set_fill_visible(ws.fill_visible) != "ok":
            ws.fill_visible = False   # a saved fill-on that no longer encloses

        # Inlay fill (2.0). Absent in older files: off, at the color and
        # opacity the maker prefers for a fresh fill.
        inlay_fill = data.get("inlay_fill") or {}
        ws.inlay_fill_visible = bool(inlay_fill.get("visible", False))
        ws.inlay_fill_color   = _hex_or(inlay_fill.get("color"),
                                        self._default_inlay_fill_color())
        ws.inlay_fill_opacity = _num_or(inlay_fill.get("opacity"),
                                        self._default_inlay_fill_opacity(),
                                        0.0, 1.0)
        img = inlay_fill.get("image")
        ws.inlay_fill_image  = img if isinstance(img, str) else ""
        ws.inlay_fill_style  = ("image" if inlay_fill.get("style") == "image"
                                else "color")
        ws.inlay_fill_tumble = bool(inlay_fill.get("tumble", False))
        ws.scene.set_inlay_fill_color(QColor(ws.inlay_fill_color))
        ws.scene.set_inlay_fill_opacity(ws.inlay_fill_opacity)
        if not self._apply_inlay_fill_material(ws):
            self._inlay_fill_image_missing(ws)
        if ws.scene.set_inlay_fill_visible(ws.inlay_fill_visible) != "ok":
            ws.inlay_fill_visible = False

        # Lens fill. Absent in pre-1.2 files: the tint stays off at the shipped
        # colors, with the opacity the maker prefers for a fresh tint.
        lens_fill = data.get("lens_fill") or {}
        ws.lens_fill_visible = bool(lens_fill.get("visible", False))
        ws.lens_fill_top     = _hex_or(lens_fill.get("top"),
                                       DEFAULT_LENS_FILL_TOP)
        ws.lens_fill_bottom  = _hex_or(lens_fill.get("bottom"),
                                       DEFAULT_LENS_FILL_BOTTOM)
        ws.lens_fill_linked  = bool(lens_fill.get("linked", False))
        ws.lens_fill_opacity = _num_or(
            lens_fill.get("opacity"), self._default_lens_fill_opacity(), 0.0, 1.0)
        ws.lens_fill_intensity = _num_or(
            lens_fill.get("intensity"), self._default_lens_fill_intensity(),
            LENS_FILL_INTENSITY_MIN, LENS_FILL_INTENSITY_MAX)
        ws.scene.set_lens_fill_colors(ws.lens_fill_top, ws.lens_fill_bottom)
        ws.scene.set_lens_fill_intensity(ws.lens_fill_intensity)
        ws.scene.set_lens_fill_opacity(ws.lens_fill_opacity)
        if ws.scene.set_lens_fill_visible(ws.lens_fill_visible) != "ok":
            ws.lens_fill_visible = False

        # If this is the active workspace, sync sidebar widgets
        if ws is self._active_ws:
            self._bridge_angle_spin.blockSignals(True)
            self._bridge_angle_spin.setValue(ws.bridge_angle)
            self._bridge_angle_spin.blockSignals(False)
            self._apical_spin.blockSignals(True)
            self._apical_spin.setValue(ws.apical_radius)
            self._apical_spin.blockSignals(False)
            # The first row, shown or not: one not on this computer is where
            # Locate… starts.
            ws.selected_face_idx = 0
            self._refresh_face_list(ws)
            self._refresh_timeline_list()
            self._update_undo_actions()

    def _save(self) -> bool:
        """Save to the document's path, or ask for one. True when a file was
        written."""
        if not getattr(self, "_current_path", None):
            return self._save_as()
        return self._do_save(self._current_path)

    def _save_as(self, start: str | None = None) -> bool:
        # Untitled project: suggest the frame-size notation (49□27.gdraw) so
        # the □ is in the filename without typing it — the native Windows
        # dialog can't receive the insert-□ application shortcut.
        start = start or getattr(self, "_current_path", "") or ""
        if not start:
            size = self._size_string()
            start = os.path.join(self._dialog_dir(), f"{size or 'design'}.gdraw")
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save GuildDraw File", start,
            "GuildDraw Project (*.gdraw);;SVG Files (*.svg)"
        )
        if not path:
            return False
        if not path.lower().endswith((".gdraw", ".svg")):
            # Non-native dialogs hand back exactly what was typed; a bare
            # name used to fall through to the single-workspace SVG writer.
            path = self._final_path(path, ".svg" if "svg" in chosen.lower()
                                    else ".gdraw")
            if path is None:
                return False
        self._remember_dir(path)
        # _do_save takes the path on success only: set before it, a failed
        # Save As left every later Ctrl+S aimed at the file that failed.
        return self._do_save(path)

    def _size_string(self) -> str | None:
        """Frame-size notation ``A□DBL`` from the front workspace's finished
        boxing dims, e.g. ``"49□27"``; None when no lens is drawn.

        Same measurement basis as _refresh_measurements (sampled union_bbox,
        finished A/DBL grown/narrowed by the bevel) — keep them in step."""
        front = next((w for w in self._workspaces
                      if w.workspace_type == "front"), None)
        if front is None:
            return None
        from .boxing import finished_ab, finished_dbl, union_bbox
        mirror_x = getattr(front.scene.mirror, "_x", 0.0) \
            if front.scene.mirror else 0.0
        os_c, od_c = [], []
        for c in front.doc_curves:
            if c.layer != Layer.LENS or not c.nodes:
                continue
            cx = sum(n.x for n in c.nodes) / len(c.nodes)
            if cx > mirror_x:
                os_c.append(c)
            elif cx < mirror_x:
                od_c.append(c)
        os_lb = union_bbox(os_c) if os_c else None
        od_lb = union_bbox(od_c) if od_c else None
        lb = od_lb or os_lb
        if lb is None:
            return None
        a = lb[2] - lb[0]
        b = lb[3] - lb[1]
        if os_lb and od_lb:
            dbl = os_lb[0] - od_lb[2]
        elif os_lb:
            dbl = 2.0 * (os_lb[0] - mirror_x)
        else:
            dbl = 2.0 * (mirror_x - od_lb[2])
        bevel_d = max(0.0, front.bevel_depth)
        if bevel_d > 0:
            a, _b = finished_ab(a, b, bevel_d)
            dbl   = finished_dbl(dbl, bevel_d)
        if dbl <= 0:
            return None
        return f"{a:.0f}□{dbl:.0f}"

    def _other_workspaces_in_use(self) -> list[str]:
        """Tab names of the non-front workspaces holding anything a .svg
        cannot carry (it is the Frame Front alone)."""
        return [self._ws_tab_widget.tabText(i)
                for i, ws in enumerate(self._workspaces)
                if ws.workspace_type != "front"
                and (ws.doc_curves or ws.doc_dims or ws.doc_texts
                     or ws.face_image_paths or ws.bookmarks)]

    def _ask_svg_scope(self, path: str, others: list[str]) -> str:
        """A .svg holds the Frame Front alone: "gdraw" (Save As a project),
        "front" (write the front anyway) or "cancel"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Save as .svg?")
        box.setText(f"{os.path.basename(path)} can hold only the Frame Front. "
                    f"{_and_list(others)} would not be saved.")
        box.setInformativeText("Save the whole design as a .gdraw project instead?")
        as_gdraw = box.addButton("Save as .gdraw…", QMessageBox.ButtonRole.AcceptRole)
        front = box.addButton("Save Front Only", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(as_gdraw)
        _run_modal(box)
        clicked = box.clickedButton()
        return ("gdraw" if clicked is as_gdraw
                else "front" if clicked is front else "cancel")

    def _remember_disk_state(self, path: str | None) -> None:
        """What the design's file looked like when this window last read or
        wrote it, for _ok_to_overwrite."""
        try:
            st = os.stat(path) if path else None
        except OSError:
            st = None
        self._disk_state = ((os.path.realpath(path), st.st_mtime_ns, st.st_size)
                            if st else None)

    def _ok_to_overwrite(self, target: str) -> bool:
        """Before a save over *target*: if another window or program changed
        it since this window read or wrote it, ask. The second window's save
        replaced the first's unasked, and one more took it off the disk."""
        known = getattr(self, "_disk_state", None)
        if known is None or known[0] != target:
            return True
        try:
            st = os.stat(target)
        except OSError:
            return True                       # gone: nothing to overwrite
        if (st.st_mtime_ns, st.st_size) == known[1:]:
            return True
        answer = self._ask_changed_on_disk(os.path.basename(target))
        if answer == "save_as":
            QTimer.singleShot(0, self, self._save_as)
        return answer == "overwrite"

    def _ask_changed_on_disk(self, name: str) -> str | None:
        """'overwrite', 'save_as' or None (Cancel) for a file changed on disk."""
        box = QMessageBox(
            QMessageBox.Icon.Warning, "File Changed on Disk",
            f"{name} was changed on disk since this window opened or saved it, "
            "by another window or program. Overwrite it with this design, or "
            "save this design under another name?",
            QMessageBox.StandardButton.Cancel, self)
        over = box.addButton("Overwrite", QMessageBox.ButtonRole.DestructiveRole)
        other = box.addButton("Save As…", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(other)
        box.exec()
        return {over: "overwrite", other: "save_as"}.get(box.clickedButton())

    def _do_save(self, path: str) -> bool:
        """Atomic save: write a temp file, keep the previous version as .bak,
        then replace. A failure mid-write can never destroy the existing file.
        Returns True when the file was written; on success `path` becomes the
        document's path."""
        front_only = False
        if not path.lower().endswith(".gdraw"):
            others = self._other_workspaces_in_use()
            if others:
                # Ctrl+S on a legacy .svg used to write the front, clear the
                # star and drop the temple and component work without a word.
                choice = self._ask_svg_scope(path, others)
                if choice == "gdraw":
                    return bool(self._save_as(
                        start=os.path.splitext(path)[0] + ".gdraw"))
                if choice != "front":
                    return False
                front_only = True
        # Through a link to the file it names (a design kept in a synced
        # folder): the link was replaced by a regular file, and the real one
        # never got the save.
        target = os.path.realpath(path)
        if os.path.exists(target) and not os.access(target, os.W_OK):
            QMessageBox.warning(
                self, "File Is Read-Only",
                f"{os.path.basename(path)} is read-only, so GuildDraw left it as "
                "it is. Save the design under another name with File ▸ Save "
                "As…, or make the file writable first.")
            return False
        if not self._ok_to_overwrite(target):
            return False
        notes: list = []
        tmp = None
        try:
            tmp = _sibling_tmp(target)
            if path.lower().endswith(".gdraw"):
                notes = self._do_save_gdraw(tmp, carry_from=target) or []
            else:
                self._do_save_svg(tmp)
            # On disk before it replaces anything: a crash or a power cut
            # after the swap could otherwise leave an empty file at the path.
            with open(tmp, "r+b") as f:
                os.fsync(f.fileno())
            if os.path.exists(target):
                # A copy, not a rename: the previous version stays at the path
                # until the one atomic replace below (the rename left no file
                # there between the two steps). The copy goes through a
                # temporary file too: one that failed half-way had already cut
                # the good .bak short.
                try:
                    _atomic_copy(target, target + ".bak")
                except OSError:
                    pass   # backup is best-effort; the save still proceeds
                try:
                    shutil.copymode(target, tmp)   # a shared file stays shared
                except OSError:
                    pass
            else:
                _give_default_mode(tmp)
            os.replace(tmp, target)
            _fsync_folder(target)
        except Exception as e:
            try:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
            QMessageBox.critical(self, "Could Not Save",
                                 _write_error_text("save the design", path, e))
            return False
        self._remember_disk_state(target)
        if notes:
            QMessageBox.warning(
                self, "Some Images Were Not Carried",
                f"{os.path.basename(path)} was saved, without these images:\n"
                + "\n".join(f"• {_TAB_TITLES.get(t, t)}: {w}"
                            for t, _sep, w in (n.partition(": ") for n in notes))
                + "\n\nAdd them again with Add Image… (Canvas tab) or the "
                "fill's Choose…, then save.")
        self._current_path = path
        self._add_recent(path)
        if front_only:
            # The temples and component are still unsaved: keep the star, the
            # close prompt and the recovery slot.
            self._update_title()
            self._status.showMessage(
                f"Saved the Frame Front to {os.path.basename(path)}; the other "
                "workspaces are not saved. Use Save As .gdraw to keep them.", 10000)
            return True
        self._clear_dirty()
        self._clear_autosave()
        self._status.showMessage(f"Saved: {os.path.basename(path)}"
                                 + self._svg_images_note(path), 12000)
        return True

    def _svg_images_note(self, path: str) -> str:
        """For a .svg save: the reference images and swatches it names but
        does not hold, which a .gdraw keeps inside it. Saved as .svg from a
        .gdraw, they lived in the image cache, and reopened as nothing."""
        if not path.lower().endswith(".svg"):
            return ""
        ws = self._workspaces[0]
        folder = os.path.dirname(os.path.abspath(path)) + os.sep
        # The stored photos only: one not stored is never named by a file.
        stored = [ws.scene.face_path(i) for i in range(ws.scene.face_count())
                  if ws.scene.face_stored(i)]
        named = [p for p in [*stored, ws.fill_image, ws.inlay_fill_image]
                 if p and not os.path.abspath(p).startswith(folder)]
        if not named:
            return ""
        return (f"  ·  {len(named)} image{'s' if len(named) != 1 else ''} it "
                f"names {'are' if len(named) != 1 else 'is'} not beside it: "
                "a .svg names its images and does not hold them; save as "
                ".gdraw to keep them with the design")

    def _ws_to_data_dict(self, ws: "WorkspaceState") -> dict:
        """Build the data dict for save_svg from a WorkspaceState."""
        from .document import WORKSPACE_LAYERS
        return {
            "layers": {
                layer.value: {
                    "visible": ws.scene.is_layer_visible(layer),
                    "locked":  ws.scene.is_layer_locked(layer),
                }
                for layer in WORKSPACE_LAYERS[ws.workspace_type]
            },
            "curves":      ws.doc_curves,
            "dims":        ws.doc_dims,
            "calibration": Calibration(px_per_mm=ws.image_px_per_mm),
            "mirror":      ws.scene.mirror or MirrorAxis(),
            "forming":     FormingMetadata(
                               bridge_angle_deg=ws.bridge_angle,
                               apical_radius_mm=ws.apical_radius,
                           ),
            "machined_bridge": MachinedBridge(),
            "bevel": BevelSpec(preset=ws.bevel_preset, depth_mm=ws.bevel_depth),
            "face_images": [
                FaceImage(
                    path     = ws.scene.face_path(i),
                    tx       = ws.scene.face_scene_pos(i)[0],
                    ty       = ws.scene.face_scene_pos(i)[1],
                    rotation = ws.scene.face_rotation(i),
                    opacity  = ws.scene.face_opacity(i),
                    px_per_mm = ws.scene.face_calibration(i),
                    visible  = ws.scene.face_visible(i),
                    locked   = ws.scene.face_is_locked(i),
                    stored   = ws.scene.face_stored(i),
                    link_id  = ws.scene.face_link(i),
                )
                for i in range(ws.scene.face_count())
            ] + [
                # Carried as they came (see WorkspaceState.unshown_faces).
                fi for fi in getattr(ws, "unshown_faces", [])
            ],
            "bookmarks": ws.bookmarks,
            # The blank and the pad block the design is drawn against (2.0):
            # read back on open, and the seed GuildModel takes for a new
            # project's stock once its reader knows the key.
            "guides": {
                "stock": {"width_mm": ws.stock_w, "height_mm": ws.stock_h},
                **({"pad": {"width_mm": ws.pad_w, "height_mm": ws.pad_h},
                    # The customer's measurements the design is drawn to
                    # (2.0): they were the session's, and leaked into the
                    # next design. A/B/DBL are the free box's, kept while it
                    # is snapped to the lens.
                    "construction": {"crest_height_mm": ws.crest_height,
                                     "crest_width_mm": ws.arm_spread,
                                     "angle_height_mm": ws.arm_drop},
                    "boxing": {"a_mm": ws.boxing_a, "b_mm": ws.boxing_b,
                               "dbl_mm": ws.boxing_dbl}}
                   if ws.workspace_type == "front" else {}),
            },
            "fill": {
                "visible": ws.fill_visible,
                "color":   ws.fill_color,
                "opacity": ws.fill_opacity,
                "style":   ws.fill_style,
                # Saved even while the color is showing, so switching back to
                # Image after a reload finds the swatch still attached.
                "image":   ws.fill_image,
            },
            "inlay_fill": {
                "visible": ws.inlay_fill_visible,
                "color":   ws.inlay_fill_color,
                "opacity": ws.inlay_fill_opacity,
                "style":   ws.inlay_fill_style,
                "image":   ws.inlay_fill_image,   # kept while the color shows
                "tumble":  ws.inlay_fill_tumble,
            },
            "lens_fill": {
                "visible": ws.lens_fill_visible,
                "top":     ws.lens_fill_top,
                "bottom":  ws.lens_fill_bottom,
                "linked":  ws.lens_fill_linked,
                "opacity": ws.lens_fill_opacity,
                "intensity": ws.lens_fill_intensity,
            },
            "texts": ws.doc_texts,
        }

    def _do_save_svg(self, path: str, ws: "WorkspaceState | None" = None,
                     export: bool = False):
        """Write one workspace as a plain SVG. Used by File > Save/Save As
        for a .svg document (legacy single-workspace format: always the
        Frame Front, whatever tab is showing — otherwise Ctrl+S from a
        temple tab wrote the temple over front.svg) and by Export > SVG
        (the active workspace)."""
        # First flush sidebar into active ws
        self._save_ws_sidebar_state(self._active_ws)
        from .export.svg import save_svg, portable_face_images, portable_fill
        ws = ws or self._workspaces[0]
        d  = self._ws_to_data_dict(ws)
        save_svg(
            curves          = d["curves"],
            path            = path,
            calibration     = d["calibration"],
            mirror          = d["mirror"],
            forming         = d["forming"],
            machined_bridge = d["machined_bridge"],
            face_images     = portable_face_images(d["face_images"], path),
            bookmarks       = d["bookmarks"],
            dims            = d["dims"],
            layers          = d["layers"],
            guides          = d["guides"],
            fill            = portable_fill(d["fill"], path),
            inlay_fill      = portable_fill(d["inlay_fill"], path),
            lens_fill       = d["lens_fill"],
            texts           = d["texts"],
            bevel           = d["bevel"],
            text_outlines   = export,
        )

    def _do_save_gdraw(self, path: str, carry_from: str | None = None) -> list[str]:
        """Save all three workspaces as a .gdraw ZIP. *carry_from* is the file
        the save replaces (its images stand in for any that cannot be read
        now); returns notes on the images not carried (gdraw.save_gdraw)."""
        # Flush sidebar into active workspace before building data dicts
        self._save_ws_sidebar_state(self._active_ws)
        tab_names = ["front", "temple_r", "temple_l", "component"]
        from .export.gdraw import save_gdraw
        ws_data = {}
        for ws, tab in zip(self._workspaces, tab_names, strict=True):
            ws_data[tab] = self._ws_to_data_dict(ws)
        active_tab = tab_names[self._ws_tab_widget.currentIndex()]
        return save_gdraw(ws_data, path, active_tab=active_tab,
                          carry_from=carry_from)

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    @staticmethod
    def _stock_mm(ws: "WorkspaceState") -> tuple[float, float]:
        """The workspace's stock guide (width, height) as the validator wants
        it, whether or not the guide is shown. Read from the session, not the
        guide: a Preferences change reaches an inactive tab's guide only when
        the tab is activated, and the batch export checks every tab."""
        return ws.stock_w, ws.stock_h

    def _readiness_note(self) -> str:
        """One-line GuildModel-readiness summary for the active workspace, used
        as the status-bar marker after a (never-blocked) DXF export."""
        from .export.validate import validate
        ws = self._active_ws
        errors, warnings = validate(self._doc_curves, self._act_mirror.isChecked(),
                                    ws.workspace_type, stock_mm=self._stock_mm(ws))
        if ws.workspace_type == "component":
            # GuildModel builds no part from this tab (the dot says so too).
            return (f"not ready for the library ({errors[0]})" if errors
                    else "a component for the library; GuildModel reads it "
                         "only once it is placed on the front or a temple")
        if errors:
            return f"not yet GuildModel-ready ({errors[0]})"
        if warnings:
            return f"ready for GuildModel (with warnings: {warnings[0]})"
        return "ready for GuildModel"

    def _export_dxf(self):
        # DXF export is never blocked on the contract: the maker may want a
        # partial frame, or an unusual multi-lens shape GuildModel will finish.
        # The readiness dot and the status note below report GuildModel-readiness.
        if self._tab_is_empty("Export DXF"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DXF", self._suggested(".dxf", per_tab=True),
            "DXF Files (*.dxf)"
        )
        if not path:
            return
        path = self._final_path(path, ".dxf")
        if path is None:
            return
        try:
            from .export.dxf import export_dxf
            # TextObjects become outline splines on their layer at export
            # time only — the document keeps the editable text.
            curves = list(self._doc_curves)
            if self._active_ws.doc_texts:
                from .textpath import text_to_curves
                for tobj in self._active_ws.doc_texts:
                    curves.extend(text_to_curves(tobj))
            export_dxf(curves=curves, path=path)
            self._status.showMessage(
                f"DXF exported: {os.path.basename(path)} — {self._readiness_note()}")
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export the DXF",
                                 _write_error_text("export the DXF", path, e))

    def _export_all_dxf(self):
        """File > Export > Export All DXF… — one DXF per populated workspace
        (<base>_front.dxf, _temple_r, _temple_l, _component). Export is never
        blocked; the per-workspace validator only annotates which files aren't
        GuildModel-ready yet (reported after the write)."""
        from .export.batch import (
            BatchWorkspace, base_from_path, check_batch, write_batch,
        )
        # Flush sidebar state so the active workspace's mirror toggle is
        # current in ws.mirror_enabled (the other workspaces were flushed
        # when their tabs were left).
        self._save_ws_sidebar_state(self._active_ws)

        items = []
        tab_names = ["front", "temple_r", "temple_l", "component"]
        for ws, tab in zip(self._workspaces, tab_names, strict=True):
            curves = [c for c in ws.doc_curves if not c.mirrored]
            if ws.doc_texts:
                from .textpath import text_to_curves
                for tobj in ws.doc_texts:
                    curves.extend(text_to_curves(tobj))
            items.append(BatchWorkspace(
                workspace_type = tab,
                curves         = curves,
                mirror_on      = ws.mirror_enabled,
                stock_mm       = self._stock_mm(ws),
            ))

        if not any(it.curves for it in items):
            QMessageBox.information(self, "Export All DXF",
                                    "All workspaces are empty — nothing to export.")
            return

        ws_titles = {"front": "Frame Front", "temple_r": "Temple R",
                     "temple_l": "Temple L",  "component": "Component"}
        # Validation never blocks the batch export — it only annotates which
        # workspaces aren't GuildModel-ready yet (reported after the write).
        report = check_batch(items)

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Every Tab as DXF: Choose a Base Name",
            self._suggested(".dxf"), "DXF Files (*.dxf)")
        if not path:
            return
        self._remember_dir(path)
        base = base_from_path(path)
        # The dialog asked about <base>.dxf, which is never written; the files
        # that are were replaced unasked, a hand-edited one among them.
        from .export.batch import batch_paths
        there = [p for p in batch_paths(base, items).values() if os.path.exists(p)]
        if there:
            more = f" and {len(there) - 1} more" if len(there) > 1 else ""
            r = QMessageBox.question(
                self, "Replace Files?",
                f"{os.path.basename(there[0])}{more} already exist"
                f"{'s' if len(there) == 1 else ''}. Replace "
                f"{'it' if len(there) == 1 else 'them'}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            written = write_batch(items, base)
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export Every Tab",
                                 _write_error_text("export every tab as DXF", base + ".dxf", e))
            return
        names = ", ".join(os.path.basename(p) for p in written)
        msg = f"Exported {len(written)} DXF file(s): {names}"
        if report.skipped:
            msg += " — skipped (empty): " + ", ".join(
                ws_titles[t] for t in report.skipped)
        not_ready = [t for t in ws_titles if t in report.errors]
        if not_ready:
            msg += " — not yet GuildModel-ready: " + ", ".join(
                ws_titles[t] for t in not_ready)
        self._status.showMessage(msg)
        # The file-name preview in the dialog can't show the suffixing, so
        # confirm what actually landed on disk.
        info = "Written:\n" + "\n".join(f"• {os.path.basename(p)}" for p in written)
        if report.skipped:
            info += "\n\nSkipped (empty): " + ", ".join(
                ws_titles[t] for t in report.skipped)
        if not_ready:
            info += "\n\nNot yet GuildModel-ready (exported anyway):"
            for tab in not_ready:
                info += f"\n• {ws_titles[tab]}: {report.errors[tab][0]}"
        QMessageBox.information(self, "Export All DXF", info)

    def _export_svg(self):
        """Export the active workspace as SVG without touching the current
        document path or window title (unlike File > Save)."""
        if self._tab_is_empty("Export SVG"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", self._suggested(".svg", per_tab=True),
            "SVG Files (*.svg)"
        )
        if not path:
            return
        path = self._final_path(path, ".svg")
        if path is None:
            return
        try:
            ws = self._active_ws
            _atomic_write(path, lambda tmp: self._do_save_svg(tmp, ws, export=True))
            self._status.showMessage(f"SVG exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export the SVG",
                                 _write_error_text("export the SVG", path, e))

    _PNG_DPI_CHOICES = [
        ("150 dpi — draft",       150),
        ("300 dpi — print",       300),
        ("600 dpi — high detail", 600),
        ("1200 dpi — maximum",    1200),
    ]

    def _png_content_rect(self) -> QRectF | None:
        """Tight scene-mm bounds for the PNG export: the geometry (same bbox
        rule as the SVG viewBox), its mirror ghost when displayed, the
        engraving text, and any visible face photos. None = no content
        (caller falls back to sceneRect)."""
        from .export.svg import _content_bbox
        from .textpath import text_outline_path
        ws = self._active_ws
        rect = QRectF()
        curves = [c for c in self._doc_curves if c.nodes]
        if curves:
            x0, y0, x1, y1 = _content_bbox(curves)
            rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            if self._act_mirror.isChecked():
                if ws.workspace_type in ("temple_r", "temple_l"):
                    ghost = QRectF(x0, -y1, x1 - x0, y1 - y0)
                else:
                    ax = self.scene.mirror.x if self.scene.mirror else 0.0
                    ghost = QRectF(2 * ax - x1, y0, x1 - x0, y1 - y0)
                rect = rect.united(ghost)
        for t in ws.doc_texts:
            if t.text.strip() and self.scene.is_layer_visible(t.layer):
                rect = rect.united(text_outline_path(t).boundingRect())
        for i in range(self.scene.face_count()):
            item = self.scene.get_face_item(i)
            if item is not None and item.isVisible():
                rect = rect.united(item.sceneBoundingRect())
        return rect if not rect.isEmpty() else None

    def _export_png(self):
        if self._tab_is_empty("Export PNG") and not self.scene.face_count():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", self._suggested(".png", per_tab=True),
            "PNG Files (*.png)"
        )
        if not path:
            return
        # Some file dialogs hand back exactly what was typed. Without the
        # suffix the raster lands somewhere the maker won't find it (and used
        # to not land at all), so add it here rather than trust the dialog.
        path = self._final_path(path, ".png")
        if path is None:
            return
        labels = [lbl for lbl, _dpi in self._PNG_DPI_CHOICES]
        dpis   = [dpi for _lbl, dpi in self._PNG_DPI_CHOICES]
        last   = self._prefs.get("png_export_dpi", 600)
        idx    = dpis.index(last) if last in dpis else 2
        choice, ok = QInputDialog.getItem(
            self, "Export PNG",
            "Resolution (the drawing at true size):",
            labels, idx, False)
        if not ok:
            return
        dpi = dpis[labels.index(choice)]
        if dpi != last:
            self._prefs["png_export_dpi"] = dpi
            self._save_prefs()
        # The drawing, not the editing: the selection's glow, its node and
        # handle dots and the Move gizmo were in the image.
        selected = list(self.scene.selectedItems())
        had_gizmo = self._move_gizmo is not None
        self._edit_tool.clear()
        self._hide_move_gizmo()
        self.scene.blockSignals(True)
        self.scene.clearSelection()
        self.scene.blockSignals(False)
        try:
            from .export.png import render_png
            # WYSIWYG, View Obverse included: the image is the canvas as seen.
            obverse = self.view.is_obverse()
            written = _atomic_write_result(path, lambda tmp: render_png(
                self.scene, tmp, dpi=dpi, rect=self._png_content_rect(),
                background=theme.color("canvas.bg"), mirrored=obverse))
            capped = (f"  ·  at {written:.0f} dpi: the largest image is "
                      "8192 px a side" if written and written < dpi - 0.5 else "")
            self._status.showMessage(
                f"PNG exported: {os.path.basename(path)}" + capped
                + (f"  ·  the {_OBVERSE_FACE[self._active_ws.workspace_type]}, "
                   "as View Obverse shows it" if obverse else ""))
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export the PNG",
                                 _write_error_text("export the PNG", path, e))
        finally:
            self.scene.select_items(selected)
            if had_gizmo and selected:
                self._show_move_gizmo()

    # ------------------------------------------------------------------
    # OMA lens-trace interchange (M7)
    # ------------------------------------------------------------------

    def _import_dxf(self, path: str | None = None):
        """File > Import > DXF… — pour any DXF's geometry into the active
        workspace.  Recognized GuildDraw layer names valid for this workspace
        are kept; everything else lands on the active layer, ungrouped, so the
        maker can drag each path to the right layer in the Layers panel."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import DXF", self._dialog_dir(), "DXF Files (*.dxf);;All Files (*)")
            if not path:
                return
        self._remember_dir(path)
        ws = self._active_ws
        try:
            from .export.dxf_import import import_dxf
            curves, notes = import_dxf(path, ws.active_layer, ws.workspace_type)
        except Exception as e:
            QMessageBox.critical(self, "Could Not Import the DXF", str(e))
            return
        if not curves:
            extra = ("\n\n" + "\n".join(notes)) if notes else ""
            QMessageBox.information(
                self, "Nothing Imported",
                f"No supported geometry was found in this DXF.{extra}")
            return

        self._push_undo_snapshot()
        self.scene.clearSelection()
        for c in curves:
            c.mirrored = False
            self._active_ws.add_curve(c).setSelected(True)

        msg = f"Imported {len(curves)} curve(s) from {os.path.basename(path)}."
        if notes:
            msg += "  " + "  ".join(notes)
        self._status.showMessage(msg)

    def _import_svg(self, path: str | None = None):
        """File > Import > SVG… — pour any SVG's geometry into the active
        workspace: a logo for a temple engraving, a shape from a colleague's
        drawing, an outline traced in another editor.  Paths arrive as the
        exact cubic splines the file holds; a group labeled with a GuildDraw
        layer name valid here keeps the layer, everything else lands on the
        active layer, selected.  A file that declares no physical size is
        read at 96 px/in and offered a size, since a logo drawn at page size
        is never wanted at page size on a temple."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import SVG", self._dialog_dir(), "SVG Files (*.svg);;All Files (*)")
            if not path:
                return
        self._remember_dir(path)
        ws = self._active_ws
        try:
            from .export.svg_import import place_curves, read_svg
            doc = read_svg(path, ws.active_layer, ws.workspace_type)
        except Exception as e:
            QMessageBox.critical(self, "Could Not Import the SVG", str(e))
            return
        if not doc.curves:
            extra = ("\n\n" + "\n".join(doc.notes)) if doc.notes else ""
            QMessageBox.information(
                self, "Nothing Imported",
                f"No supported geometry was found in this SVG.{extra}")
            return

        answer = self._ask_svg_import(doc, os.path.basename(path))
        if answer is None:
            return                              # canceled
        scale, center_on_view = answer
        center = None
        if center_on_view:
            r = self._view_source_rect()
            center = (r.center().x(), r.center().y())
        curves = place_curves(doc.curves, scale=scale, center=center)

        self._push_undo_snapshot()
        self.scene.clearSelection()
        for c in curves:
            c.mirrored = False
            ws.add_curve(c).setSelected(True)

        msg = (f"Imported {len(curves)} curve(s) from {os.path.basename(path)} at "
               f"{doc.width_mm * scale:.2f} × {doc.height_mm * scale:.2f} mm.")
        if doc.notes:
            msg += "  " + "  ".join(doc.notes)
        self._status.showMessage(msg)

    def _ask_svg_import(self, doc, filename: str) -> tuple[float, bool] | None:
        """Size and placement for an SVG import.

        Returns ``(scale, center_on_view)`` — the uniform factor to apply to the
        file's own millimeters, and whether to land the result in the middle of
        the view rather than where the file places it — or None if the maker
        canceled.  Split out so tests can monkeypatch the answer without driving
        a modal dialog."""
        import html as _html
        w0, h0 = doc.width_mm, doc.height_mm
        ref = w0 if w0 > 1e-9 else h0
        basis = ("at the size the file declares" if doc.physical
                 else "at 96 pixels per inch — the file declares no physical size")
        dlg = QDialog(self)
        dlg.setWindowTitle("Import SVG")
        lay = QVBoxLayout(dlg)
        note = QLabel(
            f"<b>{_html.escape(filename)}</b> holds {len(doc.curves)} curve(s), "
            f"{w0:.2f} × {h0:.2f} mm {basis}.<br><br>"
            "Set the width to import it at another size; the height follows.")
        note.setWordWrap(True)
        lay.addWidget(note)

        spin = QDoubleSpinBox()
        spin.setRange(0.01, 10000.0)
        spin.setDecimals(2)
        spin.setSuffix(" mm")
        spin.setValue(w0 if w0 > 1e-9 else h0)
        height_lbl = QLabel()

        def _show_height(v: float) -> None:
            if w0 > 1e-9:
                height_lbl.setText(f"{h0 * v / w0:.2f} mm")
            else:
                height_lbl.setText(f"{v:.2f} mm")
        spin.valueChanged.connect(_show_height)
        _show_height(spin.value())
        form = QFormLayout()
        form.addRow("Width:" if w0 > 1e-9 else "Height:", spin)
        form.addRow("Height:" if w0 > 1e-9 else "Width:",
                    height_lbl if w0 > 1e-9 else QLabel("0.00 mm"))
        lay.addLayout(form)
        spin.setEnabled(ref > 1e-9)

        center_cb = QCheckBox("Center on the view")
        center_cb.setChecked(not doc.physical)
        center_cb.setToolTip(
            "On: the geometry lands in the middle of what you are looking at.\n"
            "Off: it lands where the file places it, in millimeters from the "
            "file's origin — a drawing exported at true scale comes back where "
            "it was.")
        lay.addWidget(center_cb)

        btns = QDialogButtonBox()
        b_import = btns.addButton("Import", QDialogButtonBox.AcceptRole)
        btns.addButton(QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        b_import.setDefault(True)
        lay.addWidget(btns)
        if _run_modal(dlg) != QDialog.Accepted:
            return None
        scale = (spin.value() / ref) if ref > 1e-9 else 1.0
        return scale, center_cb.isChecked()

    def _ask_oma_import_bevel(self, default_depth: float) -> float | None:
        """Ask whether to shrink an imported OMA trace by the bevel depth.

        Returns the depth to shrink by (0.0 = import at traced size), or
        None if the user canceled the import. Split out so tests can
        monkeypatch the answer without driving a modal dialog."""
        return self._ask_oma_bevel(
            "Import OMA Lens Trace",
            "A tracer follows the bevel groove of the <b>finished</b> lens — "
            "the drawn lens shape grown outward by the bevel depth (this is "
            "also what OMA export writes).<br><br>"
            "Shrink the imported shape by the bevel depth to recover the "
            "drawn lens? Importing at the same depth the file was exported "
            "with round-trips exactly.",
            default_depth, "Shrink to the Drawn Lens", "Import As Traced")

    def _ask_oma_export_bevel(self, default_depth: float) -> float | None:
        """Ask whether to grow the exported OMA trace by the bevel depth.

        Returns the depth to grow by (0.0 = export the drawn lens opening
        as-is), or None if the user canceled the export. Split out so tests
        can monkeypatch the answer without driving a modal dialog."""
        return self._ask_oma_bevel(
            "Export OMA Trace",
            "A frame trace follows the bevel groove of the <b>finished</b> "
            "lens, not the drawn lens opening.<br><br>"
            "Grow the exported trace by the bevel depth so labs and edgers "
            "receive the finished size? The depth defaults to the boxing "
            "guide's bevel setting; HBOX/VBOX/DBL are computed from the "
            "same geometry either way.",
            default_depth, "Export the Finished Lens", "Export the Drawn Opening")

    def _ask_oma_bevel(self, title: str, note_html: str, default_depth: float,
                       apply_label: str, asis_label: str) -> float | None:
        """Shared import/export bevel-depth dialog. Returns the chosen depth,
        0.0 for the as-is button, or None on cancel."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        note = QLabel(note_html)
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel("Bevel depth:"))
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 5.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setSuffix(" mm")
        spin.setValue(default_depth)
        row.addWidget(spin)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QDialogButtonBox()
        b_apply = btns.addButton(apply_label, QDialogButtonBox.AcceptRole)
        b_asis  = btns.addButton(asis_label, QDialogButtonBox.ActionRole)
        btns.addButton(QDialogButtonBox.Cancel)
        btns.rejected.connect(dlg.reject)
        result: dict = {}
        def _accept(mode):
            result["mode"] = mode
            dlg.accept()
        b_apply.clicked.connect(lambda: _accept("apply"))
        b_asis.clicked.connect(lambda: _accept("asis"))
        b_apply.setDefault(True)
        lay.addWidget(btns)
        if _run_modal(dlg) != QDialog.Accepted:
            return None
        return spin.value() if result.get("mode") == "apply" else 0.0

    def _import_oma(self, path: str | None = None):
        """File > Import > OMA Lens Trace… — traced lens shapes (from a frame
        tracer / lab DCS file) become editable LENS splines in Frame Front."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import OMA Lens Trace", self._dialog_dir(),
                "OMA / DCS Trace Files (*.oma *.dcs *.txt);;All Files (*)")
            if not path:
                return
        self._remember_dir(path)
        try:
            from .export.oma import parse_oma, trace_to_curve
            with open(path, encoding="ascii", errors="replace") as f:
                job = parse_oma(f.read())
            if not job.traces:
                QMessageBox.information(
                    self, "No Trace Data",
                    "This file contains no TRCFMT/R lens-trace records.")
                return
            lenses = {side: trace_to_curve(tr.radii_mm)
                      for side, tr in job.traces.items()}
        except Exception as e:
            QMessageBox.critical(self, "Could Not Import the OMA Trace", str(e))
            return

        # DBL from the file when present, else the boxing-guide setting.
        front = self._workspaces[0]
        dbl_vals = job.floats("DBL")
        dbl = dbl_vals[0] if dbl_vals else front.boxing_dbl

        # A tracer follows the bevel groove of the FINISHED lens — the drawn
        # lens grown outward by the bevel depth (exactly what OMA export
        # writes). Ask whether to shrink back to the drawn lens shape.
        shrink = self._ask_oma_import_bevel(front.bevel_depth)
        if shrink is None:
            return                              # canceled
        if shrink > 0.0:
            try:
                from .geometry import offset_curve as _offset
                lenses = {side: _offset(c, -shrink)
                          for side, c in lenses.items()}
            except Exception as e:
                QMessageBox.warning(
                    self, "Bevel Reduction Failed",
                    f"Could not shrink the trace by {shrink:.2f} mm "
                    f"({e}).\nImporting at traced (finished) size instead.")
                shrink = 0.0
        # The file's DBL describes the finished lenses; after shrinking, the
        # drawn nasal edges sit a bevel depth further apart on each side so
        # the finished edges still land DBL apart.
        dbl_place = dbl + 2.0 * shrink

        # Place each lens: boxing centers on y = 0, nasal edges DBL apart.
        # Side R (OD) sits at negative x — viewer's left, same convention as
        # the measurement panel's OD/OS split about the mirror axis.
        # Sampled bbox (lens_bbox) so placement uses the same boxing basis as
        # the measurements panel, not the control-point extents.
        from .boxing import lens_bbox
        for side, c in lenses.items():
            bb = lens_bbox(c)
            if bb is None:
                continue
            w  = bb[2] - bb[0]
            tx = (-(dbl_place / 2 + w / 2) if side == "R"
                  else (dbl_place / 2 + w / 2)) \
                 - (bb[0] + bb[2]) / 2
            ty = -(bb[1] + bb[3]) / 2
            for nd in c.nodes:
                nd.x += tx;  nd.y += ty
                if nd.cp_in:
                    nd.cp_in.x  += tx;  nd.cp_in.y  += ty
                if nd.cp_out:
                    nd.cp_out.x += tx;  nd.cp_out.y += ty

        # A front with lenses already: replace them, or add the traced ones
        # beside them? Both went in, unasked, one pair over the other.
        drawn = [c for c in front.doc_curves
                 if c.layer == Layer.LENS and not c.mirrored]
        mode = self._ask_oma_import_mode(len(drawn)) if drawn else "add"
        if mode is None:
            return
        # Traces always land in Frame Front — switch first so the undo
        # snapshot and status bar belong to the workspace that changes.
        self._ws_tab_widget.setCurrentIndex(0)
        self._push_undo_snapshot()
        if mode == "replace":
            for c in drawn:
                self._active_ws.remove_curve(c)
        for c in lenses.values():
            self._active_ws.add_curve(c)

        # DRILLE holes → DRILL circles. OMA is y-up from the binocular frame
        # center, which the import places at the scene origin (0, 0).
        for d in job.drills:
            self._active_ws.add_curve(Curve(
                kind="circle", layer=Layer.DRILL,
                nodes=[SplineNode(d.x, -d.y)],
                radius=max(0.05, d.dia / 2.0), closed=True))

        src = "file DBL" if dbl_vals else "boxing-guide DBL"
        msg = (f"Imported {len(lenses)} traced lens shape"
               f"{'s' if len(lenses) != 1 else ''} onto LENS "
               f"({src} {dbl:.1f} mm).")
        if shrink > 0.0:
            msg += f"  Bevel reduction −{shrink:.2f} mm applied."
        if job.drills:
            msg += f"  +{len(job.drills)} drill hole(s) on DRILL."
        if len(lenses) == 1:
            msg += (" One lens in the file: the Ghost previews the other; bake it "
                    "with Mirror before handing the front to GuildModel.")
        self._status.showMessage(msg)

    def _ask_oma_import_mode(self, n: int) -> str | None:
        """'replace' or 'add' for traced lenses coming into a front that has
        *n* drawn lenses already; None to cancel."""
        box = QMessageBox(
            QMessageBox.Icon.Question, "Import OMA Lens Trace",
            f"The Frame Front already has {n} lens{'es' if n != 1 else ''}. "
            "Replace them with the traced lenses, or add the traced lenses "
            "beside them?", QMessageBox.StandardButton.Cancel, self)
        replace = box.addButton("Replace", QMessageBox.ButtonRole.AcceptRole)
        add = box.addButton("Add", QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(replace)
        box.exec()
        return {replace: "replace", add: "add"}.get(box.clickedButton())

    def _export_oma(self):
        """File > Export > OMA Trace… — write the two LENS contours as a
        TRCFMT format-1 DCS file for labs and edgers.

        A dialog asks whether the trace should describe the FINISHED lens —
        the drawn LENS shape grown outward by the bevel depth (a frame trace
        follows the bevel groove, not the lens opening; depth defaults to the
        boxing guide's bevel setting) — or the drawn lens opening as-is.
        HBOX/VBOX/DBL come from the same chosen geometry, so at the guide
        depth the file agrees with the boxing panel's finished read-outs."""
        if self._active_ws.workspace_type != "front":
            # The lenses are the front's: go there, as Import OMA does (the
            # export refused from a temple with a note to switch by hand).
            self._ws_tab_widget.setCurrentIndex(0)
            QApplication.processEvents()

        from .export.oma import (
            OmaJob, OmaTrace, build_oma, curve_to_trace, points_to_trace,
            boxing_center,
        )
        from .boxing import finished_geometry
        # The Ghost pairs a lens drawn alone, as the canvas shows it; a pair
        # drawn (or baked) is two, Ghost or not: it read as four.
        drawn_lenses = [c for c in self._doc_curves
                        if not c.mirrored and c.layer == Layer.LENS]
        ghosted = self._ghost_twins(self._active_ws, drawn_lenses)
        lenses = drawn_lenses + ghosted
        if len(lenses) != 2:
            found = (f"{len(lenses)} ({len(drawn_lenses)} drawn, {len(ghosted)} "
                     "from the Ghost)" if ghosted else f"{len(lenses)}")
            how = ("Delete the extra lenses." if len(lenses) > 2 else
                   "Draw the other lens, or turn the Ghost on (View ▸ Ghost) to "
                   "pair the one drawn.")
            QMessageBox.warning(
                self, "OMA Export",
                f"An OMA trace holds one lens per eye, and the front has {found}. "
                + how)
            return
        for c in lenses:
            if not c.closed and len(c.nodes) >= 2:
                n0, n1 = c.nodes[0], c.nodes[-1]
                gap = math.hypot(n1.x - n0.x, n1.y - n0.y)
                if gap > 0.1:
                    QMessageBox.warning(
                        self, "OMA Export",
                        f"A LENS contour is not closed "
                        f"(endpoint gap {gap:.3f} mm > 0.1 mm).")
                    return

        # OD (side R) = the lens with the smaller boxing-center x.
        lenses.sort(key=lambda c: boxing_center(c)[0])
        od, os_lens = lenses

        depth = self._ask_oma_export_bevel(max(0.0, self._active_ws.bevel_depth))
        if depth is None:
            return                              # canceled

        # Build the job before asking for a filename — the tracer rejects
        # non-star-shaped contours and we want that error first.
        try:
            job = OmaJob()
            boxes = {}
            for side, c in (("R", od), ("L", os_lens)):
                bb, outline = finished_geometry(c, depth)
                if bb is None:
                    raise ValueError("A LENS contour has no area — cannot trace.")
                radii = (points_to_trace(outline) if outline is not None
                         else curve_to_trace(c))
                job.traces[side] = OmaTrace(side=side, radii_mm=radii)
                boxes[side] = bb
            job.set_record("HBOX", ";".join(
                f"{boxes[s][2] - boxes[s][0]:.2f}" for s in ("R", "L")))
            job.set_record("VBOX", ";".join(
                f"{boxes[s][3] - boxes[s][1]:.2f}" for s in ("R", "L")))
            job.set_record("DBL", f"{boxes['L'][0] - boxes['R'][2]:.2f}")
            job.set_record("FED", ";".join(
                f"{2.0 * max(job.traces[s].radii_mm):.2f}" for s in ("R", "L")))
        except Exception as e:
            # Any failure, not only the tracer's ValueError: a geometry error
            # from a lens with a broken shape left the menu doing nothing.
            QMessageBox.critical(
                self, "Could Not Export the OMA Trace",
                f"The lenses could not be traced: {e}")
            return

        # Drill-mount holes (DRILL layer) → DRILLE features, in the binocular
        # frame system: origin midway between the two lens centers, y-up.
        from .export.oma import OmaDrill
        # Both coordinates from that center: y was taken from the scene
        # origin, and on a front drawn 7 mm above it a hole 5 mm above its
        # lens went to the lab as 12 mm (the import places the center at the
        # origin, so the round trip moved the hole too).
        center_r, center_l = boxing_center(od), boxing_center(os_lens)
        origin_x = (center_r[0] + center_l[0]) / 2.0
        origin_y = (center_r[1] + center_l[1]) / 2.0
        holes = [c for c in self._doc_curves
                 if not c.mirrored and c.layer == Layer.DRILL
                 and c.kind == "circle" and c.nodes]
        # The Ghost's twin of a hole drawn on one eye only, as for the lenses.
        for c in holes + self._ghost_twins(self._active_ws, holes):
            hx, hy = c.nodes[0].x, c.nodes[0].y
            dia = 2.0 * (c.radius or 0.7)
            job.drills.append(OmaDrill(hx - origin_x, -(hy - origin_y), dia))

        path, _ = QFileDialog.getSaveFileName(
            self, "Export OMA Trace", self._suggested(".oma"),
            "OMA / DCS Trace Files (*.oma);;All Files (*)")
        if not path:
            return
        path = self._final_path(path, ".oma")
        if path is None:
            return
        try:
            with open(path, "w", encoding="ascii", newline="") as f:
                f.write(build_oma(job))
            size = (f"finished lens (+{depth:.2f} mm bevel)" if depth > 0.0
                    else "drawn lens opening (as-is)")
            self._status.showMessage(
                f"OMA trace exported: {os.path.basename(path)} — {size}.")
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export the OMA Trace",
                                 _write_error_text("export the OMA trace", path, e))

    # ------------------------------------------------------------------
    # Print / PDF at 1:1 scale (M8)
    # ------------------------------------------------------------------

    _PRINT_PAD_MM = 5.0

    def _view_source_rect(self):
        """The scene-mm rectangle currently framed in the viewport (WYSIWYG)."""
        return self.view.mapToScene(self.view.viewport().rect()).boundingRect()

    def _print_1to1(self):
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        if not self._has_visible_geometry():
            QMessageBox.information(
                self, "Print at 1:1",
                "Nothing to print — this workspace has no visible geometry.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print at 1:1 Scale")
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        try:
            clipped = self._render_1to1(printer, self._view_source_rect())
        except Exception as e:
            QMessageBox.critical(self, "Could Not Print", str(e))
            return
        self._status.showMessage(
            "Printed at 1:1 — view larger than the page, edges cropped."
            if clipped else "Printed at 1:1 scale.")

    def _export_pdf_1to1(self):
        from PySide6.QtPrintSupport import QPrinter
        if not self._has_visible_geometry():
            QMessageBox.information(
                self, "Export PDF",
                "Nothing to export — this workspace has no visible geometry.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF (Current View, 1:1)",
            self._suggested(".pdf", per_tab=True), "PDF Files (*.pdf)")
        if not path:
            return
        path = self._final_path(path, ".pdf")
        if path is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        try:
            clipped = self._render_1to1(printer, self._view_source_rect())
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export the PDF",
                                 _write_error_text("export the PDF", path, e))
            return
        self._status.showMessage(
            f"PDF exported at 1:1: {os.path.basename(path)}"
            + ("  — view larger than the page, edges cropped." if clipped else ""))

    def _has_visible_geometry(self) -> bool:
        if any(c.nodes and not c.mirrored and self.scene.is_layer_visible(c.layer)
               for c in self._doc_curves):
            return True
        return any(t.text.strip() and self.scene.is_layer_visible(t.layer)
                   for t in self._active_ws.doc_texts)

    def _render_1to1(self, printer, source):
        """Paint the CURRENT VIEW at exactly 1 mm = 1 mm paper scale.

        Renders the visible-layer geometry (and its mirror ghost) and the
        engraving text currently framed in the viewport, drawn as clean
        vectors in each layer's color at the uniform PDF line weight from
        Settings ▸ PDF, shifted by the vertical frame offset. A 50 mm ruler
        verifies the scale. Content larger than the page is cropped 1:1.
        """
        from PySide6.QtCore import QRectF as _QRectF
        from PySide6.QtPrintSupport import QPrinter
        from .canvas.items import build_path
        from .textpath import text_outline_path

        cfg    = self._prefs.get("catalog_pdf", {})
        lw_mm  = float(cfg.get("line_weight_mm", 0.6))
        off_mm = float(cfg.get("content_offset_mm", 0.0))

        px_mm_x = printer.logicalDpiX() / 25.4
        px_mm_y = printer.logicalDpiY() / 25.4
        page = printer.pageRect(QPrinter.Unit.DevicePixel)

        target_w = source.width()  * px_mm_x
        target_h = source.height() * px_mm_y
        target = _QRectF((page.width()  - target_w) / 2,
                         (page.height() - target_h) / 2 + off_mm * px_mm_y,
                         target_w, target_h)

        # Visible-layer geometry + mirror ghost (guides/photos never print).
        vis = [c for c in self._doc_curves
               if c.nodes and not c.mirrored and self.scene.is_layer_visible(c.layer)]
        draw = list(vis) + self._ghost_twins(self._active_ws, vis)
        texts = [t for t in self._active_ws.doc_texts
                 if self.scene.is_layer_visible(t.layer)]
        # Cropped when the drawing shown in the view runs off the page: the
        # view's rectangle was tested, and a front that fit was "cropped".
        shown = _QRectF()
        for c in draw:
            shown = shown.united(build_path(c).boundingRect())
        for t in texts:
            shown = shown.united(text_outline_path(t).boundingRect())
        shown = shown.intersected(source)
        on_page = _QRectF(target.left() + (shown.left() - source.left()) * px_mm_x,
                          target.top() + (shown.top() - source.top()) * px_mm_y,
                          shown.width() * px_mm_x, shown.height() * px_mm_y)
        clipped = (not shown.isEmpty() and not _QRectF(
            0, 0, page.width(), page.height()).contains(on_page))

        # begin() checked, as the template and catalog exports do: an
        # unwritable PDF path left the painter inactive and the status bar
        # announcing a file that was never written.
        painter = QPainter()
        if not painter.begin(printer):
            where = printer.outputFileName() or printer.printerName()
            raise OSError(f"could not write {where}")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.save()
            painter.setClipRect(target)              # crop to the framed view
            painter.translate(target.left(), target.top())
            painter.scale(px_mm_x, px_mm_y)          # 1 mm = 1 mm
            painter.translate(-source.left(), -source.top())
            cos_w = lw_mm * px_mm_x                   # cosmetic px == lw_mm on paper
            for c in draw:
                # Always the light-mode (print) layer inks — dark-mode inks are
                # pale and would wash out on white paper.
                pen = QPen(QColor(theme.default_layer_color(c.layer.value, False)))
                pen.setCosmetic(True)
                pen.setWidthF(cos_w)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(build_path(c))
            for t in texts:
                pen = QPen(QColor(theme.default_layer_color(t.layer.value, False)))
                pen.setCosmetic(True)
                pen.setWidthF(cos_w)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(text_outline_path(t))
            painter.restore()

            # The scale check the templates carry (one ruler, one caption).
            from .export.template_print import paint_ruler_strip
            paint_ruler_strip(painter, px_mm_x, page.height() / px_mm_y,
                              page.width() / px_mm_x - 10.0, origin_mm=5.0)
        finally:
            painter.end()

        return clipped

    # ------------------------------------------------------------------
    # Print Front + Temples — 1:1 cutting templates (front + both temples,
    # stacked at true size on the maker's paper, paginated as needed)
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_suffix(path: str, suffix: str) -> str:
        """Append *suffix* unless the chosen name already ends with it (a
        non-native file dialog returns exactly what was typed; QPrinter and
        ezdxf happily write to a suffix-less name)."""
        return path if path.lower().endswith(suffix) else path + suffix

    def _dialog_dir(self, kind: str = "last_dir") -> str:
        """Where a file dialog starts: the folder last used for this *kind*
        ("last_dir" for designs and exports, "last_image_dir" for reference
        images), else beside the open design, else home. Most dialogs opened
        in the working folder with no name at all."""
        last = self._prefs.get(kind, "")
        if isinstance(last, str) and last and os.path.isdir(last):
            return last
        if self._current_path:
            return os.path.dirname(os.path.abspath(self._current_path))
        return os.path.expanduser("~")

    def _remember_dir(self, path: str, kind: str = "last_dir") -> None:
        folder = os.path.dirname(os.path.abspath(path))
        if folder and self._prefs.get(kind) != folder:
            self._prefs[kind] = folder
            _prefs_mod.save(self._prefs)

    def _suggested(self, ext: str, per_tab: bool = False) -> str:
        """A starting name for an export: <folder>/<design>[_<tab>]<ext>, the
        names Export Every Tab gives its files."""
        stem = self._design_name() or "design"
        if per_tab:
            stem += f"_{self._active_ws.workspace_type}"
        return os.path.join(self._dialog_dir(), stem + ext)

    def _final_path(self, path: str, ext: str) -> str | None:
        """*path* with *ext*, asking before replacing a file the dialog never
        saw: it checked the name typed ("front"), and the suffix added after
        made it "front.dxf", replaced unasked. None to stop."""
        full = self._ensure_suffix(path, ext)
        if full != path and os.path.exists(full):
            r = QMessageBox.question(
                self, "Replace File?",
                f"{os.path.basename(full)} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return None
        self._remember_dir(full)
        return full

    def _tab_is_empty(self, what: str) -> bool:
        """Say so when the active tab holds nothing to export: an empty DXF and
        a blank PNG were written without a word."""
        ws = self._active_ws
        if ws.doc_curves or ws.doc_texts or ws.doc_dims:
            return False
        QMessageBox.information(
            self, what, f"The {_TAB_TITLES.get(ws.workspace_type, 'tab')} is "
            "empty: there is nothing to export.")
        return True

    def _design_name(self) -> str:
        """The open file's stem, or '' for an unsaved design."""
        return (os.path.splitext(os.path.basename(self._current_path))[0]
                if self._current_path else "")

    def _ghost_twins(self, ws: "WorkspaceState", curves: list) -> list:
        """The Ghost's twins of *curves* as the canvas casts them
        (``ghost_eligible``), less those a drawn curve stands for: a closed
        whole outline printed its own mirror, and a baked pair printed twice
        over (the 2.0 bug hunt). Empty with the Ghost off."""
        if not ws.mirror_enabled or ws.scene.mirror is None:
            return []
        from .export.validate import ghost_twins
        horizontal = ws.workspace_type in ("temple_r", "temple_l")
        drawn = [c for c in ws.doc_curves if not c.mirrored]
        return ghost_twins(drawn, [c for c in curves if ws.scene.ghost_eligible(c)],
                           ws.scene.mirror.x, horizontal=horizontal)

    def _gather_template_components(self) -> dict:
        """What each of the front and temple workspaces currently shows —
        visible-layer curves plus the mirror ghost (so a half-drawn front
        prints whole) and visible engraving text — keyed for
        export.template_print."""
        # Flush the live toolbar into the active workspace (mirror toggle).
        self._save_ws_sidebar_state(self._active_ws)
        out = {}
        for key, ws in zip(("front", "temple_r", "temple_l"),
                           self._workspaces[:3], strict=True):
            vis = [c for c in ws.doc_curves
                   if c.nodes and not c.mirrored
                   and ws.scene.is_layer_visible(c.layer)]
            curves = list(vis) + self._ghost_twins(ws, vis)
            texts = [t for t in ws.doc_texts
                     if t.text.strip() and ws.scene.is_layer_visible(t.layer)]
            out[key] = {"curves": curves, "texts": texts}
        return out

    def _template_print_status(self, verb: str, pages: int, clipped: bool):
        msg = f"{verb} {pages} page{'s' if pages != 1 else ''} at 1:1."
        if clipped:
            msg += "  A piece was larger than the page — its edges are cropped."
        self._status.showMessage(msg)

    def _print_templates(self):
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from .export.template_print import configure_printer, render_template_pages
        components = self._gather_template_components()
        if not any(c["curves"] or c["texts"] for c in components.values()):
            QMessageBox.information(
                self, "Print Front + Temples",
                "Nothing to print — the front and temple workspaces have no "
                "visible geometry.")
            return
        cfg = self._prefs.get("template_print", {})
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        configure_printer(printer, cfg, components)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print Front + Temples at 1:1")
        if _run_modal(dlg) != QDialog.DialogCode.Accepted:
            return
        try:
            pages, clipped = render_template_pages(
                printer, components, cfg, self._design_name())
        except Exception as e:
            QMessageBox.critical(self, "Could Not Print", str(e))
            return
        self._template_print_status("Printed", pages, clipped)

    def _export_pdf_templates(self):
        from .export.template_print import export_template_pdf
        components = self._gather_template_components()
        if not any(c["curves"] or c["texts"] for c in components.values()):
            QMessageBox.information(
                self, "PDF Front + Temples",
                "Nothing to export — the front and temple workspaces have no "
                "visible geometry.")
            return
        base = self._design_name()
        suggested = os.path.join(
            self._dialog_dir(), f"{base} templates.pdf" if base else "templates.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF Front + Temples (1:1 Templates)", suggested,
            "PDF Files (*.pdf)")
        if not path:
            return
        path = self._final_path(path, ".pdf")
        if path is None:
            return
        try:
            pages, clipped = export_template_pdf(
                path, components, self._prefs.get("template_print", {}), base)
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export the PDF",
                                 _write_error_text("export the PDF", path, e))
            return
        self._template_print_status(
            f"Templates PDF exported ({os.path.basename(path)}):", pages, clipped)

    # ------------------------------------------------------------------
    # PDF for Catalog (front + both temples on one sheet + the design name)
    # ------------------------------------------------------------------

    def _catalog_component_curves(self, ws, layer_names) -> list:
        """Selected-layer geometry for one workspace, INCLUDING the mirror ghost
        so the full frame (not just the drawn half) reaches the catalog."""
        wanted = set(layer_names)
        base = [c for c in ws.doc_curves
                if c.layer.value in wanted and not c.mirrored and c.nodes]
        return list(base) + self._ghost_twins(ws, base)

    def _gather_catalog_components(self) -> dict:
        cfg = self._prefs.get("catalog_pdf", {})
        front_layers  = cfg.get("front_layers", ["OUTLINE", "LENS"])
        temple_layers = cfg.get("temple_layers", ["OUTLINE"])
        front, temple_r, temple_l = self._workspaces[0], self._workspaces[1], self._workspaces[2]
        return {
            "front":    self._catalog_component_curves(front, front_layers),
            "temple_r": self._catalog_component_curves(temple_r, temple_layers),
            "temple_l": self._catalog_component_curves(temple_l, temple_layers),
        }

    def _gather_catalog_fills(self) -> dict:
        """Per-component Frame, Inlay and Lens Fill overlays for the catalog sheet,
        taken from each workspace's own live scene so the page shows the tint
        that workspace shows. {} unless Settings ▸ PDF asks for them; a
        workspace with its fill off simply contributes nothing."""
        if not self._prefs.get("catalog_pdf", {}).get("include_fill", False):
            return {}
        out = {}
        for key, ws in zip(("front", "temple_r", "temple_l"),
                           self._workspaces[:3], strict=True):
            frame = ws.scene.fill_paint_spec()
            inlay = ws.scene.inlay_fill_paint_spec()
            lens  = ws.scene.lens_fill_paint_spec()
            if frame or inlay or lens:
                out[key] = {"frame": frame, "inlay": inlay, "lens": lens}
        return out

    def _export_pdf_catalog(self):
        # Flush the live sidebar into the active workspace so its curves are current.
        self._save_ws_sidebar_state(self._active_ws)
        components = self._gather_catalog_components()
        if not any(components.values()):
            QMessageBox.information(
                self, "PDF for Catalog",
                "Nothing to export — the front and temple workspaces have no "
                "geometry on the selected layers (set them in "
                "Preferences ▸ PDF).")
            return
        base = self._design_name()
        suggested = os.path.join(self._dialog_dir(),
                                 f"{base}.pdf" if base else "catalog.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF for Catalog", suggested, "PDF Files (*.pdf)")
        if not path:
            return
        path = self._final_path(path, ".pdf")
        if path is None:
            return
        caption = base or os.path.splitext(os.path.basename(path))[0]
        try:
            from .export.catalog_pdf import export_catalog_pdf
            export_catalog_pdf(path, components, self._prefs.get("catalog_pdf", {}),
                               caption, self._gather_catalog_fills())
            self._status.showMessage(
                f"Catalog PDF exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Could Not Export the Catalog PDF",
                                 _write_error_text("export the catalog PDF", path, e))

    def _export_catalog_folder(self):
        """File ▸ Export ▸ Catalog PDFs for a Folder… (Road to 1.4, item 3):
        scripts/batch_catalog.py in the app. A folder picker first, then the
        fill and where the PDFs go, then the run with a verdict per file."""
        from .batch_catalog_ui import (BatchCatalogOptionsDialog,
                                       BatchCatalogProgressDialog)
        from .export.batch_catalog import library_files
        last = dict(self._prefs.get("batch_catalog", {}))
        start = (os.path.dirname(self._current_path) if self._current_path
                 else last.get("library", ""))
        library = QFileDialog.getExistingDirectory(
            self, "Folder of .gdraw Designs", start)
        if not library:
            return
        if not library_files(library):
            QMessageBox.information(
                self, "Catalog PDFs for a Folder",
                f"No .gdraw files at the top of {library}.")
            return
        dlg = BatchCatalogOptionsDialog(self, library, last)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        opts = dlg.options()
        self._prefs["batch_catalog"] = dlg.remembered()
        _prefs_mod.save(self._prefs)
        progress = BatchCatalogProgressDialog(self, len(library_files(library)))
        progress.show()
        QApplication.processEvents()
        report = self._run_catalog_batch(
            library, opts,
            progress=lambda i, n, v: (progress.step(i, n, v.line()),
                                      QApplication.processEvents()),
            should_stop=progress.canceled)
        progress.finish(report.summary(),
                        str(report.out_dir) if report.out_dir is not None
                        and report.pdfs and not report.dry_run else None)
        progress.exec()

    def _run_catalog_batch(self, library: str, opts, progress=None,
                           should_stop=None):
        """Run the batch in a second window that is never shown, so the
        design open here is untouched; the window goes when the run ends.
        Returns the report (export.batch_catalog.BatchCatalogReport)."""
        from .export.batch_catalog import run_batch_catalog
        hidden = MainWindow()
        try:
            return run_batch_catalog(hidden, library, opts,
                                     progress=progress, should_stop=should_stop)
        finally:
            hidden._dirty = False
            hidden.close()
            hidden.deleteLater()

    # ------------------------------------------------------------------
    # Persistent preferences
    # ------------------------------------------------------------------

    def _save_prefs(self):
        """Persist durable settings only.

        Startup toggles and guide dimensions are written exclusively by the
        Settings dialog (see _open_settings) — toggling Ghost mid-session must
        not silently rewrite mirror_on_startup.
        """
        self._prefs["dark_mode"]           = self._dark_mode
        self._prefs["default_line_weight"] = self._default_line_weight
        self._prefs["toolbar_pinned"]      = self._toolbar.is_pinned()
        self._prefs["toolbar"]             = dict(self._toolbar_prefs)
        self._prefs["hotkeys"]             = dict(self._hotkey_prefs)
        _prefs_mod.save(self._prefs)

    def _on_toolbar_pin_changed(self, pinned: bool):
        """User toggled the toolbar overflow pin — persist the choice."""
        self._save_prefs()

    def _on_tooltips_toggled(self, on: bool, announce: bool = True):
        """The ? button: tooltips on or off, app-wide, remembered."""
        self._tooltip_filter.enabled = bool(on)
        self._act_tooltips.setToolTip(
            "Tooltips are on \u2014 click to hide them everywhere" if on
            else "Tooltips are off \u2014 click to show them again")
        if self._prefs.get("tooltips") != bool(on):
            self._prefs["tooltips"] = bool(on)
            _prefs_mod.save(self._prefs)
        if announce:
            self._status.showMessage(
                "Tooltips on" if on
                else "Tooltips off \u2014 the ? button turns them back on", 4000)

    # ------------------------------------------------------------------
    # Dark mode
    # ------------------------------------------------------------------

    def _refresh_theme_dependents(self):
        """Re-render everything that resolves theme colors — call after the
        mode, a viewport preset, or any token override changes."""
        dark = self._dark_mode
        QApplication.instance().setStyleSheet(theme.build_qss())
        _tb_px = theme.toolbar_icon_px()
        self._toolbar.setIconSize(QSize(_tb_px, _tb_px))
        bg = theme.color("canvas.bg")
        for ws in self._workspaces:
            ws.view.setBackgroundBrush(QBrush(QColor(bg)))
            ws.scene.set_dark_mode(dark)
            ws.const_guides.set_dark_mode(dark)
            ws.boxing_guide.set_dark_mode(dark)
            ws.stock_guide.set_dark_mode(dark)
            ws.pad_guide.set_dark_mode(dark)
            ws.edit_tool.refresh_theme()
            ws.view.refresh_face_marks()
        self._apply_toolbar_icons(dark)
        self._toolbar.set_dark(dark)  # overflow pop-out panel matches theme
        if getattr(self, "_snap_palette", None) is not None:
            self._snap_palette.apply_theme()
        self._refresh_layer_panel()   # eye/padlock icons are theme-colored
        self._update_readiness()      # dot colors are theme-aware

    def _toggle_dark_mode(self, dark: bool):
        self._dark_mode = dark
        theme.set_dark(dark)
        self._refresh_theme_dependents()
        self._save_prefs()

    # ------------------------------------------------------------------

    def _fit_rect(self, ws: "WorkspaceState") -> QRectF:
        """What Fit frames on *ws*: the drawing and the stock guide when it
        is shown, with a margin; the scene rectangle (the photo, or the
        default extents) when nothing is drawn. Fitting the 300 × 200 mm
        scene rectangle always left a 10 mm hinge 30 px wide on the Component
        tab, and a front at 45 % of the canvas."""
        content = ws.scene.geometry_rect()
        if content.isNull() or content.width() + content.height() < 1e-6:
            return ws.scene.sceneRect()
        content = content.united(ws.stock_guide.rect())
        m = 0.08 * max(content.width(), content.height(), 5.0)
        return content.adjusted(-m, -m, m, m)

    def _fit_view(self):
        self.view.fit_view(self._fit_rect(self._active_ws))
        self._update_info_label()


_CRASH_FP = None


def _install_crash_logger():
    """Record any fatal error to ~/.guilddraw/crash.log.

    Covers both a Python exception escaping a Qt slot/virtual (which PySide6
    routes through sys.excepthook, and may then abort) and a hard C-level fault
    — faulthandler writes on the signal at the C level, so a segfault that
    would otherwise vanish with unflushed buffers still leaves a trace. Cheap,
    always-on, and only writes when something goes wrong."""
    global _CRASH_FP
    import datetime
    import faulthandler
    import pathlib
    import traceback
    try:
        d = pathlib.Path.home() / ".guilddraw"
        d.mkdir(parents=True, exist_ok=True)
        _CRASH_FP = open(d / "crash.log", "a", buffering=1, encoding="utf-8")
        _CRASH_FP.write(
            f"\n=== session {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
            f"v{__version__} ===\n")
        _CRASH_FP.flush()
        faulthandler.enable(file=_CRASH_FP, all_threads=True)
    except Exception:
        _CRASH_FP = None

    _prev_hook = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            if _CRASH_FP is not None:
                _CRASH_FP.write(
                    f"\n--- unhandled exception "
                    f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
                traceback.print_exception(exc_type, exc, tb, file=_CRASH_FP)
                _CRASH_FP.flush()
        except Exception:
            pass
        _prev_hook(exc_type, exc, tb)

    sys.excepthook = _hook


def main():
    _install_crash_logger()
    app = QApplication(sys.argv)
    app.setApplicationName("GuildDraw")
    app.setApplicationDisplayName("GuildDraw")
    app.setOrganizationName("Guild of American Spectacle Makers")
    app.setStyleSheet(theme.build_qss())

    # Show the loading splash before building the (slower) main window, so the
    # maker sees the app is starting and doesn't re-launch a second copy.
    from .splash import make_splash
    splash = make_splash(app)

    win = MainWindow()
    win.show()
    splash.finish(win)   # dismiss once the window is up
    # Open a project passed on the command line (e.g. double-clicking a
    # .gdraw/.svg via the installed file association) — after the recovery
    # offer, not before: on its 400 ms timer the offer used to find the slot
    # already emptied by the open, and a crash's work was lost to a
    # double-click.
    target = next((a for a in app.arguments()[1:]
                   if not a.startswith("-") and os.path.isfile(a)), None)
    if target is not None and not win._offer_recovery(opening=target):
        win._open_path(target)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
