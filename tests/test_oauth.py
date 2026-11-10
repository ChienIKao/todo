import base64
import hashlib
import http.client
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from agent_todo import mobile, oauth, server, store
from agent_todo.api import Api

BASE = "https://pc.tail.ts.net"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TODO_HOME", str(tmp_path))


@pytest.fixture
def remote():
    httpd = server.create_server(Api(), 0, lambda: "pair-secret")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def request(path, method="GET", *, data=None, form=None, headers=None, raw=None):
        hdr = {"Host": "pc.tail.ts.net", **(headers or {})}
        if data is not None:
            raw = json.dumps(data).encode()
            hdr.setdefault("Content-Type", "application/json")
        if form is not None:
            raw = urlencode(form).encode()
            hdr.setdefault("Content-Type", "application/x-www-form-urlencoded")
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        try:
            conn.request(method, path, raw, hdr)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    yield request
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def register(request, uri=REDIRECT, **extra):
    status, headers, body = request("/oauth/register", "POST", data={
        "redirect_uris": [uri], "client_name": "我的 Claude", **extra})
    assert status == 201, body
    assert headers["Cache-Control"] == "no-store"
    return json.loads(body)


def params(client, **extra):
    return {"client_id": client["client_id"], "redirect_uri": client["redirect_uris"][0],
            "response_type": "code", "code_challenge": CHALLENGE, "code_challenge_method": "S256",
            "resource": BASE + "/mcp", "state": "原樣 + & 測試", **extra}


def begin(request, client, headers=None, **extra):
    result = request("/oauth/authorize?" + urlencode(params(client, **extra)), headers=headers)
    assert result[0] == 200, result[2]
    assert result[1]["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in result[1]["Content-Security-Policy"]
    return re.search("name='request_id' value='([^']+)'", result[2].decode()).group(1), result


def authorize(request, client, *, headers=None, connect_code=None):
    rid, _ = begin(request, client, headers)
    code = connect_code or oauth.new_connect_code()["code"]
    result = request("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": code}, headers=headers)
    assert result[0] == 303, result[2]
    query = parse_qs(urlsplit(result[1]["Location"]).query)
    assert query["state"] == ["原樣 + & 測試"]
    return query["code"][0]


def redeem(request, client, code, **extra):
    return request("/oauth/token", "POST", form={"grant_type": "authorization_code", "code": code,
        "client_id": client["client_id"], "redirect_uri": client["redirect_uris"][0],
        "code_verifier": VERIFIER, **extra})


def connected(request):
    client = register(request)
    status, headers, body = redeem(request, client, authorize(request, client))
    assert status == 200, body
    assert headers["Cache-Control"] == "no-store"
    return client, json.loads(body)


