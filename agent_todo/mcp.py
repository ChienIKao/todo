"""給 Claude Code／Codex 用的 MCP server：stdio 上一行一則 JSON-RPC 2.0 訊息"""
from __future__ import annotations

import json
import sys

from . import __version__, store

INSTRUCTIONS = """This is the user's personal todo list. Each todo carries a "context" field with the
background the user would otherwise have to re-explain - always read it (get_todo) before working on a task.
- When asked to "do the next task", "看我的待辦", or similar: call list_todos with current_repo set to your working directory
  (todos for that repo come first, the rest are still listed), pick one, then get_todo. Only filter with project when the user asks for this repo's todos.
- When you start a task, set status to "doing". Record meaningful progress, decisions and blockers with add_note.
- For large tasks, break the work into subtasks first and check off each step with check_subtask as you finish it.
- When finished, call complete_todo with a short summary of what you did (files, PRs, follow-ups).
- If you discover new work, add it with add_todo including enough context for someone else to pick it up."""

_ID = {"type": "integer", "description": "Todo id"}
_FILTERS = {
    "view": {"type": "string", "enum": ["today", "upcoming"]},
    "status": {"type": "string", "enum": ["open", "all", *store.STATUSES],
               "description": 'Default "open" (everything not done)'},
    "project": {"type": "string", "description": "Only todos of this project (name or path). Use only when the user asks for one project"},
    "current_repo": {"type": "string", "description": "Your working directory; its todos are listed first, others still shown"},
    "tag": {"type": "string"},
    "assignee": {"type": "string", "description": 'e.g. "me", "claude", "codex"'},
    "query": {"type": "string", "description": "Full-text search across title, context, notes"},
}
_FIELDS = {
    "repeat": {"type": "string", "enum": list(store.REPEATS)},
    "remind_at": {"type": "string", "description": "Local time YYYY-MM-DDTHH:MM, or empty"},
    "subtasks": {"type": "array", "items": {"anyOf": [
        {"type": "string"}, {"type": "object", "properties": {
            "id": {"type": "integer"}, "title": {"type": "string"}, "done": {"type": "boolean"}},
            "required": ["title"]}]}},
    "title": {"type": "string"},
    "context": {"type": "string", "description": "Background, links, acceptance criteria (markdown)"},
    "priority": {"type": "string", "enum": list(store.PRIORITIES)},
    "project": {"type": "string", "description": "Project name or absolute repo path"},
    "tags": {"type": "array", "items": {"type": "string"}},
    "assignee": {"type": "string"},
    "due": {"type": "string", "description": "YYYY-MM-DD"},
}


def _list(a, author):
    here = a.get("current_repo") or ""
    todos = store.list_todos(**{k: a[k] for k in _FILTERS if a.get(k) and k != "current_repo"}, prefer=here)
    if not todos:
        return "No matching todos."
    return "\n".join(store.format_todo(t, full=False) + ("  (has context)" if t["context"] else "")
                     + ("  (this repo)" if here and store.project_matches(t["project"], here) else "") for t in todos)


def _update(a, author):
    tid = a.pop("id")
    return "Updated:\n" + _result(store.update(tid, **_fields(a)))


def _fields(a):
    return {"remindAt" if k == "remind_at" else k: v for k, v in a.items()}


def _result(todo):
    text = store.format_todo(todo)
    if todo.get("nextId"):
        next_todo = store.get(todo["nextId"])
        text += f"\n已建立下一次 #{next_todo['id']}（due {next_todo['due']}）"
    return text


TOOLS = [
    ("list_todos", "List the user's todos (titles + metadata, no full context). "
                   "Sorted by status, priority, manual order, due date and id.",
     {"type": "object", "properties": _FILTERS}, _list),
    ("get_todo", "Get one todo with its full background context and progress notes. "
                 "Read this before working on a task.",
     {"type": "object", "properties": {"id": _ID}, "required": ["id"]},
     lambda a, _: store.format_todo(store.get(a["id"]))),
    ("add_todo", 'Create a new todo. Put all background needed to do it in "context".',
     {"type": "object", "properties": _FIELDS, "required": ["title"]},
     lambda a, _: "Created:\n" + store.format_todo(store.add(**_fields({k: v for k, v in a.items() if k in _FIELDS})))),
    ("update_todo", 'Change fields of a todo (e.g. status "doing"/"blocked", priority, context). '
                    "Omitted fields stay unchanged.",
     {"type": "object", "properties": {"id": _ID, **_FIELDS, "status": {"type": "string", "enum": list(store.STATUSES)}},
      "required": ["id"]}, _update),
    ("add_note", "Append a progress note / decision / blocker to a todo so the next person (or agent) has the history.",
     {"type": "object", "properties": {"id": _ID, "text": {"type": "string"}}, "required": ["id", "text"]},
     lambda a, author: "Noted:\n" + store.format_todo(store.add_note(a["id"], a["text"], author))),
    ("complete_todo", "Mark a todo done, with a short summary of what was done.",
     {"type": "object", "properties": {"id": _ID, "summary": {"type": "string"}}, "required": ["id"]},
     lambda a, author: "Completed:\n" + _result(store.complete(a["id"], a.get("summary", ""), author))),
    ("check_subtask", "Check off a completed step of a todo.",
     {"type": "object", "properties": {"id": _ID, "subtask_id": {"type": "integer"},
      "done": {"type": "boolean", "default": True}}, "required": ["id", "subtask_id"]},
     lambda a, _: store.format_todo(store.toggle_subtask(a["id"], a["subtask_id"], a.get("done", True)))),
]


class Handler:
    def __init__(self):
        self.author = "agent"  # initialize 時換成 client 的名稱（claude-code、codex-mcp-client…）

    def __call__(self, msg: dict) -> dict | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}

        def reply(result):
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        def fail(code, message):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

        if method == "initialize":
            self.author = (params.get("clientInfo") or {}).get("name") or self.author
            return reply({"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "agent-todo", "version": __version__},
                          "instructions": INSTRUCTIONS})
        if method == "ping":
            return reply({})
        if method == "tools/list":
            return reply({"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]})
        if method == "tools/call":
            tool = next((t for t in TOOLS if t[0] == params.get("name")), None)
            if not tool:
                return fail(-32602, f"Unknown tool: {params.get('name')}")
            try:
                text = tool[3](dict(params.get("arguments") or {}), self.author)
            except (store.TodoError, TimeoutError, KeyError, TypeError) as e:
                return reply({"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
            return reply({"content": [{"type": "text", "text": text}]})
        if mid is None:  # notification
            return None
        return fail(-32601, f"Method not found: {method}")


def run() -> None:
    handle = Handler()
    out = sys.stdout.buffer
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            res = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            res = handle(msg)
        if res:
            out.write(json.dumps(res, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()
