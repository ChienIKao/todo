"""手機存取設定、Tailscale 配對與遠端伺服器生命週期。"""
from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlencode, urlparse

from . import server, store


def load_settings():
    path = store.data_dir() / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"enabled": bool(data.get("enabled", False)), "port": int(data.get("port", 8767)),
            "token": data.get("token", "")}


def save_settings(data):
    port = int(data["port"])
    if not 1 <= port <= 65535:
        raise ValueError("連接埠必須介於 1 到 65535")
    data = {**data, "port": port}
    if data["enabled"] and not data.get("token"):
        data["token"] = secrets.token_urlsafe(32)
    path = store.data_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return data


def _tailscale(*args):
    exe = shutil.which("tailscale")
    if not exe:
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tailscale/tailscale.exe"
        exe = str(candidate) if candidate.is_file() else "tailscale"
    result = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8",
                            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or "Tailscale 執行失敗")
    return result.stdout


def parse_status(status, serve, port):
    dns = (status.get("Self", {}).get("DNSName") or "").rstrip(".")
    logged_in = status.get("BackendState") == "Running" and bool(dns)
    handler = serve.get("Web", {}).get(f"{dns}:443", {}).get("Handlers", {}).get("/", {})
    proxy = urlparse(handler.get("Proxy", ""))
    ready = (logged_in and serve.get("TCP", {}).get("443", {}).get("HTTPS") is True
             and proxy.scheme == "http" and proxy.hostname in ("127.0.0.1", "localhost")
             and proxy.port == port and proxy.path in ("", "/")
             and not serve.get("AllowFunnel", {}).get(f"{dns}:443", False))
    return {"dns": dns, "logged_in": logged_in, "serve_ready": bool(ready)}


class MobileAccess:
    def __init__(self, api):
        self.api = api
        self.settings = load_settings()
        self.httpd = None
        self.lock = threading.RLock()
        self.error = ""

    def start(self, force=False):
        with self.lock:
            if force:
                self.settings = save_settings({**self.settings, "enabled": True})
            if self.settings["enabled"] and self.httpd is None:
                self.settings = save_settings(self.settings)
                try:
                    self.httpd = server.create_server(self.api, self.settings["port"], lambda: self.settings["token"])
                    threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
                    self.error = ""
                except OSError as exc:
                    self.error = str(exc)

    def stop(self):
        with self.lock:
            if self.httpd:
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None

    def configure(self, enabled, port, regenerate=False):
        with self.lock:
            data = save_settings({"enabled": bool(enabled), "port": port,
                                  "token": secrets.token_urlsafe(32) if regenerate else self.settings["token"]})
            if not data["enabled"] or data["port"] != self.settings["port"]:
                self.stop()
            self.settings = data
            self.start()
        return self.info()

    def info(self):
        info = {"enabled": self.settings["enabled"], "port": self.settings["port"],
                "running": self.httpd is not None, "error": self.error,
                "command": f"tailscale serve --bg {self.settings['port']}"}
        try:
            status = json.loads(_tailscale("status", "--json"))
            serve = json.loads(_tailscale("serve", "status", "--json"))
            info.update(parse_status(status, serve, self.settings["port"]))
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            info.update(logged_in=False, serve_ready=False, tailscale_error=str(exc))
        if info["running"] and info["serve_ready"]:
            import segno
            url = f"https://{info['dns']}/pair?{urlencode({'token': self.settings['token']})}"
            svg = io.BytesIO()
            segno.make(url, micro=False).save(svg, kind="svg", scale=5, dark="#000", light="#fff")
            info.update(pair_url=url, qr_svg=svg.getvalue().decode())
        return info

    def setup(self):
        _tailscale("serve", "--bg", str(self.settings["port"]))
        return self.info()
