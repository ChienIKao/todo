"""Windows 系統匣、快捷鍵與提醒排程。"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from pathlib import Path

from . import store

log = logging.getLogger(__name__)
ACTIVATE_EVENT = "Local\\AgentTodoActivate"


def deliver_reminders(notify, startup=False):
    todos = store.due_reminders()
    shown = todos[:5] if startup else todos
    for todo in shown:
        body = f"期限：{todo['due']}" if todo['due'] else (todo['context'].splitlines() or ["待辦提醒"])[0]
        notify(body, todo['title'])
        store.mark_reminded(todo['id'])
    if startup and len(todos) > 5:
        rest = todos[5:]
        notify(f"還有 {len(rest)} 個提醒，請開啟 Agent Todo 查看", "Agent Todo")
        for todo in rest:
            store.mark_reminded(todo['id'])


def reminder_loop(notify, stop):
    startup = True
    while not stop.is_set():
        try:
            deliver_reminders(notify, startup)
            startup = False
        except Exception:
            log.exception("提醒通知失敗")
        if stop.wait(30):
            break


def hotkey_loop(activate, stop, user32=None):
    user32 = user32 or ctypes.windll.user32
    if not user32.RegisterHotKey(None, 1, 0x4003, ord('T')):
        log.warning("Ctrl+Alt+T 註冊失敗，快捷鍵可能已被佔用")
        return
    try:
        msg = wintypes.MSG()
        while not stop.wait(0.05):
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == 0x0312:
                    activate()
    finally:
        user32.UnregisterHotKey(None, 1)


class Desktop:
    def __init__(self, api, window):
        self.api, self.window = api, window
        self.stop = threading.Event()
        self.exiting = False
        self.hidden_once = False
        self.icon = None
        self.event = None

    def activate(self, focus=False):
        self.window.show()
        self.window.restore()
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow(self.window.native.Handle.ToInt64())
        self.window.evaluate_js(f"window.focusNewTodo && window.focusNewTodo({str(focus).lower()})")

    def closing(self):
        if self.exiting:
            return True
        self.window.hide()
        if not self.hidden_once:
            self.icon.notify("Agent Todo 還在系統匣", "Agent Todo")
            self.hidden_once = True
        return False

    def quit(self):
        self.exiting = True
        self.stop.set()
        if self.api._mini:
            self.api._mini.destroy()
        self.window.destroy()
        self.icon.stop()

    def _activation_loop(self):
        kernel = ctypes.windll.kernel32
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.event = kernel.CreateEventW(None, False, False, ACTIVATE_EVENT)
        if not self.event:
            log.error("無法建立視窗喚回事件")
            return
        try:
            while not self.stop.is_set():
                if kernel.WaitForSingleObject(self.event, 250) == 0:
                    self.activate()
        finally:
            kernel.CloseHandle(self.event)

    def start(self):
        import pystray
        from PIL import Image

        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
        self.icon = pystray.Icon('AgentTodo', Image.open(root / 'assets' / 'icon.png'), 'Agent Todo',
            pystray.Menu(
                pystray.MenuItem('開啟', lambda: self.activate(), default=True),
                pystray.MenuItem('新增待辦', lambda: self.activate(True)),
                pystray.MenuItem('置頂小視窗', lambda: self.api.show_mini()),
                pystray.MenuItem('結束', lambda: self.quit())))

        def ready(icon):
            icon.visible = True
            threading.Thread(target=reminder_loop, args=(icon.notify, self.stop), daemon=True).start()

        self.icon.run_detached(ready)
        threading.Thread(target=hotkey_loop, args=(lambda: self.activate(True), self.stop), daemon=True).start()
        threading.Thread(target=self._activation_loop, daemon=True).start()
