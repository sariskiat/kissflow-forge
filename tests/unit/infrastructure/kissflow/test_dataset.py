"""`KissflowDatasetRepository`: the invariant transport, a differential test per port
method, error translation per status, all against `KfClient`'s four `/dataset/2/...`
record routes."""

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

from app.application.exceptions import RepositoryError
from app.infrastructure.kissflow.dataset import KissflowDatasetRepository


def _adapter(client: httpx.AsyncClient) -> KissflowDatasetRepository:
    return KissflowDatasetRepository(
        client=client, base_url=BASE_URL, settings=settings()
    )


# =====================================================================
# 1. The invariant transport
# =====================================================================


@pytest.mark.asyncio
async def test_every_request_carries_the_invariant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_invariant(request.url.host, request.url.scheme, request.headers)
        return httpx.Response(200, json={"_id": "rec-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.create_dataset_record("A1", "F1", {"Name": "rec-1"})
        await adapter.list_dataset_records("A1", "F1")
        await adapter.update_dataset_record("A1", "F1", "rec-1", {"Status": "Done"})
        await adapter.delete_dataset_record("A1", "F1", "rec-1", "rec-1")


# =====================================================================
# 2. A differential test per port method
# =====================================================================


@pytest.mark.asyncio
async def test_create_dataset_record_differential() -> None:
    canned = {"_id": "rec-1", "Name": "rec-1"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_dataset_record(
            "A1", "F1", {"Name": "rec-1"}
        )

    await assert_differential(
        family="dataset",
        method_name="create_dataset_record",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_list_dataset_records_differential() -> None:
    canned = {"Columns": [], "Data": []}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).list_dataset_records("A1", "F1")

    await assert_differential(
        family="dataset",
        method_name="list_dataset_records",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_update_dataset_record_differential() -> None:
    canned = {"_id": "rec-1", "Status": "Done"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).update_dataset_record(
            "A1", "F1", "rec-1", {"Status": "Done"}
        )

    await assert_differential(
        family="dataset",
        method_name="update_dataset_record",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_delete_dataset_record_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).delete_dataset_record(
            "A1", "F1", "rec-1", "rec-1"
        )

    await assert_differential(
        family="dataset",
        method_name="delete_dataset_record",
        canned_json=canned,
        call_new=call_new,
    )


# =====================================================================
# 3. Error translation per status
# =====================================================================


@pytest.mark.asyncio
async def test_error_translation() -> None:
    async def call(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_dataset_record(
            "A1", "F1", {"Name": "rec-1"}
        )

    await assert_error_translation(call=call, error_cls=RepositoryError)


# =====================================================================
# 4. Host binding (security-judge finding 2, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_refuses_requests_off_the_configured_tenant_host() -> None:
    def build_adapter(
        client: httpx.AsyncClient, base_url: str, settings_: Any
    ) -> KissflowDatasetRepository:
        return KissflowDatasetRepository(
            client=client, base_url=base_url, settings=settings_
        )

    async def call(adapter: KissflowDatasetRepository) -> Any:
        return await adapter.list_dataset_records("A1", "F1")

    await assert_refuses_off_tenant_requests(
        build_adapter=build_adapter,
        call=call,
        settings=settings(),
        error_cls=RepositoryError,
    )


# =====================================================================
# 5. Caller ids are percent-encoded path segments (security-judge finding
#    7, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_a_path_traversal_flow_id_never_collapses_the_path() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_id": "rec-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).create_dataset_record(
            "A1", "../../../../admin", {"Name": "rec-1"}
        )

    assert len(calls) == 1
    assert calls[0].url.raw_path.startswith(f"/dataset/2/{ACCOUNT}/".encode())


@pytest.mark.asyncio
async def test_a_query_injection_flow_id_does_not_corrupt_the_real_query_param() -> (
    None
):
    """`create_dataset_record`'s URL already carries `?_application_id=...` after
    the flow id, so an unencoded `?` in the id would swallow that real
    parameter into the id's own bogus query text instead of just appending a
    new one."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_id": "rec-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).create_dataset_record(
            "A1", "x?evil=1", {"Name": "rec-1"}
        )

    assert len(calls) == 1
    assert calls[0].url.params["_application_id"] == "A1"
    assert "evil" not in calls[0].url.params


# =====================================================================
# 6. Query values are encoded (security-judge finding 2, round 2) -- the
#    exact proven case. Source: the `app_id` tool argument. Sink: the
#    `_id` query parameter that follows `_application_id` in
#    `update_dataset_record`'s query string. Guard: `build_query` runs
#    every value through `urlencode`, so an `app_id` of
#    `"APP&_id=VICTIM#"` can no longer smuggle its own `&_id=VICTIM#` ahead
#    of the caller's real `_id=MINE` and truncate it into the fragment.
# =====================================================================


@pytest.mark.asyncio
async def test_update_dataset_record_query_injection_does_not_hijack_the_id() -> None:
    """The old, unencoded query for `update_dataset_record(app_id="APP&_id=
    VICTIM#", ..., record_id="MINE")` read `?_application_id=APP&_id=VICTIM#
    &_id=MINE`: a URL parser reads everything from `#` on as the fragment,
    so the real `_id=MINE` never reached the query string at all, and the
    write landed on `VICTIM`'s record instead of `MINE`'s."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_id": "MINE"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).update_dataset_record(
            "APP&_id=VICTIM#", "DS", "MINE", {"Status": "Done"}
        )

    assert len(calls) == 1
    assert calls[0].url.params["_id"] == "MINE"
    assert calls[0].url.params["_application_id"] == "APP&_id=VICTIM#"
    assert calls[0].url.fragment == ""
