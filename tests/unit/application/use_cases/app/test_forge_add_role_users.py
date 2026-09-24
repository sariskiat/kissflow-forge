"""Spec for app.application.use_cases.app.forge_add_role_users.

The group-notification guard, proven again at the use-case edge: `groups` is refused
unless `confirm_group_notification` is true, before any port call. The merge,
duplicate-group and read-back algorithms are ported in `test__roles.py`; this file
proves the use case wires them, maps rule 7 and keeps the write order. Also ports
`tests/test_mcp_boundary.py`'s `test_force_regrant_groups_is_forwarded_through_the_
tool_boundary` at this layer.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.app_roles import EVERYONE, _RoleApp
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.app.forge_add_role_users_request import (
    ForgeAddRoleUsersRequest,
)
from app.application.use_cases.app.forge_add_role_users import ForgeAddRoleUsers


def _request(**overrides: Any) -> ForgeAddRoleUsersRequest:
    values: dict[str, Any] = {"role_id": "R1", "app_id": "App1"}
    values.update(overrides)
    return ForgeAddRoleUsersRequest.model_validate(values)


@pytest.mark.asyncio
async def test_a_group_grant_without_confirmation_is_refused_before_any_call() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddRoleUsers(app).execute(_request(groups=[EVERYONE]))

    assert exc_info.value.code == REFUSED
    assert "confirm_group_notification=True" in exc_info.value.message
    assert "CANNOT BE UNDONE" in exc_info.value.message
    assert app.calls == [] and app.body is None


@pytest.mark.asyncio
async def test_a_confirmed_group_grant_is_written_under_its_own_key() -> None:
    app = _RoleApp()

    response = await ForgeAddRoleUsers(app).execute(
        _request(groups=[EVERYONE], confirm_group_notification=True)
    )

    assert response.groups_added == ["everyone"]
    assert response.group_count == 1
    assert response.snapshot_version is None
    assert app.body is not None and app.body["Groups"] == [EVERYONE]
    assert app.body["Users"] == []
    assert_write_order(app)


@pytest.mark.asyncio
async def test_a_user_found_by_query_is_granted_and_verified() -> None:
    app = _RoleApp()
    app.assignees["ann"] = [{"_id": "U1", "Kind": "User", "Name": "Ann"}]

    response = await ForgeAddRoleUsers(app).execute(_request(user_query="ann"))

    assert response.added == ["U1"] and response.not_found == []
    assert response.user_count == 1
    assert [c[0] for c in app.calls] == [
        "get_app_role",
        "get_assignee",
        "put_app_role",
        "get_app_role",
    ]
    assert app.calls[2][1][0] == "App1", "the write is scoped to the resolved app"
    assert_write_order(app)


@pytest.mark.asyncio
async def test_a_query_with_no_match_is_verify_failed() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddRoleUsers(app).execute(_request(user_query="nobody"))

    assert exc_info.value.code == VERIFY_FAILED
    assert exc_info.value.message == "forge_add_role_users: not_found: nobody"
    assert app.body is None


@pytest.mark.asyncio
async def test_a_group_that_cannot_be_proven_is_verify_failed() -> None:
    app = _RoleApp(group_count=None)

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddRoleUsers(app).execute(
            _request(groups=[EVERYONE], confirm_group_notification=True)
        )

    assert exc_info.value.code == VERIFY_FAILED
    assert "groups_unverified: everyone" in exc_info.value.message


@pytest.mark.asyncio
async def test_force_regrant_groups_is_forwarded_to_the_duplicate_group_guard() -> None:
    """The same call that is refused under GroupCount > 0 succeeds once
    force_regrant_groups=True rides along -- a dropped forward of the flag would
    brick the override."""
    app = _RoleApp(group_count=1)

    refused = await ForgeAddRoleUsers(app).execute(
        _request(groups=[EVERYONE], confirm_group_notification=True)
    )
    assert refused.groups_refused == ["everyone"]
    assert app.body is None, "the refused grant must not write"

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddRoleUsers(app).execute(
            _request(
                groups=[EVERYONE],
                confirm_group_notification=True,
                force_regrant_groups=True,
            )
        )
    assert app.body is not None and app.body.get("Groups"), (
        "force_regrant_groups=True must reach the guard and re-issue the write"
    )
    # A re-grant leaves GroupCount at 1 -> 1, so the write cannot be proven: the
    # old report said isError: true here too; rule 7 makes that a raised failure.
    assert exc_info.value.code == VERIFY_FAILED
    assert "groups_unverified: everyone" in exc_info.value.message


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_port_call() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddRoleUsers(app).execute(_request(user_query="ann", app_id=""))

    assert exc_info.value.code == REFUSED
    assert "no app selected" in exc_info.value.message
    assert app.calls == []
