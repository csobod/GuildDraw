# GuildDraw

A focused, open-source 2D drafting application for acetate / horn eyewear
design. Draw a frame front, temples, and hinge pockets; verify them against a
calibrated face photo; export clean DXF for CNC machining (GuildModel) — and
nothing else.

Built with Python + PySide6 (Qt 6). Scene units are true millimeters (1 scene
unit = 1 mm) end to end: what you draw is what gets cut.

**Status: v1.3.1 — stable.** All drafting features are complete and tested,
and the full hardware round-trip is proven: physical frames have been cut on
GuildModel from GuildDraw-exported DXF. The 1.3.1 update adds **File ▸ Import
▸ SVG…**, so a logo or a colleague's drawing from any editor comes in as exact
curves at the size you choose, and closes a hidden seam that closed shapes
from other programs could carry (see *New in 1.3.1*). The 1.3 round serves
the hand-made workflow and finishes engraving text as a first-class object:
*Print Front + Temples* lays the three pieces out at 1:1 on your own paper as
cutting templates, engraving text now copies, pastes, transforms and travels
with Mirror Copy (readable, not mirror-written), and Delete works from the
Layers panel (see *New in 1.3*). The 1.2 round is about
seeing the frame before it is cut: lens tints with a BPI color reference, the
frame profile filled with a real material swatch, and both of those printable
on the catalog sheet (see *New in 1.2*). The 1.1 round taught the outline layer
to carry decorative openings — an aviator's bridge keyhole, a cut-out temple —
so the readiness check and the frame-fill preview both understand multi-contour
frames, including a half-frame closed by the mirror (see *New in 1.1*). The 1.0
round rebuilt the offset engine on a curve-fitting core, added the Rebuild tool
for imported DXF outlines, made node drags stable under mid-drag zoom, and
finished the interchange story: print-quality PNG export, a catalog PDF sheet,
bevel-aware OMA import *and* export, and face photos embedded in shared project
files (see *New in 1.0*).

## Highlights

- **Four workspaces** — Frame Front, Temple R, Temple L, Hinge Pocket — in one
  `.gdraw` project file, each with its own layers, guides, and undo history.
- **Drawing tools**: line, spline (centripetal Catmull-Rom), circle, arc, with
  node/handle editing, trim, split, offset, join/explode, and a Transform
  dialog (scale/rotate about selection center or origin).
- **Mirror system**: live ghost preview across the bridge axis, one-click bake,
  mirror-close, and Mirror Copy between temple workspaces.
- **Snapping**: nodes, handles, midpoints, quadrants, on-curve nearest point,
  mirror axis, and origin.
- **Face-photo calibration**: load a reference photo, calibrate px-per-mm with
  two clicks, and design directly over the customer's face.
- **OMA/DCS lens-trace interchange**: import a frame tracer's `.oma` file as
  editable LENS geometry ("derive a frame from a traced lens"), export traces
  back to labs/edgers. Round-trips within 0.05 mm.
- **ENGRAVING text**: re-editable text objects on temples, converted to
  outline splines only at DXF export time.
- **Visualization**: frame fill overlay (outline minus lenses, over the photo),
  lens tint overlay with a two-color vertical gradient and a BPI tint color
  reference, print/PDF at exact 1:1 scale with a 50 mm verification ruler for
  paper test-fits.
- **Cutting templates**: *Print Front + Temples* lays the frame front and both
  temples out at true size on US Letter, Legal, Tabloid, A3, A4, A5 or Half
  Letter, as vectors with a tick-marked ruler on every page — print, glue to
  the blank, saw to the line.
- **Clean DXF out**: R2000 SPLINE entities (exact Bézier → B-spline, never
  flattened), strict layer vocabulary, per-workspace validation, and batch
  export of all four workspaces in one go.

## New in 1.3.1

