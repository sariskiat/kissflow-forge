"""`use_cases.flow.forge_doctor.ForgeDoctor`."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_doctor_request import (
    ForgeDoctorRequest,
)
from app.application.use_cases.flow.forge_doctor import ForgeDoctor
from app.domain.entities.flow_draft import FlowDraft


@pytest.mark.asyncio
async def test_a_clean_draft_is_ok() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"Root": "M1", "M1": {}})]
    uc = ForgeDoctor(flow)

    resp = await uc.execute(
        ForgeDoctorRequest(
            flow_id="F1", kind="process", visibility_role_claims=None, app_id="A1"
        )
    )

    assert resp.ok is True
    assert resp.flow_id == "F1"
    assert resp.problems == []


@pytest.mark.asyncio
async def test_visibility_role_claims_always_fail() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"Root": "M1", "M1": {}})]
    uc = ForgeDoctor(flow)

    resp = await uc.execute(
        ForgeDoctorRequest(
            flow_id="F1",
            kind="process",
            visibility_role_claims=["Manager sees X"],
            app_id="A1",
        )
    )

    assert resp.ok is False


@pytest.mark.asyncio
async def test_no_app_selected_is_refused() -> None:
    uc = ForgeDoctor(FakeFlowRepository())
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgeDoctorRequest(
                flow_id="F1", kind="process", visibility_role_claims=None, app_id=""
            )
        )
    assert exc.value.code == "REFUSED"
