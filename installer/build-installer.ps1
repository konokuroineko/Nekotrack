$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$appVersion = (Get-Content -Raw (Join-Path $repoRoot "VERSION")).Trim()
if (-not $appVersion) {
    throw "VERSION is empty; cannot build a versioned NekoTrack installer."
}
Push-Location $repoRoot

try {
    python installer\generate_icon.py
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate the NekoTrack Windows icon."
    }

    python -m PyInstaller --onefile --windowed --name NekoTrack --icon "assets\NekoTrack.ico" --add-data "assets;assets" --add-data "VERSION;." --add-data "installer\safe_update.ps1;installer" main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed to build NekoTrack."
    }

    $iss = Join-Path $PSScriptRoot "NekoTrack.iss"
    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue

    if (-not $iscc) {
        Write-Host "PyInstaller build complete. Install Inno Setup, then compile installer\NekoTrack.iss."
        exit 0
    }

    & $iscc.Source "/DMyAppVersion=$appVersion" $iss
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed to compile the installer."
    }
}
finally {
    Pop-Location
}
