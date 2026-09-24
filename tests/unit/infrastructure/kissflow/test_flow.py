"""`KissflowFlowRepository`: the invariant transport, a differential test per port
method, error translation per status, the read-verify-write conflict test, all
against `KfClient`'s 18 flow/process/form/case/list routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast, get_args

import httpx
import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.page import FakePageRepository
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
from app.application.use_cases.flow._delete import delete_anything
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.kinds import AnyFlowKind, FlowKind
from app.infrastructure.kissflow.flow import KissflowFlowRepository


def _adapter(client: httpx.AsyncClient) -> KissflowFlowRepository:
    return KissflowFlowRepository(client=client, base_url=BASE_URL, settings=settings())


# =====================================================================
# 1. The invariant transport
# =====================================================================


@pytest.mark.asyncio
async def test_every_request_carries_the_invariant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_invariant(request.url.host, request.url.scheme, request.headers)
        return httpx.Response(200, json={"_id": "F1", "_meta_version": "v1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.get_draft("A1", "process", "F1")
        await adapter.create_flow("A1", "process", "New flow")
        await adapter.delete_flow("A1", "process", "F1", archive_first=False)
        await adapter.publish("A1", "process", "F1")
        await adapter.get_flow_detail("A1", "process", "F1")
        await adapter.list_flows("A1", "process")
        await adapter.get_members("A1", "process", "F1")
        await adapter.delete_member("A1", "process", "F1", "Ro1")
        await adapter.post_member_batch("A1", "process", "F1", [{"_id": "Ro1"}])
        await adapter.post_report_member_batch("A1", "F1", "Rp1", [{"_id": "Ro1"}])
        await adapter.get_list_items("A1", "L1")
        await adapter.list_lists("A1")
        await adapter.create_list("A1", "Colors")
        await adapter.set_list_items("L1", ["Red", "Blue"])
        await adapter.create_dataset("A1", "Orders")
        await adapter.create_case("A1", "Cases", "Case", "CS")
        await adapter.put_draft(
            "A1", "process", "F1", FlowDraft.from_wire({"_meta_version": "v1"}), "v1"
        )


# =====================================================================
# 2. A differential test per port method
# =====================================================================


@pytest.mark.asyncio
async def test_get_draft_differential() -> None:
    canned = {"_meta_version": "v1", "nodes": []}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_draft("A1", "process", "F1")

    await assert_differential(
        family="flow",
        method_name="get_draft",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda d: d.to_wire(),
    )


@pytest.mark.asyncio
async def test_create_flow_differential() -> None:
    canned = {"_id": "F1", "Name": "New flow"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_flow("A1", "process", "New flow")

    await assert_differential(
        family="flow",
        method_name="create_flow",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_delete_flow_differential_without_archive_first() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).delete_flow(
            "A1", "process", "F1", archive_first=False
        )

    await assert_differential(
        family="flow",
        method_name="delete_flow",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda _: None,
    )


@pytest.mark.asyncio
async def test_delete_flow_archives_first_for_a_process() -> None:
    """archive_first=True (the default) on a process: archive, THEN delete."""
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).delete_flow("A1", "process", "F1")

    assert methods == [
        "POST /flow/2/ACC1/process/F1/archive",
        "DELETE /flow/2/ACC1/process/F1",
    ]


@pytest.mark.asyncio
async def test_delete_archived_process_retry_skips_second_archive() -> None:
    """A MockTransport exposes an already archived process to the retry."""
    methods: list[str] = []
    list_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal list_reads
        methods.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            list_reads += 1
            return httpx.Response(
                200,
                json=([{"_id": "F1", "Status": "Archived"}] if list_reads == 1 else []),
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"status": "success"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await delete_anything(
            _adapter(client),
            FakeAppRepository(),
            FakePageRepository(),
            kind="process",
            flow_id="F1",
            app_id="A1",
        )

    assert result.deleted is True and result.verified is True
    assert methods == [
        "GET /flow/2/ACC1/process",
        "DELETE /flow/2/ACC1/process/F1",
        "GET /flow/2/ACC1/process",
    ]


@pytest.mark.asyncio
async def test_publish_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).publish("A1", "process", "F1")

    await assert_differential(
        family="flow",
        method_name="publish",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda _: None,
    )


@pytest.mark.asyncio
async def test_get_flow_detail_differential() -> None:
    canned = {"_id": "F1", "Status": "Live"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_flow_detail("A1", "process", "F1")

    await assert_differential(
        family="flow",
        method_name="get_flow_detail",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_list_flows_differential() -> None:
    canned = [{"_id": "F1", "Name": "Flow one"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).list_flows("A1", "process")

    await assert_differential(
        family="flow",
        method_name="list_flows",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_get_members_differential() -> None:
    canned = [{"_id": "Ro1", "Role": "Member"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_members("A1", "process", "F1")

    await assert_differential(
        family="flow",
        method_name="get_members",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_delete_member_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).delete_member("A1", "process", "F1", "Ro1")

    await assert_differential(
        family="flow",
        method_name="delete_member",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_post_member_batch_differential() -> None:
    canned = {"status": "success"}
    members = [{"_id": "Ro1", "Name": "Reviewers", "Kind": "AppRole"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).post_member_batch("A1", "process", "F1", members)

    await assert_differential(
        family="flow",
        method_name="post_member_batch",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_post_report_member_batch_differential() -> None:
    canned = {"status": "success"}
    members = [{"_id": "Ro1", "Name": "Reviewers", "Kind": "AppRole"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).post_report_member_batch(
            "A1", "F1", "Rp1", members
        )

    await assert_differential(
        family="flow",
        method_name="post_report_member_batch",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_get_list_items_differential() -> None:
    canned = ["Red", "Blue"]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_list_items("A1", "L1")

    await assert_differential(
        family="flow",
        method_name="get_list_items",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_list_lists_differential() -> None:
    canned = [{"_id": "L1", "Name": "Colors"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).list_lists("A1")

    await assert_differential(
        family="flow",
        method_name="list_lists",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_create_list_differential() -> None:
    canned = {"_id": "L1", "Type": "List", "Status": "Live"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_list("A1", "Colors")

    await assert_differential(
        family="flow",
        method_name="create_list",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_set_list_items_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).set_list_items("L1", ["Red", "Blue"])

    await assert_differential(
        family="flow",
        method_name="set_list_items",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_create_dataset_differential() -> None:
    canned = {"_id": "D1", "Type": "Dataset", "Status": "Live"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_dataset("A1", "Orders")

    await assert_differential(
        family="flow",
        method_name="create_dataset",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_create_case_differential() -> None:
    canned = {"_id": "C1", "Type": "Case", "Status": "Live"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_case("A1", "Cases", "Case", "CS")

    await assert_differential(
        family="flow",
        method_name="create_case",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_put_draft_differential() -> None:
    canned = {"_meta_version": "v1", "nodes": []}
    new_draft = FlowDraft.from_wire(canned)

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).put_draft("A1", "process", "F1", new_draft, "v1")

    await assert_differential(
        family="flow",
        method_name="put_draft",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda d: d.to_wire(),
        expected_calls=2,
    )


# =====================================================================
# 3. Error translation per status
# =====================================================================


@pytest.mark.asyncio
async def test_error_translation() -> None:
    async def call(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_draft("A1", "process", "F1")

    await assert_error_translation(call=call, error_cls=RepositoryError)


# =====================================================================
# 4. The read-verify-write conflict test
# =====================================================================


@pytest.mark.asyncio
async def test_put_draft_raises_conflict_on_drift() -> None:
    async def put_call(client: httpx.AsyncClient, expect_version: str | None) -> Any:
        new_draft = FlowDraft.from_wire({"_meta_version": "v-live"})
        return await _adapter(client).put_draft(
            "A1", "process", "F1", new_draft, expect_version
        )

    await assert_conflict_on_drift(
        put_call=put_call, live_version="v-live", error_cls=RepositoryError
    )


# =====================================================================
# 5. Edge cases the differential harness does not exercise by default
# =====================================================================


@pytest.mark.asyncio
async def test_create_flow_raises_when_the_response_carries_no_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Name": "New flow"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError, match="no _id"):
            await _adapter(client).create_flow("A1", "process", "New flow")


# =====================================================================
# 6. Host binding (security-judge finding 2, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_refuses_requests_off_the_configured_tenant_host() -> None:
    def build_adapter(
        client: httpx.AsyncClient, base_url: str, settings_: Any
    ) -> KissflowFlowRepository:
        return KissflowFlowRepository(
            client=client, base_url=base_url, settings=settings_
        )

    async def call(adapter: KissflowFlowRepository) -> Any:
        return await adapter.get_draft("A1", "process", "F1")

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
async def test_a_path_traversal_flow_id_never_collapses_the_path() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).delete_member(
            "A1", "process", "../../../../admin", "Ro1"
        )

    assert len(calls) == 1
    assert calls[0].url.raw_path.startswith(f"/flow/2/{ACCOUNT}/process/".encode())


@pytest.mark.asyncio
async def test_a_query_injection_role_id_does_not_corrupt_the_real_query_param() -> (
    None
):
    """`delete_member`'s URL already carries `?_application_id=...` after the
    role id, so an unencoded `?` in the id would swallow that real parameter
    into the id's own bogus query text instead of just appending a new one."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).delete_member("A1", "process", "F1", "x?evil=1")

    assert len(calls) == 1
    assert calls[0].url.params["_application_id"] == "A1"
    assert "evil" not in calls[0].url.params


