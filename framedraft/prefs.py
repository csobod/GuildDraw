"""
Persistent user preferences — stored in ~/.guilddraw/prefs.json.

All keys are listed in DEFAULTS.  load() merges saved data over defaults so
future versions that add new keys always have a valid value.
"""

import json
import pathlib

_DIR  = pathlib.Path.home() / ".guilddraw"
_FILE = _DIR / "prefs.json"

DEFAULTS: dict = {
    # Appearance
    "dark_mode":            False,
    # Recently opened files (most recent first)
    "recent_files":         [],
    # Drawing
    "default_line_weight":  1.5,
    # Toolbar overflow ("⋯") pop-out pinned open across operations
    "toolbar_pinned":       False,
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
    # Pad block reference guide (centered at origin)
    "pad_on_startup":       True,
    "pad_width_mm":         45.0,
    "pad_height_mm":        45.0,
    # PNG export resolution (true print scale: pixels = mm · dpi / 25.4)
    "png_export_dpi":       600,
    # PDF-for-Catalog export (front + both temples on one printable sheet)
    "catalog_pdf": {
        "paper":         "a5",            # "a5" | "half_letter"
        "line_weight_mm": 0.6,            # uniform weight (catalog + 1:1 PDF/print)
        "caption":       True,            # print the design file name
        "caption_font":  "Courier New",   # monospace default
        "show_scale":    False,           # print a scale note (off = true A5 scale)
        # Vertical shift (mm) of the drawing content only — the caption stays
        # put. Lets a maker clear a binding/spine margin. + = down, − = up.
        "content_offset_mm": 0.0,
        "front_layers":  ["OUTLINE", "LENS"],
        "temple_layers": ["OUTLINE"],
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
        "mirror":       True,   # Mirror (bake operation)
        "mirror_close": False,  # hidden by default
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
        "bookmark":     "Ctrl+B",
        # Types "□" into the focused text field — frame-size notation
        # A□DBL-TempleLength in bookmark names, filenames, engravings.
        "insert_square": "Ctrl+Shift+B",
    },
}


def load() -> dict:
    """Return prefs dict, merged with DEFAULTS so all keys are present."""
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            merged = {**DEFAULTS, **data}
            # Deep-merge nested dicts so new default keys survive old prefs
            # files. EVERY nested dict pref must be listed here — a missing
            # entry means old files silently clobber new defaults.
            for key in ("toolbar", "hotkeys", "theme", "viewport",
                        "snap_types", "catalog_pdf"):
                if isinstance(data.get(key), dict):
                    merged[key] = {**DEFAULTS[key], **data[key]}
                else:
                    merged[key] = dict(DEFAULTS[key])
            return merged
    except Exception:
        pass
    return dict(DEFAULTS)


def save(prefs: dict) -> None:
    """Write prefs dict to disk.  Silently ignores write errors."""
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass
