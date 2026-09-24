"""Spec for app.application.models.requests.copilot.forge_copilot_check_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.copilot.forge_copilot_check_request import (
    ForgeCopilotCheckRequest,
)


def test_constructs_from_the_minimal_shape() -> None:
    req = ForgeCopilotCheckRequest(app_id="A1", conversation_id="C1")
    assert req.app_id == "A1"
    assert req.conversation_id == "C1"
    assert req.baseline_inventory is None


def test_baseline_inventory_round_trips() -> None:
    req = ForgeCopilotCheckRequest(
        app_id="A1",
        conversation_id="C1",
        baseline_inventory={"process": ["P1"], "list": []},
    )
    assert req.baseline_inventory == {"process": ["P1"], "list": []}


def test_rejects_a_missing_conversation_id() -> None:
    with pytest.raises(ValidationError):
        ForgeCopilotCheckRequest.model_validate({"app_id": "A1"})


def test_is_frozen() -> None:
    req = ForgeCopilotCheckRequest(app_id="A1", conversation_id="C1")
    with pytest.raises(ValidationError):
        req.conversation_id = "C2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