- **Import SVG** — File ▸ Import ▸ *SVG…* reads any SVG into the active
  workspace. Paths come in as the cubic splines the file holds, one spline per
  subpath, with straight segments left straight; `rect`, `circle`, `ellipse`,
  `line`, `polyline` and `polygon` are read too, and a circle that is still a
  circle after its transforms stays a GuildDraw circle. Groups labeled with a
  GuildDraw layer name that the workspace uses keep the layer; everything
  else lands on the active layer, selected. The import asks for a width and
  the height follows; a file that declares a physical size imports at that
  size and where the file places it, so a drawing exported at true scale
  comes back where it was, while a file with no physical size (most logos) is
  read at 96 px/in and centered on the view, ready to be sized. Text, clones
  and images are counted in the status bar rather than dropped silently.
- **A closed shape from another program no longer carries a hidden seam.** A
  closed polyline that repeats its first vertex, which is how most DXF
  converters write one, imported with a zero-length segment, and Rebuild then
  fitted the hairline as a node sitting on its neighbor: a spline that crossed
  itself at the seam, which GuildModel's engraving could not fill. DXF import
  folds the repeated vertex; Rebuild and SVG import merge a hairline into its
  neighbor.

## New in 1.3

- **Print Front + Temples** — File ▸ *Print Front + Temples (1:1 Templates)…*
  and File ▸ Export ▸ *PDF Front + Temples…* lay the frame front and both
  temples out at exactly 1 mm = 1 mm, stacked and named on the paper you
  choose, as crisp vectors in each layer's print ink. A piece that will not fit
  under the previous one starts a new page, and every page carries a
  tick-marked 100 mm ruler (50 mm on small sheets) and a page counter, so a
  scaled print is caught before anything is cut. Each workspace prints what it
  shows — its visible layers, the mirror ghost (a half-drawn front prints
  whole) and its engraving text. Paper size (US Letter, Legal, Tabloid, A3, A4,
  A5, Half Letter), orientation (automatic picks the fewest pages), line weight
  and the piece labels live in *Preferences ▸ Print & PDF*. Requested by a maker who
  glues the drawing to the blank and cuts the frame by hand.
- **Engraving text is a first-class object.** Copy, Paste and Duplicate carry
  text objects (with the +5 mm offset and across workspaces, landing on REF
  where ENGRAVING does not exist); Transform scales a text's size and turns its
  rotation along with the anchor; a drag or a gizmo move on a mixed selection
  takes the text along; "select all on layer" and Alt+click cycling see text
  too. Previously a text object could only be moved on its own and re-typed.
- **Mirror Copy carries the engraving, readable.** Copying Temple R to L (or
  back) now brings the text with it, on the reflected footprint but *not*
  mirror-written: the rotation is transformed so the side of the lettering
  that faces the brow edge follows the temple, which is what puts an upright,
  outward-facing engraving on both arms. Change the words on the copy and the
  placement and style stay identical.
- **Delete works from the Layers panel.** Select one or several object rows in
  the tree (Ctrl/Shift-click) and press Delete or Backspace. Focus used to sit
  in the tree after a click, where the canvas's Delete never saw the key.
- **1:1 print and PDF draw the engraving.** The current-view print rendered
  the curves but skipped text objects; a temple with only text reported
  "nothing to print".
- **Tooltips wrap, and the ? switches them off.** Carried over from
  GuildModel so the two apps read alike: a tooltip is laid out in balanced
  lines of about fifty-six characters instead of one ribbon across the
  screen, and the **?** at the foot of the toolbar turns tooltips off
  everywhere and back on. The choice is remembered, and the button's own tip
  always shows. Each tool's tooltip now names its current hotkey, so a
  rebound tool no longer advertises its old key.
- **Preferences, tidied.** Every tab scrolls; the window opens at the size of
  its content within the screen and remembers the size you leave it at; the
  guidance under each group is one short line in a readable muted style,
  with the detail in tooltips. General groups the startup toggles in two
  columns and the Frame Front guide sizes as width × height rows; Toolbar
  groups its buttons as the toolbar does (and gains the missing Text
  button); Hotkeys lists every fixed shortcut; the PDF tab is now *Print &
  PDF*, with one group per export saying which menu item it drives.

