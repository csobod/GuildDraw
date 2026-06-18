# GuildDraw User Guide (v1.0.0-rc1)

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

At least one `LENS` contour is required for a GuildCAM-ready front (a classic
pair is two; aviators and other shapes may carry more). The validator checks
these rules per workspace and drives the readiness dot, but it no longer blocks
export — you decide when the geometry is complete and GuildCAM's intake is the
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
| Dimension | `D` | Linear dimension between two snapped points; drag the label to offset it |
| Trim | `T` | Click the segment to remove between intersections |
| Split | `X` | Split a curve at a clicked point |
| Offset | `O` | Type a distance, amber preview, Enter confirms |
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

Snap targets (toggle with the Snap button): curve nodes, handles, line
midpoints (orange), circle/arc quadrants, nearest point on curve (steel-blue
diamond), the mirror axis, and the origin (purple). Hidden layers are never
snap targets; locked layers still snap (reference geometry).

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
  the customer's measurements before drawing lenses.
- **Stock / pad guides**: outlines of your acetate blank and pad block, for
  checking the design fits the material.
- **Face photo**: File → Add Reference Image…, then calibrate px-per-mm by
  clicking two points a known distance apart (e.g. a ruler in the photo).
  Photos sit behind geometry; lock/unlock, opacity, and rotation are in the
  sidebar. The **Frame Fill** overlay (Guides panel) renders the frame
  silhouette over the photo for a realistic preview.

## 4. Lens traces (OMA/DCS)

- **File → Import → OMA Lens Trace…** reads a frame-tracer / lab DCS file
  (TRCFMT format 1). Traces land in Frame Front as editable LENS splines,
  boxing centres on y=0, nasal edges separated by the file's DBL (or the
  boxing guide's). Derive the frame around them.
- **File → Export → OMA Trace…** (Frame Front) emits both lens contours plus
  HBOX/VBOX/DBL/FED computed from the geometry, for labs and edgers.

## 5. Checking the design

- **Measurements panel**: live frame width, lens A/B, DBL readouts.
- **Dimensions**: place linear dims with `D`.
- **Print at 1:1** (File menu) or **Export PDF (1:1 scale)**: paper test-fit.
  Every print includes a **50 mm verification ruler** — measure it; if it
  isn't exactly 50 mm, your printer driver scaled the page (disable
  "fit to page").

## 6. Exporting for GuildCAM

1. Make sure each populated workspace passes validation (export runs it
   automatically and explains any failure).
2. **File → Export → Export DXF…** exports the active workspace, or
   **Export All DXF…** writes every populated workspace in one go:
   `<name>_front.dxf`, `<name>_temple_r.dxf`, `<name>_temple_l.dxf`,
   `<name>_hinge.dxf`. Nothing is written unless all populated workspaces
   validate.
3. Hand the DXFs to GuildCAM. The files are R2000 with SPLINE entities at
   true mm; closed contours have endpoints within 0.1 mm; `REF` is ignored
   by GuildCAM; ENGRAVING text is already converted to outline splines.

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
  pocket once, import it into any project (it arrives as a group).
- Preferences (theme, toolbar, hotkeys, guide defaults) are in
  `~/.guilddraw/prefs.json`.

## 8. Fixed shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Z` / `Ctrl+Y` (or `Ctrl+Shift+Z`) | Undo / Redo |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+D` | Copy / Paste / Duplicate |
| `Ctrl+A` | Select all (visible + unlocked) |
| `Ctrl+T` | Transform dialog |
| `Ctrl+G` / `Ctrl+Shift+G` | Group / Ungroup |
| Mouse wheel | Zoom (1%–10,000%) |
| Middle-button drag | Pan |
| `Delete` / `Backspace` | Delete selection |
| `Esc` | Cancel tool / back to Select |
