"""`app.infrastructure.kissflow._http`: `sign`, `send_json`, `read_verify_write`."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.application.exceptions import REFUSED, ExternalServiceError, RepositoryError
from app.domain.entities.flow_draft import FlowDraft
from app.infrastructure.kissflow import _http
from app.infrastructure.kissflow.credentials import KissflowKeyPair

_HOST = "dev-x.kissflow.com"
_ACCOUNT = "ACC1"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    error_cls: type[RepositoryError] = RepositoryError,
    *,
    expected_host: str = _HOST,
    account_id: str = _ACCOUNT,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    return await _http.send_json(
        client,
        method,
        url,
        error_cls,
        expected_host=expected_host,
        account_id=account_id,
        json_body=json_body,
        headers=headers,
    )


# ======================================================================
# Security-judge finding 7 (Stage C hardening): a caller-supplied id goes
# straight into a URL path segment unencoded. Source: a `flow_id`/`app_id`/
# etc. tool argument. Sink: the f-string-built request URL. Guard:
# `quote_path_segment` percent-encodes every reserved character before the
# id reaches the URL.
# ======================================================================


def test_quote_path_segment_is_the_identity_for_an_ordinary_id() -> None:
    assert _http.quote_path_segment("F-123_abc", RepositoryError) == "F-123_abc"


def test_quote_path_segment_escapes_a_path_traversal_id() -> None:
    assert _http.quote_path_segment("../../../../admin", RepositoryError) == (
        "..%2F..%2F..%2F..%2Fadmin"
    )


def test_quote_path_segment_escapes_a_query_injection_id() -> None:
    assert _http.quote_path_segment("x?evil=1", RepositoryError) == "x%3Fevil%3D1"
    assert _http.quote_path_segment("x&evil=1", RepositoryError) == "x%26evil%3D1"


# ======================================================================
# Security-judge finding 1 (round 2): an id of exactly "..", "." or "" turns
# a narrow call into a destructive one. Source: a `flow_id`/`app_id`/`page_id`
# tool argument. Sink: the f-string-built request URL -- `quote()` treats
# `.` as always-safe, and httpx removes dot segments (RFC 3986 5.2.4) before
# it sends, so `.../application/APP/page/..` is sent as `.../application/APP`,
# the whole-application resource, not the page one. Guard: `quote_path_segment`
# refuses all three values before any encoding runs, with the family's own
# error class and `code=REFUSED`, naming the refused value.
# ======================================================================


@pytest.mark.parametrize("value", ["", ".", ".."])
def test_quote_path_segment_refuses_unsafe_values(value: str) -> None:
    with pytest.raises(RepositoryError) as excinfo:
        _http.quote_path_segment(value, RepositoryError)
    assert excinfo.value.code == REFUSED
    assert repr(value) in excinfo.value.message


def test_quote_path_segment_refuses_with_the_callers_own_error_class() -> None:
    """The refusal raises whatever `error_cls` the caller passed -- item and
    copilot pass `ExternalServiceError`, not a hardcoded class."""
    with pytest.raises(ExternalServiceError) as excinfo:
        _http.quote_path_segment("..", ExternalServiceError)
    assert excinfo.value.code == REFUSED


# ======================================================================
# Security-judge finding 2 (round 2): an unencoded query value can smuggle
# an extra parameter, or truncate the intended query early. Source: a
# caller-supplied value (an `app_id`, a `record_id`) placed into a query
# string. Sink: the f-string-built request URL. Guard: `build_query` runs
# every value through `urllib.parse.urlencode`.
# ======================================================================


def test_build_query_is_empty_for_no_params() -> None:
    assert _http.build_query({}) == ""


def test_build_query_is_the_identity_shape_for_an_ordinary_value() -> None:
    assert _http.build_query({"_application_id": "A1"}) == "?_application_id=A1"


def test_build_query_preserves_parameter_name_and_order() -> None:
    assert (
        _http.build_query({"_application_id": "A1", "_id": "R1"})
        == "?_application_id=A1&_id=R1"
    )


def test_build_query_escapes_an_ampersand_and_hash_in_a_value() -> None:
    """`update_dataset_record(app_id="APP&_id=VICTIM#", ..., record_id="MINE")`'s
    old f-string query read `?_application_id=APP&_id=VICTIM#&_id=MINE` -- a URL
    parser reads everything from `#` on as the fragment, so the real
    `_id=MINE` never reached the query string, and the write landed on
    `VICTIM`'s record instead of `MINE`'s."""
    query = _http.build_query({"_application_id": "APP&_id=VICTIM#", "_id": "MINE"})

    assert query == "?_application_id=APP%26_id%3DVICTIM%23&_id=MINE"
    parsed = urllib.parse.urlsplit(f"https://{_HOST}/a{query}")
    assert parsed.fragment == ""
    assert urllib.parse.parse_qs(parsed.query)["_id"] == ["MINE"]


def test_safe_route_leaves_the_route_alone_when_account_id_is_empty() -> None:
    """The empty-`account_id` guard: `"".replace("", ...)` would otherwise insert
    the placeholder between every character of the route, corrupting it."""
    assert _http._safe_route(f"https://{_HOST}/a?x=1", "") == "/a?x=1"


def test_sign_returns_the_four_kissflow_headers() -> None:
    pair = KissflowKeyPair(key_id="k1", key_secret="s1")
    assert _http.sign(pair) == {
        "X-Access-Key-Id": "k1",
        "X-Access-Key-Secret": "s1",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_send_json_returns_parsed_body_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        result = await _send(client, "GET", f"https://{_HOST}/a")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_send_json_raises_on_404_with_the_status_in_its_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", f"https://{_HOST}/a")
    assert "404" in excinfo.value.message
    assert "not found" in excinfo.value.message
    assert excinfo.value.code == "REPOSITORY_ERROR"


@pytest.mark.asyncio
async def test_send_json_raises_conflict_on_409() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="conflict")

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "PUT", f"https://{_HOST}/a")
    assert excinfo.value.code == "CONFLICT"
    assert "409" in excinfo.value.message


@pytest.mark.asyncio
async def test_send_json_raises_conflict_on_400_with_kissflow_conflict_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"error":"KISSFLOW_ERROR_04602"}')

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "DELETE", f"https://{_HOST}/a")
    assert excinfo.value.code == "CONFLICT"


@pytest.mark.asyncio
async def test_send_json_400_without_the_conflict_code_is_a_plain_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "POST", f"https://{_HOST}/a")
    assert excinfo.value.code == "REPOSITORY_ERROR"


@pytest.mark.asyncio
async def test_send_json_raises_on_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", f"https://{_HOST}/a")
    assert "500" in excinfo.value.message
    assert excinfo.value.code == "REPOSITORY_ERROR"


@pytest.mark.asyncio
async def test_send_json_raises_on_a_non_json_200_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", f"https://{_HOST}/a")
    assert "non-JSON body" in excinfo.value.message


@pytest.mark.asyncio
async def test_send_json_raises_on_a_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", f"https://{_HOST}/a")
    assert excinfo.value.message.startswith("transport error:")


@pytest.mark.asyncio
async def test_send_json_never_follows_a_redirect_to_another_origin() -> None:
    """P1 review (mid-task correction): the old urllib transport followed
    redirects and replayed every header, so a 3xx would resend
    X-Access-Key-Secret to another origin, or allow an https-to-http
    downgrade. `follow_redirects=False` must hold: a 301 makes exactly one
    request, never a second one to the redirect target, and raises the same
    as any other non-200 status, with the 301 status in its message."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            301, headers={"Location": "http://evil.example.com/steal"}
        )

    pair = KissflowKeyPair(key_id="k1", key_secret="s1")
    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(
                client,
                "GET",
                f"https://{_HOST}/a",
                headers=_http.sign(pair),
            )

    assert len(calls) == 1
    assert calls[0].url.host == _HOST
    assert "301" in excinfo.value.message


