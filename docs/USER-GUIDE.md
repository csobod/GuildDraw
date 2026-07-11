# GuildDraw User Guide (v1.0.0-rc4)

GuildDraw drafts eyewear in true millimetres. Everything you draw is at 1:1
scale; the DXF you export is what the CNC cuts.

## 1. The four workspaces

A GuildDraw project (`.gdraw`) holds four tabs, each with its own canvas,
layers, guides, and undo history:

| Tab | Purpose | Machined layers |
|---|---|---|
| **Frame Front** | The front: outline + lenses | `OUTLINE` ×1, `LENS` ≥1 |
| **Temple R / L** | Each temple arm | `OUTLINE` ×1, optional `HINGE`, `ENGRAVING` |
| **Hinge Pocket** | Hinge recess geometry | `HINGE` ≥1 |

At least one `LENS` contour is required for a GuildModel-ready front (a classic
pair is two; aviators and other shapes may carry more). The validator checks
these rules per workspace and drives the readiness dot, but it no longer blocks
export — you decide when the geometry is complete and GuildModel's intake is the
final gate.

**Mirror Copy** (toolbar, temple workspaces) copies Temple R to Temple L (or
back) mirrored, so you draw one temple and stamp the other.

## 2. Drawing

Draw at real size. The origin cross is (0,0); for the frame front, the bridge
mirror axis is the vertical through x=0.

| Tool | Default key | Notes |
|---|---|---|
| Select | Esc / toolbar | Click selects; drag rubber-bands; Alt+click cycles overlapping items |
| Line | `L` | Click points; Enter/double-click ends; close by clicking the first point |
| Spline | `S` | Centripetal Catmull-Rom through clicked points; smooth handles editable afterwards |
| Circle | `C` | Click centre, click/type radius |
| Arc | `A` | Centre, radius, start/end angles |
| Dimension | `D` | Linear dimension between two snapped points; arrowed ends, drag the label to offset it |
| Trim | `T` | Click the segment to remove between intersections |
| Split | `X` | Split a curve at a clicked point |
| Offset | `O` | Type a distance, amber preview, Enter confirms. On a closed shape, positive is always outward and negative is always inward, whichever way the curve was drawn |
| Point Move | `G` | Grab a point (snapped), click destination or type exact X/Y |
| Move gizmo | `M` | Drag selection with exact-distance HUD |
| Text | `I` | ENGRAVING text (temples only); double-click to re-edit |
| Snap node→endpoint | `E` | Snap a node onto another curve's endpoint |

All hotkeys are reassignable in **Settings → Hotkeys**; toolbar buttons can be
hidden per-button in **Settings → Toolbar**.

### Editing

- **Nodes & handles**: with Select active, drag nodes; drag Bézier handles to
  shape curves. "Smooth" toggle keeps handle pairs tangent.
- **Join / Explode / Split-at-node**: merge open curves end-to-end, break a
  multi-segment curve apart, or split at a selected node.
- **Group / Ungroup** (`Ctrl+G` / `Ctrl+Shift+G`): grouped curves select and
  move as a rigid unit (hinge imports arrive grouped for this reason).
- **Copy / Paste / Duplicate** (`Ctrl+C/V/D`): works across workspaces; layers
  that don't exist in the target workspace land on REF.
- **Transform** (`Ctrl+T`): scale X/Y % (aspect lock), rotate, pivot at
  selection centre or origin.
- **Undo / Redo**: `Ctrl+Z` / `Ctrl+Y`, per workspace.

### Snapping

The **Snap** button is the master on/off; holding `Ctrl` suspends snapping
while held. The **Snap Types** button beside it opens the *snap palette* — a
pinnable pop-out that chooses *which* targets snap (hover a button for its
name) and sets the snap radius (the magnet + `r` field):

- **Endpoint** — open-curve ends and arc endpoints (green).
- **Node** — interior and closed-curve nodes.
- **Midpoint** — line-segment midpoints (orange).
- **Center / Quadrant** — circle and arc centres and 0/90/180/270° points.
- **Intersection** — where two curves cross (orange-red ×).
- **Tangent / Perpendicular** — measured from the point you are drawing, so
  they light up only mid-line/spline: tangent touch points on circles/arcs,
  and perpendicular feet on lines, circles, and splines.
