"""Deterministic two-gate OAuth tests over FastMCP 3.4.7's local ASGI routes."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlparse

import anyio
import httpx
import pytest
from fastmcp import FastMCP, settings
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oauth_proxy.proxy import ClientCode
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.provider import construct_redirect_uri
from starlette.middleware import Middleware as ASGIMiddleware

from kfforge import auth

SIGNING_KEY = "insecure-test-signing-key-not-a-secret-value"  # gitleaks:allow
GOOD_ID, GOOD_SECRET = "KEY_ALICE", "SECRET_ALICE"  # gitleaks:allow
REDIRECT = "http://localhost:33418/callback"
BASE_URL = "http://127.0.0.1:30000"


def _run(fn: Any, *args: Any, **kwargs: Any) -> Any:
    async def invoke() -> Any:
        return await fn(*args, **kwargs)

    return anyio.run(invoke)


def _run_concurrent(*awaitables: Any) -> list[Any]:
    async def invoke() -> list[Any]:
        return list(await asyncio.gather(*awaitables))

    return anyio.run(invoke)


def _jwt_payload(claims: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"fake.{encoded}.signature"


def _fake_claims(token: str) -> dict[str, Any]:
    encoded = token.split(".", 2)[1]
    encoded += "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(encoded).decode())


class _FakeVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = _fake_claims(token)
        except (IndexError, ValueError):
            return None
        if claims.get("_invalid_entra_token"):
            return None
        return AccessToken(
            token=token,
            client_id="azure-client",
            scopes=["mcp-access"],
            expires_at=int(time.time()) + 3600,
            claims=claims,
        )


class _FakeIdentityProvider(auth.KissflowOAuthProvider):
    """Use a local callback/code store while retaining AzureProvider exchange and storage code."""

    idp_variant = "valid"

    def _idp_token(self, client_id: str) -> str:
        if self.idp_variant == "invalid" or client_id == "BAD_ENTRA":
            return _jwt_payload(
                {
                    "sub": f"sub-{client_id}",
                    "oid": f"oid-{client_id}",
                    "preferred_username": "alice@example.com",
                    "_invalid_entra_token": True,
                }
            )
        claims: dict[str, Any] = {
            "sub": f"sub-{client_id}",
            "oid": f"oid-{client_id}",
            "preferred_username": "alice@example.com",
        }
        if self.idp_variant == "missing-email" or client_id == "NO_EMAIL":
            claims.pop("preferred_username")
        return _jwt_payload(claims)

    async def authorize(self, client: Any, params: Any) -> str:
        """Create the same server-side code shape as the Entra callback, without network I/O."""
        code = secrets.token_urlsafe(32)
        scopes = params.scopes or ["mcp-access"]
        await self._code_store.put(
            key=code,
            value=ClientCode(
                code=code,
                client_id=client.client_id,
                redirect_uri=str(params.redirect_uri),
                code_challenge=params.code_challenge,
                code_challenge_method="S256",
                scopes=scopes,
                idp_tokens={
                    "access_token": self._idp_token(str(client.client_id)),
                    "refresh_token": "upstream-refresh",
                    "expires_in": 3600,
                    "refresh_expires_in": 86400,
                    "scope": "api://azure-client/mcp-access",
                },
                expires_at=time.time() + 300,
                created_at=time.time(),
            ),
            ttl=300,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    @asynccontextmanager
    async def _upstream_oauth_client(self) -> Any:
        provider = self

        class _RefreshClient:
            async def refresh_token(self, **_: Any) -> dict[str, Any]:
                if provider.idp_variant == "invalid":
                    access_token = _jwt_payload(
                        {
                            "sub": "sub-refresh-invalid",
                            "oid": "oid-refresh-invalid",
                            "preferred_username": "alice@example.com",
                            "_invalid_entra_token": True,
                        }
                    )
                else:
                    access_token = _jwt_payload(
                        {
                            "sub": "sub-refresh",
                            "oid": "oid-refresh",
                            "preferred_username": "alice@example.com",
                        }
                    )
                return {
                    "access_token": access_token,
                    "expires_in": 3600,
                    "scope": "api://azure-client/mcp-access",
                }

        yield _RefreshClient()


class _Harness:
    def __init__(self, provider: _FakeIdentityProvider, app: Any, pair_calls: list[tuple[str, str]]) -> None:
        self.provider = provider
        self.app = app
        self.pair_calls = pair_calls

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport, base_url=BASE_URL, follow_redirects=False
        ) as client:
            return await client.request(method, path, **kwargs)

    async def authorize(self, client_id: str = GOOD_ID) -> tuple[httpx.Response, str, str]:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        response = await self.request(
            "GET",
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "STATE123",
                "scope": "mcp-access",
            },
        )
        location = response.headers.get("location", "")
        code = parse_qs(urlparse(location).query).get("code", [""])[0]
        return response, code, verifier

    async def token(self, form: dict[str, str]) -> httpx.Response:
        return await self.request("POST", "/token", data=form)


async def _protected_whoami(harness: _Harness, access_token: str) -> httpx.Response:
    async with harness.app.router.lifespan_context(harness.app):
        return await _protected_whoami_requests(harness, access_token)


async def _protected_whoami_requests(harness: _Harness, access_token: str) -> httpx.Response:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {access_token}",
    }
    initialize = await harness.request(
        "POST",
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert initialize.status_code == 200, initialize.text
    headers["Mcp-Session-Id"] = initialize.headers["mcp-session-id"]
    initialized = await harness.request(
        "POST",
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert initialized.status_code in {200, 202}, initialized.text
    return await harness.request(
        "POST",
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "whoami", "arguments": {}},
        },
    )


def _complete_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("KF_DOMAIN", "KF_ACCOUNT_ID", "KF_ACCESS_KEY_ID", "KF_ACCESS_KEY_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv("MCP_OAUTH_BASE_URL", "https://mcp.example.test")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant")
    monkeypatch.setenv("AZURE_CLIENT_ID", "azure-client")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "azure-server-secret")  # gitleaks:allow
    monkeypatch.setenv("AZURE_REQUIRED_SCOPES", "mcp-access")
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-kissflow.example.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "account")


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(auth.REDIRECTS_ENV, "")
    pair_calls: list[tuple[str, str]] = []

    def validate_pair(key_id: str, key_secret: str) -> bool:
        pair_calls.append((key_id, key_secret))
        return (key_id, key_secret) == (GOOD_ID, GOOD_SECRET)

    monkeypatch.setattr(auth, "_validate_pair", validate_pair)
    provider = _FakeIdentityProvider(
        client_id="azure-client",
        client_secret="azure-server-secret",  # gitleaks:allow
        tenant_id="tenant",
        required_scopes=["mcp-access"],
        base_url=BASE_URL,
        jwt_signing_key=SIGNING_KEY,
        allowed_email_domains=["example.com"],
        client_storage=MemoryStore(),
    )
    provider._token_validator = _FakeVerifier()
    mcp = FastMCP("oauth-test", auth=provider)

    @mcp.tool
    def whoami() -> dict[str, str]:
        """The tool is present so the ASGI app is a real protected MCP server."""
        return {"ok": "true"}

    app = mcp.http_app(
        middleware=[ASGIMiddleware(auth.CaptureTokenBody)],
        transport="streamable-http",
    )
    return _Harness(provider, app, pair_calls)


@pytest.fixture
def disk_harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> _Harness:
    """Use AzureProvider's default encrypted FileTree store in a temporary home."""
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(auth.REDIRECTS_ENV, "")
    monkeypatch.setattr(settings, "home", tmp_path)
    pair_calls: list[tuple[str, str]] = []

    def validate_pair(key_id: str, key_secret: str) -> bool:
        pair_calls.append((key_id, key_secret))
        return (key_id, key_secret) == (GOOD_ID, GOOD_SECRET)

    monkeypatch.setattr(auth, "_validate_pair", validate_pair)
    provider = _FakeIdentityProvider(
        client_id="azure-client",
        client_secret="azure-server-secret",  # gitleaks:allow
        tenant_id="tenant",
        required_scopes=["mcp-access"],
        base_url=BASE_URL,
        jwt_signing_key=SIGNING_KEY,
        allowed_email_domains=["example.com"],
    )
    provider._token_validator = _FakeVerifier()
    mcp = FastMCP("oauth-test-disk", auth=provider)

    @mcp.tool
    def whoami() -> dict[str, str]:
        """The tool is present so the ASGI app is a real protected MCP server."""
        return {"ok": "true"}

    app = mcp.http_app(
        middleware=[ASGIMiddleware(auth.CaptureTokenBody)],
        transport="streamable-http",
    )
    return _Harness(provider, app, pair_calls)


