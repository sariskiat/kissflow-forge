"""Spec for app.application.models.requests.app.forge_set_role_preference_request."""

from __future__ import annotations

from app.application.models.requests.app.forge_set_role_preference_request import (
    ForgeSetRolePreferenceRequest,
)


def test_constructs_with_defaults() -> None:
    req = ForgeSetRolePreferenceRequest(role_id="R1", app_id="App1")
    assert req.default_page is None
    assert req.default_navigation is None


def test_constructs_with_the_default_sentinel() -> None:
    req = ForgeSetRolePreferenceRequest(
        role_id="R1", default_page="Default", app_id="App1"
    )
    assert req.default_page == "Default"


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeSetRolePreferenceRequest(
        role_id="R1", default_page="Page_1", app_id="App1"
    )
    got = ForgeSetRolePreferenceRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