# =====================================================================
# 8. A dot-segment id is refused, not sent (security-judge finding 1,
#    round 2). Source: the `role_id` tool argument. Sink: the f-string-built
#    request URL -- httpx removes dot segments (RFC 3986 5.2.4) before it
#    sends, so a `role_id` of exactly ".." collapsed
#    `.../form/F1/member/..` onto `.../form/F1`, sending the delete-FLOW
#    request instead of a member deletion. Guard: `quote_path_segment`
#    refuses ".." before any request is built.
# =====================================================================


@pytest.mark.asyncio
async def test_delete_member_refuses_a_dot_segment_role_id_with_no_request_sent() -> (
    None
):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _adapter(client).delete_member("APP", "form", "F1", "..")

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"a request reached the wrong resource: {[c.url for c in calls]}"
    )


# =====================================================================
# 9. Query values are encoded (security-judge finding 2, round 2). Source:
#    the `app_id` tool argument. Sink: the `page_size` query parameter that
#    follows it in `list_flows`'s query string. Guard: `build_query` runs
#    `app_id` through `urlencode`, so an embedded `&page_size=1` cannot
#    override the real `page_size=100`, and a `#` cannot truncate the query.
# =====================================================================


@pytest.mark.asyncio
async def test_list_flows_query_injection_does_not_override_page_size() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).list_flows("A1&page_size=1#", "process")

    assert len(calls) == 1
    assert calls[0].url.params["page_size"] == "100"
    assert calls[0].url.params["_application_id"] == "A1&page_size=1#"
    assert calls[0].url.fragment == ""


