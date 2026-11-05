**GuildDraw 2.3** shows the frame after the press. A front is cut flat and then formed, which narrows the lens as seen from the front; a temple's tip is bent behind the ear. **View Formed** draws the front head-on as forming will leave it and the temple with its tip bend, a **Forming** group sets the base curve, the face form and the bridge projection and travels to [GuildModel 2.3](https://github.com/csobod/GuildModel/releases/tag/v2.3.0) as the default for its forming, the **Formed Measurements** read flat against formed with ISO's tolerance flagged, **Flatten Lens Shape** gives the flat lens that forms to a traced one, and the OMA trace describes the formed lens. The forming math is GuildModel's own, ported and held to it by a test, so the two apps show the same formed front. It also carries the bug hunt of 2.0.0, which never shipped on its own: the Text dialog's font box types again, an offset of a spline with sharp corners comes out clean, the readiness dot no longer shows green for a front GuildModel cannot build as drawn, dropping a file on the drawing opens it, and large imports, exploded outlines and dense traces stay responsive. One fix reaches work already sent out: the drill holes of an OMA trace were written from the wrong origin, so a trace with drill holes that went to a lab from GuildDraw should be exported again. Designs open and save as they did in 2.0; a 2.3 design opens in 2.0, which does not read or keep the forming and the bends.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker), where I will continue to post video tutorials.

## New in 2.3

**View Formed** (toolbar, View menu, hotkey `W`, or the checkbox at the top of the Forming group; front and temples)
- **The front after the press.** Every curve head-on after forming, drawn over the flat drawing, which shows faintly beneath; a *formed* chip joins the face word in the canvas corner. A flat front with no forming set looks as drawn, and the status bar says so.
- **The temple with its tip bend,** engraving text included.
- **A view only.** Every tool works on the flat drawing; the file and every export keep it, but for the PNG, which is the canvas as seen, and the OMA trace. Each tab keeps its own setting; a design you open or start begins flat.

**Forming** (Guides tab, Frame Front)
- **Show forming preview** is the same switch as View Formed on the toolbar, and the toolbar button lights while it is on.
- **A preset** sets the base curve, the die's own radius and the face form together, as the press does; the SBT presets are built in. Change either value and the preset reads *Custom*.
- **Base curve** in diopters, in quarter steps, 0 flat, with the radius in use read below it. **Face form** in degrees per side: each lens plane's angle to the plane of the front, measured from the center of the bridge, 0° flat. **Bridge projection**.
- **Flatten Lens Shape** replaces the drawn lenses with the flat shapes that form back to them: after the press each measures in its own plane what it measured flat before, within 0.015 mm all along the lens. Your nodes stay; a node is added where a span needs one, and a circle or a polygon lens becomes a spline. A box says what it will do first. The selected lenses, or both; Ctrl+Z takes it back.
- **Saved with the design** under names GuildModel reads, so a design carries its forming to GuildModel 2.3.
- The old *Construction (Forming)* group is **Nose Fit** now: those were always the customer's nose measurements.

**Forming in Preferences** (General tab)
- **Tooling index**, 1.53 by default: the historical standard, which makes the radius 530 / D. **Sheet thickness**, and the **neutral surface**: the layer of the sheet that keeps its length in the press, from the front face (GuildModel's assumption) to mid-thickness (the textbook's); nobody has measured it, and one pressed test front would.
- **Every design uses them.** They describe the shop's press and sheet, so they apply to designs already saved; saving a design writes them into it for GuildModel.

**Formed Measurements** (Properties tab, Frame Front)
- Each lens's A head-on, in the lens plane (where ISO 8624 measures and a drawing carries it) and flat, as cut; its B in the lens plane; DBL, the boxed-center distance and the frame width head-on; the circumference in the lens plane and in 3D (labs size by the 3D groove length); the edge sag; each lens plane's tilt; the frame curve; how far the endpieces sit behind the bridge. Measured on the finished lens at the groove line.
- **Flagged in red** when a lens's A in the lens plane is more than ISO's ±0.5 mm off its flat A, when a lens reaches into the bridge band, or when the sheet is thicker than the bend can carry.

