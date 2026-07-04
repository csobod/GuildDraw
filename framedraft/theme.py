"""Central theme palette — the single source of truth for GuildDraw colors.

Every color the app paints lives here as a named token with a (light, dark)
default pair. Painters query :func:`color` / :func:`layer_color` at
refresh/paint time, so switching modes or applying user overrides recolors
everything the next time it redraws — no widget holds a private palette.

User customization (Preferences ▸ Appearance / Layers & Colors) is stored as
``prefs["theme"] = {"light": {token: "#rrggbb"}, "dark": {...}}`` and applied
via :func:`set_overrides`. Tokens absent from the overrides fall back to the
defaults below, so new tokens in future versions always resolve.

Alpha-carrying colors use the ``#AARRGGBB`` form (QColor parses it natively).

Qt-free on purpose: everything returns/accepts plain hex strings so the token
logic is unit-testable without a QApplication.
"""
from __future__ import annotations

# token -> (light, dark)
_TOKENS: dict[str, tuple[str, str]] = {
    # ── UI chrome (drives the QSS template) ──────────────────────────────
    "chrome.bg":           ("#ffd580", "#1a1a1a"),
    "chrome.panel":        ("#fce9c2", "#2a2a2a"),
    "chrome.ink":          ("#1f1f1f", "#d4cfc0"),
    "chrome.border":       ("#d4a840", "#554433"),
    "chrome.hover":        ("#ffe9b8", "#3a3a3a"),
    "chrome.checked_bg":   ("#1f1f1f", "#d4cfc0"),
    "chrome.checked_ink":  ("#ffd580", "#1a1a1a"),
    "chrome.slider_hover": ("#555555", "#e8e0d0"),
    # ── Canvas / viewport ────────────────────────────────────────────────
    "canvas.bg":             ("#faf6ee", "#1e1e1e"),
    "canvas.cross":          ("#ccbbaa", "#554433"),
    "canvas.mirror_axis":    ("#c0392b", "#e05555"),
    "canvas.selection_halo": ("#82ff8c00", "#96ffaa3c"),   # amber glow, alpha
    # ── Geometry + editing dots ──────────────────────────────────────────
    "geometry.ink":           ("#1f1f1f", "#d4cfc0"),
    "geometry.node_fill":     ("#fce9c2", "#3a3020"),
    "geometry.node_hover":    ("#2e8b57", "#4aca7a"),
    "geometry.node_selected": ("#e74c3c", "#e74c3c"),
    "geometry.handle":        ("#2a7f9e", "#4ab8d8"),
    "geometry.handle_fill":   ("#dff0f7", "#1a3040"),
    # ── Guides ───────────────────────────────────────────────────────────
    "guide.construction": ("#2a7f9e", "#4ab8d8"),
    "guide.boxing":       ("#d35400", "#e8730a"),
    "guide.stock":        ("#27ae60", "#2ecc71"),
    "guide.pad":          ("#8e44ad", "#9b59b6"),
    "guide.dim":          ("#7a5c2e", "#7a5c2e"),
    "guide.dim_selected": ("#e67e22", "#e67e22"),
    # ── Snap indicator colors (mode-independent today) ───────────────────
    "snap.endpoint":     ("#2e8b57", "#2e8b57"),
    "snap.node":         ("#2e8b57", "#2e8b57"),
    "snap.handle":       ("#2a7f9e", "#2a7f9e"),
    "snap.mirror":       ("#c0392b", "#c0392b"),
    "snap.axis":         ("#7b5ea7", "#7b5ea7"),
    "snap.midpoint":     ("#e67e22", "#e67e22"),
    "snap.center":       ("#16a085", "#16a085"),
    "snap.quadrant":     ("#d4a840", "#d4a840"),
    "snap.intersection": ("#d35400", "#d35400"),
    "snap.curve":        ("#5d8aa8", "#5d8aa8"),
}

# Layers that own a distinct color; every other layer follows geometry.ink so
# the drawing reads as one ink except where a layer means something special.
_LAYER_DEFAULTS: dict[str, tuple[str, str]] = {
    "SCULPT":    ("#8e44ad", "#c39bd3"),   # purple — back-surface geometry
    "ENGRAVING": ("#16a085", "#48c9b0"),   # teal   — engraving marks
}

_dark: bool = False
_overrides: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
_dot_radius: int = 4          # node dot radius, screen px (handles are 1 less)

_MIN_DOT_R, _MAX_DOT_R = 2, 10


# ---------------------------------------------------------------------------
# Mode + overrides
# ---------------------------------------------------------------------------

