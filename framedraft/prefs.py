"""
Persistent user preferences — stored in ~/.guilddraw/prefs.json.

All keys are listed in DEFAULTS.  load() merges saved data over defaults so
future versions that add new keys always have a valid value.
"""

import copy
import datetime
import json
import math
import os
import pathlib

_DIR  = pathlib.Path.home() / ".guilddraw"
_FILE = _DIR / "prefs.json"

DEFAULTS: dict = {
    # Appearance
    "dark_mode":            False,
    # Recently opened files (most recent first)
    "recent_files":         [],
    # The folders the file dialogs last used: for designs and exports, and
    # for reference images ("": beside the open design, else home).
    "last_dir":             "",
    "last_image_dir":       "",
    # Explain what storing a reference image in the design does before the
    # paperclip stores one (the box's "Don't ask again" clears it;
    # Preferences ▸ General ▸ Prompts sets it back).
    "prompt_store_image":   True,
    # Drawing
    "default_line_weight":  1.5,
    # Toolbar overflow ("⋯") pop-out pinned open across operations
    "toolbar_pinned":       False,
    # Tooltips shown app-wide (the ? at the foot of the toolbar)
    "tooltips":             True,
    # Startup toggle states for toolbar buttons
    "mirror_on_startup":    True,
    "guides_on_startup":    True,
    "snap_on_startup":      True,
    "smooth_handles":       True,
    # Boxing guide (defaults mirror the maintainer's working setup — rc3a)
    "boxing_on_startup":    False,
    "boxing_a_mm":          49.0,
    "boxing_b_mm":          27.0,
    "boxing_dbl_mm":        18.0,
    # Stock blank reference guide (centered at origin)
    "stock_on_startup":     True,
    "stock_width_mm":       170.0,
    "stock_height_mm":      85.0,
    # The temple blank (both temple tabs; length × width, centered at origin,
    # the core line along its middle). GuildModel's default temple blank.
    "temple_stock_width_mm":  170.0,
    "temple_stock_height_mm": 30.0,
    # Pad block reference guide (centered at origin)
    "pad_on_startup":       True,
    "pad_width_mm":         45.0,
    "pad_height_mm":        45.0,
    # Lens Fill overlay: opacity a freshly-shown lens tint starts at (percent).
    # Colors are per-document and live in the .gdraw; only the strength of the
    # tint is a working preference — it depends on the maker's screen and on
    # whether they draw over a face photo.
    "lens_fill_opacity_pct": 65,
    # …and the tint depth it starts at. 1.0 is a picked color exactly as
    # picked; reference swatches are published light, so a maker who always
    # deepens can make that their starting point (see scene.deepen_tint).
    "lens_fill_intensity":   1.0,
    # Inlay Fill overlay (2.0): the color and opacity a fresh inlay fill
    # starts at. The fill itself, image and tumble included, lives in the
    # .gdraw per workspace.
    "inlay_fill_color":       "#3fb0a5",
    "inlay_fill_opacity_pct": 85,
    # PNG export resolution (true print scale: pixels = mm · dpi / 25.4)
    "png_export_dpi":       600,
    # PDF-for-Catalog export (front + both temples on one printable sheet)
    "catalog_pdf": {
        "paper":         "a5",            # "a5" | "half_letter"
        "line_weight_mm": 0.6,            # uniform weight (catalog + 1:1 PDF/print)
        "caption":       True,            # print the design file name
        "caption_font":  "Courier New",   # monospace default
        "show_scale":    False,           # print a scale note (off = true A5 scale)
        # Print the display-only Frame Fill / Lens Fill overlays under the line
        # work, exactly as the canvas shows them. Off = line work only, which
        # is what a cutting-room sheet wants; on is for a showroom page.
        "include_fill":  False,
        # Vertical shift (mm) of the drawing content only — the caption stays
        # put. Lets a maker clear a binding/spine margin. + = down, − = up.
        "content_offset_mm": 0.0,
        "front_layers":  ["OUTLINE", "LENS"],
        "temple_layers": ["OUTLINE"],
    },
    # File ▸ Export ▸ Catalog PDFs for a Folder…: what the last run used
    # (export/batch_catalog.py). The folder is picked each time; this is the
    # starting point for the picker and the options.
    "batch_catalog": {
        "library":          "",
        "out":              "",          # empty = <library>/catalog
        "color":            "#000000",
        "opacity_pct":      100,
        "save_fill":        True,
        "temple_ghost_off": False,
        "inlay_fill":        False,      # set the Inlay Fill too
        "inlay_color":       "#3fb0a5",
        "inlay_opacity_pct": 85,
    },
    # Print Front + Temples: 1:1 cutting templates on the maker's own paper
    # (File ▸ Print Front + Temples… / Export ▸ PDF Front + Temples…).
    "template_print": {
        "paper":          "letter",   # key in export.template_print.PAPER_SIZES
        "orientation":    "auto",     # auto | portrait | landscape
        "line_weight_mm": 0.35,       # a fine saw-line; 0.6 matches the catalog
        "labels":         True,       # name each piece (Frame Front, Temple R…)
    },
    # Toolbar button visibility (False = hidden; action still works via hotkey)
    "toolbar": {
        "select":       True,   # always visible; checkbox disabled in dialog
        "line":         True,
        "spline":       True,
        "circle":       True,
        "arc":          True,
        "arc_sec":      True,
        "fillet":       True,
        "dim":          True,
        "trim":         True,
        "split_curve":  True,
        "offset":       True,
        "rebuild":      True,
        "point_move":   True,
        "text":         True,
        "ghost":        True,   # Ghost (mirror-axis toggle)
        "guides":       True,
        "snap":         True,
        "snap_palette": True,
        "grid":         True,
        "smooth":       True,
        "boxing":       True,
        "stock":        True,
        "pad":          True,
        "obverse":      True,   # View Obverse (the drawing's other face)
        "mirror":       True,   # Mirror (bake operation)
        # Shown since 2.0: a whole outline is drawn as a half and closed
        # across the axis, and the messages point to it.
        "mirror_close": True,
        "copy_temple":  True,   # Mirror Copy (temple R ↔ L)
        "join":         True,
        "snap_node":    True,
        "split":        True,
        "explode":      True,
        "fit":          True,
    },
    # Theme color overrides — {"light": {token: "#rrggbb"}, "dark": {...}};
    # tokens resolve via framedraft.theme (absent tokens use its defaults)
    "theme": {},
    # Viewport appearance (Preferences ▸ Appearance)
    "viewport": {
        "preset":    "auto",      # auto|parchment|blueprint|matte|white|custom
        "custom_bg": "#faf6ee",   # canvas color when preset == "custom"
        "vignette":  0,           # 0–100 edge-darkening intensity
    },
    # The Properties dock's folded sections, by title (Road to 2.0, item 5,
    # GuildModel's "dock_folds"): {"Lens Fill": false, ...}. Only the ones
    # turned from how they open are listed.
    "dock_folds": {},
    # Node/handle editing-dot radius in screen px (theme.dot_radius)
    "dot_radius_px": 4,
    # Compact toolbar: tight button padding + slightly smaller icons
    "compact_toolbar": False,
    # Grid overlay (viewport aid; global across workspaces).
    # Standard grid: 2 mm spacing, major line every 5th = every 10 mm.
    "grid_visible":     False,
    "grid_spacing_mm":  2.0,
    "grid_major":       5,       # every Nth line is a major (heavier) line
    "grid_minor_color": "",      # "" = follow the theme (canvas.grid_minor)
    "grid_major_color": "",      # "" = follow the theme (canvas.grid_major)
    "grid_major_width_px": 1.0,  # major line weight (device px, cosmetic)
    # Snap palette: per-type toggles (keys from canvas.snapping.SNAP_TYPES;
    # absent keys default to enabled). This shipped set is the maintainer's
    # working palette: precise point targets on, the "grabby" ones (node,
    # center, on-curve, intersection) off until the maker opts in.
    "snap_types": {
        "endpoint":      True,
        "node":          False,
        "midpoint":      True,
        "center":        False,
        "quadrant":      True,
        "intersection":  False,
        "tangent":       True,
        "perpendicular": True,
        "handle":        True,
        "curve":         False,
        "grid":          True,
        "mirror":        True,
        "axis":          True,
    },
    # Snap reach in screen pixels
    "snap_radius_px": 10,
    # User-assignable hotkeys (empty string = no hotkey)
    "hotkeys": {
        "line":         "L",
        "spline":       "S",
        "circle":       "C",
        "arc":          "A",
        "arc_sec":      "",     # no default (A is taken); assign in Settings
        "fillet":       "F",
        "dim":          "D",
        "trim":         "T",
        "split_curve":  "X",
        "offset":       "O",
        "rebuild":      "R",
        "point_move":   "G",
        "text":         "I",
        "snap_node_ep": "E",
        "move_gizmo":   "M",
        "join":         "J",
        "obverse":      "V",
        "bookmark":     "Ctrl+B",
        # Types "□" into the focused text field — frame-size notation
        # A□DBL-TempleLength in bookmark names, filenames, engravings.
        "insert_square": "Ctrl+Shift+B",
    },
}


