; NekoTrack Windows installer
; Build the PyInstaller executable first:
;   pyinstaller --onefile --windowed --name NekoTrack main.py
; Then open this file with Inno Setup and compile it.

#define MyAppName "NekoTrack"
#define MyAppVersion "0.1.0-beta.2"
#define MyAppPublisher "konokuroineko"
#define MyAppExeName "NekoTrack.exe"

[Setup]
AppId={{8E9E0C0D-9D54-4A56-9A64-7C3D1D7F0F2C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\NekoTrack
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=NekoTrack-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately do not remove {userappdata}\NekoTrack or its database/images.
