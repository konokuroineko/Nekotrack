param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("UpdatePortable", "InstallSetup", "RollbackOnly", "RollbackLatest")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$InstallDirectory,
    [Parameter(Mandatory = $true)]
    [string]$DataDirectory,
    [string]$BackupDirectory = "",
    [int]$WaitForPid = 0,
    [string]$ExpectedVersion = "",
    [string]$StagedExecutable = "",
    [string]$InstallerPath = "",
    [string]$AttemptId = "",
    [switch]$RestoreDatabase
)

$ErrorActionPreference = "Stop"
$InstallDirectory = [System.IO.Path]::GetFullPath($InstallDirectory)
$DataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
$ExecutablePath = Join-Path $InstallDirectory "NekoTrack.exe"
$BackupRoot = Join-Path $DataDirectory "update_backups"

function Show-UpdateError([string]$Message) {
    try {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            $Message, "NekoTrack updater",
            [System.Windows.MessageBoxButton]::OK,
            [System.Windows.MessageBoxImage]::Warning
        ) | Out-Null
    } catch {
        Write-Error $Message
    }
}

function Test-WindowsPE([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $stream = $null
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        if ($stream.Length -lt 68) { return $false }
        $reader = New-Object System.IO.BinaryReader($stream)
        $dos = $reader.ReadBytes(64)
        if ($dos.Length -lt 64 -or $dos[0] -ne 0x4D -or $dos[1] -ne 0x5A) { return $false }
        $offset = [BitConverter]::ToInt32($dos, 0x3C)
        if ($offset -lt 64 -or $offset -gt ($stream.Length - 4)) { return $false }
        $stream.Position = $offset
        $signature = $reader.ReadBytes(4)
        return ($signature.Length -eq 4 -and $signature[0] -eq 0x50 -and
            $signature[1] -eq 0x45 -and $signature[2] -eq 0 -and $signature[3] -eq 0)
    } catch {
        return $false
    } finally {
        if ($stream) { $stream.Dispose() }
    }
}

function Wait-ForPreviousProcess([int]$ProcessId) {
    if ($ProcessId -le 0 -or $ProcessId -eq $PID) { return }
    try { $process = [System.Diagnostics.Process]::GetProcessById($ProcessId) } catch { return }
    if (-not $process.WaitForExit(90000)) {
        throw "NekoTrack did not close in time. No application files were replaced."
    }
}

function Find-LatestBackup {
    if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) { return $null }
    $valid = @()
    foreach ($folder in Get-ChildItem -LiteralPath $BackupRoot -Directory -ErrorAction SilentlyContinue) {
        $backupExe = Join-Path $folder.FullName "NekoTrack.exe"
        $manifest = Join-Path $folder.FullName "manifest.json"
        if (-not (Test-WindowsPE $backupExe) -or -not (Test-Path -LiteralPath $manifest)) { continue }
        try {
            $metadata = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
            $stamp = [string]$metadata.created_at
            if (-not $stamp) { $stamp = $folder.Name }
            $valid += [PSCustomObject]@{ Path = $folder.FullName; Stamp = $stamp }
        } catch { continue }
    }
    $latest = $valid | Sort-Object Stamp -Descending | Select-Object -First 1
    if ($latest) { return $latest.Path }
    return $null
}

function Set-ExecutableFromBackup([string]$Folder) {
    $backupExe = Join-Path $Folder "NekoTrack.exe"
    if (-not (Test-WindowsPE $backupExe)) { throw "The previous application backup is missing or invalid." }
    $temporary = Join-Path $InstallDirectory ("NekoTrack.rollback-" + [guid]::NewGuid().ToString("N") + ".exe")
    Copy-Item -LiteralPath $backupExe -Destination $temporary
    if (-not (Test-WindowsPE $temporary)) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw "The previous application copy failed validation. The installed app was not changed."
    }
    $existing = Join-Path $InstallDirectory ("NekoTrack.failed-" + [guid]::NewGuid().ToString("N") + ".exe")
    try {
        if (Test-Path -LiteralPath $ExecutablePath) { Move-Item -LiteralPath $ExecutablePath -Destination $existing }
        Move-Item -LiteralPath $temporary -Destination $ExecutablePath
    } catch {
        if (-not (Test-Path -LiteralPath $ExecutablePath) -and (Test-Path -LiteralPath $existing)) {
            Move-Item -LiteralPath $existing -Destination $ExecutablePath
        }
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Restore-DatabaseSnapshot([string]$Folder) {
    $databaseBackup = Join-Path $Folder "anime_tracker.db"
    $databaseTarget = Join-Path $DataDirectory "anime_tracker.db"
    if (-not (Test-Path -LiteralPath $databaseBackup -PathType Leaf)) {
        throw "The requested database snapshot is missing."
    }
    # Automatic restore occurs only before the health marker, before the user
    # can interact with the updated app.
    $rollbackId = [guid]::NewGuid().ToString("N")
    $temporary = Join-Path $DataDirectory ("anime_tracker.rollback-" + $rollbackId + ".db")
    Copy-Item -LiteralPath $databaseBackup -Destination $temporary
    if (Test-Path -LiteralPath $databaseTarget) {
        $databaseFailed = Join-Path $DataDirectory ("anime_tracker.failed-" + $rollbackId + ".db")
        Move-Item -LiteralPath $databaseTarget -Destination $databaseFailed
    }
    # Preserve SQLite WAL/SHM sidecars with the failed database instead of
    # letting them interfere with the restored snapshot or deleting them.
    foreach ($suffix in @("-wal", "-shm")) {
        $sidecar = $databaseTarget + $suffix
        if (Test-Path -LiteralPath $sidecar) {
            Move-Item -LiteralPath $sidecar -Destination ($DataDirectory + "\anime_tracker.failed-" + $rollbackId + ".db" + $suffix)
        }
    }
    Move-Item -LiteralPath $temporary -Destination $databaseTarget
}

function Start-CandidateAndWaitForHealth([string]$HealthVersion, [string]$Id) {
    $healthFile = Join-Path $DataDirectory ("update-health-" + $Id + ".txt")
    Remove-Item -LiteralPath $healthFile -Force -ErrorAction SilentlyContinue
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $ExecutablePath
    $startInfo.WorkingDirectory = $InstallDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.EnvironmentVariables["NEKOTRACK_UPDATE_HEALTH_FILE"] = $healthFile
    $child = [System.Diagnostics.Process]::Start($startInfo)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 60) {
        Start-Sleep -Milliseconds 350
        if (Test-Path -LiteralPath $healthFile -PathType Leaf) {
            $reportedVersion = (Get-Content -LiteralPath $healthFile -Raw -ErrorAction SilentlyContinue).Trim()
            if ($reportedVersion -eq $HealthVersion) {
                Remove-Item -LiteralPath $healthFile -Force -ErrorAction SilentlyContinue
                return $true
            }
        }
        try { $child.Refresh(); if ($child.HasExited) { break } } catch { break }
    }
    try { $child.Refresh(); if (-not $child.HasExited) { $child.Kill() } } catch {}
    Remove-Item -LiteralPath $healthFile -Force -ErrorAction SilentlyContinue
    return $false
}

