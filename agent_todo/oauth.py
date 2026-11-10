"""單一使用者的 OAuth 授權、連線碼及 Claude chat 客戶端管理。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import store

_LOCK = threading.RLock()
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# 表單送出後會 303 轉回 Claude，Chrome 對轉址目標也檢查 form-action。
# no-referrer 會讓瀏覽器在表單 POST 帶 Origin: null，授權頁改用 same-origin。
_PAGE_HEADERS = {"Content-Security-Policy": "default-src 'none'; form-action 'self' https://claude.ai https://claude.com; "
                                            "frame-ancestors 'none'",
                 "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin"}


class OAuthError(ValueError):
    def __init__(self, error, description):
        super().__init__(description)
        self.error = error


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@contextmanager
def _database():
    # 每次重讀，讓撤銷立即生效；整個讀改寫流程共用一把鎖。
    with _LOCK:
        path = store.data_dir() / "oauth.json"
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        db = json.loads(before) if before else {}
        for key in ("clients", "requests", "codes", "tokens"):
            db.setdefault(key, {})
        now = time.time()
        for key in ("requests", "codes", "tokens"):
            db[key] = {k: v for k, v in db[key].items() if v["expires_at"] > now}
        try:
            yield db
        finally:
            # 失敗的兌換也必須存下單次使用及錯誤次數的變更。
            after = json.dumps(db, ensure_ascii=False, indent=2)
            if after != before:  # 只讀的呼叫（每次 MCP 驗證）不重寫檔案
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp")
                temp.write_text(after, encoding="utf-8")
                temp.replace(path)


def base_url(host):
    parsed = urlsplit("//" + host)
    if not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise OAuthError("invalid_request", "主機位址無效")
    scheme = "http" if parsed.hostname in ("127.0.0.1", "localhost") else "https"
    return f"{scheme}://{host}"


def metadata(path, base):
    if path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        return {"resource": base + "/mcp", "authorization_servers": [base],
                "bearer_methods_supported": ["header"]}
    if path == "/.well-known/oauth-authorization-server":
        return {"issuer": base, "authorization_endpoint": base + "/oauth/authorize",
                "token_endpoint": base + "/oauth/token", "registration_endpoint": base + "/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"]}
    return None


def _valid_redirect(uri):
    if not isinstance(uri, str) or any(c.isspace() for c in uri):
        return False
    try:
        url = urlsplit(uri)
        return (url.scheme == "https" and url.netloc in ("claude.ai", "claude.com")
                and not url.fragment and not url.username and not url.password)
    except ValueError:
        return False


def register(data):
    if not isinstance(data, dict):
        raise OAuthError("invalid_client_metadata", "客戶端資料必須是 JSON 物件")
    uris = data.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(_valid_redirect(uri) for uri in uris):
        raise OAuthError("invalid_redirect_uri", "回呼網址只能使用 https://claude.ai/ 或 https://claude.com/")
    name = data.get("client_name", "Claude chat")
    if not isinstance(name, str):
        raise OAuthError("invalid_client_metadata", "客戶端名稱必須是文字")
    with _database() as db:
        if len(db["clients"]) >= 20:
            unused = [cid for cid, c in db["clients"].items() if not c["authorized"]]
            if not unused:
                raise OAuthError("invalid_client_metadata", "已達客戶端上限，請先在電腦 App 撤銷連線")
            oldest = min(unused, key=lambda cid: db["clients"][cid]["created_at"])
            del db["clients"][oldest]
        cid = secrets.token_urlsafe(24)
        created = time.time()
        db["clients"][cid] = {"client_name": name[:100], "redirect_uris": uris,
                              "created_at": created, "authorized": False, "last_used_at": None}
        return {"client_id": cid, "client_name": name[:100], "client_id_issued_at": int(created),
                "redirect_uris": uris, "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}


def new_connect_code():
    code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    expires = time.time() + 600
    with _database() as db:
        db["connect_code"] = {"hash": _hash(code), "expires_at": expires}
        db["failures"] = []  # 使用者在電腦上重新產生，表示是本人，重新計算錯誤次數
    return {"code": code, "expires_at": expires}


def list_clients():
    with _database() as db:
        return [{"client_id": cid, "client_name": c["client_name"], "created_at": c["created_at"],
                 "has_valid_token": any(t["client_id"] == cid for t in db["tokens"].values()),
                 "last_used_at": c["last_used_at"]}
                for cid, c in db["clients"].items() if c["authorized"]]


def revoke_all():
    with _database() as db:
        db.clear()
    return {"revoked": True}


def _page(message, form=""):
    return ("<!doctype html><html lang='zh-Hant'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>待辦清單連線授權</title><body><h1>待辦清單連線授權</h1>"
            f"<p>{html.escape(message)}</p>{form}</body></html>")


def error_page(message):
    return _page(message), 400, _PAGE_HEADERS


def _redirect(request, **values):
    uri = urlsplit(request["redirect_uri"])
    query = parse_qsl(uri.query, keep_blank_values=True) + list(values.items())
    if "state" in request:
        query.append(("state", request["state"]))
    return None, 303, {"Location": urlunsplit(uri._replace(query=urlencode(query)))}


def authorize_get(params, base, paired=False):
    with _database() as db:
        client = db["clients"].get(params.get("client_id"))
        if not client or params.get("redirect_uri") not in client["redirect_uris"]:
            return error_page("客戶端或回呼網址無效，請回 Claude 重新連線。")
        if (params.get("response_type") != "code" or params.get("code_challenge_method") != "S256"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.get("code_challenge", ""))):
            return _redirect(params, error="invalid_request", error_description="需要授權碼流程及 S256 PKCE")
        resource = params.get("resource", base + "/mcp")
        if resource != base + "/mcp":
            return _redirect(params, error="invalid_target", error_description="資源網址不符")
        request_id = secrets.token_urlsafe(32)
        # 只保存已驗證的參數，POST 不採用瀏覽器傳回的 client_id 或回呼網址。
        request = {k: params[k] for k in ("client_id", "redirect_uri", "code_challenge", "state") if k in params}
        request.update(resource=resource, expires_at=time.time() + 600)
        db["requests"][_hash(request_id)] = request
        field = ("<p>此瀏覽器已配對，按允許即可連線。</p>" if paired else
                 "<p><label>連線碼 <input name='connect_code' maxlength='8' autocomplete='off' "
                 "autocapitalize='characters'></label></p><p>請在電腦 App 產生連線碼，十分鐘內有效。"
                 "已用 QR code 配對過的手機可以不填，直接按允許。</p>")
        form = (f"<form method='post' action='/oauth/authorize'><input type='hidden' name='request_id' "
                f"value='{html.escape(request_id, quote=True)}'>{field}"
                "<button name='decision' value='allow'>允許</button> "
                "<button name='decision' value='deny'>拒絕</button></form>")
        return _page(client["client_name"] + " 想讀寫你的待辦清單", form), 200, _PAGE_HEADERS


def authorize_post(params, base, paired=False):
    with _database() as db:
        request = db["requests"].pop(_hash(params.get("request_id", "")), None)
        if not request or request["client_id"] not in db["clients"] or request["resource"] != base + "/mcp":
            return error_page("授權請求已過期或已使用，請回 Claude 重新連線。")
        if params.get("decision") == "deny":
            return _redirect(request, error="access_denied")
        if params.get("decision") != "allow":
            return error_page("請選擇允許或拒絕。")
        if not paired:
            now = time.time()
            failures = [at for at in db.get("failures", []) if at > now - 600]
            code = db.get("connect_code", {})
            valid = (code.get("expires_at", 0) > now and
                     hmac.compare_digest(_hash(params.get("connect_code", "")), code.get("hash", "")))
            if not valid:
                failures.append(now)
                db["failures"] = failures
                if len(failures) >= 5:
                    db.pop("connect_code", None)
                return error_page("連線碼錯誤或已失效，請回 Claude 重新連線；累計錯五次需在電腦 App 重新產生。")
            db.pop("connect_code", None)
        code = secrets.token_urlsafe(32)
        db["codes"][_hash(code)] = {**request, "expires_at": time.time() + 300}
        db["clients"][request["client_id"]]["authorized"] = True
        return _redirect(request, code=code)


def exchange(params, base):
    with _database() as db:
        cid = params.get("client_id")
        if cid not in db["clients"]:
            raise OAuthError("invalid_client", "客戶端不存在")
        grant = params.get("grant_type")
        if grant == "authorization_code":
            record = db["codes"].pop(_hash(params.get("code", "")), None)
            verifier = params.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            valid = (record and record["client_id"] == cid and record["redirect_uri"] == params.get("redirect_uri")
                     and re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
                     and hmac.compare_digest(record["code_challenge"], challenge))
        elif grant == "refresh_token":
            key = _hash(params.get("refresh_token", ""))
            record = db["tokens"].get(key)
            valid = record and record["kind"] == "refresh" and record["client_id"] == cid
        else:
            raise OAuthError("unsupported_grant_type", "不支援這種授權方式")
        if (not valid or record["resource"] != base + "/mcp"
                or params.get("resource", record["resource"]) != record["resource"]):
            raise OAuthError("invalid_grant", "授權已失效或驗證資料不符")
        if grant == "refresh_token":
            del db["tokens"][key]
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        for value, kind, lifetime in ((access, "access", 3600), (refresh, "refresh", 30 * 86400)):
            db["tokens"][_hash(value)] = {"client_id": cid, "kind": kind, "resource": record["resource"],
                                          "expires_at": now + lifetime}
        db["clients"][cid]["last_used_at"] = now
        return {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "refresh_token": refresh}


def validate_access(value, resource):
    with _database() as db:
        record = db["tokens"].get(_hash(value))
        if (not record or record["kind"] != "access" or record["resource"] != resource
                or record["client_id"] not in db["clients"]):
            return False
        client = db["clients"][record["client_id"]]
        now = time.time()
        if now - (client["last_used_at"] or 0) > 60:  # 最後使用時間精確到分鐘就夠
            client["last_used_at"] = now
        return True