- **Handle** — Bézier control points (blue).
- **On-curve** — nearest point along a curve (steel-blue diamond; fallback
  when no point target is in reach).
- **Grid** — nearest grid intersection, in empty space only (see *Grid* below).
- **Mirror axis** (red) and **Origin** (purple).

Palette choices persist across sessions. Hidden layers are never snap
targets; locked layers still snap (reference geometry).

### Grid

The **Grid** toolbar button overlays a millimetre grid (minor lines with a
heavier major line every Nth division; shipped default is 2 mm spacing with a
major line every 10 mm). Spacing, divisions, minor/major line colour, and
major line weight all live in *Preferences ▸ Appearance ▸ Grid* — a "Theme
default" button clears a colour override and follows the canvas theme again.
The Grid snap type in the palette snaps to its intersections. The grid is
display-only — never exported.

### Layers panel

The Properties sidebar's layer tree is the layer interface:

- **Eye icon** shows/hides a layer (hidden = invisible + no snapping).
- **Padlock** locks it (visible + snappable, but not selectable/editable).
- Click a **layer name** to make it the active drawing layer (bold).
- Click an **object** to select it on canvas.
- **Drag an object** onto another layer row to move it to that layer (e.g. a
  lens path accidentally drawn on OUTLINE → drop it on LENS). Ctrl/Shift-click
  to drag several at once. The move is undoable; locked layers can't be
  dragged from.
- Right-click for *select all on layer* / *move selection to layer*.

### Mirror system (frame front)

- **Ghost** toggles the live mirrored preview across the bridge axis. Ghosts
  are display-only — but `LENS`, `HINGE`, and `SCULPT` curves are
  **doubled across the axis at export** when Ghost is on.
- **Mirror** (bake) converts ghosts into real, editable curves.
- **Mirror Close** joins an open outline to its mirrored half across the axis.

`OUTLINE` and `BRIDGE` are never auto-mirrored: draw the outline as the full
symmetric contour (draw half, then Mirror Close or bake + join).

## 3. Guides & face photos

- **Construction guides**: bridge angle, apical radius, crest height, temple
  spread/drop.
