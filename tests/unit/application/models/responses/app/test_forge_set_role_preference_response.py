"""Spec for app.application.models.responses.app.forge_set_role_preference_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_set_role_preference_response import (
    ForgeSetRolePreferenceResponse,
)


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    resp = ForgeSetRolePreferenceResponse(
        role_id="R1",
        default_page="Page_1",
        default_navigation=None,
        verified=True,
    )
    assert resp.model_dump(mode="json") == {
        "role_id": "R1",
        "default_page": "Page_1",
        "default_navigation": None,
        "verified": True,
        "snapshot_version": None,
    }


def test_model_validate_round_trips() -> None:
    original = ForgeSetRolePreferenceResponse(
        role_id="R1",
        default_page="Page_1",
        default_navigation="Navigation001",
        verified=True,
    )
    got = ForgeSetRolePreferenceResponse.model_validate(
        original.model_dump(mode="json")
    )
    assert got == original
