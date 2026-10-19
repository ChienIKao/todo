from datetime import date, timedelta

import pytest

from agent_todo import cli, integrations, mcp, store
from agent_todo.api import Api


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TODO_HOME", str(tmp_path))


def test_mcp_fields_and_subtasks():
    handler = mcp.Handler()

    def call(name, args):
        return handler({"id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]

    schemas = {name: schema for name, _, schema, _ in mcp.TOOLS}
    for name in ("add_todo", "update_todo"):
        assert {"subtasks", "repeat", "remind_at"} <= schemas[name]["properties"].keys()
    assert schemas["list_todos"]["properties"]["view"]["enum"] == ["today", "upcoming"]
    assert schemas["check_subtask"]["properties"]["done"]["default"] is True
    assert "subtasks" in mcp.INSTRUCTIONS and "check_subtask" in integrations.INSTRUCTIONS
    call("add_todo", {"title": "work", "subtasks": ["first", {"title": "second", "done": True}],
                      "repeat": "daily", "due": "2099-01-01", "remind_at": "2099-01-01T15:00"})
    assert "- [x] (1) first" in call("check_subtask", {"id": 1, "subtask_id": 1})["content"][0]["text"]
    call("check_subtask", {"id": 1, "subtask_id": 2, "done": False})
    assert not store.get(1)["subtasks"][1]["done"]
    call("update_todo", {"id": 1, "subtasks": [{"id": 1, "title": "renamed"}],
                         "remind_at": "2099-01-01T16:00"})
    assert store.get(1)["remindAt"] == "2099-01-01T16:00"
    completed = call("complete_todo", {"id": 1})
    assert "已建立下一次 #2（due 2099-01-02）" in completed["content"][0]["text"]
    assert store.get(2)["subtasks"][0]["title"] == "renamed"
    assert call("check_subtask", {"id": 1, "subtask_id": 99})["isError"]
    store.add("today", due=date.today().isoformat())
    listed = call("list_todos", {"view": "today"})["content"][0]["text"]
    assert "#3 today" in listed and "#1 work" not in listed


def test_api():
    api = Api()
    parsed = api.parse_quick("明天 工作 #測試")
    assert parsed["title"] == "工作" and parsed["tags"] == ["測試"]
    t = api.add_todo({"title": "work", "repeat": "daily", "subtasks": ["step"],
                      "remindAt": "2000-01-01T09:00", "order": 7})
    assert t["order"] == 7
    api.add_subtask(1, "second")
    api.toggle_subtask(1, 1, True)
    api.remove_subtask(1, 2)
    assert api.list_todos()[0]["subtasks"][0]["done"]
    assert api.due_reminders()[0]["id"] == 1
    api.mark_reminded(1)
    assert api.due_reminders() == []
    api.reorder([1])
    assert store.get(1)["order"] == 0
    api.delete_todo(1)
    assert api.list_todos() == []
    assert api.list_trash()[0]["id"] == 1
    api.restore_todo(1)
    assert api.list_todos()[0]["id"] == 1
    api.purge_todo(1)
    assert api.list_todos() == []


def test_cli(capsys):
    assert cli.main(["add", "明天 下午3點 工作 !高 #甲 +project @codex", "--low", "--due", "2026-12-01",
                     "--assign", "me", "--tags", "乙", "--project", "explicit",
                     "--repeat", "weekly", "--remind-at", "2026-12-01T09:00"]) == 0
    t = store.get(1)
    assert t["title"] == "工作" and t["priority"] == "low"
    assert (t["due"], t["assignee"], t["tags"], t["project"], t["repeat"], t["remindAt"]) == (
        "2026-12-01", "me", ["乙"], "explicit", "weekly", "2026-12-01T09:00")
    assert cli.main(["add", "--raw", "明天 工作 !!"]) == 0
    assert store.get(2)["title"] == "明天 工作 !!" and not store.get(2)["due"]
    store.add("today", due=date.today().isoformat())
    store.add("upcoming", due=(date.today() + timedelta(days=7)).isoformat())
    capsys.readouterr()
    assert cli.main(["ls", "--today"]) == 0
    output = capsys.readouterr().out
    assert "today" in output and "upcoming" not in output
    assert cli.main(["ls", "--upcoming"]) == 0
    output = capsys.readouterr().out
    assert "upcoming" in output and "today" not in output
    assert cli.main(["rm", "2"]) == 0
    assert cli.main(["trash"]) == 0
    assert "明天 工作 !!" in capsys.readouterr().out
    assert cli.main(["restore", "2"]) == 0
    assert store.get(2)["title"] == "明天 工作 !!"
    assert cli.main(["rm", "--purge", "2"]) == 0
    assert cli.main(["show", "2"]) == 1


def test_cli_progress_text(capsys):
    store.add("work", context="background")
    assert cli.main(["block", "1", "等待回覆"]) == 0
    assert store.get(1)["notes"][-1]["text"] == "卡住：等待回覆"
    capsys.readouterr()
    assert cli.main(["ls"]) == 0
    output = capsys.readouterr().out
    assert "背景" in output and "筆記 1" in output
    assert cli.main(["done", "1", "已確認"]) == 0
    assert capsys.readouterr().out.strip() == "#1 → 完成"
    assert store.get(1)["notes"][-1]["text"] == "完成：已確認"