def rpc(request, access, method="tools/list", params=None, **extra):
    return request("/mcp", "POST", data={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                   headers={"Authorization": "Bearer " + access, **extra})


def test_metadata(remote):
    for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        status, _, body = remote(path)
        assert status == 200
        assert json.loads(body) == {"resource": BASE + "/mcp", "authorization_servers": [BASE],
                                    "bearer_methods_supported": ["header"]}
    status, _, body = remote("/.well-known/oauth-authorization-server")
    meta = json.loads(body)
    assert status == 200 and meta["issuer"] == BASE
    for key, path in (("authorization_endpoint", "authorize"), ("token_endpoint", "token"), ("registration_endpoint", "register")):
        assert meta[key] == BASE + "/oauth/" + path
    assert meta["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert meta["response_types_supported"] == ["code"]
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["token_endpoint_auth_methods_supported"] == ["none"]
    assert json.loads(remote("/.well-known/oauth-protected-resource", headers={"Host": "localhost:8767"})[2])["resource"] == "http://localhost:8767/mcp"
    assert oauth.base_url("127.0.0.1:1234") == "http://127.0.0.1:1234"


@pytest.mark.parametrize("uri", ["https://claude.ai/callback", "https://claude.com/callback"])
def test_registration_hosts(remote, uri):
    client = register(remote, uri, client_name="名" * 110)
    assert client["redirect_uris"] == [uri]
    assert len(client["client_name"]) == 100
    assert client["token_endpoint_auth_method"] == "none"


@pytest.mark.parametrize("uri", ["https://evil.example/callback", "http://claude.ai/callback",
    "https://claude.ai.evil/callback", "https://sub.claude.ai/callback", "https://claude.ai@evil.example/",
    "https://evil@claude.ai/callback", "https://claude.ai/callback#fragment", 42])
def test_registration_rejects_redirect(remote, uri):
    status, _, body = remote("/oauth/register", "POST", data={"redirect_uris": [uri]})
    assert status == 400 and json.loads(body)["error"] == "invalid_redirect_uri"


def test_registration_limit(remote):
    first = register(remote)["client_id"]
    for _ in range(20):
        register(remote)
    with oauth._database() as db:
        assert len(db["clients"]) == 20 and first not in db["clients"]
        for client in db["clients"].values():
            client["authorized"] = True
    status, _, body = remote("/oauth/register", "POST", data={"redirect_uris": [REDIRECT]})
    assert status == 400 and json.loads(body)["error"] == "invalid_client_metadata"


def test_complete_flow(remote):
    client, tokens = connected(remote)
    access = tokens["access_token"]
    assert tokens["expires_in"] == 3600 and tokens["token_type"] == "Bearer"
    status, headers, body = rpc(remote, access, "initialize", {"clientInfo": {"name": "冒名作者"}, "protocolVersion": "2025-06-18"})
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["result"]["protocolVersion"] == "2025-06-18"
    assert "add_todo" in [t["name"] for t in json.loads(rpc(remote, access)[2])["result"]["tools"]]
    assert rpc(remote, access, "tools/call", {"name": "add_todo", "arguments": {"title": "透過 Claude 新增"}})[0] == 200
    assert store.get(1)["title"] == "透過 Claude 新增"
    rpc(remote, access, "tools/call", {"name": "add_note", "arguments": {"id": 1, "text": "進度"}})
    assert store.get(1)["notes"][-1]["author"] == "claude-chat"
    result = remote("/oauth/token", "POST", form={"grant_type": "refresh_token", "client_id": client["client_id"], "refresh_token": tokens["refresh_token"]})
    assert result[0] == 200
    fresh = json.loads(result[2])
    assert fresh["refresh_token"] != tokens["refresh_token"]
    assert rpc(remote, fresh["access_token"])[0] == 200
    assert remote("/oauth/token", "POST", form={"grant_type": "refresh_token", "client_id": client["client_id"], "refresh_token": tokens["refresh_token"]})[0] == 400
    stored = (store.data_dir() / "oauth.json").read_text(encoding="utf-8")
    for token in (*tokens.values(), fresh["access_token"], fresh["refresh_token"]):
        if isinstance(token, str) and token != "Bearer":
            assert token not in stored
    assert oauth.list_clients()[0]["has_valid_token"]
    assert oauth.list_clients()[0]["last_used_at"]
    oauth.revoke_all()
    assert rpc(remote, access)[0] == 401
    assert rpc(remote, fresh["access_token"])[0] == 401
    assert oauth.list_clients() == []


def test_cookie_authorization(remote):
    client = register(remote)
    cookie = remote("/pair?token=pair-secret")[1]["Set-Cookie"].split(";", 1)[0]
    headers = {"Cookie": cookie}
    rid, result = begin(remote, client, headers)
    assert "name='connect_code'" not in result[2].decode()
    result = remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow"}, headers=headers)
    code = parse_qs(urlsplit(result[1]["Location"]).query)["code"][0]
    assert redeem(remote, client, code)[0] == 200
    assert remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow"}, headers=headers)[0] == 400


@pytest.mark.parametrize("changes", [{"code_verifier": "x" * 43}, {"redirect_uri": "https://claude.com/other"}])
def test_invalid_exchange(remote, changes):
    client = register(remote)
    code = authorize(remote, client)
    status, headers, body = redeem(remote, client, code, **changes)
    assert status == 400 and json.loads(body)["error"] == "invalid_grant"
    assert headers["Cache-Control"] == "no-store"


def test_code_expiry_and_reuse(remote, monkeypatch):
    client = register(remote)
    now = oauth.time.time()
    code = authorize(remote, client)
    monkeypatch.setattr(oauth.time, "time", lambda: now + 301)
    assert redeem(remote, client, code)[0] == 400
    code = authorize(remote, client)
    assert redeem(remote, client, code)[0] == 200
    assert redeem(remote, client, code)[0] == 400


def test_connect_code_failures_and_single_use(remote):
    client = register(remote)
    code = oauth.new_connect_code()["code"]
    assert len(code) == 8 and set(code) <= set(oauth._ALPHABET)
    for _ in range(5):
        rid, _ = begin(remote, client)
        assert remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": "錯誤"})[0] == 400
    rid, _ = begin(remote, client)
    assert remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": code})[0] == 400
    code = oauth.new_connect_code()["code"]
    authorize(remote, client, connect_code=code)
    rid, _ = begin(remote, client)
    assert remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": code})[0] == 400


def test_request_and_connect_code_expiry(remote, monkeypatch):
    client = register(remote)
    now = oauth.time.time()
    code = oauth.new_connect_code()["code"]
    rid, _ = begin(remote, client)
    monkeypatch.setattr(oauth.time, "time", lambda: now + 601)
    assert remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": code})[0] == 400
    rid, _ = begin(remote, client)
    assert remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": code})[0] == 400


def test_authorization_validation_and_denial(remote):
    client = register(remote, client_name="<script>壞</script>")
    rid, page = begin(remote, client)
    assert "<script>" not in page[2].decode() and "&lt;script&gt;" in page[2].decode()
    denied = remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "deny"})
    query = parse_qs(urlsplit(denied[1]["Location"]).query)
    assert denied[0] == 303 and query["error"] == ["access_denied"] and query["state"] == ["原樣 + & 測試"]
    for changes in ({"client_id": "missing"}, {"redirect_uri": "https://evil.example/"}):
        result = remote("/oauth/authorize?" + urlencode(params(client, **changes)))
        assert result[0] == 400 and "Location" not in result[1]
    for changes in ({"response_type": "token"}, {"code_challenge": ""}, {"code_challenge_method": "plain"}, {"resource": "https://other/mcp"}):
        result = remote("/oauth/authorize?" + urlencode(params(client, **changes)))
        assert result[0] == 303 and "error=" in result[1]["Location"]