# =====================================================================
# 10. `{kind}` is a guarded path segment, not a free string (round 3,
#    security-judge nit 2). Source: the `kind` tool argument on every flow
#    method that interpolates it into a `/flow` or `/metadata` route. Sink:
#    the f-string-built request URL -- `kind` was never run through
#    `quote_path_segment`/`_segment()` (it must reach the wire as a bare
#    word, e.g. `/flow/2/{account}/process`, not a percent-escaped one), so
#    nothing stopped a caller who bypasses the static `AnyFlowKind`/
#    `FlowKind` type from sending an arbitrary string. `delete_flow("APP",
#    "..", "F1", archive_first=False)` sent `DELETE /flow/2/{account}/F1`
#    (httpx drops the ".." dot-segment and the segment before it, RFC 3986
#    5.2.4), and `kind="application"` targeted the delete-APPLICATION route
#    at `/flow/2/{account}/application/F1` -- an entirely different
#    resource family, reached through a flow method. Guard: `flow.py`'s own
#    `_kind()`, checked against the exact `Literal` the port declares for
#    that call site (`AnyFlowKind` or `FlowKind`, read with
#    `typing.get_args`), raising before any request is built.
# =====================================================================


def _kind_call(
    method_name: str, kind: str
) -> Callable[[KissflowFlowRepository], Awaitable[Any]]:
    """Build one no-argument coroutine factory for `method_name`, `kind` plugged in.

    Every other argument is a fixed, valid value -- only `kind` varies, so a
    refusal or an acceptance can only be attributed to the kind guard.

    Args:
        method_name: The adapter method under test.
        kind: The `kind` value to call it with.

    Returns:
        A callable taking the adapter and returning the method's coroutine.
    """
    # `kind` is deliberately allowed to be any `str` here, including values no
    # real `AnyFlowKind`/`FlowKind` literal permits -- the whole point of
    # this table is calling each method with an out-of-band `kind`, the same
    # way a caller who bypasses the static type (an MCP argument before
    # Pydantic coercion, or this repository called directly) could.
    kind_arg = cast(Any, kind)
    draft = FlowDraft.from_wire({"_meta_version": "v1"})
    calls: dict[str, Callable[[KissflowFlowRepository], Awaitable[Any]]] = {
        "get_draft": lambda a: a.get_draft("A1", kind_arg, "F1"),
        "put_draft": lambda a: a.put_draft("A1", kind_arg, "F1", draft, "v1"),
        "create_flow": lambda a: a.create_flow("A1", kind_arg, "New flow"),
        "delete_flow": lambda a: a.delete_flow(
            "A1", kind_arg, "F1", archive_first=False
        ),
        "list_flows": lambda a: a.list_flows("A1", kind_arg),
        "publish": lambda a: a.publish("A1", kind_arg, "F1"),
        "get_flow_detail": lambda a: a.get_flow_detail("A1", kind_arg, "F1"),
        "get_members": lambda a: a.get_members("A1", kind_arg, "F1"),
        "delete_member": lambda a: a.delete_member("A1", kind_arg, "F1", "Ro1"),
        "post_member_batch": lambda a: a.post_member_batch(
            "A1", kind_arg, "F1", [{"_id": "Ro1"}]
        ),
    }
    return calls[method_name]


