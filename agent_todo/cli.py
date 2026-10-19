"""todo 指令：在終端機新增、查看、完成待辦；todo mcp 啟動給 AI 用的 MCP server"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, integrations, store, quickadd

ICON = {"todo": "○", "doing": "◐", "blocked": "⊘", "done": "●"}


def repo_root(start: Path | None = None) -> str:
    """目前所在的 git repo 根目錄；不在 repo 裡就是目前資料夾"""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return str(d)
    return str(here)


def _fields(a) -> dict:
    f = {}
    if a.title is not None:
        f["title"] = a.title
    if a.context is not None:
        f["context"] = sys.stdin.read() if a.context == "-" else a.context
    if a.here:
        f["project"] = repo_root()
    elif a.project is not None:
        f["project"] = a.project
    if a.priority:
        f["priority"] = a.priority
    if a.status:
        f["status"] = a.status
    if a.assign is not None:
        f["assignee"] = a.assign
    if a.due is not None:
        f["due"] = a.due
    if a.tags is not None:
        f["tags"] = a.tags
    if a.repeat is not None:
        f["repeat"] = a.repeat
    if a.remind_at is not None:
        f["remindAt"] = a.remind_at
    return f


def _print_list(todos: list[dict]) -> None:
    if not todos:
        print("（沒有待辦）")
    for t in todos:
        meta = [x for x in ("!高" if t["priority"] == "high" else "",
                            Path(t["project"]).name if t["project"] else "",
                            f"@{t['assignee']}" if t["assignee"] else "",
                            f"due {t['due']}" if t["due"] else "",
                            "背景" if t["context"] else "",
                            f"筆記 {len(t['notes'])}" if t["notes"] else "") if x]
        print(f"{ICON[t['status']]} #{t['id']:<3} {t['title']}" + (f"  [{' · '.join(meta)}]" if meta else ""))


def _setup_text() -> str:
    return f"""資料檔：{store.data_file()}
Markdown 快照：{store.markdown_file()}

── Claude Code ──────────────────────────────
{integrations.claude_command()}

