#define MyAppName "Eggie DocuFlow"
#define MyAppPublisher "Eggie DocuFlow"
#define MyAppExeName "Eggie DocuFlow.exe"
#define MyAppVersion GetEnv("EGGIE_APP_VERSION")
#define MyAppSourceDir GetEnv("EGGIE_APP_SOURCE_DIR")
#define MyAppOutputDir GetEnv("EGGIE_APP_OUTPUT_DIR")
#define MyChineseLanguageFile GetEnv("EGGIE_CHINESE_LANGUAGE_FILE")

#if FileExists(MyAppSourceDir + "\_internal\eggie-update-ed25519.pub") && !FileExists(MyAppSourceDir + "\eggie-runtime.json")
  #error Signed update runtimes need eggie-runtime.json. Stamp the isolated PyInstaller output before compiling.
#endif

[Setup]
AppId={{7DA942BC-98E2-48DB-93C7-741D7FD9C1C3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyAppOutputDir}
OutputBaseFilename=EggieDocuFlow_V{#MyAppVersion}_Windows_x64_Setup
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=no
DisableReadyPage=no

[Languages]
Name: "chinesesimp"; MessagesFile: "{#MyChineseLanguageFile}"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
#include "retired_2026110401.iss"
; Old layout package, removed only when it still looks like our Python package.
Type: filesandordirs; Name: "{app}\v2"; Check: RetiredPackageDir('v2')
Type: filesandordirs; Name: "{app}\_internal\v2"; Check: RetiredPackageDir('_internal\v2')

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,Eggie DocuFlow}"; Flags: nowait postinstall skipifsilent

[Code]
function OriginalFile(Name, ExpectedHash: String): Boolean;
var
  Filename: String;
begin
  Filename := ExpandConstant('{app}') + '\' + Name;
  Result := FileExists(Filename);
  if Result then
    Result := CompareText(GetSHA256OfFile(Filename), ExpectedHash) = 0;
end;

function RetiredPackageDir(Relative: String): Boolean;
var
  Dir: String;
  Found: TFindRec;
begin
  Dir := ExpandConstant('{app}\') + Relative;
  Result := DirExists(Dir) and (
    FileExists(Dir + '\__init__.py') or FileExists(Dir + '\__init__.pyc'));
  if not Result and DirExists(Dir) then
  begin
    if FindFirst(Dir + '\__init__.cpython-*.pyc', Found) then
    begin
      Result := True;
      FindClose(Found);
    end;
  end;
end;
