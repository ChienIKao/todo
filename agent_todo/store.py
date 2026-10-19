"""待辦資料：~/.agent-todo/todos.json（AGENT_TODO_HOME 可改位置），每次變更同時寫一份 TODO.md 快照

桌面 App、CLI、Claude Code 和 Codex 各自的 MCP server 都是不同程序，會同時讀寫同一個檔案，
所以每次「讀 → 改 → 寫」都用 .lock 檔互斥。
"""
from __future__ import annotations

import calendar
import copy
import json
import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path

STATUSES = ("todo", "doing", "blocked", "done")
PRIORITIES = ("high", "normal", "low")
REPEATS = ("", "daily", "weekdays", "weekly", "monthly", "yearly")
EDITABLE = ("title", "context", "status", "priority", "project", "tags", "assignee", "due",
            "subtasks", "repeat", "remindAt", "order")

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


def _today() -> date:
    return date.today()


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
    for t in db["todos"]:
        for key, value in {"subtasks": [], "repeat": "", "remindAt": "", "remindedAt": "",
                           "order": 0, "deletedAt": ""}.items():
            t.setdefault(key, value)
        t.setdefault("subtaskNextId", max((s["id"] for s in t["subtasks"]), default=0) + 1)
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
    cutoff = datetime.now().astimezone() - timedelta(days=30)
    db["todos"] = [t for t in db["todos"] if not t.get("deletedAt")
                   or datetime.fromisoformat(t["deletedAt"]).astimezone() >= cutoff]
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


def _find(db: dict, tid, include_deleted: bool = False) -> dict:
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        raise TodoError(f"Invalid todo id: {tid!r}") from None
    for t in db["todos"]:
        if t["id"] == tid and (include_deleted or not t.get("deletedAt")):
            return t
    raise TodoError(f"Todo #{tid} not found")


def _check(field: str, value, allowed) -> None:
    if value is not None and value not in allowed:
        raise TodoError(f'Invalid {field} "{value}". Use one of: {", ".join(allowed)}')


def sort_todos(todos: list[dict]) -> list[dict]:
    return sorted(todos, key=lambda t: (_STATUS_RANK[t["status"]], _PRIORITY_RANK[t["priority"]],
                                        t.get("order", 0), t.get("due") or "9999", t["id"]))


def project_matches(todo_project: str, wanted: str) -> bool:
    """"web" 對得到 "~/code/web"；repo 路徑對得到標成該路徑、上層路徑或資料夾名稱的待辦"""
    if not todo_project:
        return False
    a = todo_project.lower().replace("\\", "/").rstrip("/")
    b = wanted.lower().replace("\\", "/").rstrip("/")
    return b in a or b.startswith(a + "/") or a.rsplit("/", 1)[-1] == b.rsplit("/", 1)[-1]


def list_todos(status: str = "open", project: str = "", tag: str = "", assignee: str = "",
               query: str = "", prefer: str = "", view: str = "") -> list[dict]:
    """status："open" = 還沒完成的、"all" = 全部，或指定某個狀態；prefer：這個專案的排前面，其他的照樣列出"""
    _check("view", view, ("", "today", "upcoming"))
    todos = [t for t in _load()["todos"] if not t["deletedAt"]]
    today = _today().isoformat()
    if view:
        todos = [t for t in todos if t["status"] != "done"]
    if view == "today":
        todos = [t for t in todos if t["status"] == "doing" or (t["due"] and t["due"] <= today)
                 or (t["remindAt"] and t["remindAt"][:10] <= today)]
    elif view == "upcoming":
        end = (_today() + timedelta(days=7)).isoformat()
        todos = [t for t in todos if today < t["due"] <= end]
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
    todos = sort_todos(todos)
    if prefer:
        todos.sort(key=lambda t: not project_matches(t["project"], prefer))
    return todos


def _texts(t: dict) -> list[str]:
    return [t["title"], t["context"], t["project"], *t["tags"], *(n["text"] for n in t["notes"])]


def get(tid) -> dict:
    return _find(_load(), tid)


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.replace("，", ",").split(",")
    return [s.strip() for s in tags or [] if s.strip()]


def add(title: str, context: str = "", priority: str = "normal", project: str = "", tags=None,
        assignee: str = "", due: str = "", status: str = "todo", subtasks=None,
        repeat: str = "", remindAt: str = "", order=None) -> dict:
    if not (title or "").strip():
        raise TodoError("title is required")
    _check("priority", priority, PRIORITIES)
    _check("status", status, STATUSES)
    _validate_fields({"repeat": repeat, "remindAt": remindAt, "order": order})
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
            "repeat": repeat, "remindAt": remindAt or "", "remindedAt": "", "deletedAt": "",
            "order": order if order is not None else _last_order(db, status, priority),
        }
        _set_subtasks(todo, subtasks or [])
        db["nextId"] += 1
        db["todos"].append(todo)
    return todo


