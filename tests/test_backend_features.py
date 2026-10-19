import json
from datetime import date, datetime, timedelta

import pytest

from agent_todo import store


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TODO_HOME", str(tmp_path))


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(store, "_today", lambda: date(2024, 1, 1))


def test_subtask_lifecycle_and_formats():
    t = store.add("work", subtasks=["first", {"title": "second", "done": True}])
    assert [s["id"] for s in t["subtasks"]] == [1, 2]
    assert "subtasks 1/2" in store.format_todo(t, full=False)
    assert "- [x] (2) second" in store.format_todo(t)
    assert "- [x] second" in store.markdown_file().read_text(encoding="utf-8")
    store.toggle_subtask(1, 1)
    assert store.get(1)["subtasks"][0]["done"]
    store.toggle_subtask(1, 1, False)
    store.remove_subtask(1, 2)
    store.add_subtask(1, "third")
    assert store.get(1)["subtasks"][-1]["id"] == 3
    t = store.update(1, subtasks=[{"id": 1, "title": "renamed"}, "fourth"])
    assert [s["id"] for s in t["subtasks"]] == [1, 4]
    with pytest.raises(store.TodoError):
        store.toggle_subtask(1, 99)
    with pytest.raises(store.TodoError):
        store.update(1, subtasks=[{"id": 1, "title": "a"}, {"id": 1, "title": "b"}])
    assert store.get(1)["subtasks"] == t["subtasks"]


@pytest.mark.parametrize("rule,due,expected", [
    ("daily", "2026-10-19", "2026-10-20"),
    ("weekdays", "2026-10-23", "2026-10-26"),
    ("weekdays", "2026-10-24", "2026-10-26"),
    ("weekdays", "2026-10-19", "2026-10-20"),
    ("weekly", "2026-10-19", "2026-10-26"),
    ("monthly", "2026-01-31", "2026-02-28"),
    ("monthly", "2028-01-31", "2028-02-29"),
    ("monthly", "2026-12-31", "2027-01-31"),
    ("yearly", "2024-02-29", "2025-02-28"),
    ("yearly", "2026-10-19", "2027-10-19"),
])
@pytest.mark.parametrize("method", ["complete", "update"])
def test_repeats(rule, due, expected, method, frozen_today):
    original = store.add("work", context="context", priority="high", project="project", tags=["tag"],
                         assignee="codex", due=due, repeat=rule, remindAt=due + "T15:30",
                         subtasks=[{"title": "step", "done": True}], status="doing")
    store.add_note(1, "progress")
    store.mark_reminded(1)
    finish = lambda: store.complete(1, "summary") if method == "complete" else store.update(1, status="done")
    t = finish()
    assert t["nextId"] == 2
    assert "nextId" not in store.get(1)
    following = store.get(2)
    for key in ("title", "context", "priority", "project", "tags", "assignee", "repeat"):
        assert following[key] == original[key]
    assert following["due"] == expected
    assert following["remindAt"] == expected + "T15:30"
    assert following["status"] == "todo"
    assert following["notes"] == []
    assert following["subtasks"] == [{"id": 1, "title": "step", "done": False}]
    assert following["completedAt"] is None
    assert following["remindedAt"] == ""
    finish()
    assert len(store.list_todos(status="all")) == 2


def test_repeat_without_due_and_nonrepeat():
    store.add("daily", repeat="daily")
    t = store.complete(1)
    assert store.get(t["nextId"])["due"] == (date.today() + timedelta(days=1)).isoformat()
    store.add("once")
    assert "nextId" not in store.complete(3)


def test_repeat_preserves_early_reminder(frozen_today):
    store.add("monthly", due="2026-01-31", repeat="monthly", remindAt="2026-01-30T09:00")
    store.complete(1)
    assert store.get(2)["due"] == "2026-02-28"
    assert store.get(2)["remindAt"] == "2026-02-27T09:00"


@pytest.mark.parametrize("rule,due,expected", [
    ("daily", "2023-12-20", "2024-01-02"),
    ("weekly", "2023-12-04", "2024-01-08"),
    ("weekdays", "2023-12-29", "2024-01-02"),
    ("monthly", "2023-10-31", "2024-01-31"),
])
def test_overdue_repeat_jumps_past_today(rule, due, expected, frozen_today):
    store.add("late", due=due, repeat=rule, remindAt=due + "T09:00")
    store.complete(1)
    assert store.get(2)["due"] == expected
    assert store.get(2)["remindAt"] == expected + "T09:00"