def set_dark(dark: bool) -> None:
    global _dark
    _dark = bool(dark)


def is_dark() -> bool:
    return _dark


def set_overrides(theme_prefs: dict | None) -> None:
    """Install user overrides from ``prefs["theme"]`` (replaces the current
    set). Unknown tokens are kept — a future version may define them."""
    global _overrides
    theme_prefs = theme_prefs or {}
    _overrides = {
        "light": dict(theme_prefs.get("light") or {}),
        "dark":  dict(theme_prefs.get("dark") or {}),
    }


def overrides() -> dict:
    """Current overrides in the ``prefs["theme"]`` shape (copies)."""
    return {"light": dict(_overrides["light"]), "dark": dict(_overrides["dark"])}


def set_override(token: str, value: str | None, dark: bool | None = None) -> None:
    """Set (or clear with ``None``) one token override in one mode.

    ``dark=None`` targets the current mode."""
    mode = ("dark" if _dark else "light") if dark is None else \
           ("dark" if dark else "light")
    if value is None:
        _overrides[mode].pop(token, None)
    else:
        _overrides[mode][token] = value


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def color(token: str) -> str:
    """Resolved hex color for *token* in the current mode."""
    mode = "dark" if _dark else "light"
    ov = _overrides[mode].get(token)
    if ov:
        return ov
    try:
        pair = _TOKENS[token]
    except KeyError:
        raise KeyError(f"unknown theme token: {token!r}") from None
    return pair[1] if _dark else pair[0]


def default_color(token: str, dark: bool) -> str:
    """Factory default for *token* (ignores overrides) — for the prefs UI."""
    pair = _TOKENS[token]
    return pair[1] if dark else pair[0]


def layer_color(layer) -> str:
    """Resolved color for a document Layer (enum or name string).

    Order: user override for ``layer.<NAME>`` → the layer's own default
    (SCULPT/ENGRAVING) → the shared ``geometry.ink``."""
    name = getattr(layer, "value", str(layer))
    mode = "dark" if _dark else "light"
    ov = _overrides[mode].get(f"layer.{name}")
    if ov:
        return ov
    pair = _LAYER_DEFAULTS.get(name)
    if pair:
        return pair[1] if _dark else pair[0]
    return color("geometry.ink")


def default_layer_color(layer, dark: bool) -> str:
    """Factory default for a layer's color (ignores overrides)."""
    name = getattr(layer, "value", str(layer))
    pair = _LAYER_DEFAULTS.get(name)
    if pair:
        return pair[1] if dark else pair[0]
    return default_color("geometry.ink", dark)


# ---------------------------------------------------------------------------
# Viewport presets (Preferences ▸ Appearance)
#
# A preset overlays the three viewport tokens in BOTH modes, so the canvas
# looks the same whichever UI mode is active; "auto" clears the overlay and
# the canvas follows the UI theme again. "custom" derives a legible ink and
# cross from the chosen background's luminance.
# ---------------------------------------------------------------------------

_VIEWPORT_TOKENS = ("canvas.bg", "geometry.ink", "canvas.cross")

