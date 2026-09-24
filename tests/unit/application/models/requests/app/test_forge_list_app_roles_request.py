"""Spec for app.application.models.requests.app.forge_list_app_roles_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_list_app_roles_request import (
    ForgeListAppRolesRequest,
)


def test_constructs_from_keyword_args() -> None:
    req = ForgeListAppRolesRequest(app_id="App1")
    assert req.app_id == "App1"


def test_missing_app_id_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeListAppRolesRequest.model_validate({})


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeListAppRolesRequest(app_id="App1")
    got = ForgeListAppRolesRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
