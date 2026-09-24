"""`KfSetStepVisibilityRequest`: one field per `kf_set_step_visibility`
parameter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.kf_set_step_visibility_request import (
    KfSetStepVisibilityRequest,
)


def test_defaults_match_the_old_tool_signature() -> None:
    req = KfSetStepVisibilityRequest(flow_id="F1", owners={"Intake": ["Start"]})
    assert req.flow_id == "F1"
    assert req.owners == {"Intake": ["Start"]}
    assert req.publish is False
    assert req.include_pairs is False
    assert req.app_id == ""


def test_every_field_can_be_set() -> None:
    req = KfSetStepVisibilityRequest(
        flow_id="F1",
        owners={"Intake": ["Start"]},
        publish=True,
        include_pairs=True,
        app_id="App1",
    )
    assert req.publish is True
    assert req.include_pairs is True
    assert req.app_id == "App1"


def test_a_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        KfSetStepVisibilityRequest(flow_id="F1")  # ty: ignore[missing-argument]


def test_has_no_kind_or_field_owners_parameter() -> None:
    """Unlike `forge_set_visibility`, this tool always targets "process" and has no
    field-level override -- confirm the model carries no such fields."""
    fields = KfSetStepVisibilityRequest.model_fields
    assert "kind" not in fields
    assert "field_owners" not in fields