def test_mcp_authentication(remote):
    for headers in ({}, {"Authorization": "Bearer bad"}, {"Authorization": "Bearer pair-secret"},
                    {"Cookie": server.COOKIE + "=pair-secret"}):
        status, response, _ = remote("/mcp", "POST", data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)
        assert status == 401
        assert response["WWW-Authenticate"] == f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource"'
    assert remote("/mcp")[0] == 405
    assert remote("/mcp", headers={"Origin": "https://evil.example"})[0] == 403
    assert remote("/mcp", "DELETE")[0] == 401
    assert remote("/mcp", "DELETE", headers={"Authorization": "Bearer pair-secret"})[0] == 405


def test_mcp_messages_and_origin(remote):
    _, tokens = connected(remote)
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    for message in ({"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "method": "ping"}, {"jsonrpc": "2.0", "id": 2, "result": {}}):
        result = remote("/mcp", "POST", data=message, headers=headers)
        assert result[0] == 202 and result[2] == b""
    for origin in (BASE, "https://claude.ai", "https://claude.com"):
        assert rpc(remote, tokens["access_token"], Origin=origin)[0] == 200
    for origin in ("https://evil.example", "https://claude.ai.evil", "null", ""):
        assert rpc(remote, tokens["access_token"], Origin=origin)[0] == 403
    for raw in (b"{", b"[]", b"null", b'{"jsonrpc":"2.0","method":"initialize","params":[]}'):
        assert remote("/mcp", "POST", raw=raw, headers=headers)[0] == 400


def test_token_expiry_audience_and_client(remote, monkeypatch):
    client, tokens = connected(remote)
    second = register(remote)
    status, _, body = remote("/oauth/token", "POST", form={"grant_type": "refresh_token", "client_id": second["client_id"], "refresh_token": tokens["refresh_token"]})
    assert status == 400 and json.loads(body)["error"] == "invalid_grant"
    assert rpc(remote, tokens["access_token"], Host="other.ts.net")[0] == 401
    for form, error in (({"client_id": "missing"}, "invalid_client"),
                        ({"client_id": client["client_id"], "grant_type": "password"}, "unsupported_grant_type")):
        result = remote("/oauth/token", "POST", form=form)
        assert result[0] == 400 and json.loads(result[2])["error"] == error
    now = oauth.time.time()
    monkeypatch.setattr(oauth.time, "time", lambda: now + 3601)
    assert rpc(remote, tokens["access_token"])[0] == 401
    monkeypatch.setattr(oauth.time, "time", lambda: now + 31 * 86400)
    assert remote("/oauth/token", "POST", form={"client_id": client["client_id"], "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})[0] == 400


def test_oauth_concurrent_registration():
    with ThreadPoolExecutor(max_workers=6) as pool:
        clients = list(pool.map(lambda _: oauth.register({"redirect_uris": [REDIRECT]}), range(30)))
    assert len({c["client_id"] for c in clients}) == 30
    assert len(json.loads((store.data_dir() / "oauth.json").read_text(encoding="utf-8"))["clients"]) == 20


def test_management_stays_desktop_only(remote):
    api = Api()
    assert len(api.mobile_connect_code()["code"]) == 8
    assert api.mobile_oauth_clients() == []
    assert api.mobile_oauth_revoke() == {"revoked": True}
    for name in ("mobile_connect_code", "mobile_oauth_clients", "mobile_oauth_revoke"):
        assert name not in server.REMOTE_METHODS
        assert remote("/api/" + name, "POST", data=[], headers={"Authorization": "Bearer pair-secret", "Origin": BASE})[0] == 404
    assert remote("/api/list_todos", "POST", data=[], headers={"Authorization": "Bearer pair-secret"})[0] == 403


def test_funnel_status_and_setup(monkeypatch):
    status = {"BackendState": "Running", "Self": {"DNSName": "pc.tail.ts.net."}}
    serve = {"TCP": {"443": {"HTTPS": True}}, "Web": {
        "pc.tail.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8767"}}}}}
    state = {"funnel": False, "proxy": True}
    calls = []

    def tailscale(*args, **kwargs):
        calls.append(args)
        if args == ("status", "--json"):
            return json.dumps(status)
        if args == ("serve", "status", "--json"):
            return json.dumps({**serve, "AllowFunnel": {"pc.tail.ts.net:443": state["funnel"]},
                               "Web": serve["Web"] if state["proxy"] else {}})
        if args == ("funnel", "--bg", "8767"):
            state.update(funnel=True, proxy=True)
        elif args == ("funnel", "--https=443", "off"):
            state.update(funnel=False, proxy=False)
        elif args == ("serve", "--bg", "8767"):
            state["proxy"] = True
        else:
            pytest.fail(str(args))
        return ""

    monkeypatch.setattr(mobile, "_tailscale", tailscale)
    access = mobile.MobileAccess(Api())
    access.httpd = object()
    access.settings = mobile.save_settings({**access.settings, "enabled": True, "public": True})
    assert not access.info()["ready"]
    info = access.setup()
    assert info["serve_ready"] and info["funnel_on"] and info["consistent"] and info["ready"]
    assert info["mcp_url"] == BASE + "/mcp"
    assert ("funnel", "--bg", "8767") in calls
    access.settings["public"] = False
    info = access.info()
    assert not info["ready"] and "狀態不一致" in info["status_message"] and "mcp_url" not in info
    calls.clear()
    info = access.setup()
    assert calls[0] == ("serve", "--bg", "8767")
    assert ("funnel", "--https=443", "off") in calls
    assert calls.count(("serve", "--bg", "8767")) == 2
    assert not info["funnel_on"] and info["ready"] and "mcp_url" not in info


def test_funnel_enable_url(monkeypatch):
    access = mobile.MobileAccess(Api())
    access.settings["public"] = True
    url = "https://login.tailscale.com/f/funnel?node=abc"
    calls = []

    def tailscale(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("請開通 " + url)

    monkeypatch.setattr(mobile, "_tailscale", tailscale)
    monkeypatch.setattr(access, "info", lambda: {"serve_ready": False})
    assert access.setup()["serve_enable_url"] == url
    assert calls == [("funnel", "--bg", "8767")]


def test_oauth_endpoints_only_remote():
    httpd = server.create_server(Api(), 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        for path, method in (("/mcp", "GET"), ("/mcp", "POST"), ("/.well-known/oauth-authorization-server", "GET"), ("/oauth/register", "POST")):
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
            conn.request(method, path)
            response = conn.getresponse()
            assert response.status == 404
            response.read()
            conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_review_fixes(remote):
    # 註冊要求其他認證方式時改用 none，不拒絕
    status, _, body = remote("/oauth/register", "POST", data={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "client_secret_post"})
    assert status == 201 and json.loads(body)["token_endpoint_auth_method"] == "none"
    client = register(remote)
    _, (_, headers, _) = begin(remote, client)
    # 授權頁不能用 no-referrer（表單 POST 會變 Origin: null），且 form-action 要允許轉回 Claude
    assert headers["Referrer-Policy"] == "same-origin"
    assert "https://claude.ai" in headers["Content-Security-Policy"]
    # 錯五次作廢後，重新產生的連線碼重新計算錯誤次數
    for _ in range(5):
        rid, _ = begin(remote, client)
        remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": "WRONG"})
    code = oauth.new_connect_code()["code"]
    rid, _ = begin(remote, client)
    remote("/oauth/authorize", "POST", form={"request_id": rid, "decision": "allow", "connect_code": "WRONG"})
    authorize(remote, client, connect_code=code)
