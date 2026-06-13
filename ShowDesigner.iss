; ShowDesigner.iss — Script Inno Setup para Show Designer Pro (H2)
; Genera ShowDesigner_setup.exe a partir de dist/ShowDesigner/
;
; Requiere: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Uso: iscc ShowDesigner.iss
;
; Prerequisito: ejecutar scripts/build_installer.ps1 primero para generar dist/ShowDesigner/

#define AppName "Show Designer Pro"
#define AppVersion "1.10"
#define AppPublisher "Guille Pondal"
#define AppURL "https://github.com/guillermo-pondal/show-designer"
#define AppExeName "ShowDesigner.exe"

[Setup]
AppId={{8A2F4E1B-C3D7-4F9A-B2E6-1D5C8F3A7E0B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\ShowDesigner
DefaultGroupName={#AppName}
AllowNoIcons=yes
; Requiere permisos de admin (escribe en Program Files)
PrivilegesRequired=admin
OutputDir=.
OutputBaseFilename=ShowDesigner_setup
SetupIconFile=
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; VC++ Redistributable: sounddevice lo requiere; informar al usuario
InfoBeforeFile=
InfoAfterFile=

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copiar todo el directorio generado por PyInstaller
Source: "dist\ShowDesigner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpiar proyectos y configuración al desinstalar (opcional — comentar para preservar datos)
; Type: filesandordirs; Name: "{app}\projects"
; Type: filesandordirs; Name: "{app}\output_targets.json"
