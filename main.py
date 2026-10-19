import sys

from agent_todo import server, store
from agent_todo.api import Api

TITLE = "Agent Todo"
_instance_mutex = None


def _redirect_output() -> None:
    """打包後一律寫入紀錄，避免無主控台時遺失錯誤訊息。"""
    if getattr(sys, "frozen", False):
        store.data_dir().mkdir(parents=True, exist_ok=True)
        log = open(store.data_dir() / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = log


def _single_instance() -> bool:
    """Windows：已經開著就把原本的視窗叫到前面，不再開第二個"""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    global _instance_mutex
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.restype = wintypes.DWORD
    # 保留控制代碼直到程序結束，讓後續啟動仍能辨認既有實例。
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\AgentTodoSingleInstance")
    error = kernel32.GetLastError()
    if not _instance_mutex:
        raise ctypes.WinError(error)
    if error != 183:
        return True

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    return False


def main() -> None:
    _redirect_output()
    if "--dev" not in sys.argv and not _single_instance():
        return
    api = Api()

    if "--dev" in sys.argv:
        # 開發模式：不開視窗，用瀏覽器開 http://127.0.0.1:8766/?dev
        import time
        port = server.start(dev_api=api, port=8766)
        print(f"http://127.0.0.1:{port}/?dev", flush=True)
        while True:
            time.sleep(3600)

    import webview

    port = server.start()
    url = f"http://127.0.0.1:{port}/"
    window = webview.create_window(TITLE, url, js_api=api, text_select=True, width=480, height=780,
                                   min_size=(360, 480), background_color="#202020")
    api._attach(window, url)

    def on_closing():
        if api._mini:
            api._mini.destroy()

    window.events.closing += on_closing
    webview.start(debug="--debug" in sys.argv, private_mode=False)


if __name__ == "__main__":
    main()
