"""`use_cases.flow.forge_delete_flow.ForgeDeleteFlow`."""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.page import FakePageRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_delete_flow_request import (
    ForgeDeleteFlowRequest,
)
from app.application.use_cases.flow.forge_delete_flow import ForgeDeleteFlow


@pytest.mark.asyncio
async def test_deletes_a_process() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[], []]
    uc = ForgeDeleteFlow(flow, FakeAppRepository(), FakePageRepository())

    resp = await uc.execute(
        ForgeDeleteFlowRequest(
            kind="process", flow_id="F1", app_id="A1", app_id_given=True
        )
    )

    assert resp.deleted is True
    assert resp.verified is True
    assert resp.snapshot_version is None
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_deletes_an_application_with_no_app_selected() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[], []]
    uc = ForgeDeleteFlow(FakeFlowRepository(), app, FakePageRepository())

    resp = await uc.execute(
        ForgeDeleteFlowRequest(
            kind="application", flow_id="App1", app_id="", app_id_given=False
        )
    )

    assert resp.kind == "application"
    assert resp.verified is True


@pytest.mark.asyncio
async def test_a_page_delete_is_refused_when_app_id_was_not_explicitly_given() -> None:
    page = FakePageRepository()
    uc = ForgeDeleteFlow(FakeFlowRepository(), FakeAppRepository(), page)

    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgeDeleteFlowRequest(
                kind="page", flow_id="P1", app_id="KF_APP_DEFAULT", app_id_given=False
            )
        )
    assert exc.value.code == "VERIFY_FAILED"
    # ported from tests/test_client.py::test_delete_anything_page_requires_app_id
    assert exc.value.message == "app_id is required to delete a page"
    assert page.calls == []


@pytest.mark.asyncio
async def test_a_non_application_delete_with_no_app_selected_is_refused() -> None:
    uc = ForgeDeleteFlow(
        FakeFlowRepository(), FakeAppRepository(), FakePageRepository()
    )
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgeDeleteFlowRequest(
                kind="process", flow_id="F1", app_id="", app_id_given=False
            )
        )
    assert exc.value.code == "REFUSED"
