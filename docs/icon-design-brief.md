# GuildDraw — Icon Design Brief

**Project:** GuildDraw v0.9+  
**Purpose:** Replace text labels on the left vertical toolbar with 20×20 px SVG icons.  
**Deliverable:** One SVG file per icon, named exactly as listed in §3.  
**Format:** Square SVG viewport, 20×20 or 24×24 (consistent across set).

---

## 1. Style guidelines

| Property | Spec |
|---|---|
| Style | Outline / line icon — **not** filled silhouettes |
| Stroke weight | 1.5–2 px (at 20×20 native size) |
| Corner radius | Rounded joins and caps (`stroke-linecap: round; stroke-linejoin: round`) |
| Palette | Single colour: use **currentColor** so Qt's QSS can tint the icon for normal / checked / hover / disabled states |
| Background | Transparent |
| Grid | 20×20 px, 1 px safe margin on each side (live area 18×18) |
| Optical weight | All icons should feel the same visual weight at a glance — avoid very sparse vs very dense icons in the same set |

**Two-state icons** (toggles that can be checked ON or OFF) do **not** need separate checked/unchecked artwork — Qt applies a tint via QSS. However, note which icons are toggles so the designer can ensure the artwork reads clearly both tinted and untinted.

---

## 2. Colour / dark-mode compatibility

All icons use `currentColor`. The app has a light theme (`#1f1f1f` text on `#ffd580` amber background) and a dark theme (`#d4cfc0` text on `#1a1a1a` background). Icons must read clearly in both. Avoid detail that disappears at low contrast — keep geometry simple and bold enough to hold up at ~1.5× stroke weight in the dark theme.

---

## 3. Icon inventory

### 3a. Drawing tools (mutually exclusive — radio group)

| Filename | Label | Description |
|---|---|---|
| `tool-select.svg` | Select | Standard arrow cursor pointing upper-left. Clean, no shadow. |
| `tool-line.svg` | Line | Two or three short straight segments connected at sharp angles (polyline). No curve. |
| `tool-spline.svg` | Spline | A single smooth S-curve or arc. Optionally show one pair of Bézier tangent handles (small circles at handle endpoints). |
| `tool-circle.svg` | Circle | Unfilled circle with a small centre dot or crosshair. |
| `tool-arc.svg` | Arc | A partial circle arc, roughly 240° open at top-right. A small centre dot at the implied arc centre. |
| `tool-dim.svg` | Dim | A horizontal dimension line with short tick marks at each end and a small gap in the centre (where a measurement label would go). Arrows optional. |

### 3b. View toggles (independent checkboxes)

| Filename | Label | Description |
|---|---|---|
| `toggle-mirror.svg` | Mirror | A vertical dashed centre line with a simple shape (e.g. half-arc) on the left and its mirrored ghost on the right. |
| `toggle-guides.svg` | Guides | Two or three thin diagonal construction lines crossing, reminiscent of drafting guide marks. |
| `toggle-snap.svg` | Snap | A magnet — classic horseshoe magnet shape, or a small magnet attracting a node dot. |
| `toggle-smooth.svg` | Smooth Handles | A node dot on a curve with a tangent handle line extending both ways (symmetric handle), representing tangent-lock / smooth Bézier mode. |
| `toggle-boxing.svg` | Boxing | A small rectangle inscribed with two dimension tick marks — one for A (width) and one for B (height). Think "lens boxing rectangle". |
| `toggle-stock.svg` | Stock | A plain rectangle outline, slightly wider than tall, representing the raw stock blank. Corner marks or dashed border optional. |
| `toggle-pad.svg` | Pad | A square or near-square rectangle outline, slightly different weight or corner style to distinguish from Stock. |

### 3c. Operation buttons (one-shot actions)

| Filename | Label | Description |
|---|---|---|
| `op-mirror-close.svg` | Mirror Close | Two open half-curves on either side of a centre axis, with a node at the top and bottom touching the axis — indicating the operation that merges them into a closed shape. |
| `op-join.svg` | Join | Two open curve endpoints moving toward each other with a small connection indicator (e.g. overlapping circles or a link symbol). |
| `op-snap-node.svg` | Snap Node | A node dot with a dashed circle "snap ring" around it and an arrow pointing toward a nearby endpoint on another curve. |
| `op-split.svg` | Split | A single curve with a visible node in the middle, and two short outgoing arrows suggesting the curve is being broken at that node. Scissors optional. |
| `op-explode.svg` | Explode | Three or four short line segments radiating outward from a central point, suggesting a curve bursting into individual segments. |
| `op-fit.svg` | Fit | The standard "fit to view" icon — four corner arrows pointing inward toward a small central rectangle, or outward from it. |

### 3d. View / window button

| Filename | Label | Description |
|---|---|---|
| `view-sidebar.svg` | Toggle Sidebar | A layout icon: a tall narrow rectangle on the right (representing the panel) beside a wider rectangle (the canvas). A small left-arrow or collapse indicator on the panel edge. |

---

## 4. Sizing and delivery

- **Native size:** 20×20 px SVG (or 24×24 — must be consistent across the set)
- **No embedded raster content** — pure vector paths only
- **No `width`/`height` attributes** on the `<svg>` root, only `viewBox="0 0 20 20"` — Qt scales via QIcon
- Use `currentColor` for all strokes/fills so Qt QSS tinting works
- Name files exactly as in §3 — the implementation will load them by name from `framedraft/resources/icons/`
- Deliver as individual `.svg` files (not a sprite sheet)

---

## 5. Reference / inspiration

These libraries use the correct outline-icon style and can serve as reference or sources for the generic icons (cursor, circle, scissors, magnet, fit-to-view):

- **Phosphor Icons** — phosphoricons.com — `regular` weight, excellent coverage, MIT
- **Feather Icons** — feathericons.com — minimal, consistent weight
- **Material Symbols (Outlined)** — fonts.google.com/icons — weight 200–300 is closest to this spec

The specialized icons (spline, mirror-close, boxing guide, smooth handles, explode) are unlikely to exist in any library and will need to be drawn from scratch per §3.

---

## 6. Qt integration notes (for the developer, not the designer)

Icons will be loaded via:

```python
from PySide6.QtGui import QIcon
QAction("", self)
action.setIcon(QIcon(":/icons/tool-select.svg"))  # Qt resource system
# or: QIcon(str(Path(__file__).parent / "resources/icons/tool-select.svg"))
```

`QToolButton` text will be cleared (`action.setText("")`). Tooltips will be set via `action.setToolTip(...)` — these already exist in the codebase for most actions.

QSS tinting for checked state (already in app QSS):
```css
QToolButton:checked { background-color: #1f1f1f; color: #ffd580; }
```
Because icons use `currentColor`, a checked button will render its icon in `#ffd580` (amber) on a dark background — automatic visual feedback without separate artwork.

Icon size set on the toolbar:
```python
toolbar.setIconSize(QSize(20, 20))
```
