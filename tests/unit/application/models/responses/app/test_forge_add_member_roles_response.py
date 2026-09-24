"""Spec for app.application.models.responses.app.forge_add_member_roles_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_add_member_roles_response import (
    ForgeAddMemberRolesResponse,
)


def _response() -> ForgeAddMemberRolesResponse:
    return ForgeAddMemberRolesResponse(
        target_flow_id="F1",
        source_flow_id=None,
        harvested=["FDE"],
        applied=["RoExist"],
        verified=["RoExist"],
        missing=[],
        note="granted 1 app-scoped AppRole(s): FDE",
        role_ids=["RoExist"],
        resolved={"FDE": "RoExist"},
        roles_seen=1,
        roles_granted=1,
        roles_unusable=[],
    )


def test_snapshot_version_defaults_to_none() -> None:
    assert _response().snapshot_version is None


def test_model_validate_round_trips() -> None:
    original = _response()
    got = ForgeAddMemberRolesResponse.model_validate(original.model_dump(mode="json"))
    assert got == original
