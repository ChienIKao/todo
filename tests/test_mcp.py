import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class McpTests(unittest.TestCase):
    def test_stdio_session(self):
        with tempfile.TemporaryDirectory() as home:
            proc = subprocess.Popen([sys.executable, str(ROOT / "todo.py"), "mcp"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, env={**os.environ, "AGENT_TODO_HOME": home})
            self.addCleanup(lambda: (proc.stdin.close(), proc.wait(5), proc.stdout.close()))
            next_id = iter(range(1, 100))

            def rpc(method, params=None):
                mid = next(next_id)
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}).encode() + b"\n")
                proc.stdin.flush()
                res = json.loads(proc.stdout.readline())
                self.assertEqual(res["id"], mid)
                return res

            def call(name, args):
                return rpc("tools/call", {"name": name, "arguments": args})["result"]

            init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "codex", "version": "1"}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "agent-todo")
            self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
            proc.stdin.write(b'{"jsonrpc": "2.0", "method": "notifications/initialized"}\n')

            tools = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
            self.assertEqual(tools, ["list_todos", "get_todo", "add_todo", "update_todo", "add_note", "complete_todo", "check_subtask"])

            call("add_todo", {"title": "寫測試", "context": "用 unittest", "project": "todo"})
            self.assertIn("#1 寫測試", call("list_todos", {})["content"][0]["text"])
            call("add_todo", {"title": "別的事"})
            listed = call("list_todos", {"current_repo": "D:\\App\\todo"})["content"][0]["text"].split("\n#")
            self.assertIn("(this repo)", listed[0])
            self.assertTrue(listed[1].startswith("2 別的事"))
            self.assertNotIn("(this repo)", listed[1])
            call("update_todo", {"id": 2, "status": "done"})
            self.assertIn("用 unittest", call("get_todo", {"id": 1})["content"][0]["text"])
            self.assertIn("status: doing", call("update_todo", {"id": 1, "status": "doing"})["content"][0]["text"])
            call("add_note", {"id": 1, "text": "一半了"})
            done = call("complete_todo", {"id": 1, "summary": "全部通過"})["content"][0]["text"]
            self.assertIn("status: done", done)
            self.assertIn("(codex) 一半了", done)

            self.assertTrue(call("get_todo", {"id": 42})["isError"])
            self.assertTrue(call("get_todo", {})["isError"])
            self.assertEqual(rpc("nope")["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
