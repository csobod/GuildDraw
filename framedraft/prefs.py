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
    # Boxing guide
    "boxing_on_startup":    True,
    "boxing_a_mm":          50.0,
    "boxing_b_mm":          30.0,
    "boxing_dbl_mm":        18.0,
    # Stock blank reference guide (centered at origin)
    "stock_on_startup":     False,
    "stock_width_mm":       170.0,
    "stock_height_mm":      85.0,
    # Pad block reference guide (centered at origin)
    "pad_on_startup":       False,
    "pad_width_mm":         45.0,
    "pad_height_mm":        45.0,
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
        "point_move":   True,
        "text":         True,
        "ghost":        True,   # Ghost (mirror-axis toggle)
        "guides":       True,
        "snap":         True,
        "snap_palette": True,
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
    # Snap palette: per-type toggles ({snap type key: bool}; keys from
    # canvas.snapping.SNAP_TYPES — absent keys default to enabled)
    "snap_types": {},
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
        "point_move":   "G",
        "text":         "I",
        "snap_node_ep": "E",
        "move_gizmo":   "M",
        "join":         "J",
        "bookmark":     "Ctrl+B",
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
                        "snap_types"):
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