def _remember_status(todo: dict) -> None:
    """標記完成前記下原本的狀態，取消完成時可以回到進行中／卡住"""
    if todo["status"] != "done":
        todo["reopenStatus"] = todo["status"]


def update(tid, **changes) -> dict:
    changes = {k: v for k, v in changes.items() if k in EDITABLE and v is not None}
    _check("priority", changes.get("priority"), PRIORITIES)
    _check("status", changes.get("status"), STATUSES)
    _validate_fields(changes)
    if "title" in changes and not str(changes["title"]).strip():
        raise TodoError("title is required")
    if "tags" in changes:
        changes["tags"] = _clean_tags(changes["tags"])
    with _mutate() as db:
        todo = _find(db, tid)
        was_done = todo["status"] == "done"
        if "subtasks" in changes:
            _set_subtasks(todo, changes.pop("subtasks"))
        if "remindAt" in changes and changes["remindAt"] != todo["remindAt"]:
            todo["remindedAt"] = ""
        if changes.get("status") == "done":
            _remember_status(todo)
        todo.update(changes)
        if changes.get("status") == "done" and not todo["completedAt"]:
            todo["completedAt"] = _now()
        elif changes.get("status") not in (None, "done"):
            todo["completedAt"] = None
        todo["updatedAt"] = _now()
        next_id = _next_repeat(db, todo) if not was_done and todo["status"] == "done" else None
    return {**todo, "nextId": next_id} if next_id else todo


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
        was_done = todo["status"] == "done"
        if (summary or "").strip():
            todo["notes"].append({"at": _now(), "author": author, "text": f"✅ {summary.strip()}"})
        _remember_status(todo)
        todo["status"] = "done"
        todo["completedAt"] = todo["completedAt"] or _now()
        todo["updatedAt"] = _now()
        next_id = _next_repeat(db, todo) if not was_done else None
    return {**todo, "nextId": next_id} if next_id else todo


def remove(tid) -> dict:
    with _mutate() as db:
        todo = _find(db, tid)
        todo["deletedAt"] = todo["updatedAt"] = _now()
    return todo


def format_todo(t: dict, full: bool = True) -> str:
    meta = [f"status: {t['status']}", f"priority: {t['priority']}"]
    meta += [f"{k}: {t[k]}" for k in ("project", "assignee", "due", "repeat", "remindAt") if t.get(k)]
    if t.get("subtasks"):
        meta.append(f"subtasks {sum(s['done'] for s in t['subtasks'])}/{len(t['subtasks'])}")
    if t["tags"]:
        meta.append(f"tags: {', '.join(t['tags'])}")
    out = f"#{t['id']} {t['title']}\n  {' | '.join(meta)}"
    if not full:
        return out
    if t["context"]:
        out += f"\n\n## Context\n{t['context']}"
    if t.get("subtasks"):
        out += "\n\n## Subtasks"
        for s in t["subtasks"]:
            out += f"\n- [{'x' if s['done'] else ' '}] ({s['id']}) {s['title']}"
    if t["notes"]:
        out += "\n\n## Notes"
        for n in t["notes"]:
            out += f"\n- [{n['at'][:16].replace('T', ' ')}] ({n['author']}) {n['text']}"
    return out


def to_markdown(todos: list[dict]) -> str:
    todos = [t for t in todos if not t.get("deletedAt")]
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
            lines += [f"  - [{'x' if s['done'] else ' '}] {s['title']}" for s in t.get("subtasks", [])]
            lines += [f"  - _{n['at'][:10]} {n['author']}_: {n['text']}" for n in t["notes"]]
        lines.append("")
    done = sorted((t for t in todos if t["status"] == "done"), key=lambda t: t["completedAt"] or "", reverse=True)
    if done:
        lines += ["## 最近完成", ""]
        for t in done[:20]:
            lines.append(f"- [x] #{t['id']} {t['title']}")
            lines += [f"  - [{'x' if s['done'] else ' '}] {s['title']}" for s in t.get("subtasks", [])]
        lines.append("")
    return "\n".join(lines)


