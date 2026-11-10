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

from . import mcp, oauth

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

        def _paired_cookie(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                value = cookie[COOKIE].value if COOKIE in cookie else ""
            except Exception:
                return False
            expected = token()
            return bool(expected and hmac.compare_digest(value.encode(), expected.encode()))

        def _oauth_reply(self, body, status=200, headers=None):
            ctype = "text/html" if isinstance(body, str) else "application/json"
            data = (body.encode("utf-8") if isinstance(body, str) else
                    json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b"")
            return self._send(data, ctype, status, headers)

        def _trusted_origin(self, base):
            origin = self.headers.get("Origin")
            return origin is None or origin in (base, "https://claude.ai", "https://claude.com")

        def _mcp_post(self, raw, base):
            if not self._trusted_origin(base):
                return self._send("來源不受信任".encode(), "text/plain", 403)
            bearer = self.headers.get("Authorization", "")
            if not bearer.startswith("Bearer ") or not oauth.validate_access(bearer[7:], base + "/mcp"):
                return self._oauth_reply({"error": "invalid_token"}, 401, {
                    "WWW-Authenticate": f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'})
            try:
                msg = json.loads(raw)
            except (ValueError, UnicodeError):
                return self._oauth_reply({"jsonrpc": "2.0", "id": None,
                                          "error": {"code": -32700, "message": "JSON 格式錯誤"}}, 400)
            if (not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0"
                    or ("method" in msg and not isinstance(msg["method"], str))
                    or ("params" in msg and not isinstance(msg["params"], dict))
                    or ("method" not in msg and not ("id" in msg and ("result" in msg or "error" in msg)))):
                return self._oauth_reply({"jsonrpc": "2.0", "id": None,
                                          "error": {"code": -32600, "message": "JSON-RPC 訊息無效"}}, 400)
            if "method" not in msg:
                return self._oauth_reply(None, 202)
            # 每次請求各用一個 Handler，HTTP 的作者固定，不讓 clientInfo 改寫。
            handle = mcp.Handler()
            handle.author = "claude-chat"
            if msg["method"] == "initialize":
                msg["params"] = {**msg.get("params", {}), "protocolVersion": "2025-06-18", "clientInfo": {}}
            response = handle(msg)
            if "id" not in msg or response is None:
                return self._oauth_reply(None, 202)
            return self._oauth_reply(response)

        def _oauth_post(self, path, raw):
            try:
                base = oauth.base_url(self.headers.get("Host", ""))
                if path == "/mcp":
                    return self._mcp_post(raw, base)
                if not self._trusted_origin(base):
                    return self._send("來源不受信任".encode(), "text/plain", 403)
                ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if path == "/oauth/register":
                    if ctype != "application/json":
                        raise oauth.OAuthError("invalid_request", "請使用 JSON 格式")
                    return self._oauth_reply(oauth.register(json.loads(raw)), 201)
                if ctype != "application/x-www-form-urlencoded":
                    raise oauth.OAuthError("invalid_request", "請使用表單格式")
                fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                if any(len(values) != 1 for values in fields.values()):
                    raise oauth.OAuthError("invalid_request", "表單參數不可重複")
                params = {k: v[0] for k, v in fields.items()}
                if path == "/oauth/authorize":
                    return self._oauth_reply(*oauth.authorize_post(params, base, self._paired_cookie()))
                return self._oauth_reply(oauth.exchange(params, base))
            except oauth.OAuthError as exc:
                return self._oauth_reply({"error": exc.error, "error_description": str(exc)}, 400)
            except (ValueError, UnicodeError):
                return self._oauth_reply({"error": "invalid_request", "error_description": "資料格式錯誤"}, 400)

        def do_POST(self):
            # 先把 body 讀完再回錯誤，不然 Windows 會直接重設連線（WinError 10053）
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return self.send_error(400)
            if not 0 <= length <= 2_000_000:
                return self.send_error(413)
            raw = self.rfile.read(length)
            if token is not None and urlparse(self.path).path in ("/mcp", "/oauth/token", "/oauth/register", "/oauth/authorize"):
                return self._oauth_post(urlparse(self.path).path, raw)
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
                args = json.loads(raw or b"[]")
                if not isinstance(args, list):
                    return self.send_error(400)
                body = {"result": getattr(dev_api, name)(*args)}
            except Exception as e:  # noqa: BLE001
                body = {"error": str(e)}
            self._send(json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")

        def do_GET(self):
            if token is not None:
                parsed = urlparse(self.path)
                if parsed.path == "/mcp":
                    try:
                        base = oauth.base_url(self.headers.get("Host", ""))
                    except ValueError:
                        return self._send("主機位址無效".encode(), "text/plain", 400)
                    if not self._trusted_origin(base):
                        return self._send("來源不受信任".encode(), "text/plain", 403)
                    return self._send("此端點只接受 POST".encode(), "text/plain", 405, {"Allow": "POST"})
                if parsed.path.startswith("/.well-known/oauth-") or parsed.path == "/oauth/authorize":
                    try:
                        base = oauth.base_url(self.headers.get("Host", ""))
                        data = oauth.metadata(parsed.path, base)
                        if data is not None:
                            return self._oauth_reply(data)
                        if parsed.path == "/oauth/authorize":
                            fields = parse_qs(parsed.query, keep_blank_values=True)
                            if any(len(values) != 1 for values in fields.values()):
                                return self._oauth_reply(*oauth.error_page("授權參數不可重複"))
                            params = {k: v[0] for k, v in fields.items()}
                            return self._oauth_reply(*oauth.authorize_get(params, base, self._paired_cookie()))
                    except (ValueError, UnicodeError):
                        return self._oauth_reply(*oauth.error_page("授權參數無效"))
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

        def do_DELETE(self):
            if token is not None and urlparse(self.path).path == "/mcp":
                return self._send("此端點只接受 POST".encode(), "text/plain", 405, {"Allow": "POST"})
            self.send_error(405)

        def _send(self, data: bytes, ctype: str, status=200, headers=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json")) else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
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
