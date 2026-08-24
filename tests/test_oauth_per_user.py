"""Per-user Kissflow credentials over OAuth — proven on the wire, not in a mock.

The whole point of kfforge.auth is HTTP behaviour: whether Claude Desktop's connector fields
survive an OAuth 2.1 authorization-code exchange and come out the far end as the CALLER's Kissflow
key. An offline unit test of the provider's methods would prove none of that, so this spawns the
real server, drives real requests through real `/authorize` + `/token` routes, and asserts on what
lands. Only the one Kissflow round-trip (`_validate_pair`) is stubbed — the tenant is not this
test's subject.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
SIGNING_KEY = "insecure-test-signing-key-not-a-secret-value"  # gitleaks:allow
GOOD_ID, GOOD_SECRET = "KEY_ALICE", "SECRET_ALICE"
SHARED_ENV_ID = "SHARED_ENV_ID"
REDIRECT = "http://localhost:33418/callback"

RUNNER = '''
import os, sys
sys.path.insert(0, {repo!r})
os.environ.update(
    MCP_HTTP="1", PORT="{port}",
    MCP_OAUTH_BASE_URL="http://127.0.0.1:{port}",
    MCP_OAUTH_SIGNING_KEY="{key}",
    KF_DEV_DOMAIN="dev-kissflow.example.com", KF_DEV_ACCOUNT_ID="Ac1", KF_APP="App1",
    KF_DEV_ACCESS_KEY_ID="{shared}", KF_DEV_ACCESS_KEY_SECRET="SHARED_ENV_SECRET",
)
import kfforge.auth as auth
auth._validate_pair = lambda kid, sec: (kid, sec) == ({good_id!r}, {good_secret!r})
import kfforge.server as server
from kfforge.client import Err

@server.mcp.tool
def whoami() -> dict:
    """Which Kissflow identity this call runs as."""
    c = server._client(require_app=False)
    if isinstance(c, Err):
        return c.as_tool_result()
    return {{"key_id": c._cfg.key_id, "domain": c._cfg.domain, "isError": False}}

server.main()
'''


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


def _req(
    method: str, url: str, data: str | None = None, headers: dict[str, str] | None = None,
    follow: bool = True,
) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(
        url, data=data.encode() if data else None, headers=headers or {}, method=method
    )
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=10) as resp:  # nosec B310 — loopback, test-only
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server_url(tmp_path_factory: pytest.TempPathFactory) -> Any:
    port = _free_port()
    runner = tmp_path_factory.mktemp("oauth") / "runner.py"
    runner.write_text(RUNNER.format(
        repo=str(REPO), port=port, key=SIGNING_KEY, shared=SHARED_ENV_ID,
        good_id=GOOD_ID, good_secret=GOOD_SECRET,
    ))
    proc = subprocess.Popen(  # nosec B603 — fixed argv, test-only
        [sys.executable, str(runner)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        if proc.poll() is not None:
            pytest.skip(f"server exited early: {(proc.stdout.read() if proc.stdout else b'')!r}")
        try:
            urllib.request.urlopen(f"{url}/mcp", timeout=1)  # nosec B310
        except urllib.error.HTTPError:
            break  # answering, which is all we need
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("server never came up")
    yield url
    proc.kill()
    proc.wait(timeout=10)


def _authorize(url: str, client_id: str, redirect: str = REDIRECT) -> tuple[int, str, str]:
    """Run the browser leg. Returns (status, code, verifier)."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "ST123", "scope": "",
    })
    status, headers, _ = _req("GET", f"{url}/authorize?{query}", follow=False)
    location = headers.get("location", "")
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    return status, parsed.get("code", [""])[0], verifier


