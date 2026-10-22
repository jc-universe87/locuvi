; Inno Setup script for the Locuvi Windows installer.
; Built by .github/workflows/release.yml after PyInstaller:  iscc /DAppVersion=1.2.3 locuvi.iss
; Installs for the current user (no administrator needed). Your records are NOT in the
; program folder: they stay in %LOCALAPPDATA%\Locuvi, so updating or uninstalling keeps them.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B1E9C2A-4F3D-4A8E-9C71-2D5B8E0F4A11}
AppName=Locuvi
AppVersion={#AppVersion}
AppPublisher=Locuvi
AppPublisherURL=https://github.com/jc-universe87/locuvi
AppSupportURL=https://github.com/jc-universe87/locuvi/blob/main/docs/APPS.md
DefaultDirName={localappdata}\Programs\Locuvi
DefaultGroupName=Locuvi
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Locuvi-Windows-Setup
SetupIconFile=..\assets\locuvi.ico
UninstallDisplayIcon={app}\Locuvi.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Locuvi icon on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Locuvi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Locuvi"; Filename: "{app}\Locuvi.exe"
Name: "{group}\Uninstall Locuvi"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Locuvi"; Filename: "{app}\Locuvi.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Locuvi.exe"; Description: "Open Locuvi now"; Flags: nowait postinstall skipifsilent