**Forming on a temple** (Guides tab, Temple R and L)
- **Show temple tip bend** is the same switch as View Formed on the toolbar.
- **Length to bend** from the hinge end of the outline to the ear point, *auto* leaving 37 mm of drop; **downward angle**, 0 a straight library temple; **bend radius** at the core, which keeps its length through the bend. Readouts: the drop, the overall length straightened (the marking's number), the reach and the tip's drop. A bend that does not fit reads *out of range*, as the Offset tool does.
- **Each temple bends toward its own drop,** Temple L toward the top of the canvas, where its drop is drawn; **Temple Copy** takes the tip bend with the temple, so the pair bends alike.

**The OMA trace of a formed front**
- The radii, HBOX and VBOX in each lens's own plane, DBL head-on, the holes with their lens, and `FCRV`, `ZTILT` and `CIRC`, as a 3D tracer writes them. A flat front exports as it always did.

**A bug hunt and an interface review of the whole app** (five reviews; each fix held by a test)
- **Files.** A design whose archive lacked a tab it named opened as if whole and the next Save wrote an empty tab over it; it now opens with an error and without its file name, so a Save cannot write over it. The OMA export no longer leaves a cut-short file over a good one when the write fails. A trace with `1_000` or non-Latin digits in a radius is refused.
- **The window.** Group (Ctrl+G) takes whole groups, so a placed hinge's hidden guide line stays with it. Space and Shift+Tab cannot be assigned as hotkeys (Space pans). If W is already one of your hotkeys it stays yours, and View Formed has no key until you give it one in Preferences. The apical radius typed at 2 mm over a design that had none is saved. A turn of 360° adds no step. Preferences opens over a hand-edited preferences file with a damaged theme block.
- **The canvas.** A click picks the curve nearest the cursor, not the later-drawn one beside it, and a click well beside a lone curve at high zoom picks nothing; Trim, Split, Fillet, Offset and Rebuild follow the same rule, where they acted on a click 60 pixels beside a line. A double-click to finish a line keeps its last node: it was dropped when it sat within 12 pixels of the node before, a last millimeter at working zoom. Offset refuses a distance past ten meters, as every typed length is. Rebuild refuses a fit that keeps fewer nodes than a curve needs.
- **The dock.** Tooltips on the Nose Fit, Boxing System and Bevel fields, the fill color buttons, the hole diameter, and the library's and bookmarks' buttons; the Nose Fit fields take a typed value on Enter or leaving the field.

## Fixes since 2.0.0

**OMA drill holes** (a fault older than 2.0; if a trace with drill holes went to a lab from GuildDraw, export it again)
- **Drill holes are written as the lab standard defines them.** The standard (DCS 3.14, 5.5.2) places each `DRILLE` hole from the box center of its own lens, and reads a hole marked `B` as the right lens's, to be mirrored for the left. GuildDraw wrote every hole from the midpoint between the two lenses and marked it `B`, which an edger would have drilled a lens-width off. The export now writes one record for each hole, on its own eye, from its own lens's box center; of a formed front, in that lens's plane.
- **A mount's file imports with its holes in the lenses.** A rimless mount's own trace came in with its holes heaped at the two lens centers. `R`, `L` and `B` records are placed as the standard says. Holes measured from the lens edge or box, and slots, are not read as such; the status bar counts them, where they were placed wrongly without a word. The standard's shortest record, and a hole with no diameter given, are read.
- **A trace GuildDraw wrote before 2.3 still opens as it was drawn.** It is recognized by where its holes fall and read the old way; the status bar says so.
- **A trace that states no DBL takes the boxing guide's.** A rimless pattern file writes `DBL=0`, and the lenses came in touching.

**Typing and the panel**
- **The font box types again.** In the Text dialog, typing a font name filters the list as you go. In 2.0.0 the first letter jumped to the first font starting with it, and nothing typed after it landed.
- **Boxing A, B and DBL are kept.** Values typed before *Snap to lens shape* came back as the old ones when you unticked it, and a save while snapped wrote the old ones.
- **A value typed and not yet entered is kept.** The panel's number fields take a value on Enter or on leaving the field, and Ctrl+S, a click on a workspace tab or a toolbar button, and closing the window did not count as leaving: an A, B, DBL or line weight typed just before was left out of the saved file, dropped at the tab switch, or lost at close without a prompt. The field is now entered before a shortcut runs, on a click anywhere outside it, and before a save.
- **A click through the Scale field keeps a 2-point calibration.** Clicking into the field and away replaced the exact calibration with its rounded display.
- **Ctrl+G, Ctrl+Shift+G and Ctrl+Y stay out of text fields.** Typing in a panel field could group the selection, or on Mac and Linux redo a drawing step.
- **Unlinking a lens tint gives back this design's bottom color,** never the last design's. A stock or pad size changed in Preferences no longer marks an empty design unsaved, and the Line weight box follows the tab you switch to.

**The drawing**
- **Drop a file on the drawing to open it.** In 2.0.0 the drawing refused the drop; only the toolbar and status bar took it.
- **Clicks reach the curve you aim at.** Zoomed out, a second click beside a selected curve no longer deselects it. A locked curve lying on top no longer takes the click meant for the curve beside it.
- **An open end beside the origin snaps to the end.** The origin used to win over a nearer end, which left a gap in the outline.
- **Switching tools in the middle of a drag** no longer leaves editable nodes on a curve that is no longer selected.

**The tools**
- **A double-click trims once.** With Trim it trimmed the piece beside the stub too. With the start-end-center arc, a double-click on the end no longer commits a half circle.
- **Fillet works on open lines only.** It opened a closed polyline and dropped one of its sides.
- **Placed components stay whole.** Rebuild picked inside the tool and Explode now refuse a grouped curve, as Trim, Split and Fillet do, and Mirror Close keeps the group. A refused Trim, Split or Fillet now says so instead of reporting success.
- **No zero-length segments.** The Line tool no longer places a node on top of the last one, from a typed length of 0 or from a second click on the same spot. Deleting a node of a closed triangle is refused rather than leaving a shape with no area.
- **Offset gives clean corners.** An offset of a spline with sharp corners crossed itself at each inside corner: every shipped hinge pocket inward, and most outlines. The two pieces at a corner are now trimmed where they cross, and the readiness dot stays green. Offsetting a large outline is also about ten times faster, so the preview keeps up as you type.
- **A distance too large for the curve no longer freezes GuildDraw.** An offset far past the curve's bends, such as −10 mm on an open outline, could leave the window not responding for minutes. Now the distance reads *out of range* in red, the status bar says why (nothing of the shape would be left, or the offset folds over itself too often to untangle), and Enter adds nothing. The preview waits for a pause in your typing, so a long number costs one offset rather than one for each key. On a dense curve (a trace, a scan) the message suggests Rebuild first.
- **Trim, Split and the Intersection snap find every meeting.** A line that ended on a curve from outside, as the snaps place a connector, was not seen, and a shallow crossing was cut up to 2 mm off. Cuts now land exactly where the curves meet. A line lying along another no longer leaves slivers, and Trim on an exact copy says to delete one instead. Short lines and tiny circles can be cut, and a click on a dense trace takes milliseconds rather than seconds.
- **Rebuild waits for a pause in your typing** and caps the node count at four times the curve's own (at least 64): typing 100000 fitted 17,000 nodes and took seconds a key. The readout says when the cap applies.
- **Fillet with a radius equal to a leg** no longer leaves a zero-length line behind; the arc meets the far end. Two legs all but in line are refused instead of saving a full circle, and arcs draw as the file stores them.
- **Typed lengths past ten meters are refused.** A move of 1e300 was taken, and Fit then did nothing. A typed length takes plain digits only: a `²`, a plain key on some keyboards, went into the number and Enter then ended the line.
- **An offset of a polyline grows it, whatever the distance.** Past half the shape's size, a closed polyline drawn one way round came back turned inside out: a 3.5 by 2 mm slot offset by 3 mm returned 2.5 by 4. An inward offset past a narrow part, such as a lug, drops the part instead of turning it inside out; one that would cut the shape in two reads *out of range*.
- **Split splits once, where you click.** A double-click split one of the two pieces again. Zoomed in, a click nowhere near a crossing was pulled to it from 1.5 mm away (120 pixels at high zoom) and split the crossing curve too; the pull is now 12 pixels on screen.
- **Join leaves a V open.** Two lines meeting at a point, their free ends within 2 mm, were closed by folding one leg onto the other.

**Large drawings and imports**
- **The readiness dot keeps up with any drawing.** After an outline was exploded and a piece deleted, or after a few hundred curves were imported onto the outline layer, every later edit froze the window for seconds to minutes. The check now does the same work in a fraction of a second; its findings are unchanged.
- **Imports select their curves at once.** A DXF of 20,000 lines took nearly three minutes to select after it was read.
- **Dense curves are quick to edit and snap to.** Dragging a node, inserting one, and snapping near a curve of thousands of nodes no longer slows the window.
- **The stock width and height fields** take the value when you press Enter or leave the field, as the boxing fields do.
- **The Ghost and the Frame Fill keep up with a large outline.** With both on, an outline of thousands of pieces took many seconds to reopen and as long after each edit (21 seconds at 20,000 pieces); it takes a quarter of a second.

**Files**
- **Each reference photo keeps its own scale on reopen.** A photo you never calibrated was resized to another photo's calibration every time the design opened.
- **Save As keeps every stored photo.** It took missing photos from the file being replaced, so it could pick up another design's photo or drop one of yours.
- **An SVG exported from a temple or the Component tab opens back into that tab.** In 2.0.0 it opened into the Frame Front, and Save wrote it back as a front. It now opens without a file name, so Save asks for one.
- **Photos and swatches beside a design at the top of a drive** (a USB stick, a shared folder) are found.
- **Catalog PDFs for a Folder** starts with *Save the fill into the files* off. A file from Inkscape with a layer named "curves" is imported rather than failing to open.
- **A design's apical radius is saved as the file had it** unless you change it. A file without one was saved with the field's 2 mm minimum.
- **Mirror Close is back on the toolbar** for anyone upgrading from 1.3, whose preferences had it hidden by default.
- **A fill image that did not travel with the design is kept.** On a computer without the Frame Fill or Inlay Fill image, the fill shows its color, and a save there no longer changes the design's style to Color. Choose the image again, or clear it to keep the color.
- **Reference images keep their order** when the design is saved on a computer that lacks one of them. The missing image moved to the top of the stack.
- **A design with many bookmarks opens again.** Each bookmark stores the whole drawing, so a dense design with a few of them saved a tab GuildDraw then refused to open, and the front came back empty. Such tabs open now, and a save warns if a tab grows past what GuildDraw can open.
- **OMA traces import in far fewer nodes.** Tried on 412 frames traced in a practice, a lens came in with 72 to 256 nodes; it now comes in with about 35, still within 0.02 mm of every traced point, and its bevel shrink takes a third of the time. A trace with tracer noise came in with one node per traced point, and its bevel shrink was refused after many seconds; it is now smoothed first. If one lens cannot be shrunk, the other still is.
- **The OMA import's bevel question no longer assumes a groove.** An eyewire's bevel, a demo lens and a drill-mount shape each trace differently, and only you know which a file holds and what the shape is for. The dialog now names what the file declares, such as *a pattern trace (P) of a rimless frame*, and the choice stays yours. Its button reads **Shrink by the Bevel Depth**.
- **An OMA file with a byte-order mark, or padded at its end, imports.** An editor's mark before the first record, or a DOS-era host's Ctrl-Z or NUL padding after the last, refused the whole file. `TRCFMT=0`, the standard's "no trace available", now says there is no trace instead of asking for another format.
- **A fill image named in a `.gdraw` and not found keeps its name,** as it did in an `.svg` design; the next save wrote the style as Color.
- **Catalog PDFs for a Folder leaves a read-only design alone** and keeps a design's file permissions; File ▸ Save already refused the first.
- **DXF units no longer change a lens.** A file drawn in inches, centimeters or meters imported up to 0.6 mm off, and a near-circle in meters became a circle; it now comes in as close as a millimeter file. A drawing whose size is not plausible for eyewear (3 to 300 mm) gets a note, whatever units it states. Arrays of blocks (MINSERT) import every copy, and a file of deeply nested blocks stops with a note instead of running on.
- **Densely sampled SVG outlines import.** One sampled finer than 0.01 mm imported as nothing, with a message blaming the file. An SVG whose width and height disagree with its viewBox imports at the size a browser draws it, imports stop at 20,000 curves with a note, and deeply nested groups no longer fail.

**Printing**
- **Print at 1:1 and Export PDF (Current View, 1:1) follow View Obverse,** as PNG export does: mirrored, as the canvas shows the other face, and the status bar names the face. The ruler reads normally. Template prints and catalog PDFs keep the drawn face.

**The readiness dot**
- **Two fronts that GuildModel cannot build as drawn no longer read green:** a rim drawn without its lens beside one that has it, on either side, and two lenses drawn on the same eye.
- **A rim drawn as an open curve with its ends touching** gets the same Ghost check as a closed one.
- **The dot no longer asks you to bake a twin the canvas does not show.**

**Measuring and geometry**
- **Polygon lenses measure to their corners.** A and B read up to 0.2 mm short, and Resize scaled by the wrong amount.
- **Split at a node** no longer leaves a hidden second node there. **Offsetting a polyline** with a repeated node moves every corner.
- **A lens with a loop at a node measures its whole width.** One with a handle dragged through its node read A 10 mm short, and Resize then made it too large.
- **A locked lens is not resized to nothing.** Typing 0, or leaving the field after a partial number, shrank the lenses to half a millimeter with the readiness dot green. A and B now take 10 to 120 mm, and B reads past 100 mm.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildDraw-2.3.0-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gdraw` association; upgrades in place. |
| `GuildDraw-2.3.0-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildDraw-2.3.0.exe` | Windows single-file portable. Slower to start, and the most likely to bother your antivirus. |
| `GuildDraw-2.3.0-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildDraw-2.3.0-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

The Mac builds need **macOS 13 Ventura or later** (the Qt they are built on sets that floor); Windows builds need Windows 10 or later, 64-bit.

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once. Details for your IT department: [IT-NOTES](docs/IT-NOTES.md).

Pair it with [GuildModel 2.3](https://github.com/csobod/GuildModel/releases/tag/v2.3.0) to cut what you draw and to draw the frame after forming.

## Learning GuildDraw

The [user guide](docs/USER-GUIDE.md) covers the tools, hotkeys, printing and the GuildModel handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
