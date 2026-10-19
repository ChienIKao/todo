"""接上 Claude Code／Codex：MCP server 設定與全域指示（CLAUDE.md／AGENTS.md）"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = "<!-- agent-todo -->"

INSTRUCTIONS = f"""{MARKER}
## 我的待辦清單（Agent Todo）

我用 `todo` MCP server 管理待辦事項，每個待辦的 `context` 欄位就是我要交代的背景，讀它就不用我再解釋一次。

- 我說「做下一件事」「看我的待辦」「處理 #12」之類的話時：先用 `list_todos`（在 repo 裡就帶 `project` 篩選目前 repo），再用 `get_todo` 讀完整背景與筆記後才開始。
- 開始做時用 `update_todo` 把狀態設成 `doing`；重要決定、進度、卡住的原因用 `add_note` 記下來。
- 做完用 `complete_todo`，`summary` 寫清楚做了什麼（改了哪些檔案、PR 連結、後續要注意的事）。
- 過程中發現新的工作，用 `add_todo` 新增，`context` 寫到別人能直接接手的程度。
- 若沒有 MCP 工具可用，可直接讀 `~/.agent-todo/TODO.md`（唯讀快照），或用 `todo` 指令（`todo ls`、`todo show <id>`、`todo note <id> "..."`、`todo done <id> "摘要"`）。
"""


def mcp_command() -> list[str]:
    """啟動 MCP server 的指令：安裝版用 App 旁邊的 todo.exe，原始碼版用 python todo.py"""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("todo.exe")), "mcp"]
    python = Path(sys.executable)
    if python.stem.lower() == "pythonw" and python.with_name("python.exe").exists():
        python = python.with_name("python.exe")  # pythonw 沒有 stdio
    return [str(python), str(ROOT / "todo.py"), "mcp"]


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def claude_command() -> str:
    return "claude mcp add --scope user todo -- " + " ".join(_quote(a) for a in mcp_command())


def codex_toml() -> str:
    cmd = mcp_command()
    return f"[mcp_servers.todo]\ncommand = {json.dumps(cmd[0])}\nargs = {json.dumps(cmd[1:])}\n"


def _claude_home() -> Path:
    return Path.home() / ".claude"


def _codex_home() -> Path:
    return Path.home() / ".codex"


def _has_marker(file: Path) -> bool:
    try:
        return MARKER in file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False


def _append_instructions(file: Path) -> None:
    if _has_marker(file):
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    old = file.read_text(encoding="utf-8") if file.exists() else ""
    sep = "" if not old else ("\n" if old.endswith("\n") else "\n\n")
    file.write_text(old + sep + INSTRUCTIONS, encoding="utf-8")


def status() -> dict:
    """各個 AI 工具是否已接上（MCP server 與全域指示）"""
    try:
        claude_cfg = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))
        claude_mcp = "todo" in (claude_cfg.get("mcpServers") or {})
    except (OSError, ValueError):
        claude_mcp = False
    try:
        codex_cfg = (_codex_home() / "config.toml").read_text(encoding="utf-8")
        codex_mcp = bool(re.search(r"^\[mcp_servers\.todo\]", codex_cfg, re.M))
    except OSError:
        codex_mcp = False
    return {
        "claude": {"installed": bool(shutil.which("claude")), "mcp": claude_mcp,
                   "instructions": _has_marker(_claude_home() / "CLAUDE.md")},
        "codex": {"installed": bool(shutil.which("codex")) or _codex_home().exists(), "mcp": codex_mcp,
                  "instructions": _has_marker(_codex_home() / "AGENTS.md")},
    }


def setup_claude() -> None:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("找不到 claude 指令，請先安裝 Claude Code，或手動執行下面的指令")
    if not status()["claude"]["mcp"]:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run([exe, "mcp", "add", "--scope", "user", "todo", "--", *mcp_command()],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=flags, timeout=60)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip() or "claude mcp add 失敗")
    _append_instructions(_claude_home() / "CLAUDE.md")


def setup_codex() -> None:
    cfg = _codex_home() / "config.toml"
    if not status()["codex"]["mcp"]:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        old = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
        sep = "" if not old else ("\n" if old.endswith("\n") else "\n\n")
        cfg.write_text(old + sep + codex_toml(), encoding="utf-8")
    _append_instructions(_codex_home() / "AGENTS.md")
