; Agent Todo 安裝程式（Inno Setup 6）
; 由 build.ps1 呼叫：ISCC /DAppVersion=0.1.0 installer\agent-todo.iss
; 安裝在使用者自己的資料夾，不需要系統管理員權限

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{F3F21B9E-F950-4E49-A0D2-B5FDCE985E10}
AppName=Agent Todo
AppVersion={#AppVersion}
AppVerName=Agent Todo {#AppVersion}
AppPublisher=ChienIKao
AppPublisherURL=https://github.com/ChienIKao/todo
DefaultDirName={localappdata}\Programs\AgentTodo
DefaultGroupName=Agent Todo
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AgentTodo-Setup-v{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\AgentTodo.exe
UninstallDisplayName=Agent Todo
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
ChangesEnvironment=yes

[Languages]
Name: "zh_tw"; MessagesFile: "ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "其他選項："
Name: "startup"; Description: "開機時自動啟動"; GroupDescription: "其他選項："
Name: "addtopath"; Description: "把 todo 指令加入 PATH（在終端機直接打 todo）"; GroupDescription: "其他選項："

[Files]
Source: "..\dist\AgentTodo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 升級時清掉舊版的程式庫，避免殘留不相容的檔案（待辦資料在 ~\.agent-todo，不受影響）
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Agent Todo"; Filename: "{app}\AgentTodo.exe"
Name: "{group}\解除安裝 Agent Todo"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Agent Todo"; Filename: "{app}\AgentTodo.exe"; Tasks: desktopicon
Name: "{userstartup}\Agent Todo"; Filename: "{app}\AgentTodo.exe"; Tasks: startup

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\AgentTodo.exe"; Description: "啟動 Agent Todo"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Dir: string): Boolean;
var
  Path: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Path) then
    Path := '';
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Path) + ';') = 0;
end;
