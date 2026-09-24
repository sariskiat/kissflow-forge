"""`use_cases.flow.forge_create_list.ForgeCreateList`."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_create_list_request import (
    ForgeCreateListRequest,
)
from app.application.use_cases.flow.forge_create_list import ForgeCreateList


@pytest.mark.asyncio
async def test_creates_a_list_and_verifies_items() -> None:
    flow = FakeFlowRepository()
    flow.results["list_lists"] = [[]]
    flow.results["create_list"] = [{"_id": "L1"}]
    flow.results["get_list_items"] = [["Low", "High"]]
    uc = ForgeCreateList(flow)

    resp = await uc.execute(
        ForgeCreateListRequest(name="Priorities", values=["Low", "High"], app_id="A1")
    )

    assert resp.list_id == "L1"
    assert resp.created is True
    assert resp.verified_items == ["Low", "High"]
    assert resp.snapshot_version is None
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_no_app_selected_is_refused() -> None:
    uc = ForgeCreateList(FakeFlowRepository())
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(ForgeCreateListRequest(name="X", values=[], app_id=""))
    assert exc.value.code == "REFUSED"