@pytest.mark.parametrize(
    "missing, expected",
    [
        (auth.SIGNING_KEY_ENV, auth.SIGNING_KEY_ENV),
        ("AZURE_TENANT_ID", "AZURE_TENANT_ID"),
        ("AZURE_CLIENT_ID", "AZURE_CLIENT_ID"),
        ("AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        ("AZURE_REQUIRED_SCOPES", "AZURE_REQUIRED_SCOPES"),
        ("MCP_OAUTH_BASE_URL", "MCP_OAUTH_BASE_URL"),
        ("KF_DEV_DOMAIN", "KF_DEV_DOMAIN"),
        ("KF_DEV_ACCOUNT_ID", "KF_DEV_ACCOUNT_ID"),
    ],
)
def test_http_startup_rejects_partial_configuration(
    monkeypatch: pytest.MonkeyPatch, missing: str, expected: str
) -> None:
    """HTTP mode has no unauthenticated or shared-key fallback."""
    _complete_env(monkeypatch)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match=expected):
        auth.provider_from_env()


def test_http_provider_requires_entra_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP startup cannot fall back to the old Kissflow-only provider."""
    monkeypatch.setenv("MCP_OAUTH_BASE_URL", "https://mcp.example.test")
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, SIGNING_KEY)
    for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_REQUIRED_SCOPES"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="AZURE_TENANT_ID"):
        auth.provider_from_env()


def test_azure_authorize_and_callback_use_real_transaction_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production Azure authorize/callback path remains offline-testable at its transport seam."""
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, SIGNING_KEY)
    monkeypatch.setenv(auth.REDIRECTS_ENV, "")
    provider = auth.KissflowOAuthProvider(
        client_id="azure-client",
        client_secret="azure-server-secret",  # gitleaks:allow
        tenant_id="tenant",
        required_scopes=["mcp-access"],
        base_url=BASE_URL,
        jwt_signing_key=SIGNING_KEY,
        allowed_email_domains=["example.com"],
        client_storage=MemoryStore(),
    )
    upstream_calls: list[dict[str, Any]] = []

    class _OfflineUpstream:
        async def fetch_token(self, **kwargs: Any) -> dict[str, Any]:
            upstream_calls.append(kwargs)
            return {
                "access_token": _jwt_payload({
                    "sub": "sub-alice", "oid": "oid-alice", "preferred_username": "alice@example.com"
                }),
                "refresh_token": "upstream-refresh",
                "expires_in": 3600,
                "scope": "api://azure-client/mcp-access",
            }

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(provider, "_create_upstream_oauth_client", lambda: _OfflineUpstream())
    mcp = FastMCP("oauth-real-azure-test", auth=provider)
    app = mcp.http_app(transport="streamable-http")
    harness = _Harness(provider, app, [])

    response, _, _ = _run(harness.authorize)
    assert response.status_code == 302
    upstream_location = response.headers["location"]
    upstream_query = parse_qs(urlparse(upstream_location).query)
    assert upstream_location.startswith("https://login.microsoftonline.com/")
    txn_id = upstream_query["state"][0]
    transaction = _run(provider._transaction_store.get, key=txn_id)
    assert transaction is not None
    assert transaction.client_id == GOOD_ID
    assert transaction.client_redirect_uri == REDIRECT
    assert transaction.client_state == "STATE123"
    callback = _run(
        harness.request,
        "GET",
        "/auth/callback",
        params={"code": "offline-idp-code", "state": txn_id},
    )
    assert callback.status_code == 302
    callback_query = parse_qs(urlparse(callback.headers["location"]).query)
    assert callback_query["code"]
    assert callback_query["state"] == ["STATE123"]
    assert upstream_calls and upstream_calls[0]["code"] == "offline-idp-code"


