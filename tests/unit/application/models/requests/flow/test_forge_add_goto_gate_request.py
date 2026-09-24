"""`ForgeAddGotoGateRequest`: one field per `forge_add_goto_gate` parameter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_add_goto_gate_request import (
    ForgeAddGotoGateRequest,
)


def test_defaults_match_the_old_tool_signature() -> None:
    req = ForgeAddGotoGateRequest(
        flow_id="F1", target_activity_name="Review", field_name="Done Flag"
    )
    assert req.flow_id == "F1"
    assert req.target_activity_name == "Review"
    assert req.field_name == "Done Flag"
    assert req.branch_name is None
    assert req.kind == "process"
    assert req.publish is False
    assert req.app_id == ""


def test_every_field_can_be_set() -> None:
    req = ForgeAddGotoGateRequest(
        flow_id="F1",
        target_activity_name="Shared Step",
        field_name="Done Flag",
        branch_name="Branch A",
        kind="form",
        publish=True,
        app_id="App1",
    )
    assert req.branch_name == "Branch A"
    assert req.kind == "form"
    assert req.publish is True
    assert req.app_id == "App1"


def test_a_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeAddGotoGateRequest(  # ty: ignore[missing-argument]
            flow_id="F1",
            target_activity_name="Review",
        )


def test_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeAddGotoGateRequest(
            flow_id="F1",
            target_activity_name="Review",
            field_name="Done Flag",
            kind="not-a-kind",  # ty: ignore[invalid-argument-type]
        )
