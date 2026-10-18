[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,
    [string]$DataDirectory = (Join-Path $env:LOCALAPPDATA "NekoTrack-PreviewData"),
    [switch]$CopyCurrentData
)

$ErrorActionPreference = "Stop"

$ExePath = [System.IO.Path]::GetFullPath($ExePath)
$DataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
$NormalDataDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path ($env:APPDATA) "NekoTrack")
)
$comparison = [System.StringComparison]::OrdinalIgnoreCase
$normalPath = $NormalDataDirectory.TrimEnd("\")
$previewPath = $DataDirectory.TrimEnd("\")

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "NekoTrack.exe was not found: $ExePath"
}
if ($previewPath -eq $normalPath -or
    $previewPath.StartsWith($normalPath + "\", $comparison)) {
    throw "Preview data must be separate from the live %APPDATA%\NekoTrack folder."
}

if ($CopyCurrentData) {
    if (-not (Test-Path -LiteralPath $NormalDataDirectory -PathType Container)) {
        throw "The live NekoTrack data folder was not found to copy."
    }
    if (Test-Path -LiteralPath $DataDirectory -PathType Container) {
        $existing = Get-ChildItem -LiteralPath $DataDirectory -Force | Select-Object -First 1
        if ($null -ne $existing) {
            throw "Preview data already exists. Refusing to overwrite it; choose another DataDirectory or remove that preview copy yourself."
        }
    } else {
        New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    }

    foreach ($entry in Get-ChildItem -LiteralPath $NormalDataDirectory -Force) {
        Copy-Item -LiteralPath $entry.FullName -Destination $DataDirectory -Recurse
    }
}

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
$env:NEKOTRACK_DATA_DIR = $DataDirectory
Set-Location -LiteralPath $DataDirectory
& $ExePath
exit $LASTEXITCODE
