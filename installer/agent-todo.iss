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
var
  RenamedTodo: string;
  ClosedApp: Boolean;

// todo.exe 常被 Claude Code／Codex 當 MCP server 開著，沒辦法覆蓋。
// Windows 允許改名執行中的 exe，舊的 process 照樣跑，所以先改名再裝新版。
procedure DeleteOldTodoExes(Dir: string);
var
  Find: TFindRec;
begin
  if FindFirst(Dir + '\todo.exe*.old', Find) then
  try
    repeat
      DeleteFile(Dir + '\' + Find.Name);  // 還在用的刪不掉，留到下次
    until not FindNext(Find);
  finally
    FindClose(Find);
  end;
end;

// 依完整路徑結束 {app} 裡的 AgentTodo.exe，不影響其他位置的同名程式。
// 它的關閉按鈕只會縮到系統匣，靠 CloseApplications 關不掉。
function CloseAgentTodo(ExePath: string): Boolean;
var
  Locator, Service, Procs, Proc, Path: Variant;
  I, Tries: Integer;
  Found: Boolean;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    for Tries := 0 to 20 do begin
      Procs := Service.ExecQuery('SELECT ProcessId, ExecutablePath FROM Win32_Process WHERE Name = ''AgentTodo.exe''');
      Found := False;
      for I := 0 to Procs.Count - 1 do begin
        Proc := Procs.ItemIndex(I);
        Path := Proc.ExecutablePath;
        if not VarIsNull(Path) then
          if SameText(Path, ExePath) then begin
            Found := True;
            Result := True;
            if Tries = 0 then
              Proc.Terminate(0);
          end;
      end;
      if not Found then
        Exit;
      Sleep(250);
    end;
  except
    Log('無法檢查 AgentTodo.exe 是否在執行：' + GetExceptionMessage);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Dir, Todo, Stamp: string;
  N: Integer;
begin
  Result := '';
  Dir := ExpandConstant('{app}');
  ClosedApp := CloseAgentTodo(Dir + '\AgentTodo.exe');
  DeleteOldTodoExes(Dir);
  Todo := Dir + '\todo.exe';
  if not FileExists(Todo) then
    Exit;
  Stamp := GetDateTimeString('yyyymmddhhnnss', #0, #0);
  RenamedTodo := Todo + '.' + Stamp + '.old';
  N := 1;
  while FileExists(RenamedTodo) do begin
    RenamedTodo := Todo + '.' + Stamp + '-' + IntToStr(N) + '.old';
    N := N + 1;
  end;
  if not RenameFile(Todo, RenamedTodo) then begin
    Result := '無法把 ' + Todo + ' 改名成 ' + ExtractFileName(RenamedTodo) +
      '，所以沒辦法更新它。' + #13#10 + SysErrorMessage(DLLGetLastError) + #13#10 +
      '請關閉正在使用 todo 指令的程式（例如 Claude Code、Codex）後再試一次。';
    RenamedTodo := '';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    RenamedTodo := '';
    // 一般安裝由 [Run] 的勾選項重新啟動；靜默安裝時把關掉的 App 開回來
    if ClosedApp and WizardSilent then
      if not ExecAsOriginalUser(ExpandConstant('{app}\AgentTodo.exe'), '', '', SW_SHOWNORMAL, ewNoWait, ResultCode) then
        Log('無法重新啟動 AgentTodo.exe：' + SysErrorMessage(ResultCode))
      else
        Log('已重新啟動 AgentTodo.exe');
  end;
end;

// 改名後安裝沒完成（取消或失敗）就把舊的 todo.exe 放回去
procedure DeinitializeSetup();
var
  Todo: string;
begin
  if RenamedTodo <> '' then begin
    Todo := ExtractFilePath(RenamedTodo) + 'todo.exe';
    if not FileExists(Todo) then
      RenameFile(RenamedTodo, Todo);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    DeleteOldTodoExes(ExpandConstant('{app}'));
end;

function NeedsAddPath(Dir: string): Boolean;
var
  Path: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Path) then
    Path := '';
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Path) + ';') = 0;
end;
