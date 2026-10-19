import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_todo import integrations


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        p = patch.object(Path, "home", return_value=self.home)
        p.start()
        self.addCleanup(p.stop)

    def test_setup_codex_appends_once(self):
        cfg = self.home / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text('model = "gpt-5"', encoding="utf-8")
        integrations.setup_codex()
        integrations.setup_codex()
        text = cfg.read_text(encoding="utf-8")
        self.assertTrue(text.startswith('model = "gpt-5"\n\n[mcp_servers.todo]'))
        self.assertEqual(text.count("[mcp_servers.todo]"), 1)
        agents = (self.home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(agents.count(integrations.MARKER), 1)
        st = integrations.status()["codex"]
        self.assertTrue(st["mcp"] and st["instructions"])

    def test_setup_claude_without_cli(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                integrations.setup_claude()

    def test_windows_paths_are_valid_toml(self):
        with patch.object(integrations, "mcp_command", return_value=["C:\\Program Files\\Agent Todo\\todo.exe", "mcp"]):
            self.assertIn('command = "C:\\\\Program Files\\\\Agent Todo\\\\todo.exe"', integrations.codex_toml())
            self.assertIn('"C:\\Program Files\\Agent Todo\\todo.exe" mcp', integrations.claude_command())


if __name__ == "__main__":
    unittest.main()
