; Inno Setup script for GuildDraw — per-user (no-admin) Windows installer.
;
; Packages the PyInstaller one-folder build (dist\GuildDraw) into a single
; GuildDraw-<version>-setup.exe that installs to %LocalAppData%\Programs\GuildDraw,
; adds Start Menu (and optional Desktop) shortcuts, registers the .gdraw / .svg
; file associations under HKCU, and provides an Add/Remove Programs uninstaller.
;
; Compile manually:
;   "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" installer\GuildDraw.iss
; Or, with overrides from the release script:
;   ISCC.exe /DMyAppVersion=1.0.0-rc2 /DMyAppVersionNumeric=1.0.0.0 installer\GuildDraw.iss
;
; The release script (scripts\build_release.ps1) passes the version defines and
; builds dist\GuildDraw first. Defaults below let the script be compiled by hand.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyAppVersionNumeric
  #define MyAppVersionNumeric "1.0.0.0"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\dist\GuildDraw"
#endif

#define MyAppName "GuildDraw"
#define MyAppPublisher "Guild of American Spectacle Makers"
#define MyAppExeName "GuildDraw.exe"
#define MyAppId "{{B7E5B0C4-3A9F-4D2E-9C61-5A7F2E8D4B10}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersionNumeric}
VersionInfoProductVersion={#MyAppVersionNumeric}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install — no UAC/admin prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=GuildDraw-{#MyAppVersion}-setup
; Show the GNU GPL v3.0 the app is released under during setup.
LicenseFile=..\LICENSE
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associate"; Description: "Associate .gdraw project files with GuildDraw"; GroupDescription: "File associations:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; .gdraw project association (per-user, removed on uninstall).
Root: HKCU; Subkey: "Software\Classes\.gdraw"; ValueType: string; ValueName: ""; ValueData: "GuildDraw.Project"; Flags: uninsdeletevalue; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildDraw.Project"; ValueType: string; ValueName: ""; ValueData: "GuildDraw Project"; Flags: uninsdeletekey; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildDraw.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildDraw.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
