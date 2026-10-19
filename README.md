# Agent Todo

**讓 Claude Code 和 Codex 也看得到的待辦清單。** 每件事都附一段「背景」，寫一次就好；之後跟 AI 說「處理 #12」，它會自己讀背景、開始做、記進度、做完回報，不用再重複解釋。

*A Windows desktop todo app (Python + pywebview) with a built-in MCP server, so Claude Code and Codex can read your todos — including the background for each — and update them as they work. UI in Traditional Chinese.*

## 功能

**桌面 App**
- 快速新增：輸入標題按 Enter；按「⋯」可以填背景、專案、優先度、負責人、期限、標籤
- 依狀態分組（進行中／待辦／卡住／已完成），可以依專案篩選或搜尋
- 點標題展開：直接改背景、狀態、優先度，或加進度筆記
- **📌 置頂小視窗**：縮成一個浮在最上層的小清單，隨時看得到，也能直接打勾或新增
- 「🤖 複製給 AI 的指令」：複製一段請 AI 處理這個待辦的話，貼給 Claude Code／Codex 即可
- AI 或 `todo` 指令改了清單，畫面會自動更新

**接上 AI**
- 右上角 🤖 →「一鍵設定」：自動幫 Claude Code／Codex 加上 MCP server 與全域指示（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md`）
- AI 可以用的工具：`list_todos`、`get_todo`、`add_todo`、`update_todo`、`add_note`、`complete_todo`
- AI 寫的筆記會標上是誰寫的（claude-code、codex…），你在 App 裡就看得到它做到哪
- 沒接 MCP 的 AI 也可以直接讀 `~/.agent-todo/TODO.md`（自動產生的唯讀快照）

**`todo` 指令**
- 在終端機新增、查看、完成待辦；`--here` 會把目前的 git repo 當成專案

資料存在 `~/.agent-todo/todos.json`（可以用環境變數 `AGENT_TODO_HOME` 改位置），全部在你的電腦上，不需要帳號或雲端服務。

## 安裝

到 [Releases](../../releases/latest) 下載 `AgentTodo-Setup-v*.exe`。安裝時可以勾選：

- 建立桌面捷徑
- 開機時自動啟動
- 把 `todo` 指令加入 PATH

裝好打開 App，按右上角 🤖 →「一鍵設定」，重新開啟 Claude Code／Codex 就生效。

### 從原始碼執行

需要 Python 3.10 以上。雙擊 `啟動待辦.bat`（第一次會自動建立 `.venv` 並安裝套件），或：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

`todo` 指令用 `python todo.py …` 執行。開發介面時可以用 `python main.py --dev`，在一般瀏覽器開 `http://127.0.0.1:8766/?dev`。

## 怎麼跟 AI 說

在任何 repo 裡開 Claude Code 或 Codex：

- 「看一下我的待辦，做優先度最高的那個」
- 「處理 #3」
- 「這個 repo 有什麼待辦？」
- 「把剛剛討論的後續工作加到我的待辦，背景寫清楚」

AI 會：`list_todos` → `get_todo` 讀背景 → 設成進行中 → 邊做邊 `add_note` → `complete_todo` 附上摘要。

### 手動設定

不想用一鍵設定的話（`todo setup` 會印出含正確路徑的版本）：

```powershell
# Claude Code
claude mcp add --scope user todo -- "C:\Users\你\AppData\Local\Programs\AgentTodo\todo.exe" mcp
```

```toml
# Codex：~/.codex/config.toml
[mcp_servers.todo]
command = "C:\\Users\\你\\AppData\\Local\\Programs\\AgentTodo\\todo.exe"
args = ["mcp"]
```

## `todo` 指令

```powershell
todo add 修登入頁 OAuth 500 --here --high --assign claude `
  -c "Google 登入後 callback 回 500，log 是 redirect_uri mismatch。驗收：本機與 staging 都能登入。"
todo add 整理 Q4 報告 -p 工作 --due 2026-10-25
Get-Clipboard | todo add 照這份規格實作 -c -     # 背景從 stdin 讀

todo                  # 列出未完成
todo ls --here        # 只看目前 repo 的
todo ls -a -q 登入    # 含已完成，搜尋
todo show 1           # 看完整背景與筆記
todo start 1
todo note 1 原因是 GCP 少設 staging 網址
todo block 2 等 PM 回覆
todo done 1 補上 redirect URI，兩邊都測過
todo edit 2 --high --assign codex
todo rm 3
todo setup            # 顯示接上 Claude Code／Codex 的設定
```

## 開發

```powershell
python -m unittest        # 測試
.\build.ps1               # 打包：dist\AgentTodo-v<版本>-win64.zip，有 Inno Setup 6 會再產生安裝程式
```

推送 `v*` 標籤（版本要跟 `agent_todo/__init__.py` 一致）會由 GitHub Actions 自動打包並建立 Release。

| 檔案 | 用途 |
|---|---|
| `main.py` | 桌面 App 進入點（pywebview 視窗） |
| `todo.py` | `todo` 指令與 MCP server 進入點 |
| `agent_todo/store.py` | 待辦資料的讀寫（多個程序同時寫入時用 lock 檔互斥） |
| `agent_todo/mcp.py` | MCP server（stdio JSON-RPC） |
| `agent_todo/api.py` | 介面呼叫的 API（pywebview js_api） |
| `agent_todo/integrations.py` | 一鍵設定 Claude Code／Codex |
| `agent_todo/ui/` | 介面（HTML／CSS／JavaScript） |
