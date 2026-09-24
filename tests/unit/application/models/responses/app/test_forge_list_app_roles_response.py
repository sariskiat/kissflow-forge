"""Spec for app.application.models.responses.app.forge_list_app_roles_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_list_app_roles_response import (
    ForgeListAppRolesResponse,
)


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    resp = ForgeListAppRolesResponse(
        roles=[{"_id": "Ro1", "Name": "Reviewer"}], count=1, app_id="App1"
    )
    assert resp.model_dump(mode="json") == {
        "roles": [{"_id": "Ro1", "Name": "Reviewer"}],
        "count": 1,
        "app_id": "App1",
    }


def test_has_no_snapshot_version_field() -> None:
    """Read-only tool: no `snapshot_version` (that field is only additive on writes)."""
    resp = ForgeListAppRolesResponse(roles=[], count=0, app_id="App1")
    assert not hasattr(resp, "snapshot_version")


def test_model_validate_round_trips() -> None:
    original = ForgeListAppRolesResponse(
        roles=[{"_id": "Ro1", "Name": "Reviewer"}], count=1, app_id="App1"
    )
    got = ForgeListAppRolesResponse.model_validate(original.model_dump(mode="json"))
    assert got == original
