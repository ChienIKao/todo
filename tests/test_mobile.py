import http.client
import json
import threading
from unittest.mock import Mock

import pytest

from agent_todo import mobile, server
from agent_todo.api import Api


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TODO_HOME", str(tmp_path))


@pytest.fixture
def remote():
    state = {"token": "test-secret"}
    httpd = server.create_server(Api(), 0, lambda: state["token"])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def request(path="/", method="GET", headers=None, args=None):
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
        conn.request(method, path, body=json.dumps(args or []) if method == "POST" else None,
                     headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    yield request, state, httpd
    httpd.shutdown()
    httpd.server_close()


def test_authentication(remote):
    request, _, _ = remote
    for path in ("/", "/app.js", "/sw.js", "/pair?token=bad"):
        status, _, body = request(path)
        assert status == 401
        assert "請重新從電腦上的 App 掃描 QR code" in body.decode()
    # 瀏覽器安裝 PWA 時抓 manifest、圖示不帶 cookie
    for path in ("/manifest.webmanifest", "/icons/icon-192.png"):
        assert request(path)[0] == 200
    assert request(headers={"Authorization": "Bearer bad"})[0] == 401
    assert request("/api/list_todos", "POST")[0] == 401
    for method in ("HEAD", "OPTIONS", "PUT", "DELETE"):
        assert request(method=method)[0] == 401
    assert request(headers={"Authorization": "Bearer test-secret", "Host": "pc.tailnet.ts.net"})[0] == 200


def test_pair_cookie_and_rotation(remote):
    request, state, _ = remote
    status, headers, _ = request("/pair?token=test-secret", headers={"Host": "pc.tailnet.ts.net"})
    assert status == 303 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"]
    for attribute in ("HttpOnly", "Secure", "SameSite=Strict", "Max-Age=31536000", "Path=/"):
        assert attribute in cookie
    assert request(headers={"Cookie": cookie.split(";")[0]})[0] == 200
    assert "Secure" not in request("/pair?token=test-secret")[1]["Set-Cookie"]
    assert "Secure" in request("/pair?token=test-secret", headers={"Host": "localhost:8767"})[1]["Set-Cookie"]
    state["token"] = "replacement"
    assert request(headers={"Cookie": cookie.split(";")[0]})[0] == 401


def test_remote_methods_and_origin(remote):
    request, _, httpd = remote
    assert httpd.server_address[0] == "127.0.0.1"
    headers = {"Authorization": "Bearer test-secret", "Host": "pc.tailnet.ts.net", "Origin": "https://pc.tailnet.ts.net"}
    for method in ("setup_claude", "setup_codex", "open_data_dir", "show_mini", "info",
                   "mobile_info", "mobile_configure", "mobile_setup", "_attach"):
        assert request(f"/api/{method}", "POST", headers)[0] == 404
    for origin in ("https://evil.example", "null", "", "https://pc.tailnet.ts.net.evil"):
        assert request("/api/add_todo", "POST", {**headers, "Origin": origin}, [{"title": "bad"}])[0] == 403
    assert request("/api/list_todos", "POST", headers)[2] == b'{"result": []}'
    result = request("/api/add_todo", "POST", headers, [{"title": "phone"}])
    assert json.loads(result[2])["result"]["title"] == "phone"
    assert Api().list_todos()[0]["title"] == "phone"
    assert request("/api/update_todo", "POST", headers, [1, {"status": "done"}])[0] == 200
    assert Api().list_todos()[0]["status"] == "done"


def test_settings():
    assert mobile.load_settings() == {"enabled": False, "port": 8767, "token": ""}
    data = mobile.save_settings({"enabled": True, "port": 8767, "token": ""})
    assert len(data["token"]) >= 43
    assert mobile.load_settings() == data
    assert mobile.save_settings({**data, "enabled": False})["token"] == data["token"]
    with pytest.raises(ValueError):
        mobile.save_settings({**data, "port": 0})


def test_tailscale_json_and_command(monkeypatch):
    status = {"BackendState": "Running", "Self": {"DNSName": "pc.tail.ts.net."}}
    serve = {"TCP": {"443": {"HTTPS": True}}, "Web": {
        "pc.tail.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8767"}}}}}
    run = Mock(side_effect=[Mock(returncode=0, stdout=json.dumps(status)), Mock(returncode=0, stdout=json.dumps(serve))])
    monkeypatch.setattr(mobile.subprocess, "run", run)
    access = mobile.MobileAccess(Api())
    info = access.info()
    assert info["dns"] == "pc.tail.ts.net" and info["serve_ready"]
    assert run.call_args_list[0].args[0][-2:] == ["status", "--json"]
    assert run.call_args.kwargs["creationflags"] == getattr(mobile.subprocess, "CREATE_NO_WINDOW", 0)
    assert not mobile.parse_status(status, serve, 8768)["serve_ready"]
    assert not mobile.parse_status({"BackendState": "NeedsLogin"}, serve, 8767)["logged_in"]
    serve["AllowFunnel"] = {"pc.tail.ts.net:443": True}
    assert not mobile.parse_status(status, serve, 8767)["serve_ready"]
    monkeypatch.setattr(mobile.subprocess, "run", Mock(side_effect=FileNotFoundError("missing")))
    assert "missing" in access.info()["tailscale_error"]


