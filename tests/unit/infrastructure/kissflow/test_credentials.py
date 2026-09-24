"""The caller's own Kissflow key pair, read fresh on every call (refactor spec G4, D4).

HR2: the key pair is never a tool argument, never logged, never stored by the server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from app.infrastructure.config.settings import Settings, load_settings
from app.infrastructure.kissflow import credentials
from app.infrastructure.kissflow.credentials import KissflowKeyPair, caller_keys
from app.infrastructure.mcp.lifespan import app_lifespan
from app.infrastructure.mcp.server import create_server


def _real_server() -> FastMCP:
    """Build the real server (every family's real adapters) around the real
    `app_lifespan`, reading `Settings` off the current environment -- the
    same shape `app.main.main` builds for a real run. `create_server` never
    hits the network itself; the two tests below spy on
    `httpx.AsyncClient.request`, the one seam every adapter's shared
    transport (`_http.send_json`) sends through, instead of `KfClient._req`
    (removed with the rest of `app.infrastructure.kissflow.client`, Stage E).
    """
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> Any:
        async with app_lifespan(server, settings) as context:
            yield context

    return create_server(lifespan)


FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "tool_surface.json"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "A",
        "kf_app": None,
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": None,
        "kf_dev_access_key_secret": None,
        "http_timeout_seconds": 10.0,
    }
    values.update(overrides)
    return Settings(**values)


# ======================================================================
# 1. Both headers present over HTTP -> a pair
# ======================================================================


def test_both_headers_present_over_http_returns_a_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {
            "x-access-key-id": "key-1",
            "x-access-key-secret": "secret-1",  # gitleaks:allow
        },
    )
    settings = _settings(mcp_http=True)

    pair = caller_keys(settings)

    assert pair == KissflowKeyPair(key_id="key-1", key_secret="secret-1")


# ======================================================================
# 2. One header missing over HTTP -> ToolError, and no outbound Kissflow call happens
# ======================================================================


def test_one_header_missing_over_http_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials, "get_http_headers", lambda **_: {"x-access-key-id": "key-1"}
    )
    settings = _settings(mcp_http=True)

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(settings)


# ======================================================================
# 2b. A whitespace-only header is not a pair either (security-judge finding
#     6, Stage C hardening). Source: the `X-Access-Key-Id`/`X-Access-Key-Secret`
#     request headers, caller-controlled over HTTP. Sink: `KissflowKeyPair`,
#     which every adapter signs onto its outbound Kissflow request. Guard:
#     `if not key_id or not key_secret` treated `" "` as truthy, so a
#     whitespace-only header reached Kissflow as a literal credential
#     instead of being refused.
# ======================================================================


def test_whitespace_only_key_id_over_http_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {"x-access-key-id": " ", "x-access-key-secret": "secret-1"},
    )
    settings = _settings(mcp_http=True)

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(settings)


def test_whitespace_only_key_secret_over_http_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {"x-access-key-id": "key-1", "x-access-key-secret": " "},
    )
    settings = _settings(mcp_http=True)

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(settings)


def test_surrounding_whitespace_is_stripped_from_an_otherwise_valid_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {
            "x-access-key-id": "  key-1  ",
            "x-access-key-secret": "  secret-1  ",  # gitleaks:allow
        },
    )
    settings = _settings(mcp_http=True)

    pair = caller_keys(settings)

    assert pair == KissflowKeyPair(key_id="key-1", key_secret="secret-1")


# ======================================================================
# 2c. A non-ASCII or non-printable key is not a pair either (security-judge
#     finding 6, round 2). Source: the `X-Access-Key-Id`/`X-Access-Key-Secret`
#     request headers, caller-controlled over HTTP (or `Settings` in stdio
#     mode). Sink: `sign(pair)`'s header dict, which httpx encodes onto the
#     wire -- a zero-width space or another non-ASCII character used to
#     pass the plain emptiness check, then `send_json` raised a raw,
#     untranslated `UnicodeEncodeError` the first time httpx tried to
#     encode it as a header value. Guard: `caller_keys` refuses any key
#     that is not printable ASCII, with the same `ToolError`.
# ======================================================================


def test_a_zero_width_space_in_key_id_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {
            "x-access-key-id": "key​",
            "x-access-key-secret": "secret-1",  # gitleaks:allow
        },
    )
    settings = _settings(mcp_http=True)

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(settings)


def test_a_non_ascii_character_in_key_secret_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {
            "x-access-key-id": "key-1",
            "x-access-key-secret": "sécret-1",  # gitleaks:allow
        },
    )
    settings = _settings(mcp_http=True)

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(settings)


def test_stdio_pair_with_a_zero_width_space_raises_tool_error() -> None:
    settings = _settings(
        mcp_http=False,
        kf_dev_access_key_id="key​",
        kf_dev_access_key_secret="secret-1",  # gitleaks:allow
    )

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(settings)


def test_missing_pair_over_http_makes_no_outbound_kissflow_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The port's own adapter calls caller_keys() before it ever builds request
    headers, so a missing pair fails before any Kissflow call is attempted --
    proven on the real call_tool path, with a spy on the shared httpx transport
    every adapter sends through."""
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-acme.kissflow.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")
    monkeypatch.setenv("MCP_HTTP", "1")
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {"x-access-key-id": "key-1"},  # the secret header is missing
    )
    calls: list[tuple[str, str]] = []

    async def _spy(
        self: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        calls.append((method, url))
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", _spy)

    async def _run() -> Any:
        async with Client(_real_server()) as client:
            return await client.call_tool(
                "forge_doctor", {"flow_id": "F"}, raise_on_error=False
            )

    result = asyncio.run(_run())

    assert result.is_error is True
    assert "no Kissflow key pair on this call" in str(result.content)
    assert calls == []


# ======================================================================
# 3. stdio -> the pair from Settings
# ======================================================================


def test_stdio_pair_comes_from_settings() -> None:
    settings = _settings(
        mcp_http=False,
        kf_dev_access_key_id="key-1",
        kf_dev_access_key_secret="secret-1",  # gitleaks:allow
    )

    pair = caller_keys(settings)

    assert pair == KissflowKeyPair(key_id="key-1", key_secret="secret-1")


def test_stdio_missing_pair_raises_the_same_tool_error() -> None:
    settings = _settings(
        mcp_http=False, kf_dev_access_key_id=None, kf_dev_access_key_secret=None
    )

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(settings)


# ======================================================================
# 4. repr and str never show the secret; the pair reaches the one outbound
#    request, and nowhere else
# ======================================================================


def test_repr_and_str_never_show_the_secret() -> None:
    """The same direct repr assertion `Settings` and `KfConfig` each carry -- honest on
    its own terms because it never manufactures its own log call to "prove" the
    result, unlike the old version of the test below."""
    # gitleaks:allow
    pair = KissflowKeyPair(key_id="key-1", key_secret="super-secret-value")

    assert "super-secret-value" not in repr(pair)
    assert "super-secret-value" not in str(pair)


def test_the_caller_pair_reaches_the_one_outbound_request_and_never_the_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The old version of this test logged `pair` through its OWN logger call and then
    checked that text -- which proves only that `KissflowKeyPair.__str__` masks the
    secret, something covered elsewhere. It never touched the real request path at
    all, so a leak anywhere else in that path (a debug log of the raw headers, for
    instance) would have passed it silently.

    This one builds the real server, sets both headers, spies on the shared
    httpx transport every adapter sends through, and asserts that call carries
    exactly the caller's own key pair and a URL rooted at the configured dev
    domain -- then asserts the logs collected over the whole call hold no trace
    of the secret. `fastmcp`'s own logger has `propagate=False` (it does not
    bubble to the root logger `caplog` listens on by default), so its handler is
    attached directly.
    """
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-acme.kissflow.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")
    monkeypatch.setenv("MCP_HTTP", "1")
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {
            "x-access-key-id": "caller-key-id",
            "x-access-key-secret": "caller-key-secret",  # gitleaks:allow
        },
    )

    calls: list[tuple[str, str, str, str]] = []

    async def _spy(
        self: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        headers = kwargs.get("headers") or {}
        key_id = headers.get("X-Access-Key-Id")
        key_secret = headers.get("X-Access-Key-Secret")
        assert isinstance(key_id, str)
        assert isinstance(key_secret, str)
        calls.append(
            (
                method,
                url,
                key_id,
                key_secret,
            )
        )
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", _spy)

    fastmcp_logger = logging.getLogger("fastmcp")
    fastmcp_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG, logger="fastmcp"):
            server = _real_server()

            async def _run() -> Any:
                async with Client(server) as client:
                    return await client.call_tool(
                        "kf_get_flow_schema",
                        {"flow_kind": "process", "flow_id": "F", "app_id": "App1"},
                        raise_on_error=False,
                    )

            result = asyncio.run(_run())
    finally:
        fastmcp_logger.removeHandler(caplog.handler)

    assert result.is_error is False
    assert len(calls) == 1, f"expected exactly one outbound request, got {calls}"
    method, url, key_id, key_secret = calls[0]
    assert method == "GET"
    assert key_id == "caller-key-id"
    assert key_secret == "caller-key-secret"
    assert url.startswith("https://dev-acme.kissflow.com")
    assert "caller-key-secret" not in caplog.text


# ======================================================================
# 5. no tool parameter is named like a key (surface fixture)
# ======================================================================

_KEY_LIKE_NAMES = frozenset(
    {
        "key_id",
        "key_secret",
        "secret",
        "access_key",
        "api_key",
        "token",
        "password",
    }
)


def test_no_tool_parameter_has_a_key_like_name() -> None:
    """No parameter is NAMED like a credential (exact match, case-insensitive) -- not
    a substring search, which would also flag `forge_plan_app`'s legitimate
    `approval_token` (the design-confirmation HMAC, unrelated to the Kissflow key
    pair, HR3-frozen)."""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    offenders: dict[str, list[str]] = {}
    for tool_name, tool in fixture["tools"].items():
        props = tool["parameters"].get("properties", {})
        hits = [name for name in props if name.lower() in _KEY_LIKE_NAMES]
        if hits:
            offenders[tool_name] = hits
    assert not offenders, f"tool parameters look like credentials: {offenders}"


# ======================================================================
# Bearer fallback: a connector that may only send approved header names
# ======================================================================


def _with_headers(monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]) -> None:
    monkeypatch.setattr(credentials, "get_http_headers", lambda **_: headers)


def test_bearer_pair_over_http_returns_a_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_headers(
        monkeypatch, {"authorization": "Bearer key-1:secret-1"}
    )  # gitleaks:allow

    pair = caller_keys(_settings(mcp_http=True))

    assert pair == KissflowKeyPair(key_id="key-1", key_secret="secret-1")


def test_bearer_secret_may_contain_a_colon(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_headers(
        monkeypatch, {"authorization": "bearer key-1:se:cret"}
    )  # gitleaks:allow

    pair = caller_keys(_settings(mcp_http=True))

    assert pair == KissflowKeyPair(key_id="key-1", key_secret="se:cret")


def test_explicit_pair_wins_over_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_headers(
        monkeypatch,
        {
            "x-access-key-id": "key-x",
            "x-access-key-secret": "secret-x",  # gitleaks:allow
            "authorization": "Bearer key-b:secret-b",  # gitleaks:allow
        },
    )

    pair = caller_keys(_settings(mcp_http=True))

    assert pair.key_id == "key-x"


@pytest.mark.parametrize(
    "value",
    [
        "Basic a2V5OnNlY3JldA==",
        "Bearer no-colon-here",
        "Bearer :secret-only",
        "Bearer key-only:",
        "Bearer    ",
        "Bearer ke​y:secret",
        "",
    ],
)
def test_malformed_bearer_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _with_headers(monkeypatch, {"authorization": value})

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(_settings(mcp_http=True))


def test_authorization_header_is_requested_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fastmcp's get_http_headers drops `authorization` unless it is named in
    `include`; without it the Bearer fallback would silently never see a value."""
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> dict[str, str]:
        seen.update(kwargs)
        return {"authorization": "Bearer key-1:secret-1"}  # gitleaks:allow

    monkeypatch.setattr(credentials, "get_http_headers", fake)
    caller_keys(_settings(mcp_http=True))

    assert "authorization" in seen["include"]


