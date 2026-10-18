**GuildDraw 2.0** is the drawing side of the leap with [GuildModel 2.0](https://github.com/csobod/GuildModel/releases/tag/v2.0.0). A new **INLAY** layer draws seats for plaques, laminates, plates and stones; **combination frames** put two acetate rims on a metal bridge; the HINGE layer becomes **COMPONENT**, with a component library you arrange in folders. **View Obverse** shows the drawing from its other face, and **Inlay Fill** previews the stone or color in each seat. Reference images are now yours to keep or to share: a photo stays on your computer unless you store it in the design. A long review of the interface fixed about 190 faults along the way.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker), where I will continue to post video tutorials.

## Before you upgrade

- **Use GuildModel 2.0 with GuildDraw 2.0.** GuildModel 1.8.1 skips COMPONENT curves without a word, so a 2.0 drawing or DXF loses its hinge and bridge pockets there.
- **A 2.0 design does not open whole in GuildDraw 1.3.** A tab holding a COMPONENT or an INLAY curve fails to load in 1.3.x, and that is nearly every 2.0 design. A 2.0 file saved from 1.3.1 also loses the Component tab's drawing. Designs from 1.3 open in 2.0 as they did; their HINGE curves read as COMPONENT.
- **The Ghost is never exported.** GuildModel reads the curves you drew, never the mirror ghost, so the DXF now carries exactly the curves drawn, as the `.gdraw` always has. A front drawn as a half needs its twins baked (Mirror) before it is cut; the readiness dot names every curve that has no drawn twin, with the fix.
- **A new reference image is not stored in the design.** The file keeps the image's place and an id, and your computer remembers which photo that is. Click the paperclip on the Canvas tab to store an image, so it shows on any computer that opens the file. Designs from before 2.0 stored every image, and open with each one stored.
- **A few values now read the other way.** The pointer readout and Point Move count y upward, as the DXF does. The Line tool's angle is counter-clockwise and takes a minus sign. The construction guide's crest height is positive above the datum line, the optical convention; no file saved it before, so no design changes.

## New in 2.0

**Inlays**
- **The INLAY layer**, on the front and both temples, draws a seat for a plaque, a laminate or a plate as a closed curve; a curve inside it is a step. The drawing carries the shape only; GuildModel 2.0 holds each seat's depth, face and floor, and cuts it. A seat must meet the part, and where it runs off an edge it is a step open there; a seat crossing a lens, a drill hole or a component pocket is refused, as are two seats that overlap without nesting.
- **Inlay Fill** (Guides panel, under Frame Fill) paints each seat in a color or an image: a turquoise photo, say, cropped to cover each body. With several bodies, *Tumble bodies* turns each copy differently, so one photo reads as several stones, the same way every time the file opens. It is a preview only: saved with the design, printed on the catalog page when you ask, never machined.

**Combination frames**
- **Separated rims.** Two acetate rims on a metal bridge are drawn as two real outlines, each holding its lens; GuildModel 2.0 builds one front with a body per rim from the same blank. A rim drawn in pieces that meet end to end is one error, with the fix: Join them. The bridge's mount is one shape across the gap, on COMPONENT when it mounts from behind and on INLAY when it mounts from the front. The user guide has a *Combination frames* section.

**Components**
- **HINGE becomes COMPONENT**, for everything that mounts on the posterior: hinges, bridges, endpieces and bridge bars. Every drawing, library entry and DXF that says HINGE still reads.
- **A component library in folders.** The Library tab is a tree of folders you create, rename, reorder by dragging and delete; Hinges (the shipped set) and Bridges start you off, and your own hinges move into Hinges. A component placed from a folder carries the folder's name, ready for a later GuildModel to tell a hinge from a mount.

**Seeing the other face**
- **View Obverse** (`V`, View menu and toolbar) mirrors the whole tab left to right: a front's posterior, a temple's anterior. It is a view only; the document and every export are unchanged. A quiet label in the corner names the face you are looking at, and PNG export follows the view.

**Reference images**
- **Rows like the Layers panel.** The Canvas tab lists each image with an **eye** (a hidden image is left out of PNG export and printing), a **padlock** (its place, turn and scale) and a **paperclip** (stored in the design). A new image starts unlocked, to be placed, turned and calibrated; lock it once it is set.
- **Stored only when you choose.** Not stored, an image stays where it is on your computer, and the design holds no part of it, its name or where it is: a patient's photo does not leave your computer in a design you send. On another computer the image is listed as *not on this computer*, and **Locate…** brings it back at its place and scale.
- **Each image keeps its own calibration**, so a front photo and a side photo taken at different distances both read true.
- **Preferences ▸ General ▸ Clear Image Cache…** deletes the copies GuildDraw unpacks from designs that store their images; each design unpacks them again when it is opened.

**The handoff to GuildModel**
- **The origin, shown and checked.** Both temple tabs draw the core line across the blank, where the wire runs. The readiness dot warns about a temple drawn off the core line and about an outline that leaves the blank, with the overrun in millimeters.
- **The blank travels with the design.** The `.gdraw` carries each tab's stock guide and the front's pad block, so GuildModel 2.0 starts a new project's blank from the drawing. The temple blank is a preference of its own, 170 × 30 mm by default, as GuildModel's. The construction guide's crest and angle values and the free boxing A, B and DBL are saved with the design too.
- **Each layer says what it becomes.** The Layers panel's tooltips say what GuildModel makes of each layer, ENGRAVING spelled out: a closed curve is a filled shape, a curve inside it an island, an open curve a stroke, and text its centerlines.
- **The readiness dot checks what GuildModel will read**: two lenses or one, each held whole by its outline; no curve that crosses itself, encloses nothing or lies on another.

**The catalog**
- **File ▸ Export ▸ Catalog PDFs for a Folder…** turns every design in a folder into a catalog page in one run, setting the Frame Fill (and the Inlay Fill, if you ask) on the way, with a backup of each design it saves and a verdict per file.

**The interface**
- **The Properties panel folds** like GuildModel's, section by section, and remembers what you folded.
- **More of the app in the menus.** Help ▸ About GuildDraw; Edit ▸ Delete, Edit ▸ Move Gizmo and Edit ▸ Modify, with every operation, a hidden toolbar button's too; and a View toggle for every switch, each with its key. The unsaved-changes question names the design and what you were doing.
- **The canvas.** Pan with the right mouse button or Space; Fit frames the drawing and its blank; a tab says what to draw first while it is empty; the zoom reads in pixels per millimeter, as GuildModel's; a comma works as a decimal point.
- **Preferences** gain *Prompts*, where a question you silenced with *Don't ask again* is turned back on, and ask before changing a drawn design's guide sizes.

## Fixes

**Your work**
- A save goes through a link to the file it names, keeps the file's permissions, leaves a read-only file alone, and asks when another program changed the file since you opened it. An unchanged design saves to the same bytes.
- A curve, dimension or text that does not read is left out and named, and the rest of the tab opens; Save then asks for a new name, so the original is never overwritten. A recovery file that reads only in part is kept whole.
- The photo calibration, the Ghost and the guide sizes no longer carry from one design into the next.

**Drawing tools**
- Join leaves closed curves and circles alone, and wants one layer. Trim, Split, Fillet and Rebuild leave a group alone; a group survives Join, Close and Offset.
- Node and handle drags wait for 4 pixels of movement, so a click no longer nudges a node. A smooth handle's sibling keeps its length.
- Mirror (bake) skips a twin that would lie on a curve already drawn.

**Import and export**
- DXF import reads splines exactly up to degree 3 and fits the rest within 0.01 mm, reads a NURBS circle as a circle, takes units when they are plausible, and leaves out layers that are off or frozen.
- SVG import reads nested viewBoxes and classes hidden by CSS, and Illustrator files at 72 to the inch.
- Exports start beside the design with its name, refuse an empty tab, and Export Every Tab asks before replacing files. PNG files record their resolution and leave the selection out.

**Speed**
- The fills and the readiness check are fast on long outlines: a 1500-node outline's frame fill went from 1.9 s to 7 ms, a half outline with the Ghost from 5.3 s to 24 ms.

The full list is in the [README](README.md), under *New in 2.0*.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildDraw-2.0.0-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gdraw` association; upgrades in place. |
| `GuildDraw-2.0.0-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildDraw-2.0.0.exe` | Windows single-file portable. Slower to start, and the most likely to bother your antivirus. |
| `GuildDraw-2.0.0-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildDraw-2.0.0-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

The Mac builds need **macOS 13 Ventura or later** (the Qt they are built on sets that floor); Windows builds need Windows 10 or later, 64-bit.

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once. Details for your IT department: [IT-NOTES](docs/IT-NOTES.md).

Pair it with [GuildModel 2.0](https://github.com/csobod/GuildModel/releases/tag/v2.0.0) to cut what you draw.

## Learning GuildDraw

The [user guide](docs/USER-GUIDE.md) covers the tools, hotkeys, printing and the GuildModel handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