# Set by load() when the file could not be read: what to tell the maker, once.
LOAD_NOTE: str | None = None


def _fits(default, value):
    """*value* as the kind *default* is, or the _MISSING marker when it is
    not one: a bool for a bool, a finite number (not a bool) for a number, a
    string for a string, a list for a list. One wrong-typed value ("170" for
    a guide width, "false" for a switch) stopped GuildDraw from starting,
    on every launch, until the file was deleted by hand."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else _MISSING
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _MISSING
        if not math.isfinite(value):
            return _MISSING
        if isinstance(default, int):
            return int(value) if float(value).is_integer() else _MISSING
        return float(value)
    if isinstance(default, str):
        return value if isinstance(value, str) else _MISSING
    if isinstance(default, list):
        if not isinstance(value, list):
            return _MISSING
        kinds = {type(x) for x in default}
        if len(kinds) == 1:                   # a list of strings stays one
            (kind,) = kinds
            return [x for x in value if type(x) is kind]
        return value
    if isinstance(default, dict):
        return _merged(default, value) if isinstance(value, dict) else _MISSING
    return value


_MISSING = object()


def _merged(defaults: dict, data: dict) -> dict:
    """*defaults* with each value of *data* that fits its kind (_fits); a key
    the defaults do not have (a later GuildDraw's) is kept as it is."""
    out = copy.deepcopy(defaults)
    for key, value in data.items():
        if key in defaults:
            got = _fits(defaults[key], value)
            if got is not _MISSING:
                out[key] = got
        else:
            out[key] = value
    return out


def _keep_damaged() -> str | None:
    """Move a prefs file that does not read aside, so the defaults written
    over it at the next save do not destroy it. Returns its new name."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    aside = _FILE.with_name(f"{_FILE.name}.damaged-{stamp}")
    try:
        os.replace(_FILE, aside)
        return aside.name
    except OSError:
        return None


def load() -> dict:
    """Return prefs dict, merged with DEFAULTS so all keys are present."""
    # Always hand out a deep copy: the live prefs get mutated in place (lists
    # of recent files, nested export dicts), and a shallow copy would alias
    # those nested objects to DEFAULTS itself — a fresh install then rewrites
    # the shipped defaults for the rest of the process.
    global LOAD_NOTE
    LOAD_NOTE = None
    if not _FILE.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        # utf-8-sig: an editor's byte-order mark made the file unreadable.
        data = json.loads(_FILE.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError):
        # A file cut short (a full disk, a power cut mid-write) or damaged:
        # the defaults for now, the file kept aside rather than overwritten
        # at the next save, as every setting was.
        aside = _keep_damaged()
        LOAD_NOTE = ("Your preferences could not be read, so GuildDraw started "
                     "from its defaults."
                     + (f" The damaged file is kept beside it as {aside}." if aside
                        else ""))
        return copy.deepcopy(DEFAULTS)
    merged = _merged(DEFAULTS, data)
    _rename_layers(merged)
    return merged


def _rename_layers(prefs: dict) -> None:
    """Layer names saved before 2.0, read under the names since, in place:
    HINGE became COMPONENT (document.LAYER_ALIASES). A layer color the maker
    set, and the catalog's layer choices, carry over; the next save writes
    the new names."""
    from .document import LAYER_ALIASES
    for mode in ("light", "dark"):
        tokens = prefs.get("theme", {}).get(mode)
        if not isinstance(tokens, dict):
            continue
        for old, new in LAYER_ALIASES.items():
            if f"layer.{old}" in tokens:
                tokens.setdefault(f"layer.{new}", tokens[f"layer.{old}"])
                del tokens[f"layer.{old}"]
    cat = prefs.get("catalog_pdf", {})
    for key in ("front_layers", "temple_layers"):
        if isinstance(cat.get(key), list):
            cat[key] = list(dict.fromkeys(LAYER_ALIASES.get(n, n) for n in cat[key]))


def save(prefs: dict) -> None:
    """Write prefs dict to disk.  Silently ignores write errors.

    Through a temporary file and one replace: written in place, a save that
    failed after the truncate (a full disk, a power cut) left an empty file,
    and the next start lost every setting."""
    tmp = _FILE.with_name(_FILE.name + ".tmp")
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(prefs, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _FILE)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
