"""介面呼叫的 API（pywebview js_api）：每個公開方法都可以從 JS 以 pywebview.api.xxx() 呼叫"""
from __future__ import annotations

import os
import subprocess
import sys

from . import __version__, integrations, store, quickadd

_ADD_FIELDS = ("title", "context", "priority", "project", "tags", "assignee", "due", "status",
               "subtasks", "repeat", "remindAt", "order")

_RESIZE_HIT = {"left": 10, "right": 11, "top": 12, "top-left": 13, "top-right": 14,
               "bottom": 15, "bottom-left": 16, "bottom-right": 17}


def _mini_x(screen_width: int) -> int:
    """小視窗靠右的 x 座標。webview.screens 給的是實際像素，視窗位置卻是縮放後的座標，
    螢幕縮放 125% 時直接相減會把小視窗放到螢幕外面"""
    scale = 1.0
    if sys.platform == "win32":
        try:
            import ctypes
            scale = ctypes.windll.user32.GetDpiForSystem() / 96 or 1.0
        except (AttributeError, OSError):
            pass
    return max(0, int(screen_width / scale) - 360)


class Api:
    def __init__(self):
        self._window = None
        self._mini = None
        self._url = ""
        self._mobile = None
        self._maximized = False

    def mobile_info(self) -> dict:
        return self._mobile.info()

    def mobile_configure(self, enabled: bool, port: int = 8767, regenerate: bool = False) -> dict:
        return self._mobile.configure(enabled, port, regenerate)

    def mobile_setup(self) -> dict:
        return self._mobile.setup()

    def open_url(self, url: str) -> None:
        """用系統瀏覽器開 Tailscale 的網頁（App 視窗內點連結不會開新視窗）"""
        if not url.startswith(("https://login.tailscale.com/", "https://tailscale.com/")):
            raise ValueError("只能開啟 Tailscale 的網址")
        import webbrowser
        webbrowser.open(url)

    def _attach(self, window, url: str = "") -> None:
        self._window = window
        self._url = url
        window.events.maximized += self._on_maximized
        window.events.restored += self._on_restored

    # ---- 主視窗標題列 ----
    def _on_maximized(self) -> None:
        self._maximized = True
        self._sync_window_state()

    def _on_restored(self) -> None:
        self._maximized = False
        self._sync_window_state()

    def _sync_window_state(self) -> None:
        self._window.evaluate_js(
            f"window.syncWindowState && window.syncWindowState({str(self._maximized).lower()})")

    def window_state(self) -> bool:
        return self._maximized

    def minimize_window(self) -> None:
        if self._window:
            self._window.minimize()

    def toggle_maximize(self) -> bool:
        if self._window:
            maximized = not self._maximized
            if maximized:
                self._fit_maximize_to_work_area()
                self._window.maximize()
            else:
                self._window.restore()
            self._maximized = maximized
        return self._maximized

    def _fit_maximize_to_work_area(self) -> None:
        """無框視窗最大化預設會蓋住工作列；限制在目前螢幕扣掉工作列的範圍"""
        if sys.platform != "win32":
            return
        try:
            from System import Action
            from System.Drawing import Rectangle
            from System.Windows.Forms import Screen
        except ImportError:
            return
        form = self._window.native

        def fit():
            screen = Screen.FromControl(form)
            work, bounds = screen.WorkingArea, screen.Bounds
            # MaximizedBounds 是相對於所在螢幕左上角的座標
            form.MaximizedBounds = Rectangle(work.X - bounds.X, work.Y - bounds.Y, work.Width, work.Height)

        form.Invoke(Action(fit))

    def close_window(self) -> None:
        if self._window:
            # destroy 會先觸發 Desktop.closing，沿用縮到系統匣的處理
            self._window.destroy()

    def start_resize(self, direction: str) -> None:
        hit = _RESIZE_HIT[direction]
        if not self._window or self._maximized or sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes
        from System import Action

        hwnd = self._window.native.Handle.ToInt64()
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        def resize():
            # 滑鼠擷取屬於 UI 執行緒，要在同一個執行緒交給 Windows 縮放
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, 0x00A1, hit, 0)

        self._window.native.Invoke(Action(resize))

    # ---- 待辦 ----
    def version(self) -> float:
        """資料檔的修改時間：AI 或 todo 指令改了清單，介面輪詢到就重新載入"""
        return store.version()

    def list_todos(self, view: str = "") -> list[dict]:
        return store.list_todos(status="all", view=view)

    def add_todo(self, fields: dict) -> dict:
        return store.add(**{k: v for k, v in fields.items() if k in _ADD_FIELDS and v not in (None, "")})

    def update_todo(self, tid: int, fields: dict) -> dict:
        return store.update(tid, **fields)

    def add_note(self, tid: int, text: str) -> dict:
        return store.add_note(tid, text, "me")

    def delete_todo(self, tid: int) -> dict:
        return store.remove(tid)

    def add_subtask(self, tid: int, title: str) -> dict:
        return store.add_subtask(tid, title)

    def toggle_subtask(self, tid: int, sid: int, done=None) -> dict:
        return store.toggle_subtask(tid, sid, done)

    def remove_subtask(self, tid: int, sid: int) -> dict:
        return store.remove_subtask(tid, sid)

    def reorder(self, ids: list[int]) -> list[dict]:
        return store.reorder(ids)

    def restore_todo(self, tid: int) -> dict:
        return store.restore(tid)

    def list_trash(self) -> list[dict]:
        return store.list_trash()

    def purge_todo(self, tid: int) -> dict:
        return store.purge(tid)

    def parse_quick(self, text: str) -> dict:
        return quickadd.parse(text)

    def due_reminders(self) -> list[dict]:
        return store.due_reminders()

    def mark_reminded(self, tid: int) -> dict:
        return store.mark_reminded(tid)

    # ---- 接上 AI ----
    def info(self) -> dict:
        return {"version": __version__, "data_file": str(store.data_file()),
                "markdown_file": str(store.markdown_file()), "status": integrations.status(),
                "claude_command": integrations.claude_command(), "codex_toml": integrations.codex_toml(),
                "instructions": integrations.INSTRUCTIONS}

    def setup_claude(self) -> dict:
        integrations.setup_claude()
        return self.info()

    def setup_codex(self) -> dict:
        integrations.setup_codex()
        return self.info()

    def open_data_dir(self) -> None:
        folder = store.data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])

    # ---- 置頂小視窗 ----
    def show_mini(self) -> None:
        if self._mini or not self._url:
            return
        import webview

        x = _mini_x(webview.screens[0].width) if webview.screens else None
        self._mini = webview.create_window("Agent Todo・小視窗", f"{self._url}?mini=1", js_api=self, width=320,
                                           height=480, x=x, y=60 if x is not None else None, min_size=(260, 200),
                                           frameless=True, easy_drag=False, on_top=True, background_color="#0e0f14")
        self._mini.events.closed += self._mini_closed
        if self._window:
            self._window.minimize()

    def _mini_closed(self) -> None:
        self._mini = None
        if self._window:
            self._window.show()
            self._window.restore()

    def close_mini(self) -> None:
        mini, self._mini = self._mini, None
        if mini:
            mini.destroy()
            if self._window:
                self._window.show()
                self._window.restore()

    def open_in_main(self, tid: int) -> None:
        """小視窗點了某個待辦：回到主視窗並展開它"""
        self.close_mini()
        if self._window:
            self._window.evaluate_js(f"openTodo({int(tid)})")
