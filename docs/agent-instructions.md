## 我的待辦清單（agent-todo）

我用 `todo` MCP server 管理待辦事項，每個待辦的 `context` 欄位就是我要交代的背景，讀它就不用我再解釋一次。

- 我說「做下一件事」「看我的待辦」「處理 #12」之類的話時：先用 `list_todos`（在 repo 裡就帶 `project` 篩選目前 repo），再用 `get_todo` 讀完整背景與筆記後才開始。
- 開始做時用 `update_todo` 把狀態設成 `doing`；重要決定、進度、卡住的原因用 `add_note` 記下來。
- 做完用 `complete_todo`，`summary` 寫清楚做了什麼（改了哪些檔案、PR 連結、後續要注意的事）。
- 過程中發現新的工作，用 `add_todo` 新增，`context` 寫到別人能直接接手的程度。
- 若沒有 MCP 工具可用，可直接讀 `~/.agent-todo/TODO.md`（唯讀快照），或用 `todo` CLI（`todo ls`、`todo show <id>`、`todo note <id> "..."`、`todo done <id> "摘要"`）。
