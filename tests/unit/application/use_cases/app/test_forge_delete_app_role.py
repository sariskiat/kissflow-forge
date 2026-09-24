"""Spec for app.application.use_cases.app.forge_delete_app_role.

Ports `tests/test_mcp_surface.py`'s
`test_forge_list_app_roles_is_the_read_back_forge_delete_app_role_names` at the
use-case level: the delete answers `deleted: True`, and the deletion is only a fact
once the list route stops carrying the role.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.app import FakeAppRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, ApplicationError, RepositoryError
from app.application.models.requests.app.forge_delete_app_role_request import (
    ForgeDeleteAppRoleRequest,
)
from app.application.models.requests.app.forge_list_app_roles_request import (
    ForgeListAppRolesRequest,
)
from app.application.use_cases.app.forge_delete_app_role import ForgeDeleteAppRole
from app.application.use_cases.app.forge_list_app_roles import ForgeListAppRoles


class _Roster(FakeAppRepository):
    """An account whose AppRole list really loses a deleted role."""

    def __init__(self, roles: list[dict[str, Any]]) -> None:
        super().__init__()
        self.roles = roles

    async def list_app_roles(self, app_id: str | None = None) -> list[dict[str, Any]]:
        self._record("list_app_roles", (), {"app_id": app_id})
        return [r for r in self.roles if r.get("_application_id") == app_id]

    async def get_app_role(self, role_id: str) -> dict[str, Any]:
        self._record("get_app_role", (role_id,), {})
        return next((r for r in self.roles if r["_id"] == role_id), {})

    async def delete_app_role(self, role_id: str) -> Any:
        self._record("delete_app_role", (role_id,), {})
        self.roles = [r for r in self.roles if r["_id"] != role_id]
        return {"status": "success"}


@pytest.mark.asyncio
async def test_deletes_and_the_list_route_confirms_it() -> None:
    app = _Roster([{"_id": "Ro1", "Name": "Throwaway", "_application_id": "App1"}])

    response = await ForgeDeleteAppRole(app).execute(
        ForgeDeleteAppRoleRequest(role_id="Ro1", app_id="App1")
    )

    assert response.model_dump(mode="json") == {
        "role_id": "Ro1",
        "deleted": True,
        "snapshot_version": None,
    }
    assert [c[0] for c in app.calls] == ["get_app_role", "delete_app_role"]
    assert_write_order(app)

    after = await ForgeListAppRoles(app).execute(
        ForgeListAppRolesRequest(app_id="App1")
    )
    assert after.roles == [] and after.count == 0


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    app = FakeAppRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteAppRole(app).execute(
            ForgeDeleteAppRoleRequest(role_id="Ro1", app_id="")
        )

    assert exc_info.value.code == REFUSED
    assert app.calls == []


@pytest.mark.asyncio
async def test_a_role_that_is_not_there_fails_on_the_snapshot_read() -> None:
    class _Gone(FakeAppRepository):
        async def get_app_role(self, role_id: str) -> dict[str, Any]:
            self._record("get_app_role", (role_id,), {})
            raise RepositoryError("RoleDoesNotExistsError")

    app = _Gone()
    use_case = ForgeDeleteAppRole(app)
    request = ForgeDeleteAppRoleRequest(role_id="Ro1", app_id="App1")

    with pytest.raises(RepositoryError, match="RoleDoesNotExistsError"):
        await use_case.execute(request)

    assert [c[0] for c in app.calls] == ["get_app_role"], "never deletes blind"
