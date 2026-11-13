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
; Retired from the 1.5.2 release. Preserve locally modified copies.
Type: files; Name: "{app}\_internal\assets\software_logo.png"; Check: OriginalFile('_internal\assets\software_logo.png', 'f45f54eaffe2d79ea1bc0e073a2962f7c7f17f0c7d311d11749dac1ff9e78f2e')
Type: files; Name: "{app}\_internal\release_notes_v1.5.2.md"; Check: OriginalFile('_internal\release_notes_v1.5.2.md', 'b35fe0fa1a60c4a6a7ab41f80ad6634feb4c4d0fbfae71cb29d4db07678d055f')

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
