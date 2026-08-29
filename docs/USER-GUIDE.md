# GuildDraw User Guide (v1.0.0)

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
| Rebuild | `R` | Refit the selected spline/polyline: type a target node count (or press `Tab` and type a tolerance in mm); the HUD shows the achieved deviation live, Enter replaces the original (undoable). The way to turn a dense imported DXF outline into a clean, editable spline |
| Point Move | `G` | Grab a point (snapped), click destination or type exact X/Y |
| Move gizmo | `M` | Drag selection with exact-distance HUD |
| Text | `I` | ENGRAVING text (temples only); double-click to re-edit. The **Font** box filters as you type — see below |
| Snap node→endpoint | `E` | Snap a node onto another curve's endpoint |

All hotkeys are reassignable in **Settings → Hotkeys**; toolbar buttons can be
hidden per-button in **Settings → Toolbar**.

**Choosing a font** (the Text tool's dialog, and the caption font in
*Preferences ▸ PDF*): the box stays empty-handed until you type — with a big
library installed, nothing is loaded and nothing stalls. From the first
character it narrows to the families that match anywhere in their name and
drops them down, while still completing the best match inline, so three
letters and Enter is as quick as it ever was. The arrow re-filters on whatever
is already in the box, which is how you get from "Helvetica Neue" to its
weights and italics. A name no installed font answers to snaps back rather
than silently becoming your system default — except one you typed in full,
which is kept so a design drawn on a machine that has the font keeps asking
for it.

### Editing

- **Nodes & handles**: with Select active, drag nodes; drag Bézier handles to
  shape curves. "Smooth" toggle keeps handle pairs tangent.
