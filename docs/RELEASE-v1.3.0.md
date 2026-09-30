**GuildDraw 1.3** is for the maker who cuts by hand. **Print Front + Temples** lays the front and both temples out at true size on your own paper, ready to glue to the blank and saw. Engraving text is now a full part of the drawing: it copies, pastes, transforms and travels with Temple Copy. The interface now matches GuildModel's, and a full review of it fixed a long list of faults. The DXF handoff to [GuildModel](https://github.com/csobod/GuildModel/releases/tag/v1.8.0) is unchanged, and files from 1.2 open as they did.

**Two controls now turn the other way.** Transform rotates counter-clockwise for a positive angle, as the Text dialog always has; before, it turned clockwise. In Library ▸ Holes, a positive Y is now above the lens center and a positive X is toward the nose, on either lens, as in an OMA trace; before, Y ran down the screen. Hole patterns saved with 1.2 are placed as they were drawn.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker), where I will continue to post video tutorials.

## New in 1.3

**Printing for the bench**
- **Print Front + Temples.** File ▸ Print Front + Temples (and File ▸ Export ▸ PDF Front + Temples) prints the three pieces at exactly 1:1, stacked and labeled, on US Letter, Legal, Tabloid, A3, A4, A5 or Half Letter. A piece that does not fit starts a new page. Every page carries a ruler, so a scaled print is caught before you cut. Each workspace prints what it shows: its visible layers, the mirror ghost and its engraving. Requested by a maker who cuts every frame by hand.

**Engraving text**
- **Text behaves like the rest of the drawing.** Copy, Paste, Duplicate, Transform, a drag or the move gizmo take text along with the curves.
- **Temple Copy carries the engraving, readable.** The copy sits on the reflected position but is not mirror-written, so both arms read the right way up.
- **Delete works from the Layers panel.** Select rows in the tree and press Delete.

**The interface**
- **Tooltips wrap, and the ? switches them off.** A tooltip is laid out in short, even lines instead of one long ribbon. The **?** at the foot of the toolbar turns tooltips off everywhere and back on; its own tooltip always shows. Each tool's tooltip names its current hotkey.
- **Preferences, tidied.** Every tab scrolls; the window opens at the size of its content and remembers the size you leave it at. Each group has one short line of guidance, and the detail is in the tooltips. The PDF tab is now *Print & PDF*, with one group per export.
- **Checkboxes you can see.** They are drawn in the app's own colors, so an unchecked box is clear in dark mode.
- **Standard shortcuts.** Ctrl+N, Ctrl+O and Ctrl+Q; Ctrl++, Ctrl+- and Ctrl+0 zoom and fit. Preferences ▸ Hotkeys lists every fixed shortcut.
- **The window remembers its size and place.** The first launch fits the window to your screen.

## Fixes

**Your work**
- After a crash, double-clicking a file asks about the recovered work first. Before, opening the file deleted the recovery file. The offer's answers are Restore, Later and Discard; Later keeps the work for the next launch.
- Two copies of GuildDraw no longer share one recovery file.
- Saving a `.svg` while a temple or the hinge has work asks first; a `.svg` holds the Frame Front only.
- A failed Save As keeps the old file name, and a PDF or print that could not be written says so.
- Deleting one of two identical curves no longer removes the wrong one from the saved document.

**Drawing tools**
- Trim, Split, Fillet, Offset and Rebuild act on the curve nearest the click, not the one drawn last. Trim and Split cut exactly where you click.
- Undo in the middle of a tool no longer duplicates curves, and a right-click no longer acts like a left-click. Undoing Mirror (bake) turns Ghost back on.
- A double-click no longer edits a curve on a locked layer, and text can no longer be dragged without an undo step. Dragging a red node keeps it selected.
- A tool's instructions stay in the status bar; the pointer coordinates have their own place.

**Panels**
- The mouse wheel scrolls the Properties panel and Preferences instead of changing the field under the pointer.
- The Measurements update after every change, so the Refresh button is gone. Moving a lens to another layer updates them, and Frame height reads an outline joined across the mirror.
- DBL applies when you finish typing, and snapping the boxing guide no longer marks the design unsaved. Moving a reference photo does, since its place is saved.
- The Properties and Library tabs scroll, so the window fits a small laptop screen.
- Preferences OK applies only what you changed; it no longer resets Snap and the guide sizes on the Frame Front.

**Import and export**
- DXF import reads periodic splines, mirrored entities and block references.
- The 1:1 print and the templates mirror only the layers the canvas shows mirrored, and a hole pattern lands the same way on a frame drawn on either side.
- The fill sliders, select-all, box-select and snapping near dense DXF traces are fast again.

The full list is in the [README](README.md), under *New in 1.3*.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildDraw-1.3.0-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gdraw` association; upgrades in place. |
| `GuildDraw-1.3.0-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildDraw-1.3.0.exe` | Windows single-file portable. Slower to start, and the most likely to bother your antivirus. |
| `GuildDraw-1.3.0-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildDraw-1.3.0-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once. Details for your IT department: [IT-NOTES](docs/IT-NOTES.md).

Pair it with [GuildModel 1.8.0](https://github.com/csobod/GuildModel/releases/tag/v1.8.0) to cut what you draw.

## Learning GuildDraw

The [user guide](docs/USER-GUIDE.md) covers the tools, hotkeys, printing and the GuildModel handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
