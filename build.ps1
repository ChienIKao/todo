# 打包成免安裝的 Windows 版：dist\AgentTodo-v<版本>-win64.zip
# 用法：.\build.ps1（需要先建立 .venv 並安裝 requirements.txt）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $python -m pip install -q -r requirements-build.txt
if ($LASTEXITCODE) { throw "安裝打包工具失敗" }

$version = (& $python -c "import agent_todo; print(agent_todo.__version__)").Trim()

# 桌面 App（無主控台視窗）
& $python -m PyInstaller main.py `
    --name AgentTodo `
    --noconfirm --clean --windowed --onedir `
    --icon assets\icon.ico `
    --add-data "agent_todo\ui;agent_todo\ui" `
    --add-data "assets\icon.png;assets" `
    --hidden-import pystray._win32 `
    --hidden-import PIL.PngImagePlugin `
    --collect-all webview
if ($LASTEXITCODE) { throw "PyInstaller（App）失敗" }

# todo 指令與 MCP server（主控台程式，Claude Code／Codex 透過它讀寫待辦）
& $python -m PyInstaller todo.py `
    --name todo `
    --noconfirm --onefile --console `
    --icon assets\icon.ico `
    --distpath build\cli
if ($LASTEXITCODE) { throw "PyInstaller（todo 指令）失敗" }
Copy-Item build\cli\todo.exe dist\AgentTodo\

Copy-Item README.md dist\AgentTodo\
$zip = "dist\AgentTodo-v$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\AgentTodo -DestinationPath $zip
Write-Host "完成：$zip"

$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "/DAppVersion=$version" installer\agent-todo.iss
    if ($LASTEXITCODE) { throw "Inno Setup 失敗" }
    Write-Host "完成：dist\AgentTodo-Setup-v$version.exe"
} else {
    Write-Host "沒有安裝 Inno Setup 6，略過安裝程式"
}
