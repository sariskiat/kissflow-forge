"""Spec for app.application.use_cases.app.forge_list_app_roles.

Ports `server.py`'s `forge_list_app_roles` body: the scope is the resolved app, and
every record narrows to `{_id, Name}`. Read-only: no write-order check applies.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository

from app.application.exceptions import REFUSED, ApplicationError
from app.application.models.requests.app.forge_list_app_roles_request import (
    ForgeListAppRolesRequest,
)
from app.application.use_cases.app.forge_list_app_roles import ForgeListAppRoles


@pytest.mark.asyncio
async def test_lists_the_roles_scoped_to_the_app_as_id_and_name() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [
            {"_id": "Ro1", "Name": "Requester", "UserCount": 3, "Preference": {}},
            {"_id": "Ro2", "Name": "Approver", "_application_id": "App_here"},
        ]
    ]

    response = await ForgeListAppRoles(app).execute(
        ForgeListAppRolesRequest(app_id="App_here")
    )

    assert response.roles == [
        {"_id": "Ro1", "Name": "Requester"},
        {"_id": "Ro2", "Name": "Approver"},
    ]
    assert response.count == 2 and response.app_id == "App_here"
    assert app.calls == [("list_app_roles", (), {"app_id": "App_here"})]


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    app = FakeAppRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeListAppRoles(app).execute(ForgeListAppRolesRequest(app_id=""))

    assert exc_info.value.code == REFUSED
    assert app.calls == []
