"""Spec for app.application.models.requests.app.forge_publish_app_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_publish_app_request import (
    ForgePublishAppRequest,
)


def test_carries_the_app_id() -> None:
    assert ForgePublishAppRequest(app_id="App1").app_id == "App1"


def test_rejects_a_missing_app_id() -> None:
    with pytest.raises(ValidationError):
        ForgePublishAppRequest.model_validate({})


def test_is_frozen() -> None:
    req = ForgePublishAppRequest(app_id="App1")
    with pytest.raises(ValidationError):
        req.app_id = "App2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
