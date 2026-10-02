; Instalador de Windows (Inno Setup). Lo compila la publicación automática (.github/workflows/release.yml):
;   ISCC.exe /DAppVersion=1.13.1 installer\Descargador.iss      →  installer\Output\Descargador_Musica-Setup-v1.13.1.exe
; Se instala solo para tu usuario (no pide permisos de administrador), crea el acceso en el menú Inicio y aparece en
; Configuración de Windows → Aplicaciones → Aplicaciones instaladas, desde donde se puede desinstalar.
; Tus datos (listas, ajustes, letras, biblioteca) viven en %APPDATA%\Descargador de Música y NO se borran al desinstalar.
; El AppId no debe cambiar nunca: es lo que une las versiones entre sí (y lo que usa services/app_updater.py).

#define AppName "Descargador de Música"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B6E1C1F2-5A47-4D0B-9C6E-2D1F7A3E8C54}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Zak208
AppPublisherURL=https://github.com/Zak208/Descargar_Musica
AppSupportURL=https://github.com/Zak208/Descargar_Musica/issues
AppUpdatesURL=https://github.com/Zak208/Descargar_Musica/releases
DefaultDirName={autopf}\Descargador de Musica
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\Descargar_Musica.exe
UninstallDisplayName={#AppName}
OutputDir=Output
OutputBaseFilename=Descargador_Musica-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "..\dist_app\Descargar_Musica\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Descargar_Musica.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Descargar_Musica.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Descargar_Musica.exe"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; la aplicación se actualiza copiando archivos nuevos sobre los viejos: al desinstalar se borra la carpeta entera
Type: filesandordirs; Name: "{app}"
