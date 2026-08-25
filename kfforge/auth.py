"""Per-user Kissflow credentials, carried in over OAuth.

Door 1 (Claude Desktop -> this server) and door 2 (this server -> Kissflow) are DELIBERATELY the
same credential here: the Desktop connector's `OAuth Client ID` field holds the user's own
Kissflow access-key ID and `OAuth Client Secret` holds their access-key secret. The server never
holds a shared key over HTTP — every caller acts as themselves, so Kissflow's own role model, not
ours, bounds what they can do. `KF_DEV_DOMAIN` / `KF_DEV_ACCOUNT_ID` stay server-side env: the
caller picks their identity, never the tenant, so client.py's `dev-` refusal stays welded shut.

Those two connector fields are NOT a pipe for two loose strings. Claude Desktop spends them in an
OAuth 2.1 authorization-code exchange against `/authorize` + `/token` on THIS server, so the
server has to be a real OAuth authorization server for the pair to arrive at all. That is what
this module is.

STATELESS by construction. Every auth code, access token and refresh token is a Fernet blob
(cryptography, already a fastmcp dependency) sealed with a key derived from `MCP_OAUTH_SIGNING_KEY`
— authenticated encryption plus a built-in timestamp, so expiry is `ttl=` on the open, not a
server-side table. Nothing is kept in memory, so a pod restart or a second replica behind the mesh
changes nothing. The tenant credential rides INSIDE the sealed token, which is why the token is
encrypted and not merely signed: a token in a log must not leak a Kissflow key.

Read alongside `docs/engine/13-deploying-the-mcp-server.md` (the endpoint is Istio + Entra-fronted;
`/authorize` is a BROWSER hit and the edge proxy may bounce it through Microsoft login first).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import sys
import time
import urllib.parse
from contextvars import ContextVar
from typing import Any, Final

from cryptography.fernet import Fernet, InvalidToken
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from fastmcp.server.auth.auth import AccessToken, OAuthProvider

from .client import Err, KfClient, KfConfig

CODE_TTL_S: Final[int] = 60
ACCESS_TTL_S: Final[int] = 60 * 60
REFRESH_TTL_S: Final[int] = 30 * 24 * 60 * 60
SIGNING_KEY_ENV: Final[str] = "MCP_OAUTH_SIGNING_KEY"
REDIRECTS_ENV: Final[str] = "MCP_OAUTH_ALLOWED_REDIRECTS"
MIN_SIGNING_KEY_LEN: Final[int] = 32
# The refresh_token grant sends no redirect_uri and the client model demands one. Never used.
PLACEHOLDER_REDIRECT: Final[str] = "http://localhost/kfforge-oauth-unused"

# The /token request body, captured by CaptureTokenBody below. `get_client` cannot read it any
# other way: fastmcp's request contextvar hands back a DIFFERENT Request object than the one the
# SDK's TokenHandler already drained, so `await req.form()` there dies with "Receive channel has
# not been made available" (probed live, fastmcp 3.4.7). Headers survive; the body does not.
_TOKEN_FORM: ContextVar[dict[str, str]] = ContextVar("kfforge_token_form", default={})


# --- sealed tokens -------------------------------------------------------------------


def _fernet() -> Fernet:
    """Fernet keyed off `MCP_OAUTH_SIGNING_KEY`. Raises if the env is missing or too short —
    a per-process random key would break the moment the mesh runs a second replica, so this
    fails loud at startup instead of failing silently on every second request."""
    raw = os.environ.get(SIGNING_KEY_ENV, "")
    if len(raw) < MIN_SIGNING_KEY_LEN:
        raise RuntimeError(
            f"{SIGNING_KEY_ENV} must be set to at least {MIN_SIGNING_KEY_LEN} characters of "
            "high-entropy secret, shared by every replica (a per-process key breaks refresh and "
            "breaks multi-pod). Generate one with: python3 -c "
            "'import secrets;print(secrets.token_urlsafe(48))'"
        )
    digest = hashlib.blake2b(raw.encode(), digest_size=32, person=b"kfforge-oauth").digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _seal(kind: str, payload: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps({"t": kind, **payload}).encode()).decode()


def _open(kind: str, token: str, ttl_s: int) -> dict[str, Any] | None:
    """Open a sealed token, or None if it is forged, tampered with, expired, or the wrong kind.
    Never raises and never logs the token — a token carries a live Kissflow secret."""
    try:
        raw = _fernet().decrypt(token.encode(), ttl=ttl_s)
    except (InvalidToken, binascii.Error, ValueError, RuntimeError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("t") != kind:
        return None
    return data


# --- credential validation -----------------------------------------------------------


def _validate_pair(key_id: str, key_secret: str) -> bool:
    """One cheap Kissflow GET proving the pasted pair actually works, spent once per /token.
    A user who typo'd a secret finds out during login, not three tool calls into a build.

    ⚠️ DEPLOYMENT POSTURE, not a code gap: this call is UNAUTHENTICATED and UNTHROTTLED by
    design — any anonymous POST to `/token` reaches it and the 200-vs-401 response distinguishes
    a valid Kissflow access-key pair from an invalid one, which makes this endpoint a live oracle
    for credential-stuffing if it is ever exposed raw. No rate limiter lives in this module on
    purpose — see `docs/engine/13-deploying-the-mcp-server.md`. In the hosted deployment the
    Entra/oauth2-proxy + Istio mesh edge in FRONT of this server is the required shield (rate
    limiting and access control both live there, not here). Never expose this endpoint directly
    to the internet without that edge in place."""
    domain = os.environ.get("KF_DEV_DOMAIN", "")
    account = os.environ.get("KF_DEV_ACCOUNT_ID", "")
    if not domain or not account or "dev-" not in domain:
        return False
    cfg = KfConfig(
        key_id=key_id, key_secret=key_secret, account=account, domain=domain, app_id=""
    )
    return not isinstance(KfClient(cfg).list_applications(), Err)


# --- request-scoped reads ------------------------------------------------------------


def _http_request() -> Any | None:
    from fastmcp.server.dependencies import get_http_request

    try:
        return get_http_request()
    except (RuntimeError, LookupError):
        return None


def _presented_secret() -> tuple[str, str] | None:
    """The client_secret this request carried plus the auth method it arrived by:
    `(secret, "client_secret_post")` from the captured form body or
    `(secret, "client_secret_basic")` from the Authorization header — the client record must
    advertise the method actually used, or the SDK middleware 401s a Basic-auth client that
    did supply the secret. None on the /authorize leg, which by design never carries one."""
    form_secret = _TOKEN_FORM.get().get("client_secret")
    if form_secret:
        return form_secret, "client_secret_post"
    req = _http_request()
    if req is None:
        return None
    header = req.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    secret = urllib.parse.unquote(decoded.split(":", 1)[1])
    if not secret:
        return None
    return secret, "client_secret_basic"


def _requested_scope() -> str | None:
    """Whatever scope string this request asked for, echoed straight back onto the client record.
    Scopes carry NO authorization meaning here — a caller is one Kissflow identity with the whole
    tool surface, and Kissflow's own roles do the bounding — but the SDK refuses any scope a client
    was not "registered" with, and there is no registration step to register one in."""
    form_scope = _TOKEN_FORM.get().get("scope")
    if form_scope is not None:
        return form_scope
    req = _http_request()
    if req is None:
        return None
    return req.query_params.get("scope")


def _allowed_redirect(uri: str) -> bool:
    """Loopback and claude.ai by default; `MCP_OAUTH_ALLOWED_REDIRECTS` (comma-separated prefixes)
    widens it without a code change. An unchecked redirect_uri is an open redirect, and this is a
    trust boundary — the code alone is useless without the Kissflow secret, but "useless to whom"
    is not a question worth guessing at."""
    extra = [p.strip() for p in os.environ.get(REDIRECTS_ENV, "").split(",") if p.strip()]
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    # exact host or a real subdomain — a bare endswith admits evilclaude.ai
    if parsed.scheme == "https" and (host == "claude.ai" or host.endswith(".claude.ai")):
        return True
    for prefix in extra:
        # prefix match only at a "/" boundary, or https://corp.example.com admits
        # https://corp.example.com.evil.net
        if uri == prefix or uri.startswith(prefix if prefix.endswith("/") else prefix + "/"):
            return True
    return False


def _raw_redirect_uris() -> list[str]:
    seen: list[str] = []
    form_uri = _TOKEN_FORM.get().get("redirect_uri")
    if form_uri:
        seen.append(form_uri)
    req = _http_request()
    if req is not None:
        query_uri = req.query_params.get("redirect_uri")
        if query_uri:
            seen.append(query_uri)
    return seen


def _requested_redirect_uris() -> list[AnyUrl] | None:
    """Whatever redirect this request asked for, if it passes `_allowed_redirect`; None when one
    was asked for and refused, which the caller turns into a clean "invalid client". Desktop's
    callback is not knowable ahead of time and there is no registration step to learn it in —
    DCR is deliberately off, which is exactly why the connector dialog shows the manual fields.

    The `refresh_token` grant carries no redirect at all, and the client model requires at least
    one, so that leg gets a placeholder that is never redirected to."""
    seen = _raw_redirect_uris()
    if not seen:
        return [AnyUrl(PLACEHOLDER_REDIRECT)]
    allowed = list(map(AnyUrl, filter(_allowed_redirect, seen)))
    if not allowed:
        return None
    return allowed


# --- ASGI middleware -----------------------------------------------------------------


class CaptureTokenBody:
    """Drain the `/token` body once, stash the parsed form in `_TOKEN_FORM`, replay it downstream.

    Without this the pasted Kissflow secret is unreachable: the SDK's TokenHandler consumes the
    body before `get_client` runs, and fastmcp's request contextvar exposes a different Request
    object whose receive channel is already spent."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path", "").rstrip("/") != "/token":
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        body = b"".join(chunks)
        try:
            form = dict(urllib.parse.parse_qsl(body.decode("utf-8")))
        except UnicodeDecodeError:
            form = {}
        token = _TOKEN_FORM.set(form)
        replayed = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        try:
            await self.app(scope, replay, send)
        finally:
            _TOKEN_FORM.reset(token)


