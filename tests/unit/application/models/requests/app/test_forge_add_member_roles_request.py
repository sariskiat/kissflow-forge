"""Spec for app.application.models.requests.app.forge_add_member_roles_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_add_member_roles_request import (
    ForgeAddMemberRolesRequest,
)


def test_constructs_with_defaults() -> None:
    req = ForgeAddMemberRolesRequest(
        target_flow_id="F1", roles={"RoX": "Requester"}, app_id="App1"
    )
    assert req.roles == {"RoX": "Requester"}
    assert req.kind == "process"


def test_missing_roles_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeAddMemberRolesRequest.model_validate(
            {"target_flow_id": "F1", "app_id": "App1"}
        )


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeAddMemberRolesRequest(
        target_flow_id="F1", roles={"RoX": "Requester"}, app_id="App1"
    )
    got = ForgeAddMemberRolesRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