def test_setup_reports_serve_enable_url(monkeypatch):
    access = mobile.MobileAccess(Api())
    monkeypatch.setattr(mobile.MobileAccess, "info", lambda self: {"serve_ready": False})
    url = "https://login.tailscale.com/f/serve?node=abc123"
    stalled = mobile.subprocess.TimeoutExpired(["tailscale"], 15, output=f"\nServe is not enabled on your tailnet.\nTo enable, visit:\n\n         {url}\n")
    monkeypatch.setattr(mobile.subprocess, "run", Mock(side_effect=stalled))
    assert access.setup() == {"serve_ready": False, "serve_enable_url": url}
    monkeypatch.setattr(mobile.subprocess, "run", Mock(side_effect=mobile.subprocess.TimeoutExpired(["tailscale"], 15)))
    with pytest.raises(RuntimeError, match="沒有回應"):
        access.setup()
    monkeypatch.setattr(mobile.subprocess, "run", Mock(return_value=Mock(returncode=1, stderr=f"To enable, visit: {url}", stdout="")))
    assert access.setup()["serve_enable_url"] == url


def test_open_url_only_allows_tailscale(monkeypatch):
    opened = Mock()
    monkeypatch.setattr("webbrowser.open", opened)
    Api().open_url("https://login.tailscale.com/f/serve?node=abc")
    opened.assert_called_once()
    with pytest.raises(ValueError):
        Api().open_url("https://evil.example/")
    assert "open_url" not in server.REMOTE_METHODS


def test_live_toggle_and_qr(monkeypatch):
    monkeypatch.setattr(mobile.MobileAccess, "info", lambda self: {"running": self.httpd is not None})
    # 先由 OS 取得可用埠，設定檔仍使用正常的固定埠值。
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    api = Api()
    access = mobile.MobileAccess(api)
    try:
        assert access.configure(True, port)["running"]
        first = access.settings["token"]
        access.configure(True, port, True)
        assert access.settings["token"] != first
        assert not access.configure(False, port)["running"]
    finally:
        access.stop()


def test_pairing_svg(monkeypatch):
    access = mobile.MobileAccess(Api())
    access.settings = mobile.save_settings({"enabled": True, "port": 8767, "token": ""})
    access.httpd = Mock()
    monkeypatch.setattr(mobile, "_tailscale", lambda *args: "{}")
    monkeypatch.setattr(mobile, "parse_status", lambda *args: {"dns": "pc.tail.ts.net", "logged_in": True, "serve_ready": True})
    info = access.info()
    assert info["pair_url"].startswith("https://pc.tail.ts.net/pair?token=")
    assert "<svg" in info["qr_svg"]
    assert "token" not in {key for key in info if key != "pair_url"}


@pytest.mark.parametrize("path, mime", [
    ("/fonts/Cubic_11.woff2", "font/woff2"),
    ("/pixelarticons/sprite.svg", "image/svg+xml"),
])
def test_remote_pixel_assets(remote, path, mime):
    request, _, _ = remote
    assert request(path)[0] == 401
    status, headers, body = request(path, headers={"Authorization": "Bearer test-secret"})
    assert status == 200
    assert headers["Content-Type"] == mime
    assert body


def test_ui_prefs_persist_in_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TODO_HOME", str(tmp_path))
    api = Api()
    assert api.get_prefs() == {}
    assert api.set_prefs({"theme": "beige"}) == {"theme": "beige"}
    assert api.set_prefs({"view": "calendar", "theme": "neon", "evil": 1}) == {"theme": "beige", "view": "calendar"}
    assert Api().get_prefs() == {"theme": "beige", "view": "calendar"}  # 重開 App 後還在
    (tmp_path / "ui.json").write_text("not json", encoding="utf-8")
    assert Api().get_prefs() == {}
    assert "get_prefs" not in server.REMOTE_METHODS and "set_prefs" not in server.REMOTE_METHODS
