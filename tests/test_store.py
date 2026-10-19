import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from agent_todo import store


class StoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"AGENT_TODO_HOME": temp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_lifecycle(self):
        t = store.add(" Fix login ", context="OAuth callback 500s", project="/home/me/web", priority="high")
        self.assertEqual((t["id"], t["title"], t["status"]), (1, "Fix login", "todo"))
        store.update(t["id"], status="doing")
        store.add_note(t["id"], "Found it: missing redirect URI", "claude-code")
        done = store.complete(t["id"], "Added redirect URI", "claude-code")
        self.assertEqual(done["status"], "done")
        self.assertTrue(done["completedAt"])
        self.assertEqual(done["notes"][-1]["text"], "完成：Added redirect URI")
        self.assertEqual([n["author"] for n in done["notes"]], ["claude-code", "claude-code"])
        self.assertEqual(store.list_todos(), [])
        self.assertEqual(len(store.list_todos(status="all")), 1)
        store.update(t["id"], status="todo")
        self.assertIsNone(store.get(t["id"])["completedAt"])

    def test_sort_doing_first_then_priority(self):
        store.add("low", priority="low")
        store.add("high", priority="high")
        doing = store.add("doing")
        store.update(doing["id"], status="doing")
        self.assertEqual([t["title"] for t in store.list_todos()], ["doing", "high", "low"])

    def test_project_filter(self):
        store.add("a", project="web")
        store.add("b", project="/home/me/code/web")
        store.add("c", project="api")
        store.add("d", project="C:\\Users\\me\\code\\web")
        titles = lambda p: [t["title"] for t in store.list_todos(project=p)]  # noqa: E731
        self.assertEqual(titles("/home/me/code/web"), ["a", "b", "d"])
        self.assertEqual(titles("/home/me/code/web/src"), ["b"])
        self.assertEqual(titles("api"), ["c"])

    def test_prefer_lists_project_first_without_hiding_others(self):
        store.add("general", priority="high")
        store.add("other", project="api")
        store.add("mine", project="web")
        titles = [t["title"] for t in store.list_todos(prefer="/home/me/code/web")]
        self.assertEqual(titles, ["mine", "general", "other"])

    def test_reopen_restores_status_before_done(self):
        t = store.add("x")
        store.update(t["id"], status="blocked")
        store.update(t["id"], status="done")
        self.assertEqual(store.get(t["id"])["reopenStatus"], "blocked")
        store.update(t["id"], status="doing")
        store.complete(t["id"])
        store.complete(t["id"])  # 重複完成不會蓋掉
        self.assertEqual(store.get(t["id"])["reopenStatus"], "doing")

    def test_search_and_tags(self):
        store.add("x", context="needs the staging url", tags="ops, 上線")
        store.add("y")
        self.assertEqual([t["title"] for t in store.list_todos(query="STAGING")], ["x"])
        self.assertEqual([t["title"] for t in store.list_todos(tag="上線")], ["x"])

    def test_validation(self):
        with self.assertRaisesRegex(store.TodoError, "title is required"):
            store.add("  ")
        with self.assertRaisesRegex(store.TodoError, "Invalid priority"):
            store.add("x", priority="urgent")
        with self.assertRaisesRegex(store.TodoError, "not found"):
            store.get(99)
        with self.assertRaisesRegex(store.TodoError, "Invalid todo id"):
            store.get("abc")

    def test_markdown_snapshot(self):
        store.add("Ship it", context="line one\nline two", priority="high")
        md = store.markdown_file().read_text(encoding="utf-8")
        self.assertIn("**#1 Ship it**", md)
        self.assertIn("> line two", md)

    def test_concurrent_adds_keep_every_todo(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: store.add(f"t{i}"), range(40)))
        ids = sorted(t["id"] for t in store.list_todos())
        self.assertEqual(ids, list(range(1, 41)))
        self.assertFalse((Path(os.environ["AGENT_TODO_HOME"]) / ".lock").exists())


if __name__ == "__main__":
    unittest.main()
