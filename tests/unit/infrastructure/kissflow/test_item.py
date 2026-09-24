"""`KissflowItemService`: the invariant transport, a differential test per port method
(against the frozen `tests/fixtures/recorded/item/*.json` capture of the OLD
`LiveDataPlane`'s five `/process/2/...` routes, `LiveDataPlane` itself gone with Stage
E), error translation per status."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from tests.unit.infrastructure.kissflow._differential import (
    assert_differential,
    assert_error_translation,
    assert_refuses_off_tenant_requests,
)
from tests.unit.infrastructure.kissflow._fixtures import (
    ACCOUNT,
    BASE_URL,
    assert_invariant,
    settings,
)

from app.application.exceptions import ExternalServiceError
from app.infrastructure.kissflow.item import KissflowItemService


def _adapter(client: httpx.AsyncClient) -> KissflowItemService:
    return KissflowItemService(client=client, base_url=BASE_URL, settings=settings())


# =====================================================================
# 1. The invariant transport
# =====================================================================


@pytest.mark.asyncio
async def test_every_request_carries_the_invariant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_invariant(request.url.host, request.url.scheme, request.headers)
        return httpx.Response(200, json={"_id": "I1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.create_item("F1")
        await adapter.put_fields("F1", "I1", {"Name": "Alice"})
        await adapter.get_detail("F1", "I1")
        await adapter.submit("F1", "I1", "AI1")
        await adapter.reject("F1", "I1", "AI1", "not ready")


# =====================================================================
# 2. A differential test per port method
# =====================================================================


@pytest.mark.asyncio
async def test_create_item_differential() -> None:
    canned = {"_id": "I1"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_item("F1")

    await assert_differential(
        family="item",
        method_name="create_item",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_put_fields_differential() -> None:
    canned = {"_id": "I1", "Name": "Alice"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).put_fields("F1", "I1", {"Name": "Alice"})

    await assert_differential(
        family="item",
        method_name="put_fields",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_get_detail_differential() -> None:
    canned = {"_id": "I1", "_current_context": []}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_detail("F1", "I1")

    await assert_differential(
        family="item",
        method_name="get_detail",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_submit_differential() -> None:
    canned = {"_id": "I1", "Status": "Submitted"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).submit("F1", "I1", "AI1")

    await assert_differential(
        family="item",
        method_name="submit",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_reject_differential() -> None:
    canned = {"_id": "I1", "Status": "Rejected"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).reject("F1", "I1", "AI1", "not ready")

    await assert_differential(
        family="item",
        method_name="reject",
        canned_json=canned,
        call_new=call_new,
    )


# =====================================================================
# 3. Error translation per status
# =====================================================================


@pytest.mark.asyncio
async def test_error_translation() -> None:
    async def call(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_detail("F1", "I1")

    await assert_error_translation(call=call, error_cls=ExternalServiceError)


# =====================================================================
# 4. Host binding (security-judge finding 2, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_refuses_requests_off_the_configured_tenant_host() -> None:
    def build_adapter(
        client: httpx.AsyncClient, base_url: str, settings_: Any
    ) -> KissflowItemService:
        return KissflowItemService(client=client, base_url=base_url, settings=settings_)

    async def call(adapter: KissflowItemService) -> Any:
        return await adapter.get_detail("F1", "I1")

    await assert_refuses_off_tenant_requests(
        build_adapter=build_adapter,
        call=call,
        settings=settings(),
        error_cls=ExternalServiceError,
    )


# =====================================================================
# 5. Caller ids are percent-encoded path segments (security-judge finding
#    7, Stage C hardening). None of this family's routes carry a query
#    string, so a path-traversal or query-injection id corrupts the
#    request differently than in the other families: the traversal id
#    escapes the `/process/2/{account}` prefix entirely, and the
#    injection id swallows the trailing `/submit` action segment into a
#    bogus query string instead of adding a query parameter.
# =====================================================================


@pytest.mark.asyncio
async def test_a_path_traversal_flow_id_never_escapes_the_account_prefix() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).submit("../../../../admin", "I1", "A1")

    assert len(calls) == 1
    assert calls[0].url.raw_path.startswith(f"/process/2/{ACCOUNT}/".encode())


@pytest.mark.asyncio
async def test_a_query_injection_aiid_keeps_the_submit_action_in_the_path() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).submit("F1", "I1", "x?evil=1")

    assert len(calls) == 1
    assert calls[0].url.raw_path.endswith(b"/submit")
    assert not calls[0].url.params


# =====================================================================
# 6. A dot-segment id is refused, not sent (security-judge finding 1,
#    round 2). Source: the `flow_id` tool argument. Sink: the f-string-built
#    request URL -- `.` is always-safe to `quote()`, and httpx removes dot
#    segments (RFC 3986 5.2.4) before it sends, so `put_fields(".", "X",
#    {})` collapsed `/admin/./X` onto `/admin/X`, silently dropping the
#    flow id from the path entirely. Guard: `quote_path_segment` refuses
#    "." before any request is built.
# =====================================================================


@pytest.mark.asyncio
async def test_put_fields_refuses_a_dot_segment_flow_id_with_no_request_sent() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalServiceError) as excinfo:
            await _adapter(client).put_fields(".", "X", {})

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"a request reached the wrong resource: {[c.url for c in calls]}"
    )