VIEWPORT_PRESETS: dict[str, dict[str, str]] = {
    "parchment": {"canvas.bg": "#faf6ee", "geometry.ink": "#1f1f1f",
                  "canvas.cross": "#ccbbaa"},
    "blueprint": {"canvas.bg": "#16324f", "geometry.ink": "#dce8f2",
                  "canvas.cross": "#3a5a78"},
    "matte":     {"canvas.bg": "#1e1e1e", "geometry.ink": "#d4cfc0",
                  "canvas.cross": "#554433"},
    "white":     {"canvas.bg": "#ffffff", "geometry.ink": "#1f1f1f",
                  "canvas.cross": "#d8d8d8"},
}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 8:          # #AARRGGBB
        h = h[2:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luminance(hex_color: str) -> float:
    r, g, b = _rgb(hex_color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _mix(a: str, b: str, t: float) -> str:
    """Blend color *a* toward *b* by t in [0, 1]."""
    ar, ag, ab_ = _rgb(a)
    br, bg, bb = _rgb(b)
    return "#{:02x}{:02x}{:02x}".format(
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab_ + (bb - ab_) * t))


def apply_viewport(preset: str | None, custom_bg: str | None = None) -> None:
    """Overlay (or clear, for "auto") the viewport tokens in both modes."""
    for dark in (False, True):
        for tok in _VIEWPORT_TOKENS:
            set_override(tok, None, dark=dark)
    if preset in (None, "", "auto"):
        return
    if preset == "custom":
        bg = custom_bg or default_color("canvas.bg", False)
        ink = "#d4cfc0" if _luminance(bg) < 0.5 else "#1f1f1f"
        vals = {"canvas.bg": bg, "geometry.ink": ink,
                "canvas.cross": _mix(bg, ink, 0.25)}
    else:
        vals = VIEWPORT_PRESETS.get(preset)
        if vals is None:
            return
    for dark in (False, True):
        for tok, v in vals.items():
            set_override(tok, v, dark=dark)


# ---------------------------------------------------------------------------
# Editing-dot size (4K/accessibility; exposed in Preferences ▸ Appearance)
# ---------------------------------------------------------------------------

def dot_radius() -> int:
    return _dot_radius


def set_dot_radius(px: int) -> None:
    global _dot_radius
    _dot_radius = max(_MIN_DOT_R, min(_MAX_DOT_R, int(px)))


# ---------------------------------------------------------------------------
# Application stylesheet — ONE template rendered from the chrome tokens
# (replaces the former hardcoded QSS / QSS_DARK string pair in app.py)
# ---------------------------------------------------------------------------

_QSS_TEMPLATE = """
QMainWindow, QWidget {
    background-color: %(bg)s;
    color: %(ink)s;
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QToolBar {
    background-color: %(bg)s;
    border: none;
    spacing: 2px;
    padding: 4px;
}
QToolButton, QPushButton {
    background-color: %(panel)s;
    border: 1px solid %(btn_border)s;
    border-radius: 4px;
    color: %(ink)s;
}
QToolButton { padding: 5px; min-width: 30px; }
QPushButton { padding: 4px 10px; min-width: 54px; }
QToolButton:hover, QPushButton:hover { background-color: %(hover)s; }
QToolButton:checked, QPushButton:checked { background-color: %(checked_bg)s; color: %(checked_ink)s; }
QToolBar::separator { background: %(border)s; width: 1px; margin: 4px 3px; }
QStatusBar {
    background-color: %(bg)s;
    border-top: 1px solid %(border)s;
}
QMenuBar { background-color: %(bg)s; color: %(ink)s; }
QMenuBar::item:selected { background-color: %(panel)s; }
QMenu { background-color: %(panel)s; color: %(ink)s; border: 1px solid %(menu_border)s; }
QMenu::item:selected { background-color: %(checked_bg)s; color: %(checked_ink)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 2px 6px; }
QDockWidget { background-color: %(bg)s; }
QDockWidget::title {
    background-color: %(dock_title)s;
    padding: 4px 6px;
    font-weight: bold;
}
QGroupBox {
    border: 1px solid %(border)s;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    background-color: %(bg)s;
}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background-color: %(panel)s;
    border: 1px solid %(border)s;
    border-radius: 3px;
    padding: 2px 4px;
    color: %(ink)s;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: %(focus_border)s; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: %(panel)s;
    border: 1px solid %(menu_border)s;
    selection-background-color: %(checked_bg)s;
    selection-color: %(checked_ink)s;
}
QSlider::groove:horizontal {
    border: 1px solid %(border)s;
    height: 4px;
    background: %(panel)s;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: %(checked_bg)s;
    border: 1px solid %(checked_bg)s;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: %(slider_hover)s; }
QTabWidget::pane { border-top: 1px solid %(border)s; }
QTabBar::tab {
    background: %(panel)s;
    color: %(ink)s;
    border: 1px solid %(border)s;
    border-bottom: none;
    padding: 5px 8px;
    min-width: 40px;
}
QTabBar::tab:selected { background: %(bg)s; font-weight: bold; }
QTabBar::tab:hover:!selected { background: %(hover)s; }
"""


def build_qss() -> str:
    """Render the application stylesheet for the current mode + overrides."""
    ink    = color("chrome.ink")
    border = color("chrome.border")
    # Historical light theme drew button/menu borders and the focus ring in
    # ink (not the softer border color) and titled docks with the border
    # color; dark theme used its border color throughout. Preserve that.
    dark = is_dark()
    return _QSS_TEMPLATE % {
        "bg":           color("chrome.bg"),
        "panel":        color("chrome.panel"),
        "ink":          ink,
        "border":       border,
        "hover":        color("chrome.hover"),
        "checked_bg":   color("chrome.checked_bg"),
        "checked_ink":  color("chrome.checked_ink"),
        "slider_hover": color("chrome.slider_hover"),
        "btn_border":   border if dark else ink,
        "menu_border":  border if dark else ink,
        "focus_border": ink,
        "dock_title":   color("chrome.panel") if dark else border,
    }
