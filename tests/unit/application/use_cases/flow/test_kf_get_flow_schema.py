"""`use_cases.flow.kf_get_flow_schema.KfGetFlowSchema`."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.page import FakePageRepository

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.flow.kf_get_flow_schema_request import (
    KfGetFlowSchemaRequest,
)
from app.application.use_cases.flow.kf_get_flow_schema import KfGetFlowSchema
from app.domain.entities.flow_draft import FlowDraft
from app.domain.entities.page_draft import PageDraft


@pytest.mark.asyncio
async def test_reads_a_flow_draft_verbatim() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"Root": "M1", "M1": {}})]
    uc = KfGetFlowSchema(flow, FakePageRepository())

    resp = await uc.execute(
        KfGetFlowSchemaRequest(
            flow_kind="process", flow_id="F1", app_id="A1", app_id_given=True
        )
    )

    assert resp.root == {"Root": "M1", "M1": {}}
    assert flow.calls == [("get_draft", ("A1", "process", "F1"), {})]


@pytest.mark.asyncio
async def test_reads_a_page_draft_when_app_id_was_explicitly_given() -> None:
    page = FakePageRepository()
    page.results["get_page_draft"] = [PageDraft.from_wire({"Root": "P1"})]
    uc = KfGetFlowSchema(FakeFlowRepository(), page)

    resp = await uc.execute(
        KfGetFlowSchemaRequest(
            flow_kind="page", flow_id="Pg1", app_id="A1", app_id_given=True
        )
    )

    assert resp.root == {"Root": "P1"}
    assert page.calls == [("get_page_draft", ("A1", "Pg1"), {})]


@pytest.mark.asyncio
async def test_a_page_read_is_refused_when_app_id_was_not_explicitly_given() -> None:
    page = FakePageRepository()
    uc = KfGetFlowSchema(FakeFlowRepository(), page)

    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            KfGetFlowSchemaRequest(
                flow_kind="page",
                flow_id="Pg1",
                app_id="KF_APP_DEFAULT",
                app_id_given=False,
            )
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "app_id is required to read a page draft" in exc.value.message
    assert page.calls == []


@pytest.mark.asyncio
async def test_no_app_selected_is_refused() -> None:
    uc = KfGetFlowSchema(FakeFlowRepository(), FakePageRepository())

    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            KfGetFlowSchemaRequest(
                flow_kind="process", flow_id="F1", app_id="", app_id_given=False
            )
        )
    assert exc.value.code == "REFUSED"


def _raise(exc: Exception):
    async def _fn(*args: object, **kwargs: object) -> object:
        raise exc

    return _fn


# ---- ported from tests/test_p2_server.py ---------------------------------------------


@pytest.mark.asyncio
async def test_kf_get_flow_schema_page_kind_propagates_a_read_failure() -> None:
    page = FakePageRepository()
    page.get_page_draft = _raise(RepositoryError("GET page draft -> 404"))
    uc = KfGetFlowSchema(FakeFlowRepository(), page)

    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            KfGetFlowSchemaRequest(
                flow_kind="page", flow_id="Page1", app_id="App_Other", app_id_given=True
            )
        )

    assert "404" in exc.value.message


@pytest.mark.asyncio
async def test_kf_get_flow_schema_non_page_kind_routes_through_get_draft() -> None:
    """A non-page kind reads the generic flow draft for the resolved app -- the same
    app the former `_client(app_id)` scoped its client to."""
    wire = {"Root": "M1", "_meta_version": "v1", "M1": {"Kind": "Model"}}
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire(wire)]
    page = FakePageRepository()
    uc = KfGetFlowSchema(flow, page)

    resp = await uc.execute(
        KfGetFlowSchemaRequest(
            flow_kind="process", flow_id="F1", app_id="App_Other", app_id_given=True
        )
    )

    assert resp.root == wire
    assert flow.calls == [("get_draft", ("App_Other", "process", "F1"), {})]
    assert page.calls == []


@pytest.mark.asyncio
async def test_a_dataform_draft_is_readable() -> None:
    """Ported from tests/test_mcp_boundary.py: `dataset` reads through the same
    generic draft route."""
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"Root": "D1"})]
    uc = KfGetFlowSchema(flow, FakePageRepository())

    resp = await uc.execute(
        KfGetFlowSchemaRequest(
            flow_kind="dataset", flow_id="D1", app_id="A1", app_id_given=False
        )
    )

    assert resp.root == {"Root": "D1"}
    assert flow.calls == [("get_draft", ("A1", "dataset", "D1"), {})]
