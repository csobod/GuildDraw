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

## Status snapshot *(2026-06-09, v0.9.1 — M1 complete)*

**Working:** all drawing tools (line, spline, circle, arc), node/handle editing,
snapping (nodes/handles/midpoints/quadrants/mirror/origin), trim/split/offset,
join/explode/split-at-node, mirror system (ghost, bake, mirror-close), move gizmo +
point move, dimension lines, four tabbed workspaces (Frame Front, Temple R,
Temple L, Hinge Pocket) with Mirror Copy, hinge library, construction/boxing/stock/pad
guides, dark mode, configurable toolbar + hotkeys, `.gdraw` ZIP format, SVG round-trip,
DXF R2000 SPLINE export with validator, PNG render, PyInstaller Windows build.

**Not yet built:** snap-along-curve, copy/paste/transform, frame fill overlay,
text/engraving, GuildCAM hardware round-trip, BRIDGE layer tooling.

**Code health:** ~10,700 lines; geometry core is solid. The M1 bug list from the
2026-06-09 review is fixed (v0.9.1) and the repo is under git. Remaining gaps:
no unsaved-changes protection (M2), no tests (M3), and `app.py` is a 4,400-line
god-object whose proxy-property pattern breeds bugs (M4).

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

Eight milestones. Each is small enough to finish in one or two sessions, ends in
a working app, and gets a version bump + git commit. Order matters: stabilization
and data safety come before features, because every later milestone builds on
being able to trust saves, undo, and the test suite.

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

## M2 — Data safety (v0.9.2) · *never lose a maker's work again*

This is the highest-value milestone in the plan.

1. **`git init`** + initial commit + `.gitignore` (`.venv/`, `dist/`, `build/`,
   `__pycache__/`, `.pytest_cache/`). Commit at every milestone from here on.
2. **Dirty flag + unsaved-changes guard** — track modification per workspace
   (set on every `_push_undo_snapshot`, cleared on save). Override `closeEvent`;
   prompt on File → New *and* File → Open. Show `*` in the title bar.
3. **Surface load errors** — `load_gdraw` currently swallows per-tab parse errors
   (`except Exception: pass`), so a corrupt tab loads *empty* and the next save
   destroys it. Collect errors, show them, and refuse to mark the document clean.
4. **Backup-on-save** — write to a temp file, then atomic-replace; keep one
   `.gdraw.bak` of the previous version.
5. **Autosave / crash recovery** — timer-based autosave to
   `~/.guilddraw/autosave/<name>.gdraw` every N minutes when dirty; offer recovery
   on next launch if an autosave is newer than its source.
6. **Recent Files** menu (persisted in prefs).

## M3 — Engineering foundation (v0.9.3) · *tests + tooling*

1. Add `pytest` + `ruff` to `requirements-dev.txt`; add minimal `pyproject.toml`.
2. **Geometry tests** (pure Python, no Qt — highest ROI):
   `extract_open_segment` / `extract_wrapping_segment` invariants,
   `split_curve_at_t`, `offset_curve` (line miter, closed spline, circle/arc),
   `dedup_ts`, arc angle conventions.
3. **SVG round-trip test** — `save_svg → load_svg` equality for every curve kind,
   dims, bookmarks, face-image metadata.
4. **Validator tests** — OUTLINE/LENS counts with mirror on/off, closure tolerance.
5. **DXF smoke test** — export a known document; reload with ezdxf; assert entity
   types, layers, and closure flags.
6. Mirror-math tests (vertical + horizontal reflection of line/spline/circle/arc —
   this math is duplicated in four places today; tests first, then dedupe in M4).

## M4 — Architecture cleanup (v0.9.4) · *make the next ten features cheap*

No big-bang rewrite — three incremental moves:

1. **Tool registry.** One `_activate_tool(name)` on MainWindow that deactivates
   every registered tool, clears HUDs/selection consistently, then activates the
   target. Deletes the ten hand-rolled `_set_tool_*` dances (source of M1 #6).
2. **Workspace controller.** Move document mutations (`add_curve`,
   `delete_selected`, `push_undo`/`restore`, `join`, `split`, `explode`,
   `mirror_close`, `duplicate_mirror`) from MainWindow into `WorkspaceState`
   methods that take explicit state — no proxy properties. MainWindow keeps
   wiring + widgets only. Proxies are then deleted incrementally as call sites
   migrate. (The Mirror Copy bug happened precisely because cross-workspace code
   can't use the proxies.)
3. **One mirror-transform function.** `mirror_curve(curve, axis, horizontal)` in
   `geometry.py`; used by scene ghosts, DXF export, Mirror bake, and Mirror Copy
   (currently four near-identical implementations).
4. **Adopt or delete the dead model classes** — `Document` / `WorkspaceDocument`
   in `document.py` are defined but unused. Either make `WorkspaceDocument` the
   single source of truth that the sidebar reads/writes (preferred; kills the
   fragile `_save/_restore_ws_sidebar_state` dance), or delete them.
5. *(Optional, if appetite remains)* migrate snapshot undo to `QUndoStack` per
   workspace — gets command merging and enable/disable state for free.

## M5 — Maker-demo UX fixes (v0.9.5) · *retest, then fix what's still broken*

Carried from the 2026-06-08 demo (archive "Known issues"). Some may already be
fixed — retest each first:

- [ ] **Click selection over-reliant on Alt+Click** — selecting a lens inside an
  outline is hard. The stroked `shape()` fix exists; verify hit tolerance scales
  with zoom and tune.
- [ ] **Dim drag detaches anchors** — code now routes dim drags to offset-only;
  verify fixed, then close.
- [ ] **2-point calibration flow** — `CalibTool` does pop the mm dialog in current
  code; verify end-to-end with a real photo, then close.
- [ ] **Boxing guide asymmetry when Ghost off** — `_mirror_on` is stored but
  unused in `BoxingGuide._refresh`; verify behavior and remove the dead flag or
  honor it.
- [ ] **Move gizmo origin** — gizmo should center on selection bbox even when a
  node is focused.
- [ ] **Mirror-line re-snap after move** — endpoint drag-snap to the axis exists;
  verify it works after a whole-curve move; consider a "snap endpoints to axis"
  one-click repair action.
- [ ] **Frame-width recompute error after mirror+join** — likely fixed by M1 #4/#5;
  reproduce, confirm, close.
- [ ] **Tab-switch mid-draw silently discards placed nodes** — either commit the
  in-progress curve or warn.

## M6 — Workflow features (v0.9.6) · *carried-over CAD essentials*

1. **Snap along curve segments** *(the #1 maker request — needed for
   OUTLINE→LENS scallop/extrusion connections)*. Add nearest-point-on-curve snap
   target to `SnapEngine` (sample-based, mm tolerance, lowest priority so node
   snaps still win). Indicator: hollow diamond.
2. **Copy / Paste / Duplicate** (Ctrl+C/V/D) — shared clipboard across
   workspaces; paste offset +5 mm; undo-safe. *(spec: archive §23a)*
3. **Transform dialog — Scale / Rotate** with pivot choice; non-uniform scale of
   circles/arcs converts to 4-segment Bézier spline. *(spec: archive §23b)*
4. **Workspace-aware export + validation** — `validate()` gets the workspace
   type (front: OUTLINE×1 + LENS×2; temple: OUTLINE×1, no LENS; hinge: HINGE≥1);
   `export_dxf` gets the mirror orientation (temple/hinge mirror is horizontal —
   currently exported across the wrong axis).
5. **Selection & layer QoL**: Ctrl+A select-all, select-by-layer menu, per-layer
   show/hide and lock toggles in the Properties tab.

## M7 — Visualization & engraving (v0.9.7)

1. **Frame fill / render overlay** — translucent fill of OUTLINE−LENS over the
   face photo; display-only. *(full spec: archive §25)*
2. **Text insertion (ENGRAVING)** — re-editable `TextObject` via
   `QPainterPath.addText`; converted to splines at DXF export. *(full spec:
   archive §26; stroke fonts stay deferred)*
3. **Print / PDF at 1:1 scale** *(new — see Feature candidates)* — true-scale
   paper test fit before cutting stock.

## M8 — GuildCAM validation + release engineering (v0.9.8 → 1.0)

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
| Print/PDF at **1:1 scale** | Makers test-fit on paper before cutting stock — needs only `QPrinter` + the existing scene render at true mm scale | M7 |
| Batch DXF export (all workspaces) | One frame = 4 files; doing it one tab at a time invites mistakes | M8 |

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
7. **DXF / OMA import** — trace or reuse existing frames: import DXF outlines
   onto REF or LENS, and (stretch) the optical-industry OMA/VCA lens-shape format.
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
