import ctypes
import sys
from unittest.mock import MagicMock, Mock

import pytest

from agent_todo.api import Api
from agent_todo.desktop import Desktop
from agent_todo.server import REMOTE_METHODS


@pytest.fixture
def attached():
    api, window = Api(), Mock()
    window.events.maximized = MagicMock()
    window.events.restored = MagicMock()
    for event in (window.events.maximized, window.events.restored):
        event.__iadd__.return_value = event
    api._attach(window)
    return api, window


def test_maximize_toggle_and_native_events(attached):
    api, window = attached
    assert api.window_state() is False
    assert api.toggle_maximize() is True
    window.maximize.assert_called_once_with()
    assert api.toggle_maximize() is False
    window.restore.assert_called_once_with()
    window.events.maximized.__iadd__.assert_called_once_with(api._on_maximized)
    window.events.restored.__iadd__.assert_called_once_with(api._on_restored)
    api._on_maximized()
    assert api.window_state() is True
    window.evaluate_js.assert_called_with('window.syncWindowState && window.syncWindowState(true)')
    api.toggle_maximize()
    assert window.restore.call_count == 2
    api._on_restored()
    assert api.window_state() is False
    window.evaluate_js.assert_called_with('window.syncWindowState && window.syncWindowState(false)')


def test_close_uses_desktop_closing(attached):
    api, window = attached
    desktop = Desktop(api, window)
    desktop.icon = Mock()
    window.destroy.side_effect = desktop.closing
    api.close_window()
    api.close_window()
    assert window.hide.call_count == 2
    desktop.icon.notify.assert_called_once_with('Agent Todo 還在系統匣', 'Agent Todo')
    assert not desktop.exiting
    api.minimize_window()
    window.minimize.assert_called_once_with()


@pytest.mark.parametrize('direction,hit', [
    ('left', 10), ('right', 11), ('top', 12), ('top-left', 13), ('top-right', 14),
    ('bottom', 15), ('bottom-left', 16), ('bottom-right', 17),
])
def test_resize_hit_codes(attached, monkeypatch, direction, hit):
    api, window = attached
    window.native.Handle.ToInt64.return_value = 0x123456789
    user32 = Mock()
    monkeypatch.setattr('agent_todo.api.sys.platform', 'win32')
    monkeypatch.setattr(ctypes, 'windll', Mock(user32=user32), raising=False)
    monkeypatch.setitem(sys.modules, 'System', Mock(Action=lambda callback: callback))
    window.native.Invoke.side_effect = lambda callback: callback()
    api.start_resize(direction)
    user32.ReleaseCapture.assert_called_once_with()
    user32.SendMessageW.assert_called_once_with(0x123456789, 0xA1, hit, 0)
    api._on_maximized()
    user32.reset_mock()
    api.start_resize(direction)
    user32.SendMessageW.assert_not_called()


def test_invalid_resize_direction(attached):
    api, window = attached
    with pytest.raises(KeyError):
        api.start_resize('invalid')
    window.native.Handle.ToInt64.assert_not_called()


def test_window_controls_are_local():
    assert REMOTE_METHODS.isdisjoint({
        'window_state', 'minimize_window', 'toggle_maximize', 'close_window', 'start_resize',
    })


def test_activate_brings_native_window_forward(attached, monkeypatch):
    api, window = attached
    user32 = Mock()
    window.native.Handle.ToInt64.return_value = 0x123456789
    monkeypatch.setattr('agent_todo.desktop.sys.platform', 'win32')
    monkeypatch.setattr(ctypes, 'windll', Mock(user32=user32), raising=False)
    desktop = Desktop(api, window)
    desktop.activate(True)
    window.show.assert_called_once_with()
    window.restore.assert_called_once_with()
    user32.SetForegroundWindow.assert_called_once_with(0x123456789)
    window.evaluate_js.assert_called_once_with('window.focusNewTodo && window.focusNewTodo(true)')
