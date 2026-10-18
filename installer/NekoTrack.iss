; NekoTrack Windows installer
; Run installer\build-installer.ps1 from the repository root first. It generates
; the shared application icon, builds the executable, and optionally compiles this installer.

#define MyAppName "NekoTrack"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
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
SetupIconFile=..\assets\NekoTrack.ico
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "safe_update.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Restore Previous NekoTrack Version"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\safe_update.ps1"" -Action RollbackLatest -InstallDirectory ""{app}"" -DataDirectory ""{userappdata}\NekoTrack"""; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately do not remove {userappdata}\NekoTrack or its database/images.