#: The eleven public methods that put `kind` into a path -- `get_draft` and
#: `put_draft` share `_draft_url`'s one guarded interpolation (`flow.py`
#: line 94 at `2ddcac1`); the rest each carry their own.
_ANY_FLOW_KIND_METHODS = (
    "get_draft",
    "put_draft",
    "create_flow",
    "delete_flow",
    "list_flows",
)
_FLOW_KIND_METHODS = (
    "publish",
    "get_flow_detail",
    "get_members",
    "delete_member",
    "post_member_batch",
)
_ALL_KIND_METHODS = _ANY_FLOW_KIND_METHODS + _FLOW_KIND_METHODS


def _kind_canned_handler(
    calls: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_id": "F1", "_meta_version": "v1"})

    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", _ALL_KIND_METHODS)
async def test_kind_dot_dot_is_refused_with_no_request_sent(method_name: str) -> None:
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_kind_canned_handler(calls))
    ) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _kind_call(method_name, "..")(_adapter(client))

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"{method_name}(kind='..') reached the wrong resource: {[c.url for c in calls]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", _ALL_KIND_METHODS)
async def test_kind_application_is_refused_with_no_request_sent(
    method_name: str,
) -> None:
    """`kind="application"` is a real Kissflow word -- just not a flow kind: it
    names the wholly different application/app-role route family. Nothing
    but the `_kind()` guard stops it from routing a flow call onto that
    other family's URL shape."""
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_kind_canned_handler(calls))
    ) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _kind_call(method_name, "application")(_adapter(client))

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"{method_name}(kind='application') reached the wrong resource: "
        f"{[c.url for c in calls]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name,kind",
    [(m, k) for m in _ANY_FLOW_KIND_METHODS for k in get_args(AnyFlowKind)]
    + [(m, k) for m in _FLOW_KIND_METHODS for k in get_args(FlowKind)],
)
async def test_every_real_kind_still_builds_a_request(
    method_name: str, kind: str
) -> None:
    """The guard never blocks a real kind: every value the call site's own
    port `Literal` declares still reaches the wire, in the same `/{kind}/`
    position the recorded differential fixtures under
    `tests/fixtures/recorded/flow/` captured for `kind="process"`."""
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_kind_canned_handler(calls))
    ) as client:
        await _kind_call(method_name, kind)(_adapter(client))

    assert calls, f"{method_name}(kind={kind!r}) sent no request"
    assert kind in calls[0].url.path.split("/"), (
        f"{method_name}(kind={kind!r}) built {calls[0].url.path!r}"
    )
