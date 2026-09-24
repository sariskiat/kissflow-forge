"""Spec for app.application.models.requests.copilot.forge_copilot_ask_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.copilot.forge_copilot_ask_request import (
    ForgeCopilotAskRequest,
)


def test_constructs_from_the_minimal_shape() -> None:
    req = ForgeCopilotAskRequest(app_id="A1", message="add a field")
    assert req.app_id == "A1"
    assert req.message == "add a field"
    assert req.expect is None


def test_expect_round_trips() -> None:
    req = ForgeCopilotAskRequest(
        app_id="A1", message="add a currency field", expect=["Field"]
    )
    assert req.expect == ["Field"]


def test_rejects_a_missing_message() -> None:
    with pytest.raises(ValidationError):
        ForgeCopilotAskRequest.model_validate({"app_id": "A1"})


def test_is_frozen() -> None:
    req = ForgeCopilotAskRequest(app_id="A1", message="add a field")
    with pytest.raises(ValidationError):
        req.message = "other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
