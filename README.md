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
- 今天／即將到期／全部／日曆／回收桶分頁，支援搜尋、同狀態與優先度內拖曳排序
- 自然語言新增（例如「明天下午3點 交報告 #工作 !高」），即時預覽日期、提醒與標籤
- 詳細內容可編輯子任務、重複規則與提醒；完成或刪除後可按「復原」，回收桶可還原或永久刪除
- 關閉主視窗會縮到系統匣；從系統匣選單結束，`Ctrl+Alt+T` 隨時叫出新增框，提醒會跳通知
- `Ctrl+N` 新增、`/` 搜尋、`1`～`5` 切換分頁（輸入文字時除外）

**接上 AI**
- 右上角 🤖 →「一鍵設定」：自動幫 Claude Code／Codex 加上 MCP server 與全域指示（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md`）
- AI 可以用的工具：`list_todos`、`get_todo`、`add_todo`、`update_todo`、`add_note`、`complete_todo`、`check_subtask`
- 資料與後端支援子任務、重複任務、提醒時間、今天／即將到期檢視、手動排序與回收桶（保留 30 天）
- AI 寫的筆記會標上是誰寫的（claude-code、codex…），你在 App 裡就看得到它做到哪
- 沒接 MCP 的 AI 也可以直接讀 `~/.agent-todo/TODO.md`（自動產生的唯讀快照）

**`todo` 指令**
- 在終端機新增、查看、完成待辦；`--here` 會把目前的 git repo 當成專案，快速輸入可拆出日期、時間、重複規則與標籤（`--raw` 關閉）

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
todo add "明天 下午3點 整理報告 !高 #工作 +報告 @me"
todo add 每天 檢查信箱 --repeat daily --remind-at 2026-10-20T09:00
Get-Clipboard | todo add 照這份規格實作 -c -     # 背景從 stdin 讀

todo                  # 列出未完成
todo ls --here        # 只看目前 repo 的
todo ls --today       # 今天與逾期待辦
todo ls --upcoming    # 明天起 7 天內到期
todo ls -a -q 登入    # 含已完成，搜尋
todo show 1           # 看完整背景與筆記
todo start 1
todo note 1 原因是 GCP 少設 staging 網址
todo block 2 等 PM 回覆
todo done 1 補上 redirect URI，兩邊都測過
todo edit 2 --high --assign codex
todo rm 3             # 移到回收桶
todo trash            # 列出回收桶
todo restore 3        # 還原
todo rm --purge 3     # 永久刪除
todo setup            # 顯示接上 Claude Code／Codex 的設定
```

## 在手機上使用

電腦上的 Agent Todo 和手機共用同一份資料；電腦必須開著 App，縮到系統匣後仍可使用。

- 電腦與手機都安裝 [Tailscale](https://tailscale.com/download)，登入同一個帳號並連線。
- 在電腦 App 右上角按 📱，開啟「手機存取」。預設連接埠為 `8767`，可在面板修改；設定與配對 token 存在 `~/.agent-todo/settings.json`，也支援 `AGENT_TODO_HOME`。
- 面板會偵測 Tailscale。若尚未設定 HTTPS 轉送，按「幫我設定」，或在電腦終端執行 `tailscale serve --bg 8767`（使用自訂埠時請替換數字）。若 Tailscale 提示啟用 tailnet 的 HTTPS，依提示完成後按「重新偵測」。這使用 Tailscale Serve，手機透過 tailnet 連線。[Serve 說明](https://tailscale.com/docs/reference/tailscale-cli/serve)
- 全部就緒後，用手機掃描面板的 QR code，或複製配對網址到手機開啟。網址形式為 `https://<電腦名稱>.<tailnet>.ts.net/pair?token=…`；配對後自動回到首頁，cookie 有效一年。配對網址可存取你的待辦，請妥善保管。
- iPhone 用 Safari 開啟，按分享 →「加入主畫面」；Android 用 Chrome 開啟，選「安裝應用程式」。之後可直接從主畫面使用。
- 連不到電腦時，會顯示最後成功讀取的清單並停用新增、打勾與編輯；恢復連線後自動更新。沒有離線寫入佇列。
- 關閉「手機存取」立即停止遠端服務；「重新產生 token」會讓所有舊手機需要重新配對。

開發測試可執行 `.venv\Scripts\python main.py --dev --remote`，本機介面為 `http://127.0.0.1:8766/?dev`。這個選項會啟用並儲存手機存取設定；測完可在 📱 面板關閉。從資料夾 `~/.agent-todo`（或 `AGENT_TODO_HOME`）的 `settings.json` 取得 token 後，開啟 `http://127.0.0.1:8767/pair?token=…`。只有 Host 為 `127.0.0.1` 的本機測試省略 cookie 的 Secure 屬性，ts.net 配對一律使用 Secure。遠端只接受待辦 API，桌面設定仍由電腦操作。

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