def test_authorize_redirects_before_kissflow_and_preserves_state(harness: _Harness) -> None:
    response, code, _ = _run(harness.authorize)
    assert response.status_code == 302
    assert code
    assert "state=STATE123" in response.headers["location"]
    assert harness.pair_calls == []


def test_wrong_pair_consumes_code_and_never_mints(harness: _Harness) -> None:
    _, code, verifier = _run(harness.authorize)
    wrong = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "client_secret": "WRONG_SECRET",  # gitleaks:allow
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert wrong.status_code >= 400
    assert harness.pair_calls == [(GOOD_ID, "WRONG_SECRET")]
    replay = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert replay.status_code >= 400
    assert harness.pair_calls == [(GOOD_ID, "WRONG_SECRET")]


def test_missing_pair_and_random_token_do_not_call_kissflow(harness: _Harness) -> None:
    _, code, verifier = _run(harness.authorize)
    missing = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    random = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": "random-code",
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert missing.status_code >= 400 and random.status_code >= 400
    assert harness.pair_calls == []


def test_valid_pair_binds_encrypted_claim_and_preserves_jti(harness: _Harness) -> None:
    _, code, verifier = _run(harness.authorize)
    response = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    access = body["access_token"]
    refresh = body["refresh_token"]
    assert GOOD_SECRET not in access and GOOD_SECRET not in refresh
    payload = harness.provider.jwt_issuer.verify_token(access)
    upstream = payload["upstream_claims"]
    assert upstream["oid"] == f"oid-{GOOD_ID}"
    sealed = upstream[auth.KISSFLOW_CREDENTIALS_CLAIM]
    assert GOOD_SECRET not in sealed
    assert auth._open(auth.KISSFLOW_CREDENTIALS_KIND, sealed, None) == {
        "t": auth.KISSFLOW_CREDENTIALS_KIND,
        "kid": GOOD_ID,
        "sec": GOOD_SECRET,
    }
    jti = payload["jti"]
    mapping = _run(harness.provider._jti_mapping_store.get, key=jti)
    assert mapping is not None and mapping.jti == jti
    protected = _run(_protected_whoami, harness, access)
    assert protected.status_code == 200, protected.text
    assert '"ok":"true"' in protected.text.replace(" ", "")

    from fastmcp.server import dependencies

    access_info = AccessToken(
        token=access,
        client_id=GOOD_ID,
        scopes=["mcp-access"],
        expires_at=payload["exp"],
        claims={"upstream_claims": upstream},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(dependencies, "get_access_token", lambda: access_info)
    try:
        assert auth.creds_from_token() == (GOOD_ID, GOOD_SECRET)
    finally:
        monkeypatch.undo()


def test_refresh_revalidates_pair_rotates_refresh_and_rebinds_access(harness: _Harness) -> None:
    _, code, verifier = _run(harness.authorize)
    first = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    ).json()
    wrong = _run(
        harness.token,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": GOOD_ID,
            "client_secret": "WRONG_SECRET",  # gitleaks:allow
        },
    )
    assert wrong.status_code >= 400
    assert harness.pair_calls[-1] == (GOOD_ID, "WRONG_SECRET")

    refreshed_response = _run(
        harness.token,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
        },
    )
    assert refreshed_response.status_code == 200, refreshed_response.text
    refreshed = refreshed_response.json()
    assert refreshed["refresh_token"] != first["refresh_token"]
    first_payload = harness.provider.jwt_issuer.verify_token(first["access_token"])
    refreshed_payload = harness.provider.jwt_issuer.verify_token(refreshed["access_token"])
    assert refreshed_payload["jti"] != first_payload["jti"]
    assert auth._open(
        auth.KISSFLOW_CREDENTIALS_KIND,
        refreshed_payload["upstream_claims"][auth.KISSFLOW_CREDENTIALS_CLAIM],
        None,
    )["sec"] == GOOD_SECRET

    old_again = _run(
        harness.token,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
        },
    )
    assert old_again.status_code >= 400


