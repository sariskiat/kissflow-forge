"""Spec for app.application.models.requests.app.forge_create_app_role_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_create_app_role_request import (
    ForgeCreateAppRoleRequest,
)


def test_constructs_from_keyword_args() -> None:
    req = ForgeCreateAppRoleRequest(name="Reviewer", app_id="App1")
    assert req.name == "Reviewer"
    assert req.app_id == "App1"


def test_missing_name_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeCreateAppRoleRequest.model_validate({"app_id": "App1"})


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeCreateAppRoleRequest(name="Reviewer", app_id="App1")
    got = ForgeCreateAppRoleRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
