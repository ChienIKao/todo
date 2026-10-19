"""給 Claude Code／Codex 用的 MCP server：stdio 上一行一則 JSON-RPC 2.0 訊息"""
from __future__ import annotations

import json
import sys

from . import __version__, store

INSTRUCTIONS = """This is the user's personal todo list. Each todo carries a "context" field with the
background the user would otherwise have to re-explain - always read it (get_todo) before working on a task.
- When asked to "do the next task", "看我的待辦", or similar: call list_todos (filter by project if you are inside a repo), pick one, then get_todo.
- When you start a task, set status to "doing". Record meaningful progress, decisions and blockers with add_note.
- When finished, call complete_todo with a short summary of what you did (files, PRs, follow-ups).
- If you discover new work, add it with add_todo including enough context for someone else to pick it up."""

_ID = {"type": "integer", "description": "Todo id"}
_FILTERS = {
    "status": {"type": "string", "enum": ["open", "all", *store.STATUSES],
               "description": 'Default "open" (everything not done)'},
    "project": {"type": "string", "description": "Project name or path; matches by substring"},
    "tag": {"type": "string"},
    "assignee": {"type": "string", "description": 'e.g. "me", "claude", "codex"'},
    "query": {"type": "string", "description": "Full-text search across title, context, notes"},
}
_FIELDS = {
    "title": {"type": "string"},
    "context": {"type": "string", "description": "Background, links, acceptance criteria (markdown)"},
    "priority": {"type": "string", "enum": list(store.PRIORITIES)},
    "project": {"type": "string", "description": "Project name or absolute repo path"},
    "tags": {"type": "array", "items": {"type": "string"}},
    "assignee": {"type": "string"},
    "due": {"type": "string", "description": "YYYY-MM-DD"},
}


def _list(a, author):
    todos = store.list_todos(**{k: a[k] for k in _FILTERS if a.get(k)})
    if not todos:
        return "No matching todos."
    return "\n".join(store.format_todo(t, full=False) + ("  (has context)" if t["context"] else "") for t in todos)


def _update(a, author):
    tid = a.pop("id")
    return "Updated:\n" + store.format_todo(store.update(tid, **a))


TOOLS = [
    ("list_todos", "List the user's todos (titles + metadata, no full context). "
                   "Sorted: doing first, then by priority and due date.",
     {"type": "object", "properties": _FILTERS}, _list),
    ("get_todo", "Get one todo with its full background context and progress notes. "
                 "Read this before working on a task.",
     {"type": "object", "properties": {"id": _ID}, "required": ["id"]},
     lambda a, _: store.format_todo(store.get(a["id"]))),
    ("add_todo", 'Create a new todo. Put all background needed to do it in "context".',
     {"type": "object", "properties": _FIELDS, "required": ["title"]},
     lambda a, _: "Created:\n" + store.format_todo(store.add(**{k: v for k, v in a.items() if k in _FIELDS}))),
    ("update_todo", 'Change fields of a todo (e.g. status "doing"/"blocked", priority, context). '
                    "Omitted fields stay unchanged.",
     {"type": "object", "properties": {"id": _ID, **_FIELDS, "status": {"type": "string", "enum": list(store.STATUSES)}},
      "required": ["id"]}, _update),
    ("add_note", "Append a progress note / decision / blocker to a todo so the next person (or agent) has the history.",
     {"type": "object", "properties": {"id": _ID, "text": {"type": "string"}}, "required": ["id", "text"]},
     lambda a, author: "Noted:\n" + store.format_todo(store.add_note(a["id"], a["text"], author))),
    ("complete_todo", "Mark a todo done, with a short summary of what was done.",
     {"type": "object", "properties": {"id": _ID, "summary": {"type": "string"}}, "required": ["id"]},
     lambda a, author: "Completed:\n" + store.format_todo(store.complete(a["id"], a.get("summary", ""), author))),
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