# --- the provider --------------------------------------------------------------------


class KissflowOAuthProvider(OAuthProvider):
    """OAuth 2.1 authorization server whose client_id/client_secret ARE a Kissflow access-key pair.

    `client_registration_options` and `revocation_options` are both left off on purpose: DCR stays
    unadvertised so Desktop uses the manual connector fields, and revocation stays unadvertised
    because a stateless token cannot be revoked — rotate the Kissflow key in Kissflow instead.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url=base_url)
        _fernet()  # fail at startup, not on the first login

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        redirect_uris = _requested_redirect_uris()
        if redirect_uris is None:
            return None  # redirect_uri outside the allowlist — refuse, never 500
        presented = _presented_secret()
        secret, auth_method = presented if presented else (None, "none")
        info = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=secret,
            redirect_uris=redirect_uris,
            scope=_requested_scope(),
            token_endpoint_auth_method=auth_method,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )
        if secret is None:
            # /authorize leg: an authorization-code request never carries the secret. Let the
            # browser leg through; the pair is proven at /token before any token is minted.
            return info
        if not await asyncio.to_thread(_validate_pair, client_id, secret):
            return None
        return info

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError(
            "dynamic client registration is off — paste your own Kissflow access-key ID and "
            "secret into the connector's OAuth Client ID / Client Secret fields"
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        code = _seal(
            "code",
            {
                "cid": client.client_id,
                "cc": params.code_challenge,
                "ru": str(params.redirect_uri),
                "rue": params.redirect_uri_provided_explicitly,
                "sc": params.scopes or [],
                "res": params.resource,
            },
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        # ponytail: a stateless code is replayable inside its TTL, unlike a consumed one. PKCE
        # binds it to the caller's verifier AND /token re-checks the Kissflow secret, so a replay
        # needs both — hence 60s instead of a server-side used-code table. Add the table if a
        # single-use guarantee is ever required on its own.
        data = _open("code", authorization_code, CODE_TTL_S)
        if data is None or data.get("cid") != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=list(data.get("sc") or []),
            expires_at=time.time() + CODE_TTL_S,
            client_id=str(data["cid"]),
            code_challenge=str(data.get("cc") or ""),
            redirect_uri=AnyUrl(str(data["ru"])),
            redirect_uri_provided_explicitly=bool(data.get("rue")),
            resource=data.get("res"),
        )

    def _mint(self, client: OAuthClientInformationFull, scopes: list[str]) -> OAuthToken:
        if not client.client_id or not client.client_secret:
            raise TokenError(
                "invalid_client",
                "no Kissflow access-key pair on this request — put your key ID in the "
                "connector's OAuth Client ID field and your key secret in OAuth Client Secret",
            )
        body = {"kid": client.client_id, "sec": client.client_secret, "sc": scopes}
        return OAuthToken(
            access_token=_seal("access", body),
            token_type="Bearer",
            expires_in=ACCESS_TTL_S,
            refresh_token=_seal("refresh", body),
            scope=" ".join(scopes),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        return self._mint(client, list(authorization_code.scopes))

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        data = _open("refresh", refresh_token, REFRESH_TTL_S)
        if data is None or data.get("kid") != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=str(data["kid"]),
            scopes=list(data.get("sc") or []),
            expires_at=int(time.time() + REFRESH_TTL_S),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if not set(scopes).issubset(set(refresh_token.scopes)):
            raise TokenError("invalid_scope", "requested scopes exceed the refresh token's")
        # The refresh leg carries the pair too, so `client.client_secret` was re-validated against
        # Kissflow in get_client — a key revoked in Kissflow stops refreshing within the hour.
        return self._mint(client, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = _open("access", token, ACCESS_TTL_S)
        if data is None:
            return None
        return AccessToken(
            token=token,
            client_id=str(data["kid"]),
            scopes=list(data.get("sc") or []),
            expires_at=int(time.time() + ACCESS_TTL_S),
            claims={"kissflow_key_id": str(data["kid"]), "kissflow_key_secret": str(data["sec"])},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Stateless: nothing to delete. Rotate the key in Kissflow to cut a session off for real.
        return None


# --- wiring --------------------------------------------------------------------------


def creds_from_token() -> tuple[str, str] | None:
    """The calling user's Kissflow pair for THIS request, or None when the call carries no token
    (stdio, or an unauthenticated HTTP deployment)."""
    from fastmcp.server.dependencies import get_access_token

    try:
        token = get_access_token()
    except (RuntimeError, LookupError):
        return None
    if token is None:
        return None
    claims = getattr(token, "claims", None) or {}
    key_id, key_secret = claims.get("kissflow_key_id"), claims.get("kissflow_key_secret")
    if not key_id or not key_secret:
        return None
    return str(key_id), str(key_secret)


def provider_from_env() -> KissflowOAuthProvider | None:
    """The provider for HTTP mode, or None when `MCP_OAUTH_BASE_URL` is unset — which leaves the
    endpoint unauthenticated exactly as it is today, warned about loudly in server.main()."""
    base_url = os.environ.get("MCP_OAUTH_BASE_URL", "").strip()
    if not base_url:
        return None
    provider = KissflowOAuthProvider(base_url=base_url)
    print(
        f"per-user Kissflow OAuth ENABLED at {base_url} — every caller supplies their own "
        "access-key pair in the connector's OAuth Client ID / Client Secret fields",
        file=sys.stderr,
        flush=True,
    )
    return provider
