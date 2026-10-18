NekoTrack installer build

1. From PowerShell at the repository root, run:
   .\installer\build-installer.ps1

   This generates the shared Windows icon, bundles the vector logo assets, and builds the executable. If Inno Setup is installed, the script also compiles the installer.

2. If Inno Setup was not detected, install it and compile installer\NekoTrack.iss.

3. The installer is written to dist-installer\NekoTrack-Setup-<VERSION>.exe, using the version in the repository root VERSION file.

The installer uses a per-user installation under %LOCALAPPDATA%\Programs\NekoTrack.
NekoTrack user data is kept separately under %APPDATA%\NekoTrack and is not bundled into the installer.


Rollback-aware updates
- Before changing an installed executable, NekoTrack verifies the downloaded EXE, records its SHA-256 when the release provides one, and saves a copy of the previous executable.
- A consistent SQLite snapshot and an update manifest are stored under %APPDATA%\NekoTrack\update_backups. Existing database and artwork files are not removed.
- The separate updater waits for NekoTrack to close, replaces the executable only after staging and backup, then requires the candidate to reach its startup health marker. If the first launch fails, it restores the previous executable and its pre-update database snapshot.
- Manual rollback from Settings or the Start Menu restores the previous executable but deliberately leaves the current database and artwork alone. The database snapshot stays available in that backup folder.
- To test releases on an installed app, choose Preview in Settings, publish a higher vX.Y.Z-beta.N prerelease with a NekoTrack.exe asset built from the updater-enabled branch, and keep Stable selected for normal use.
- Running the source with python main.py does not attempt to overwrite source files; it opens the official release page instead.

Isolated preview testing on Windows
1. Create a separate folder such as C:\NekoTrack-Preview and copy NekoTrack.exe there. Do not point the preview shortcut at the normal installed executable.
2. Copy the current %APPDATA%\NekoTrack user-data folder to a separate folder such as %LOCALAPPDATA%\NekoTrack-PreviewData. This copy is the preview library; normal NekoTrack data remains untouched.
3. Make a shortcut to powershell.exe with arguments -NoProfile -ExecutionPolicy Bypass -File "C:\NekoTrack-Preview\run-preview.ps1". Create run-preview.ps1 beside the copied exe with:
   $env:NEKOTRACK_DATA_DIR = "$env:LOCALAPPDATA\NekoTrack-PreviewData"
   Set-Location -LiteralPath $env:NEKOTRACK_DATA_DIR
   & "C:\NekoTrack-Preview\NekoTrack.exe"
4. In Preview Settings, select Preview releases (testing), then Check for updates now. Preview releases should publish NekoTrack.exe built from the updater-enabled branch. To keep the preview install isolated, publish the portable EXE as the preview asset rather than the Setup installer.
5. Test the candidate. The updater stores an EXE backup and a consistent SQLite snapshot under the preview data directory before replacement. Settings > Updates > Restore previous version restores the previous EXE; normal NekoTrack's data is separate.
The NEKOTRACK_DATA_DIR override is process-local. Normal launches without it continue using %APPDATA%\NekoTrack.