def test_wrong_key_id_and_email_domain_fail_closed(harness: _Harness) -> None:
    _, code, verifier = _run(harness.authorize, "WRONG_KEY")
    response = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "WRONG_KEY",
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert response.status_code >= 400
    assert harness.pair_calls == [("WRONG_KEY", GOOD_SECRET)]

    harness.provider.idp_variant = "missing-email"
    _, no_email_code, no_email_verifier = _run(harness.authorize)
    no_email = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": no_email_code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": no_email_verifier,
        },
    )
    assert no_email.status_code >= 400
    assert no_email.json().get("access_token") is None
    assert harness.pair_calls == [("WRONG_KEY", GOOD_SECRET)]
    replay = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": no_email_code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": no_email_verifier,
        },
    )
    assert replay.status_code >= 400


def test_invalid_entra_result_cannot_make_usable_token(harness: _Harness) -> None:
    harness.provider.idp_variant = "invalid"
    _, code, verifier = _run(harness.authorize)
    response = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert response.status_code >= 400
    assert response.json().get("access_token") is None
    assert harness.pair_calls == []
    blocked = _run(
        harness.request,
        "POST",
        "/mcp",
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert blocked.status_code == 401


def test_invalid_entra_refresh_cannot_make_usable_token(harness: _Harness) -> None:
    _, code, verifier = _run(harness.authorize)
    first = _run(
        harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    ).json()
    harness.provider.idp_variant = "invalid"
    response = _run(
        harness.token,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
        },
    )
    assert response.status_code >= 400
    assert response.json().get("access_token") is None


