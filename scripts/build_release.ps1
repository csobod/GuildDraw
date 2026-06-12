# GuildDraw release build — run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
#
# Gates on the test suite, freezes with PyInstaller (framedraft.spec), and
# zips dist\GuildDraw into a versioned archive ready to hand to testers.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"

# 1. Test gate — never ship a build from a red suite
& $py -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Test suite failed - build aborted." }

# 2. Read the version stamp from the package
$version = & $py -c "from framedraft import __version__; print(__version__)"
Write-Host "Building GuildDraw $version" -ForegroundColor Cyan

# 3. Freeze (one-folder build -> dist\GuildDraw\GuildDraw.exe)
& $py -m PyInstaller framedraft.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

# 4. Zip for distribution
$zip = Join-Path $repo "dist\GuildDraw-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $repo "dist\GuildDraw") -DestinationPath $zip
Write-Host "Done: $zip" -ForegroundColor Green
