"""Spec for app.application.use_cases.app.forge_member_batch.

The harvest and account-level algorithms themselves are ported in
`test__members.py`; this file proves the use case wires them: source discovery,
the fallback, app-id refusal, rule 7 and the write order.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.app.forge_member_batch_request import (
    ForgeMemberBatchRequest,
)
from app.application.use_cases.app.forge_member_batch import ForgeMemberBatch


def _request(**overrides: object) -> ForgeMemberBatchRequest:
    values: dict[str, object] = {"target_flow_id": "F_target", "app_id": "App1"}
    values.update(overrides)
    return ForgeMemberBatchRequest.model_validate(values)


@pytest.mark.asyncio
async def test_falls_back_to_account_level_app_roles_when_nothing_to_harvest() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[]]
    flow.results["get_members"] = [[{"_id": "RoA", "Role": "DataAdmin"}]]
    app = FakeAppRepository()
    app.results["list_app_roles"] = [[{"_id": "RoA", "Name": "Admin"}]]

    response = await ForgeMemberBatch(flow, app).execute(_request())

    assert response.source_flow_id is None
    assert response.role_ids == ["RoA"] and response.harvested == ["Admin"]
    assert response.verified == ["RoA"] and response.missing == []
    assert response.roles_seen == 1 and response.roles_granted == 1
    assert response.snapshot_version is None
    assert app.calls[0] == ("list_app_roles", (), {"app_id": "App1"})
    assert_write_order(flow)
    assert_write_order(app)


@pytest.mark.asyncio
async def test_an_explicit_source_skips_discovery_and_the_fallback() -> None:
    """An explicit source_flow_id, even one with zero members, must NOT fall through to
    the account-level grant -- the caller asked for THAT flow."""
    flow = FakeFlowRepository()
    flow.results["get_members"] = [[]]
    app = FakeAppRepository()

    response = await ForgeMemberBatch(flow, app).execute(
        _request(source_flow_id="F_explicit")
    )

    assert response.source_flow_id == "F_explicit"
    assert response.role_ids == [] and response.harvested == []
    assert response.note is not None and "no AppRole members" in response.note
    assert [c[0] for c in flow.calls] == ["get_members"]
    assert app.calls == []


@pytest.mark.asyncio
async def test_a_discovered_sibling_flow_is_harvested() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "F_target"}, {"_id": "F_source"}]]
    member = {"_id": "m1", "Name": "Desk", "Kind": "AppRole", "Role": "Ro_front"}
    flow.results["get_members"] = [[member], [member], [member]]
    app = FakeAppRepository()

    response = await ForgeMemberBatch(flow, app).execute(_request())

    assert response.source_flow_id == "F_source"
    assert response.harvested == ["Ro_front"] and response.role_ids == ["m1"]
    assert app.calls == []
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    flow = FakeFlowRepository()
    app = FakeAppRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeMemberBatch(flow, app).execute(_request(app_id=""))

    assert exc_info.value.code == REFUSED
    assert "no app selected" in exc_info.value.message
    assert flow.calls == [] and app.calls == []


@pytest.mark.asyncio
async def test_a_grant_missing_on_read_back_is_verify_failed() -> None:
    """Review rule 7: the old report's `isError: true` (a non-empty `missing`) is a
    raised failure, never a success response."""
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[]]
    flow.results["get_members"] = [[{"_id": "RoA", "Role": "DataAdmin"}]]
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [{"_id": "RoA", "Name": "Admin"}, {"_id": "RoB", "Name": "User"}]
    ]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeMemberBatch(flow, app).execute(_request())

    assert exc_info.value.code == VERIFY_FAILED
    assert "forge_member_batch" in exc_info.value.message
    assert "RoB" in exc_info.value.message
