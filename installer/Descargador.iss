; Instalador de Windows (Inno Setup). Lo compila la publicación automática (.github/workflows/release.yml):
;   ISCC.exe /DAppVersion=1.15.1 installer\Descargador.iss      →  installer\Output\Descargador_Musica-Setup-v1.15.1.exe
;
; Asistente sencillo, como el de cualquier aplicación:
;   1. Bienvenida  2. Aviso legal, privacidad y licencia (hay que aceptarlo)  3. ¿En qué carpeta se instala?
;   4. ¿Dónde se crean los accesos directos? (escritorio / menú Inicio)  5. Resumen  6. Instalación  7. Abrir el programa
; Se instala solo para tu usuario (no pide permisos de administrador) y aparece en Configuración de Windows →
; Aplicaciones, desde donde se desinstala. Tus datos (listas, ajustes, letras...) viven en %APPDATA%\Descargador de Música;
; al desinstalar, el propio desinstalador pregunta si quieres borrarlos también (por defecto NO).
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
; en una instalación nueva pregunta la carpeta; al actualizar con el instalador usa la de la vez anterior
DisableDirPage=auto
UsePreviousAppDir=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile=..\AVISO_LEGAL_Y_PRIVACIDAD.txt
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\Descargar_Musica.exe
UninstallDisplayName={#AppName}
WizardImageFile=imagen_grande.bmp,imagen_grande_2x.bmp
WizardSmallImageFile=imagen_pequena.bmp,imagen_pequena_2x.bmp
OutputDir=Output
OutputBaseFilename=Descargador_Musica-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardResizable=no
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
WizardLicense=Aviso legal y privacidad
LicenseLabel=Lee con calma esta información antes de continuar.
LicenseLabel3=Para instalar el programa tienes que aceptar este aviso. Si no lo aceptas, cancela la instalación.
LicenseAccepted=&Lo he leído y lo acepto
LicenseNotAccepted=&No lo acepto
SelectDirLabel3=El programa se instalará en la siguiente carpeta.
SelectDirBrowseLabel=Pulsa Siguiente para continuar. Si quieres elegir otra carpeta, pulsa Examinar.

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el &escritorio"; GroupDescription: "¿Dónde quieres los accesos directos?"
Name: "startmenuicon"; Description: "Crear un acceso directo en el menú &Inicio"; GroupDescription: "¿Dónde quieres los accesos directos?"

[Files]
Source: "..\dist_app\Descargar_Musica\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\AVISO_LEGAL_Y_PRIVACIDAD.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; DestName: "LICENCIAS_DE_TERCEROS.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Descargar_Musica.exe"; Tasks: startmenuicon
Name: "{autoprograms}\{#AppName} - Aviso legal y privacidad"; Filename: "{app}\AVISO_LEGAL_Y_PRIVACIDAD.txt"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Descargar_Musica.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Descargar_Musica.exe"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; la aplicación se actualiza copiando archivos nuevos sobre los viejos: al desinstalar se borra la carpeta del programa
; (el instalador nunca deja instalar en una carpeta con archivos ajenos, ver NextButtonClick)
Type: filesandordirs; Name: "{app}"

[Code]
function CarpetaTieneArchivosAjenos(Dir: String): Boolean;
var
  Busqueda: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Dir) + '*', Busqueda) then
  begin
    try
      repeat
        if (Busqueda.Name <> '.') and (Busqueda.Name <> '..') then
        begin
          Result := True;
          Break;
        end;
      until not FindNext(Busqueda);
    finally
      FindClose(Busqueda);
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Dir := RemoveBackslash(WizardDirValue);
    { si la carpeta elegida ya tiene otras cosas, se instala dentro de una carpeta propia: así desinstalar nunca borra archivos ajenos }
    if DirExists(Dir) and CarpetaTieneArchivosAjenos(Dir) and not FileExists(Dir + '\Descargar_Musica.exe') then
    begin
      WizardForm.DirEdit.Text := Dir + '\Descargador de Musica';
      MsgBox('Esa carpeta ya tiene otros archivos, así que el programa se instalará dentro de su propia carpeta:' + #13#10 + #13#10 +
             WizardForm.DirEdit.Text, mbInformation, MB_OK);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Datos: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Datos := ExpandConstant('{userappdata}\Descargador de Música');
    if DirExists(Datos) and not UninstallSilent then
    begin
      if MsgBox('¿Quieres borrar también tus listas, favoritos, ajustes y letras?' + #13#10 +
                '(Tu música descargada no se borra.)', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Datos, True, True, True);
    end;
  end;
end;
