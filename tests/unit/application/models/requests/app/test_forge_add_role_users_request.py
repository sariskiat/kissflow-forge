"""Spec for app.application.models.requests.app.forge_add_role_users_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_add_role_users_request import (
    ForgeAddRoleUsersRequest,
)


def test_constructs_with_defaults() -> None:
    req = ForgeAddRoleUsersRequest(role_id="R1", app_id="App1")
    assert req.user_query is None
    assert req.user_ids is None
    assert req.groups is None
    assert req.confirm_group_notification is False
    assert req.force_regrant_groups is False


def test_constructs_with_every_field() -> None:
    req = ForgeAddRoleUsersRequest(
        role_id="R1",
        user_query="ann",
        user_ids=[{"_id": "U1", "Kind": "User"}],
        groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True,
        force_regrant_groups=True,
        app_id="App1",
    )
    assert req.confirm_group_notification is True
    assert req.force_regrant_groups is True


def test_missing_role_id_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeAddRoleUsersRequest.model_validate({"app_id": "App1"})


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeAddRoleUsersRequest(role_id="R1", user_query="ann", app_id="App1")
    got = ForgeAddRoleUsersRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
