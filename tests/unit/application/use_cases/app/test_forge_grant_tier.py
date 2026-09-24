"""Spec for app.application.use_cases.app.forge_grant_tier.

The tier map itself is ported in `test__roles.py`; this file proves the use case
wires it, refuses an invalid (kind, tier) pair before any call, maps rule 7 and
keeps the write order on the written flow port.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.app_roles import _reviewer_app, _TierFlow
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.app.forge_grant_tier_request import (
    ForgeGrantTierRequest,
)
from app.application.use_cases.app.forge_grant_tier import ForgeGrantTier


def _request(**overrides: Any) -> ForgeGrantTierRequest:
    values: dict[str, Any] = {
        "kind": "process",
        "flow_id": "F1",
        "role_id": "R1",
        "tier": "Manage",
        "app_id": "App1",
    }
    values.update(overrides)
    return ForgeGrantTierRequest.model_validate(values)


@pytest.mark.asyncio
async def test_grants_manage_and_answers_the_verified_tier() -> None:
    flow = _TierFlow()
    app = _reviewer_app()

    response = await ForgeGrantTier(flow, app).execute(_request())

    assert response.model_dump(mode="json") == {
        "flow_id": "F1",
        "kind": "process",
        "role_id": "R1",
        "tier": "Manage",
        "verified": True,
        "snapshot_version": None,
    }
    assert [c[0] for c in flow.calls] == [
        "get_members",
        "post_member_batch",
        "get_members",
    ]
    assert_write_order(flow)
    assert_write_order(app)


@pytest.mark.asyncio
async def test_no_access_removes_through_the_delete_route() -> None:
    flow = _TierFlow()
    flow.members = [{"_id": "R1", "Role": "DataAdmin"}]
    app = _reviewer_app()

    response = await ForgeGrantTier(flow, app).execute(_request(tier="No access"))

    assert response.verified is True
    assert [c[0] for c in flow.calls] == [
        "get_members",
        "delete_member",
        "get_members",
    ]
    assert app.calls == [], "a removal never needs the role's Name"
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_a_tier_invalid_for_the_kind_is_refused_before_any_call() -> None:
    flow = _TierFlow()
    app = _reviewer_app()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeGrantTier(flow, app).execute(_request(tier="Read-only"))

    assert exc_info.value.code == REFUSED
    assert exc_info.value.message == (
        "forge_grant_tier: unknown tier 'Read-only' for kind 'process' — "
        "valid: ['Initiate', 'Manage', 'No access']"
    )
    assert flow.calls == [] and app.calls == []


@pytest.mark.asyncio
async def test_an_unverified_grant_is_verify_failed() -> None:
    flow = _TierFlow()
    flow.drop_grants = True

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeGrantTier(flow, _reviewer_app()).execute(_request())

    assert exc_info.value.code == VERIFY_FAILED
    assert "did not verify on read-back" in exc_info.value.message


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    flow = _TierFlow()
    app = _reviewer_app()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeGrantTier(flow, app).execute(_request(app_id=""))

    assert exc_info.value.code == REFUSED
    assert flow.calls == [] and app.calls == []
