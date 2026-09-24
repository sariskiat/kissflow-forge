"""`ForgeSetVisibilityRequest`: one field per `forge_set_visibility` parameter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_set_visibility_request import (
    ForgeSetVisibilityRequest,
)


def test_defaults_match_the_old_tool_signature() -> None:
    req = ForgeSetVisibilityRequest(flow_id="F1", owners={"Intake": ["Start"]})
    assert req.flow_id == "F1"
    assert req.owners == {"Intake": ["Start"]}
    assert req.field_owners is None
    assert req.kind == "process"
    assert req.publish is False
    assert req.include_pairs is False
    assert req.app_id == ""


def test_every_field_can_be_set() -> None:
    req = ForgeSetVisibilityRequest(
        flow_id="F1",
        owners={"Intake": ["Start"]},
        field_owners={"Field 25": ["Wrap-up report"]},
        kind="form",
        publish=True,
        include_pairs=True,
        app_id="App1",
    )
    assert req.field_owners == {"Field 25": ["Wrap-up report"]}
    assert req.kind == "form"
    assert req.publish is True
    assert req.include_pairs is True
    assert req.app_id == "App1"


def test_a_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeSetVisibilityRequest(flow_id="F1")  # ty: ignore[missing-argument]


def test_owners_values_must_be_lists_of_strings() -> None:
    with pytest.raises(ValidationError):
        ForgeSetVisibilityRequest(flow_id="F1", owners={"Intake": "Start"})
