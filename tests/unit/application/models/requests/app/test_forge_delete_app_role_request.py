"""Spec for app.application.models.requests.app.forge_delete_app_role_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_delete_app_role_request import (
    ForgeDeleteAppRoleRequest,
)


def test_constructs_from_keyword_args() -> None:
    req = ForgeDeleteAppRoleRequest(role_id="Ro1", app_id="App1")
    assert req.role_id == "Ro1"
    assert req.app_id == "App1"


def test_missing_role_id_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeDeleteAppRoleRequest.model_validate({"app_id": "App1"})


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeDeleteAppRoleRequest(role_id="Ro1", app_id="App1")
    got = ForgeDeleteAppRoleRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