def test_reminders():
    store.add("reminder", remindAt="2026-10-19T15:00")
    store.add("future", remindAt="2026-10-20T15:00")
    store.add("done", remindAt="2026-10-19T15:00", status="done")
    store.add("deleted", remindAt="2026-10-19T15:00")
    store.remove(4)
    now = datetime(2026, 10, 19, 15)
    assert [t["id"] for t in store.due_reminders(now)] == [1]
    store.mark_reminded(1)
    assert store.due_reminders(now) == []
    store.update(1, remindAt="2026-10-19T15:00")
    assert store.due_reminders(now) == []
    store.update(1, remindAt="2026-10-19T14:00")
    assert [t["id"] for t in store.due_reminders(now)] == [1]
    store.update(1, remindAt="")
    assert store.due_reminders(now) == []
    with pytest.raises(store.TodoError):
        store.add("invalid", remindAt="2026-13-01T12:00")
    with pytest.raises(store.TodoError):
        store.update(1, repeat="hourly")


def test_views():
    today = date.today()
    day = lambda n: (today + timedelta(days=n)).isoformat()
    for title, fields in [
        ("overdue", {"due": day(-1)}), ("today", {"due": day(0)}),
        ("doing", {"status": "doing"}), ("reminder", {"remindAt": day(0) + "T23:59"}),
        ("tomorrow", {"due": day(1)}), ("week", {"due": day(7)}),
        ("later", {"due": day(8)}), ("none", {}),
        ("done", {"due": day(0), "status": "done"}), ("deleted", {"due": day(1)})]:
        store.add(title, **fields)
    store.remove(10)
    assert {t["title"] for t in store.list_todos(status="all", view="today")} == {"overdue", "today", "doing", "reminder"}
    assert {t["title"] for t in store.list_todos(view="upcoming")} == {"tomorrow", "week"}


def test_manual_order():
    store.add("a", due="2026-10-25")
    store.add("b", due="2026-10-20")
    store.add("c", priority="high")
    store.add("d", status="doing", priority="low")
    assert [t["id"] for t in store.list_todos()] == [4, 3, 1, 2]
    store.reorder([2, 1])
    assert [t["id"] for t in store.list_todos()] == [4, 3, 2, 1]
    assert store.add("e")["order"] == 2
    with pytest.raises(store.TodoError):
        store.reorder([1, 99])
    assert store.get(1)["order"] == 1


def test_trash_and_retention():
    store.add("hidden", subtasks=["step"])
    store.remove(1)
    with pytest.raises(store.TodoError, match="not found"):
        store.get(1)
    assert store.list_todos(status="all") == []
    assert "hidden" not in store.to_markdown(store._load()["todos"])
    assert store.list_trash()[0]["id"] == 1
    store.restore(1)
    assert store.get(1)["subtasks"][0]["title"] == "step"
    store.remove(1)
    db = store._load()
    db["todos"][0]["deletedAt"] = (datetime.now().astimezone() - timedelta(days=31)).isoformat()
    store.data_file().write_text(json.dumps(db), encoding="utf-8")
    store.add("recent")
    assert store.list_trash() == []
    assert [t["id"] for t in store._load()["todos"]] == [2]
    store.remove(2)
    store.add("trigger")
    assert len(store.list_trash()) == 1
    store.purge(2)
    with pytest.raises(store.TodoError):
        store.restore(2)


def test_old_format():
    t = store.add("legacy")
    for key in ("subtasks", "subtaskNextId", "repeat", "remindAt", "remindedAt", "order", "deletedAt"):
        t.pop(key)
    store.data_file().write_text(json.dumps({"todos": [t]}), encoding="utf-8")
    loaded = store.get(1)
    assert loaded["subtasks"] == []
    assert loaded["repeat"] == loaded["remindAt"] == loaded["remindedAt"] == loaded["deletedAt"] == ""
    assert loaded["order"] == 0
    assert store.add_subtask(1, "new")["subtasks"][0]["id"] == 1
    assert store.add("next")["id"] == 2