# ======================================================================
# Security-judge finding 5 (Stage C hardening): the error message reaches an
# MCP client through `ToolError`, a path `mask_error_details` does not
# cover. Source: the outbound request URL, which carries the tenant host
# and the dev-tenant account id. Sink: `ApplicationError.message`, read
# verbatim by the tool boundary. Guard: strip the scheme and host, and
# scrub every occurrence of the account id, before the message is built.
# ======================================================================


@pytest.mark.asyncio
async def test_send_json_error_message_drops_the_scheme_host_and_account_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="KISSFLOW_ERROR_01234: no such flow")

    url = f"https://{_HOST}/flow/2/{_ACCOUNT}/process/F1?_application_id=App1"
    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", url)

    message = excinfo.value.message
    assert _HOST not in message
    assert "https://" not in message
    assert _ACCOUNT not in message
    assert "GET" in message
    assert "404" in message
    assert "/process/F1" in message
    assert "no such flow" in message


@pytest.mark.asyncio
async def test_send_json_non_json_message_also_drops_scheme_host_and_account_id() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    url = f"https://{_HOST}/flow/2/{_ACCOUNT}/process/F1"
    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", url)

    message = excinfo.value.message
    assert _HOST not in message
    assert _ACCOUNT not in message
    assert "non-JSON body" in message


