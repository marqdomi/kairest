; KaiRest POS - Windows installer
; Wraps the existing install.ps1 / update.ps1 / uninstall.ps1 / restore.ps1 scripts
; in a normal double-click Setup.exe wizard for non-technical users.
;
; Build:
;   "C:\Users\USER\AppData\Local\Programs\Inno Setup 6\ISCC.exe" windows-installer\kairest.iss
; Output:
;   windows-installer\dist\KaiRest-Setup.exe

#define MyAppName "KaiRest POS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "KaiRest"
#define MyAppURL "https://github.com/marqdomi/kairest"
#define RepoRoot "..\"

[Setup]
AppId={{7B7E9C2E-7A0B-4B7C-9C7B-6B0F1A5F2B9E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={%USERPROFILE}\kairest
DefaultGroupName=KaiRest POS
DisableProgramGroupPage=yes
DisableWelcomePage=no
; Siempre instalacion por usuario, sin pedir contrasena de administrador.
; Con el override habilitado, que quedara per-user o per-machine dependia de
; como se lanzara el instalador, y mezclar ambos modos aborta con un mensaje
; que el cliente no puede resolver.
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=KaiRest-Setup
SetupIconFile=assets\kairest.ico
UninstallDisplayIcon={app}\windows-installer-assets\kairest.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio para abrir KaiRest"; GroupDescription: "Accesos directos:"

[Files]
; Modo imagen: la aplicacion se descarga ya compilada desde GHCR, asi que el
; instalador NO lleva el codigo fuente. Solo van los archivos de operacion.
; Esto tambien hace el instalador chico y la instalacion mucho mas rapida.
Source: "{#RepoRoot}docs\GUIA_INSTALACION_WINDOWS.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#RepoRoot}docker-compose.prod.yml"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}update.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}restore.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}respaldo-externo.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\detener.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\reiniciar.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\actualizar.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\restaurar_backup.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\respaldo_externo.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\kairest.url"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\kairest.ico"; DestDir: "{app}\windows-installer-assets"; Flags: ignoreversion

[Icons]
Name: "{group}\Abrir KaiRest"; Filename: "{app}\kairest.url"; IconFilename: "{app}\windows-installer-assets\kairest.ico"
Name: "{group}\Detener KaiRest"; Filename: "{app}\detener.cmd"; IconFilename: "{app}\windows-installer-assets\kairest.ico"; WorkingDir: "{app}"
Name: "{group}\Reiniciar KaiRest"; Filename: "{app}\reiniciar.cmd"; IconFilename: "{app}\windows-installer-assets\kairest.ico"; WorkingDir: "{app}"
Name: "{group}\Actualizar KaiRest"; Filename: "{app}\actualizar.cmd"; IconFilename: "{app}\windows-installer-assets\kairest.ico"; WorkingDir: "{app}"
Name: "{group}\Restaurar backup"; Filename: "{app}\restaurar_backup.cmd"; IconFilename: "{app}\windows-installer-assets\kairest.ico"; WorkingDir: "{app}"
Name: "{group}\Respaldo fuera de la laptop"; Filename: "{app}\respaldo_externo.cmd"; IconFilename: "{app}\windows-installer-assets\kairest.ico"; WorkingDir: "{app}"
Name: "{group}\Desinstalar KaiRest"; Filename: "{uninstallexe}"; IconFilename: "{app}\windows-installer-assets\kairest.ico"
Name: "{userdesktop}\Abrir KaiRest"; Filename: "{app}\kairest.url"; IconFilename: "{app}\windows-installer-assets\kairest.ico"; Tasks: desktopicon

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"""; WorkingDir: "{app}"; RunOnceId: "StopKaiRest"; Flags: waituntilterminated runascurrentuser

[Code]
function DockerDesktopInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{pf}\Docker\Docker\Docker Desktop.exe')) or
            FileExists(ExpandConstant('{pf64}\Docker\Docker\Docker Desktop.exe'));
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;
  if not DockerDesktopInstalled() then
  begin
    if MsgBox('KaiRest necesita Docker Desktop instalado (y abierto) antes de continuar.' + #13#10 + #13#10 +
              'Quieres abrir la pagina de descarga de Docker Desktop ahora?',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      ShellExec('open', 'https://www.docker.com/products/docker-desktop/', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
    end;
    MsgBox('Instala Docker Desktop, abrelo y espera a que diga "Docker Desktop is running". ' +
           'Despues vuelve a ejecutar este instalador.', mbInformation, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  InstallScript: String;
begin
  if CurStep = ssPostInstall then
  begin
    InstallScript := ExpandConstant('{app}\install.ps1');
    WizardForm.StatusLabel.Caption := 'Instalando KaiRest (puede tardar varios minutos la primera vez)...';
    if not Exec('powershell.exe',
                '-NoProfile -ExecutionPolicy Bypass -File "' + InstallScript + '"',
                ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) then
    begin
      MsgBox('No se pudo iniciar PowerShell para completar la instalacion.', mbError, MB_OK);
    end
    else if ResultCode <> 0 then
    begin
      MsgBox('KaiRest se copio pero no pudo iniciar.' + #13#10 + #13#10 +
             'Revisa que Docker Desktop este abierto y funcionando, y vuelve a intentarlo con ' +
             'el acceso directo "Actualizar KaiRest" del menu inicio.', mbError, MB_OK);
    end;
  end;
end;
