from unittest.mock import Mock, call

import pytest

from agent_todo import desktop


@pytest.fixture
def reminders(monkeypatch):
    todos = [{"id": i, "title": f"task {i}", "due": "2026-10-19", "context": "背景\n第二行"}
             for i in range(8)]
    monkeypatch.setattr(desktop.store, "due_reminders", Mock(return_value=todos))
    mark = Mock()
    monkeypatch.setattr(desktop.store, "mark_reminded", mark)
    return todos, mark


def test_startup_reminders_are_batched(reminders):
    todos, mark = reminders
    notify = Mock()
    desktop.deliver_reminders(notify, startup=True)
    assert notify.call_count == 6
    assert notify.call_args_list[0] == call("期限：2026-10-19", "task 0")
    assert notify.call_args_list[-1] == call("還有 3 個提醒，請開啟 Agent Todo 查看", "Agent Todo")
    assert mark.call_args_list == [call(t["id"]) for t in todos]


def test_regular_reminders_and_context(reminders):
    todos, mark = reminders
    todos[0]["due"] = ""
    notify = Mock()
    desktop.deliver_reminders(notify)
    assert notify.call_count == 8
    assert notify.call_args_list[0] == call("背景", "task 0")
    assert mark.call_count == 8


def test_failed_notification_is_not_marked(reminders):
    _, mark = reminders
    with pytest.raises(RuntimeError):
        desktop.deliver_reminders(Mock(side_effect=RuntimeError("failed")))
    mark.assert_not_called()


def test_scheduler_runs_immediately_then_every_30_seconds(monkeypatch):
    deliver = Mock()
    monkeypatch.setattr(desktop, "deliver_reminders", deliver)
    stop = Mock()
    stop.is_set.return_value = False
    stop.wait.side_effect = [False, True]
    notify = Mock()
    desktop.reminder_loop(notify, stop)
    assert deliver.call_args_list == [call(notify, True), call(notify, False)]
    assert stop.wait.call_args_list == [call(30), call(30)]


def test_scheduler_recovers_after_error(monkeypatch):
    deliver = Mock(side_effect=[RuntimeError("failed"), None])
    monkeypatch.setattr(desktop, "deliver_reminders", deliver)
    stop = Mock()
    stop.is_set.return_value = False
    stop.wait.side_effect = [False, True]
    desktop.reminder_loop(Mock(), stop)
    assert deliver.call_count == 2
    assert all(c.args[1] is True for c in deliver.call_args_list)


def test_hotkey_registration_failure_is_logged(caplog):
    user32 = Mock()
    user32.RegisterHotKey.return_value = 0
    desktop.hotkey_loop(Mock(), Mock(), user32)
    assert "註冊失敗" in caplog.text
    user32.PeekMessageW.assert_not_called()
    user32.UnregisterHotKey.assert_not_called()


def test_hotkey_dispatch_and_cleanup():
    user32 = Mock()
    user32.RegisterHotKey.return_value = 1
    def peek(msg, *args):
        msg._obj.message = 0x0312
        return user32.messages.pop(0)
    user32.messages = [1, 0]
    user32.PeekMessageW.side_effect = peek
    stop = Mock()
    stop.wait.side_effect = [False, True]
    activate = Mock()
    desktop.hotkey_loop(activate, stop, user32)
    activate.assert_called_once_with()
    user32.UnregisterHotKey.assert_called_once_with(None, 1)


def test_close_hides_once_and_quit_destroys():
    api, window = Mock(), Mock()
    app = desktop.Desktop(api, window)
    app.icon = Mock()
    assert app.closing() is False
    assert app.closing() is False
    assert window.hide.call_count == 2
    app.icon.notify.assert_called_once_with("Agent Todo 還在系統匣", "Agent Todo")
    app.quit()
    assert app.stop.is_set()
    assert app.closing() is True
    window.destroy.assert_called_once()


def test_second_instance_signals_hidden_window(monkeypatch):
    import main

    kernel = Mock()
    kernel.CreateMutexW.return_value = 10
    kernel.GetLastError.return_value = 183
    kernel.OpenEventW.return_value = 20
    user = Mock()
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(desktop.ctypes, "windll", Mock(kernel32=kernel, user32=user))
    assert main._single_instance() is False
    kernel.OpenEventW.assert_called_once_with(2, False, desktop.ACTIVATE_EVENT)
    kernel.SetEvent.assert_called_once_with(20)
    kernel.CloseHandle.assert_called_once_with(20)
    user.FindWindowW.assert_not_called()


def test_dev_mode_skips_desktop(monkeypatch):
    import main
    import time

    monkeypatch.setattr(main.sys, "argv", ["main.py", "--dev"])
    single = Mock()
    monkeypatch.setattr(main, "_single_instance", single)
    monkeypatch.setattr(main.server, "start", Mock(return_value=8766))
    start = Mock()
    monkeypatch.setattr(desktop.Desktop, "start", start)
    monkeypatch.setattr(time, "sleep", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        main.main()
    single.assert_not_called()
    start.assert_not_called()


@pytest.mark.parametrize("dpi,width,expected", [(96, 1920, 1560), (120, 1920, 1176), (144, 2880, 1560)])
def test_mini_window_stays_on_scaled_screen(monkeypatch, dpi, width, expected):
    import ctypes
    from agent_todo import api
    monkeypatch.setattr(api.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", Mock(user32=Mock(GetDpiForSystem=Mock(return_value=dpi))), raising=False)
    assert api._mini_x(width) == expected


def test_webview_storage_is_app_specific(monkeypatch, tmp_path):
    import main
    monkeypatch.delenv("AGENT_TODO_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert main._webview_storage() == str(tmp_path / "AgentTodo" / "WebView2")
    monkeypatch.setenv("AGENT_TODO_HOME", str(tmp_path / "data"))
    assert main._webview_storage() == str(tmp_path / "data" / "WebView2")