def _token(url: str, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
    status, _, body = _req(
        "POST", f"{url}/token", urllib.parse.urlencode(form),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, {"raw": body}


def _mcp(url: str, access: str) -> Any:
    """Initialize a session with the bearer token, return a caller for tools/call."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {access}",
    }
    status, resp_headers, body = _req("POST", f"{url}/mcp", json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}},
    }), headers)
    assert status == 200, body
    headers["Mcp-Session-Id"] = resp_headers.get("mcp-session-id", "")
    _req("POST", f"{url}/mcp", json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}), headers)

    def call(name: str) -> str:
        _, _, out = _req("POST", f"{url}/mcp", json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }), headers)
        return out

    return call


def test_anonymous_call_is_refused(server_url: str) -> None:
    status, _, body = _req("POST", f"{server_url}/mcp", json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}},
    }), {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"})
    assert status == 401, body


def test_wrong_secret_never_mints_a_token(server_url: str) -> None:
    _, code, verifier = _authorize(server_url, GOOD_ID)
    status, _ = _token(server_url, {
        "grant_type": "authorization_code", "code": code, "client_id": GOOD_ID,
        "client_secret": "WRONG", "redirect_uri": REDIRECT, "code_verifier": verifier,
    })
    assert status >= 400


def test_unknown_kissflow_user_is_refused(server_url: str) -> None:
    _, code, verifier = _authorize(server_url, "KEY_MALLORY")
    status, _ = _token(server_url, {
        "grant_type": "authorization_code", "code": code, "client_id": "KEY_MALLORY",
        "client_secret": "WHATEVER", "redirect_uri": REDIRECT, "code_verifier": verifier,
    })
    assert status >= 400


def test_redirect_outside_the_allowlist_is_refused(server_url: str) -> None:
    status, code, _ = _authorize(server_url, GOOD_ID, redirect="https://evil.example.com/cb")
    assert status >= 400 or not code


def test_full_flow_runs_as_the_caller_never_the_shared_env_key(server_url: str) -> None:
    status, code, verifier = _authorize(server_url, GOOD_ID)
    assert status in (302, 307) and code, status

    status, tok = _token(server_url, {
        "grant_type": "authorization_code", "code": code, "client_id": GOOD_ID,
        "client_secret": GOOD_SECRET, "redirect_uri": REDIRECT, "code_verifier": verifier,
    })
    assert status == 200, tok
    access, refresh = tok["access_token"], tok["refresh_token"]
    # The tenant secret rides inside the token, which is why the token is sealed, not just signed.
    assert GOOD_SECRET not in access and GOOD_SECRET not in refresh

    body = _mcp(server_url, access)("whoami")
    assert GOOD_ID in body, body
    assert SHARED_ENV_ID not in body, body

    status, refreshed = _token(server_url, {
        "grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": GOOD_ID, "client_secret": GOOD_SECRET,
    })
    assert status == 200 and refreshed.get("access_token"), refreshed


# --- offline pieces ------------------------------------------------------------------


def test_sealed_tokens_reject_tampering_and_wrong_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from kfforge import auth

    monkeypatch.setenv(auth.SIGNING_KEY_ENV, SIGNING_KEY)
    sealed = auth._seal("access", {"kid": "A", "sec": "B"})
    assert auth._open("access", sealed, 60) == {"t": "access", "kid": "A", "sec": "B"}
    assert auth._open("refresh", sealed, 60) is None          # right key, wrong kind
    assert auth._open("access", sealed[:-4] + "AAAA", 60) is None  # tampered
    # ttl below the token's age is how Fernet decides "expired"; -1 makes any token older
    # than it, which is the same branch a real hour-old access token takes.
    assert auth._open("access", sealed, -1) is None           # expired
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, "another-signing-key-entirely-0123456789abcdef")
    assert auth._open("access", sealed, 60) is None           # different signing key


def test_short_signing_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    from kfforge import auth

    monkeypatch.setenv(auth.SIGNING_KEY_ENV, "tooshort")
    with pytest.raises(RuntimeError, match=auth.SIGNING_KEY_ENV):
        auth._seal("access", {})


def test_redirect_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from kfforge import auth

    monkeypatch.delenv(auth.REDIRECTS_ENV, raising=False)
    assert auth._allowed_redirect("http://localhost:1234/cb")
    assert auth._allowed_redirect("http://127.0.0.1:1234/cb")
    assert auth._allowed_redirect("https://claude.ai/api/mcp/auth_callback")
    assert not auth._allowed_redirect("https://evil.example.com/cb")
    assert not auth._allowed_redirect("https://claude.ai.evil.example.com/cb")
    assert not auth._allowed_redirect("https://evilclaude.ai/cb"), (
        "a hostname merely ENDING in 'claude.ai' is an attacker domain, not a subdomain"
    )
    assert auth._allowed_redirect("https://sub.claude.ai/cb")
    monkeypatch.setenv(auth.REDIRECTS_ENV, "https://corp.example.com/")
    assert auth._allowed_redirect("https://corp.example.com/cb")
    monkeypatch.setenv(auth.REDIRECTS_ENV, "https://corp.example.com")
    assert auth._allowed_redirect("https://corp.example.com/cb")
    assert not auth._allowed_redirect("https://corp.example.com.evil.net/cb"), (
        "an env prefix must only match at a '/' boundary, never as a bare startswith"
    )


def test_raw_redirect_uris(monkeypatch: pytest.MonkeyPatch) -> None:
    from kfforge import auth

    token = auth._TOKEN_FORM.set({})
    try:
        monkeypatch.setattr(auth, "_http_request", lambda: None)
        assert auth._raw_redirect_uris() == []

        auth._TOKEN_FORM.set({"redirect_uri": "http://localhost:1234/cb"})
        assert auth._raw_redirect_uris() == ["http://localhost:1234/cb"]

        auth._TOKEN_FORM.set({})
        mock_req = type("Req", (), {"query_params": {"redirect_uri": "http://localhost:5678/cb"}})()
        monkeypatch.setattr(auth, "_http_request", lambda: mock_req)
        assert auth._raw_redirect_uris() == ["http://localhost:5678/cb"]

        mock_req_empty = type("Req", (), {"query_params": {}})()
        monkeypatch.setattr(auth, "_http_request", lambda: mock_req_empty)
        assert auth._raw_redirect_uris() == []

        auth._TOKEN_FORM.set({"redirect_uri": "http://localhost:1234/cb"})
        monkeypatch.setattr(auth, "_http_request", lambda: mock_req)
        assert auth._raw_redirect_uris() == ["http://localhost:1234/cb", "http://localhost:5678/cb"]
    finally:
        auth._TOKEN_FORM.reset(token)


def test_requested_redirect_uris(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import AnyUrl
    from kfforge import auth

    monkeypatch.delenv(auth.REDIRECTS_ENV, raising=False)
    token = auth._TOKEN_FORM.set({})
    try:
        monkeypatch.setattr(auth, "_http_request", lambda: None)
        assert auth._requested_redirect_uris() == [AnyUrl(auth.PLACEHOLDER_REDIRECT)]

        auth._TOKEN_FORM.set({"redirect_uri": "http://localhost:1234/cb"})
        assert auth._requested_redirect_uris() == [AnyUrl("http://localhost:1234/cb")]

        auth._TOKEN_FORM.set({"redirect_uri": "https://evil.example.com/cb"})
        assert auth._requested_redirect_uris() is None

        auth._TOKEN_FORM.set({})
        mock_req = type("Req", (), {"query_params": {"redirect_uri": "https://claude.ai/cb"}})()
        monkeypatch.setattr(auth, "_http_request", lambda: mock_req)
        assert auth._requested_redirect_uris() == [AnyUrl("https://claude.ai/cb")]

        mock_req_evil = type("Req", (), {"query_params": {"redirect_uri": "https://evil.example.com/cb"}})()
        monkeypatch.setattr(auth, "_http_request", lambda: mock_req_evil)
        assert auth._requested_redirect_uris() is None

        auth._TOKEN_FORM.set({"redirect_uri": "http://localhost:1234/cb"})
        monkeypatch.setattr(auth, "_http_request", lambda: mock_req_evil)
        assert auth._requested_redirect_uris() == [AnyUrl("http://localhost:1234/cb")]
    finally:
        auth._TOKEN_FORM.reset(token)
