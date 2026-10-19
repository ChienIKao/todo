# agent-todo

一份待辦清單，三個入口：

| 入口 | 給誰 | 做什麼 |
|---|---|---|
| `todo` CLI | 你 | 在終端機快速新增、查看、完成 |
| 桌面看板 | 你 | 小視窗常駐桌面，隨時看到清單；AI 改了會即時更新 |
| MCP server | Claude Code / Codex | 直接讀你的待辦和**背景說明**、記錄進度、標完成 |

重點是每個待辦都有一個 **背景（context）** 欄位：把需求、連結、限制、驗收條件寫在這裡一次，之後只要跟 AI 說「做 #12」，它就會自己讀，不用再重複解釋。

資料存在 `~/.agent-todo/todos.json`（可用 `AGENT_TODO_HOME` 改位置），每次變更同時產生一份 `~/.agent-todo/TODO.md` 快照。不需要任何外部服務，純 Node.js、零依賴。

## 安裝

需要 Node.js 18 以上。

```bash
git clone https://github.com/ChienIKao/todo.git ~/tools/agent-todo
cd ~/tools/agent-todo
npm link          # 之後就能直接用 `todo` 指令
todo setup        # 印出下面兩段設定，路徑已幫你填好
```

## 接上 Claude Code

```bash
claude mcp add --scope user todo -- node ~/tools/agent-todo/bin/todo.js mcp
```

## 接上 Codex

在 `~/.codex/config.toml` 加：

```toml
[mcp_servers.todo]
command = "node"
args = ["/Users/你/tools/agent-todo/bin/todo.js", "mcp"]
```

## 讓 AI 預設會去看待辦（建議）

把 [`docs/agent-instructions.md`](docs/agent-instructions.md) 的內容貼進：

- `~/.claude/CLAUDE.md`（Claude Code 全域指示）
- `~/.codex/AGENTS.md`（Codex 全域指示）

之後在任何 repo 裡說「看一下我的待辦，做優先度最高的那個」或「處理 #3」就行。
AI 會：`list_todos` → `get_todo` 讀背景 → 設成進行中 → 邊做邊 `add_note` → `complete_todo` 附上摘要。
你在看板上就能看到它做到哪、留了什麼筆記。

MCP 提供的工具：

| 工具 | 用途 |
|---|---|
| `list_todos` | 列出待辦（可依 status / project / tag / assignee / 關鍵字篩選） |
| `get_todo` | 讀單一待辦的完整背景與筆記 |
| `add_todo` | 新增待辦 |
| `update_todo` | 改狀態、優先度、背景等 |
| `add_note` | 追加進度筆記（會記錄是哪個 agent 寫的） |
| `complete_todo` | 標記完成並附摘要 |

## 桌面看板

```bash
todo serve --open     # http://localhost:4567
```

在 Chrome / Edge 打開後，網址列右側點「安裝」（或選單 → 投放、儲存和分享 → 安裝為應用程式），就會變成一個獨立的桌面小視窗，可以釘在 Dock / 工作列。

- 點標題展開，可以直接改背景、狀態、優先度，或加筆記
- 「🤖 複製給 AI 的指令」會複製一段叫 AI 處理這個待辦的話，貼給 Claude Code / Codex 即可
- AI 或 CLI 改了清單，看板會即時更新

想開機自動啟動看板：

- **macOS**：在「系統設定 → 一般 → 登入項目」加一個執行 `todo serve` 的腳本，或用 LaunchAgent
- **Windows**：在 `shell:startup` 資料夾放一個捷徑，目標為 `node C:\…\bin\todo.js serve`
- **Linux**：用 systemd user service 或桌面環境的自動啟動

看板只監聽 `127.0.0.1`，並會擋掉其他網站的跨站請求。

## CLI

```bash
todo add "修登入頁 OAuth 500" --here --high --assign claude \
  -c "Google 登入後 callback 回 500，log 是 redirect_uri mismatch。驗收：本機與 staging 都能登入。"
todo add "整理 Q4 報告" -p 工作 --due 2026-10-25
pbpaste | todo add "照這份規格實作" -c -     # 背景從 stdin 讀

todo                  # 列出未完成
todo ls --here        # 只看目前 repo 的
todo ls -a -q 登入    # 含已完成，搜尋
todo show 1           # 看完整背景與筆記
todo start 1
todo note 1 "原因是 GCP 少設 staging 網址"
todo block 2 "等 PM 回覆"
todo done 1 "補上 redirect URI，兩邊都測過"
todo edit 2 --high --assign codex
todo rm 3
```

`--here` 會把目前所在的 git repo 路徑當作專案，AI 在同一個 repo 裡就能用 project 篩出相關待辦。

## 開發

```bash
npm test
```
