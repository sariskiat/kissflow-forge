"""Spec for app.application.use_cases.app.forge_create_app_role.

Ports `server.py`'s `forge_create_app_role` body: create scoped to the resolved app,
answer `{role_id, name, app_id}`. No old orchestration test existed for it; the happy
path and the failure codes are new (common brief, item 5).
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, ApplicationError, RepositoryError
from app.application.models.requests.app.forge_create_app_role_request import (
    ForgeCreateAppRoleRequest,
)
from app.application.use_cases.app.forge_create_app_role import ForgeCreateAppRole


@pytest.mark.asyncio
async def test_creates_the_role_scoped_to_the_resolved_app() -> None:
    app = FakeAppRepository()
    app.results["create_app_role"] = ["RoNew1"]

    response = await ForgeCreateAppRole(app).execute(
        ForgeCreateAppRoleRequest(name="Reviewer", app_id="App1")
    )

    assert response.model_dump(mode="json") == {
        "role_id": "RoNew1",
        "name": "Reviewer",
        "app_id": "App1",
        "snapshot_version": None,
    }
    # never `app_id=None`: the adapter scopes a None to "" (unscoped), which
    # member/batch would then reject with 00051
    assert app.calls[1] == ("create_app_role", ("Reviewer",), {"app_id": "App1"})
    assert_write_order(app)


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    app = FakeAppRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeCreateAppRole(app).execute(
            ForgeCreateAppRoleRequest(name="Reviewer", app_id="")
        )

    assert exc_info.value.code == REFUSED
    assert app.calls == []


@pytest.mark.asyncio
async def test_a_create_failure_propagates_as_the_ports_own_error() -> None:
    class _Failing(FakeAppRepository):
        async def create_app_role(self, name: str, app_id: str | None = None) -> str:
            raise RepositoryError("create_app_role('Reviewer') returned no _id")

    use_case = ForgeCreateAppRole(_Failing())
    request = ForgeCreateAppRoleRequest(name="Reviewer", app_id="App1")

    with pytest.raises(RepositoryError, match="returned no _id"):
        await use_case.execute(request)
