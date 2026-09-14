$ErrorActionPreference = "Stop"

python -m PyInstaller --onefile --windowed --name NekoTrack main.py

$iss = Join-Path $PSScriptRoot "NekoTrack.iss"
$iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue

if (-not $iscc) {
    Write-Host "PyInstaller build complete. Install Inno Setup, then compile installer\NekoTrack.iss."
    exit 0
}

& $iscc.Source $iss
