#!/usr/bin/env bash
# GuildDraw macOS release build — run from the repo root on a Mac:
#   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
#   bash scripts/build_release_macos.sh
#
# Gates on the test suite, then produces in dist/:
#   GuildDraw-<version>-macos-<arch>.zip   the .app, zipped with ditto
#   GuildDraw-<version>-macos-<arch>.dmg   the .app on a drag-to-Applications image
#
# <arch> is the machine you build on (arm64 on Apple Silicon, x86_64 on
# Intel) — PyInstaller does not cross-compile, so ship one artifact per
# architecture. The .github/workflows/macos-build.yml workflow builds both
# on GitHub's runners if building locally is inconvenient.
#
# The app is ad-hoc signed by PyInstaller (required on Apple Silicon) but
# NOT notarized — first launch needs right-click > Open (see README).
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "missing .venv — create it first (see header)"; exit 1; }

# 1. Test gate — never ship a build from a red suite. CI runs the suite as
#    its own workflow step (with per-test timeouts) and sets the skip.
if [ "${GUILDDRAW_SKIP_TESTS:-0}" != "1" ]; then
    "$PY" -m pytest tests -q
fi

# 2. Version + arch stamps
VERSION="$("$PY" -c 'from framedraft import __version__; print(__version__)')"
ARCH="$(uname -m)"
echo "Building GuildDraw $VERSION for macOS/$ARCH"

# 3. Refresh icons (writes assets/icon.icns used by the spec's BUNDLE step)
"$PY" scripts/make_icon.py

# 4. Freeze -> dist/GuildDraw.app
"$PY" -m PyInstaller framedraft.spec --clean --noconfirm

APP="dist/GuildDraw.app"
[ -d "$APP" ] || { echo "PyInstaller produced no $APP"; exit 1; }

# 5. Zip with ditto (preserves symlinks + executable bits; a plain zip of a
#    .app made elsewhere breaks the bundle)
ZIP="dist/GuildDraw-$VERSION-macos-$ARCH.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "  zip: $ZIP"

# 6. DMG (drag-to-Applications)
DMG="dist/GuildDraw-$VERSION-macos-$ARCH.dmg"
rm -f "$DMG"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "GuildDraw $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "  dmg: $DMG"

# 7. Launch smoke test (skipped in headless CI where no window server exists)
if [ "${GUILDDRAW_SKIP_SMOKE:-0}" != "1" ]; then
    "$APP/Contents/MacOS/GuildDraw" &
    SMOKE_PID=$!
    sleep 8
    if kill -0 "$SMOKE_PID" 2>/dev/null; then
        echo "  smoke test: app alive after 8s"
        kill "$SMOKE_PID"
    else
        echo "  smoke test FAILED: app exited early"; exit 1
    fi
fi

echo "Done."
