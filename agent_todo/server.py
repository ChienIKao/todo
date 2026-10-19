"""本機 HTTP 伺服器：提供介面檔案；開發模式另外提供 POST /api/<方法> 讓一般瀏覽器呼叫 API"""
from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

UI_DIR = Path(__file__).parent / "ui"


def start(dev_api=None, port: int = 0) -> int:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _local(self) -> bool:
            # 擋掉其他網站透過 localhost 讀寫待辦（含 DNS rebinding）
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            origin = self.headers.get("Origin")
            return host in ("127.0.0.1", "localhost") and (not origin or urlparse(origin).netloc == self.headers["Host"])

        def do_POST(self):
            name = urlparse(self.path).path.removeprefix("/api/")
            if dev_api is None or not self._local() or name.startswith("_") or not hasattr(dev_api, name):
                return self.send_error(404)
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"[]")
            try:
                body = {"result": getattr(dev_api, name)(*args)}
            except Exception as e:  # noqa: BLE001
                body = {"error": str(e)}
            self._send(json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")

        def do_GET(self):
            if not self._local():
                return self.send_error(403)
            path = unquote(urlparse(self.path).path)
            file = (UI_DIR / (path.lstrip("/") or "index.html")).resolve()
            if UI_DIR.resolve() not in file.parents or not file.is_file():
                return self.send_error(404)
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix == ".js":
                ctype = "text/javascript"
            self._send(file.read_bytes(), ctype)

        def _send(self, data: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json")) else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]