### Interface review in 1.3

Three read-only reviews of the interface (the window chrome, the Properties
panel, the canvas tools), with a regression test for each confirmed item in
`tests/test_ui_review.py` and `tests/test_ui_review_canvas.py`.

**Changes in behavior**

- **Transform turns counter-clockwise for a positive angle**, as the Text
  dialog always has; it used to turn clockwise. Selected dimensions now move
  with the drawing instead of staying where they were.
- **Library ▸ Holes reads Y upward and X toward the nose**, on either lens,
  as the OMA datum it refers to does; a typed +3 mm used to land 3 mm below
  the lens center. A pattern now lands the same way on a frame drawn on
  either side of the mirror; one saved on the right-hand lens used to land
  nasal-for-temporal on a frame drawn on the left. Patterns saved before 1.3
  are placed as they were drawn.
- **OK in Preferences applies only what you changed.** It re-applied every
  startup value, so switching dark mode turned Snap back on and reset the
  stock and boxing sizes on the Frame Front. The Ghost setting now applies to
  the next document only; it no longer flips the open design's mirror.
- **Standard shortcuts**: Ctrl+N, Ctrl+O, Ctrl+Q, Ctrl++ / Ctrl+-, and
  Ctrl+0 for Fit. A hotkey can no longer take one of these, or a key the
  tools read while you type a value (digits, the decimal point, Enter, Tab).
- **The window remembers its size and place**; the first launch fits it to
  the screen instead of opening at 1440 × 860 on a smaller laptop panel.

**Data safety**

- **Double-clicking a file after a crash** asks about the recovered work
  first. The file used to open before the recovery offer, and opening it
  deleted the recovery file. The offer's answers are Restore, Later (keep it
  for the next launch) and Discard; No used to delete the work.
- **Each running copy keeps its own recovery file.** A second copy used to
  offer the first copy's live work, and answering No deleted it.
- **Saving a .svg while a temple or the hinge has work asks first**: save a
  .gdraw project instead, save the front alone (the design stays marked
  unsaved), or cancel. Ctrl+S on a .svg used to drop that work silently.
- **A failed Save As keeps the old file name**; every later Ctrl+S used to
  target the file that failed.
- **PDF and print exports report a failure** (an unwritable folder, a PDF
  open in another program) instead of announcing a file that was never
  written.

**Fixes**

- The trim, split, fillet, offset and rebuild tools act on the curve nearest
  the click; they took the topmost curve within a few pixels, so drawing
  order decided which curve was cut. Split's crossing-curve cut leaves locked
  layers and parallel neighbors alone.
- Undo during Fillet, Rebuild, Offset or Point Move ends the tool first;
  finishing the operation afterwards duplicated curves or reported a move
  that never happened. Ctrl+Z with the Line tool idle undoes the document.
- A right-click no longer acts like a left-click in the tools. Double-click
  no longer adds a node to a curve on a locked layer or a locked lens. Text
  can no longer be dragged by Qt on its own after a tool switch (it moved
  with no undo step). Calibration ends when you pick another tool.
- The pointer coordinates have their own place in the status bar; they used
  to replace each tool's instructions on the first mouse move. Refusals and
  "canceled" messages stay on show, and the autosave note hands the bar back.
- The mouse wheel scrolls the Properties panel and Preferences; it changed a
  field under the pointer, which with a locked lens resized it one undo step
  per notch. DBL, like A and B, applies when you finish typing.
- The Measurements update after every change, so their Refresh button is
  gone; moving a lens to another layer now updates them (and the fills),
  which it did not. Clicking away from the image scale field no longer
  applies its 1.0 placeholder (a large photo became meters wide). Frame
  height reads an outline joined across the mirror axis. The readiness dot follows node
  drags. Snapping the boxing guide no longer marks the design unsaved.