def test_refresh_lock_state_remains_bounded_for_failed_exchange(disk_harness: _Harness) -> None:
    refresh_tokens: list[str] = []
    for _ in range(10):
        _, code, verifier = _run(disk_harness.authorize)
        token_response = _run(
            disk_harness.token,
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": GOOD_ID,
                "client_secret": GOOD_SECRET,
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
            },
        )
        assert token_response.status_code == 200, token_response.text
        refresh_tokens.append(token_response.json()["refresh_token"])
    refresh_form = {
        "grant_type": "refresh_token",
        "client_secret": "WRONG_SECRET",  # gitleaks:allow
    }
    for refresh_token in refresh_tokens:
        response = _run(
            disk_harness.token,
            {
                **refresh_form,
                "client_id": GOOD_ID,
                "refresh_token": refresh_token,
            },
        )
        assert response.status_code >= 400
    lock_state = getattr(disk_harness.provider, "_refresh_grant_locks", None)
    if lock_state is not None:
        assert isinstance(lock_state, dict), lock_state
        assert len(lock_state) <= 1, lock_state


def test_concurrent_authorization_code_redemption_is_single_use(disk_harness: _Harness) -> None:
    _, code, verifier = _run(disk_harness.authorize)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": GOOD_ID,
        "client_secret": GOOD_SECRET,
        "redirect_uri": REDIRECT,
        "code_verifier": verifier,
    }
    responses = _run_concurrent(*(disk_harness.token(dict(form)) for _ in range(20)))
    successful = [response for response in responses if response.status_code == 200]
    assert len(successful) == 1, [response.status_code for response in responses]
    assert disk_harness.pair_calls == [(GOOD_ID, GOOD_SECRET)]
    assert _run(disk_harness.provider._code_store.get, key=code) is None


