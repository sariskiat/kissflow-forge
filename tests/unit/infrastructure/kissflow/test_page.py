"""`KissflowPageRepository`: the invariant transport, a differential test per port
method, error translation per status, the read-verify-write conflict test, all against
`KfClient`'s six page routes."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from tests.unit.infrastructure.kissflow._differential import (
    assert_conflict_on_drift,
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

from app.application.exceptions import RepositoryError
from app.domain.entities.page_draft import PageDraft
from app.infrastructure.kissflow.page import KissflowPageRepository


def _adapter(client: httpx.AsyncClient) -> KissflowPageRepository:
    return KissflowPageRepository(client=client, base_url=BASE_URL, settings=settings())


# =====================================================================
# 1. The invariant transport
# =====================================================================


@pytest.mark.asyncio
async def test_every_request_carries_the_invariant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_invariant(request.url.host, request.url.scheme, request.headers)
        return httpx.Response(200, json={"_id": "P1", "_meta_version": "v1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.list_pages("A1")
        await adapter.create_page("A1", "Dashboard")
        await adapter.delete_page("A1", "P1")
        await adapter.get_page_draft("A1", "P1")
        await adapter.put_page_draft(
            "A1", "P1", PageDraft.from_wire({"_meta_version": "v1"}), "v1"
        )
        await adapter.publish_page("A1", "P1")


# =====================================================================
# 2. A differential test per port method
# =====================================================================


@pytest.mark.asyncio
async def test_list_pages_differential() -> None:
    canned = [{"_id": "P1", "Name": "Dashboard"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).list_pages("A1")

    await assert_differential(
        family="page",
        method_name="list_pages",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_create_page_differential() -> None:
    canned = {"_id": "P1", "Name": "Dashboard"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_page("A1", "Dashboard")

    await assert_differential(
        family="page",
        method_name="create_page",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_delete_page_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).delete_page("A1", "P1")

    await assert_differential(
        family="page",
        method_name="delete_page",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda _: None,
    )


@pytest.mark.asyncio
async def test_get_page_draft_differential() -> None:
    canned = {"_meta_version": "v1", "nodes": []}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_page_draft("A1", "P1")

    await assert_differential(
        family="page",
        method_name="get_page_draft",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda d: d.to_wire(),
    )


@pytest.mark.asyncio
async def test_put_page_draft_differential() -> None:
    """Read-verify-write: GET then PUT, both against the same canned body."""
    canned = {"_meta_version": "v1", "nodes": []}
    new_draft = PageDraft.from_wire(canned)

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).put_page_draft("A1", "P1", new_draft, "v1")

    await assert_differential(
        family="page",
        method_name="put_page_draft",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda d: d.to_wire(),
        expected_calls=2,
    )


@pytest.mark.asyncio
async def test_publish_page_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).publish_page("A1", "P1")

    await assert_differential(
        family="page",
        method_name="publish_page",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda _: None,
    )


# =====================================================================
# 3. Error translation per status
# =====================================================================


@pytest.mark.asyncio
async def test_error_translation() -> None:
    async def call(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).list_pages("A1")

    await assert_error_translation(call=call, error_cls=RepositoryError)


# =====================================================================
# 4. The read-verify-write conflict test
# =====================================================================


@pytest.mark.asyncio
async def test_put_page_draft_raises_conflict_on_drift() -> None:
    async def put_call(client: httpx.AsyncClient, expect_version: str | None) -> Any:
        new_draft = PageDraft.from_wire({"_meta_version": "v-live"})
        return await _adapter(client).put_page_draft(
            "A1", "P1", new_draft, expect_version
        )

    await assert_conflict_on_drift(
        put_call=put_call, live_version="v-live", error_cls=RepositoryError
    )


# =====================================================================
# 5. Edge cases the differential harness does not exercise by default
# =====================================================================


@pytest.mark.asyncio
async def test_create_page_raises_when_the_response_carries_no_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Name": "Dashboard"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError, match="no _id"):
            await _adapter(client).create_page("A1", "Dashboard")


# =====================================================================
# 6. Host binding (security-judge finding 2, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_refuses_requests_off_the_configured_tenant_host() -> None:
    def build_adapter(
        client: httpx.AsyncClient, base_url: str, settings_: Any
    ) -> KissflowPageRepository:
        return KissflowPageRepository(
            client=client, base_url=base_url, settings=settings_
        )

    async def call(adapter: KissflowPageRepository) -> Any:
        return await adapter.get_page_draft("A1", "P1")

    await assert_refuses_off_tenant_requests(
        build_adapter=build_adapter,
        call=call,
        settings=settings(),
        error_cls=RepositoryError,
    )


# =====================================================================
# 7. Caller ids are percent-encoded path segments (security-judge finding
#    7, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_a_path_traversal_page_id_never_collapses_the_path() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_meta_version": "v1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).get_page_draft("A1", "../../../../admin")

    assert len(calls) == 1
    assert calls[0].url.raw_path.startswith(
        f"/metadata/2/{ACCOUNT}/application/A1/page/".encode()
    )


@pytest.mark.asyncio
async def test_a_query_injection_app_id_does_not_corrupt_the_real_query_param() -> None:
    """`list_pages`'s URL already carries `?page_size=100` after the app id, so
    an unencoded `?` in the id would swallow that fixed parameter into the id's
    own bogus query text instead of just appending a new one."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).list_pages("x?evil=1")

    assert len(calls) == 1
    assert calls[0].url.params["page_size"] == "100"
    assert "evil" not in calls[0].url.params


# =====================================================================
# 8. A dot-segment id is refused, not sent (security-judge finding 1,
#    round 2). Source: the `page_id` tool argument. Sink: the f-string-built
#    request URL -- httpx removes dot segments (RFC 3986 5.2.4) before it
#    sends, so a `page_id` of exactly ".." collapsed the path onto the
#    APPLICATION resource, not the page one: `delete_page` sent the
#    delete-application request, `publish_page` published the whole app,
#    and `put_page_draft` both read and wrote the app's own navigation
#    draft (its version guard passing only because the read landed on that
#    same wrong resource). Guard: `quote_path_segment` refuses ".." before
#    any request is built.
# =====================================================================


@pytest.mark.asyncio
async def test_delete_page_refuses_a_dot_segment_id_with_no_request_sent() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _adapter(client).delete_page("APP", "..")

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"a request reached the wrong resource: {[c.url for c in calls]}"
    )


@pytest.mark.asyncio
async def test_publish_page_refuses_a_dot_segment_id_with_no_request_sent() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _adapter(client).publish_page("APP", "..")

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"a request reached the wrong resource: {[c.url for c in calls]}"
    )


@pytest.mark.asyncio
async def test_put_page_draft_refuses_a_dot_segment_id_with_no_request_sent() -> None:
    """Neither the read nor the write half of the read-verify-write guard
    may fire: both would have landed on the application's own navigation
    draft, not a page draft, with the version guard passing only because
    the read hit that same wrong resource."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_meta_version": "v1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _adapter(client).put_page_draft(
                "APP", "..", PageDraft.from_wire({"_meta_version": "v1"}), "v1"
            )

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"a request reached the wrong resource: {[c.url for c in calls]}"
    )
