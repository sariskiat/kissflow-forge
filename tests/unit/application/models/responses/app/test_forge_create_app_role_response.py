"""Spec for app.application.models.responses.app.forge_create_app_role_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_create_app_role_response import (
    ForgeCreateAppRoleResponse,
)


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    resp = ForgeCreateAppRoleResponse(role_id="Ro1", name="Reviewer", app_id="App1")
    assert resp.model_dump(mode="json") == {
        "role_id": "Ro1",
        "name": "Reviewer",
        "app_id": "App1",
        "snapshot_version": None,
    }


def test_model_validate_round_trips() -> None:
    original = ForgeCreateAppRoleResponse(role_id="Ro1", name="Reviewer", app_id="App1")
    got = ForgeCreateAppRoleResponse.model_validate(original.model_dump(mode="json"))
    assert got == original