def _validate_fields(fields: dict) -> None:
    _check("repeat", fields.get("repeat"), REPEATS)
    if fields.get("remindAt"):
        value = fields["remindAt"]
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
            if parsed.strftime("%Y-%m-%dT%H:%M") != value:
                raise ValueError
        except (ValueError, TypeError):
            raise TodoError("Invalid remindAt: use YYYY-MM-DDTHH:MM") from None
    if fields.get("order") is not None:
        value = fields["order"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TodoError("Invalid order: use a finite number")


def _last_order(db: dict, status: str, priority: str):
    return max((t["order"] for t in db["todos"] if not t["deletedAt"]
                and t["status"] == status and t["priority"] == priority), default=-1) + 1


def _set_subtasks(todo: dict, items) -> None:
    if not isinstance(items, list):
        raise TodoError("subtasks must be a list")
    next_id = max(todo.get("subtaskNextId", 1),
                  max((s["id"] for s in todo.get("subtasks", [])), default=0) + 1)
    explicit = [s["id"] for s in items if isinstance(s, dict) and "id" in s]
    if any(type(sid) is not int or sid < 1 for sid in explicit) or len(set(explicit)) != len(explicit):
        raise TodoError("Invalid or duplicate subtask id")
    next_id = max(next_id, max(explicit, default=0) + 1)
    result = []
    for item in items:
        s = {"title": item} if isinstance(item, str) else item
        if not isinstance(s, dict) or not isinstance(s.get("title"), str) or not s["title"].strip():
            raise TodoError("subtask title is required")
        if not isinstance(s.get("done", False), bool):
            raise TodoError("subtask done must be a boolean")
        sid = s.get("id")
        if sid is None:
            sid, next_id = next_id, next_id + 1
        result.append({"id": sid, "title": s["title"].strip(), "done": s.get("done", False)})
    todo["subtasks"], todo["subtaskNextId"] = result, next_id


def add_subtask(tid, title: str) -> dict:
    with _mutate() as db:
        todo = _find(db, tid)
        _set_subtasks(todo, [*todo["subtasks"], title])
        todo["updatedAt"] = _now()
    return todo


def _subtask(todo: dict, sid) -> dict:
    try:
        return next(s for s in todo["subtasks"] if s["id"] == int(sid))
    except (StopIteration, TypeError, ValueError):
        raise TodoError(f"Subtask #{sid} not found") from None


def toggle_subtask(tid, sid, done=None) -> dict:
    if done is not None and not isinstance(done, bool):
        raise TodoError("subtask done must be a boolean")
    with _mutate() as db:
        todo = _find(db, tid)
        s = _subtask(todo, sid)
        s["done"] = not s["done"] if done is None else done
        todo["updatedAt"] = _now()
    return todo


def remove_subtask(tid, sid) -> dict:
    with _mutate() as db:
        todo = _find(db, tid)
        todo["subtasks"].remove(_subtask(todo, sid))
        todo["updatedAt"] = _now()
    return todo


def _next_repeat(db: dict, todo: dict):
    rule = todo["repeat"]
    if not rule:
        return None
    try:
        base = date.fromisoformat(todo["due"]) if todo["due"] else _today()
    except ValueError:
        raise TodoError("Invalid due: use YYYY-MM-DD for repeating todos") from None
    due, step = base, 0
    # 至少往後推一次；拖了很久才完成就一直推到今天之後
    while step == 0 or due <= _today():
        step += 1
        if rule in ("daily", "weekdays", "weekly"):
            due += timedelta(days=7 if rule == "weekly" else 1)
            while rule == "weekdays" and due.weekday() >= 5:
                due += timedelta(days=1)
        else:
            months = base.month - 1 + step * (12 if rule == "yearly" else 1)
            year, month = base.year + months // 12, months % 12 + 1
            due = date(year, month, min(base.day, calendar.monthrange(year, month)[1]))
    new = copy.deepcopy(todo)
    ts = _now()
    new.update(id=db["nextId"], status="todo", due=due.isoformat(), notes=[], createdAt=ts,
               updatedAt=ts, completedAt=None, remindedAt="", deletedAt="",
               order=_last_order(db, "todo", todo["priority"]))
    new.pop("reopenStatus", None)
    if new["remindAt"]:
        reminder_date = date.fromisoformat(new["remindAt"][:10]) + (due - base)
        new["remindAt"] = reminder_date.isoformat() + new["remindAt"][10:]
    for s in new["subtasks"]:
        s["done"] = False
    db["nextId"] += 1
    db["todos"].append(new)
    return new["id"]


def due_reminders(now: datetime | None = None) -> list[dict]:
    current = (now or datetime.now()).strftime("%Y-%m-%dT%H:%M")
    return [t for t in list_todos() if t["remindAt"] and t["remindAt"] <= current and not t["remindedAt"]]


def mark_reminded(tid) -> dict:
    with _mutate() as db:
        todo = _find(db, tid)
        todo["remindedAt"] = todo["updatedAt"] = _now()
    return todo


def reorder(ids: list[int]) -> list[dict]:
    with _mutate() as db:
        todos = [_find(db, tid) for tid in ids]
        for order, todo in enumerate(todos):
            todo["order"] = order
            todo["updatedAt"] = _now()
    return todos


def list_trash() -> list[dict]:
    return sort_todos([t for t in _load()["todos"] if t["deletedAt"]])


def restore(tid) -> dict:
    with _mutate() as db:
        todo = _find(db, tid, include_deleted=True)
        todo["deletedAt"] = ""
        todo["updatedAt"] = _now()
    return todo


def purge(tid) -> dict:
    with _mutate() as db:
        todo = _find(db, tid, include_deleted=True)
        db["todos"].remove(todo)
    return todo