# ======================================================================
# Security-judge finding 2 (Stage C hardening): `_http.py` documented the
# invariant `r.url.host == settings.kf_dev_domain` but nothing enforced it
# at runtime. Source: `url`, built by the calling adapter from its own
# `base_url`. Sink: the outbound `client.request()` call, which would carry
# `X-Access-Key-Secret` to whatever host `url` names. Guard: a host+scheme
# check before the request goes out, raising `error_cls` with no request
# made when it fails.
# ======================================================================


@pytest.mark.asyncio
async def test_send_json_refuses_a_host_mismatch_with_no_request_made() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        with pytest.raises(RepositoryError):
            await _send(client, "GET", "https://evil.example.com/a")

    assert calls == []


@pytest.mark.asyncio
async def test_send_json_refuses_an_http_scheme_with_no_request_made() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        with pytest.raises(RepositoryError):
            await _send(client, "GET", f"http://{_HOST}/a")

    assert calls == []


# ======================================================================
# Security-judge finding 3 (round 2): the host check read only `.hostname`,
# so it skipped the port and any userinfo. Source: `url`, built by the
# calling adapter from its own `base_url`. Sink: the outbound
# `client.request()` call, which would carry `X-Access-Key-Secret` to
# whatever origin `url` names. Guard: `send_json` also refuses an explicit
# port and userinfo (`user:pass@host`), with no request sent.
# ======================================================================


@pytest.mark.asyncio
async def test_send_json_refuses_an_explicit_port_with_no_request_made() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        with pytest.raises(RepositoryError):
            await _send(client, "GET", f"https://{_HOST}:8443/a")

    assert calls == []


@pytest.mark.asyncio
async def test_send_json_refuses_userinfo_with_no_request_made() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        with pytest.raises(RepositoryError):
            await _send(client, "GET", f"https://u:p@{_HOST}/a")

    assert calls == []


