# BUILDPLAN.md — GuildDraw · Road to Version 1.0

A focused, open-source 2D drafting application for acetate / horn eyewear design.
Built on Python + PySide6 (Qt 6). Single purpose: give a maker all the tools to
draw a frame front, temples, and hinge pockets, verify them against a face photo,
and export clean DXF for GuildCAM — and nothing else.

> **This document is the v1.0 roadmap.** The full v0.x history — every completed
> phase (0–19), the resolved GuildCAM intake Q&A, and the detailed feature specs —
> is archived verbatim at **`docs/BUILDPLAN-v0.9-archive.md`**. Sections of the
> archive are referenced below as *(archive §N)*.

---

## Status snapshot *(2026-06-10, v0.9.8 — M1–M8 complete; next: M9 GuildCAM validation + 1.0)*

**Working:** all drawing tools (line, spline, circle, arc), node/handle editing,
snapping (nodes/handles/midpoints/quadrants/mirror/origin), trim/split/offset,
join/explode/split-at-node, mirror system (ghost, bake, mirror-close), move gizmo +
point move, dimension lines, four tabbed workspaces (Frame Front, Temple R,
Temple L, Hinge Pocket) with Mirror Copy, hinge library, construction/boxing/stock/pad
guides, dark mode, configurable toolbar + hotkeys, `.gdraw` ZIP format, SVG round-trip,
DXF R2000 SPLINE export with validator, PNG render, PyInstaller Windows build,
layers panel + groups, on-curve snap, clipboard + Transform dialog, OMA lens-trace
import/export (TRCFMT format 1), frame fill overlay, ENGRAVING text objects,
print/PDF at 1:1 scale.

**Not yet built:** GuildCAM hardware round-trip, batch DXF export,
BRIDGE layer tooling.

**Code health:** ~10,900 lines; geometry core is solid. The M1 bug list is fixed
(v0.9.1), the repo is under git, and data safety landed in v0.9.2 (dirty-flag
guards, atomic saves with .bak, autosave/crash recovery, surfaced load errors,
Recent Files). v0.9.3 added the test suite (65 tests) and a ruff-clean
codebase. v0.9.4 centralized tool switching, document mutations
(`WorkspaceState` primitives), and mirror math (`geometry.mirror_curve`).
v0.9.5–0.9.6 delivered the maker-UX round (Layers panel v2 with eye/padlock
icons as the single layer interface, Group/Ungroup, grouped hinge imports,
Point Move root-cause fixes) and the M6 workflow set (on-curve snapping,
copy/paste/duplicate, Transform dialog, workspace-aware validation + DXF
mirror orientation, select-all). v0.9.7 shipped M7: OMA/DCS lens-trace
interchange (`export/oma.py`, Qt-free, 16 tests incl. the <0.05 mm round-trip
criterion) with File > Import/Export wiring. v0.9.8 shipped M8: frame fill
overlay, re-editable ENGRAVING `TextObject`s (`textpath.py`, Text tool,
DXF-time outline conversion), and 1:1 print/PDF with a 50 mm verification
ruler (suite: 88). Next: M9 GuildCAM validation + release.

---

## 1. Goal & scope *(unchanged — archive §1)*

Draw a frame half → mirror it → verify on a calibrated face photo → export DXF
that GuildCAM machines without manual repair. Temples and hinge pockets get the
same treatment in their own workspaces.

Explicit non-goals: gradients, layers-as-art, filters, general-purpose vector
editing, anything not related to eyewear drafting.

## 2. Export contract (GuildCAM — confirmed, do not break)

- **DXF R2000 (AC1015), SPLINE entities** — exact cubic Bézier → B-spline
  (`ezdxf.math.bezier_to_bspline`). Never pre-flatten. GuildCAM tessellates at
  0.01 mm.
- **Units: true mm at 1:1.** GuildCAM ignores `$INSUNITS`; we set 4 by convention.
- **Closed contours**: endpoints within **0.1 mm** auto-close.
- **Strict layers**: `OUTLINE` ×1, `LENS` ×2, `BRIDGE`/`HINGE` optional (machined),
  `REF` ignored, `SCULPT` (back-surface), `ENGRAVING` (temples).
