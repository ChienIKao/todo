"""本機 HTTP 伺服器：提供介面檔案；開發模式另外提供 POST /api/<方法> 讓一般瀏覽器呼叫 API"""
from __future__ import annotations

import json
import hmac
from http.cookies import SimpleCookie
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

UI_DIR = Path(__file__).parent / "ui"
REMOTE_METHODS = frozenset({
    "version", "list_todos", "add_todo", "update_todo", "add_note", "delete_todo",
    "add_subtask", "toggle_subtask", "remove_subtask", "reorder", "restore_todo",
    "list_trash", "purge_todo", "parse_quick",
})
COOKIE = "agent_todo_pair"


def create_server(dev_api=None, port: int = 0, token=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def parse_request(self):
            if not super().parse_request():
                return False
            # 未支援的 HTTP 方法也先驗證，避免形成不需憑證的入口。
            if token is not None and self.command not in ("GET", "POST"):
                return self._authorized()
            return True

        def _authorized(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                value = cookie[COOKIE].value if COOKIE in cookie else ""
            except Exception:
                value = ""
            bearer = self.headers.get("Authorization", "")
            if bearer.startswith("Bearer "):
                value = bearer[7:]
            expected = token()
            if expected and hmac.compare_digest(value.encode(), expected.encode()):
                return True
            self._send("請重新從電腦上的 App 掃描 QR code".encode(), "text/plain", 401)
            return False

        def _local(self) -> bool:
            # 擋掉其他網站透過 localhost 讀寫待辦（含 DNS rebinding）
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            origin = self.headers.get("Origin")
            return host in ("127.0.0.1", "localhost") and (not origin or urlparse(origin).netloc == self.headers["Host"])

        def do_POST(self):
            if token is not None:
                if not self._authorized():
                    return
                origin = urlparse(self.headers.get("Origin", ""))
                if origin.scheme not in ("http", "https") or origin.netloc != self.headers.get("Host"):
                    return self.send_error(403)
            name = urlparse(self.path).path.removeprefix("/api/")
            if (not self.path.startswith("/api/") or dev_api is None
                    or (token is None and not self._local())
                    or (token is not None and name not in REMOTE_METHODS)
                    or name.startswith("_") or not callable(getattr(dev_api, name, None))):
                return self.send_error(404)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 <= length <= 2_000_000:
                    return self.send_error(413)
                args = json.loads(self.rfile.read(length) or b"[]")
                if not isinstance(args, list):
                    return self.send_error(400)
                body = {"result": getattr(dev_api, name)(*args)}
            except Exception as e:  # noqa: BLE001
                body = {"error": str(e)}
            self._send(json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")

        def do_GET(self):
            if token is not None:
                parsed = urlparse(self.path)
                if parsed.path == "/pair":
                    value = parse_qs(parsed.query).get("token", [""])[0]
                    expected = token()
                    if not expected or not hmac.compare_digest(value.encode(), expected.encode()):
                        return self._send("請重新從電腦上的 App 掃描 QR code".encode(), "text/plain", 401)
                    # 僅允許直接以 127.0.0.1 測試時省略 Secure；代理的 ts.net Host 一律加上。
                    secure = "" if urlparse("//" + self.headers.get("Host", "")).hostname == "127.0.0.1" else "; Secure"
                    self.send_response(303)
                    self.send_header("Set-Cookie", f"{COOKIE}={value}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict{secure}")
                    self.send_header("Location", "/")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                # 瀏覽器抓 manifest 和圖示時不帶 cookie；這兩個不含待辦內容，不用驗證
                public = parsed.path == "/manifest.webmanifest" or parsed.path.startswith("/icons/")
                if not public and not self._authorized():
                    return
            elif not self._local():
                return self.send_error(403)
            path = unquote(urlparse(self.path).path)
            file = (UI_DIR / (path.lstrip("/") or "index.html")).resolve()
            if UI_DIR.resolve() not in file.parents or not file.is_file():
                return self.send_error(404)
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix == ".js":
                ctype = "text/javascript"
            ctype = {".woff2": "font/woff2", ".svg": "image/svg+xml"}.get(file.suffix, ctype)
            data = file.read_bytes()
            if file.name == "index.html":
                mode = "remote" if token is not None else ("dev" if dev_api is not None else "desktop")
                data = data.replace(b"<head>", f'<head><script>window.agentTodoMode = "{mode}";</script>'.encode())
            self._send(data, ctype)

        def _send(self, data: bytes, ctype: str, status=200):
            self.send_response(status)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json")) else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    return httpd


def start(dev_api=None, port: int = 0) -> int:
    httpd = create_server(dev_api, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]