def test_stdio_ignores_the_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_headers(
        monkeypatch, {"authorization": "Bearer key-b:secret-b"}
    )  # gitleaks:allow
    settings = _settings(
        mcp_http=False,
        kf_dev_access_key_id="env-id",
        kf_dev_access_key_secret="env-secret",  # gitleaks:allow
    )

    pair = caller_keys(settings)

    assert pair.key_id == "env-id"


def test_a_lone_key_id_header_is_ignored_in_favour_of_the_whole_bearer_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sources never mix: an incomplete X pair yields to the Bearer pair as a whole."""
    _with_headers(
        monkeypatch,
        {
            "x-access-key-id": "key-x",
            "authorization": "Bearer key-b:secret-b",  # gitleaks:allow
        },
    )

    pair = caller_keys(_settings(mcp_http=True))

    assert pair == KissflowKeyPair(key_id="key-b", key_secret="secret-b")


# ======================================================================
# The approved connector header pair: X-Api-Key + X-Api-Secret
# ======================================================================


def test_approved_api_key_pair_over_http_returns_a_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_headers(
        monkeypatch,
        {"x-api-key": "key-a", "x-api-secret": "secret-a"},  # gitleaks:allow
    )

    pair = caller_keys(_settings(mcp_http=True))

    assert pair == KissflowKeyPair(key_id="key-a", key_secret="secret-a")


def test_api_key_pair_wins_over_bearer_and_leaves_authorization_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway may put its own sign-in token in Authorization; the approved pair
    must win so that token is never read as a Kissflow key."""
    _with_headers(
        monkeypatch,
        {
            "x-api-key": "key-a",
            "x-api-secret": "secret-a",  # gitleaks:allow
            "authorization": "Bearer gateway-token-without-a-colon",
        },
    )

    pair = caller_keys(_settings(mcp_http=True))

    assert pair.key_id == "key-a"