- Explode, Split and Snap Node follow the selection of the tab you switch
  to; New and Open end a half-drawn line and keep the panel's settings;
  hiding the Ghost button keeps its View menu entry.
- The pinned ⋯ pop-out no longer collapses to an empty box, and its ⋯
  button and the dock's tab arrows draw their glyphs. The dock is wide enough
  for its five tabs. Disabled controls look disabled, and checkboxes are
  drawn in the app's own colors, so an unchecked box is clear in dark mode
  (GuildModel 1.8 carries the same rules).
- The fill sliders repaint the fill instead of recomputing it (about 35 ms a
  tick on a real frame), and switching tabs no longer re-reads a material
  swatch from disk. Snapping near dense imported traces is fast again.
- Edit Text with no changes keeps every value exactly and adds no undo step.
- Dragging a reference photo marks the design unsaved (its place is saved
  with it). Temple Endpiece width reads a one-piece outline. The 1:1 print
  and the templates mirror only the layers the canvas ghosts (a REF line
  printed twice). Dragging a red node keeps it red, so Delete still removes
  the node. The overflow pop-out stays below the menus, and the window can be
  made as short as a small laptop panel needs. Restoring a bookmark mid-tool
  no longer duplicates curves, and the wheel scrolls every list and panel.
- Undoing Mirror (bake) switches Ghost back on, and Redo switches it off
  again; Undo used to restore the single lens and leave half a frame showing.
- American spelling throughout: the interface, the documentation and the
  code (color, center, canceled).

### Bug-hunt fixes in 1.3

A source-wide review before this release, with a regression test for each
of the confirmed items. The ones a maker could have met:

- **Trim and Split cut where you click.** The cut parameter was the nearest
  of 32 samples per segment and never refined, so a trim on a 100 mm line
  could end up to 0.7 mm short of the cutting edge, and the pieces of an
  intersection split did not always meet at one point. The parameter is now
  solved to well below machining tolerance. Splitting a closed curve opens
  it at the click as one curve instead of two pieces with a hidden second cut
  at the seam, and a split-off piece no longer carries a stray handle at its
  ends.