@pytest.mark.asyncio
async def test_send_json_refuses_a_non_numeric_port_with_no_request_made() -> None:
    """A port that does not even parse as an integer must not slip past the
    check as "no port" -- `urlsplit(...).port` raises `ValueError` for one,
    and that must translate to a refusal, not an unhandled exception."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        with pytest.raises(RepositoryError):
            await _send(client, "GET", f"https://{_HOST}:notaport/a")

    assert calls == []


# ======================================================================
# Security-judge finding 4 (round 2): a transport error's own text can carry
# the tenant host -- a TLS hostname-mismatch message names it, for one.
# Source: `str(exc)` from the underlying httpx/httpcore exception. Sink:
# `ApplicationError.message`, read verbatim by the tool boundary through
# `ToolError`, a path `mask_error_details` does not cover. Guard: only the
# exception's class name survives into the message.
# ======================================================================


@pytest.mark.asyncio
async def test_send_json_transport_error_message_never_carries_the_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"[SSL: CERTIFICATE_VERIFY_FAILED] hostname mismatch for {_HOST}",
            request=request,
        )

    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", f"https://{_HOST}/a")

    assert excinfo.value.message == "transport error: ConnectError"
    assert _HOST not in excinfo.value.message


# ======================================================================
# Security-judge finding 4 (Stage C hardening): `except httpx.HTTPError`
# does not catch `httpx.InvalidURL` (a sibling of `Exception`, not a
# subclass of `HTTPError`), so a malformed URL that still names the right
# host -- one that passes the finding-2 pre-check but that httpx's own
# stricter parser still refuses (a non-printable character, for one) --
# escaped `send_json` as a raw httpx exception instead of `error_cls`.
# ======================================================================


@pytest.mark.asyncio
async def test_send_json_translates_a_malformed_url_with_the_right_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    url = f"https://{_HOST}/\x00bad"
    async with _client(handler) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _send(client, "GET", url)

    assert excinfo.value.message.startswith("transport error:")


@pytest.mark.asyncio
async def test_read_verify_write_writes_when_the_version_matches() -> None:
    live = FlowDraft.from_wire({"_meta_version": "v1"})
    written = FlowDraft.from_wire({"_meta_version": "v2"})
    write_calls: list[bool] = []

    async def read() -> FlowDraft:
        return live

    async def write() -> FlowDraft:
        write_calls.append(True)
        return written

    result = await _http.read_verify_write(
        read=read, write=write, expect_version="v1", error_cls=RepositoryError
    )

    assert result is written
    assert write_calls == [True]


@pytest.mark.asyncio
async def test_read_verify_write_raises_conflict_on_drift_without_writing() -> None:
    live = FlowDraft.from_wire({"_meta_version": "v-live"})
    write_calls: list[bool] = []

    async def read() -> FlowDraft:
        return live

    async def write() -> FlowDraft:
        write_calls.append(True)
        return live

    with pytest.raises(RepositoryError) as excinfo:
        await _http.read_verify_write(
            read=read, write=write, expect_version="v-stale", error_cls=RepositoryError
        )

    assert excinfo.value.code == "CONFLICT"
    assert write_calls == []
    assert "v-stale" in excinfo.value.message
    assert "v-live" in excinfo.value.message


# ======================================================================
# Security-judge finding 3 (Stage C hardening): a whole-draft clobber.
# Source: the caller's own `expect_version` argument (`None` meaning "I
# expect a draft with no version yet"). Sink: the unconditional `write()`
# call, which overwrites whatever is live. Guard: `None` only skips the
# conflict when the live draft ALSO carries no version; all four
# (expect_version, live_version) combinations are covered below.
# ======================================================================


@pytest.mark.asyncio
async def test_read_verify_write_writes_when_both_expect_and_live_are_versionless() -> (
    None
):
    """(None, None): a brand new draft, nothing to clobber."""
    live = FlowDraft.from_wire({})
    write_calls: list[bool] = []

    async def read() -> FlowDraft:
        return live

    async def write() -> FlowDraft:
        write_calls.append(True)
        return live

    result = await _http.read_verify_write(
        read=read, write=write, expect_version=None, error_cls=RepositoryError
    )

    assert result is live
    assert write_calls == [True]


@pytest.mark.asyncio
async def test_read_verify_write_conflicts_when_expect_none_live_has_version() -> None:
    """(None, "v-live"): the caller planned against "no version yet", but the
    live draft already has one -- writing anyway would clobber it."""
    live = FlowDraft.from_wire({"_meta_version": "v-live"})
    write_calls: list[bool] = []

    async def read() -> FlowDraft:
        return live

    async def write() -> FlowDraft:
        write_calls.append(True)
        return live

    with pytest.raises(RepositoryError) as excinfo:
        await _http.read_verify_write(
            read=read, write=write, expect_version=None, error_cls=RepositoryError
        )

    assert excinfo.value.code == "CONFLICT"
    assert write_calls == []
    assert "v-live" in excinfo.value.message