- **Y-axis**: scene is Y-down; DXF is Y-up — negate Y, swap+negate arc angles.
- Full details and resolved Q&A: archive §4, §13.

**Open contract question (carried over):** asymmetric frames — does importing two
distinct LENS entities set `symmetric = False` in GuildCAM, or does it overwrite
the OS lens? Resolve during M8 hardware validation.

---

# Road to 1.0

Nine milestones. Each is small enough to finish in one or two sessions, ends in
a working app, and gets a version bump + git commit. Order matters: stabilization
and data safety come before features, because every later milestone builds on
being able to trust saves, undo, and the test suite.

> **2026-06-09 replan:** OMA lens-trace import/export was promoted from the
> Tier B candidate list to its own pre-1.0 milestone (M7) — opticians deriving
> frames from traced lenses is a headline workflow, not a nice-to-have.
> Visualization moved to M8; GuildCAM validation + release became M9.

## M1 — Stabilization (v0.9.1) · *fix the confirmed bugs* — ✅ DONE 2026-06-09

Findings from the 2026-06-09 full-code review. All verified against source.
**All 14 fixes + the Shapely hard-import landed in v0.9.1** (verified by compile
check, geometry sanity tests, and a GUI launch smoke test). Notable
implementation details: `geometry.point_at_t()` (exact evaluator) and
`geometry.arc_bbox()` were added; `dedup_ts` was replaced by mm-space
`dedup_ts_mm`; ghosts now update in place via `FrameScene._update_ghost_for`;
DimItem drags gained a 4 px threshold and an undo hook
(`FrameScene.set_dim_drag_callback`); hotkeys are suppressed while a
`QLineEdit`/spinbox has focus; zoom is clamped to 1%–10,000% via
`CanvasView.zoom_by`.

| # | Bug | Where | Fix |
|---|---|---|---|
| 1 | Offset live preview crashes (`TypeError`) on every typed digit | `tools/offset.py` `_update_preview` — `CurveItem(off_c, self._scene)` | Drop the second argument |
| 2 | Ctrl+Z crashes in target workspace after Mirror Copy | `app.py` `_copy_temple_to_other` pushes a raw *list* onto the undo stack; `_restore_snapshot` expects `{"curves":…, "dims":…}` | Push a proper snapshot dict (curves + dims) |
| 3 | Restored bookmarks get corrupted by later edits | `_restore_bookmark` installs the snapshot's live objects | `copy.deepcopy` the snapshot on restore |
| 4 | Frame width wrong when only one side is drawn | `_refresh_measurements` doubles the half-bbox width | Use `2 × max(|x − mirror_x|)` |
| 5 | Arcs inflate every bbox (measurements, SVG viewBox) | `_curves_bbox` + `svg._content_bbox` treat arcs as full circles | Compute true arc extents (endpoints + contained quadrant points) |
| 6 | Trim/Split tool switching leaves Offset/PointMove half-active (stale HUD) | `_set_tool_trim` / `_set_tool_split_curve` skip `_deactivate_cursor_tools()` | Call it (or see M4 tool registry, which eliminates the class of bug) |
| 7 | Ghost toggle silently rewrites `mirror_on_startup` pref (incl. programmatic uncheck in Mirror bake) | toggled → `_save_prefs` wiring | Separate "session state" from "startup default"; only the Settings dialog writes startup prefs |
| 8 | Export SVG mis-titles the window / status as "Saved" | `_export_svg` routes through `_do_save` | Give export its own path that doesn't touch title or `_current_path` |
| 9 | Single-key hotkeys fire while HUD text fields have focus | `QShortcut` with `WindowShortcut` context | Guard targets when a `QLineEdit` has focus, or switch to `WidgetWithChildrenShortcut` on the canvas |
| 10 | Unbounded wheel zoom (degenerate transforms) | `CanvasView.wheelEvent` | Clamp zoom to ~1%–10,000% |
| 11 | DimItem offset-drag: no undo snapshot; any left-press starts a drag | `canvas/dim.py` | Snapshot on drag start (threshold the drag like CanvasView does); delete dead `_drag_offset_start` |
| 12 | Trim/split tolerances are fractions of whole-curve t (`_T_TOL = 0.04`, `0.01 < t < 0.99`) — merges/ignores intersections on many-segment outlines | `geometry.py` | Convert tolerances to mm-space using sample spacing |
| 13 | Ghost rebuild churn: `_update_ghosts` destroys/recreates **all** ghosts on every `refresh_curve` (every drag mouse-move) | `canvas/scene.py` | Keep ghost items; `setPath()` only the changed curve's ghost |
| 14 | Hinge import centers circles/arcs by center node only (lands off-center) | `_import_from_library` | Use radius-aware bbox |

