"""Spec for app.application.models.requests.app.forge_create_app_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_create_app_request import (
    ForgeCreateAppRequest,
)


def test_carries_the_name() -> None:
    assert ForgeCreateAppRequest(name="Sample App").name == "Sample App"


def test_needs_no_app_id_it_is_an_account_level_create() -> None:
    """The old tool built its client with `require_app=False`: this is how a user
    makes their FIRST app, so the request has no app id at all."""
    assert "app_id" not in ForgeCreateAppRequest.model_fields


def test_rejects_a_missing_name() -> None:
    with pytest.raises(ValidationError):
        ForgeCreateAppRequest.model_validate({})


def test_rejects_a_name_that_is_not_a_string() -> None:
    with pytest.raises(ValidationError):
        ForgeCreateAppRequest.model_validate({"name": 7})


def test_is_frozen() -> None:
    req = ForgeCreateAppRequest(name="Sample App")
    with pytest.raises(ValidationError):
        req.name = "Other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
