**GuildDraw 1.3.1** adds SVG import and closes a hidden seam in shapes brought in from other programs. **File ▸ Import ▸ SVG…** brings a logo, a mark or a colleague's drawing into the active workspace as the exact curves the file holds, at the size you choose. Files from 1.3 open as they did, and the DXF handoff to [GuildModel](https://github.com/csobod/GuildModel/releases/tag/v1.8.1) is unchanged.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker), where I will continue to post video tutorials.

## New in 1.3.1

**Import SVG**
- **File ▸ Import ▸ SVG…** reads any SVG into the active workspace. Paths come in as the cubic splines the file holds, one spline per subpath, with straight segments left straight; lines stay lines and circles stay circles. Groups labeled with a GuildDraw layer name that this workspace uses keep the layer; everything else lands on the active layer, selected, so one drag or Transform places it.
- **At the size you choose.** The import asks for a width; the height follows. A file that declares a physical size imports at that size and where the file places it, so a drawing exported at true scale comes back where it was. A file with no physical size, which is most logos, is read at 96 pixels per inch and centered on the view, ready to be sized.
- **What is skipped is reported.** Text, clones and images are counted in the status bar rather than dropped silently. Convert text to paths and expand clones in your editor first.
- **For a temple logo**, import onto the ENGRAVING layer. GuildModel 1.8.1 cuts a drawn closed shape as a filled engraving, leaves a closed curve drawn inside it standing, traces a drawn open curve as a stroke, and engraves text as stroke centerlines.

## Fixes

- **A closed shape from another program no longer carries a hidden seam.** A closed polyline that repeats its first vertex, which is how most DXF converters write one, imported with a zero-length segment, and Rebuild then fitted the hairline as a node sitting on its neighbor. The result was a spline that crossed itself at the seam, which GuildModel's engraving could not fill. DXF import folds the repeated vertex; Rebuild and SVG import merge a hairline into its neighbor.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildDraw-1.3.1-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gdraw` association; upgrades in place. |
| `GuildDraw-1.3.1-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildDraw-1.3.1.exe` | Windows single-file portable. Slower to start, and the most likely to bother your antivirus. |
| `GuildDraw-1.3.1-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildDraw-1.3.1-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

The Mac builds need **macOS 13 Ventura or later** (the Qt they are built on sets that floor); Windows builds need Windows 10 or later, 64-bit.

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once. Details for your IT department: [IT-NOTES](docs/IT-NOTES.md).

Pair it with [GuildModel 1.8.1](https://github.com/csobod/GuildModel/releases/tag/v1.8.1) to cut what you draw.

## Learning GuildDraw

The [user guide](docs/USER-GUIDE.md) covers the tools, hotkeys, printing and the GuildModel handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
