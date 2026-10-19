"""待辦資料：~/.agent-todo/todos.json（AGENT_TODO_HOME 可改位置），每次變更同時寫一份 TODO.md 快照

桌面 App、CLI、Claude Code 和 Codex 各自的 MCP server 都是不同程序，會同時讀寫同一個檔案，
所以每次「讀 → 改 → 寫」都用 .lock 檔互斥。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

STATUSES = ("todo", "doing", "blocked", "done")
PRIORITIES = ("high", "normal", "low")
EDITABLE = ("title", "context", "status", "priority", "project", "tags", "assignee", "due")

_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}
_STATUS_RANK = {"doing": 0, "todo": 1, "blocked": 2, "done": 3}


class TodoError(ValueError):
    pass


def data_dir() -> Path:
    return Path(os.environ.get("AGENT_TODO_HOME") or Path.home() / ".agent-todo")


def data_file() -> Path:
    return data_dir() / "todos.json"


def markdown_file() -> Path:
    return data_dir() / "TODO.md"


def version() -> float:
    """資料檔最後修改時間，介面用來判斷要不要重新載入"""
    try:
        return data_file().stat().st_mtime
    except FileNotFoundError:
        return 0


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load() -> dict:
    try:
        db = json.loads(data_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "nextId": 1, "todos": []}
    db.setdefault("todos", [])
    db.setdefault("nextId", max((t["id"] for t in db["todos"]), default=0) + 1)
    return db


def _replace(src: Path, dst: Path) -> None:
    # Windows 上其他程序正在讀檔時 os.replace 會失敗，稍等再試
    for attempt in range(50):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.02)


def _save(db: dict) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    tmp = data_file().with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _replace(tmp, data_file())
    md = markdown_file().with_suffix(f".{os.getpid()}.tmp")
    md.write_text(to_markdown(db["todos"]), encoding="utf-8")
    _replace(md, markdown_file())


@contextmanager
def _locked():
    data_dir().mkdir(parents=True, exist_ok=True)
    lock = data_dir() / ".lock"
    deadline = time.monotonic() + 5
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 10:  # 上一個程序寫到一半被關掉
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"無法取得 {lock}") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _mutate():
    with _locked():
        db = _load()
        yield db
        _save(db)


def _find(db: dict, tid) -> dict:
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        raise TodoError(f"Invalid todo id: {tid!r}") from None
    for t in db["todos"]:
        if t["id"] == tid:
            return t
    raise TodoError(f"Todo #{tid} not found")


def _check(field: str, value, allowed) -> None:
    if value is not None and value not in allowed:
        raise TodoError(f'Invalid {field} "{value}". Use one of: {", ".join(allowed)}')


def sort_todos(todos: list[dict]) -> list[dict]:
    return sorted(todos, key=lambda t: (_STATUS_RANK[t["status"]], _PRIORITY_RANK[t["priority"]],
                                        t.get("due") or "9999", t["id"]))


def project_matches(todo_project: str, wanted: str) -> bool:
    """"web" 對得到 "~/code/web"；repo 路徑對得到標成該路徑、上層路徑或資料夾名稱的待辦"""
    if not todo_project:
        return False
    a = todo_project.lower().replace("\\", "/").rstrip("/")
    b = wanted.lower().replace("\\", "/").rstrip("/")
    return b in a or b.startswith(a + "/") or a.rsplit("/", 1)[-1] == b.rsplit("/", 1)[-1]


def list_todos(status: str = "open", project: str = "", tag: str = "", assignee: str = "",
               query: str = "") -> list[dict]:
    """status："open" = 還沒完成的、"all" = 全部，或指定某個狀態"""
    todos = _load()["todos"]
    if status == "open":
        todos = [t for t in todos if t["status"] != "done"]
    elif status != "all":
        todos = [t for t in todos if t["status"] == status]
    if project:
        todos = [t for t in todos if project_matches(t["project"], project)]
    if tag:
        todos = [t for t in todos if tag in t["tags"]]
    if assignee:
        todos = [t for t in todos if t["assignee"] == assignee]
    if query:
        q = query.lower()
        todos = [t for t in todos if any(q in s.lower() for s in _texts(t))]
    return sort_todos(todos)


def _texts(t: dict) -> list[str]:
    return [t["title"], t["context"], t["project"], *t["tags"], *(n["text"] for n in t["notes"])]


def get(tid) -> dict:
    return _find(_load(), tid)


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.replace("，", ",").split(",")
    return [s.strip() for s in tags or [] if s.strip()]


def add(title: str, context: str = "", priority: str = "normal", project: str = "", tags=None,
        assignee: str = "", due: str = "", status: str = "todo") -> dict:
    if not (title or "").strip():
        raise TodoError("title is required")
    _check("priority", priority, PRIORITIES)
    _check("status", status, STATUSES)
    with _mutate() as db:
        ts = _now()
        todo = {
            "id": db["nextId"],
            "title": title.strip(),
            "context": (context or "").strip(),
            "status": status,
            "priority": priority,
            "project": (project or "").strip(),
            "tags": _clean_tags(tags),
            "assignee": (assignee or "").strip(),
            "due": due or "",
            "notes": [],
            "createdAt": ts,
            "updatedAt": ts,
            "completedAt": ts if status == "done" else None,
        }
        db["nextId"] += 1
        db["todos"].append(todo)
    return todo


def update(tid, **changes) -> dict:
    changes = {k: v for k, v in changes.items() if k in EDITABLE and v is not None}
    _check("priority", changes.get("priority"), PRIORITIES)
    _check("status", changes.get("status"), STATUSES)
    if "title" in changes and not str(changes["title"]).strip():
        raise TodoError("title is required")
    if "tags" in changes:
        changes["tags"] = _clean_tags(changes["tags"])
    with _mutate() as db:
        todo = _find(db, tid)
        todo.update(changes)
        if changes.get("status") == "done" and not todo["completedAt"]:
            todo["completedAt"] = _now()
        elif changes.get("status") not in (None, "done"):
            todo["completedAt"] = None
        todo["updatedAt"] = _now()
    return todo


def add_note(tid, text: str, author: str = "me") -> dict:
    if not (text or "").strip():
        raise TodoError("note text is required")
    with _mutate() as db:
        todo = _find(db, tid)
        todo["notes"].append({"at": _now(), "author": author, "text": text.strip()})
        todo["updatedAt"] = _now()
    return todo


def complete(tid, summary: str = "", author: str = "me") -> dict:
    with _mutate() as db:
        todo = _find(db, tid)
        if (summary or "").strip():
            todo["notes"].append({"at": _now(), "author": author, "text": f"✅ {summary.strip()}"})
        todo["status"] = "done"
        todo["completedAt"] = todo["completedAt"] or _now()
        todo["updatedAt"] = _now()
    return todo


def remove(tid) -> dict:
    with _mutate() as db:
        todo = _find(db, tid)
        db["todos"].remove(todo)
    return todo


def format_todo(t: dict, full: bool = True) -> str:
    meta = [f"status: {t['status']}", f"priority: {t['priority']}"]
    meta += [f"{k}: {t[k]}" for k in ("project", "assignee", "due") if t[k]]
    if t["tags"]:
        meta.append(f"tags: {', '.join(t['tags'])}")
    out = f"#{t['id']} {t['title']}\n  {' | '.join(meta)}"
    if not full:
        return out
    if t["context"]:
        out += f"\n\n## Context\n{t['context']}"
    if t["notes"]:
        out += "\n\n## Notes"
        for n in t["notes"]:
            out += f"\n- [{n['at'][:16].replace('T', ' ')}] ({n['author']}) {n['text']}"
    return out


def to_markdown(todos: list[dict]) -> str:
    lines = ["# TODO", "", "> 由 Agent Todo 自動產生，請勿手動編輯。用 App、`todo` 指令或 MCP 工具修改。", ""]
    ordered = sort_todos(todos)
    for status, label in (("doing", "進行中"), ("todo", "待辦"), ("blocked", "卡住")):
        items = [t for t in ordered if t["status"] == status]
        if not items:
            continue
        lines += [f"## {label}", ""]
        for t in items:
            meta = " · ".join(x for x in (t["priority"] if t["priority"] != "normal" else "", t["project"],
                                          f"due {t['due']}" if t["due"] else "",
                                          f"@{t['assignee']}" if t["assignee"] else "") if x)
            lines.append(f"- [ ] **#{t['id']} {t['title']}**" + (f" — {meta}" if meta else ""))
            lines += [f"  > {line}" for line in t["context"].splitlines()]
            lines += [f"  - _{n['at'][:10]} {n['author']}_: {n['text']}" for n in t["notes"]]
        lines.append("")
    done = sorted((t for t in todos if t["status"] == "done"), key=lambda t: t["completedAt"] or "", reverse=True)
    if done:
        lines += ["## 最近完成", ""]
        lines += [f"- [x] #{t['id']} {t['title']}" for t in done[:20]]
        lines.append("")
    return "\n".join(lines)
