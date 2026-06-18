# GuildDraw release build — run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
#
# Gates on the test suite, then produces three distribution artifacts in dist\:
#   1. GuildDraw-<version>-win64.zip     portable one-folder build (unzip + run)
#   2. GuildDraw-<version>.exe           portable single-file build (no install)
#   3. GuildDraw-<version>-setup.exe     per-user Inno Setup installer
# The installer step is skipped with a warning if Inno Setup (ISCC.exe) is absent.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"

# 1. Test gate — never ship a build from a red suite
& $py -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Test suite failed - build aborted." }

# 2. Read the version stamp from the package; derive a numeric x.y.z.w for the
#    installer's VersionInfo (strips any pre-release suffix like -rc1c).
$version = & $py -c "from framedraft import __version__; print(__version__)"
$numericBase = ($version -split '-')[0]
$parts = @($numericBase -split '\.')
while ($parts.Count -lt 4) { $parts += '0' }
$numeric = ($parts[0..3]) -join '.'
Write-Host "Building GuildDraw $version (VersionInfo $numeric)" -ForegroundColor Cyan

# 3. Refresh the app icon from assets\icon.svg
& $py (Join-Path $repo "scripts\make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }

# 4. Freeze the one-folder build -> dist\GuildDraw\GuildDraw.exe
& $py -m PyInstaller framedraft.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (one-folder) failed." }

# 5. Zip the one-folder build for distribution
$zip = Join-Path $repo "dist\GuildDraw-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $repo "dist\GuildDraw") -DestinationPath $zip
Write-Host "  zip:       $zip" -ForegroundColor Green

# 6. Freeze the portable one-file build -> dist\GuildDraw.exe, then version it
& $py -m PyInstaller framedraft-onefile.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (one-file) failed." }
$portable = Join-Path $repo "dist\GuildDraw-$version.exe"
if (Test-Path $portable) { Remove-Item $portable -Force }
Move-Item (Join-Path $repo "dist\GuildDraw.exe") $portable -Force
Write-Host "  portable:  $portable" -ForegroundColor Green

# 7. Build the per-user installer with Inno Setup (skip if ISCC is missing)
$iscc = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if ($iscc) {
    & $iscc "/DMyAppVersion=$version" "/DMyAppVersionNumeric=$numeric" (Join-Path $repo "installer\GuildDraw.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed." }
    Write-Host "  installer: $(Join-Path $repo "dist\GuildDraw-$version-setup.exe")" -ForegroundColor Green
} else {
    Write-Warning "Inno Setup (ISCC.exe) not found - skipped installer. Install it with: winget install JRSoftware.InnoSetup"
}

Write-Host "Done." -ForegroundColor Green
