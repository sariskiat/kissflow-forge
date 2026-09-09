"""Two-gate HTTP authentication for Kissflow Forge.

HTTP callers authenticate through FastMCP's AzureProvider (Microsoft Entra) and then prove the
Kissflow access-key pair entered in the OAuth client fields. The pair is never checked during
client lookup: `/authorize` can only start the Entra browser flow, while `/token` and refresh call
Kissflow after FastMCP has validated the authorization code plus PKCE or the stored refresh token.
A successful access token therefore represents both gates. This proves possession of a valid
Kissflow pair, not that Entra and Kissflow independently identify the same person.

The Entra provider owns OAuth state, upstream token validation, refresh rotation, and FastMCP JTI
mappings. Only the access JWT is rebound with a Fernet ciphertext containing the caller's pair;
the original upstream claims and FastMCP refresh token are preserved. The encrypted claim is
request-scoped input to `creds_from_token`, never a raw secret in token text or logs.

`KF_DEV_DOMAIN` / `KF_DEV_ACCOUNT_ID` (or their `KF_DOMAIN` / `KF_ACCOUNT_ID` non-dev opt-in — see
client.py `_tenant_env`) stay server-side env: the caller picks their identity, never the tenant,
so client.py's `dev-` refusal on the default KF_DEV_* path stays welded shut. Stdio does not create
an Entra provider and retains the process-env credential fallback.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import sys
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, Final, Literal, cast
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastmcp.server.auth.oauth_proxy.models import ProxyDCRClient
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.redirect_validation import validate_redirect_uri
from mcp.server.auth.provider import AuthorizationCode, RefreshToken, TokenError
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from .client import Err, KfClient, KfConfig, _tenant_env

CODE_TTL_S: Final[int] = 60
ACCESS_TTL_S: Final[int] = 60 * 60
REFRESH_TTL_S: Final[int] = 30 * 24 * 60 * 60
SIGNING_KEY_ENV: Final[str] = "MCP_OAUTH_SIGNING_KEY"
REDIRECTS_ENV: Final[str] = "MCP_OAUTH_ALLOWED_REDIRECTS"
AZURE_TENANT_ID_ENV: Final[str] = "AZURE_TENANT_ID"
AZURE_CLIENT_ID_ENV: Final[str] = "AZURE_CLIENT_ID"
AZURE_CLIENT_SECRET_ENV: Final[str] = "AZURE_CLIENT_SECRET"
AZURE_REQUIRED_SCOPES_ENV: Final[str] = "AZURE_REQUIRED_SCOPES"
AZURE_ADDITIONAL_SCOPES_ENV: Final[str] = "AZURE_ADDITIONAL_SCOPES"
AZURE_REDIRECT_PATH_ENV: Final[str] = "AZURE_REDIRECT_PATH"
AZURE_BASE_AUTHORITY_ENV: Final[str] = "AZURE_BASE_AUTHORITY"
AZURE_TOKEN_ISSUER_ENV: Final[str] = "AZURE_TOKEN_ISSUER"
AZURE_IDENTIFIER_URI_ENV: Final[str] = "AZURE_IDENTIFIER_URI"
ALLOWED_EMAIL_DOMAINS_ENV: Final[str] = "ALLOWED_EMAIL_DOMAINS"
MAX_TOKEN_BODY_BYTES: Final[int] = 64 * 1024
MIN_SIGNING_KEY_LEN: Final[int] = 32
# The refresh_token grant sends no redirect_uri and the client model demands one. Never used.
PLACEHOLDER_REDIRECT: Final[str] = "http://localhost/kfforge-oauth-unused"
KISSFLOW_CREDENTIALS_CLAIM: Final[str] = "kissflow_credentials"
KISSFLOW_CREDENTIALS_KIND: Final[str] = "kissflow"
DEFAULT_REDIRECT_PATTERNS: Final[tuple[str, ...]] = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
    "https://claude.ai/*",
    "https://*.claude.ai/*",
)
# FastMCP's AzureProvider adds this scope itself, while the access-token verifier needs a real
# application scope supplied by the operator.
OIDC_ONLY_SCOPES: Final[frozenset[str]] = frozenset(
    {"openid", "profile", "email", "offline_access"}
)
AZURE_IDENTITY_CLAIMS: Final[tuple[str, ...]] = (
    "sub",
    "oid",
    "tid",
    "azp",
    "name",
    "given_name",
    "family_name",
    "preferred_username",
    "upn",
    "email",
    "roles",
    "groups",
)

logger = logging.getLogger(__name__)

# The /token request body, captured by CaptureTokenBody below. `get_client` cannot read it any
# other way: fastmcp's request contextvar hands back a DIFFERENT Request object than the one the
# SDK's TokenHandler already drained, so `await req.form()` there dies with "Receive channel has
# not been made available" (probed live, fastmcp 3.4.7). Headers survive; the body does not.
_TOKEN_FORM: ContextVar[dict[str, str] | None] = ContextVar("kfforge_token_form", default=None)
_TOKEN_REQUEST: ContextVar[bool] = ContextVar("kfforge_token_request", default=False)
_TOKEN_CLEANUPS: ContextVar[list[Callable[[], Awaitable[None]]] | None] = ContextVar(
    "kfforge_token_cleanups", default=None
)
_VERIFIED_UPSTREAM_CLAIMS: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "kfforge_verified_upstream_claims", default=None
)


def _register_token_cleanup(cleanup: Callable[[], Awaitable[None]]) -> None:
    """Register request cleanup while keeping token-claim state out of process-global storage."""
    callbacks = _TOKEN_CLEANUPS.get()
    if callbacks is not None:
        callbacks.append(cleanup)


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


def _open(kind: str, token: str, ttl_s: int | None) -> dict[str, Any] | None:
    """Open a sealed value, or ``None`` for forgery, tampering, expiry, or wrong kind.

    The access JWT already supplies the expiry for its credential claim, so callers that have
    passed JWT validation may use ``ttl_s=None``; standalone sealed values retain a Fernet TTL.
    The token is never logged because it may carry a live Kissflow secret.
    """
    try:
        fernet = _fernet()
        raw = fernet.decrypt(token.encode()) if ttl_s is None else fernet.decrypt(token.encode(), ttl=ttl_s)
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
    """Return whether one Kissflow GET accepts the caller's pair.

    The provider calls this only after FastMCP has established an Entra authorization-code/PKCE
    exchange or a stored refresh token. The pair is never an unauthenticated client-lookup oracle.
    """
    resolved = _tenant_env()
    if isinstance(resolved, Err):
        return False
    _prefix, domain, account = resolved
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


def _request_path() -> str | None:
    req = _http_request()
    if req is None:
        return None
    url = getattr(req, "url", None)
    path = getattr(url, "path", None)
    if isinstance(path, str):
        return path
    scope = getattr(req, "scope", None)
    raw_path = scope.get("path") if isinstance(scope, dict) else None
    return raw_path if isinstance(raw_path, str) else None


def _is_token_request() -> bool:
    """The credential capture is true only for `/token`, never for `/authorize`."""
    path = _request_path()
    return _TOKEN_REQUEST.get() or (path is not None and path.rstrip("/") == "/token")


def _presented_secret() -> tuple[str, Literal["client_secret_post", "client_secret_basic"]] | None:
    """Return the `/token` client secret and its RFC 6749 authentication method.

    Invariant: no request outside `/token` can expose a Kissflow secret to client lookup.
    """
    if not _is_token_request():
        return None
    form_secret = (_TOKEN_FORM.get() or {}).get("client_secret")
    if form_secret:
        return form_secret, "client_secret_post"
    req = _http_request()
    if req is None:
        return None
    header = req.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
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
    form_scope = (_TOKEN_FORM.get() or {}).get("scope")
    if form_scope is not None:
        return form_scope
    req = _http_request()
    if req is None:
        return None
    return req.query_params.get("scope")


def _redirect_patterns() -> list[str]:
    """Return the component-aware redirect policy shared by both OAuth legs.

    HTTP is permitted only for loopback patterns. Remote callbacks must be HTTPS, and configured
    patterns are rejected at startup if they contain userinfo, dot-segments, unsafe schemes, or a
    non-loopback HTTP host.
    """
    extras = [p.strip() for p in os.environ.get(REDIRECTS_ENV, "").split(",") if p.strip()]
    for pattern in extras:
        parsed = urlsplit(pattern)
        try:
            host = parsed.hostname or ""
        except ValueError:
            raise RuntimeError(f"{REDIRECTS_ENV} contains an invalid redirect pattern") from None
        if parsed.username is not None or parsed.password is not None:
            raise RuntimeError(f"{REDIRECTS_ENV} contains a redirect pattern with userinfo")
        if parsed.scheme.lower() not in {"http", "https"}:
            raise RuntimeError(f"{REDIRECTS_ENV} contains an unsafe redirect scheme")
        if parsed.scheme.lower() == "http" and host.lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise RuntimeError(f"{REDIRECTS_ENV} permits a non-HTTPS remote redirect")
        if not validate_redirect_uri(pattern, [pattern]):
            raise RuntimeError(f"{REDIRECTS_ENV} contains an invalid redirect pattern")
    return [*DEFAULT_REDIRECT_PATTERNS, *extras]


def _allowed_redirect(uri: str) -> bool:
    """Return whether a callback matches the same component-aware policy used by FastMCP."""
    try:
        return validate_redirect_uri(uri, _redirect_patterns())
    except (RuntimeError, ValueError):
        return False


def _raw_redirect_uris() -> list[str]:
    seen: list[str] = []
    form_uri = (_TOKEN_FORM.get() or {}).get("redirect_uri")
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
    """Replay a bounded `/token` body while exposing its form to static client lookup.

    Invariant: a token request consumes at most ``MAX_TOKEN_BODY_BYTES`` and the body is never
    logged or returned in a 413 response.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path", "").rstrip("/") != "/token":
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                break
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > MAX_TOKEN_BODY_BYTES:
                await send({
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"cache-control", b"no-store")],
                })
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        body = b"".join(chunks)
        try:
            form = dict(urllib.parse.parse_qsl(body.decode("utf-8"), max_num_fields=100))
        except (UnicodeDecodeError, ValueError):
            form = {}
        form_token = _TOKEN_FORM.set(form)
        request_token = _TOKEN_REQUEST.set(True)
        cleanup_token = _TOKEN_CLEANUPS.set([])
        claims_token = _VERIFIED_UPSTREAM_CLAIMS.set({})
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
            for cleanup in reversed(_TOKEN_CLEANUPS.get() or []):
                try:
                    await cleanup()
                except Exception:
                    logger.exception("OAuth token request cleanup failed")
            _VERIFIED_UPSTREAM_CLAIMS.reset(claims_token)
            _TOKEN_CLEANUPS.reset(cleanup_token)
            _TOKEN_REQUEST.reset(request_token)
            _TOKEN_FORM.reset(form_token)