**Also in M1:** make Shapely a hard import (it's in requirements; the silent
no-Shapely fallback makes Trim/Split mysteriously dead instead of failing loudly).

## M2 — Data safety (v0.9.2) · *never lose a maker's work again* — ✅ DONE 2026-06-09

1. ✅ **`git init`** + initial commit + `.gitignore` — done at the start of M1;
   tags `v0.9.1`, `v0.9.2`.
2. ✅ **Dirty flag + unsaved-changes guard** — single document-wide flag set by
   `_push_undo_snapshot` (plus calibration, face images, bookmarks, Mirror
   Copy, forming spins, undo/redo); cleared on save/open/new. `closeEvent`,
   File → New, File → Open, and Open Recent all run `_confirm_discard()`
   (Save / Discard / Cancel). Title shows `GuildDraw <ver> — <name>*`.
3. ✅ **Surface load errors** — `load_gdraw` returns an `errors` list; on a
   partial load the app warns, sets `_current_path = None` (forcing Save As so
   the original is never overwritten with empty tabs), and marks dirty.
4. ✅ **Backup-on-save** — `_do_save` writes `<file>.tmp`, moves the previous
   version to `<file>.bak`, then atomic-replaces. A mid-write failure can
   never destroy the existing file.
5. ✅ **Autosave / crash recovery** — 3-minute timer writes
   `~/.guilddraw/autosave/recovery.gdraw` (+ JSON sidecar with source path and
   timestamp) whenever dirty; cleared on save / clean close / New. On launch,
   an existing recovery file triggers a restore prompt; restored content keeps
   the original document path and is marked unsaved.
6. ✅ **Recent Files** — File → Open Recent (8 entries, persisted in prefs,
   full-path tooltips, Clear Recent, missing files pruned on click).

*Also fixed en route (user-reported):* toolbar visibility is now the AND of
Settings prefs and per-workspace rules — the Settings dialog no longer
resurrects workspace-hidden buttons (e.g. Mirror Copy on Front), and tab
switches no longer resurrect pref-hidden ones.

*Known gap (accepted):* dragging an unlocked reference image doesn't mark the
document dirty (image position is saved but the drag bypasses all hooks);
revisit in M4 when document state is centralized.

## M3 — Engineering foundation (v0.9.3) · *tests + tooling* — ✅ DONE 2026-06-09

1. ✅ `pytest` + `ruff` in `requirements-dev.txt`; `pyproject.toml` configures
   pytest (`tests/`) and ruff (F/E9/B — bug rules only, style rules off to
   respect the aligned-assignment house style).
2. ✅ **45 tests, all green, <1 s**: `tests/test_geometry.py` (point_at_t,
   arc_bbox, mm-space dedup incl. the old 0.04-t regression, intersections +
   endpoint filtering, split continuity, segment extraction incl. wrapping,
   offset invariants), `tests/test_svg_roundtrip.py` (every curve kind, handles,
   weights, dims, bookmarks, metadata, mirrored-curve exclusion),
   `tests/test_validate.py` (counts, mirror doubling, closure tolerance),
   `tests/test_gdraw.py` (4-workspace round-trip, corrupt-tab error reporting,
   legacy temple.svg mapping), `tests/test_dxf.py` (entity types/layers, closed
   flag, Y-negation, arc angle swap+negate, mirror-layer duplication).
