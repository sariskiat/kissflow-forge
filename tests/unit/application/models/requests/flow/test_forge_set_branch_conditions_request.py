"""`ForgeSetBranchConditionsRequest`: one field per `forge_set_branch_conditions`
parameter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_set_branch_conditions_request import (
    ForgeSetBranchConditionsRequest,
)


def test_defaults_match_the_old_tool_signature() -> None:
    req = ForgeSetBranchConditionsRequest(
        flow_id="F1", field_name="Track", branch_literals={"Branch A": "Alpha"}
    )
    assert req.flow_id == "F1"
    assert req.field_name == "Track"
    assert req.branch_literals == {"Branch A": "Alpha"}
    assert req.kind == "process"
    assert req.publish is False
    assert req.app_id == ""


def test_every_field_can_be_set() -> None:
    req = ForgeSetBranchConditionsRequest(
        flow_id="F1",
        field_name="Track",
        branch_literals={"Branch A": "Alpha", "Branch B": "Beta"},
        kind="form",
        publish=True,
        app_id="App1",
    )
    assert req.branch_literals == {"Branch A": "Alpha", "Branch B": "Beta"}
    assert req.kind == "form"
    assert req.publish is True
    assert req.app_id == "App1"


def test_a_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeSetBranchConditionsRequest(  # ty: ignore[missing-argument]
            flow_id="F1",
            field_name="Track",
        )


def test_a_non_string_literal_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeSetBranchConditionsRequest(
            flow_id="F1",
            field_name="Track",
            branch_literals={"Branch A": 1},  # ty: ignore[invalid-argument-type]
        )