# --- the provider --------------------------------------------------------------------


def _split_env(name: str) -> list[str]:
    return [part for part in os.environ.get(name, "").replace(",", " ").split() if part]


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set in HTTP mode")
    return value


def _base_url_from_env() -> str:
    base_url = os.environ.get("MCP_OAUTH_BASE_URL", "").strip()
    if not base_url:
        base_url = os.environ.get("AZURE_BASE_URL", "").strip()
    if not base_url:
        raise RuntimeError("MCP_OAUTH_BASE_URL (or AZURE_BASE_URL) must be set in HTTP mode")
    parsed = urlsplit(base_url)
    try:
        host = parsed.hostname or ""
    except ValueError:
        host = ""
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("MCP_OAUTH_BASE_URL must be an absolute HTTP(S) URL without credentials")
    if parsed.scheme.lower() == "http" and host.lower() not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError("HTTP OAuth base URLs are permitted only on loopback")
    return base_url.rstrip("/")


class KissflowOAuthProvider(AzureProvider):
    """AzureProvider with a second, per-user Kissflow credential gate.

    Invariant: a returned access token has an AzureProvider-issued JTI mapping and an encrypted
    Kissflow pair merged into its existing ``upstream_claims``; the FastMCP refresh token returned
    by the parent is unchanged.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        required_scopes: list[str],
        base_url: str,
        jwt_signing_key: str,
        allowed_email_domains: list[str] | None = None,
        allowed_client_redirect_uris: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        _fernet()
        redirect_patterns = (
            _redirect_patterns()
            if allowed_client_redirect_uris is None
            else list(allowed_client_redirect_uris)
        )
        self._allowed_email_domains = frozenset(
            domain.strip().lower().lstrip("@")
            for domain in (allowed_email_domains or [])
            if domain.strip()
        )
        self._authorization_code_claim_lock = asyncio.Lock()
        self._claimed_authorization_codes: set[str] = set()
        # One active replica is documented and enforced by deployment policy; one lock serializes
        # all refresh grants without per-token state growth.
        self._refresh_grant_lock = asyncio.Lock()
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id,
            required_scopes=required_scopes,
            base_url=base_url,
            jwt_signing_key=jwt_signing_key,
            allowed_client_redirect_uris=redirect_patterns,
            enable_cimd=False,
            require_authorization_consent="external",
            **kwargs,
        )
        # OAuthProxy hard-codes DCR on in 3.4.7. Keep valid/default scopes for metadata and client
        # scope checks, but disable its registration route and do not use its storage lookup.
        options = cast(
            ClientRegistrationOptions | None,
            getattr(self, "client_registration_options", None),
        )
        if options is None:  # pragma: no cover - AzureProvider always supplies options
            raise RuntimeError("FastMCP registration options unexpectedly missing")
        scopes = list(options.valid_scopes or required_scopes)
        self.client_registration_options = ClientRegistrationOptions(
            enabled=False,
            valid_scopes=scopes,
            default_scopes=scopes,
        )
        if self._cimd_manager is not None:  # exact-pin contract: CIMD must stay disabled
            raise RuntimeError("FastMCP CIMD unexpectedly enabled")

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Synthesize the static client without consulting DCR/CIMD storage.

        `/authorize` needs only the key ID so Entra can authenticate first. `/token` must carry a
        secret, but this method deliberately does not validate it; the exchange methods do that
        only after FastMCP has checked the authorization code/PKCE or refresh-token state.
        """
        if not client_id:
            return None
        redirect_uris = _requested_redirect_uris()
        if redirect_uris is None:
            return None
        presented = _presented_secret()
        if _is_token_request() and presented is None:
            return None
        if presented is None:
            secret = None
            auth_method: Literal["none", "client_secret_post", "client_secret_basic"] = "none"
        else:
            secret, auth_method = presented
        return ProxyDCRClient(
            client_id=client_id,
            client_secret=secret,
            redirect_uris=[AnyUrl("http://localhost")],
            scope=self._default_scope_str,
            token_endpoint_auth_method=auth_method,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            allowed_redirect_uri_patterns=self._allowed_client_redirect_uris,
            allow_unregistered_redirect_uris=True,
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError(
            "dynamic client registration is disabled; enter the Kissflow key ID and secret "
            "in the OAuth client fields"
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Claim an authorization code before the handler checks PKCE or calls exchange.

        Invariant: at most one request in this provider process can receive a given live code;
        request cleanup consumes a claimed code even when PKCE or redirect validation fails.
        """
        async with self._authorization_code_claim_lock:
            if authorization_code in self._claimed_authorization_codes:
                return None
            code = await super().load_authorization_code(client, authorization_code)
            if code is None:
                return None
            self._claimed_authorization_codes.add(authorization_code)
        _register_token_cleanup(
            lambda: self._release_authorization_code_claim(authorization_code)
        )
        return code

    async def _release_authorization_code_claim(self, code: str) -> None:
        """Consume a claimed code, then make its process-local claim reusable only after deletion."""
        await self._code_store.delete(key=code)
        async with self._authorization_code_claim_lock:
            self._claimed_authorization_codes.discard(code)


    async def _caller_pair(self, client: OAuthClientInformationFull) -> tuple[str, str]:
        key_id = client.client_id
        presented = _presented_secret()
        key_secret = presented[0] if presented else client.client_secret
        if not key_id or not key_secret:
            raise TokenError("invalid_client", "Kissflow access-key credentials are required")
        try:
            valid = await asyncio.to_thread(_validate_pair, key_id, key_secret)
        except Exception as exc:  # do not expose a credential-bearing client error
            raise TokenError("invalid_client", "Kissflow access-key validation failed") from exc
        if not valid:
            raise TokenError("invalid_client", "Kissflow access-key validation failed")
        return key_id, key_secret

    async def _validate_code_identity(self, code: AuthorizationCode) -> None:
        """Validate the stored Entra token before spending a Kissflow request on the pair gate."""
        try:
            code_model = await self._code_store.get(key=code.code)
        except Exception as exc:  # pragma: no cover - storage failure is deployment-specific
            raise TokenError("invalid_grant", "authorization code could not be loaded") from exc
        if code_model is None:
            raise TokenError("invalid_grant", "authorization code does not exist")
        await self._extract_upstream_claims(code_model.idp_tokens)

    async def _consume_failed_code(self, code: AuthorizationCode) -> None:
        try:
            await self._code_store.delete(key=code.code)
            async with self._authorization_code_claim_lock:
                self._claimed_authorization_codes.discard(code.code)
        except Exception as exc:  # pragma: no cover - storage failure is deployment-specific
            raise TokenError("invalid_grant", "authorization code could not be consumed") from exc

    def _bind_access_token(
        self,
        token: OAuthToken,
        client: OAuthClientInformationFull,
        key_id: str,
        key_secret: str,
    ) -> OAuthToken:
        """Reissue one parent access JWT while preserving its JTI, claims, and expiry.

        Equation: ``new_access = issue(JTI, client_id, scopes, exp-now, claims + encrypted_pair)``;
        the parent refresh token is copied byte-for-byte so its stored hash remains valid.
        """
        try:
            payload = self.jwt_issuer.verify_token(token.access_token)
            jti = str(payload["jti"])
            token_client_id = str(payload["client_id"])
            if client.client_id != token_client_id:
                raise ValueError("client mismatch")
            exp = int(payload["exp"])
            remaining = exp - int(time.time())
            if remaining <= 0:
                raise ValueError("access token expired")
            raw_scopes = payload.get("scope", "")
            scopes = raw_scopes.split() if isinstance(raw_scopes, str) and raw_scopes else []
            upstream = payload.get("upstream_claims")
            merged_claims = dict(upstream) if isinstance(upstream, dict) else {}
            merged_claims[KISSFLOW_CREDENTIALS_CLAIM] = _seal(
                KISSFLOW_CREDENTIALS_KIND,
                {"kid": key_id, "sec": key_secret},
            )
            access_token = self.jwt_issuer.issue_access_token(
                client_id=token_client_id,
                scopes=scopes,
                jti=jti,
                expires_in=remaining,
                upstream_claims=merged_claims,
            )
        except TokenError:
            raise
        except Exception as exc:
            raise TokenError("invalid_grant", "issued access token could not be bound") from exc
        return OAuthToken(
            access_token=access_token,
            token_type=token.token_type,
            expires_in=remaining,
            refresh_token=token.refresh_token,
            scope=token.scope,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        try:
            await self._validate_code_identity(authorization_code)
            key_id, key_secret = await self._caller_pair(client)
        except TokenError:
            # A failed Entra or Kissflow gate must not leave a reusable authorization code behind.
            await self._consume_failed_code(authorization_code)
            raise
        token = await super().exchange_authorization_code(client, authorization_code)
        return self._bind_access_token(token, client, key_id, key_secret)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # TokenHandler has already loaded and scope-checked the FastMCP refresh token. The lock
        # spans pair validation and parent rotation, so a copied request cannot both rotate.
        async with self._refresh_grant_lock:
            key_id, key_secret = await self._caller_pair(client)
            token = await super().exchange_refresh_token(client, refresh_token, scopes)
            return self._bind_access_token(token, client, key_id, key_secret)

    async def _extract_upstream_claims(
        self, idp_tokens: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Verify the upstream JWT, then apply the email-domain gate to verified claims only."""
        access_token = idp_tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenError("invalid_client", "Entra access token is missing")
        cache = _VERIFIED_UPSTREAM_CLAIMS.get()
        claims = cache.get(access_token) if cache is not None else None
        if claims is None:
            try:
                validated = await self._token_validator.verify_token(access_token)
            except Exception as exc:
                raise TokenError("invalid_client", "Entra identity validation failed") from exc
            verified_claims = getattr(validated, "claims", None) if validated is not None else None
            if not isinstance(verified_claims, dict):
                raise TokenError("invalid_client", "Entra identity validation failed")
            claims = {
                name: verified_claims[name]
                for name in AZURE_IDENTITY_CLAIMS
                if name in verified_claims
            }
            if cache is not None:
                cache[access_token] = claims
        if not self._allowed_email_domains:
            return claims
        email = next(
            (
                value.strip().lower()
                for name in ("preferred_username", "email", "upn")
                for value in [claims.get(name)]
                if isinstance(value, str) and "@" in value and value.rsplit("@", 1)[-1]
            ),
            "",
        )
        if not email:
            raise TokenError("invalid_client", "Entra identity has no allowed email claim")
        domain = email.rsplit("@", 1)[-1]
        if domain not in self._allowed_email_domains:
            raise TokenError("invalid_client", "Entra identity domain is not permitted")
        return claims


# --- wiring --------------------------------------------------------------------------


def creds_from_token() -> tuple[str, str] | None:
    """Decrypt the caller's pair from validated upstream claims, or return ``None``.

    The MCP request must already carry a FastMCP-valid access token. The ciphertext is authenticated
    by ``MCP_OAUTH_SIGNING_KEY``; a missing, forged, or mismatched claim fails closed.
    """
    from fastmcp.server.dependencies import get_access_token

    try:
        token = get_access_token()
    except (RuntimeError, LookupError):
        return None
    if token is None:
        return None
    claims = getattr(token, "claims", None) or {}
    upstream = claims.get("upstream_claims")
    if not isinstance(upstream, dict):
        return None
    sealed = upstream.get(KISSFLOW_CREDENTIALS_CLAIM)
    if not isinstance(sealed, str):
        return None
    data = _open(KISSFLOW_CREDENTIALS_KIND, sealed, None)
    if data is None:
        return None
    key_id, key_secret = data.get("kid"), data.get("sec")
    if not isinstance(key_id, str) or not isinstance(key_secret, str) or not key_id or not key_secret:
        return None
    # AzureProvider returns the validated upstream token's client_id (azp/sub), not the MCP
    # static client_id. Fernet integrity, the signed FastMCP JWT, and the JTI mapping are the
    # binding here; comparing against AccessToken.client_id would reject every valid Entra token.
    return key_id, key_secret


def provider_from_env() -> KissflowOAuthProvider:
    """Build the mandatory HTTP provider; incomplete configuration fails closed at startup."""
    signing_key = _required_env(SIGNING_KEY_ENV)
    _fernet()
    tenant_id = _required_env(AZURE_TENANT_ID_ENV)
    azure_client_id = _required_env(AZURE_CLIENT_ID_ENV)
    azure_client_secret = _required_env(AZURE_CLIENT_SECRET_ENV)
    required_scopes = _split_env(AZURE_REQUIRED_SCOPES_ENV)
    if not required_scopes or all(scope in OIDC_ONLY_SCOPES for scope in required_scopes):
        raise RuntimeError(
            f"{AZURE_REQUIRED_SCOPES_ENV} must contain at least one non-OIDC application scope"
        )
    resolved = _tenant_env()
    if isinstance(resolved, Err):
        raise RuntimeError(resolved.message)  # noqa: TRY004 — Err is the existing config result type
    _prefix, domain, account = resolved
    if not domain.strip() or not account.strip():
        raise RuntimeError("Kissflow tenant domain and account must be set in HTTP mode")
    base_url = _base_url_from_env()
    redirect_path = os.environ.get(AZURE_REDIRECT_PATH_ENV, "/auth/callback").strip()
    if not redirect_path.startswith("/"):
        raise RuntimeError(f"{AZURE_REDIRECT_PATH_ENV} must start with '/'")
    provider = KissflowOAuthProvider(
        client_id=azure_client_id,
        client_secret=azure_client_secret,
        tenant_id=tenant_id,
        required_scopes=required_scopes,
        additional_authorize_scopes=_split_env(AZURE_ADDITIONAL_SCOPES_ENV) or None,
        identifier_uri=os.environ.get(AZURE_IDENTIFIER_URI_ENV, "").strip() or None,
        base_authority=os.environ.get(AZURE_BASE_AUTHORITY_ENV, "").strip()
        or "login.microsoftonline.com",
        token_issuer=os.environ.get(AZURE_TOKEN_ISSUER_ENV, "").strip() or None,
        redirect_path=redirect_path,
        base_url=base_url,
        jwt_signing_key=signing_key,
        allowed_email_domains=_split_env(ALLOWED_EMAIL_DOMAINS_ENV),
        allowed_client_redirect_uris=_redirect_patterns(),
    )
    print(
        f"two-gate Entra + Kissflow OAuth ENABLED at {base_url}; disk-backed FastMCP state "
        "requires one active replica until shared storage is configured",
        file=sys.stderr,
        flush=True,
    )
    return provider
