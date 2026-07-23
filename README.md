# GuildDraw

A focused, open-source 2D drafting application for acetate / horn eyewear
design. Draw a frame front, temples, and hinge pockets; verify them against a
calibrated face photo; export clean DXF for CNC machining (GuildModel) — and
nothing else.

Built with Python + PySide6 (Qt 6). Scene units are true millimetres (1 scene
unit = 1 mm) end to end: what you draw is what gets cut.

**Status: v1.1.0 — stable.** All drafting features are complete and tested
(354-test suite), and the full hardware round-trip is proven: physical frames
have been cut on GuildModel from GuildDraw-exported DXF. The 1.1 round teaches
the outline layer to carry decorative openings — an aviator's bridge keyhole,
a cut-out temple — so the readiness check and the frame-fill preview both
understand multi-contour frames, including a half-frame closed by the mirror
(see *New in 1.1*). The 1.0 round rebuilt the offset engine on a curve-fitting
core, added the Rebuild tool for imported DXF outlines, made node drags stable
under mid-drag zoom, and finished the interchange story: print-quality PNG
export, a catalog PDF sheet, bevel-aware OMA import *and* export, and face
photos embedded in shared project files (see *New in 1.0*).

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

## New in 1.1

- **Aviator & cut-out frames** — the OUTLINE layer can now carry more than one
  closed contour: the largest is the frame profile and any closed curve drawn
  inside it is a decorative opening (an aviator's bridge keyhole, a cut-out
  temple), matching GuildModel's intake. The readiness dot stays green for these
  frames instead of flagging "more than one outline" (community-reported).
- **Frame Fill understands openings and Ghost mode** — the fill preview punches
  those openings through the frame body, and it finally works while you mirror:
  draw one half of a frame against the mirror line and the fill closes it with
  the live ghost. It recognises endpoints snapped together (so an unjoined half
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
  count or a millimetre tolerance, with a live achieved-deviation readout.
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
  (Apple Silicon) and **x86_64** (Intel) flavours.

First launch: the builds are unsigned (see [IT notes](docs/IT-NOTES.md)) — on
Windows, SmartScreen wants *More info ▸ Run anyway* once; on macOS,
**right-click the app ▸ Open** once.

Or **build it yourself** on Windows, macOS, or Linux with the steps below.

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
- Strict layers: `OUTLINE` ×1, `LENS` ≥1 (at least one lens is required; a
  classic pair is two, but aviators and other shapes may carry more),
  `BRIDGE`/`HINGE` optional, `REF` ignored, `SCULPT` (back-surface),
  `ENGRAVING` (temples).
- Scene is Y-down; DXF is Y-up — Y is negated on export.

## License

GuildDraw is free software, released under the **GNU General Public License,
version 3.0** — see [LICENSE](LICENSE) for the full text. A production of the
Guild of American Spectacle Makers.