def test_concurrent_refresh_replay_rotates_once(disk_harness: _Harness) -> None:
    _, code, verifier = _run(disk_harness.authorize)
    first_response = _run(
        disk_harness.token,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    refresh_form = {
        "grant_type": "refresh_token",
        "refresh_token": first["refresh_token"],
        "client_id": GOOD_ID,
        "client_secret": GOOD_SECRET,
    }
    responses = _run_concurrent(
        disk_harness.token(dict(refresh_form)), disk_harness.token(dict(refresh_form))
    )
    successful = [response for response in responses if response.status_code == 200]
    assert len(successful) == 1, [response.status_code for response in responses]
    rotated = successful[0].json()
    descendant = _run(
        disk_harness.token,
        {
            "grant_type": "refresh_token",
            "refresh_token": rotated["refresh_token"],
            "client_id": GOOD_ID,
            "client_secret": GOOD_SECRET,
        },
    )
    assert descendant.status_code == 200, descendant.text
    replay = _run(disk_harness.token, refresh_form)
    assert replay.status_code >= 400


def test_metadata_disables_dcr_and_cimd(harness: _Harness) -> None:
    assert harness.provider._cimd_manager is None
    assert not harness.provider.client_registration_options.enabled
    response = _run(harness.request, "GET", "/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    metadata = response.json()
    assert "registration_endpoint" not in metadata
    assert "client_id_metadata_document_supported" not in metadata
    assert metadata["scopes_supported"] == ["mcp-access"]
    assert set(metadata["token_endpoint_auth_methods_supported"]) == {
        "client_secret_post",
        "client_secret_basic",
    }
    register = _run(harness.request, "POST", "/register", content=b"{}")
    assert register.status_code == 404


def test_redirect_policy_rejects_bypasses_and_unsafe_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(auth.REDIRECTS_ENV, raising=False)
    allowed = [
        "http://localhost:1234/cb",
        "http://127.0.0.1:1234/cb",
        "https://claude.ai/api/mcp/auth_callback",
        "https://sub.claude.ai/callback",
    ]
    rejected = [
        "javascript://localhost/cb",
        "http://localhost@evil.example/cb",
        "https://evilclaude.ai/cb",
        "https://claude.ai.evil/cb",
        "http://evil.example/cb",
        "https://claude.ai/foo/%2e%2e/bar",
    ]
    assert all(auth._allowed_redirect(uri) for uri in allowed)
    assert all(not auth._allowed_redirect(uri) for uri in rejected)

    monkeypatch.setenv(auth.REDIRECTS_ENV, "javascript://localhost/*")
    assert not auth._allowed_redirect("javascript://localhost/cb")
    with pytest.raises(RuntimeError, match=auth.REDIRECTS_ENV):
        auth._redirect_patterns()
    monkeypatch.setenv(auth.REDIRECTS_ENV, "http://remote.example/*")
    assert not auth._allowed_redirect("http://remote.example/cb")
    with pytest.raises(RuntimeError, match=auth.REDIRECTS_ENV):
        auth._redirect_patterns()
    monkeypatch.setenv(auth.REDIRECTS_ENV, "https://corp.example.com/*")
    assert auth._allowed_redirect("https://corp.example.com/cb")


def test_sealed_tokens_reject_tampering_and_wrong_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, SIGNING_KEY)
    sealed = auth._seal("access", {"kid": "A", "sec": "B"})
    assert auth._open("access", sealed, 60) == {"t": "access", "kid": "A", "sec": "B"}
    assert auth._open("refresh", sealed, 60) is None
    assert auth._open("access", sealed[:-4] + "AAAA", 60) is None
    assert auth._open("access", sealed, -1) is None
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, "another-signing-key-entirely-0123456789abcdef")
    assert auth._open("access", sealed, 60) is None


def test_short_signing_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth.SIGNING_KEY_ENV, "tooshort")
    with pytest.raises(RuntimeError, match=auth.SIGNING_KEY_ENV):
        auth._seal("access", {})


def test_capture_token_body_is_bounded_and_does_not_replay_oversize() -> None:
    sent: list[dict[str, Any]] = []
    called = False

    async def app(*_: Any) -> None:
        nonlocal called
        called = True

    async def receive() -> dict[str, Any]:
        return {
            "type": "http.request",
            "body": b"x" * (auth.MAX_TOKEN_BODY_BYTES + 1),
            "more_body": False,
        }

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    _run(
        auth.CaptureTokenBody(app),
        {"type": "http", "path": "/token"},
        receive,
        send,
    )
    assert not called
    assert sent[0]["status"] == 413
    assert sent[1]["body"] == b""


def test_http_client_does_not_fall_back_to_process_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from kfforge import server

    monkeypatch.setenv("MCP_HTTP", "1")
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-kissflow.example.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "account")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_ID", "SHARED_ENV_ID")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_SECRET", "SHARED_ENV_SECRET")  # gitleaks:allow
    monkeypatch.setattr(server, "creds_from_token", lambda: None)
    result = server._client(require_app=False)
    assert isinstance(result, server.Err)
    assert "not authenticated" in result.message