- **Join / Explode / Split-at-node**: merge open curves end-to-end, break a
  multi-segment curve apart, or split at a selected node.
  - **Join with one curve selected closes it onto itself** — if its two ends
    sit within 2 mm, they fuse into a closed loop. That is what an imported DXF
    lens trace usually needs after a Rebuild: it comes back as a single spline
    that *looks* closed but is still an open path, so it never counts as a
    finished lens. Select it, press **J**, done.
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
  - Turning **Snap to lens shape** on brings the boxing guide up with it,
    because the bevel outline rides on the guide. Turning it back off restores
    the guide to however you had it — hidden stays hidden.
  - **Lock lens shape**: the spline freezes (still movable). Type a new **A**/**B**
    to restretch the lens to that exact finished size — the **chain** button
    between them links A/B proportionally; type **DBL** to slide it. **Lock
    outline to lens** co-resizes the frame outline at a constant eyewire wall
    (flats and corners preserved; open mirrored halves grow from the bridge,
    closed finished frames grow symmetrically).
- **Stock / pad guides**: outlines of your acetate blank and pad block, for
  checking the design fits the material.
- **Frame Fill** (Guides panel): fills the frame body — the OUTLINE profile
  minus the LENS apertures and any decorative openings — so the drawing reads
  as a frame rather than a wireframe. **Style** picks what it is filled with:
  - **Colour** — a flat translucent tint at whatever **Opacity** you set.
  - **Image** — a material swatch. Point it at a supplier's acetate sample
    sheet (Jimei, Mazzucchelli, Takiron and the rest publish them as JPEGs) and
    the frame shows the pattern it would really be cut from, which is the whole
    point for a laminate, a tortoise, or anything with grain. The swatch is
    scaled to span your **Stock Blank width** and centred on the origin, so it
    lands on the drawing exactly as the sheet would sit under it — change the
    stock width and the material rescales with it. Whether the Stock guide is
    *shown* makes no difference. If the frame runs past the blank the pattern
    repeats rather than running out; the Stock guide is what tells you it no
    longer fits the sheet.
  - Crop the supplier's logo and part number off the swatch first — they sit in
    a corner of the sheet, and on a big frame they will end up on the design.
  - Display-only, like the tint: no fill ever reaches exported DXF/SVG
    geometry, but it does appear in a PNG render, and on the catalog PDF if
    you tick *Print Frame Fill and Lens Fill* in *Preferences ▸ PDF*. Saved
    `.gdraw` files
    **embed** the swatch the same way they embed a face photo, so a shared
    project shows the material on the recipient's machine.
  - Needs a perimeter that closes. If the OUTLINE leaks, GuildDraw says so
    instead of filling something half-formed.
- **Lens Fill** (Guides panel, Frame Front): tints each closed LENS aperture
  with a vertical **Top → Bottom** gradient, the way a dyed lens runs. Every
  lens gets its own run of the gradient, so a pair reads as two matching
  lenses rather than slices of one. The **chain** button holds both stops at
  the same colour for a flat tint.
  - Two sliders, and the difference matters. **Intensity** is how deeply the
    dye reads — the tint's own strength. **Opacity** is how much of what sits
    behind it (the face photo, the frame fill) shows through. Intensity starts
    a quarter along, at the colour exactly as picked; drag right for a deeper
    dye. Opacity starts at 65%. Both defaults are yours to set in
    Preferences ▸ General ▸ Lens Fill.
  - The **BPI** button beside either colour opens a searchable grid of
    approximate screen colours for BPI's published tint catalog; click a
    swatch to drop its hex into that stop. These are *approximate* — sampled
    from BPI's own display swatches, not a dye-lot match, and how deep a lens
    actually comes out depends on dye time, material, and base curve.
  - **Expect to reach for Intensity after picking a BPI colour.** Those
    swatches show a dye at one modest depth over white, so a colour taken from
    one lands pale. Raising Intensity deepens it along the same hue, the way a
    longer dye time would — the picked hex itself never changes, so winding the
    slider back always recovers exactly what you chose. The colour bars preview
    the tint at the current intensity; the picker still edits the base colour.
  - Display-only: the tint never reaches exported DXF/SVG geometry. It does
    reach a PNG render, and the catalog PDF when you ask for it (see
    *Preferences ▸ PDF*). Colours, link state, and opacity are saved with the
    design.
  - Needs a lens that closes. If nothing encloses a region GuildDraw says so
    rather than tinting something half-formed — close the LENS (select it and
    press **J**), or in Ghost mode snap the open half's ends to the mirror line.
- **Face photo**: File → Add Reference Image…, then calibrate px-per-mm by
  clicking two points a known distance apart (e.g. a ruler in the photo).
  Photos sit behind geometry; lock/unlock, opacity, and rotation are in the
  sidebar. The **Frame Fill** overlay (Guides panel) renders the frame
  silhouette over the photo — in a flat colour or in a real material swatch —
  and **Lens Fill** just below it tints the lenses. Saved `.gdraw` files
  **embed** the photo, so a shared project shows it on the recipient's
  machine — and the file never records where the photo came from on yours.

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
- **The bevel question, both directions.** A frame trace follows the bevel
  groove of the *finished* lens — the drawn lens opening grown outward by the
  bevel depth. Import and export each ask what you want (depth pre-filled
  from the boxing guide's bevel setting):
  - *Import*: **Apply Reduction** shrinks the trace back to the drawn lens
    (the finished edges still land the file's DBL apart), or **Import As
    Traced** keeps the finished size.
  - *Export*: **Apply Increase** writes the finished size for labs and
    edgers, or **Export As-Is** writes the drawn lens opening.
  - Exporting with the increase and reimporting with the reduction at the
    same depth round-trips exactly.

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
- **Print at 1:1** (File menu) or **File → Export → PDF (1:1 scale)…**: paper
  test-fit. Both render **what your viewport currently frames** at exact
  1:1 in print-friendly inks. Every print includes a **50 mm verification
  ruler** — measure it; if it isn't exactly 50 mm, your printer driver
  scaled the page (disable "fit to page").
- **File → Export → PDF for Catalog…**: the frame front and both temples on
  one landscape sheet with the design's name — true size when it fits.
  Paper size, line weight, caption font, and a vertical offset (for a
  binding margin) live in *Preferences ▸ PDF*.
  - **Print Frame Fill and Lens Fill** (same preferences page, off by default)
    lays those overlays under the line work, per workspace, exactly as that
    workspace shows them — the material swatch or tint in the frame profile
    and the gradient in each aperture. Off is the cutting-room sheet; on is
    the showroom page. A workspace with its fill switched off, or whose
    outline doesn't close, prints line work only.
- **File → Export → PNG…** renders at a chosen print resolution
  (150–1200 dpi), cropped to the drawing.

## 6. Exporting for GuildModel

1. Make sure each populated workspace passes validation (export runs it
   automatically and explains any failure).
2. **File → Export → DXF…** exports the active workspace, or
   **All DXF…** writes every populated workspace in one go:
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
- **For your IT department**: [IT-NOTES.md](IT-NOTES.md) documents what
  GuildDraw does and does not do (no network, no background processes,
  exactly what it writes to disk) and why unsigned builds sometimes trip
  antivirus heuristics.

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
