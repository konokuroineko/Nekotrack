param(
    [string]$VersionOverride = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$versionSource = Join-Path $repoRoot "VERSION"
$temporaryVersionDirectory = $null
if ($VersionOverride) {
    $VersionOverride = $VersionOverride.Trim()
    if ($VersionOverride -notmatch '^\d+\.\d+\.\d+(?:-(?:dev|alpha|beta|rc)(?:\.\d+)?(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?)?

try {
    python installer\generate_icon.py
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate the NekoTrack Windows icon."
    }

    python -m PyInstaller --noconfirm --clean --onefile --windowed --name NekoTrack --icon "assets\NekoTrack.ico" --add-data "assets;assets" --add-data "$versionSource;." --add-data "installer\safe_update.ps1;installer" main.py
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
    if ($temporaryVersionDirectory -and (Test-Path -LiteralPath $temporaryVersionDirectory)) {
        Remove-Item -LiteralPath $temporaryVersionDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}
) {
        throw "VersionOverride must be a NekoTrack version such as 1.0.1-beta.1."
    }
    $temporaryVersionDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
        "NekoTrack-VersionOverride-" + [guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $temporaryVersionDirectory | Out-Null
    $versionSource = Join-Path $temporaryVersionDirectory "VERSION"
    [System.IO.File]::WriteAllText(
        $versionSource,
        $VersionOverride,
        (New-Object System.Text.UTF8Encoding($false))
    )
}
$appVersion = (Get-Content -Raw $versionSource).Trim()
if (-not $appVersion) {
    throw "The selected version is empty; cannot build NekoTrack."
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