── Codex（~/.codex/config.toml）────────────
{integrations.codex_toml()}
── 全域指示：貼到 ~/.claude/CLAUDE.md 和 ~/.codex/AGENTS.md ──
{integrations.INSTRUCTIONS}
（在 App 的「接上 AI」裡可以一鍵完成以上設定）"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="todo", description="Agent Todo：待辦清單，Claude Code／Codex 也看得到")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    def fields(sp, title_flag: bool):
        if title_flag:
            sp.add_argument("--title")
            sp.add_argument("--status", choices=store.STATUSES)
        sp.add_argument("-c", "--context", help='背景說明（給 AI 看）；用 "-" 從 stdin 讀')
        sp.add_argument("-p", "--project", help="專案名稱或路徑")
        sp.add_argument("--here", action="store_true", help="用目前的 git repo 當專案")
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--high", dest="priority", action="store_const", const="high", help="高優先")
        g.add_argument("--low", dest="priority", action="store_const", const="low", help="低優先")
        g.add_argument("--normal", dest="priority", action="store_const", const="normal", help="普通優先")
        sp.add_argument("--assign", help="負責：me / claude / codex …")
        sp.add_argument("--due", help="期限 YYYY-MM-DD")
        sp.add_argument("--repeat", choices=store.REPEATS, help="重複規則")
        sp.add_argument("--remind-at", help="提醒時間 YYYY-MM-DDTHH:MM")
        sp.add_argument("-t", "--tags", help="標籤，用逗號分隔")

    ls = sub.add_parser("ls", help="列出待辦（預設）")
    ls.add_argument("-a", "--all", action="store_true", help="含已完成")
    ls.add_argument("-p", "--project")
    ls.add_argument("--here", action="store_true", help="只看目前 repo")
    ls.add_argument("-q", "--query", help="搜尋")
    views = ls.add_mutually_exclusive_group()
    views.add_argument("--today", dest="view", action="store_const", const="today")
    views.add_argument("--upcoming", dest="view", action="store_const", const="upcoming")

    add = sub.add_parser("add", help="新增待辦")
    add.add_argument("words", nargs="+", metavar="標題")
    add.add_argument("--raw", action="store_true", help="不解析標題中的欄位")
    fields(add, title_flag=False)
    add.set_defaults(title=None, status=None)

    for name, text in (("show", "顯示完整內容"), ("start", "標記進行中"), ("restore", "從回收桶還原")):
        sub.add_parser(name, help=text).add_argument("id", type=int)
    rm = sub.add_parser("rm", help="移到回收桶")
    rm.add_argument("id", type=int)
    rm.add_argument("--purge", action="store_true", help="永久刪除")
    sub.add_parser("trash", help="列出回收桶")
    for name, text, arg in (("done", "標記完成", "摘要"), ("block", "標記卡住", "原因"), ("note", "新增筆記", "文字")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("id", type=int)
        sp.add_argument("text", nargs="*", metavar=arg)
        sp.add_argument("--by", default=os.environ.get("AGENT_TODO_AUTHOR") or "me",
                        help="記錄是誰寫的（例如 claude-code、codex），預設 me")

    edit = sub.add_parser("edit", help="修改欄位")
    edit.add_argument("id", type=int)
    fields(edit, title_flag=True)

    sub.add_parser("mcp", help="以 MCP server 模式執行（給 Claude Code／Codex 用）")
    sub.add_parser("setup", help="顯示接上 Claude Code／Codex 的設定")
    sub.add_parser("path", help="顯示資料檔位置")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            # 輸出被 AI 或其他程式讀取（不是主控台）時用 UTF-8，不然 Windows 預設的 cp950 會變亂碼
            stream.reconfigure(errors="replace", **({} if stream.isatty() else {"encoding": "utf-8"}))
    a = _parser().parse_args(argv)
    try:
        if a.cmd in (None, "ls"):
            _print_list(store.list_todos(status="all" if getattr(a, "all", False) else "open",
                                         project=repo_root() if getattr(a, "here", False) else (getattr(a, "project", None) or ""),
                                         query=getattr(a, "query", None) or "", prefer=repo_root(),
                                         view=getattr(a, "view", None) or ""))
        elif a.cmd == "add":
            title = " ".join(a.words)
            parsed = {"title": title} if a.raw else quickadd.parse(title)
            t = store.add(**{**parsed, **_fields(a)})
            print(f"已新增 #{t['id']} {t['title']}")
        elif a.cmd == "show":
            print(store.format_todo(store.get(a.id)))
        elif a.cmd == "start":
            store.update(a.id, status="doing")
            print(f"#{a.id} → 進行中")
        elif a.cmd == "block":
            store.update(a.id, status="blocked")
            if a.text:
                store.add_note(a.id, "卡住：" + " ".join(a.text), a.by)
            print(f"#{a.id} → 卡住")
        elif a.cmd == "done":
            t = store.complete(a.id, " ".join(a.text), a.by)
            print(f"#{a.id} → 完成")
            if t.get("nextId"):
                next_todo = store.get(t["nextId"])
                print(f"已建立下一次 #{next_todo['id']}（due {next_todo['due']}）")
        elif a.cmd == "note":
            store.add_note(a.id, " ".join(a.text), a.by)
            print(f"#{a.id} 已新增筆記")
        elif a.cmd == "edit":
            print(store.format_todo(store.update(a.id, **_fields(a))))
        elif a.cmd == "rm":
            (store.purge if a.purge else store.remove)(a.id)
            print(f"{'已永久刪除' if a.purge else '已移到回收桶'} #{a.id}")
        elif a.cmd == "trash":
            _print_list(store.list_trash())
        elif a.cmd == "restore":
            store.restore(a.id)
            print(f"已還原 #{a.id}")
        elif a.cmd == "mcp":
            from . import mcp
            mcp.run()
        elif a.cmd == "setup":
            print(_setup_text())
        elif a.cmd == "path":
            print(store.data_file())
    except (store.TodoError, TimeoutError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    return 0
