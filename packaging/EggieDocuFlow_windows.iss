#define MyAppName "Eggie DocuFlow"
#define MyAppPublisher "Eggie DocuFlow"
#define MyAppExeName "Eggie DocuFlow.exe"
#define MyAppVersion GetEnv("EGGIE_APP_VERSION")
#define MyAppSourceDir GetEnv("EGGIE_APP_SOURCE_DIR")
#define MyAppOutputDir GetEnv("EGGIE_APP_OUTPUT_DIR")
#define MyChineseLanguageFile GetEnv("EGGIE_CHINESE_LANGUAGE_FILE")

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

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,Eggie DocuFlow}"; Flags: nowait postinstall skipifsilent
