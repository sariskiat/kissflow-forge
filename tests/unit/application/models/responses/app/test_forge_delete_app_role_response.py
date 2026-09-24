"""Spec for app.application.models.responses.app.forge_delete_app_role_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_delete_app_role_response import (
    ForgeDeleteAppRoleResponse,
)


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    resp = ForgeDeleteAppRoleResponse(role_id="Ro1", deleted=True)
    assert resp.model_dump(mode="json") == {
        "role_id": "Ro1",
        "deleted": True,
        "snapshot_version": None,
    }


def test_model_validate_round_trips() -> None:
    original = ForgeDeleteAppRoleResponse(role_id="Ro1", deleted=True)
    got = ForgeDeleteAppRoleResponse.model_validate(original.model_dump(mode="json"))
    assert got == original
