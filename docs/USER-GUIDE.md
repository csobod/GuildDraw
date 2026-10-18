# GuildDraw User Guide (v2.0.0)

GuildDraw drafts eyewear in true millimeters. Everything you draw is at 1:1
scale; the DXF you export is what the CNC cuts.

## 1. The four workspaces

A GuildDraw project (`.gdraw`) holds four tabs, each with its own canvas,
layers, guides, and undo history:

| Tab | Purpose | Machined layers |
|---|---|---|
| **Frame Front** | The front: outline + lenses | `OUTLINE` ×1 (one per rim for a combination frame), `LENS` ×2 (×1 for a monocle), optional `DRILL`, `INLAY`, `COMPONENT` |
| **Temple R / L** | Each temple arm | `OUTLINE` ×1, optional `COMPONENT`, `ENGRAVING`, `INLAY` |
| **Component** | A component drawn for the library: a hinge, a bridge | `COMPONENT` ≥1 |

A GuildModel-ready front has two `LENS` contours, or one for a monocle, whose
outline is one rim around it. The validator checks
these rules per workspace and drives the readiness dot, but it no longer blocks
export — you decide when the geometry is complete and GuildModel's intake is the
final gate.

**Temple Copy** (toolbar, temple workspaces) copies Temple R to Temple L (or
back) mirrored, so you draw one temple and stamp the other. Engraving text
comes along on the mirrored footprint but stays readable: its rotation is
transformed so the side of the lettering that faces the brow edge follows the
temple (a right-temple engraving at 180° becomes 0° on the left). Double-click
the copy to change the words; placement and style are already identical.

**Which face you see.** A front is drawn facing the anterior, the side the
world sees, as its reference photo is. A temple is drawn from the posterior,
the skin side, so engraved text reads naturally. **View Obverse** (toolbar
and *View* menu, hotkey `V`; front and temples) turns the active tab's view to
show the other face. The whole canvas is mirrored left to right: the face
photo, the grid and the dimension lines turn with the drawing, and engraved
text reads mirrored, while dimension values stay readable. A badge in the
canvas's top-left corner names the face toward you: *posterior* on a front,
*anterior* on a temple; in the default view a quieter word in the same corner
names the face you see. Angles you type or read follow the screen in View
Obverse: Transform's counter-clockwise turn and the Line tool's angle are as
you see them, and an arc runs clockwise on screen from its start click. Use it to see a temple's
inlays from the outside, or a front from behind. It is a view only: you draw,
edit and snap as usual, the file and every export keep the drawing as drawn,
and GuildModel still makes its single flip when it reads the file. Each tab
keeps its own setting, and a design you open or start begins on its default
faces.

## 2. Drawing

Draw at real size. The origin cross is (0,0); for the frame front, the bridge
mirror axis is the vertical through x=0. The origin is also where GuildModel
puts the part: its blank is centered on (0,0), a front is cut as drawn, and a
temple's y = 0 is the core line (see *The origin rule* in section 6).

**Getting around.** Scroll to zoom; drag with the right or middle button, or
hold `Space` and drag, to pan. **Fit** (`Ctrl+0`) frames the drawing and the
stock guide; an empty tab shows its default extents, with a note on what to
draw first. The status bar reads the pointer's position with y up from the
origin, as the DXF, the Holes fields and GuildModel count it, and the zoom in
screen pixels per millimeter.

A drawing tool started on a hidden or locked layer asks first, and shows or
unlocks it for you: a curve drawn there would not show, or could not be
selected.