- **DXF import no longer aborts on a periodic spline** (how Rhino and
  AutoCAD write a closed spline); it is sampled instead. Entities written in
  a mirrored coordinate system (AutoCAD's MIRROR command) land where the CAD
  file shows them rather than x-mirrored, block references (INSERT) are
  expanded with their transform, and 3D polylines are reported as skipped
  instead of vanishing.
- **Deleting one of two identical curves** (a double paste, a duplicate DXF
  entity) removed the *other* one from the document while the scene kept it:
  the survivor on screen was no longer saved or exported. Removal is by
  identity now.
- **DRILL holes ghost on canvas** the way they mirror in the DXF; the three
  places that listed the mirrored layers were unified.
- **Select-all and box-select are instant** on large drawings. Every
  selection change (and every wheel tick) re-ran the export validator, so
  selecting a few hundred curves took seconds.
- **Escape from Line, Spline, Circle, Arc or Dimension** returns the canvas to
  Select mode; it used to leave the view routed to the dead tool with nothing
  selectable until the Select button was clicked. Escape before a circle's
  center is placed now cancels, a double-click that ends a line keeps the
  point under it, and a double-click while dimensioning no longer inserts a
  node in the curve underneath.
- **Opening a plain .svg** clears the temple and hinge workspaces (the previous
  project's were riding along into the next save), a `.svg` document always
  saves the Frame Front whatever tab is showing, Save As adds the `.gdraw`
  suffix when the dialog hands back a bare name, and every export adds its
  own suffix.
- **Crash recovery** no longer restores the original file's path when part of
  the recovery file failed to load (Ctrl+S could overwrite the original with
  an empty tab), an unreadable recovery file is kept under another name
  instead of being offered and failing on every launch, and opening a file
  clears the previous document's recovery slot.
- **Opening a file resets session state**: the boxing snap, the lens and
  outline locks and a custom bevel from the previous document no longer leak
  into the next one.
- **Clicking a node or handle** no longer adds an undo step and marks the
  document unsaved; the snapshot is taken on the first real movement.
- **Hiding the OUTLINE (or LENS) layer** pauses the Frame Fill (Lens Fill)
  instead of switching it off for good.
- **Mirror-axis snapping** no longer steals an endpoint that sits on the axis
  (the projection is a zero-distance hit), which left a gap the perimeter
  could not close. Snap distances are measured to the sub-pixel, and the
  on-curve/intersection snaps no longer miss the bulge of a wide lens.
- **Curves are as easy to click at 25 % zoom as at 400 %**: hit-testing uses
  a screen-pixel tolerance instead of a fixed 2 mm stroke.
- **A move with the gizmo** keeps the node dots on the moved curve;
  Preferences no longer rewrites the selected curve's line weight or resizes
  a locked lens to the startup A/B; the Undo/Redo menu follows the tab; a
  reference photo added after calibration takes that scale straight away.
- **Temple Copy** refuses an empty source instead of offering to wipe the
  other temple, keeps grouped hinges grouped, and puts dimensions on the
  correct side. Mirror bake keeps groups too. Explode leaves circles and arcs
  whole (it deleted an arc and left a radius-less ghost of a circle).
- **Layers panel**: rows on a locked layer can no longer be dragged to another
  layer, text rows can be, a layer you expanded or collapsed stays that way
  across rebuilds, and clicking a row while a drawing tool is active switches
  to Select instead of silently selecting nothing.
- **A hotkey bound to a fixed shortcut** (Ctrl+Z, Ctrl+S…) is flagged in
  Preferences; Qt treated the pair as ambiguous and fired neither, so Undo
  simply died.
- **Rebuild on a dense imported polyline** fits the vertices themselves
  instead of 24 samples per segment (a 500-vertex outline took over a second
  per keystroke); the confirmed fit is reused instead of recomputed.
- **Offsetting an arc inward by more than its radius** is refused instead of
  producing an invisible zero-radius curve; a retracted spline handle no
  longer sends the offset endpoint along the wrong normal.
- **The catalog sheet and the Measurements panel** use the drawn extent, not
  the Bézier control polygon (a hand-tuned lens measured a third taller than
  it draws and centered several millimeters off).
- **A shared `.gdraw` that inflates to hundreds of megabytes** is refused
  from the archive directory, before anything is decompressed; an unwritable
  image cache falls back to a temp folder and never strips the photos from
  the next save.
- Also: OMA lab request files with an empty trace record open; the PNG crop
  includes engraving text; icons render sharp on HiDPI screens; a prefs file
  with a malformed theme block no longer stops the app starting; and a fresh
  install no longer mutates the shipped defaults in memory.

## New in 1.2

- **Lens Fill** — tint the lenses, not just the frame. Guides ▸ Lens Fill paints
  each LENS aperture with a vertical two-color gradient the way a dyed lens
  runs, so a design reads as finished eyewear over the face photo. The chain
  button links the two stops for a flat tint. Two sliders separate the two
  things people mean by "stronger": **Intensity** is how deeply the dye reads,
  **Opacity** is how much shows through from behind. Both defaults are yours to
  set in Preferences ▸ General. Display-only — never exported to DXF/SVG
  geometry, and saved with the design.
- **Frame Fill from a material swatch** — Guides ▸ Frame Fill gains a **Style**
  choice: the flat color it has always had, or an image. Point it at a
  supplier's acetate sample sheet and the frame shows the pattern it would
  really be cut from — the thing a flat color can't do for a laminate or a
  tortoise. The swatch is scaled to span your Stock Blank width and centered on
  the origin, so it lands on the drawing exactly as the sheet would sit under
  it; change the stock width and the material rescales with it. Saved `.gdraw`
  files embed the swatch the way they embed a face photo, so a shared project
  shows the material on the recipient's machine.
- **BPI tint reference** — the **BPI** button beside each color opens a
  searchable grid of approximate screen colors for BPI's published tint
  catalog; click one to drop its hex into that gradient stop. The table ships
  as plain name/hex data (`framedraft/resources/bpi_tints.json`, regenerated by
  `scripts/scrape_bpi_tints.py`) — no artwork is bundled. Approximate and
  unofficial: not a dye-lot match, and GuildDraw is not affiliated with BPI.
  Those swatches are published as a light tint over white, so expect to raise
  Intensity after picking one.
- **Frame and lens color on the catalog sheet** — File ▸ Export ▸ PDF for
  Catalog can now print the Frame Fill and Lens Fill overlays under the line
  work, per workspace, exactly as the canvas shows them: the material swatch
  or tint in the frame profile and the gradient in each aperture. Off by
  default in Preferences ▸ PDF — off is the cutting-room sheet, on is the
  showroom page.
- **Font boxes filter instead of guessing** — the Text tool's font picker and
  the caption font in Preferences ▸ PDF stay quiet until you type, then narrow
  to the families that match and drop them down, still completing the best
  match inline. Nothing is loaded from a large font library up front, and a
  weight or an italic is one glance away instead of a scroll past two dozen
  near-identical siblings.
- **PNG export writes the file** — a name typed without a `.png` suffix
  produced no file at all, and the export said it had succeeded.
- **A clear message on too old a Python** — the dependencies install fine on
  Python 3.11 and older, so the mismatch used to surface as an unreadable
  `TypeError` at startup. GuildDraw now says which interpreter it found and how
  to build a virtualenv on a newer one before it imports anything.
- **Join closes a curve onto itself** — select a single open curve whose two
  ends meet and press Join to fuse them into a closed loop. This is the shape
  an imported DXF lens trace comes back as after a Rebuild: one spline that
  reads as closed but is still an open path, which no amount of chaining could
  fix because there is no second curve to chain to.
- **Snapping the boxing guide no longer strands a box** — turning on "Snap to
  lens shape" force-shows the boxing guide (the bevel outline rides on it).
  Turning it back off now restores the guide to however you had it, instead of
  leaving a default-sized box parked over the drawing.
- **Opening a file refreshes the sidebar** — loading a design while already on
  its saved workspace tab left the guide and fill controls showing the previous
  document's values.

## New in 1.1

- **Aviator & cut-out frames** — the OUTLINE layer can now carry more than one
  closed contour: the largest is the frame profile and any closed curve drawn
  inside it is a decorative opening (an aviator's bridge keyhole, a cut-out
  temple), matching GuildModel's intake. The readiness dot stays green for these
  frames instead of flagging "more than one outline" (community-reported).
- **Frame Fill understands openings and Ghost mode** — the fill preview punches
  those openings through the frame body, and it finally works while you mirror:
  draw one half of a frame against the mirror line and the fill closes it with
  the live ghost. It recognizes endpoints snapped together (so an unjoined half
  still reads as closed), warns if the perimeter has a leak when you switch it
  on, and quietly turns itself off if you break the perimeter while it's showing
  — rather than painting something wrong.
- **Preferences shortcut** — `Ctrl+,` opens Preferences, matching GuildSend and
  GuildModel.

## New in 1.0

- **Trustworthy Offset** — the offset engine was rewritten to follow the true
  drawn curve (adaptive per-segment offsetting), then refit through a new
  least-squares curve-fitting core so results stay compact and hand-editable:
  a two-node lens outline offsets to ~8 clean nodes instead of collapsing or
  ballooning. Fixes the community-reported offset failures (#5, #6).
- **Rebuild tool** (`R`) — refit any spline or polyline to a target node
  count or a millimeter tolerance, with a live achieved-deviation readout.
  Turns a 400-point imported DXF outline into a clean editable spline in one
  step.
- **Rock-solid node drags** — node and handle drags no longer "fly away" when
  the wheel grazes mid-drag; zooming *while* dragging is now safe (and
  useful). Also fixed a crash when deleting a dimension.
- **Print-quality PNG export** (#7) — true print resolution (150–1200 dpi
  picker), cropped to the drawing, instead of a screen-resolution snapshot.
- **PDF for Catalog** — front + both temples on one landscape sheet with the
  design's name, true size when it fits; paper size, line weight, caption
  font, and a binding-margin offset in *Preferences ▸ PDF*. Print/PDF at 1:1
  now renders exactly what your viewport frames, in print inks.
- **Bevel-aware OMA, both directions** — import asks whether to shrink a
  trace from the finished (beveled) lens back to the drawn lens opening;
  export asks whether to grow it. Round-trips exactly at the same depth.
- **Face photos travel with the file** — `.gdraw` projects now embed the
  reference photo: share a fit-check file and the recipient sees it, and the
  file no longer records the photo's location on your machine.
- **Settings scoping fix** (#4) — saving Preferences while in a temple
  workspace no longer rewrites that workspace's stock/pad guides.
- **[IT notes](docs/IT-NOTES.md)** — a one-page answer for IT departments:
  no network, no persistence, exactly what the app writes to disk.

## Download

Prebuilt builds are on the [Releases](../../releases) page and our website —
no Python needed:

- **Windows** — `-setup.exe` installer (recommended; per-user, no admin,
  upgrades in place), or the portable `-win64.zip` / single-file `.exe`.
- **macOS** — `.dmg` (drag to Applications) or `.zip`, in **arm64**
  (Apple Silicon) and **x86_64** (Intel) flavors.

First launch: the builds are unsigned (see [IT notes](docs/IT-NOTES.md)) — on
Windows, SmartScreen wants *More info ▸ Run anyway* once; on macOS,
**right-click the app ▸ Open** once.

Or **build it yourself** on Windows, macOS, or Linux with the steps below.

## Install & run (from source)

Requires **Python 3.12+** (developed on 3.14) and Qt 6 support (Windows, Linux,
or macOS). Three runtime dependencies: PySide6, ezdxf, shapely.

**Check your interpreter first** — the dependencies install happily on older
Pythons, and the app only fails later, at startup:

```bash
python3 --version
```

macOS in particular ships a `python3` older than GuildDraw needs. If yours is
below 3.12, install a current one (the [python.org](https://www.python.org/downloads/)
installer, or `brew install python@3.12`) and name it explicitly when you create
the virtualenv — `python3.12 -m venv .venv` — or skip the build entirely and use
the [`.dmg`](../../releases), which needs no Python at all.

**Windows** (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

**Linux / macOS** (bash):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

On a bare Linux box Qt may also need the usual X/XCB system libraries (e.g. on
Debian/Ubuntu: `sudo apt install libxcb-cursor0 libegl1`).

## Packaging (building executables)

### Windows

PyInstaller does not cross-compile, so the Windows build is made **on Windows**
— either your own machine or GitHub's free runners:

- **Without a Windows machine**: the repository ships a GitHub Actions workflow
  (*Actions ▸ Windows build ▸ Run workflow*) that builds on GitHub's
  `windows-latest` runners and uploads all three artifacts for download. It
  installs Inno Setup itself and fails the run if any artifact is missing,
  rather than quietly shipping a release without its installer.
- **On Windows**, one command builds every distribution artifact (gates on the
  test suite first):

```
.venv\Scripts\pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
```

It writes three files to `dist\` (version stamped from `framedraft/__version__`):

| Artifact | What it is |
|---|---|
| `GuildDraw-<ver>-setup.exe` | **Installer** — per-user (no admin), Start Menu + optional Desktop shortcuts, `.gdraw` file association, Add/Remove Programs uninstaller. Built with [Inno Setup](https://jrsoftware.org/isinfo.php). |
| `GuildDraw-<ver>.exe` | **Portable** single-file build — double-click to run, nothing to install. |
| `GuildDraw-<ver>-win64.zip` | **Portable folder** — unzip and run `GuildDraw.exe` (fastest launch). |

The installer step needs Inno Setup (`winget install JRSoftware.InnoSetup`); the
script warns and skips it if `ISCC.exe` isn't found, still producing the zip and
portable exe. Set `GUILDDRAW_SKIP_TESTS=1` to skip the script's own test gate
when the caller has already run the suite — which is what the workflow does, so
that a hung test is caught by a per-test timeout instead of the job's.

Build a single artifact by hand:

```
.venv\Scripts\python -m PyInstaller framedraft.spec --clean           # one-folder -> dist\GuildDraw\
.venv\Scripts\python -m PyInstaller framedraft-onefile.spec --clean   # portable  -> dist\GuildDraw.exe
"%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" installer\GuildDraw.iss
```

Both specs share their hidden-imports / Qt-excludes / bundled data via
`build_common.py`. The app icon is rendered from `assets/icon.svg` by
`scripts/make_icon.py` (run automatically by the release script; the build
works without it — PyInstaller just falls back to its default icon).

### macOS

PyInstaller does not cross-compile, so the macOS build is made **on a Mac** —
either your own or GitHub's free runners:

- **On a Mac**: create the venv (see *Install & run*), then

  ```bash
  .venv/bin/pip install -r requirements-dev.txt
  bash scripts/build_release_macos.sh
  ```

  It gates on the test suite, then writes `GuildDraw-<ver>-macos-<arch>.zip`
  and a drag-to-Applications `.dmg` to `dist/` for the architecture you build
  on (arm64 on Apple Silicon, x86_64 on Intel).
- **Without a Mac**: the repository ships a GitHub Actions workflow
  (*Actions ▸ macOS build ▸ Run workflow*) that builds on GitHub's macOS
  runners and uploads the same artifacts for download.

Like the Windows builds, the app is **unsigned and not notarized** (no
certificate budget); it is ad-hoc signed, which Apple Silicon requires. On
first launch macOS will refuse a normal double-click on a downloaded copy —
**right-click the app ▸ Open ▸ Open** once (or
`xattr -cr /Applications/GuildDraw.app`), and it opens normally after that.

### Linux

PyInstaller is cross-platform; the same one-folder spec produces a native Linux
binary. There's no `.ico` and no Inno installer — ship the folder (or a tarball):

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m PyInstaller framedraft.spec --clean      # -> dist/GuildDraw/GuildDraw
```

Build on the oldest Linux/glibc you intend to support, since PyInstaller bundles
against the host's system libraries.

## Tests

```
.venv\Scripts\python -m pytest tests -q
```

## Documentation

- **[User guide](docs/USER-GUIDE.md)** — tool reference, hotkeys, workflows,
  GuildModel handoff.
- **How-to videos** — a tutorial series is in the works on YouTube; links
  will land here when they're up.
- **[IT notes](docs/IT-NOTES.md)** — what GuildDraw does and does not do, for
  IT departments and security reviewers.
- **[BUILDPLAN.md](BUILDPLAN.md)** — roadmap and engineering history.

## DXF export contract (GuildModel)

- DXF R2000 (AC1015), SPLINE entities — exact cubic Bézier → B-spline.
- Units: true mm at 1:1 (`$INSUNITS = 4` by convention).
- Closed contours: endpoints within 0.1 mm auto-close.
- Strict layers: `OUTLINE` ≥1 (the largest contour is the profile; closed
  contours inside it are decorative openings), `LENS` ≥1 (at least one lens
  is required; a classic pair is two, but aviators and other shapes may carry
  more), `BRIDGE`/`HINGE` optional, `DRILL` (mirrors with the lens), `REF`
  ignored, `SCULPT` (back-surface), `ENGRAVING` (temples).
- Scene is Y-down; DXF is Y-up — Y is negated on export.

## License

GuildDraw is free software, released under the **GNU General Public License,
version 3.0** — see [LICENSE](LICENSE) for the full text. A production of the
Guild of American Spectacle Makers.
