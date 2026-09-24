"""Spec for app.application.use_cases.app.forge_set_role_preference.

The preference write itself is ported in `test__roles.py`; this file proves the
use case wires it, refuses an empty call, maps rule 7 and keeps the write order.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.app_roles import _RoleApp
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.app.forge_set_role_preference_request import (
    ForgeSetRolePreferenceRequest,
)
from app.application.use_cases.app.forge_set_role_preference import (
    ForgeSetRolePreference,
)


def _request(**overrides: Any) -> ForgeSetRolePreferenceRequest:
    values: dict[str, Any] = {"role_id": "R1", "app_id": "App1"}
    values.update(overrides)
    return ForgeSetRolePreferenceRequest.model_validate(values)


@pytest.mark.asyncio
async def test_writes_both_keys_and_keeps_existing_members() -> None:
    app = _RoleApp(members=[{"_id": "U0", "Kind": "User", "Name": "Old"}])

    response = await ForgeSetRolePreference(app).execute(
        _request(default_page="Page_123", default_navigation="Navigation001")
    )

    assert response.model_dump(mode="json") == {
        "role_id": "R1",
        "default_page": "Page_123",
        "default_navigation": "Navigation001",
        "verified": True,
        "snapshot_version": None,
    }
    assert app.body is not None
    assert app.body["Users"] == [{"_id": "U0", "Kind": "User", "Name": "Old"}]
    assert app.calls[1][1][0] == "App1", "the write is scoped to the resolved app"
    assert_write_order(app)


@pytest.mark.asyncio
async def test_neither_key_is_refused_before_any_call() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRolePreference(app).execute(_request())

    assert exc_info.value.code == REFUSED
    # `apply_set_role_preference` was a public function in `client.py`
    # (`:5863`), so lesson 5 (name the public caller) does not apply: the
    # OLD public name is the one this message keeps (review fix 5).
    assert exc_info.value.message == (
        "apply_set_role_preference: give default_page or default_navigation"
    )
    assert app.calls == []


@pytest.mark.asyncio
async def test_an_unverified_write_is_verify_failed() -> None:
    app = _RoleApp()
    app.readback = {"_id": "R1", "Name": "Tech", "Members": [], "Preference": {}}

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRolePreference(app).execute(_request(default_page="Default"))

    assert exc_info.value.code == VERIFY_FAILED
    assert "default_page='Default'" in exc_info.value.message


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRolePreference(app).execute(
            _request(default_page="Default", app_id="")
        )

    assert exc_info.value.code == REFUSED
    assert app.calls == []
