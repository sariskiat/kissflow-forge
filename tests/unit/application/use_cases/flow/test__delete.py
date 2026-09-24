"""`use_cases.flow._delete.delete_anything`: ported from the former
`client.delete_anything`."""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.page import FakePageRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.use_cases.flow._delete import delete_anything
from app.domain.value_objects.kinds import AnyFlowKind


@pytest.mark.asyncio
async def test_delete_a_process_verifies_via_list_flows() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[], []]  # before: absent; after: still absent

    result = await delete_anything(
        flow,
        FakeAppRepository(),
        FakePageRepository(),
        kind="process",
        flow_id="F1",
        app_id="A1",
    )

    assert result.deleted is True
    assert result.verified is True
    assert [c[0] for c in flow.calls] == ["list_flows", "delete_flow", "list_flows"]
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_delete_a_process_raises_when_the_read_back_still_lists_it() -> None:
    """Lesson 7: a delete whose read-back cannot confirm removal is a failure, never
    a success with `verified: False`."""
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[], [{"_id": "F1"}]]

    with pytest.raises(ApplicationError) as exc:
        await delete_anything(
            flow,
            FakeAppRepository(),
            FakePageRepository(),
            kind="process",
            flow_id="F1",
            app_id="A1",
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "F1" in exc.value.message
    assert "write did not fully land" in exc.value.message
    assert "published=False" in exc.value.message
    assert "--" not in exc.value.message, "product text uses an em dash, never '--'"


@pytest.mark.asyncio
async def test_delete_raises_through_raise_if_write_failed_on_a_list_read_failure() -> (
    None
):
    """`brief_stage_d_common.md` review fix 7: the verifying list read's own
    failure must use `_fields.raise_if_write_failed`'s shared format, not a
    hand-written `"... did not fully land -- ..."` sentence."""
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[]]
    flow.list_flows = _flaky_list_flows(flow)

    with pytest.raises(ApplicationError) as exc:
        await delete_anything(
            flow,
            FakeAppRepository(),
            FakePageRepository(),
            kind="process",
            flow_id="F1",
            app_id="A1",
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "write did not fully land" in exc.value.message
    assert "published=False" in exc.value.message
    assert "--" not in exc.value.message, "product text uses an em dash, never '--'"


def _flaky_list_flows(flow: FakeFlowRepository):
    calls = {"n": 0}
    real = flow.list_flows

    async def _fn(app_id: str, kind: AnyFlowKind) -> list[dict[str, object]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return await real(app_id, kind)
        raise RepositoryError("GET list -> 503")

    return _fn


@pytest.mark.asyncio
async def test_delete_a_page_uses_the_page_port() -> None:
    page = FakePageRepository()
    page.results["list_pages"] = [[], []]

    result = await delete_anything(
        FakeFlowRepository(),
        FakeAppRepository(),
        page,
        kind="page",
        flow_id="P1",
        app_id="A1",
    )

    assert result.kind == "page"
    assert result.verified is True
    assert [c[0] for c in page.calls] == ["list_pages", "delete_page", "list_pages"]
    assert_write_order(page)


@pytest.mark.asyncio
async def test_delete_an_application_uses_the_app_port_and_ignores_app_id() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[], []]

    result = await delete_anything(
        FakeFlowRepository(),
        app,
        FakePageRepository(),
        kind="application",
        flow_id="App1",
        app_id="",
    )

    assert result.kind == "application"
    assert result.id == "App1"
    assert result.verified is True
    assert [c[0] for c in app.calls] == [
        "list_applications",
        "delete_application",
        "list_applications",
    ]
    assert_write_order(app)


@pytest.mark.asyncio
async def test_delete_a_list_and_a_dataset_go_through_the_generic_flow_route() -> None:
    for kind in ("list", "dataset"):
        flow = FakeFlowRepository()
        flow.results["list_flows"] = [[], []]

        result = await delete_anything(
            flow,
            FakeAppRepository(),
            FakePageRepository(),
            kind=kind,  # type: ignore[arg-type]
            flow_id="X1",
            app_id="A1",
        )
        assert result.kind == kind
        assert result.verified is True
        # ported from tests/test_mcp_boundary.py: the generic flow route, with the
        # same archive_first value the former client passed.
        assert flow.calls[1] == (
            "delete_flow",
            ("A1", kind, "X1"),
            {"archive_first": True},
        )


# ---- ported from tests/test_client.py ------------------------------------------------


@pytest.mark.asyncio
async def test_delete_anything_page_verifies_via_list_route() -> None:
    page = FakePageRepository()
    page.results["list_pages"] = [[{"_id": "Page_1", "Name": "X"}], []]

    result = await delete_anything(
        FakeFlowRepository(),
        FakeAppRepository(),
        page,
        kind="page",
        flow_id="Page_1",
        app_id="App_1",
    )

    assert result.deleted is True and result.verified is True
    assert page.calls[1] == ("delete_page", ("App_1", "Page_1"), {})
    assert page.calls[2] == ("list_pages", ("App_1",), {})


@pytest.mark.asyncio
async def test_delete_anything_application_archives_first_then_verifies() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[{"_id": "App_T", "Name": "Throwaway"}], []]

    result = await delete_anything(
        FakeFlowRepository(),
        app,
        FakePageRepository(),
        kind="application",
        flow_id="App_T",
        app_id="",
    )

    assert result.deleted is True and result.verified is True
    assert app.calls[1] == (
        "delete_application",
        ("App_T",),
        {"archive_first": True},
    )


