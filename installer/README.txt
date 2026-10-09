NekoTrack installer build

1. From PowerShell at the repository root, run:
   .\installer\build-installer.ps1

   This generates the shared Windows icon, bundles the vector logo assets, and builds the executable. If Inno Setup is installed, the script also compiles the installer.

2. If Inno Setup was not detected, install it and compile installer\NekoTrack.iss.

3. The installer is written to dist-installer\NekoTrack-Setup-0.1.0-beta.2.exe.

The installer uses a per-user installation under %LOCALAPPDATA%\Programs\NekoTrack.
NekoTrack user data is kept separately under %APPDATA%\NekoTrack and is not bundled into the installer.
