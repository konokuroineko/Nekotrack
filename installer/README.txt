NekoTrack installer build

1. Build the standalone app from the repository root:
   pyinstaller --onefile --windowed --name NekoTrack main.py

2. Install Inno Setup on the development machine.

3. Open installer\NekoTrack.iss in Inno Setup and compile it.

4. The installer is written to dist-installer\NekoTrack-Setup-0.1.0-beta.2.exe.

The installer uses a per-user installation under %LOCALAPPDATA%\Programs\NekoTrack.
NekoTrack user data is kept separately under %APPDATA%\NekoTrack and is not bundled into the installer.
