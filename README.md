# GuildDraw

A focused, open-source 2D drafting application for acetate / horn eyewear
design. Draw a frame front, temples, and hinge pockets; verify them against a
calibrated face photo; export clean DXF for CNC machining (GuildModel) — and
nothing else.

Built with Python + PySide6 (Qt 6). Scene units are true millimetres (1 scene
unit = 1 mm) end to end: what you draw is what gets cut.

**Status: v1.0.0-rc4 — release candidate.** All drafting features are
complete and tested (258-test suite). rc4 is a field-fixes-and-polish round:
three community-reported bugs, light-mode readability for every floating
pop-up, a reworked dimension tool, a grid appearance panel, and a size-notation
hotkey (see *New in rc4* below). Final 1.0 sign-off is gated on the GuildModel
hardware round-trip (cutting a physical frame from exported DXF), which is
pending GuildModel's redevelopment.

## Highlights

- **Four workspaces** — Frame Front, Temple R, Temple L, Hinge Pocket — in one
  `.gdraw` project file, each with its own layers, guides, and undo history.
- **Drawing tools**: line, spline (centripetal Catmull-Rom), circle, arc, with
  node/handle editing, trim, split, offset, join/explode, and a Transform
  dialog (scale/rotate about selection centre or origin).
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
  print/PDF at exact 1:1 scale with a 50 mm verification ruler for paper
  test-fits.
- **Clean DXF out**: R2000 SPLINE entities (exact Bézier → B-spline, never
  flattened), strict layer vocabulary, per-workspace validation, and batch
  export of all four workspaces in one go.

## New in rc4

- **Field fixes** — wheel-zoom no longer resets the viewport while a tool is
  active; the shipped hinge library now merges into an existing library
  instead of only seeding an empty one; Offset on a closed shape is now
  always outward on a positive distance and inward on negative, regardless of
  how the curve was drawn.
- **Light-mode pop-ups** — the Move, Point Move, and Radius/Diameter HUDs now
  read correctly in light mode (they used to sit on the app's chrome colour
  instead of their own background). The Radius/Diameter chip also moved from
  a bar docked behind the scroll bar to a floating chip near the circle/arc
  centre.
- **Dimension tool** — the snap indicator now shows while picking the first
  point, not just the second; dimension ends draw real arrowheads instead of
  ticks; the length label rotates parallel to the line and floats clear of it.
- **Grid appearance** — minor/major line colour and major line weight are now
  set in *Preferences ▸ Appearance ▸ Grid*, alongside spacing; shipped default
  is 2 mm spacing with a major line every 10 mm.
- **"Dimmed" canvas preset** — a softer light-mode canvas option between
  Parchment and the dark presets.
- **□ hotkey** (`Ctrl+Shift+B`) — types the boxing square used in frame-size
  notation (`49□27-145`) into bookmark names, the hinge/drill library dialogs,
  and the engraving text dialog; Save As pre-fills an untitled project's
  filename with the size string.
- Renamed **GuildCAM → GuildModel** throughout, matching the downstream tool's
  new name.

## New in rc3a

- **Snap palette** — a pinnable pop-out beside the Snap button with per-type
  toggles: Endpoint, Node, Midpoint, Center, Quadrant, **Intersection** (new),
  **Tangent** and **Perpendicular** (new; active while drawing a line/spline),
  Handle, On-curve, Grid, Mirror axis, and Origin — plus the snap radius. The
  Snap button stays the master on/off and holding Ctrl still suspends snapping.
- **Millimetre grid** — a Grid toolbar toggle draws a minor/major grid over the
  canvas (spacing and divisions in *Preferences ▸ Appearance*); an opt-in Grid
  snap targets its intersections in empty space.
- **Themes & appearance** — every colour now lives in one theme system: canvas
  presets (Parchment, Blueprint, Matte Dark, Plain White, or a custom colour
  with auto-derived ink), a vignette slider, per-layer colours for light and
  dark mode (*Preferences ▸ Layers*), node-dot size for high-DPI displays, and
  a compact-toolbar option.
- **Ctrl+S saves** (Ctrl+Shift+S = Save As), shown in the File menu.
- **Starter hinge library** — nine Zoye hinge pocket designs ship with the app
  and seed an empty library on first run.
- **Fixes** — intersection splits undo as one step, Mirror-Close preserves
  hand-tuned handles, OMA export boxes/trace describe the finished (beveled)
  lens, split-at-node endpoint corruption fixed, snap indicators no longer
  linger after a Point Move, and two full-codebase audits' worth of smaller
  correctness and performance work.

## New in rc2

- **Generic DXF import** (*File ▸ Import ▸ DXF…*) — bring in any existing DXF
  library. Entities on recognised GuildDraw layers keep them; everything else
  lands on the active layer for you to re-file by dragging rows in the Layers
  panel. Handles lines, polylines (incl. bulge arcs), splines, circles, arcs,
  and ellipses.
- **Bevel model + lens-locked boxing** — a bevel preset (Flat/Rimless, Horn/Metal,
  Acetate, or Custom depth) plus **Snap to lens shape**: the boxing box and a
  bevel-offset "full lens depth" outline fit the real lens, and A/B/DBL read the
  finished (beveled) measurements live.
- **Measurement-driven auto-resize** — **Lock lens shape** to freeze the spline,
  then type new A/B to restretch the lens to exact finished sizes (a chain toggle
  links A/B proportionally), and DBL to slide it. **Lock outline to lens**
  co-resizes the frame at a constant eyewire wall — preserving flats and corners —
  and auto-detects open (mirrored half) vs closed (finished) outlines.
- **Drill-mount holes** — a DRILL layer, a coordinate-entry and pattern library
  (*Library ▸ Holes*, offsets from the lens boxing centre), and **OMA `DRILLE`
  import/export** so drill-mount lens designs round-trip with labs.

## Download

- **Prebuilt Windows builds** (installer, portable exe, and zip) are on the
  [Releases](../../releases) page and our website — no Python needed.
- **Build it yourself** on Windows or Linux with the steps below.

## Install & run (from source)

Requires Python 3.12+ (developed on 3.14) and Qt 6 support (Windows, Linux, or
macOS). Three runtime dependencies: PySide6, ezdxf, shapely.

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

One command builds every distribution artifact (gates on the test suite first):

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
portable exe.

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
- **[BUILDPLAN.md](BUILDPLAN.md)** — roadmap and engineering history.

## DXF export contract (GuildModel)

- DXF R2000 (AC1015), SPLINE entities — exact cubic Bézier → B-spline.
- Units: true mm at 1:1 (`$INSUNITS = 4` by convention).
- Closed contours: endpoints within 0.1 mm auto-close.
- Strict layers: `OUTLINE` ×1, `LENS` ≥1 (at least one lens is required; a
  classic pair is two, but aviators and other shapes may carry more),
  `BRIDGE`/`HINGE` optional, `REF` ignored, `SCULPT` (back-surface),
  `ENGRAVING` (temples).
- Scene is Y-down; DXF is Y-up — Y is negated on export.

## License

GuildDraw is free software, released under the **GNU General Public License,
version 3.0** — see [LICENSE](LICENSE) for the full text. A production of the
Guild of American Spectacle Makers.
