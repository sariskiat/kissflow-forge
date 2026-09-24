"""`KissflowAppRepository`: the invariant transport, a differential test per port
method, error translation per status, the read-verify-write conflict test, all against
`KfClient`'s 13 app/app-role routes."""

from __future__ import annotations

import json
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
from app.domain.entities.navigation import Navigation
from app.infrastructure.kissflow.app import KissflowAppRepository


def _adapter(client: httpx.AsyncClient) -> KissflowAppRepository:
    return KissflowAppRepository(client=client, base_url=BASE_URL, settings=settings())


# =====================================================================
# 1. The invariant transport
# =====================================================================


@pytest.mark.asyncio
async def test_every_request_carries_the_invariant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_invariant(request.url.host, request.url.scheme, request.headers)
        return httpx.Response(200, json={"_id": "Ro1", "_meta_version": "v1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.list_app_roles("A1")
        await adapter.get_app_role("Ro1")
        await adapter.put_app_role("A1", "Ro1", {"Users": []})
        await adapter.get_assignee("jane")
        await adapter.create_app_role("Reviewers", "A1")
        await adapter.delete_app_role("Ro1")
        await adapter.list_applications()
        await adapter.create_application("New app")
        await adapter.delete_application("A1", archive_first=False)
        await adapter.get_app_draft("A1")
        await adapter.put_app_draft(
            "A1", Navigation.from_wire({"_meta_version": "v1"}), "v1"
        )
        await adapter.publish_app("A1")


# =====================================================================
# 2. A differential test per port method
# =====================================================================


@pytest.mark.asyncio
async def test_list_app_roles_differential() -> None:
    canned = [{"_id": "Ro1", "Name": "Reviewers"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).list_app_roles()

    await assert_differential(
        family="app",
        method_name="list_app_roles",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_get_app_role_differential() -> None:
    canned = {"_id": "Ro1", "Name": "Reviewers"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_app_role("Ro1")

    await assert_differential(
        family="app",
        method_name="get_app_role",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_put_app_role_differential() -> None:
    canned = {"_id": "Ro1", "Users": [{"_id": "U1"}]}
    body = {"Users": [{"_id": "U1"}]}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).put_app_role("A1", "Ro1", body)

    await assert_differential(
        family="app",
        method_name="put_app_role",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_get_assignee_differential() -> None:
    canned = [{"_id": "U1", "Kind": "User", "Name": "Jane Doe"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_assignee("Jane Doe")

    await assert_differential(
        family="app",
        method_name="get_assignee",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_create_app_role_differential() -> None:
    canned = {"_id": "Ro1", "Name": "Reviewers"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_app_role("Reviewers", "A1")

    await assert_differential(
        family="app",
        method_name="create_app_role",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_create_app_role_with_no_app_id_sends_an_empty_scope() -> None:
    """No explicit app_id and no ambient config app_id left to fall back to (the new
    adapter has none): matches the old default's own empty-string scope."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"_id": "Ro1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).create_app_role("Reviewers")

    assert calls == [{"Name": "Reviewers", "_application_id": ""}]


@pytest.mark.asyncio
async def test_delete_app_role_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).delete_app_role("Ro1")

    await assert_differential(
        family="app",
        method_name="delete_app_role",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_list_applications_differential() -> None:
    canned = [{"_id": "A1", "Name": "My App"}]

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).list_applications()

    await assert_differential(
        family="app",
        method_name="list_applications",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_create_application_differential() -> None:
    canned = {"_id": "A1", "Name": "New app"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).create_application("New app")

    await assert_differential(
        family="app",
        method_name="create_application",
        canned_json=canned,
        call_new=call_new,
    )


@pytest.mark.asyncio
async def test_delete_application_differential_without_archive_first() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).delete_application("A1", archive_first=False)

    await assert_differential(
        family="app",
        method_name="delete_application",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda _: None,
    )


@pytest.mark.asyncio
async def test_delete_application_archives_first_by_default() -> None:
    """archive_first=True (the default): archive, THEN delete, in that order."""
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).delete_application("A1")

    assert methods == [
        "POST /flow/2/ACC1/application/A1/archive",
        "DELETE /flow/2/ACC1/application/A1",
    ]


@pytest.mark.asyncio
async def test_get_app_draft_differential() -> None:
    canned = {"_meta_version": "v1", "nodes": []}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).get_app_draft("A1")

    await assert_differential(
        family="app",
        method_name="get_app_draft",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda d: d.to_wire(),
    )


@pytest.mark.asyncio
async def test_put_app_draft_differential() -> None:
    canned = {"_meta_version": "v1", "nodes": []}
    new_draft = Navigation.from_wire(canned)

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).put_app_draft("A1", new_draft, "v1")

    await assert_differential(
        family="app",
        method_name="put_app_draft",
        canned_json=canned,
        call_new=call_new,
        normalize_new_result=lambda d: d.to_wire(),
        expected_calls=2,
    )


@pytest.mark.asyncio
async def test_publish_app_differential() -> None:
    canned = {"status": "success"}

    async def call_new(client: httpx.AsyncClient) -> Any:
        return await _adapter(client).publish_app("A1")

    await assert_differential(
        family="app",
        method_name="publish_app",
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
        return await _adapter(client).get_app_role("Ro1")

    await assert_error_translation(call=call, error_cls=RepositoryError)


# =====================================================================
# 4. The read-verify-write conflict test
# =====================================================================


@pytest.mark.asyncio
async def test_put_app_draft_raises_conflict_on_drift() -> None:
    async def put_call(client: httpx.AsyncClient, expect_version: str | None) -> Any:
        new_draft = Navigation.from_wire({"_meta_version": "v-live"})
        return await _adapter(client).put_app_draft("A1", new_draft, expect_version)

    await assert_conflict_on_drift(
        put_call=put_call, live_version="v-live", error_cls=RepositoryError
    )


# =====================================================================
# 5. Edge cases the differential harness does not exercise by default
# =====================================================================


@pytest.mark.asyncio
async def test_list_app_roles_pages_past_a_full_first_page() -> None:
    """A first page of exactly 100 items means there is a second page to fetch."""
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page_number"])
        pages.append(page)
        if page == 1:
            items = [{"_id": f"Ro{i}"} for i in range(100)]
        else:
            items = [{"_id": "Ro100"}]
        return httpx.Response(200, json=items)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await _adapter(client).list_app_roles()

    assert pages == [1, 2]
    assert len(out) == 101


@pytest.mark.asyncio
async def test_create_app_role_raises_when_the_response_carries_no_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Name": "Reviewers"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError, match="no _id"):
            await _adapter(client).create_app_role("Reviewers", "A1")


@pytest.mark.asyncio
async def test_create_application_raises_when_the_response_carries_no_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Name": "New app"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError, match="no _id"):
            await _adapter(client).create_application("New app")


# =====================================================================
# 6. Host binding (security-judge finding 2, Stage C hardening)
# =====================================================================


@pytest.mark.asyncio
async def test_refuses_requests_off_the_configured_tenant_host() -> None:
    def build_adapter(
        client: httpx.AsyncClient, base_url: str, settings_: Any
    ) -> KissflowAppRepository:
        return KissflowAppRepository(
            client=client, base_url=base_url, settings=settings_
        )

    async def call(adapter: KissflowAppRepository) -> Any:
        return await adapter.get_app_role("Ro1")

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
async def test_a_path_traversal_role_id_never_collapses_the_path() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_id": "x"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).get_app_role("../../../../admin")

    assert len(calls) == 1
    assert calls[0].url.raw_path.startswith(f"/app_role/2/{ACCOUNT}/".encode())


@pytest.mark.asyncio
async def test_a_query_injection_role_id_does_not_corrupt_the_real_query_param() -> (
    None
):
    """`put_app_role`'s URL already carries `?_application_id=...` after the role
    id, so an unencoded `?` in the id would swallow that real parameter into the
    id's own bogus query text instead of just appending a new one."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_id": "x"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).put_app_role("A1", "x?evil=1", {"Users": []})

    assert len(calls) == 1
    assert calls[0].url.params["_application_id"] == "A1"
    assert "evil" not in calls[0].url.params


# =====================================================================
# 8. An empty path segment is refused, not sent (security-judge finding 1,
#    round 2). Source: the `role_id` tool argument. Sink: the f-string-built
#    request URL -- `delete_app_role("")` left a bare trailing `/` where the
#    id belonged, sending `DELETE /app_role/2/<account>/` instead of naming
#    one role. Guard: `quote_path_segment` refuses `""` before any request
#    is built.
# =====================================================================


@pytest.mark.asyncio
async def test_delete_app_role_refuses_an_empty_id_with_no_request_sent() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RepositoryError) as excinfo:
            await _adapter(client).delete_app_role("")

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"a request reached the wrong resource: {[c.url for c in calls]}"
    )


# =====================================================================
# 9. Query values are encoded (security-judge finding 2, round 2). Source:
#    the `app_id` tool argument. Sink: `put_app_role`'s `_application_id`
#    query value. Guard: `build_query` runs `app_id` through `urlencode`,
#    so `&`/`#` inside it can neither inject a new query parameter nor get
#    truncated at a fragment boundary.
# =====================================================================


@pytest.mark.asyncio
async def test_put_app_role_query_injection_does_not_add_a_bogus_parameter() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"_id": "Ro1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).put_app_role("A1&Users=HIJACKED#", "Ro1", {"Users": []})

    assert len(calls) == 1
    assert calls[0].url.params["_application_id"] == "A1&Users=HIJACKED#"
    assert "Users" not in calls[0].url.params
    assert calls[0].url.fragment == ""


@pytest.mark.asyncio
async def test_list_app_roles_filters_server_side_when_scoped_to_an_app() -> None:
    """With an app id the tenant filters (`_application_id`): one request, and a
    role the server returns for another app is still dropped client-side."""
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(
            200,
            json=[
                {"_id": "Ro1", "_application_id": "A1"},
                {"_id": "Ro2", "Applications": [{"_id": "A1"}]},
                {"_id": "Ro3", "_application_id": "OTHER"},
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await _adapter(client).list_app_roles("A1")

    assert [p["_application_id"] for p in seen] == ["A1"]
    assert [r["_id"] for r in out] == ["Ro1", "Ro2"]


@pytest.mark.asyncio
async def test_list_app_roles_sends_no_app_filter_when_unscoped() -> None:
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json=[{"_id": "Ro1"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _adapter(client).list_app_roles()

    assert ["_application_id" in p for p in seen] == [False]
