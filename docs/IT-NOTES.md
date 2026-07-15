# GuildDraw — Notes for IT Departments and Security Reviewers

GuildDraw is an open-source 2D drafting application for handmade-eyewear
design (Python + Qt 6, packaged with PyInstaller and Inno Setup). This page
answers the questions IT and endpoint-security teams usually ask before
approving it. It summarizes a full source audit of the application code,
both build specs, the installer script, and the build pipeline — the source
is public, so every claim below can be verified directly.

## What GuildDraw does NOT do

- **No network access of any kind.** There is no networking code — no
  sockets, no HTTP, no update checks, no telemetry, no crash reporting.
  The Qt networking modules (`QtNetwork`, `QtWebEngine*`, `QtWebSockets`)
  are explicitly *excluded* from the application bundle, so the capability
  is not merely unused, it is not shipped.
- **No background processes or persistence.** GuildDraw installs no
  services, scheduled tasks, drivers, or startup (Run-key) entries. Nothing
  runs unless the user launches the app, and nothing survives closing it.
- **No shell or subprocess execution.** The app never launches other
  programs.
- **No dynamic code execution.** No `eval`/`exec`, no `pickle`/`marshal`
  deserialization of user files. Documents are plain ZIP/XML/JSON/DXF data
  parsed with size caps and a DOCTYPE/ENTITY guard against XML
  entity-expansion attacks.
- **No system-wide changes.** The installer is per-user (no admin rights,
  no HKLM). Its only registry writes are the per-user (HKCU) entries for
  the optional `.gdraw` file association, removed on uninstall.

## What GuildDraw writes to disk

- `~/.guilddraw/` (in the user's profile): preferences, autosave/crash
  recovery, the hinge/drill pattern libraries, recent-files list, and an
  `imagecache/` folder holding face photos extracted from opened `.gdraw`
  files.
- The documents and exports the user explicitly saves.
- Short-lived temporary files during save/export (standard user temp).

That is the complete list.

## Privacy

- Nothing ever leaves the machine (see "no network" above).
- Saved `.gdraw` files **embed** reference face photos rather than
  recording where they came from, so a shared design file does not reveal
  the author's user name or folder structure. (Files saved by pre-1.0
  release candidates recorded the photo's original path; resaving with a
  current version removes it.)

## Why antivirus / EDR tools sometimes flag it

Behavioral flags on GuildDraw are packaging artifacts, not malware:

1. **The portable one-file `.exe`** self-extracts its Python runtime to a
   temp folder on every launch and cleans up on exit — a pattern
   behavioral engines treat as suspicious. If your environment dislikes
   this, use the **installer** (or the portable *zip*), which runs in
   place and does not extract to temp.
2. **The binaries are unsigned.** GuildDraw is a no-budget open-source
   project without an Authenticode certificate, so SmartScreen shows
   "unknown publisher" on first run and reputation-based scoring starts
   low. This is a reputation statement, not a behavioral finding. (The
   macOS build is likewise ad-hoc signed but not notarized: Gatekeeper
   requires right-click ▸ Open on first launch.)
3. Releases are **not** UPX-compressed (a common heuristic trigger) —
   that was removed early in the release-candidate series.

For a second opinion, upload the installer or exe to
[VirusTotal](https://www.virustotal.com/) and review the per-engine
results; heuristic "ML/AI" verdicts on unsigned PyInstaller apps are the
expected noise pattern.

## Verifying for yourself

- Source: <https://github.com/csobod/GuildDraw> — the app code is in
  `framedraft/`, the bundle definition (including the excluded Qt network
  modules) in `build_common.py`, the installer in
  `installer/GuildDraw.iss`.
- Build reproducibility: `scripts/build_release.ps1` runs the test suite,
  then PyInstaller, then Inno Setup — the same path every release uses.
- Runtime check: the app holds no listening ports and makes no outbound
  connections (verify with `netstat`/Process Monitor while drawing,
  saving, and exporting).