- **Boxing guide**: A / B / DBL boxes per the boxing system — match these to
  the customer's measurements before drawing lenses. Three modes:
  - *Free* (default): A / B / DBL are inputs that size the floating box.
  - **Snap to lens shape**: the box (and a dashed bevel-offset "full lens depth"
    outline) fit the actual lens; pick a **Bevel** preset (Flat/Rimless 0,
    Horn/Metal 0.5, Acetate 1.0, or Custom). A / B / DBL now read the *finished*
    (beveled) measurements live as you edit or move the lens.
  - **Lock lens shape**: the spline freezes (still movable). Type a new **A**/**B**
    to restretch the lens to that exact finished size — the **chain** button
    between them links A/B proportionally; type **DBL** to slide it. **Lock
    outline to lens** co-resizes the frame outline at a constant eyewire wall
    (flats and corners preserved; open mirrored halves grow from the bridge,
    closed finished frames grow symmetrically).
- **Stock / pad guides**: outlines of your acetate blank and pad block, for
  checking the design fits the material.
- **Face photo**: File → Add Reference Image…, then calibrate px-per-mm by
  clicking two points a known distance apart (e.g. a ruler in the photo).
  Photos sit behind geometry; lock/unlock, opacity, and rotation are in the
  sidebar. The **Frame Fill** overlay (Guides panel) renders the frame
  silhouette over the photo for a realistic preview.

## 4. Importing & lens traces (DXF, OMA/DCS)

- **File → Import → DXF…** brings any DXF into the active workspace. Entities on
  recognised GuildDraw layers (OUTLINE/LENS/…) keep them; everything else lands
  on the active layer, selected, so you can drag each path to the right layer in
  the Layers panel. Use it to migrate an existing frame library.
- **File → Import → OMA Lens Trace…** reads a frame-tracer / lab DCS file
  (TRCFMT format 1). Traces land in Frame Front as editable LENS splines,
  boxing centres on y=0, nasal edges separated by the file's DBL (or the
  boxing guide's). Any `DRILLE` drill holes in the file land on the DRILL layer.
- **File → Export → OMA Trace…** (Frame Front) emits both lens contours plus
  HBOX/VBOX/DBL/FED computed from the geometry, and `DRILLE` records for any
  DRILL holes (mirrored into symmetric pairs), for labs and edgers.

### Drill-mount holes

For rimless / drill-mount lenses (flat, no bevel), use the **DRILL** layer:

- **Library ▸ Holes** — type a hole's X / Y offset from the lens boxing centre
  plus a diameter, then **Add Hole**. Save a set as a named pattern; **Import
  Pattern onto Lens** re-centres a saved pattern on the current lens, so one
  drill spec re-applies to any size. Per-hole diameters are kept.
- Holes export/import as OMA `DRILLE` records (see above) and as DXF `CIRCLE`s
  on the DRILL layer.

## 5. Checking the design

- **Measurements panel**: live frame width, lens A/B, DBL readouts.
- **Dimensions**: place linear dims with `D`.
- **Print at 1:1** (File menu) or **Export PDF (1:1 scale)**: paper test-fit.
  Every print includes a **50 mm verification ruler** — measure it; if it
  isn't exactly 50 mm, your printer driver scaled the page (disable
  "fit to page").

## 6. Exporting for GuildModel

1. Make sure each populated workspace passes validation (export runs it
   automatically and explains any failure).
2. **File → Export → Export DXF…** exports the active workspace, or
   **Export All DXF…** writes every populated workspace in one go:
   `<name>_front.dxf`, `<name>_temple_r.dxf`, `<name>_temple_l.dxf`,
   `<name>_hinge.dxf`. Nothing is written unless all populated workspaces
   validate.
3. Hand the DXFs to GuildModel. The files are R2000 with SPLINE entities at
   true mm; closed contours have endpoints within 0.1 mm; `REF` is ignored
   by GuildModel; ENGRAVING text is already converted to outline splines.

What the validator enforces:

- Frame Front: exactly 1 `OUTLINE` + 2 `LENS` (the mirror ghost counts toward
  the lens pair when Ghost is on).
- Temples: exactly 1 `OUTLINE`, no `LENS`.
- Hinge Pocket: at least 1 `HINGE`, no `OUTLINE`/`LENS`.
- Machined contours must be closed (gap ≤ 0.1 mm warns, larger blocks).

## 7. Files & data safety

- **`.gdraw`** is the native project format (a ZIP of per-workspace SVGs +
  manifest). Single-workspace SVG save/load is also supported.
- Saves are **atomic** with a `.bak` of the previous version.
- **Autosave** writes a recovery file every 3 minutes while there are unsaved
  changes; after a crash, the next launch offers to restore.
- The hinge library lives in `~/.guilddraw/library/hinges/` — save a hinge
  pocket once, import it into any project (it arrives as a group). New
  shipped starter hinges merge into your library automatically; a hinge you
  delete stays deleted.
- **□ (boxing square)** — `Ctrl+Shift+B` types "□" into the focused field,
  for frame-size notation like `49□27-145` (A□DBL-TempleLength) in bookmark
  names, hinge/drill library saves, and engraving text. Reassignable in
  *Settings ▸ Hotkeys*. Save As on an untitled project pre-fills the
  filename with the current design's size string.
- **Appearance** (*Settings ▸ Preferences ▸ Appearance*): dark mode, canvas
  presets (Parchment / **Dimmed** / Blueprint / Matte Dark / Plain White /
  custom colour), a vignette slider, node-dot size, compact toolbar, and grid
  spacing/colours/weight. Dimmed is a light-mode canvas darker than Parchment
  but still light enough for the standard line palette. Per-layer drawing
  colours (light + dark) are on the **Layers** tab.
- Preferences (theme, toolbar, hotkeys, guide defaults) are in
  `~/.guilddraw/prefs.json`.

## 8. Fixed shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save As |
| `Ctrl+Z` / `Ctrl+Y` (or `Ctrl+Shift+Z`) | Undo / Redo |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+D` | Copy / Paste / Duplicate |
| `Ctrl+A` | Select all (visible + unlocked) |
| `Ctrl+T` | Transform dialog |
| `Ctrl+G` / `Ctrl+Shift+G` | Group / Ungroup |
| Mouse wheel | Zoom (1%–10,000%) |
| Middle-button drag | Pan |
| `Delete` / `Backspace` | Delete selection |
| `Esc` | Cancel tool / back to Select |