function Start-RestoredApplication {
    if (Test-WindowsPE $ExecutablePath) {
        Start-Process -FilePath $ExecutablePath -WorkingDirectory $InstallDirectory
    }
}

try {
    Wait-ForPreviousProcess $WaitForPid
    if ($Action -eq "RollbackLatest") { $BackupDirectory = Find-LatestBackup }

    if ($Action -eq "RollbackOnly" -or $Action -eq "RollbackLatest") {
        if (-not $BackupDirectory) { throw "No valid previous NekoTrack version backup was found." }
        Set-ExecutableFromBackup $BackupDirectory
        Start-RestoredApplication
        exit 0
    }

    if (-not (Test-Path -LiteralPath $BackupDirectory -PathType Container)) {
        throw "The verified pre-update backup folder could not be found."
    }

    if ($Action -eq "UpdatePortable") {
        if (-not (Test-WindowsPE $StagedExecutable)) {
            throw "The staged update executable is invalid. The installed version was not changed."
        }
        $temporary = Join-Path $InstallDirectory ("NekoTrack.staged-" + [guid]::NewGuid().ToString("N") + ".exe")
        Copy-Item -LiteralPath $StagedExecutable -Destination $temporary
        if (-not (Test-WindowsPE $temporary)) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            throw "The staged executable copy failed validation."
        }
        $oldCopy = Join-Path $InstallDirectory ("NekoTrack.before-" + [guid]::NewGuid().ToString("N") + ".exe")
        try {
            if (Test-Path -LiteralPath $ExecutablePath) { Move-Item -LiteralPath $ExecutablePath -Destination $oldCopy }
            Move-Item -LiteralPath $temporary -Destination $ExecutablePath
        } catch {
            if (-not (Test-Path -LiteralPath $ExecutablePath) -and (Test-Path -LiteralPath $oldCopy)) {
                Move-Item -LiteralPath $oldCopy -Destination $ExecutablePath
            }
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            throw
        }
    } elseif ($Action -eq "InstallSetup") {
        try {
            $stagingRoot = [System.IO.Path]::GetFullPath((Join-Path $DataDirectory "update_staging"))
            $providedInstaller = [System.IO.Path]::GetFullPath($InstallerPath)
            if (-not (Test-WindowsPE $providedInstaller) -or
                -not $providedInstaller.StartsWith($stagingRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "The downloaded Setup package failed path or executable validation."
            }
            $setup = Start-Process -FilePath $providedInstaller -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
            if ($setup.ExitCode -ne 0) { throw "NekoTrack Setup returned exit code $($setup.ExitCode)." }
            if (-not (Test-WindowsPE $ExecutablePath)) { throw "Setup completed but the installed executable was not found." }
        } catch {
            $setupFailure = $_.Exception.Message
            try {
                Set-ExecutableFromBackup $BackupDirectory
                Start-RestoredApplication
                $setupFailure += " The previous executable was restored from backup."
            } catch {
                $setupFailure += " Automatic executable recovery also failed: " + $_.Exception.Message
            }
            throw $setupFailure
        }

    if (-not (Start-CandidateAndWaitForHealth $ExpectedVersion $AttemptId)) {
        Set-ExecutableFromBackup $BackupDirectory
        if ($RestoreDatabase) { Restore-DatabaseSnapshot $BackupDirectory }
        Start-RestoredApplication
        throw "The updated app failed its startup health check. The previous app was restored and your backup was kept."
    }
} catch {
    Show-UpdateError ("NekoTrack could not complete the update." + [Environment]::NewLine + [Environment]::NewLine + $_.Exception.Message)
    exit 1
}