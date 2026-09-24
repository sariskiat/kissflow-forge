"""Spec for app.application.use_cases.app.forge_add_member_roles.

Ports `tests/test_client.py`'s `apply_member_roles` tests at the use-case level;
the create-then-grant algorithm's own cases live in `test__members.py`.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.app.forge_add_member_roles_request import (
    ForgeAddMemberRolesRequest,
)
from app.application.use_cases.app.forge_add_member_roles import ForgeAddMemberRoles


def _request(**overrides: object) -> ForgeAddMemberRolesRequest:
    values: dict[str, object] = {
        "target_flow_id": "F_target",
        "roles": {"RoForeign": "FDE"},
        "app_id": "App1",
    }
    values.update(overrides)
    return ForgeAddMemberRolesRequest.model_validate(values)


@pytest.mark.asyncio
async def test_reuses_an_existing_same_name_role_and_grants() -> None:
    app = FakeAppRepository()
    existing = [{"_id": "RoExist", "Name": "FDE", "_application_id": "App1"}]
    app.results["list_app_roles"] = [existing, existing]
    flow = FakeFlowRepository()

    response = await ForgeAddMemberRoles(flow, app).execute(_request())

    assert response.missing == []
    assert response.resolved == {"FDE": "RoExist"}, (
        "reuse the scoped role, not RoForeign"
    )
    assert response.role_ids == ["RoExist"]
    assert response.note is not None and "created" not in response.note
    posted = [c for c in flow.calls if c[0] == "post_member_batch"][0][1][3]
    assert posted == [
        {
            "_id": "RoExist",
            "Name": "FDE",
            "Kind": "AppRole",
            "Role": "DataAdmin",
            "Permission": ["InitiateItems"],
        }
    ]
    assert_write_order(flow)
    assert_write_order(app)


@pytest.mark.asyncio
async def test_creates_every_missing_role_scoped_to_the_app_then_grants() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [],
        [{"_id": "RoNew1", "Name": "Requester"}, {"_id": "RoNew2", "Name": "CoE Lead"}],
    ]
    app.results["create_app_role"] = ["RoNew1", "RoNew2"]
    flow = FakeFlowRepository()

    response = await ForgeAddMemberRoles(flow, app).execute(
        _request(roles={"RoX": "Requester", "RoY": "CoE Lead"})
    )

    assert response.resolved == {"Requester": "RoNew1", "CoE Lead": "RoNew2"}
    assert response.note is not None and "created 2" in response.note
    creates = [c for c in app.calls if c[0] == "create_app_role"]
    assert creates == [
        ("create_app_role", ("Requester",), {"app_id": "App1"}),
        ("create_app_role", ("CoE Lead",), {"app_id": "App1"}),
    ]
    assert len([c for c in flow.calls if c[0] == "post_member_batch"]) == 1
    assert_write_order(app)
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    app = FakeAppRepository()
    flow = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddMemberRoles(flow, app).execute(_request(app_id=""))

    assert exc_info.value.code == REFUSED
    assert app.calls == [] and flow.calls == []


@pytest.mark.asyncio
async def test_a_role_absent_from_the_read_back_is_verify_failed() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [[{"_id": "RoExist", "Name": "FDE"}], []]
    flow = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddMemberRoles(flow, app).execute(_request())

    assert exc_info.value.code == VERIFY_FAILED
    assert "forge_add_member_roles" in exc_info.value.message
    assert "RoExist" in exc_info.value.message
