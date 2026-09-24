"""`KissflowCopilotService`: the invariant transport, a differential test per port
method, error translation per status, all against
`KfClient.copilot_send`/`copilot_conversations`."""

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
from app.infrastructure.kissflow.copilot import KissflowCopilotService


def _adapter(client: httpx.AsyncClient) -> KissflowCopilotService:
    return KissflowCopilotService(client=client, base_url=BASE_URL, settings=settings())


# =====================================================================
# 1. The invariant transport
# =====================================================================


@pytest.mark.asyncio
async def test_every_request_carries_the_invariant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_invariant(request.url.host, request.url.scheme, request.headers)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.copilot_send("A1", "hello")
        await adapter.copilot_conversations("A1")


# =====================================================================
# 2. A differential test per port method
# =====================================================================


@pytest.mark.asyncio
async def test_copilot_send_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).copilot_send("A1", "hello")

    await assert_differential(
        family="copilot",
        method_name="copilot_send",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_copilot_conversations_differential() -> None:
    canned = [{"ConversationId": "C1", "UserMessage": "hi"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).copilot_conversations("A1")

    await assert_differential(
        family="copilot",
        method_name="copilot_conversations",
        canned_json=canned,
        call_new=call_new,
    )


# =====================================================================
# 3. Error translation per status
# =====================================================================


@pytest.mark.asyncio
async def test_error_translation() -> None:
    async def call(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).copilot_send("A1", "hello")

    await assert_error_translation(call=call, error_cls=ExternalServiceError)


# =====================================================================
# 4. Host binding (security-judge finding 2, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_refuses_requests_off_the_configured_tenant_host() -> None:
    def build_adapter(
        client: httpx.AsyncClient, base_url: str, settings_: Any
    ) -> KissflowCopilotService:
        return KissflowCopilotService(
            client=client, base_url=base_url, settings=settings_
        )

    async def call(adapter: KissflowCopilotService) -> Any:
        return await adapter.copilot_conversations("A1")

    await assert_refuses_off_tenant_requests(
        build_adapter=build_adapter,
        call=call,
        settings=settings(),
        error_cls=ExternalServiceError,
    )


# =====================================================================
# 5. Caller ids are percent-encoded path segments (security-judge finding
#    7, Stage C hardening). `app_id` appears twice in this family's URLs --
#    once as a path segment, once as the pre-existing `_application_id`
#    query value -- only the path occurrence is a new encoding site; the
#    query occurrence is unchanged, per "keep the query parameters that
#    the old URLs carry".
# =====================================================================


@pytest.mark.asyncio
async def test_a_path_traversal_app_id_never_collapses_the_path() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).copilot_send("../../../../admin", "hi")

    assert len(calls) == 1
    assert calls[0].url.raw_path.startswith(
        f"/metadata/2/{ACCOUNT}/ai/application/".encode()
    )


@pytest.mark.asyncio
async def test_a_query_injection_app_id_keeps_the_send_action_in_the_path() -> None:
    """An unquoted `?` in the PATH occurrence of `app_id` would swallow
    `/copilot/send` into a bogus query string and truncate the real
    `_application_id` value down to `"x"`; quoting only that occurrence
    keeps `/copilot/send` in the path and the full id in the query value."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).copilot_send("x?evil=1", "hi")

    assert len(calls) == 1
    path_only = calls[0].url.raw_path.split(b"?", 1)[0]
    assert path_only.endswith(b"/copilot/send")
    assert calls[0].url.params["_application_id"] == "x?evil=1"


# =====================================================================
# 6. Query values are encoded (security-judge finding 2, round 2). Source:
#    the `app_id` tool argument. Sink: the `_application_id` query value.
#    Guard: `build_query` runs `app_id` through `urlencode`, so `&`/`#`
#    inside it can neither inject a new query parameter nor get truncated
#    at a fragment boundary.
# =====================================================================


@pytest.mark.asyncio
async def test_copilot_send_query_injection_does_not_add_a_bogus_parameter() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).copilot_send("A1&UserMessage=HIJACKED#", "hi")

    assert len(calls) == 1
    assert calls[0].url.params["_application_id"] == "A1&UserMessage=HIJACKED#"
    assert "UserMessage" not in calls[0].url.params
    assert calls[0].url.fragment == ""