def test_kissflow_pair_wins_over_the_api_key_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_headers(
        monkeypatch,
        {
            "x-access-key-id": "key-x",
            "x-access-key-secret": "secret-x",  # gitleaks:allow
            "x-api-key": "key-a",
            "x-api-secret": "secret-a",  # gitleaks:allow
        },
    )

    assert caller_keys(_settings(mcp_http=True)).key_id == "key-x"


def test_half_an_api_key_pair_never_mixes_with_another_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_headers(
        monkeypatch,
        {"x-api-key": "key-a", "x-access-key-secret": "secret-x"},  # gitleaks:allow
    )

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        caller_keys(_settings(mcp_http=True))


def test_api_key_headers_are_requested_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> dict[str, str]:
        seen.update(kwargs)
        return {"x-api-key": "key-a", "x-api-secret": "secret-a"}  # gitleaks:allow

    monkeypatch.setattr(credentials, "get_http_headers", fake)
    caller_keys(_settings(mcp_http=True))

    assert {"x-api-key", "x-api-secret"} <= seen["include"]


def test_a_whitespace_only_higher_pair_does_not_hide_a_valid_lower_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_headers(
        monkeypatch,
        {
            "x-access-key-id": " ",
            "x-access-key-secret": " ",
            "x-api-key": "key-a",
            "x-api-secret": "secret-a",  # gitleaks:allow
        },
    )

    assert caller_keys(_settings(mcp_http=True)).key_id == "key-a"


def test_api_pair_wins_over_a_bearer_that_also_holds_a_colon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_headers(
        monkeypatch,
        {
            "x-api-key": "key-a",
            "x-api-secret": "secret-a",  # gitleaks:allow
            "authorization": "Bearer gw-id:gw-secret",  # gitleaks:allow
        },
    )

    assert caller_keys(_settings(mcp_http=True)) == KissflowKeyPair(
        key_id="key-a", key_secret="secret-a"
    )
