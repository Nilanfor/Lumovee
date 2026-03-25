# Lumovee – Windows build script
# Produces dist/windows/Lumovee-Setup-<version>.exe
#
# Prerequisites:
#   pip install pyinstaller
#   Inno Setup 6  https://jrsoftware.org/isdl.php  (adds iscc to PATH)
#
# Usage (from repo root):
#   .\packaging\windows\build.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Write-Host "==> Step 1/2: PyInstaller bundle"
pyinstaller `
    --distpath "$Root\dist\windows" `
    --workpath "$Root\dist\_build\windows" `
    --noconfirm `
    "$Root\packaging\windows\lumovee.spec"

Write-Host ""
Write-Host "==> Step 2/2: Inno Setup installer"
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    # Common default install location
    $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) {
        Write-Error "iscc not found. Install Inno Setup 6 and ensure it is on PATH."
    }
}
& $iscc "$Root\packaging\windows\installer.iss"

Write-Host ""
Write-Host "==> Done.  Installer written to dist\windows\"
