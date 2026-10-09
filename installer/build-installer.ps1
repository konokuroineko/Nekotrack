$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot

try {
    python installer\generate_icon.py
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate the NekoTrack Windows icon."
    }

    python -m PyInstaller --onefile --windowed --name NekoTrack --icon "assets\NekoTrack.ico" --add-data "assets;assets" main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed to build NekoTrack."
    }

    $iss = Join-Path $PSScriptRoot "NekoTrack.iss"
    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue

    if (-not $iscc) {
        Write-Host "PyInstaller build complete. Install Inno Setup, then compile installer\NekoTrack.iss."
        exit 0
    }

    & $iscc.Source $iss
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed to compile the installer."
    }
}
finally {
    Pop-Location
}