@pytest.mark.asyncio
async def test_delete_anything_process_archives_and_deletes() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "F1"}], []]

    result = await delete_anything(
        flow,
        FakeAppRepository(),
        FakePageRepository(),
        kind="process",
        flow_id="F1",
        app_id="A1",
    )

    assert result.deleted is True and result.verified is True
    assert flow.calls[1] == (
        "delete_flow",
        ("A1", "process", "F1"),
        {"archive_first": True},
    )
    assert flow.calls[2] == ("list_flows", ("A1", "process"), {})


@pytest.mark.asyncio
async def test_delete_anything_archived_process_skips_archive_on_retry() -> None:
    """A retry after archive succeeded must go straight to DELETE."""
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "F1", "Status": "Archived"}], []]

    result = await delete_anything(
        flow,
        FakeAppRepository(),
        FakePageRepository(),
        kind="process",
        flow_id="F1",
        app_id="A1",
    )

    assert result.deleted is True and result.verified is True
    assert flow.calls[1] == (
        "delete_flow",
        ("A1", "process", "F1"),
        {"archive_first": False},
    )


@pytest.mark.asyncio
async def test_delete_unexpected_process_status_keeps_archive_enabled() -> None:
    """Only the exact Archived status may suppress the archive request."""
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "F1", "Status": "Unexpected"}], []]

    await delete_anything(
        flow,
        FakeAppRepository(),
        FakePageRepository(),
        kind="process",
        flow_id="F1",
        app_id="A1",
    )

    assert flow.calls[1][2] == {"archive_first": True}


# ---- a verifying list read that fails after the delete landed ------------------------


def _second_call_raises(first: list[dict[str, str]], exc: Exception):
    """A list read that answers `first` once, then raises `exc`: the pre-delete read
    works, the verifying read after the delete fails."""
    seen = 0

    async def _fn(*args: object, **kwargs: object) -> list[dict[str, str]]:
        nonlocal seen
        seen += 1
        if seen >= 2:
            raise exc
        return first

    return _fn


@pytest.mark.asyncio
async def test_a_failed_page_read_back_says_the_delete_itself_landed() -> None:
    """The former dict said `deleted: True, verified: False` with the list error. A
    raise carries no dict, so the message says the delete call succeeded."""
    page = FakePageRepository()
    page.list_pages = _second_call_raises(
        [{"_id": "Page_1"}], RepositoryError("GET pages -> 503")
    )

    with pytest.raises(ApplicationError) as exc:
        await delete_anything(
            FakeFlowRepository(),
            FakeAppRepository(),
            page,
            kind="page",
            flow_id="Page_1",
            app_id="App_1",
        )

    assert exc.value.code == "VERIFY_FAILED"
    assert "the delete call succeeded" in exc.value.message
    assert "GET pages -> 503" in exc.value.message
    assert page.calls == [("delete_page", ("App_1", "Page_1"), {})]


@pytest.mark.asyncio
async def test_a_failed_application_read_back_says_the_delete_itself_landed() -> None:
    app = FakeAppRepository()
    app.list_applications = _second_call_raises(
        [{"_id": "App_T"}], RepositoryError("GET applications -> 503")
    )

    with pytest.raises(ApplicationError) as exc:
        await delete_anything(
            FakeFlowRepository(),
            app,
            FakePageRepository(),
            kind="application",
            flow_id="App_T",
            app_id="",
        )

    assert exc.value.code == "VERIFY_FAILED"
    assert "the delete call succeeded" in exc.value.message
    assert "GET applications -> 503" in exc.value.message


@pytest.mark.asyncio
async def test_a_failed_flow_read_back_is_not_reported_as_verified() -> None:
    """The former client left `verified` True when this re-list failed. That claims
    a check that never ran, so the port reports it as a failed verify instead."""
    flow = FakeFlowRepository()
    flow.list_flows = _second_call_raises(
        [{"_id": "F1"}], RepositoryError("GET flows -> 503")
    )

    with pytest.raises(ApplicationError) as exc:
        await delete_anything(
            flow,
            FakeAppRepository(),
            FakePageRepository(),
            kind="process",
            flow_id="F1",
            app_id="A1",
        )

    assert exc.value.code == "VERIFY_FAILED"
    assert "the delete call succeeded" in exc.value.message
    assert "GET flows -> 503" in exc.value.message
