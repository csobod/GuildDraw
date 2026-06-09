# BUILDPLAN.md — GuildDraw

A focused, open-source 2D drafting application for acetate / horn eyewear design.
Built on Python + PySide6 (Qt 6). Single purpose: give a maker all the tools to
draw a frame half, mirror it, verify it against a face photo, and export clean DXF
for GuildCAM — and nothing else.

> **Integration status:** GuildCAM intake questions resolved against GuildCAM
> source, Session 5 (2026-06-04). See §4, §6, §8a, and §13.

---

## Current Implementation Status *(updated 2026-06-09)*

### What is fully working

| Feature | Notes |
|---|---|
| Line & spline drawing | Click-to-place nodes; double-click or Enter to finish; click first node to close |
| Node / handle editing | Drag NodeDots to move on-curve points; drag HandleDots to adjust Bézier tangents |
| Node insert | Double-click a curve segment to insert a node (de Casteljau split for splines) |
| Node delete | Click a NodeDot to select it (red highlight), then Del removes it |
| Smooth handle mode | "Smooth Handles" toggle mirrors opposite handle through the node (Fusion 360-style tangent lock) |
| Snapping | 10 px radius; snaps to: all curve nodes and control points, in-progress draw nodes, mirror axis, origin (0,0), line segment midpoints, circle/arc quadrant points and arc endpoints |
| Endpoint drag-snap | Drag a NodeDot near another open curve's endpoint to snap to it (orange ring indicator); Ctrl suspends; respects global Snap toggle |
| Mirror display | Live dotted ghost of the OD half reflected about the vertical axis |
| Mirror Close | Combines selected open half-curve + its mirror image into a single closed shape |
| Join | Greedy chain-join of 2+ selected curves at their nearest endpoints (2 mm tolerance); handles mixed line/spline; auto-detects closed result |
| Multi-select | Ctrl/Shift click; rubber-band drag over empty canvas (RubberBandDrag mode) |
| Dimension lines | Two-click snap-aware annotation; label in mm; draggable offset; selectable/deletable; persisted in SVG. |
| Construction guides | Bridge-angle + apical-radius + arm-spread + arm-drop guides (toggleable, dark-mode aware) |
| Boxing Guide | A×B lens box with DBL separation overlay (toggled, driven by Properties panel) |
| Stock Blank guide | Green dashed rectangle centered at origin; default 170×85 mm; configurable in side panel and Settings; startup toggle |
| Pad Block guide | Purple dashed rectangle centered at origin; default 45×45 mm; configurable in side panel and Settings; startup toggle |
| Persistent preferences | `~/.guilddraw/prefs.json` — persists dark mode, all startup toggle states, boxing/stock/pad dimensions, default line weight; merged over DEFAULTS on load |
| Face image | Load JPEG/PNG background, adjust opacity and rotation |
| Calibration | 2-point px-per-mm calibration, or direct numeric entry |
| Layers | OUTLINE / LENS / BRIDGE / HINGE / REF — assigned per-curve, shown in Properties panel |
| Line weight | Per-curve cosmetic weight; default set via Settings > Preferences |
| Dark mode | Full dark theme; toggled via Settings menu or Preferences dialog; persists across restarts |
| Settings dialog | Scrollable; sections: Appearance, Drawing, Startup Toggles (7 checkboxes), Boxing Guide dimensions, Stock Blank dimensions, Pad Block dimensions |
| Undo / Redo | Snapshot-based (deep copy of curve list); 100-step stacks; Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z |
| Revision Timeline | Named bookmark History tab in sidebar; Bookmark / Restore / Rename / Delete; persisted in SVG metadata; View → Revision History jumps straight to the tab |
| Icon toolbar | All 20 toolbar actions use `currentColor` SVGs rendered per-theme (`_make_icon`); `ToolButtonIconOnly` style; compact 30 px buttons; styled amber/dark separators; icons re-rendered when dark mode is toggled |
| Tabbed sidebar | Right sidebar reorganised into 4 tabs — **Properties** (layer + weight), **Guides** (construction/forming, boxing, stock, pad), **Canvas** (face image + calibration), **History** (revision bookmarks, with live count badge) |
| Status bar indicator | Permanent right-side label showing `LAYER \| ZOOM%`; updates on layer change, curve selection, wheel zoom, and Fit |
| SVG save / load | Native format; full round-trip including bookmarks, dims, forming metadata, calibration, face image reference |
| Trim tool | Cursor tool: hover to highlight (amber), click a curve to remove the segment between its nearest intersections with all other curves; works on open, closed, circle, and arc curves; stays active for successive trims; Esc returns to Select |
| Split tool | Cursor tool: click anywhere on a curve to split it into two open curves; snaps to intersections within 1.5 mm and splits both curves simultaneously; stays active; Esc to exit |
| Offset tool | Cursor tool (O): select a curve, type offset distance (mm), live amber preview, Enter confirms; miter join for lines (bevel fallback), averaged-normal + Catmull-Rom recompute for splines, analytical radius ± d for circles/arcs; Esc cancels |
| Move gizmo | Hotkey M: four-arrow gizmo at selection centre; drag arrow to translate along that axis; click arrow to type exact distance; Esc or M dismisses |
| Point Move tool | Hotkey G: two-click precise translate — click grab point (snapped), then click destination or type X/Y in HUD; selection moves so grab lands on destination; Esc cancels |
| Mirror (bake) | Toolbar action: creates real mirrored copies of selected curves opposite the mirror axis; turns off live ghost so export does not double-mirror; use Join or Mirror-Close afterward to close shapes |
| Tabbed workspaces | Three independent canvases: Frame Front, Temple, Hinge Pocket; each has its own scene, document, undo/redo stack, snap engine, and tool instances; sidebar reconfigures on tab switch (layer list, guide sections, library buttons) |
| Hinge pocket library | 5th sidebar tab (Library): browse ~/.guilddraw/library/hinges/*.svg; Import into any workspace (centered at origin); Save/Rename/Delete visible in Hinge Pocket workspace only |
| Toolbar + hotkeys | Settings dialog Toolbar tab: per-button visibility (mirror_close hidden by default); Hotkeys tab: user-assignable keys with conflict detection; defaults L/S/C/A/D/T/X/O/G/M/E |
| DXF export | ezdxf R2000; SPLINE entities; correct layers; Y-axis negated for DXF Y-up convention; arc angles correctly converted (swap + negate); mirrored OS side materialized at export when mirror is on |
| PNG export | Scene render composite |
| Pre-export validator | Enforces 1 OUTLINE, 2 LENS, closure, calibration |
| Fit view | Toolbar button |
| Alt+click overlap cycling | Alt+click cycles through all overlapping items at the cursor (Z-order); status bar shows "item N of M" |
| Split at node | Select a curve, click a node (red), press Split; open → two curves, closed → one open curve; undo-able |
| Explode | Select one or more curves, press Explode; each curve breaks into individual 2-node segments; undo-able |

### What is NOT yet built

- **Snap along curve segments** — on-curve snap targets at parametric positions on spline/line segments (nearest point on curve), required for connecting OUTLINE to LENS geometry for scallop and extrusion; see Known issues
- **Asymmetric export** — two distinct LENS entities for non-symmetric frames (open question in §13)
- **GuildCAM round-trip validation** (Phase 8) — pending hardware cut

### Upcoming — Next Sprint (Phases 18–21)

| Feature | Phase | Section |
|---------|-------|---------|
| Copy / Paste / Duplicate + Scale / Rotate | 18 | §23 |
| Temple R + Temple L workspaces + Mirror Copy tool | 19 | §24 |
| Frame fill / render overlay | 20 | §25 |
| Text insertion (ENGRAVING layer) | 21 | §26 |

### Fixed issues (resolved 2026-06-06)

- **Phase 12 revised — Fusion 360-style floating polar HUD** — Replaced the static
  bottom-bar `MeasureBar` workflow for line/spline tools with a cursor-following dual-field
  HUD. Digit keys write directly to the active field with no QLineEdit focus required.
  **Tab** switches between Length (mm) and Angle (°) fields. Typing a length locks the
  rubber-band to that radius; typing an angle constrains it to that direction ray; both
  locks together fully determine the next node's position. **Enter** with any lock active
  places one node at the constrained point and clears locks (continuing the curve); Enter
  with no locks finishes the curve (existing behaviour). **Escape** clears the active field
  first, then the other, then cancels drawing. Circle/Arc gained matching inline keyboard
  radius input (digits → floating HUD + locked preview → Enter). `CanvasView` now overrides
  `focusNextPrevChild()` to return `False` during drawing so Tab routes to the tool's
  `handle_key` rather than Qt's focus traversal. `MeasureBar` bottom bar retained for
  circle/arc alternative workflow; removed from line/spline path entirely. Version → 0.9.0.

- **Phase 12 — Exact measurement input implemented** — `MeasureBar` overlay added at
  bottom of `CanvasView`. Line/Spline tools show **Length (mm)** + **Angle (°)** fields after
  the first node is placed; pressing Enter places the next node at the exact polar offset.
  Circle/Arc tool shows **Radius (mm)** field after center is placed; pressing Enter emits the
  circle or locks the arc radius. Typing a digit on the canvas while the bar is visible
  automatically focuses the Length field (redirected from `DrawTool.handle_key`). The existing
  floating cursor-HUD (`_LengthHud`) remains for instant visual feedback near the cursor.
  `MeasureBar` is repositioned on window resize via `CanvasView.resizeEvent`.

### Completed features *(2026-06-09)*

- **Phase 13b — Toolbar + hotkey customization** — Settings dialog Toolbar tab (per-button
  visibility checkboxes) and Hotkeys tab (user-assignable keys with conflict detection).
  `prefs.py` DEFAULTS extended with `"toolbar"` and `"hotkeys"` dicts. `_apply_hotkeys()`
  tears down and rebuilds `QShortcut` objects on every settings save. Mirror-Close hidden by
  default. "Duplicate Mirror" → "Mirror".

- **Phase 14 — Tabbed workspaces** — `WorkspaceState` dataclass holds an independent scene,
  snap engine, all tool instances, undo/redo stacks, and guide state per tab. `QTabWidget`
  replaces the single central canvas. Sidebar reconfigures on every tab switch: layer combo,
  guide section visibility, library button visibility. Tab state (zoom, pan, active layer,
  guide toggles) saved/restored on each switch.

- **Phase 15 — Hinge pocket library** — `framedraft/library.py` (`HingeLibrary`): list SVG
  entries, save with collision-safe naming, load, rename, delete, and render thumbnails via
  QPainter. 5th sidebar tab visible across all workspaces; Save/Rename/Delete buttons visible
  in Hinge Pocket workspace only. Import centers geometry at canvas origin.

- **Phase 16 — Move tools** — `MoveGizmo` (four cardinal arrows, drag-to-translate, click
  for exact-distance HUD; hotkey M). `PointMoveTool` (hotkey G): two-click workflow — click
  grab point (snapped), then click destination or type absolute X/Y in HUD; HUD fields
  update live on hover; selection moved by delta, then returned to Select mode with items
  re-selected. Selectability-timing fix: `_set_tool_select()` called before
  `_end_move_selected()` so `setSelected(True)` fires with `ItemIsSelectable = True`.

- **Phase 17 — Offset tool** — `offset_curve()` in `geometry.py`: miter join with bevel
  fallback for lines, averaged-normal + inline Catmull-Rom recompute for splines (avoids
  circular import), analytical radius ± d for circles/arcs. `OffsetTool` cursor tool (O):
  type distance, live amber preview, Enter confirms, Esc cancels. Undo-safe.

- **Snap improvements** — `SnapEngine` gains: (1) midpoints of line segments (orange
  indicator); (2) origin snap at (0, 0) (purple indicator) — evaluated after all other
  candidates and overrides them when within radius, so the mirror-line projection cannot
  silently win over the origin point.

### Known issues / UX bugs *(from maker demo, 2026-06-08)*

- **Click detection over-reliant on Alt+Click** — Selecting a lens curve is difficult even when the cursor is far from the outline curve. Alt+Click cycling should be reserved for genuinely ambiguous overlaps; normal single-click should reliably pick the topmost non-overlapping item without requiring the Alt modifier. Hit shape inflation or smarter Z-ordering needed.
- **Snap along curve segments missing** — Snap engine only targets nodes, handles, and the mirror axis. Makers need to snap to arbitrary on-curve points (parametric positions along a segment) to draw connecting lines from OUTLINE to LENS for scallop and extrusion operations. Nearest-point-on-curve snap target required.
- **Dimension drag detaches from anchor points** — Clicking and dragging a `DimItem` translates the entire annotation (both anchor endpoints and the label) as a unit. The offset-drag interaction should only move the label offset; the anchor endpoints must stay locked to the geometry positions where the dimension was placed.
- **Properties frame-width recompute error after mirror + join** — An error is thrown when refreshing/reading back frame width in the Properties tab after performing a mirror (bake) operation followed by a join. Root cause unknown; likely a stale curve-list reference or a NaN width from the joined geometry.
- **Boxing guide asymmetry when Ghost is hidden** — The left-hand boxing guide disappears when the live mirror ghost is toggled off, but the right-hand boxing guide remains visible. The boxing overlay should be symmetric regardless of ghost state.
- **Move gizmo uses focused point as translation origin** — If a node is selected (focused) before the Move tool is activated, the gizmo translates the object from that point rather than from the object's own centroid or the gizmo's drag handle. Pre-selected nodes should not affect the move origin.
- **Mirror-line snap not re-applied after outline move** — If a spline endpoint has been snapped to the mirror axis and the curve is subsequently moved or edited, the endpoint cannot re-snap to the axis. The snap constraint is not persistent; moving the curve should preserve or allow re-establishment of the axis snap.
- **2-point calibration workflow broken** — Clicking two points on the face image to define a calibration line does not trigger a HUD or dialog to enter the real-world mm distance. The px-per-mm value is never computed from the drawn line; only the manual numeric entry field in the Canvas tab functions. The `CalibTool` two-click flow needs to pop up a measurement entry (floating HUD or inline dialog) after the second click, compute `px_per_mm = pixel_distance / entered_mm`, and apply it.

### Fixed issues (resolved 2026-06-07) — Phase 13 + DXF + Mirror

- **Phase 13 complete — Trim and Split tools** — `framedraft/geometry.py` added with shared
  parameterisation helpers (de Casteljau split, Shapely intersection, segment extraction for
  open/closed/circle/arc curves). `TrimTool` and `SplitTool` added in `framedraft/tools/`.
  Both wired into `app.py` with toolbar actions, amber hover highlighting, undo/redo, and
  status bar messages. A sampling bug in `t_nearest` (lines only sampled endpoints) and a
  `mapFromScene().toPoint()` call (returns `QPoint`, not `QPointF`) were found and fixed
  during integration.

- **DXF Y-axis fix** — all Y coordinates are now negated on export to conform to DXF's
  Y-up standard (`y_dxf = −y_scene`). Arc angles are corrected by **swapping** start/end
  angles before negating (`start_dxf = (−end_angle) % 360`, `end_dxf = (−start_angle) % 360`),
  because the Y-flip reverses the sweep direction. Frames no longer appear upside-down in
  standard CAD viewers. DXF header comment updated to document the convention.

- **Mirror (bake) operation** — new **Duplicate Mirror** toolbar action (icon `op-dup-mirror.svg`)
  creates real geometry copies of selected curves across the mirror axis. Copies are independent
  `Curve` objects (`mirrored=False`), fully saved and exported. The live mirror toggle is
  automatically turned off after baking so the originals do not get double-mirrored at export.
  Works on any selection of lines, splines, circles, and arcs simultaneously; preserves each
  curve's kind (a LINE curve stays a LINE curve after mirroring). To be renamed "Mirror" next
  session (see §21).

### Fixed issues (resolved 2026-06-07) — UI Polish

- **Icon-based toolbar** — all 20 toolbar actions replaced text labels with 20×20 px
  `currentColor` SVG icons from `framedraft/resources/icons/`. `_make_icon(name,
  normal_color, checked_color)` renders each SVG at two colors using `QSvgRenderer`
  + `QPixmap`, producing a two-state `QIcon` (off / on) without needing Qt's theme
  engine. `_apply_toolbar_icons(dark)` is called on startup and on every dark-mode
  toggle. Toolbar style set to `ToolButtonIconOnly`; icon size 20×20; spacing 2 px;
  buttons styled to `padding: 5px; min-width: 30px` (separated from `QPushButton`
  which keeps `padding: 4px 10px; min-width: 54px`). Toolbar separators styled as
  1 px amber/dark lines. All 20 actions gained or improved tooltips.

- **Sidebar tab reorganisation** — single-scroll right panel replaced with a
  `QTabWidget` (4 tabs): **Properties** (layer + line weight), **Guides** (all
  construction/boxing/stock/pad spinboxes in a scroll area), **Canvas** (face image
  + calibration in a scroll area), **History** (revision bookmarks). Title bar hidden
  via `setTitleBarWidget(QWidget())` + `NoDockWidgetFeatures`; `tabBar().setExpanding(False)`
  prevents the `>>` overflow button; dock widened to 270 px. `self._side_tabs` stored
  for programmatic tab switching. History tab label shows live bookmark count
  (`"History (n)"`). Revision Timeline dock (formerly bottom) removed entirely.
  View → Revision History shows sidebar and switches to History tab (index 3).

- **Status bar info label** — permanent `QLabel` (right side) shows current active
  layer and zoom percentage, e.g. `LENS  |  82%`. Updated by `_update_info_label()`
  called from: `_on_layer_combo_changed`, `_on_selection_changed`, `_fit_view`, and
  via `CanvasView.zoom_changed` signal emitted from `wheelEvent`. Initial value set
  at end of `__init__`.

### Fixed issues (resolved 2026-06-07) — Phase 11 + Phase 12

- **Phase 11 — Circles + arcs implemented** — `Circle` and `Arc` toolbar buttons added. `CircleTool` (two-click circle, three-click arc). `Curve` dataclass extended with `radius`, `start_angle`, `end_angle`. `build_path`, `_mirror_path`, `SnapEngine`, SVG serialize/load, DXF export, and `EditTool.insert_node_at` all updated. All existing module imports verified clean.

### Fixed issues (resolved 2026-06-06)

- **Bookmark save crash: `'str' object has no attribute 'nodes'`** — `save_svg` iterated
  `for c in bm["snapshot"]`; iterating a dict yields string keys (`"curves"`, `"dims"`), not
  `Curve` objects. Fixed by indexing `bm["snapshot"]["curves"]`. Companion fix: `load_svg`
  now returns the bookmark snapshot as `{"curves": [...], "dims": []}` (a dict) so
  `_restore_snapshot` can subscript it correctly.
- **Pad Block guide renders at wrong size (170×85 instead of 45×45)** — `RectGuide.__init__`
  hardcoded `_width_mm = 170.0, _height_mm = 85.0` for all instances. The pad spinboxes
  initialize to 45.0 in `_build_side_panel`, but the prefs `setValue(45.0)` call in `__init__`
  didn't emit `valueChanged` (no change from the spinbox's current value), so `set_width(45.0)`
  was never called. Fixed by adding `width_mm` / `height_mm` parameters to `RectGuide.__init__`
  and passing `width_mm=45.0, height_mm=45.0` when creating the pad guide.

### Fixed issues (resolved 2026-06-07)

- **`DimItem` interaction fully broken** — root cause was a missing `QPainterPath`
  import in `canvas/dim.py`. Every call to `shape()` silently raised `NameError`;
  PySide6 fell back to the C++ default (full bounding rect as hit shape), making
  the DimItem claim a large padded region and block all CurveItems underneath.
  Three fixes applied simultaneously:
  1. Added `QPainterPath, QPainterPathStroker` to the `canvas/dim.py` imports.
  2. Overrode `DimItem.contains()` with direct point-to-segment distance math
     (`_seg_dist` helper, `_HIT_TOL_MM = 3.0 mm`) — bypasses `QPainterPath.contains()`
     entirely for single-click hit-testing; robust against Qt version differences.
  3. Rewrote `shape()` using `QPainterPathStroker` + `WindingFill` — correct
     approach for rubber-band selection; avoids the inverted-winding issue that
     made prior `QPainterPathStroker` attempts fail under `OddEvenFill`.
  4. Fixed `boundingRect()` to cover both sides of the dim line (was only
     extending in the positive perpendicular direction).
- **Dim deletion not undoable** — `_delete_selected` was pushing the undo snapshot
  after dims were already removed, and dim-only deletions had no snapshot at all.
  Fixed: single `_push_undo_snapshot()` call before any removal in that method.

### Fixed issues (resolved 2026-06-06)

- **Hit-detection conflict: overlapping items always select the top Z item** —
  Implemented **Alt+click** to cycle through all overlapping `CurveItem`/`DimItem`
  instances at the cursor position. `CanvasView.mousePressEvent` intercepts
  `Alt+LeftButton` in select mode, calls `self.items(vp_pos)` (shape-tested,
  highest-Z first), finds the currently selected item in the candidate list, advances
  to the next index (wrapping), and clears+sets selection. Falls through to normal
  `super()` behavior when fewer than 2 items overlap. Status bar shows
  `"Alt+click: item N of M overlapping"`. Select tool tooltip updated to advertise
  the shortcut.

---

## 1. Goal & scope

A tool that lets a maker:

1. Draw straight lines.
2. Draw splines (editable Bézier curves).
3. Draw circles and arcs.
4. Snap to points (nodes, control points, curve centers, quadrants, the mirror axis).
5. Enter exact measurements (length, radius, diameter) when placing geometry.
6. Trim curves at intersections and split curves at picked points.
7. Toggle a **mirror line** to mirror geometry along the bridge centerline.
8. Toggle **construction lines** preset for **bridge angle** and **apical radius**.
9. Load a photo of the wearer's face as a background to draw upon.
10. Work across **tabbed workspaces** — frame front, temple, and hinge pocket.
11. Build a **personal hinge library** — save pocket designs and import them into any workspace.
12. Save three artifacts per workspace: an **SVG** (editable master with full session state), a
    **PNG** render, and a **DXF** that GuildCAM consumes with splines intact.

Explicit non-goals: text, gradients, layers-as-art, filters, anything not related to
eyewear drafting.

---

## 2. Platform target

PySide6 (Qt 6 binding for Python). Tested on:

- **Windows** — primary (Python 3.14, PySide6)
- **Linux** — supported
- **macOS** — supported, lower priority (Gatekeeper signing deferred)

---

## 3. Tech stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Tested on 3.14 |
| GUI / canvas | PySide6 (Qt 6, LGPL) | `QGraphicsView`/`QGraphicsScene` vector canvas |
| Geometry on screen | `QPainterPath` (cubic Béziers) | Converts exactly to DXF splines |
| DXF export | `ezdxf` (MIT) | R2000 with native SPLINE |
| Contour checks | Shapely (optional, dev/validation) | Pre-export validator |
| PNG render | Qt `QImage` scene render | Composite face image + geometry |
| SVG | Hand-serialized with embedded `<metadata>` JSON | Full control; round-trip |
| Packaging | PyInstaller (not yet done) | Per-OS standalone builds |

---

## 4. File format / export contract (confirmed against GuildCAM)

### DXF — R2000 (AC1015) with SPLINE entities

GuildCAM accepts DXF R12–R2018 via ezdxf; handles `SPLINE` natively, tessellating
at **0.01 mm chord tolerance**. SPLINE is the preferred path; do not pre-flatten.

### Units — true mm at 1:1

GuildCAM reads raw coordinates as mm; does **not** read `$INSUNITS`. Set
`$INSUNITS = 4` by convention. App calibration (§5) is the sole scale authority.

### Closed contours + strict layers

GuildCAM auto-closes contours whose endpoints are within **0.1 mm**.

| Layer     | Required count | Machined? |
|-----------|----------------|-----------|
| `OUTLINE` | exactly 1      | yes       |
| `LENS`    | exactly 2      | yes       |
| `BRIDGE`  | optional       | yes       |
| `HINGE`   | optional       | yes       |
| `REF`     | optional       | no        |

### Spline conversion (exact)

```python
from ezdxf.math import Bezier4P, bezier_to_bspline
curves = [Bezier4P(seg) for seg in cubic_segments_mm]
bspline = bezier_to_bspline(curves)
msp.add_spline(dxfattribs={"layer": "LENS"}).apply_construction_tool(bspline)
```

### SVG — native save format

SVG 1.1 with a `<metadata>` child on the root `<svg>` element containing a single
JSON blob. The blob carries:

```json
{
  "calibration": { "px_per_mm": float | null },
  "mirror":      { "x": float, "enabled": bool },
  "forming":     { "bridge_angle_deg": float, "apical_radius_mm": float },
  "machined_bridge": { "depth_mm": float, "width_mm": float },
  "face_image":  { "path": str, "tx": float, "ty": float, "rotation": float, "opacity": float },
  "curves":      [ { "kind", "layer", "closed", "mirrored", "line_weight", "nodes": [...] } ],
  "bookmarks":   [
    { "name": str, "timestamp": str, "curves": [ ... same curve format ... ] }
  ]
}
```

Bookmarks (revision timeline) are stored in the same metadata block, serialized
with the same curve format. Files without a `"bookmarks"` key open cleanly with no
timeline. The SVG path elements are also written for compatibility with external
viewers (Inkscape, browsers); geometry is authoritative from the metadata JSON.

### PNG — render over face image

`QImage` scene render; composite face + geometry at chosen DPI. Presentation only.

---

## 5. Real-world scale

GuildCAM has no calibration. The app establishes **px-per-mm** via:

- 2-point landmark click on the face photo + real distance entry, **or**
- Direct numeric entry in the Calibration panel.

Stored in SVG metadata; applied to every export.

---

## 6. Data model

```python
# framedraft/document.py

class Layer(str, Enum):
    OUTLINE = "OUTLINE"
    LENS    = "LENS"
    BRIDGE  = "BRIDGE"
    HINGE   = "HINGE"
    REF     = "REF"

@dataclass
class ControlPoint:
    x: float
    y: float

@dataclass
class SplineNode:
    x: float
    y: float
    cp_in:  Optional[ControlPoint] = None   # incoming Bézier handle
    cp_out: Optional[ControlPoint] = None   # outgoing Bézier handle

@dataclass
class Curve:
    kind:        str           # "line" | "spline"
    layer:       Layer
    nodes:       List[SplineNode]
    closed:      bool  = False
    mirrored:    bool  = False  # True = derived OS copy; not saved, not exported separately
    line_weight: float = 1.5   # cosmetic screen-pixel width

@dataclass
class Calibration:
    px_per_mm: Optional[float] = None

@dataclass
class MirrorAxis:
    enabled: bool  = True
    x:       float = 0.0      # scene-space x of the vertical centerline

@dataclass
class FormingMetadata:
    bridge_angle_deg: float = 0.0
    apical_radius_mm: float = 0.0

@dataclass
class MachinedBridge:
    depth_mm: float = 4.0
    width_mm: float = 5.0

@dataclass
class FaceImage:
    path:     str   = ""
    tx:       float = 0.0
    ty:       float = 0.0
    rotation: float = 0.0
    opacity:  float = 0.7
```

Geometry stored once (OD half); OS side is derived live and materialized into
independent DXF entities at export only. Construction guides are never exported.

---

## 7. Feature implementation notes

### Drawing

- **Line tool**: click-to-place polyline nodes; double-click or Enter to finish open;
  click first node to close; Escape to cancel; Ctrl+Z removes last placed point.
- **Spline tool**: same interaction; nodes get Catmull-Rom-computed Bézier handles on
  finish; handles are editable in Select mode.
- Shift during drawing = constrain to nearest 45° from last node.
- Ctrl during drawing = suspend snap (free placement).

### Select mode

- Click a curve to select (shows NodeDots and HandleDots).
- Ctrl/Shift+click or rubber-band drag to multi-select.
- Layer and line weight of the selected curve(s) shown in Properties panel;
  changes apply immediately to the selection.
- Delete/Backspace removes selected curves.

### Snapping

- 10 px screen-space radius.
- Targets: all curve nodes, all control-point handles, in-progress draw nodes, mirror axis.
- Snap indicator dot shown at snap target.
- Ctrl held = suspend snap for that event.

### Join operation

Merges 2+ selected open curves into one by chaining them at nearest endpoints
(within 2 mm). Algorithm:

1. Greedy: start with first selected curve; find closest endpoint of remaining curves
   to either end of the current chain; repeat.
2. Handles all four endpoint orientations (tail→head, tail→tail, head→head, head→tail)
   by reversing curves as needed. On reversal, `cp_in`/`cp_out` are swapped.
3. At each junction, merged node keeps `cp_in` from the first curve, `cp_out` from
   the second, preserving existing handle shapes.
4. If chain start and end are also within 2 mm, result is marked `closed`.
5. Result kind is "spline" if any input is a spline; otherwise "line".

### Mirror Close

Combines a selected open curve with its mirror image into one closed shape:

1. Snaps first and last node x to the axis.
2. Appends reversed mirrored interior nodes.
3. Runs `compute_catmull_handles(nodes, closed=True)` for smooth splines.
4. Replaces the open half-curve with the new closed curve.

### Undo / Redo

- Snapshot-based: `copy.deepcopy(self._doc_curves)` before every mutation.
- Mutations that snapshot: add curve, delete, join, mirror-close, layer change, line
  weight change, any node/handle drag (via `EditTool.about_to_modify` signal fired
  from `NodeDot.mousePressEvent` / `HandleDot.mousePressEvent`).
- Stacks: `_undo_stack` (list of snapshots, oldest first) + `_redo_stack`.
- Max 100 steps each direction. Redo stack wiped on any new operation.
- Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z (window-scope `QShortcut`).
- In draw mode, Ctrl+Z removes the last placed point without touching the canvas stack.
- Edit menu shows live counts: "Undo (3) Ctrl+Z".

### Revision Timeline

Lives in the **History tab** of the right sidebar. Access via View → Revision History
(shows sidebar + switches to that tab).

- **Bookmark Current State…** — prompts for a name, saves deep copy of curves +
  timestamp.
- **Double-click** or **Restore** — pushes current state to undo stack first, then
  restores the bookmark (so the restore itself is undoable).
- **Rename…** — renames via dialog.
- **Delete** — confirms, then removes entry.
- Bookmarks persist to SVG via the `"bookmarks"` key in `<metadata>` JSON.
- Session-only undo/redo stacks are NOT saved; bookmarks ARE.
- Tab label shows live count: `"History (n)"` when bookmarks exist.

### Construction guides

Visible, toggleable, non-exported:

- Bridge angle guide: two arms from pivot points at configurable angle.
- Apical radius guide: arc at the top of the bridge.
- Boxing guide: A×B lens box with DBL (distance between lenses) separation.

All dark-mode aware. Values stored in SVG forming metadata (not machined in GuildCAM v1).

### Mirror

- Vertical centerline at scene x = `mirror.x` (default 0).
- Live dotted ghost rendered for LENS, HINGE, OUTLINE (open) curves.
- Mirror display and snap are independently toggleable.
- Mirror-Close requires both endpoints of the selected curve to be at/near the axis.

---

## 8. UI & styling

Guild palette. Two themes: light (default) and dark (Settings menu).

| Role | Light | Dark |
|---|---|---|
| App chrome | `#ffd580` | `#1a1a1a` |
| Canvas | `#faf6ee` | `#1e1e1e` |
| Geometry / text | `#1f1f1f` | `#d4cfc0` |
| Mirror axis | `#c0392b`, dashed | same |
| Guides | `#2a7f9e`, dashed | same |
| Snap indicator | `#2e8b57` | same |
| Node handle lines | `#2a7f9e`, dotted | `#4ab8d8`, dotted |
| Toolbar icon (normal) | `#1f1f1f` | `#d4cfc0` |
| Toolbar icon (checked) | `#ffd580` on `#1f1f1f` bg | `#1a1a1a` on `#d4cfc0` bg |

Dark mode is toggled via **Settings menu** (checkable action) or **Settings >
Preferences…** dialog. Both are in sync. Toggling dark mode calls `_apply_toolbar_icons(dark)`
to re-render all SVG icons at the new theme's colors.

### Toolbar

Left vertical `QToolBar`. `ToolButtonIconOnly` style; 20×20 px icons; 2 px item
spacing; 5 px button padding; 30 px minimum button width. Three separator groups:
drawing tools (6) / view toggles (7) / operation buttons (6 + Fit) / panel toggle (1).

SVG icons live in `framedraft/resources/icons/` (20 named files). All use
`currentColor`; `_make_icon()` renders each at two explicit hex colors to produce a
per-state `QIcon`. Icons are re-rendered at theme change.

### Right sidebar

`QDockWidget` (270 px minimum width) with hidden title bar. Contains a `QTabWidget`
with 4 tabs:

| Tab | Contents |
|---|---|
| **Properties** | Layer combo + line weight spinbox |
| **Guides** | Construction/Forming spinboxes; Boxing System (A/B/DBL); Stock Blank; Pad Block (all in a scroll area) |
| **Canvas** | Face image (load / opacity / rotation); Calibration (2-point + direct entry) |
| **History** | Revision bookmark list; Bookmark / Restore / Rename / Delete; tab label shows count |

### Status bar

Left side: ephemeral messages (`showMessage`). Right side: permanent label
`LAYER  |  ZOOM%` updated by `_update_info_label()` on layer change, selection
change, zoom, and Fit.

---

## 8a. Pre-export validator

Runs before any DXF write. Checks:

- Exactly 1 `OUTLINE` contour present and closed (endpoints ≤ 0.1 mm apart).
- Exactly 2 `LENS` contours present and closed.
- All `BRIDGE`/`HINGE` contours closed if present.
- Calibration is set (px_per_mm > 0).
- Warns on geometry outside the known layer vocabulary.

Blocks export on errors; warns-and-confirms on warnings only.

---

## 9. Module layout (current)

```
framedraft/
├── __init__.py           # package version
├── app.py                # QApplication, MainWindow (~4 500 lines), WorkspaceState,
│                         #   CanvasView, SettingsDialog; all tool wiring and signal dispatch
├── document.py           # dataclasses: Curve, SplineNode, ControlPoint, Layer, DimLine, etc.
├── calibration.py        # CalibTool (2-point px-per-mm)
├── construction.py       # ConstructionGuides, BoxingGuide, RectGuide (stock/pad centered rects)
├── geometry.py           # Shared helpers: de Casteljau split, Shapely intersection,
│                         #   segment extraction, offset_curve()
├── library.py            # HingeLibrary: list/save/load/rename/delete/thumbnail
├── prefs.py              # Persistent user preferences (~/.guilddraw/prefs.json); load() / save()
│                         #   DEFAULTS includes toolbar visibility + hotkey assignments
├── canvas/
│   ├── __init__.py
│   ├── scene.py          # FrameScene (curves, ghosts, dim items, face image, origin cross)
│   ├── items.py          # CurveItem, NodeDot (selectable), HandleDot, build_path
│   ├── dim.py            # DimItem (offset dim line + extension lines, draggable)
│   ├── snapping.py       # SnapEngine — nodes, handles, midpoints, mirror axis, origin (0,0),
│   │                     #   circle quadrants; origin overrides mirror when within snap radius
│   ├── mirror.py         # MirrorAxis (scene item + logic)
│   ├── move_gizmo.py     # MoveGizmo (four-arrow handles + exact-distance HUD)
│   └── measure_bar.py    # MeasureBar (polar HUD for line/spline/circle/arc tools)
├── tools/
│   ├── __init__.py
│   ├── draw.py           # DrawTool, compute_catmull_handles
│   ├── edit.py           # EditTool (node select/insert/delete, about_to_modify Signal)
│   ├── circle.py         # CircleTool (two-click circle, three-click arc)
│   ├── dim.py            # DimTool (two-click snap-aware placement)
│   ├── trim.py           # TrimTool (cursor tool: remove segment between intersections)
│   ├── split.py          # SplitTool (cursor tool: split at click or intersection)
│   ├── offset.py         # OffsetTool (type distance → amber preview → Enter confirms)
│   └── point_move.py     # PointMoveTool (click grab point → click/type destination)
├── resources/
│   └── icons/            # currentColor SVGs; rendered per-theme by _make_icon()
└── export/
    ├── __init__.py
    ├── svg.py            # save_svg / load_svg (bookmarks + dims in metadata JSON)
    ├── png.py            # render_png
    ├── validate.py       # pre-export validator
    └── dxf.py            # export_dxf (ezdxf R2000, SPLINE, mirrored OS)
```

---

## 10. Build phases / milestones

- ✅ **Phase 0** — Skeleton: window, toolbar, canvas, QSS palette.
- ✅ **Phase 1** — Background + calibration: face image load/rotate, px-per-mm.
- ✅ **Phase 2** — Drawing + layers: line + spline tools, node editing.
- ✅ **Phase 3** — Snapping: snap engine + indicator.
- ✅ **Phase 4** — Mirror: vertical axis, live reflection, Mirror Close.
- ✅ **Phase 5** — Construction: bridge-angle + apical-radius + boxing guides.
- ✅ **Phase 6** — Export + validate: SVG save/load, PNG, validator, DXF R2000/SPLINE.
- ✅ **Phase 6b** — Multi-select (rubber-band), Join operation, Settings dialog.
- ✅ **Phase 6c** — Undo/Redo (snapshot, 100 steps) + Revision Timeline (persisted bookmarks).
- ✅ **Phase 7** — Packaging: PyInstaller one-folder Windows build (`dist/GuildDraw/GuildDraw.exe`, ~174 MB); `framedraft.spec` + `requirements-dev.txt` added; `__version__ = "0.7.0"`.
- ⬜ **Phase 8** — GuildCAM validation: round-trip real DXFs; confirm layer counts,
  closure, symmetric-flag behavior.
- ✅ **Phase 9** — Dimension lines: `DimTool` two-click placement; `DimItem` renders line + ticks + label; draggable offset with extension lines; snaps to curve nodes; selectable/deletable; persisted in SVG `"dims"` metadata key.
- ✅ **Phase 10** — Node insert/delete: double-click on curve segment inserts node (de Casteljau split for splines, parametric interpolation for lines); click NodeDot to select (red highlight) then Del removes it.
- ✅ **Phase 10b** — Split at node / Explode (§20): with a node selected, split
  the curve at that point into two open curves. Explode: break any curve into
  individual 2-node segments. Both are undo-able; no Shapely required.
- ✅ **Phase 11** — Circles + arcs (§15): `Circle` (2-click: center + edge) and
  `Arc` (3-click: center + start + end) tools; `CircleTool` class; `Curve`
  extended with `radius`, `start_angle`, `end_angle`; snap to center + quadrant
  points + arc endpoints; DXF CIRCLE/ARC export; full SVG round-trip.
- ✅ **Phase 12** — Floating polar HUD (§16): Fusion 360-style cursor-following dual-field
  HUD for line/spline tools. Digit keys fill the active field inline (no QLineEdit focus);
  Tab switches between Length and Angle fields; Enter with a lock active places one node
  at the constrained position. Angle lock constrains rubber-band to a direction ray; length
  lock constrains to a fixed radius; both together fully determine the point. Circle/Arc
  tools gained inline keyboard radius input (digits → lock → Enter) with matching floating
  HUD. Static bottom `MeasureBar` retained for circle/arc bottom-bar workflow.
- ✅ **Phase 13** — Trim/Split tools (§17): `TrimTool` and `SplitTool` cursor tools;
  `framedraft/geometry.py` with de Casteljau split, Shapely intersection, segment
  extraction for open/closed/circle/arc; both tools wired into toolbar with amber
  hover, undo, and status messages.
- ✅ **Phase 13b** — Toolbar customization + hotkey assignment (§21): Settings dialog
  Toolbar and Hotkeys tabs; Mirror-Close hidden by default; "Duplicate Mirror" renamed
  "Mirror"; defaults L/S/C/A/D/T/X/O/G/M/E.
- ✅ **Phase 14** — Tabbed workspaces (§18): Frame Front, Temple, Hinge Pocket tabs;
  independent canvas, document, undo/redo stack, snap engine, and tool instances per tab;
  sidebar reconfigures on switch; `.gdraw` ZIP project format (front.svg + temple.svg +
  hinge.svg + manifest.json).
- ✅ **Phase 15** — Hinge pocket library (§19): `framedraft/library.py` HingeLibrary;
  5th sidebar tab; import into any workspace; save/rename/delete in Hinge Pocket only;
  thumbnail rendering via QPainter + build_path.
- ✅ **Phase 16** — Move tool (§20): MoveGizmo (four-arrow, drag + exact-distance HUD,
  hotkey M); PointMoveTool (two-click point-to-point / point-to-position, hotkey G,
  snap-aware, X/Y HUD with live hover update).
- ✅ **Phase 17** — Offset tool (§22): `offset_curve()` in geometry.py; OffsetTool
  cursor tool (O); miter join for lines, averaged-normal + Catmull-Rom for splines,
  analytical for circles/arcs; amber live preview; undo-safe.
- ⬜ **Phase 18** — Snap along curve segments: nearest-point-on-curve snap targets for
  splines and lines; required for OUTLINE→LENS scallop/extrusion connections.

Usable internal alpha: **complete**. Phases 0–17 done; Phase 7 (PyInstaller packaging) done.
Phase 8 (GuildCAM round-trip validation) pending hardware cut.
Phase 18 (on-curve snap) is the next technical priority. Known UX bugs listed above.

---

## 11. Packaging & distribution

- **PyInstaller** one-folder/one-file builds per OS. Windows/Linux straightforward.
- **macOS** needs Apple Developer ID for signing + notarization; deferred.
- Alternative: **Briefcase (BeeWare)** for native installers.

**Done (Phase 7):** `framedraft.spec` (one-folder); `dist/GuildDraw/GuildDraw.exe` (~174 MB); `requirements-dev.txt`. Entry point is `main.py` → `framedraft.app.main()`.

macOS needs Apple Developer ID for signing + notarization; deferred.

---

## 12. Licensing

PySide6 is LGPL, ezdxf and Shapely are MIT/BSD. App can ship MIT/BSD or GPL per
guild preference.

---

## 13. Open questions

**Resolved (GuildCAM Session 5):**

1. DXF intake — R2000 + SPLINE; tessellated at 0.01 mm; R12 fallback dropped.
2. Units — mm at 1:1; `$INSUNITS` ignored by GuildCAM, set to 4 by convention.
3. Closed contours + strict layers — 1 OUTLINE, 2 LENS; validator enforces.
4. Bridge angle / apical radius — forming metadata, not machined in GuildCAM v1.
5. Calibration — none in GuildCAM; fully app responsibility.
6. Mirror — live, about vertical centerline; default workflow.

**Still to confirm:**

- **Symmetric flag vs. two exported LENS entities.** With `symmetric = True` (default
  in GuildCAM), GuildCAM re-derives OS by mirroring OD on every rebuild. For
  symmetric frames (mirror on) this is harmless. For intentionally **asymmetric**
  exports (mirror off), confirm whether importing two distinct LENS entities sets
  `symmetric = False`, or whether GuildCAM overwrites the exported OS anyway. If the
  latter, asymmetric frames require a manual `symmetric = False` on the GuildCAM
  project side.
- **Guild-standard defaults** for bridge angle and apical radius (supply values for
  the construction guide presets).

---

## 14. Dimension lines (Phase 9)

Snap-aware annotation tool. Measures two picked points, displays mm distance. Never
exported as machined geometry.

### Behavior

- **Dim tool**: click A, click B → dimension line with arrowheads + text label (mm).
- Labels update live if calibration factor changes.
- Lives on a `DIM` layer (never exported to DXF/PNG/SVG machined data).
- Selectable and deletable via Select tool.
- Snap-aware (snaps to curve nodes, handles, mirror axis).

### Data model addition

```python
@dataclass
class DimLine:
    x0: float; y0: float
    x1: float; y1: float
```

Stored as `Document.dims: List[DimLine]`; serialized in SVG `<metadata>` JSON
alongside curves and bookmarks.

### Modules (not yet created)

- `framedraft/canvas/dim.py` — `DimItem(QGraphicsItem)`: renders line, arrowheads, text.
- `framedraft/tools/dim.py` — `DimTool(QObject)`: two-click placement with snap.

---

## 15. Circles and arcs (Phase 11)

A new first-class primitive alongside line and spline.

### Primitives

- **Circle** — defined by center + radius. Closed, always. Snap targets: center and four
  cardinal quadrant points (0°, 90°, 180°, 270°).
- **Arc** — defined by center + radius + start angle + end angle (counter-clockwise).
  Snap targets: center, start point, end point, quadrant points that fall within the arc.

### Drawing interaction

- **Circle tool**: click to place center; drag or Tab to enter radius numerically; release/Enter to confirm.
- **Arc tool**: click center, click start point (sets radius), click end point (sets sweep angle).
  Alternatively, Tab after placing center to enter radius and start/end angles numerically.

### Data model addition

```python
@dataclass
class Curve:
    kind: str  # "line" | "spline" | "circle" | "arc"
    ...
    # For kind == "circle": nodes[0] = center; nodes[0].cp_out.x = radius
    # For kind == "arc":    nodes[0] = center; cp_out.x = radius,
    #                       cp_in.x = start_deg, cp_in.y = end_deg
```

Encoding radius and angles into the existing `ControlPoint` fields avoids a dataclass
change but is fragile. Preferred alternative: add optional fields to `Curve`:

```python
@dataclass
class Curve:
    ...
    radius:      Optional[float] = None  # circle / arc radius (mm)
    start_angle: Optional[float] = None  # arc start (degrees, CCW from +x)
    end_angle:   Optional[float] = None  # arc end (degrees, CCW from +x)
```

`nodes[0]` = center node for circle/arc. `nodes` list unused otherwise.

### Rendering

`build_path` gains a circle/arc branch:

```python
elif curve.kind == "circle":
    cx, cy, r = curve.nodes[0].x, curve.nodes[0].y, curve.radius
    path.addEllipse(cx - r, cy - r, 2 * r, 2 * r)
elif curve.kind == "arc":
    # QPainterPath.arcTo(rect, start_deg, sweep_deg)
    path.arcTo(cx - r, cy - r, 2 * r, 2 * r, start_angle, sweep)
```

### DXF export

Emit DXF `ARC` / `CIRCLE` entities directly (simpler and exact). If GuildCAM has
trouble with these, fall back to SPLINE approximation via 4-segment Bézier circle
(standard 0.00273% error approximation).

```python
msp.add_circle(center=(cx_mm, cy_mm), radius=r_mm, dxfattribs={"layer": lyr})
msp.add_arc(center=(cx_mm, cy_mm), radius=r_mm,
            start_angle=start_deg, end_angle=end_deg, dxfattribs={"layer": lyr})
```

### SVG serialization

Circle/arc curves serialize as regular curve dicts with `kind = "circle"` / `"arc"`,
`radius`, `start_angle`, `end_angle` fields added. Backward-compatible: old loaders
see an unknown kind and can skip or warn.

### Snap additions

`SnapEngine` gains circle/arc targets: center, cardinal quadrant points, arc endpoints.

---

## 16. Exact measurement input (Phase 12)

Allows a designer to specify a precise dimension rather than relying on mouse placement.
Primary use case: "I want this endpiece line to be exactly 14.0 mm."

### Input modes

1. **Length + angle** — after placing the first node of a line segment, a small HUD
   input bar appears at the bottom of the canvas (not a modal dialog, so the user can
   still see the drawing). Fields: **Length (mm)** and **Angle (°)**. Tab moves
   between fields; Enter confirms and places the next node exactly.
2. **Radius / diameter** — when the Circle or Arc tool is active and the center has
   been placed, the same HUD shows a single **Radius (mm)** or **Diameter (mm)** field
   (toggled by a small button). Enter confirms.
3. **Relative coordinate** — advanced mode (later): type `@dx,dy` in the length field
   to place by offset rather than polar coordinates.

### HUD design

`MeasureBar` — a `QWidget` overlaid at the bottom of `CanvasView`, hidden unless a
draw tool is active and at least one node has been placed.

```
[ Length: ______ mm ]  [ Angle: ______ ° ]   [Enter = confirm]
```

- Appears automatically when the second node is being placed during line/spline drawing.
- Dismissed on Escape or when the draw tool becomes inactive.
- Does not block canvas interaction; mouse can still click to set values graphically,
  with the HUD updating to reflect the measured value of the placed point.

### Angle conventions

- 0° = rightward (+x axis). Positive = counter-clockwise.
- "Constrain to 45°" (Shift key) still works; the HUD reflects the snapped angle.

### Modules (not yet created)

- `framedraft/canvas/measure_bar.py` — `MeasureBar(QWidget)`: overlay HUD with length/angle fields.
- `DrawTool` extended: accepts a `(length_mm, angle_deg)` pair to compute the next node
  position from the current tail node rather than from a mouse event.

---

## 17. Trim / Split tools (Phase 13)

CAD-standard destructive editing operations.

### Trim

**Goal**: click a segment of a curve to remove the portion between its two nearest
intersections with other curves (like AutoCAD TRIM).

**Workflow**:
1. Activate Trim tool.
2. Optionally pre-select "cutting edges" (the curves that define the trim boundaries).
   If nothing is pre-selected, all curves act as potential cutting edges.
3. Click the portion of a curve to remove. The segment between the two nearest
   intersections with cutting edges is deleted; the remainder becomes one or two new
   open curves.

**Algorithm**:
1. Compute all intersections between the clicked curve and the cutting edges using
   Shapely (`curve_a.intersection(curve_b)`). Shapely is already a listed dependency.
2. Find the parameter values `t` on the clicked curve at each intersection.
3. Split the clicked curve at those `t` values into sub-segments.
4. Delete the sub-segment containing the click point; keep the others.

**Bézier split at parameter t** (de Casteljau):

```python
def split_bezier_at_t(p0, p1, p2, p3, t):
    # Returns two cubic segments [left, right]
    ...
```

Applied per cubic segment in the spline; the split point may fall in the middle of
one segment, requiring that segment to be split and the spline re-assembled.

### Split

**Goal**: click a point on a curve to split it into two curves at that point.

**Workflow**:
1. Activate Split tool (or hold a modifier in Trim mode).
2. Click on a curve. The curve is split at the nearest point to the click; both
   halves remain in the document as independent open curves.

**Special case — intersection split**: if the click is near an intersection of two
curves, both curves are split at the intersection point simultaneously, creating four
curve fragments.

### Modules (not yet created)

- `framedraft/tools/trim.py` — `TrimTool(QObject)`: cutting-edge selection, click target, Shapely intersection query, de Casteljau split.
- `framedraft/tools/split.py` — `SplitTool(QObject)`: single-click split; reuses de Casteljau helpers from trim module.
- `framedraft/geometry.py` — shared low-level helpers: `split_bezier_at_t`, `bezier_t_at_point`, `curve_to_shapely`, `shapely_to_curve_segments`.

### Undo

Both operations call `_push_undo_snapshot()` before any mutation. Each trim/split
is a single undoable step regardless of how many intersections are computed.

---

## 18. Tabbed workspaces (Phase 14)

Separate drafting environments for the three core eyewear components. Each tab is an
independent document that can be saved, loaded, and exported on its own.

### Tabs and layers

| Tab | Purpose | Layers (strict) |
|---|---|---|
| **Frame Front** | OD half of the front; mirrored to produce full front | OUTLINE, LENS, SCULPT, HINGE, REF |
| **Temple** | One temple arm; left/right via mirror export | OUTLINE, ENGRAVING, SCULPT, HINGE, REF |
| **Hinge Pocket** | A single hinge cutout design | HINGE, REF |

Layer notes:
- **SCULPT** (purple) — back-surface scallop lines for GuildCAM machining; mirrored in both ghost display and DXF export.
- **ENGRAVING** (teal) — engraving mark guides for temple arms; not mirrored.
- **BRIDGE** — exists in the enum but is unassigned to any workspace. Reserved for a future bridge-path offset tool (GuildCAM angled bridge cutaway).
- The layer combo in the Properties sidebar is filtered to the active workspace's layer set. Drawing tools always use the currently selected layer.

### WorkspaceDocument

Each workspace tab owns a `WorkspaceDocument` dataclass (defined in `framedraft/document.py`):

```python
@dataclass
class WorkspaceDocument:
    workspace_type: str          # "front" | "temple" | "hinge"
    curves:         list[Curve]
    dims:           list[DimLine]
    calibration:    Calibration
    mirror:         MirrorAxis
    forming:        FormingMetadata   # stored on all; only used for front export
    face_images:    list[FaceImage]
    bookmarks:      list[dict]
    guide_state:    dict              # on/off flags + float values, keyed by name
    active_layer:   str
    zoom:           float
    pan_x:          float
    pan_y:          float
    undo_stack:     list
    redo_stack:     list
```

Tab switching saves the departing workspace's `zoom`, `pan_x`, `pan_y`, `active_layer`, and all guide toggle states into its `WorkspaceDocument`, then restores the arriving workspace's values.

### Architecture

`QTabWidget` replaces the single `CanvasView` at the center of `MainWindow`. Each tab
holds a `CanvasView` + `FrameScene` pair. The sidebar is a single widget tree that
reconfigures itself when the active workspace changes (Option C — shared sidebar,
workspace-aware state).

**Sidebar reconfiguration on workspace switch:**
- Properties tab: layer combo repopulated from `WORKSPACE_LAYERS[workspace_type]`.
- Guides tab: sections shown/hidden based on workspace (see Guides below).
- Canvas tab: always present; each workspace has its own reference images and calibration.
- History tab: always present; bookmarks are per-workspace.
- Hinge Library tab (5th, always visible): content adapts per workspace —
  Front/Temple show browse + import; Hinge Pocket additionally shows save-to-library
  and create/edit actions.

### Guides per workspace

**Frame Front** (existing controls, unchanged):
- Construction lines on/off (bridge angle, apical radius)
- Boxing guide on/off + A/B/DBL dimensions
- Stock blank guide on/off + width/height
- Pad block guide on/off + width/height

**Temple:**
- Stock bar guide on/off + length × width (rectangle, centered at origin)

**Hinge Pocket:**
- Bounding box guide on/off + width × height (overall pocket dimensions)
- Distance-to-edge offsets: top, bottom, inside, outside (mm) — defines the anchor
  frame used when auto-positioning imported hinge pockets into Front/Temple drawings.

### File model — `.gdraw` ZIP

**Decided: Option 2.** A `.gdraw` file is a ZIP archive containing:

```
project.gdraw
├── manifest.json
├── front.svg
├── temple.svg
└── hinge.svg
```

`manifest.json`:
```json
{
  "version": 1,
  "guilddraw_version": "0.14.0",
  "tabs": ["front", "temple", "hinge"],
  "active_tab": "front"
}
```

Each SVG uses the existing `save_svg` / `load_svg` format unchanged. A tab with no
geometry still saves an empty (but valid) SVG. Backward compat: lone `.svg` files
still open as before (single-tab mode, Front workspace only).

### DXF export

Each tab exports independently via the existing DXF pipeline. The Frame Front DXF
follows the existing contract (OUTLINE ×1, LENS ×2 when mirrored, etc.). The Temple
DXF uses the same layer vocabulary; OUTLINE represents the temple arm silhouette.
GuildCAM project setup maps each DXF to the correct stock piece.

---

## 19. Hinge pocket library (Phase 15)

A personal library of reusable hinge cutout designs, stored locally and importable
into any workspace.

### Library storage

```
~/.guilddraw/
└── library/
    └── hinges/
        ├── barrel_3hole_std.svg
        ├── barrel_5hole_wide.svg
        └── euro_flex.svg
```

Each entry is a standard GuildDraw SVG file (hinge pocket tab export). The filename
(minus extension) is the display name; the file's SVG `<title>` element provides a
longer description.

### Library panel

The **Hinge Library** is the 5th tab of the right sidebar (always visible across all
workspaces). Its content adapts based on the active workspace:

**All workspaces (Front, Temple, Hinge Pocket):**
- Scrollable list of saved designs, each showing name, geometry thumbnail, and date saved.
- **Import into Workspace** — inserts the selected entry's geometry into the active
  canvas. Geometry arrives as regular curves on layer HINGE, fully editable. Positioned
  relative to the hinge pocket's distance-to-edge anchor frame if that metadata is
  present; otherwise centered at canvas origin.

**Hinge Pocket workspace only (additional actions):**
- **Save Current Pocket to Library…** — prompts for a name, writes the active Hinge
  Pocket tab's geometry to the library folder as a new SVG.
- **Rename** / **Delete** — manage existing entries.
- **Open in New Tab** — opens the library SVG in a new Hinge Pocket tab for editing.

### Import behavior

On import, the hinge pocket geometry is translated so its bounding-box center lands at
the drop point. The designer then moves/rotates it to align with the frame's hinge
location. A future enhancement could add a "snap to hinge node" option that aligns a
designated reference point on the pocket to a selected node on the frame outline.

### Modules (not yet created)

- `framedraft/library.py` — `HingeLibrary`: scan folder, save entry, load entry,
  delete entry, generate thumbnail pixmap from SVG path data.
- `framedraft/canvas/library_panel.py` — `LibraryDock(QDockWidget)`: list widget,
  thumbnail rendering, save/import/delete actions.

### Future extension

The local library folder structure is intentionally simple so it can later be synced
with a guild-hosted shared library (a curated set of standard hinge types distributed
via HTTP or a guild server). Shared entries would be read-only; local entries remain
editable.

---

## 20. Split at node / Explode (Phase 10b)

Lightweight curve-breaking operations that require no intersection math. Both build
on the node-selection infrastructure added in Phase 10.

### Split at selected node

**Goal**: break a curve into two open curves at the currently selected NodeDot.

**Workflow**:
1. Select a curve so its NodeDots are visible.
2. Click a NodeDot to select it (it turns red — existing Phase 10 behaviour).
3. Click a **Split** toolbar button (or shortcut), or a context menu item.
4. The curve is replaced by two open curves that share the split node as an endpoint.

**Algorithm** (no Shapely needed):

```python
left  = Curve(kind=curve.kind, layer=curve.layer,
              nodes=curve.nodes[:idx + 1], closed=False)
right = Curve(kind=curve.kind, layer=curve.layer,
              nodes=curve.nodes[idx:],    closed=False)
```

For a **closed** curve, splitting at node `idx` produces a single open curve:
```python
# Rotate the node list so idx is both first and last, then open it
rotated = curve.nodes[idx:] + curve.nodes[:idx + 1]
result  = Curve(..., nodes=rotated, closed=False)
```

The split node's `cp_in` / `cp_out` handles are preserved on both halves, so
the spline tangent at the break point is retained.

**Undo**: standard `_push_undo_snapshot()` before mutation.

### Explode

**Goal**: break any curve into individual 2-node segments. Useful after a Join
when the designer wants to work on individual pieces again.

**Workflow**: select one or more curves, click **Explode** toolbar button.

**Algorithm**:

```python
segments = []
n = len(curve.nodes)
pairs = range(n - 1)
if curve.closed:
    pairs = range(n)       # last segment wraps first → last node
for i in pairs:
    a = curve.nodes[i]
    b = curve.nodes[(i + 1) % n]
    seg = Curve(kind=curve.kind, layer=curve.layer,
                nodes=[copy(a), copy(b)], closed=False)
    segments.append(seg)
```

Each segment keeps the `cp_out` of its start node and the `cp_in` of its end
node, so spline segment shapes are preserved exactly.

### UI

Add to the toolbar (between Join and Fit):

- **Split** button — enabled only when exactly one curve is selected AND a node
  is selected. Tooltip: "Split curve at the selected node."
- **Explode** button — enabled when one or more curves are selected. Tooltip:
  "Break selected curve(s) into individual segments."

Both operations return to Select mode automatically and leave the resulting
curves selected.

### Modules

No new files needed. Implement in `app.py` as `_split_at_node()` and
`_explode_selected()`, following the same pattern as `_join_selected_curves()`.

---

## 21. Toolbar customization + hotkey assignment (Phase 13b)

UI polish phase that makes the toolbar and keyboard shortcuts user-configurable.
No new geometry or document-model changes.

### 21a. Rename and visibility

- **"Duplicate Mirror" → "Mirror"** — the bake-mirror operation is the primary
  meaning of "mirror" in day-to-day use; rename the toolbar action label and tooltip.
  The live ghost toggle already labelled "Mirror" should be distinguished; consider
  renaming it **"Ghost"** or **"Preview"** to avoid confusion now that "Mirror" is an
  action rather than a toggle.
- **Mirror-Close hidden by default** — a specialty operation used rarely; not shown
  unless the user enables it in the Toolbar settings tab.

### 21b. Settings dialog — Toolbar tab

The existing `SettingsDialog` (currently a flat `QFormLayout` inside a scroll area)
is converted to a `QTabWidget`. Existing content becomes the **General** tab.
Two new tabs are added: **Toolbar** and **Hotkeys**.

**Toolbar tab** — a scrollable `QListWidget` (or `QTableWidget`) of all toolbar
actions with a checkbox per row:

| Checkbox | Action label | Notes |
|----------|-------------|-------|
| ☑ | Select | always visible, not user-hideable |
| ☑ | Line | |
| ☑ | Spline | |
| ☑ | Circle | |
| ☑ | Arc | |
| ☑ | Dim | |
| ☑ | Trim | |
| ☑ | Split Curve | |
| ☑ | Mirror (toggle) | |
| ☑ | Guides | |
| ☑ | Snap | |
| ☑ | Smooth Handles | |
| ☑ | Boxing | |
| ☑ | Stock | |
| ☑ | Pad | |
| ☑ | Mirror | the bake operation |
| ☐ | Mirror-Close | **hidden by default** |
| ☑ | Join | |
| ☑ | Snap Node | |
| ☑ | Split at Node | |
| ☑ | Explode | |
| ☑ | Fit | |

Visibility state is stored in `prefs.json` under a `"toolbar"` dict keyed by action
name. Applied at startup and whenever the dialog is accepted. Hiding a button calls
`QAction.setVisible(False)`; the action remains functional via its hotkey.

### 21c. Settings dialog — Hotkeys tab

A two-column table: **Action** | **Key**. Each row shows the action label and an
editable key field. Clicking the key field and pressing a key captures it (no
modifier required for single-letter shortcuts). Shift/Ctrl/Alt combinations are
allowed. An empty field means no hotkey for that action.

Keys are stored in `prefs.json` under a `"hotkeys"` dict and applied at startup via
`QShortcut` (window-scope) mapped to the relevant `QAction.trigger()`.

**Default assignments:**

| Key | Action |
|-----|--------|
| `L` | Line tool |
| `S` | Spline tool |
| `C` | Circle tool |
| `A` | Arc tool |
| `D` | Dim tool |
| `T` | Trim tool |
| `X` | Split Curve tool |
| `E` | Snap Node to Endpoint (already hardcoded; move to hotkey system) |
| — | Mirror (bake) — no default; uncommon enough to be click-only |
| — | Move tool (Phase 16) — no hotkey; interaction is click-drag on the curve |

The following are **not** user-reassignable (hardcoded Qt actions):

| Key | Action |
|-----|--------|
| `Ctrl+Z` | Undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |
| `Del` / `Backspace` | Delete selected |
| `Esc` | Cancel / return to Select |

### 21d. Implementation notes

- `prefs.py` gains two new top-level keys: `"toolbar"` (dict of bool per action name,
  defaults all `True` except `mirror_close: False`) and `"hotkeys"` (dict of str per
  action name, defaults as above).
- `MainWindow.__init__` applies toolbar visibility and registers `QShortcut` objects
  after the toolbar is built. Store shortcuts in `self._shortcuts` dict so they can
  be torn down and rebuilt when settings change.
- The hotkey capture widget can be a custom `QLineEdit` subclass that overrides
  `keyPressEvent` to record the pressed key and format it as a human-readable string
  (`"L"`, `"Ctrl+D"`, etc.) without inserting characters.
- Conflicts (same key assigned to two actions) should be flagged inline with a red
  background on both rows; the dialog accept button is disabled until resolved.
- `QAction.setShortcut()` is **not** used (it fires on key-down in any focused widget);
  window-scope `QShortcut` with `Qt.ShortcutContext.WindowShortcut` is correct and
  consistent with the existing Ctrl+Z/Y/Z implementation.

---

## 22. Offset tool (Phase 17)

Creates a new curve that runs parallel to an existing curve at a fixed offset distance.
Primary use case: drawing scallop boundaries, extrusion rails, and shell thicknesses
from existing OUTLINE or LENS geometry.

### Behavior

- **Activation**: toolbar button (icon `op-offset.svg`) or hotkey `O`.
- **Workflow**: select one curve, activate Offset tool, type or drag the offset distance
  (positive = outward / left-normal, negative = inward / right-normal), press Enter or
  click to confirm. A preview of the offset curve is shown in amber before confirmation.
- **Input types supported**: line, spline, open curve, closed curve. Circle and arc
  support is a stretch goal (can use analytical offset for circles; arcs are trivial).
- **Output**: a new `Curve` on the same layer as the source curve, with `mirrored = False`.
  The source curve is left unchanged. Result is pushed as a single undoable step.

### Algorithm

#### Lines

Each segment's offset is the segment shifted perpendicular to its direction by the
offset distance. For a polyline, adjacent offset segments are intersected (or extended)
to produce clean mitered joins at each node:

```python
def offset_line_segment(a, b, d):
    dx, dy = b.x - a.x, b.y - a.y
    length = hypot(dx, dy)
    nx, ny = -dy / length, dx / length   # left-hand normal
    return (a.x + nx*d, a.y + ny*d,
            b.x + nx*d, b.y + ny*d)
```

Miter join: intersect the two adjacent offset segments as infinite lines. Fall back to
a bevel join if the miter ratio exceeds a threshold (e.g., miter > 10× offset distance).

#### Splines

Offset each node position along its averaged normal (average of the normals of the two
adjacent segments meeting at that node). Recompute Catmull-Rom handles on the offset
node list for smooth results. This approximation is visually accurate for typical frame
curves; for high-precision offset (e.g., machining offset), a future enhancement can
use Shapely's `parallel_offset` as a fallback and re-fit the spline.

```python
def node_normal(prev, node, next):
    # Average of the two segment left-normals at this node
    n1 = left_normal(prev, node)
    n2 = left_normal(node, next)
    avg = normalize((n1[0]+n2[0], n1[1]+n2[1]))
    return avg

def offset_spline_nodes(nodes, closed, d):
    result = []
    n = len(nodes)
    for i, nd in enumerate(nodes):
        prev = nodes[(i - 1) % n] if (closed or i > 0) else nd
        nxt  = nodes[(i + 1) % n] if (closed or i < n-1) else nd
        nx, ny = node_normal(prev, nd, nxt)
        result.append(SplineNode(nd.x + nx*d, nd.y + ny*d))
    compute_catmull_handles(result, closed=closed)
    return result
```

#### Node count

The offset curve has the **same number of nodes** as the input curve. No node
insertion or removal is performed. If the offset creates self-intersections (e.g., a
very large inward offset on a tight curve), the geometry is still produced; the user is
responsible for trimming if needed.

### Input dialog / HUD

Reuses the floating HUD pattern from Phase 12. After activating the tool with a curve
selected, a single-field HUD appears:

```
[ Offset: ______ mm ]   (+ = outward, − = inward)   [Enter = confirm]
```

Dragging on the canvas (left = inward, right = outward relative to curve direction)
also sets the offset distance live, showing the amber preview curve.

### Edge cases

- **Closed curves**: offset outward expands the shape; offset inward contracts it. The
  result remains closed.
- **Open curves with sharp corners**: miter join with bevel fallback (see Lines above).
- **Zero offset**: silently no-ops (no new curve created).
- **Degenerate offset** (self-intersecting result): produce the curve anyway; the user
  can Trim as needed. Optionally show a status bar warning.

### Modules

- Implement `offset_curve(curve: Curve, d_mm: float) -> Curve` in `framedraft/geometry.py`.
- `OffsetTool` in `framedraft/tools/offset.py`: tool activation, HUD display, amber
  preview `CurveItem`, Enter/drag confirmation, undo snapshot.
- Wire into `app.py`: toolbar action, icon, hotkey `O`, undo integration.

---

## 23. Copy / Paste / Duplicate + Scale / Rotate (Phase 18)

### 23a. Copy / Paste / Duplicate

An in-memory clipboard on `MainWindow` (shared across workspaces) holds deep-copied
`Curve` + `DimLine` lists. Clipboard survives workspace tab switches; pasting into a
different workspace works naturally because curves are plain dataclasses.

| Action | Shortcut | Behavior |
|--------|----------|----------|
| Copy | Ctrl+C | Deep-copy selected curves + dims into `self._clipboard` |
| Paste | Ctrl+V | Insert clipboard contents into active workspace, offset +5 mm in x and y |
| Duplicate | Ctrl+D | Copy + paste in one step at the same +5 mm offset |

Paste pushes an undo snapshot before inserting. Pasting with an empty clipboard is a
no-op (no error). The pasted curves are immediately selected so the user can reposition
them.

**Files changed:**
- `framedraft/app.py`: add `self._clipboard: list = []`; add `_copy_selected`,
  `_paste`, `_duplicate_selected` methods; wire `QShortcut` for Ctrl+C/V/D after the
  existing Ctrl+Z/Y shortcuts in `__init__`; add Copy / Paste / Duplicate to the
  Edit menu.
- No other files needed — curves are plain dataclasses, deep-copy works without
  special support.

### 23b. Scale / Rotate (Transform dialog)

A modal **Transform** dialog. Exact numeric input is appropriate for eyeglass CAD
where visual interactive handles would be imprecise.

**Fields:**
- Scale X (%) — default 100
- Scale Y (%) — default 100; checkbox "Lock aspect ratio" (ties X to Y)
- Rotation (°) — positive = CCW in screen space (matches scene Y-down convention)
- Pivot — radio: "Bounding-box centre" (default) | "Scene origin (0, 0)"

**Apply math** (all nodes + control points):

```python
# Rotation by angle θ (radians) around pivot (px, py):
dx = x - px;  dy = y - py
x' = px + dx * cos(θ) - dy * sin(θ)
y' = py + dx * sin(θ) + dy * cos(θ)

# Scale (sx, sy) around pivot:
x' = px + (x - px) * sx
y' = py + (y - py) * sy

# Both together: scale first, then rotate (or compose into a single matrix).
```

Both transforms are applied to every `SplineNode` x/y and every `ControlPoint` x/y
in each selected curve. Arc/circle curves update `nodes[0]` (center); for **uniform
scale** (sx == sy), `radius` is multiplied by `sx`. For **non-uniform scale** of a
circle or arc, the result is an ellipse, which is not representable as a `Curve` circle
— **convert to a 4-segment cubic Bézier spline approximation** (standard 0.00273%
error) and change `kind` to `"spline"`. The conversion function:

```python
def circle_to_spline(cx, cy, r, layer, line_weight) -> Curve:
    # 4 Bézier segments approximating a circle; k = 0.5522847498
    k = 0.5522847498 * r
    nodes = [
        SplineNode(cx,   cy-r, cp_in=ControlPoint(cx+k, cy-r),
                               cp_out=ControlPoint(cx-k, cy-r)),
        SplineNode(cx-r, cy,   cp_in=ControlPoint(cx-r, cy-k),
                               cp_out=ControlPoint(cx-r, cy+k)),
        SplineNode(cx,   cy+r, cp_in=ControlPoint(cx-k, cy+r),
                               cp_out=ControlPoint(cx+k, cy+r)),
        SplineNode(cx+r, cy,   cp_in=ControlPoint(cx+r, cy+k),
                               cp_out=ControlPoint(cx+r, cy-k)),
    ]
    return Curve(kind="spline", layer=layer, nodes=nodes,
                 closed=True, line_weight=line_weight)
```

After conversion, the non-uniform scale is applied to the spline nodes normally. Arcs
are converted similarly (arc segment to single spline segment via de Casteljau).

**Files changed:**
- `framedraft/app.py`: add `TransformDialog(QDialog)` class (~80 lines); add
  `_transform_selected()` method; add `_circle_arc_to_spline(curve) -> Curve` helper;
  add "Transform…" to the Edit menu (below Redo); push undo snapshot before applying.

**Decisions:**
- Non-uniform scale of circles/arcs: **convert to spline** (confirmed).
- Transform is Edit-menu-only for now; hotkey `Ctrl+T` optional.

---

## 24. Temple R + Temple L Workspaces + Mirror Copy (Phase 19)

### 24a. Workspace restructure

Change from three workspaces `[front, temple, hinge]` to four:
`[front, temple_r, temple_l, hinge]`.

Tab labels: **Frame Front** · **Temple R** · **Temple L** · **Hinge Pocket**

**`framedraft/document.py`** — update `WORKSPACE_LAYERS`:
```python
WORKSPACE_LAYERS = {
    "front":    [Layer.OUTLINE, Layer.LENS,      Layer.SCULPT, Layer.HINGE, Layer.REF],
    "temple_r": [Layer.OUTLINE, Layer.ENGRAVING, Layer.SCULPT, Layer.HINGE, Layer.REF],
    "temple_l": [Layer.OUTLINE, Layer.ENGRAVING, Layer.SCULPT, Layer.HINGE, Layer.REF],
    "hinge":    [Layer.HINGE,   Layer.REF],
}
```

**`framedraft/export/gdraw.py`** — update `_TAB_NAMES`:
```python
_TAB_NAMES = ["front", "temple_r", "temple_l", "hinge"]
```

**Backward compatibility** — when loading an old `.gdraw` that contains `temple.svg`
but not `temple_r.svg`, load `temple.svg` into `temple_r` and leave `temple_l` empty.
Add a check in `load_gdraw`: if `"temple.svg" in zf.namelist()` and
`"temple_r.svg" not in zf.namelist()`, treat `temple.svg` as `temple_r`.

**`framedraft/app.py`** — workspace creation:
```python
for ws_type, label in [
    ("front",    "Frame Front"),
    ("temple_r", "Temple R"),
    ("temple_l", "Temple L"),
    ("hinge",    "Hinge Pocket"),
]:
    ...
```

All occurrences of `workspace_type == "temple"` become
`workspace_type in ("temple_r", "temple_l")`.

Workspace-specific defaults applied to **both** temple workspaces:
- Stock guide visible, 160×30 mm.
- Construction guides, boxing guide, pad guide: hidden.
- Horizontal mirror axis.

Measurements: temple length + endpiece width shown for both `temple_r` and
`temple_l`. The measurement box label changes to "Temple R" / "Temple L" based on
which tab is active.

### 24b. Mirror Copy tool

A toolbar button **"Mirror Copy →"** (or a menu item under Edit) that:

1. Is shown only when the active workspace is `temple_r` or `temple_l`.
   - In `temple_r`: copies R → L, label "Copy → Temple L".
   - In `temple_l`: copies L → R, label "Copy → Temple R".
2. If the target workspace has existing content, shows a confirmation dialog:
   "Replace Temple L content? This cannot be undone." Cancel aborts.
3. Deep-copies all curves + dims from the current temple workspace.
4. Horizontally flips each curve across x = 0 (reflect through the Y axis):
   - All node x-coordinates: `x → −x`
   - All control point x-coordinates: `x → −x`
   - For `kind == "circle"`: center x negated, radius unchanged.
   - For `kind == "arc"`: center x negated; angles transformed by
     `θ → 180° − θ` with start/end swapped (same as the existing `_mirror_curve`
     function with `axis_x = 0`). **Reuse `_mirror_curve(curve, 0.0)` directly.**
5. Clears the target workspace (removes all curves + dims, clears undo stack).
6. Places the flipped curves + dims in the target workspace.
7. Pushes an undo snapshot in the target workspace.
8. Switches the tab widget to the target workspace.

The flip is equivalent to calling the existing `_mirror_curve(curve, 0.0)` on each
curve. No new mirroring math is needed.

**Files changed:**
- `framedraft/document.py`: update `WORKSPACE_LAYERS`.
- `framedraft/export/gdraw.py`: update `_TAB_NAMES`; add backward-compat load branch.
- `framedraft/app.py`: workspace creation list; all `"temple"` checks; `_show_guide_sections`;
  measurements; add `_act_copy_temple` action + `_copy_temple_to_other()` method;
  add action to toolbar (after Mirror-Close) and wire visibility to temple workspaces.
- `framedraft/prefs.py`: add `"copy_temple": True` to `DEFAULTS["toolbar"]`; add to
  `_TOOLBAR_ACTION_DEFS` in app.py.

**Open questions:**
- Hinge pocket R/L variants: **confirmed single workspace**. Directional hinges are
  saved as two named library entries. No second Hinge Pocket tab needed.
- Flip axis: `x = 0` (the scene origin). Confirm this is correct for the temple
  coordinate convention (hinge end near origin, tip extending in +x direction).

---

## 25. Frame Fill / Render Overlay (Phase 20)

### Purpose

Visualize the frame on a face photo by filling the frame interior with a translucent
solid color, so the designer can see how the frame looks before any material is cut.
This is a **display-only** feature — fill is never exported to DXF, SVG, or PNG
(PNG export renders the scene as-is; add a separate "render PNG with fill" option if
needed later).

### What gets filled — Front workspace

Fill shape is built from **OUTLINE** and **LENS** curves:
1. Union all OUTLINE paths (including ghost mirror paths if Ghost is enabled) into one
   combined path.
2. Subtract all LENS paths (even-odd fill rule makes lens apertures transparent).
3. The resulting path is the frame "lenticle" interior.

If only half the frame is drawn (open OUTLINE curve snapped to the mirror axis), the
ghost (mirrored) half from `FrameScene._update_ghosts` provides the other side.
Both halves are combined with `QPainterPath.united()` before lens subtraction.

### What gets filled — Temple workspace

Fill shape is built from OUTLINE curves only (no lens aperture). This lets the designer
see the temple arm opaque against the face photo.

### Scene implementation

Add `FillItem(QGraphicsPathItem)` to `FrameScene`:

```python
class FillItem(QGraphicsPathItem):
    def __init__(self, parent_scene):
        super().__init__()
        self._scene = parent_scene
        self.setZValue(-0.5)   # above face images (z=-1), below curves (z=0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        parent_scene.addItem(self)

    def update_fill(self, outline_curves, lens_curves, ghost_paths, fill_color, opacity):
        # Build combined path from OUTLINE (real + ghost) minus LENS
        combined = QPainterPath()
        for c in outline_curves:
            combined = combined.united(build_path(c))
        for gp in ghost_paths:           # QPainterPath objects, already computed
            combined = combined.united(gp)
        for c in lens_curves:
            combined = combined.subtracted(build_path(c))
        self.setPath(combined)
        color = QColor(fill_color)
        color.setAlphaF(opacity)
        self.setBrush(QBrush(color))
        self.setPen(Qt.PenStyle.NoPen)
```

`FrameScene` new public methods:
```python
scene.set_fill_visible(bool)         # show/hide the FillItem
scene.set_fill_color(QColor)         # set fill brush color (opacity applied separately)
scene.set_fill_opacity(float)        # 0.0–1.0
scene.rebuild_fill()                 # recompute path; called after add/remove/refresh curve
                                     # and after mirror state changes
```

`rebuild_fill` is called at the end of `add_curve`, `remove_curve`, `refresh_curve`,
and `set_mirror_display`. It is a no-op when fill is not visible (skip computation).

### Properties panel UI

Add a **"Frame Fill"** group box in the **Properties tab** of the sidebar, visible only
for Front and Temple workspaces (`_show_guide_sections` controls visibility).

Controls:
- Checkbox: "Show fill" (default off)
- Color button: opens `QColorDialog`; shows a 16×16 px color swatch inline
- Opacity slider: 0–100 %, default 50 %

State is stored in `WorkspaceState`:
```python
ws.fill_visible: bool   = False
ws.fill_color:   QColor = QColor("#2a6099")   # a frame-blue default
ws.fill_opacity: float  = 0.50
```

State is saved/restored on tab switch via `_save_ws_sidebar_state` /
`_restore_ws_sidebar_state`. Fill state **is persisted to `.gdraw`** (confirmed).

The three fill fields are added to the SVG `<metadata>` JSON blob per workspace:
```json
"fill": { "visible": false, "color": "#2a6099", "opacity": 0.50 }
```
`save_svg` writes the key; `load_svg` reads it with a safe default (not visible) when
the key is absent (backward compat with older files).

### Files changed

- `framedraft/canvas/scene.py`: add `FillItem`, `set_fill_visible`, `set_fill_color`,
  `set_fill_opacity`, `rebuild_fill`; call `rebuild_fill` from `add_curve`,
  `remove_curve`, `refresh_curve`, `set_mirror_display`.
- `framedraft/app.py`: add fill group box in `_build_side_panel`; show/hide in
  `_show_guide_sections`; save/restore in `_save_ws_sidebar_state` /
  `_restore_ws_sidebar_state`; add `fill_visible`, `fill_color`, `fill_opacity` to
  `WorkspaceState.__init__`.

**Risk:** `QPainterPath.united()` / `subtracted()` use Qt's boolean path operations.
These are reliable for simple convex/mildly concave shapes (typical frame geometry)
but can misbehave on highly self-intersecting paths. Test with real frame geometry
before committing to this approach. Fallback: use even-odd fill rule on a single
combined path rather than explicit subtraction.

---

## 26. Text Insertion — ENGRAVING Layer (Phase 21)

### Design decisions

**Outline font approach** (Phase 21): Use `QPainterPath.addText()` to convert any
installed system font into cubic Bézier outlines. These are closed filled-letter shapes,
suitable for pocket engraving or laser-fill operations. Zero external dependencies.

**Single-stroke (stick) fonts** (future phase): Hershey fonts or similar produce open
stroke paths — one pass per stroke — ideal for single-pass CNC engraving. Requires
bundling a font data file. Defer to a later phase.

### Tool flow

New `TextTool` in `framedraft/tools/text.py`:

1. User activates Text tool (toolbar button, hotkey `I`).
2. Clicks a point on the canvas — this is the text baseline left anchor.
3. A small placement dialog appears (not modal canvas-blocker; a floating `QDialog`):
   - Text string (QLineEdit)
   - Font family (QFontComboBox, filtered to outline fonts)
   - Size in mm (QDoubleSpinBox, range 1–50 mm, default 5 mm)
   - Rotation in degrees (QDoubleSpinBox, default 0°)
4. On OK, convert text → curves and emit `curves_added(list[Curve])` signal
   (same pattern as `DrawTool.curve_added`).
5. Returns to Select mode; new curves are selected.

Text tool is only available when the active layer is `ENGRAVING` (or any layer that
makes sense for text); no layer filtering required since layer is taken from the combo.

### Conversion: QPainterPath → Curve objects

```python
from PySide6.QtGui import QPainterPath, QFont

# 1. Build the path at origin
path = QPainterPath()
size_pt = size_mm * 72.0 / 25.4
font = QFont(family)
font.setPointSizeF(size_pt)
path.addText(0.0, 0.0, font, text)

# 2. Apply rotation around the anchor
if rotation_deg != 0.0:
    t = QTransform().rotate(rotation_deg)
    path = t.map(path)

# 3. Translate to anchor point
path.translate(anchor_x, anchor_y)

# 4. Extract sub-paths (one per letter outline or counter)
curves = []
i = 0
n = path.elementCount()
nodes = []
while i < n:
    el = path.elementAt(i)
    if el.type == QPainterPath.ElementType.MoveToElement:
        if nodes:
            curves.append(Curve(kind="spline", layer=layer,
                                nodes=nodes, closed=True))
            nodes = []
        nodes = [SplineNode(x=el.x, y=el.y)]
        i += 1
    elif el.type == QPainterPath.ElementType.LineToElement:
        nodes.append(SplineNode(x=el.x, y=el.y))
        i += 1
    elif el.type == QPainterPath.ElementType.CurveToElement:
        # CurveToElement: c1 (el), c2 (el+1), endpoint (el+2)
        c1 = path.elementAt(i)
        c2 = path.elementAt(i + 1)
        ep = path.elementAt(i + 2)
        # cp_out of previous node, cp_in of new endpoint node
        if nodes:
            nodes[-1].cp_out = ControlPoint(c1.x, c1.y)
        nodes.append(SplineNode(
            x=ep.x, y=ep.y,
            cp_in=ControlPoint(c2.x, c2.y)
        ))
        i += 3
if nodes:
    curves.append(Curve(kind="spline", layer=layer, nodes=nodes, closed=True))
```

Each sub-path of `QPainterPath.addText` is a separate letter outline or interior
counter-shape (e.g., the hole in "O"). All become individual `Curve` objects on the
selected layer. These are permanent geometry — there is no re-edit of the text string
after placement (delete and re-insert to change text).

### SVG font size conversion

`size_pt = size_mm × 72.0 / 25.4`

A 5 mm capital letter height corresponds to approximately 14.2 pt (at standard
12 pt → ~4.2 mm cap height; the user enters the desired visual size in mm and the
tool sizes the font to match).

**Note:** The conversion from point size to rendered mm cap height varies by font
(x-height vs. cap height vs. em size differences). For accuracy, consider measuring
the rendered path bounding box and rescaling to the desired height. Add this as a
refinement if the initial implementation shows visible size errors.

### Files changed

- **New file** `framedraft/tools/text.py`: `TextTool(QObject)` with `curves_added`
  signal and placement dialog.
- `framedraft/app.py`: import `TextTool`; add `_act_text` toolbar action; add
  `_set_tool_text` / `_on_text_curves_added` methods; add `"text": "I"` to
  `_HOTKEY_ACTION_DEFS`; wire tool signal + deactivation logic.
- `framedraft/prefs.py`: add `"text": "I"` to `DEFAULTS["hotkeys"]`;
  add `"text": True` to `DEFAULTS["toolbar"]`.

### TextObject dataclass

Text insertions are stored as `TextObject` (re-editable), not as permanent curves.
Add to `framedraft/document.py`:

```python
@dataclass
class TextObject:
    text:        str
    family:      str
    size_mm:     float
    rotation:    float          # degrees, CCW
    anchor_x:    float          # baseline-left origin in scene mm
    anchor_y:    float
    layer:       Layer = Layer.ENGRAVING
    line_weight: float = 1.0
```

`WorkspaceState` gains a `doc_texts: list[TextObject]` alongside `doc_curves` and
`doc_dims`.  Each workspace tab tracks its own list; undo/redo snapshots include it
(deep-copy alongside curves and dims).

### Scene representation

A `TextItem(QGraphicsItem)` in `framedraft/canvas/scene.py` renders each `TextObject`
by calling the same `QPainterPath.addText()` → outline-path conversion used at
insertion time, so the canvas always matches what will be exported.  `TextItem` is
selectable and deletable.  Double-clicking a `TextItem` re-opens the placement dialog
pre-filled with the stored values, allowing the text, font, size, and rotation to be
changed in-place (push undo snapshot first).

`FrameScene` gains:
```python
scene.add_text(text_obj)       # creates and adds a TextItem
scene.remove_text(text_obj)    # removes the TextItem
scene.refresh_text(text_obj)   # redraws after a property change
```

### DXF export

At DXF export time, each `TextObject` is converted to curves on the fly:
```python
for t in ws.doc_texts:
    curves = text_to_curves(t)   # same QPainterPath conversion
    for c in curves:
        _add_curve(msp, c)
```
No `TextObject` data is written to the DXF — the file receives only `SPLINE` /
`LWPOLYLINE` entities on the `ENGRAVING` layer, exactly as a CAM tool expects.

### SVG / .gdraw persistence

`TextObject` instances are serialized in the SVG `<metadata>` JSON under a `"texts"`
key, alongside `"curves"` and `"dims"`:
```json
"texts": [
  { "text": "LEFT", "family": "Arial", "size_mm": 5.0,
    "rotation": 0.0, "anchor_x": 12.3, "anchor_y": -4.1,
    "layer": "ENGRAVING", "line_weight": 1.0 }
]
```
`save_svg` / `load_svg` are updated to round-trip this key.  Files without the key
load with an empty text list (backward compat).

### Files changed

- `framedraft/document.py`: add `TextObject` dataclass.
- `framedraft/canvas/scene.py`: add `TextItem`, `add_text`, `remove_text`,
  `refresh_text`.
- **New file** `framedraft/tools/text.py`: `TextTool(QObject)` with placement dialog
  and `texts_added(list[TextObject])` signal.
- `framedraft/export/svg.py`: serialize/deserialize `"texts"` key.
- `framedraft/export/dxf.py`: add `text_to_curves` helper; call it during export.
- `framedraft/app.py`: add `doc_texts` to `WorkspaceState`; import `TextTool`; wire
  `_act_text`, `_set_tool_text`, `_on_texts_added`; include texts in undo snapshots,
  `_new`, `_load_ws_data`, `_ws_to_data_dict`; handle double-click on `TextItem` for
  re-edit.
- `framedraft/prefs.py`: add `"text": "I"` to `DEFAULTS["hotkeys"]`; add `"text": True`
  to `DEFAULTS["toolbar"]`.

### Deferred

- **Single-stroke fonts**: bundle a Hershey font JSON in a later phase; add a "stroke
  mode" toggle to the placement dialog.
