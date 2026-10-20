# Agent Todo

**讓 Claude Code 和 Codex 也看得到的待辦清單。**

每件事附一段「背景」，寫一次就好。之後在 Claude Code 或 Codex 裡說「處理 #12」，AI 會自己讀背景、開始做、邊做邊記進度、做完回報，不用再重講一次來龍去脈。

*A Windows todo app with a built-in MCP server, so Claude Code and Codex can read your todos — including the background for each one — and update them as they work. Desktop app, `todo` CLI and a phone PWA, all sharing one local file. UI in Traditional Chinese.*

## 安裝

到 [Releases](../../releases/latest) 下載 `AgentTodo-Setup-v*.exe` 執行。不需要系統管理員權限，可以勾選：

- 建立桌面捷徑
- 開機時自動啟動
- 把 `todo` 指令加入 PATH

裝好之後：

1. 打開 App，按右上角的「接上 AI」按鈕 →「一鍵設定」，幫 Claude Code／Codex 接上待辦清單
2. 重新開啟 Claude Code／Codex
3. 在任何 repo 裡說「看一下我的待辦」

## 用法

### 新增待辦

在最上面的輸入框直接打一句話，按 Enter。日期、時間、標籤這些會自動拆出來，輸入框下面會即時顯示拆到了什麼：

```
明天下午3點 交報告 #工作 +公司 @codex !高
```

| 寫法 | 例子 | 結果 |
|---|---|---|
| 日期 | `今天` `明天` `後天` `週五` `下週一` `10/25` `2026-10-25` | 期限 |
| 時間 | `下午3點` `晚上8點半` `15:00` `3pm` | 提醒（同時設期限） |
| 重複 | `每天` `平日` `每週一` `每月` `每年` | 重複規則 |
| 優先度 | `!高` `!!` `!低` | 高／低 |
| 標籤 | `#工作` | 可以多個 |
| 專案 | `+公司` | 名稱或 repo 路徑 |
| 負責 | `@claude` `@codex` `@me` | 誰來做 |

按「更多欄位」按鈕可以展開完整欄位，最重要的是**背景**：連結、要求、驗收條件，寫到別人（或 AI）不用問你就能開始做的程度。

### 看清單

- **分頁**：今天（含逾期與進行中）／即將到期（7 天內）／全部／日曆／回收桶
- **點標題展開**：直接改背景、狀態、優先度、期限，加子任務、設重複和提醒，寫進度筆記
- **拖曳排序**：同一個狀態、同一個優先度裡可以拖曳調整順序
- **完成和刪除都可以復原**：刪除的會先進回收桶，保留 30 天
- **複製給 AI 的指令**：複製一段「請處理 #N」的話，貼給 Claude Code／Codex

### 隨時看得到

- **置頂小視窗**：縮成一個浮在最上層的小清單，可以直接打勾或新增
- **系統匣**：按「關閉」按鈕會縮到系統匣，App 還在跑、提醒照常通知；要結束從系統匣選單
- **`Ctrl+Alt+T`**：在任何地方叫出 App 並聚焦新增框
- **提醒**：時間到跳 Windows 通知

| 快捷鍵 | 作用 |
|---|---|
| `Ctrl+Alt+T` | 任何地方叫出新增框 |
| `Ctrl+N` | 新增 |
| `/` | 搜尋 |
| `1`～`5` | 切換分頁 |

## 跟 AI 一起用

在任何 repo 裡開 Claude Code 或 Codex：

- 「看一下我的待辦，做優先度最高的那個」
- 「處理 #3」
- 「這個 repo 有什麼待辦？」
- 「把剛剛討論的後續工作加到我的待辦，背景寫清楚」