3. ✅ **Ruff clean** — fixed ~39 findings: dead module/local imports (incl. the
   shadowing re-import block in `WorkspaceState.__init__`), unused locals, a
   latent undefined-name in scene.py's MirrorAxis annotation, `zip(strict=True)`
   on the workspace/tab pairings.
4. ⏭ Mirror-math reflection tests deferred to M4 (written alongside the
   dedupe of the four duplicated implementations they'll be guarding).

## M4 — Architecture cleanup (v0.9.4) · *make the next ten features cheap* — ✅ DONE 2026-06-10

1. ✅ **Single tool-switch path.** `_teardown_tools(clear_selection)` is the one
   place every tool gets deactivated (draw, circle, dim, cursor tools, measure
   bar, optional selection clear); the ten `_set_tool_*` setters are now
   2–4-line activate calls. The per-setter drift bug class (M1 #6) is gone.
2. ✅ **Workspace document primitives.** `WorkspaceState` owns
   `take_snapshot / push_undo_snapshot / add_curve / remove_curve / add_dim /
   remove_dim / clear_geometry / clear_document / restore_snapshot / undo /
   redo` — the single source of truth for snapshot shape and doc↔scene
   consistency. MainWindow's undo/redo, New, file load, Temple Copy, and all
   14 hand-rolled list+scene mutation pairs now go through them; cross-workspace
   code uses the same methods as active-workspace code (the M1 #2 bug class is
   structurally gone). The read-accessor proxy properties remain (deleting them
   is mechanical churn deferred until a milestone needs to touch those lines).
3. ✅ **One mirror transform.** `geometry.mirror_curve(curve, axis_x,
   horizontal)` replaces the four near-identical implementations (scene ghosts,
   DXF export, Mirror bake, Temple Copy) plus a fifth point-mapper in the
   draw-tool preview ghost. Guarded by `tests/test_mirror.py` (13 tests:
   reflection invariants per curve kind/axis, metadata preservation,
   double-mirror identity) — written before the implementation.
4. ✅ **Dead model classes deleted** — `Document` / `WorkspaceDocument` removed
   from `document.py`; `WorkspaceState` + its primitives are the live model.
5. ⏭ `QUndoStack` migration — skipped (optional); snapshot undo behind
   `WorkspaceState.undo()/redo()` is now a one-file swap if ever wanted.

## M5 — Maker UX (v0.9.5–v0.9.6) · *layers, groups, reliable moves* — ✅ DONE 2026-06-10

### Landed 2026-06-10 (v0.9.5) — from the maker session

- ✅ **Layers panel** (sidebar tab 1, Fusion/Inkscape-style): tree of the active
  workspace's layers with every object listed beneath; per-layer **Show** and
  **Lock** checkboxes; clicking an object row selects it on canvas. Hidden
  layers vanish and offer **no snap targets**; locked layers stay visible and
  snappable (reference geometry) but can't be selected, trimmed, split,
  offset, or Alt+click-cycled. States persist in the SVG/.gdraw metadata
  (`"layers"` key) and reset on File > New. Panel auto-refreshes via
  `WorkspaceState.on_document_changed`.
- ✅ **Group / Ungroup** (Ctrl+G / Ctrl+Shift+G, Edit menu): `Curve.group_id`
  (persisted, `"group"` key). Selecting any member selects the whole group;
  grouped curves move as a rigid unit and expose **no node dots** (node insert
  is blocked too).
- ✅ **Hinge-import distortion bug fixed**: imports arrive as a group, so the
  pocket can't be warped by accidental node drags + endpoint-snap onto frame
  geometry at the origin. Root cause: loose curves at origin + 12 px endpoint
  drag-snap onto overlapping frame curves.
- ✅ **Point Move reliability fixed**: root cause — activating the tool strips
  `ItemIsSelectable`, which *clears the Qt selection*; the handler then fell
  back to a stale press-time capture that was only sometimes right. Now the
  selection is captured before activation, and the view's drag capture is
  cleared on every mouse release.

### Landed 2026-06-10 (v0.9.6) — second maker session

- ✅ **Point Move snap fix** — root cause: only draw tools registered curves
  with the SnapEngine, so Point Move had **zero snap targets** until a draw
  tool had been used (the "can't place an imported hinge" bug). The snap
  engine is now wired to the live curve list at workspace creation.
- ✅ **Layers panel v2, consolidated into Properties** — the layer combo is
  gone; the tree is THE layer interface: headerless, eye/padlock icon toggles
  (4 new SVGs: layer-show/hide/lock/unlock, theme-colored), click a layer name
  to set the **active drawing layer** (bold), click an object to select it,
  right-click for *select all on layer* / *move selection to layer* (the
  combo's old reassignment job). Selecting a curve makes its layer active and
  highlights its row.
- ✅ **Tab-switch mid-draw** now explicitly cancels the departing workspace's
  in-progress drawing with a status message (was a silent discard).

### 2026-06-08 demo retest list — resolved

- ✅ Dim drag detaching anchors — fixed in M1 #11 (drag threshold +
  offset-only); code-verified.
- ✅ Frame-width recompute error after mirror+join — fixed by M1 #4/#5.
- ✅ Snap along curve segments — shipped in M6 #1.
- ✅ Tab-switch mid-draw — explicit cancel + message (above).
- ✅ Click selection over Alt+Click — mitigated structurally: lock/hide the
  layers you're not working on; groups select as units.
- ◑ Closed-unless-reobserved (could not reproduce in code): boxing-guide
  asymmetry (`_mirror_on` is unused — both boxes always draw), move-gizmo
  origin (always selection-bbox center), mirror-axis re-snap (endpoint
  drag-snap targets the axis), 2-point calibration (dialog flow present).
  Reopen with repro steps if they resurface in real use.

## M6 — Workflow features (v0.9.6) · *carried-over CAD essentials* — ✅ DONE 2026-06-10

1. ✅ **Snap along curve segments** — nearest-point-on-curve target in
   `SnapEngine`: lowest priority (point targets always win, since every node
   lies on its curve), sample-based with bbox pre-reject, hidden layers
   excluded, hollow steel-blue **diamond** indicator. Unblocks OUTLINE→LENS
   scallop/extrusion connectors.
2. ✅ **Copy / Paste / Duplicate** (Ctrl+C/V/D, Edit menu) — in-memory
   clipboard survives workspace switches; paste lands at +5 mm, selected,
   undo-safe; pasted groups get fresh ids; layers that don't exist in the
   target workspace remap to REF with a status note.
3. ✅ **Transform dialog** (Ctrl+T) — Scale X/Y % with aspect lock, rotation,
   pivot = selection center or origin. Uniform scale keeps circles/arcs
   analytic (radius scales, arc angles shift under rotation); non-uniform
   scale converts via new `geometry.circle_to_spline` / `arc_to_spline`
   (≤0.1% radial error, tested).
4. ✅ **Workspace-aware export + validation** — `validate(curves, mirror_on,
   workspace_type)`: front OUTLINE×1+LENS×2; temple OUTLINE×1, LENS
   forbidden; hinge HINGE≥1, OUTLINE/LENS forbidden. `export_dxf(...,
   horizontal=)` mirrors temple exports across y=0 (was the wrong axis).
   Tested for both.
5. ✅ **Selection & layer QoL** — Ctrl+A select-all (visible + unlocked only);
   select-by-layer and move-to-layer via the Layers panel context menu;
   per-layer show/hide + lock shipped in v0.9.5.

## M7 — OMA lens-trace interchange (v0.9.7) · *traced lenses in, lens shapes out* — ✅ DONE 2026-06-10

**Why pre-1.0:** opticians with a frame tracer can capture a customer's
existing lens shape as OMA data; importing that trace as editable LENS
geometry turns GuildDraw into "derive a frame from a traced lens" — a
headline workflow. Export closes the loop with labs and edgers.

**Format ground truth:** OMA / The Vision Council Data Communication
Standard (DCS). ASCII `LABEL=value;value` records. Lens traces:
`TRCFMT=<fmt>;<n points>;<E|U spacing>;<side R|L>;…` followed by `R=`
records carrying radii in **1/100 mm** at equally spaced angles (format
**1** = ASCII signed integers; format **4** = packed binary). Frame box
records: `HBOX`, `VBOX`, `DBL`, `FED`, `CRIB`. Reference implementation:
[eeng/lens_protocol](https://github.com/eeng/lens_protocol) (Ruby, MIT) —
record parser/builder structure, TRCFMT two-dataset (R then L) handling,
R-records emitted in 10-value chunks; it implements format 1 only, which
confirms format 1 as the safe baseline.

Scope (all landed 2026-06-10):

1. ✅ **`framedraft/export/oma.py`** — standalone, Qt-free module:
   - `parse_oma(text) -> OmaJob` — generic record parser, TRCFMT/R dataset
     extraction per side (format 1, E spacing), 1/100 mm → mm; unknown records
     preserved verbatim through a parse → build round trip; specific
     ValueErrors for format 4 / U spacing / count mismatches / malformed lines.
   - `trace_to_curve(radii_mm) -> Curve` — polar (equal angles, CCW, y-up OMA
     frame) → scene y-down Cartesian → closed Catmull-Rom spline decimated to
     ~32 nodes; non-positive (invalid tracer) radii skipped angle-correctly.
     `compute_catmull_handles` moved from tools/draw.py into geometry.py so
     Qt-free modules can build splines (draw.py re-exports it).
   - `curve_to_trace(curve, n=400) -> radii` + `boxing_center(curve)` —
     θ-unwrap + winding/monotonicity checks reject non-star-shaped contours
     with a clear message; equal-angle resample about the bbox centre.
   - `build_oma(job) -> text` — CRLF, R records in 10-value chunks, preserved
     records first.
2. ✅ **Import UI** — File → Import → OMA Lens Trace…: lenses land in Frame
   Front (auto tab-switch) on the LENS layer, boxing centres on y=0, nasal
   edges at DBL from the file (else boxing-guide DBL), side R/OD at negative x;
   undo-safe + dirty; single-side files note that the mirror ghost previews
   the other side.
3. ✅ **Export UI** — File → Export → OMA Trace… (Frame Front only): exactly
   2 LENS contours after mirror doubling, 0.1 mm closure rule, OD/OS assigned
   by boxing-centre x; emits HBOX/VBOX/DBL/FED computed from the geometry.
4. ✅ **Tests** — 16 in `tests/test_oma.py` (suite: 81): golden-file parse,
   tolerance cases, error cases, build chunking, circle fidelity both ways,
   invalid-point skipping, non-star rejection, and the release criterion
   import → export → reimport round-trip (< 0.05 mm; measured ~0.02 mm worst
   on a lens-like shape incl. 1/100 mm quantization). Offscreen GUI smoke test
   verified import placement (nasal gap exactly = DBL), undo/redo, and export.
5. ⏭ **Stretch (slipped to 1.x as planned):** TRCFMT format 4 (packed) import,
   Z/curve records, direct serial tracer input.

## M8 — Visualization & engraving (v0.9.8) — ✅ DONE 2026-06-10

1. ✅ **Frame fill / render overlay** *(archive §25)* — `FrameScene` owns one
   `QGraphicsPathItem` (z = −500: above face photos, below geometry) built as
   union of OUTLINE curves + their mirror ghosts minus LENS curves + ghosts;
   hidden layers excluded; rebuilt from `add/remove/refresh_curve`,
   `set_mirror_display`, and `set_layer_visible` (no-op while hidden so
   boolean path ops never run during normal editing). "Frame Fill" group in
   the Guides panel (front + temple): show checkbox, colour swatch button,
   opacity slider. Per-workspace state persists in SVG/.gdraw under `"fill"`;
   resets on File > New. Display-only — never exported.
2. ✅ **Text insertion (ENGRAVING)** *(archive §26)* — `TextObject` dataclass
   (re-editable: string/font/size/rotation/anchor); new Qt-GUI-only
   `framedraft/textpath.py` builds outline paths with **true mm cap height**
   (path measured against the font's capHeight, not point-size guessing) and
   converts to closed spline Curves at DXF-export time only. `TextItem` on
   canvas: selectable, threshold-drag to move (undo-safe via the dim-drag
   callback), double-click re-opens the dialog (incl. anchor X/Y for precise
   placement), follows layer show/lock + dark mode. Text tool (`I`, toolbar
   `tool-text.svg`) is temple-only (ENGRAVING isn't a front layer — toolbar
   rule + hotkey guard). Persisted under `"texts"` in SVG/.gdraw; included in
   undo snapshots (`take_snapshot` gained a `texts` key; old bookmark
   snapshots load via `.get`). Stroke/Hershey fonts stay deferred (1.x).
3. ✅ **Print / PDF at 1:1 scale** — File > Print at 1:1 Scale… (QPrintDialog;
   "Microsoft Print to PDF" works) and File > Export > PDF (1:1 scale)….
   Renders `scene.geometry_rect()` (curves + ghosts + texts; guides stay if
   toggled on, face photos and origin cross auto-hidden) centred on the page
   at exactly printer-px-per-mm, cropped 1:1 with a warning if larger than
   the printable area, plus a printed **50 mm verification ruler** so the
   maker can catch a driver's silent fit-to-page.

Tests: 8 in `tests/test_m8.py` (textpath cap-height/rotation/anchoring/
counter-shapes + SVG round-trip of `"texts"`/`"fill"` incl. pre-M8 files;
suite 88). End-to-end smoke verified fill persistence, text
place/undo/delete/edit + DXF ENGRAVING splines, and the 1:1 PDF.
*Known gaps (accepted):* texts don't appear in the Layers-panel object tree
and aren't copied by Ctrl+C/V — revisit on demand.

## M9 — GuildCAM validation + release engineering (v0.9.9 → 1.0)

1. **Hardware round-trip** (old Phase 8): cut a real frame front + temples from
   exported DXF. Confirm layer counts, closure, spline fidelity, and resolve the
   asymmetric-lens question (§2).
2. **Batch export** — "Export All DXF…" writes `<name>_front.dxf`,
   `<name>_temple_r.dxf`, `<name>_temple_l.dxf`, `<name>_hinge.dxf` in one go,
   running each workspace's validator.
3. PyInstaller build refresh; version stamping; smoke-test the frozen build.
4. README + a short user guide (tool reference, hotkeys, GuildCAM handoff steps).
5. Tag `v1.0.0`.

### 1.0 release criteria (definition of done)

- [ ] All M1 bugs fixed; M5 demo issues retested and closed
- [ ] No data-loss path: dirty-flag guards, atomic saves, autosave recovery, load
      errors surfaced
- [ ] Test suite green (geometry, SVG round-trip, validator, DXF smoke) and run
      before every release build
- [ ] DXF from all four workspaces imports into GuildCAM and **a physical frame
      has been cut** from GuildDraw output
- [ ] OMA: a real tracer file imports as editable LENS geometry, and
      import → export → reimport round-trips within 0.05 mm
- [ ] Repository under git with tagged releases
- [ ] Packaged Windows build + written user guide

---

# Feature candidates (input for post-M-series planning)

Prioritized suggestions from the 2026-06-09 review. **Tier A** items are folded
into the milestones above; **Tier B** are strong 1.x candidates; **Parking lot**
items need a maker-demand signal first.

## Tier A — folded into the roadmap

| Feature | Why | Where |
|---|---|---|
| Autosave + crash recovery | Single worst current risk is silent work loss | M2 |
| Recent Files | Friction every single session | M2 |
| Snap along curve | Blocks the scallop/extrusion workflow today | M6 |
| Layer visibility/lock, select-all, select-by-layer | Standard CAD hygiene; cheap | M6 |
| OMA lens-trace import/export | Opticians derive frames from traced lenses; lab/edger interchange | **M7** (promoted 2026-06-09) |
| Print/PDF at **1:1 scale** | Makers test-fit on paper before cutting stock — needs only `QPrinter` + the existing scene render at true mm scale | M8 |
| Batch DXF export (all workspaces) | One frame = 4 files; doing it one tab at a time invites mistakes | M9 |

## Tier B — strong candidates for 1.x

1. **Curvature comb display** — toggle that draws normal-direction quills scaled
   by curvature along a selected spline. Eyewear outlines live or die on fair
   curves; this is the single best "make my splines beautiful" tool, and the
   sampling machinery in `geometry.py` already exists.
2. **Fillet / chamfer at node** — select a node, type a radius, get a tangent
   arc blended into the corner. Endpiece and lug corners are drawn by hand today.
3. **Lens-shape preset library** — same pattern as the hinge library
   (`~/.guilddraw/library/lenses/`): save/import LENS contours (panto, P3,
   aviator, rectangle…). Near-zero new code — generalize `HingeLibrary` to a
   typed library with a target layer.
4. **Boxing-driven starter outline** — "New from measurements": enter A/B/DBL +
   style preset, generate an editable starting LENS pair + bridge guide. Turns a
   blank canvas into a 10-minute head start.
5. **PD / optical-center markers** — after calibration, place pupil crosses on
   the photo (from PD or by clicking pupils); live readout of lens decentration
   vs. boxing center. Connects the calibration feature to an actual optical
   decision.
6. **Symmetry checker** — report max deviation between left/right halves of a
   baked-mirror outline (sampled Hausdorff distance); warns before export when a
   "symmetric" frame isn't.
7. **DXF import** — trace or reuse existing frames: import DXF outlines onto
   REF or LENS. *(OMA lens-trace import/export was promoted to milestone M7.)*
8. **Angle + radius dimension annotations** — current dims are linear only.
9. **Stroke (Hershey) fonts for engraving** — single-pass CNC engraving
   *(already specced as deferred in archive §26)*.
10. **Shared guild library sync** — read-only guild-hosted hinge/lens libraries
    over HTTP *(archive §19 future extension)*.

## Parking lot (needs demand signal)

- BRIDGE layer tooling (GuildCAM angled bridge cutaway — enum already reserved)
- Grid + grid snap (mm grid; makers may prefer guides-only)
- Multi-document / multiple `.gdraw` projects open at once
- macOS signing + notarization (archive §11)
- Localization

---

# Reference

## Module layout (current)

```
framedraft/
├── app.py                # MainWindow, WorkspaceState, CanvasView, SettingsDialog (4,400 lines — see M4)
├── document.py           # Layer, Curve, SplineNode, DimLine, WORKSPACE_LAYERS (+ unused Document/WorkspaceDocument — M4)
├── geometry.py           # sampling, de Casteljau, Shapely intersection, segment extraction, offset_curve
├── calibration.py        # CalibTool (2-point px-per-mm)
├── construction.py       # ConstructionGuides, BoxingGuide, RectGuide
├── library.py            # HingeLibrary (~/.guilddraw/library/hinges/)
├── prefs.py              # ~/.guilddraw/prefs.json (toolbar, hotkeys, startup toggles)
├── canvas/               # scene.py, items.py, dim.py, snapping.py, mirror.py, move_gizmo.py, measure_bar.py
├── tools/                # draw, edit, circle, dim, trim, split, offset, point_move
├── resources/icons/      # currentColor SVGs, rendered per-theme
└── export/               # svg.py (native format), gdraw.py (ZIP), dxf.py (ezdxf R2000), png.py, validate.py
```

## Working agreements

- One milestone per version bump; commit (and tag milestones) in git.
- Update the **Status snapshot** and check off milestone tables in this file as
  work lands; move completed milestone detail to the archive if it grows stale.
- Bug fixes land with a regression test when the code is testable without Qt.
- The GuildCAM export contract (§2) is frozen; changes require a round-trip test.
- Known-issue findings live in this file; session-to-session context lives in
  Claude's project memory.