| Tool | Default key | Notes |
|---|---|---|
| Select | Esc / toolbar | Click selects; drag rubber-bands; Alt+click cycles overlapping items |
| Line | `L` | Click points; Enter/double-click ends; close by clicking the first point (three points or more). Type a length, `Tab`, then an angle: degrees counter-clockwise from screen right, a minus allowed |
| Spline | `S` | Catmull-Rom through clicked points; smooth handles editable afterwards |
| Circle | `C` | Click center, click/type radius |
| Arc | `A` | Click the center, the start (it sets the radius), then the end: the arc runs clockwise on screen from the start |
| Arc (start–end–center) | — (assign in Preferences ▸ Hotkeys) | Click the two ends, then a point that sets the bulge |
| Fillet | `F` | Click two lines, type a radius; rounds the corner |
| Dimension | `D` | Linear dimension between two snapped points; arrowed ends, drag the label to offset it |
| Trim | `T` | Click the segment to remove between intersections |
| Split | `X` | Split a curve at a clicked point |
| Offset | `O` | Type a distance, amber preview, Enter confirms. On a closed shape, positive is always outward and negative is always inward, whichever way the curve was drawn |
| Rebuild | `R` | Refit the selected spline/polyline: type a target node count (or press `Tab` and type a tolerance in mm); the HUD shows the achieved deviation live, Enter replaces the original (undoable). The way to turn a dense imported DXF outline into a clean, editable spline |
| Point Move | `G` | Grab a point (snapped), click destination or type exact X/Y (y up, as the status bar reads) |
| Move gizmo | `M` | Drag selection with exact-distance HUD |
| View Obverse | `V` | Turn the view to the drawing's other face (section 1); front and temples |
| Text | `I` | ENGRAVING text (temples only); double-click to re-edit. The **Font** box filters as you type — see below. A text stays on ENGRAVING or REF: it is engraving, never a cut |
| Snap node→endpoint | `E` | Snap the red node onto the nearest free end of another open curve (an arc's end on its rim), within the snap reach and on a shown layer |

A typed value takes a comma as its decimal point too: `12,5` is 12.5 mm.

All hotkeys are reassignable in **Preferences → Hotkeys**, and each tool's
tooltip names its current key. A hotkey cannot take a fixed shortcut (section
8) or a key the tools read while you type a value (digits, `.`, `,`, `-`, Enter
and Tab). Toolbar buttons can be hidden per button in **Preferences →
Toolbar**; Ghost, Guides and View Obverse stay in the View menu when their
buttons are hidden.

**Tooltips** wrap to a readable width. The **?** button at the foot of the
toolbar turns them off everywhere and back on; the choice is remembered, and
the button's own tooltip always shows.

**Choosing a font** (the Text tool's dialog, and the caption font in
*Preferences ▸ Print & PDF*): the box stays empty-handed until you type — with a big
library installed, nothing is loaded and nothing stalls. From the first
character it narrows to the families that match anywhere in their name and
drops them down, while still completing the best match inline, so three
letters and Enter is as quick as it ever was. The arrow re-filters on whatever
is already in the box, which is how you get from "Helvetica Neue" to its
weights and italics. A name no installed font answers to snaps back rather
than silently becoming your system default — except one you typed in full,
which is kept so a design drawn on a machine that has the font keeps asking
for it. When the font is not installed on this computer, the dialog says
which face stands in for it, and so does the status bar when a design opens:
the text shows and exports in that face, and GuildModel engraves with the
font its own computer has.

### Editing

- **Nodes & handles**: with Select active, drag nodes; drag Bézier handles to
  shape curves. A drag starts after a few pixels, so a click picks a node
  without moving it. "Smooth" toggle keeps handle pairs tangent: the other handle
  turns to stay opposite and keeps its own length; hold `Shift` while
  dragging to give it the same length too.
- **Join / Explode / Split-at-node**: merge open curves end-to-end, break a
  multi-segment curve apart, or split at a selected node. Join takes curves
  on one layer (move them to one first), and when it brings ends together
  that were apart, the status bar says by how much.
  - **Join with one curve selected closes it onto itself** — if its two ends
    sit within 2 mm, they fuse into a closed loop. That is what an imported DXF
    lens trace usually needs after a Rebuild: it comes back as a single spline
    that *looks* closed but is still an open path, so it never counts as a
    finished lens. Select it, press **J**, done.
- **Group / Ungroup** (`Ctrl+G` / `Ctrl+Shift+G`): grouped curves select and
  move as a rigid unit (components from the library arrive grouped for this
  reason). `Ctrl`+click takes a whole group into or out of the selection.
  Trim, Split, Fillet, Rebuild and Insert Node leave a group's shape alone:
  ungroup it first.
- **Copy / Paste / Duplicate** (`Ctrl+C/V/D`): curves, dimensions and
  engraving text; works across workspaces; layers that don't exist in the
  target workspace land on REF. Each paste of the same copy lands 5 mm
  further on, and the status bar names a hidden or locked layer it landed on.
- **Transform** (`Ctrl+T`): scale X/Y % (aspect lock), rotate, pivot at
  selection center or origin. A positive angle turns counter-clockwise, as
  in the Text dialog (before 1.3 it turned clockwise), and in View Obverse
  as the screen shows it. Text objects scale
  their size (uniform scale only; lettering has no stretched form) and turn
  with the rotation, and selected dimensions move with the drawing.
- **Undo / Redo**: `Ctrl+Z` / `Ctrl+Y`, per workspace.

### Snapping

The **Snap** button is the master on/off; holding `Ctrl` suspends snapping
while held. The **Snap Types** button beside it opens the *snap palette* — a
pinnable pop-out that chooses *which* targets snap (hover a button for its
name) and sets the snap radius (the magnet + `r` field):

- **Endpoint** — open-curve ends and arc endpoints (green).
- **Node** — interior and closed-curve nodes.
- **Midpoint** — line-segment midpoints (orange).
- **Center / Quadrant** — circle and arc centers and 0/90/180/270° points.
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

The **Grid** toolbar button overlays a millimeter grid (minor lines with a
heavier major line every Nth division; shipped default is 2 mm spacing with a
major line every 10 mm). Spacing, divisions, minor/major line color, and
major line weight all live in *Preferences ▸ Appearance ▸ Grid* — a "Theme
default" button clears a color override and follows the canvas theme again.
The Grid snap type in the palette snaps to its intersections while the grid
is shown; a hidden grid pulls nothing. The grid is display-only — never
exported.

### Layers panel

The Properties sidebar's layer tree is the layer interface:

- **Eye icon** shows/hides a layer (hidden = invisible + no snapping).
- **Padlock** locks it (visible + snappable, but not selectable/editable).
- Click a **layer name** to make it the active drawing layer (bold).
- Click an **object** to select it on canvas; Ctrl/Shift-click to pick
  several, then **Delete** (or Backspace) removes them, undoably.
- **Drag an object** onto another layer row to move it to that layer (e.g. a
  lens path accidentally drawn on OUTLINE → drop it on LENS). Ctrl/Shift-click
  to drag several at once. The move is undoable; locked layers can't be
  dragged from.
- Right-click for *Select All on …* / *Move Selection to …*.
- A row in a group reads by its kind, *Hinges 1*, or *group 2* when it has
  none.

Each layer row's tooltip says what the layer becomes in GuildModel:

- `OUTLINE` is the profile GuildModel cuts. The largest closed curve is the
  profile; a closed curve inside it is a decorative opening; one outside it
  is ignored. It is never mirrored, so draw the whole contour.
- `LENS` is the lens apertures: two, or one for a monocle; `DRILL` the
  drill-mount holes; `SCULPT` the back-surface section cuts; `COMPONENT` the
  pocket for what mounts on the posterior. The Ghost previews all four across
  the axis, but GuildModel reads only the curves drawn: bake a twin with
  **Mirror** to make it real.
- `COMPONENT` (2.0; `HINGE` before) is a pocket for anything mounted on the
  posterior: a hinge, a bridge, an endpiece, a bridge bar. GuildModel cuts
  each closed curve as a pocket. Place one from the component library (see
  *The component library*). Every file made before 2.0 says `HINGE`, and
  GuildDraw and GuildModel read it as `COMPONENT`; GuildDraw writes only
  `COMPONENT`.
- `ENGRAVING` (temples) is what GuildModel engraves, since 1.8.1: a closed
  drawn curve is a **filled shape**; a closed curve inside it is an
  **island** left standing, so an O is two circles; an open curve is traced
  as a **stroke**; **text** is engraved as stroke centerlines and stays
  editable text in the `.gdraw` (a DXF carries it as outlines).
- `INLAY` (front and temples, 2.0) is a seat for a plaque, a laminate or a
  metal plate: a closed curve GuildModel cuts to a depth and on a face it
  keeps per inlay, the visible face by default. On a temple that is the
  anterior, the face **View Obverse** shows. An inlay inside an inlay is a
  **step**; an inlay inside a `COMPONENT` curve is a step in the pocket's
  floor. A seat may run off the part's edge, where it is cut as a step open
  there (a front-mounted bridge's seat, see *Combination frames*). Inlays
  never cross a lens, a drill hole, a component curve or a decorative opening,
  and two inlays either nest or stay apart. They are not mirrored: draw each
  seat, or Mirror (bake) a pair.
- `REF` is reference geometry: never exported, and GuildModel ignores it.

### Mirror system (frame front)

- **Ghost** toggles the live mirrored preview across the bridge axis. Ghosts
  are display-only, and since 2.0 nothing exports them: the `.gdraw` and the
  DXF carry the curves drawn, and GuildModel never applies the Ghost, so a
  monocle can be made. With the Ghost on, the readiness dot names each twin
  that no drawn curve stands for, such as the other lens or the other end's
  component pocket. The OMA trace still pairs a lens and its drill holes with the
  Ghost, for labs and edgers.
- **Mirror** (bake) converts ghosts into real, editable curves. It skips a
  curve whose twin would lie on itself or on a curve already drawn, and a
  closed curve across the axis.
- **Mirror Close** joins an open outline to its mirrored half across the axis.
  Both ends must reach the axis, within 2 mm (the axis snap puts them on it),
  and the half must stay on one side of it.

`OUTLINE` is never auto-mirrored: draw the outline as the full symmetric
contour (draw half, then Mirror Close, or bake and Join).

### Combination frames (separated rims)

A combination frame's acetate rims ride on a metal bridge, so its front is
two rims, each holding its lens. Draw the left rim as one closed `OUTLINE`
curve; a rim drawn in pieces, such as a spline and a straight temple edge,
wants **Join** first, and the readiness dot says so. Draw its lens. With the
Ghost on, the right rim is previewed and Frame Fill fills both. Then select
the rim and its lens and use **Mirror** (bake): both rims must be real curves
for GuildModel, and the readiness dot stays amber while the right rim is the
Ghost's only.

Then draw the bridge's seat as one closed shape across the gap, reaching into
each rim's nasal end. On the `COMPONENT` layer it is a pocket in the back, for a
bridge that mounts from behind; on the `INLAY` layer it is a seat in the face,
for one that mounts from the front. Either way GuildModel cuts it where it
meets each rim, as a step open at the rim's edge. For GuildModel the front is
one part with a body per rim, cut from the same blank.

### The component library

The **Components** list on the Library tab holds what you place on a front
or a temple for a pocket: hinges, bridges, endpieces, bridge bars. The list
is a set of folders, and a component's folder is its kind. A new library has
two folders: **Hinges**, with the starter set, and **Bridges**, empty for
your own.

- **Import into Workspace**, or a double-click, places the selected
  component as a group at the origin. Its `COMPONENT` curves carry the
  folder's name, and the `.gdraw` keeps it. GuildModel 2.0 reads the curves
  and not the kind; a later GuildModel will treat a kind with "hinge" in its
  name as a hinge, and any other kind as a mount, measured flat from its
  terrace wherever it sits. A component drawn by hand carries no kind, and
  its pocket is placed by where it sits. A DXF carries layers only, so it
  carries no kind.
- On the **Component** tab you keep the library. **Save Current
  Component…** asks for a name and a folder; type a new name for a new
  folder. **New Folder…**, **Rename…** and **Delete** work on folders and
  entries; deleting a folder that holds components asks first. **Move to
  Folder…**, or a drag, moves an entry to another folder, and dragging a
  folder changes the folders' order.

## 3. Guides & face photos

- **Construction guides**: frontal angle, apical radius, and the crest:
  **Crest height** (the arc's top above the datum line, positive up as the
  optical convention measures it; negative below), **Crest width** (half the
  crest's width: from the axis to each arm's pivot) and **Angle height** (how
  far below the crest the arms pivot). With the boxing guide's A, B and DBL
  they are the customer's measurements, saved with the design.
- **Boxing guide**: A / B / DBL boxes per the boxing system — match these to
  the customer's measurements before drawing lenses. Three modes:
  - *Free* (default): A / B / DBL are inputs that size the floating box.
  - **Snap to lens shape**: the box (and a dashed bevel-offset "full lens depth"
    outline) fit the actual lens; pick a **Bevel** preset (Flat/Rimless 0,
    Horn/Metal 0.5, Acetate 1.0, or Custom). A / B / DBL now read the *finished*
    (beveled) measurements live as you edit or move the lens.
  - Snapped with no lens drawn, A, B and DBL read "—"; **Lock lens shape**
    waits for a lens.
  - Turning **Snap to lens shape** on brings the boxing guide up with it,
    because the bevel outline rides on the guide. Turning it back off restores
    the guide to however you had it — hidden stays hidden.
  - **Lock lens shape**: the spline freezes (still movable). Type a new **A**/**B**
    to restretch the lens to that exact finished size — the **chain** button
    between them links A/B proportionally; type **DBL** to slide it. **Lock
    outline to lens** co-resizes the frame outline at a constant eyewire wall
    (flats and corners preserved; open mirrored halves grow from the bridge,
    closed finished frames grow symmetrically).
- **Stock / pad guides**: outlines of your acetate blank and pad block,
  centered on the origin, for checking the design fits the material.
  GuildModel centers its blank on the same origin, so the readiness dot warns
  when an OUTLINE leaves the stock guide, with the overrun in mm. On the
  temple tabs the stock guide carries a dash-dot **core line** at y = 0, where
  the wire runs: draw the temple across it. The front's blank is set once in
  *Preferences ▸ General* (Stock blank); the temple blank sits beside it
  (Temple blank, 170 × 30 mm by default, GuildModel's own), shared by both
  temple tabs. Each tab's guide sizes are saved in the `.gdraw` and come back
  when you open it, so a design keeps the blank it was drawn against; the
  preferences (*Guide Sizes for New Designs*) set the sizes a new design
  starts with. Changing them while a drawn design is open asks whether the
  open design takes them too (*Apply to This Design*) or keeps its own (*New
  Designs Only*); set the open design's sizes on the Guides tab.
- **Frame Fill** (Guides panel): fills the frame body — the OUTLINE profile
  minus the LENS apertures and any decorative openings — so the drawing reads
  as a frame rather than a wireframe. **Style** picks what it is filled with:
  - **Color** — a flat translucent tint at whatever **Opacity** you set.
  - **Image** — a material swatch. Point it at a supplier's acetate sample
    sheet (Jimei, Mazzucchelli, Takiron and the rest publish them as JPEGs) and
    the frame shows the pattern it would really be cut from, which is the whole
    point for a laminate, a tortoise, or anything with grain. The swatch is
    scaled to span your **Stock Blank width** and centered on the origin, so it
    lands on the drawing exactly as the sheet would sit under it — change the
    stock width and the material rescales with it. Whether the Stock guide is
    *shown* makes no difference. If the frame runs past the blank the pattern
    repeats rather than running out; the Stock guide is what tells you it no
    longer fits the sheet.
  - Crop the supplier's logo and part number off the swatch first — they sit in
    a corner of the sheet, and on a big frame they will end up on the design.
  - Display-only, like the tint: no fill ever reaches exported DXF/SVG
    geometry, but it does appear in a PNG render, and on the catalog PDF if
    you tick *Print frame, inlay and lens fills* in *Preferences ▸ Print &
    PDF*. Saved `.gdraw` files **embed** the swatch, so a shared project
    shows the material on the recipient's machine.
  - Needs a perimeter that closes. Turned on over a leaking OUTLINE, it says
    so instead of filling something half-formed. On, it pauses while an edit
    leaves the outline open (an end dragged off, the Ghost switched off under
    a half): the box stays ticked, the status bar says why, and the fill
    comes back when the outline closes, Undo included. The same goes for the
    Inlay and Lens Fills. Lens openings stay open in the fill with the LENS
    layer hidden.
- **Inlay Fill** (Guides panel, Frame Front and both temples): fills each
  closed `INLAY` body over the frame fill, since an inlay is taken to sit on
  the anterior. A seat inside a seat (a step) is a body of its own, and the
  outer body keeps a hole where the step is. **Style** picks the fill:
  - **Color**: a flat tint at the **Opacity** you set. It starts turquoise at
    85%; set your own starting color and opacity in *Preferences ▸ General ▸
    Inlay Fill*.
  - **Image**: a photo of the material, such as a turquoise stone, a shell or
    a wood. Each body gets its own copy, scaled to cover the body and
    centered on it.
  - **Tumble bodies**, for an image on two or more bodies: each body's copy
    is turned differently, every other one is mirrored and the crop moves,
    so one photo reads as several stones. The arrangement depends only on
    where the bodies sit, so the drawing looks the same each time you open
    it.
  - Each tab keeps its own Inlay Fill. It is display-only, like the other
    fills: it never reaches the DXF, but it appears in a PNG render and on
    the catalog PDF, and the `.gdraw` embeds the image.
- **Lens Fill** (Guides panel, Frame Front): tints each closed LENS aperture
  with a vertical **Top → Bottom** gradient, the way a dyed lens runs. Every
  lens gets its own run of the gradient, so a pair reads as two matching
  lenses rather than slices of one. The **chain** button holds both stops at
  the same color for a flat tint.
  - Two sliders, and the difference matters. **Intensity** is how deeply the
    dye reads — the tint's own strength. **Opacity** is how much of what sits
    behind it (the face photo, the frame fill) shows through. Intensity starts
    a quarter along, at the color exactly as picked; drag right for a deeper
    dye. Opacity starts at 65%. Both defaults are yours to set in
    Preferences ▸ General ▸ Lens Fill.
  - The **BPI** button beside either color opens a searchable grid of
    approximate screen colors for BPI's published tint catalog; click a
    swatch to drop its hex into that stop. These are *approximate* — sampled
    from BPI's own display swatches, not a dye-lot match, and how deep a lens
    actually comes out depends on dye time, material, and base curve.
  - **Expect to reach for Intensity after picking a BPI color.** Those
    swatches show a dye at one modest depth over white, so a color taken from
    one lands pale. Raising Intensity deepens it along the same hue, the way a
    longer dye time would — the picked hex itself never changes, so winding the
    slider back always recovers exactly what you chose. The color bars preview
    the tint at the current intensity; the picker still edits the base color.
  - Display-only: the tint never reaches exported DXF/SVG geometry. It does
    reach a PNG render, and the catalog PDF when you ask for it (see
    *Preferences ▸ Print & PDF*). Colors, link state, and opacity are saved with the
    design.
  - Needs a lens that closes. If nothing encloses a region GuildDraw says so
    rather than tinting something half-formed — close the LENS (select it and
    press **J**), or in Ghost mode snap the open half's ends to the mirror line.
- **Reference images** (the face photo): File ▸ Add Reference Image…, the
  Canvas tab's **Add Image…**, or drop the image on the window. The Canvas
  tab lists them as the Layers panel lists layers, the last added on top:
  - The **eye** shows or hides an image. A hidden image is left out of PNG
    export and printing, and the calibration tool does not find it.
  - The **padlock** locks an image's place, turn and scale. A new image
    starts unlocked: drag it into place, turn it and calibrate it, then lock
    it, so a drag over it selects your drawing instead of moving the photo.
    The design keeps each image locked or unlocked as you left it.
  - The **paperclip** stores the image in the design. Not stored (the
    default), the image stays where it is on your computer: the `.gdraw`
    keeps its place, turn and calibration, and a random id that GuildDraw
    matches to the file on this computer. The file holds no part of the
    image, its name or where it is, so a patient's photo does not leave your
    computer in a design you send. Stored, the image is copied into the
    `.gdraw` and shows on any computer that opens it; GuildDraw explains
    this the first time (Preferences ▸ General ▸ Prompts brings the
    explanation back). To stop storing an image that exists only inside the
    design, save a copy on your computer when GuildDraw asks. A design's
    stored images are unpacked into GuildDraw's image cache when it opens;
    **Preferences ▸ General ▸ Clear Image Cache…** deletes those copies
    (each design unpacks its images again when next opened).
  - On another computer, or after you move the photo, an image the design
    does not store is listed as *Reference 1 — not on this computer*.
    **Locate…** finds it, and it returns at its place and scale.

  Calibrate by clicking two points a known distance apart (the pupils at the
  PD, or a ruler in the photo): the image under the first click is the one
  calibrated, and each image keeps its own scale, so a front photo and a side
  photo taken at different distances both read true. The Canvas tab's
  **Scale** field shows and sets the selected image's. Opacity and rotation
  are under the list, and removing an image asks first (Undo does not bring
  it back). An image over 64 MB, the most a design carries, is refused: a
  JPEG of a few MB is plenty to trace over. Designs from before 2.0 stored
  every image, and open with each one stored. The **Frame Fill** overlay
  (Guides panel) renders the frame silhouette over the photo, in a flat color
  or in a real material swatch, and **Lens Fill** just below it tints the
  lenses.

## 4. Importing & lens traces (DXF, SVG, OMA/DCS)

- **File → Import → DXF…** brings any DXF into the active workspace. Entities on
  recognized GuildDraw layers (OUTLINE/LENS/…) keep them; everything else lands
  on the active layer, selected, so you can drag each path to the right layer in
  the Layers panel. Use it to migrate an existing frame library. A closed
  polyline that repeats its first vertex, as most converters write one, is
  folded so the curve has no zero-length seam. Each polyline comes in as one
  curve, its bulges as true arcs. A spline comes in exactly when it can (a
  clamped spline of degree 1 to 3); one that cannot (a closed spline as Rhino
  and AutoCAD write it, a rational or higher-degree one) is fitted within
  0.01 mm, with as many nodes as that takes, and a NURBS circle comes in as a
  circle. Inside a block, each entity keeps its own layer (one on layer 0
  takes the insert's), and a mirrored block lands where CAD shows it. The
  file's drawing units are used when the drawing comes out a plausible size
  in them; otherwise, and when it names none, it is read as millimeters, and
  the status bar says which. Entities on layers that are off or frozen are
  left out, as is anything whose numbers are not numbers.
- **File → Import → SVG…** brings any SVG into the active workspace: a logo for
  a temple engraving, a shape from a colleague's drawing, an outline traced in
  another editor. Paths come in as the exact cubic splines the file holds, one
  spline per subpath; `rect`, `circle`, `ellipse`, `line`, `polyline` and
  `polygon` are read too. Groups labeled with a GuildDraw layer name that this
  workspace uses (Inkscape's layer name, or an `id`) keep the layer; everything
  else lands on the active layer, selected. The import asks for a **width** and
  the height follows. A file that declares a physical size (mm, cm, in, pt)
  imports at that size and where the file places it, so a drawing exported at
  true scale comes back where it was; a file with no physical size, which is
  most logos, is read at 96 px/in and **centered on the view**, ready to be
  sized. An Adobe Illustrator file is read at its own 72 units an inch. A
  nested `<svg>` is placed by its viewBox, and a shape hidden by a `<style>`
  class stays out. Text, clones (`use`) and images are not imported and are
  counted in the status bar: convert text to paths and expand clones in your
  editor first.
  To engrave a logo, draw or import it on a temple's ENGRAVING layer; GuildModel
  1.8.1 cuts a drawn closed shape as a filled engraving (a closed curve drawn
  inside it is left standing, so an O is two circles), traces a drawn open
  curve as a stroke, and engraves text as stroke centerlines.
- **File → Import → OMA Lens Trace…** reads a frame-tracer / lab DCS file
  (TRCFMT format 1). Traces land in Frame Front as editable LENS splines
  within 0.02 mm of the traced points, boxing centers on y=0, nasal edges
  separated by the file's DBL (or the boxing guide's). Any `DRILLE` drill
  holes in the file land on the DRILL layer. Into a front that has lenses
  already, it asks whether the traced lenses replace them or go beside them.
- **File → Export → OMA Lens Trace…** (from any tab; it goes to the Frame
  Front) emits both lens contours plus HBOX/VBOX/DBL/FED computed from the
  geometry, and `DRILLE` records for any DRILL holes (mirrored into symmetric
  pairs), each measured from the midpoint of the two lenses' boxing centers,
  for labs and edgers.
- **Dropping a file on the window** opens a design (`.gdraw`, or a GuildDraw
  `.svg`), imports a DXF, an SVG from another program or an OMA trace into
  the active tab, or adds a reference image.
- **The bevel question, both directions.** A frame trace follows the bevel
  groove of the *finished* lens — the drawn lens opening grown outward by the
  bevel depth. Import and export each ask what you want (depth pre-filled
  from the boxing guide's bevel setting):
  - *Import*: **Shrink to the Drawn Lens** shrinks the trace back to the
    drawn lens (the finished edges still land the file's DBL apart), or
    **Import As Traced** keeps the finished size.
  - *Export*: **Export the Finished Lens** writes the finished size for labs
    and edgers, or **Export the Drawn Opening** writes the drawn lens
    opening.
  - Exporting with the increase and reimporting with the reduction at the
    same depth round-trips exactly.

### Drill-mount holes

For rimless / drill-mount lenses (flat, no bevel), use the **DRILL** layer:

- **Library ▸ Holes** — type a hole's X / Y offset from the lens boxing center
  plus a diameter, then **Add Hole**. Toward the nose and up are positive, on
  either lens, as in an OMA trace (before 1.3, a positive Y went down the
  canvas). Save a set as a named pattern; **Import Pattern onto Lens**
  re-centers a saved pattern on the current lens, so one drill spec re-applies
  to any size, and to a frame drawn on either side of the mirror. Per-hole
  diameters are kept. Patterns saved before 1.3 are placed as they were drawn.
- Holes export/import as OMA `DRILLE` records (see above) and as DXF `CIRCLE`s
  on the DRILL layer.

## 5. Checking the design

- **Measurements panel**: live frame width, lens A/B, DBL readouts.
- **Dimensions**: place linear dims with `D`.
- **Print at 1:1** (File menu) or **File → Export → PDF (1:1 Scale)…**: paper
  test-fit. Both render **what your viewport currently frames** at exact
  1:1 in print-friendly inks, and say so when the drawing shown runs off the
  page. Every print carries the templates' tick-marked **100 mm ruler** (50 mm
  on small sheets): measure it; if it isn't exact, your printer driver scaled
  the page (disable "fit to page").
- **File → Print Front + Temples (1:1 Templates)…** or **File → Export →
  PDF Front + Temples…**: cutting templates for the hand-made workflow. The
  frame front and both temples are laid out at exactly 1:1, stacked and
  named, as vectors in each layer's print ink; a piece that won't fit under
  the previous one starts a new page, and a piece larger than the page is
  cropped (the status bar says so). Each workspace prints what it shows —
  visible layers, the mirror ghost, engraving text. Every page carries a
  tick-marked **100 mm ruler** (50 mm on small sheets) and a page counter.
  Paper size (US Letter, Legal, Tabloid, A3, A4, A5, Half Letter),
  orientation, line weight and the piece labels are in *Preferences ▸ Print & PDF*;
  the print dialog can still override the paper.
- **File → Export → PDF for Catalog…**: the frame front and both temples on
  one landscape sheet with the design's name — true size when it fits.
  Paper size, line weight, caption font, and a vertical offset (for a
  binding margin) live in *Preferences ▸ Print & PDF*.
- **File → Export → Catalog PDFs for a Folder…**: pick a folder of designs,
  and every `.gdraw` at its top (subfolders are left alone) gets the Frame
  Fill switched on in the front and both temples at the color and opacity
  you choose, saved back when that changed anything (the originals that
  change are copied to `_backup/<timestamp>/` in the folder first), and a
  catalog PDF written to `catalog/` beside them, or to a folder you pick,
  with your PDF preferences and the fill included. A progress window shows
  one line per design; a design that does not open cleanly, or whose outline
  does not close, is reported and left as it was. *Report only* shows what
  would change without writing anything (and leaves saving off). Saving the
  fill into the files is off until you tick it. The box for the Ghost
  switches off a mirror left on in a temple tab drawn as a half, which would
  print its mirrored other half. The summary says how many PDFs went where,
  with an **Open Folder** button. With the Inlay Fill box ticked, the run also turns the Inlay Fill
  on, at its own color and opacity, on every tab with a closed `INLAY` seat;
  otherwise each design's Inlay Fill stays as it is. The design open in
  GuildDraw is untouched: the run happens in a second window that is never
  shown. The same run is available from the
  command line as `scripts/batch_catalog.py`.
  - **Print frame, inlay and lens fills** (same preferences page, off by
    default) lays those overlays under the line work, per workspace, exactly
    as that workspace shows them: the material swatch or tint in the frame
    profile, the inlay fill in each seat, and the gradient in each aperture. Off is the cutting-room sheet; on is
    the showroom page. A workspace with its fill switched off, or whose
    outline doesn't close, prints line work only.
- **File → Export → PNG…** renders at a chosen print resolution
  (150–1200 dpi), cropped to the drawing, without the selection's highlight
  or handles. The file records its resolution, so it prints at true size;
  past 8192 px a side the resolution comes down, and the status bar says so.
  With View Obverse on, the image is mirrored, as the canvas shows it.
- **File → Export → SVG…** writes the tab for other programs: hairline
  strokes, and engraving text as its letters' outlines.
- The export dialogs start beside the open design, or in the folder you last
  used, with a name: `<design>_front.dxf` and the like. An empty tab exports
  nothing and says so, and a name that gets its suffix added after you
  typed it is checked again before it replaces a file.

## 6. Exporting for GuildModel

1. Make sure each populated workspace passes validation (export runs it
   automatically and explains any failure).
2. **File → Export → DXF of This Tab…** exports the active workspace, or
   **DXF of Every Tab…** writes every populated workspace in one go:
   `<name>_front.dxf`, `<name>_temple_r.dxf`, `<name>_temple_l.dxf`,
   `<name>_component.dxf`, asking first when any of them exists. The files
   are written whatever the validator says; the confirmation lists which
   workspaces are not yet GuildModel-ready.
3. Hand the DXFs to GuildModel. The files are R2000 with SPLINE entities at
   true mm; closed contours have endpoints within 0.1 mm; `REF` is ignored
   by GuildModel; ENGRAVING text is already converted to outline splines.

**The origin rule.** Since GuildModel 1.8.2 a part is placed by the drawing's
origin: the blank is centered on (0,0), a front is cut as drawn, and a temple's
y = 0 is the core line, where the wire runs. The temple's hinge end is snapped
to the blank's end, so where the temple sits along x does not matter; across
the blank it stays exactly where you drew it. A temple drawn beside the core
line is therefore cut beside the wire. GuildDraw shows the rule (the core line
on the temple stock guide, the origin cross) and checks it: the readiness dot
warns, in its tooltip, about a temple that does not cross y = 0 and about an
OUTLINE that leaves the stock guide. Both are warnings; the dot stays green.
In GuildModel, the part's *Stock* tab has an *Origin from drawing* box;
clearing it restores the old placement, centered on the outline.

**The `.gdraw` itself.** GuildModel (1.8.1 and later) opens the `.gdraw`
directly: save here, then open the file in GuildModel (its *File ▸ Open*, or
*Open with* on Windows). GuildModel watches the open drawing and reloads it on
request after your next save; the drawing stays open here. The DXF route
above remains for GuildModel's DXF intake and for other tools. GuildDraw never
launches GuildModel, or any other program: each of the three apps stands
alone, and the handoff is always a file you open.

What the validator checks (it drives the readiness dot and the export
notes; since 1.0 it never blocks an export — you decide when the geometry is
complete, and GuildModel's intake is the final gate). The dot's tooltip lists
every gap, not only the first, and shows even with tooltips switched off:

- Only the curves drawn are checked, as only they reach GuildModel; the
  Ghost is never counted.
- Frame Front: at least 1 `OUTLINE` (the largest contour is the profile;
  closed contours inside it are decorative openings, and one beside it that
  holds a lens is a separated rim) and two `LENS` curves, or one for a
  monocle, whose outline is one rim around it. GuildModel refuses a third
  lens, and one lens in an outline drawn for two, since the other eye would
  be cut solid. Every lens lies whole inside the profile or a rim.
- With the Ghost on, a twin that no drawn curve stands for is not ready: the
  other lens, the other rim, a component pocket or a sculpt line on one side
  only. Bake it with **Mirror**, or turn the Ghost off. A curve across the
  axis overlaps its own twin and is fine.
- Temples: at least 1 `OUTLINE`, no `LENS`.
- Component: at least 1 `COMPONENT`, no `OUTLINE`/`LENS`. GuildModel builds
  no part from this tab, so its dot is never green: gray when the component
  is ready for the library, amber with the gap when it is not.
- Machined contours must be closed (a gap ≤ 0.1 mm is auto-closed at export
  and warned about; a larger one is reported as not ready; an open arc counts
  by its ends). A contour drawn in pieces that meet end to end is reported
  once, with the fix: Join them, since GuildModel reads each piece on its own.
- A closed curve that crosses itself, or encloses no area, is not ready:
  GuildModel keeps only the largest piece of the first and drops the second.
  So is a curve with a single node, a circle or an arc with no radius, and a
  curve that lies on top of another of its layer (GuildModel reads each).
- `INLAY` seats meet the part (one may run off a body's edge, a step open
  there, as a front-mounted bridge's seat does), never cross a `LENS`, `DRILL`
  or `COMPONENT` curve (inside a component curve is a step) or a decorative opening,
  and either nest or stay apart.
- Warnings only: an `OUTLINE` that leaves the stock guide (front or temple,
  with the overrun in mm; set the guide to your blank once, in Preferences),
  and a temple `OUTLINE` that does not cross the core line (y = 0), with the
  gap in mm.

## 7. Files & data safety

- **`.gdraw`** is the native project format (a ZIP of per-workspace SVGs +
  manifest). Single-workspace SVG save/load is also supported.
- Saves are **atomic** with a `.bak` of the previous version. A save goes
  through a link to the file it names (a design kept in a synced folder) and
  keeps the file's permissions; a read-only file is left alone, with a note.
  When another window or program changed the file since this window opened
  or saved it, the save asks: **Overwrite**, **Save As…** or Cancel.
- A part of a file that does not read (a curve on a layer from a later
  GuildDraw, a number that is not one) is left out and named, and the rest
  opens; the file itself is untouched, as Save asks for a new name. A
  stored reference image or swatch the save cannot read, or no longer finds,
  is copied over from the file being replaced, or named when it cannot be.
  Every `.gdraw` member carries a fixed date, so an unchanged design saves
  to the same bytes. A path in a file is never followed outside its folder,
  and an image the design does not store is found only through this
  computer's own record (`~/.guilddraw/image_links.json`), never by a path in
  the file. The recovery file stores the same images the design does.
- **Autosave** writes a recovery file every 3 minutes while there are unsaved
  changes; after a crash, the next launch offers to restore. Each running copy
  of GuildDraw keeps its own recovery file, so a second copy never offers (or
  deletes) the first one's work. The offer has three answers: **Restore**,
  **Later** (keep the work and ask again next launch; also what Esc does) and
  **Discard**. Double-clicking a file after a crash asks first; Later opens the
  file and keeps the recovered work for next time. A recovery file that reads
  only in part is kept whole, as `failed-<time>.gdraw.bak` beside it, and a
  recovery older than its design's last save opens as a new, unsaved design.
- **A `.svg` holds the Frame Front only.** Saving one while a temple or the
  Component tab has work asks first: save as a `.gdraw` project, save the front
  alone (the design stays marked unsaved), or cancel.
- The component library lives in `~/.guilddraw/library/components/`, a
  folder per kind (see *The component library*). New shipped starter hinges
  merge into your library automatically; a component or a folder you delete
  stays deleted. The library of hinges before 2.0
  (`~/.guilddraw/library/hinges/`) moves into the Hinges folder the first
  time 2.0 starts.
- **□ (boxing square)** — `Ctrl+Shift+B` types "□" into the focused field,
  for frame-size notation like `49□27-145` (A□DBL-TempleLength) in bookmark
  names, component/drill library saves, and engraving text. Reassignable in
  *Preferences ▸ Hotkeys*. Save As on an untitled project pre-fills the
  filename with the current design's size string.
- **Appearance** (*Settings ▸ Preferences ▸ Appearance*): dark mode, canvas
  presets (Parchment / **Dimmed** / Blueprint / Matte Dark / Plain White /
  custom color), a vignette slider, node-dot size, compact toolbar, and grid
  spacing/colors/weight. Dimmed is a light-mode canvas darker than Parchment
  but still light enough for the standard line palette. Per-layer drawing
  colors (light + dark) are on the **Layers** tab.
- Preferences (theme, toolbar, hotkeys, guide defaults) are in
  `~/.guilddraw/prefs.json`, written whole each time. A value of the wrong
  kind falls back to its default, and a file that does not read is kept
  aside as `prefs.json.damaged-<time>` and said once, rather than
  overwritten.
- **For your IT department**: [IT-NOTES.md](IT-NOTES.md) documents what
  GuildDraw does and does not do (no network, no background processes,
  exactly what it writes to disk) and why unsigned builds sometimes trip
  antivirus heuristics.

## 8. Fixed shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+N` / `Ctrl+O` | New / Open |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save As |
| `Ctrl+Z` / `Ctrl+Y` (or `Ctrl+Shift+Z`) | Undo / Redo |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+D` | Copy / Paste / Duplicate |
| `Ctrl+A` | Select all (visible + unlocked) |
| `Ctrl+T` | Transform dialog |
| `Ctrl+G` / `Ctrl+Shift+G` | Group / Ungroup |
| `Ctrl++` (or `Ctrl+=`) / `Ctrl+-` / `Ctrl+0` | Zoom in / Zoom out / Fit |
| `Ctrl+,` | Preferences |
| `Ctrl+Q` | Quit |
| Mouse wheel | Zoom (0.01 to 100 screen pixels per mm; the status bar shows it) |
| Right- or middle-button drag, or `Space` + drag | Pan |
| `Delete` / `Backspace` | Delete selection (on the canvas or in the Layers panel) |
| `Esc` | Cancel tool / back to Select |

Over the Properties panel or in Preferences, the mouse wheel scrolls the page;
a number field, list or slider takes the wheel only after you click into it.
Each section of the Properties panel folds under its header: click the header
to fold it away or open it again. The panel remembers which sections you
folded, as GuildModel's does.