AI 會依照一鍵設定加進去的全域指示（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md`）做事：

1. `list_todos`：列出待辦，目前 repo 的排前面
2. `get_todo`：讀完整背景與筆記
3. 把狀態設成進行中；工作大的話先拆成子任務
4. 邊做邊 `add_note` 記進度、`check_subtask` 勾掉完成的步驟
5. `complete_todo` 附上摘要（改了哪些檔案、PR 連結、後續要注意的事）

AI 寫的筆記會標上是誰寫的（claude-code、codex），在 App 裡就看得到它做到哪。AI 改了清單，畫面會自動更新。

| MCP 工具 | 用途 |
|---|---|
| `list_todos` | 列出待辦，可以篩選今天、即將到期、專案、標籤、負責人、關鍵字 |
| `get_todo` | 讀一個待辦的完整背景、子任務與筆記 |
| `add_todo` | 新增，可以帶子任務、重複、提醒 |
| `update_todo` | 修改任何欄位 |
| `add_note` | 加進度筆記 |
| `check_subtask` | 勾掉子任務 |
| `complete_todo` | 標記完成並附摘要；重複任務會自動建立下一次 |

沒接 MCP 的 AI 也可以讀 `~/.agent-todo/TODO.md`（自動產生的唯讀快照），或用 `todo` 指令。

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

## 在手機上使用

手機透過 [Tailscale](https://tailscale.com/download) 連回電腦上的 App，用的是同一份資料。不用上架商店，加到主畫面就像一般 App。**電腦要開著 App**（縮在系統匣也可以），手機才能用。

1. 電腦和手機都安裝 Tailscale，登入同一個帳號
2. 電腦 App 右上角按「手機存取」按鈕
3. 面板會偵測 Tailscale；還沒設定的話按「幫我設定」（等同執行 `tailscale serve --bg 8767`）
4. 用手機掃面板上的 QR code 配對
5. iPhone 用 Safari 開，按分享 →「加入主畫面」；Android 用 Chrome 開，選「安裝應用程式」

連線只在你的 Tailscale 網路裡，外人連不到；配對網址等於鑰匙，不要外流。按「重新產生 token」會讓所有手機都要重新配對。連不到電腦時，手機會顯示上次的清單（唯讀）。

電腦關機時也能用的雲端同步還在規劃中，見 [#1](../../issues/1)。

## `todo` 指令

```powershell
todo add 明天下午3點 交報告 #工作 !高             # 跟 App 一樣會拆日期、時間、標籤（--raw 關閉）
todo add 修登入頁 OAuth 500 --here --assign claude `
  -c "Google 登入後 callback 回 500，log 是 redirect_uri mismatch。驗收：本機與 staging 都能登入。"
Get-Clipboard | todo add 照這份規格實作 -c -      # 背景從 stdin 讀

todo                  # 列出未完成（目前 repo 的排前面）
todo ls --today       # 今天與逾期
todo ls --upcoming    # 7 天內到期
todo ls --here        # 只看目前 repo
todo ls -a -q 登入    # 含已完成，搜尋
todo show 1           # 完整背景、子任務與筆記

todo start 1
todo note 1 原因是 GCP 少設 staging 網址
todo block 2 等 PM 回覆
todo done 1 補上 redirect URI，兩邊都測過
todo edit 2 --high --assign codex --repeat weekly --remind-at 2026-10-27T09:00

todo rm 3             # 移到回收桶
todo trash            # 看回收桶
todo restore 3        # 還原
todo rm --purge 3     # 永久刪除

todo setup            # 顯示接上 Claude Code／Codex 的設定
```

AI 用 `todo` 指令寫筆記時加上 `--by claude-code` 或 `--by codex`，筆記才會標成它寫的。

## 資料

全部存在你的電腦上，不需要帳號或雲端服務：

| 檔案 | 內容 |
|---|---|
| `~/.agent-todo/todos.json` | 待辦資料（App、`todo` 指令、MCP server 共用） |
| `~/.agent-todo/TODO.md` | 唯讀快照，給沒接 MCP 的 AI 讀 |
| `~/.agent-todo/settings.json` | 手機存取設定與配對 token |

環境變數 `AGENT_TODO_HOME` 可以改資料夾位置。

## 開發

需要 Python 3.10 以上。雙擊 `啟動待辦.bat`（第一次會自動建立 `.venv` 並安裝套件），或：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pytest
.venv\Scripts\python main.py            # 桌面 App
.venv\Scripts\python todo.py ls         # todo 指令
.venv\Scripts\python -m pytest -q       # 測試
.\build.ps1                             # 打包，有 Inno Setup 6 會再產生安裝程式
```

安裝程式升級時會先把現有的 `todo.exe` 改名成 `todo.exe.<時間>.old`（Claude Code／Codex 開著的 MCP server 照樣跑，不會被關掉），再放入新版；之後安裝或解除安裝時會清掉已經沒在用的 `.old` 檔。`AgentTodo.exe` 若正在執行會先被結束，靜默安裝完會自動重新開啟。

`python main.py --dev` 不開視窗，改在瀏覽器開 `http://127.0.0.1:8766/?dev` 方便改介面；加上 `--remote` 會一起開手機用的伺服器（`127.0.0.1:8767`）。

推送 `v*` 標籤（要跟 `agent_todo/__init__.py` 的版本一致）會由 GitHub Actions 跑測試、打包並建立 Release。

| 檔案 | 用途 |
|---|---|
| `main.py` | 桌面 App 進入點 |
| `todo.py` | `todo` 指令與 MCP server 進入點 |
| `agent_todo/store.py` | 待辦資料讀寫（多個程序同時寫入時用 lock 檔互斥） |
| `agent_todo/quickadd.py` | 自然語言快速輸入 |
| `agent_todo/mcp.py` | MCP server（stdio JSON-RPC） |
| `agent_todo/api.py` | 介面呼叫的 API |
| `agent_todo/desktop.py` | 系統匣、全域快捷鍵、提醒通知 |
| `agent_todo/mobile.py` | 手機存取、Tailscale 偵測與配對 |
| `agent_todo/server.py` | 本機與手機用的 HTTP 伺服器 |
| `agent_todo/integrations.py` | 一鍵設定 Claude Code／Codex |
| `agent_todo/ui/` | 介面（HTML／CSS／JavaScript、PWA） |

## 授權

[MIT](LICENSE)
