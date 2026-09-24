"""`use_cases.flow.kf_publish.KfPublish`."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.kf_publish_request import KfPublishRequest
from app.application.use_cases.flow.kf_publish import KfPublish
from app.domain.entities.flow_draft import FlowDraft


@pytest.mark.asyncio
async def test_publishes_and_carries_the_snapshot_version() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"_meta_version": "v1"})]
    uc = KfPublish(flow)

    resp = await uc.execute(
        KfPublishRequest(flow_kind="process", flow_id="F1", app_id="A1")
    )

    assert resp.published is True
    assert resp.flow_id == "F1"
    assert resp.snapshot_version == "v1"
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_no_app_selected_is_refused() -> None:
    uc = KfPublish(FakeFlowRepository())
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(KfPublishRequest(flow_kind="process", flow_id="F1", app_id=""))
    assert exc.value.code == "REFUSED"
