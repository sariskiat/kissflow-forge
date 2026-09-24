"""Spec for app.application.models.requests.flow.forge_apply_fields_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_apply_fields_request import (
    ForgeApplyFieldsRequest,
)


def test_constructs_with_only_the_required_fields() -> None:
    req = ForgeApplyFieldsRequest(
        flow_id="F1",
        fields=[{"name": "Ticket No", "type": "Text"}],
        app_id="A1",
    )
    assert req.kind == "process"
    assert req.publish is False
    assert req.sections is None
    assert req.validation is None
    assert req.computed is None
    assert req.conditional_visibility is None


def test_carries_sections_validation_computed_and_conditional_visibility() -> None:
    req = ForgeApplyFieldsRequest(
        flow_id="F1",
        fields=[{"name": "Total", "type": "Number"}],
        sections={"Case Info": ["Total"]},
        validation={"Total": [{"operator": "MAX_LENGTH", "rhs": "10"}]},
        computed={"Total": {"fn": "concatenate", "args": []}},
        conditional_visibility={
            "Total": {"trigger_field": "Region", "operator": "EQUAL_TO", "rhs": "x"}
        },
        kind="dataset",
        publish=True,
        app_id="A1",
    )
    assert req.sections == {"Case Info": ["Total"]}
    assert req.validation == {"Total": [{"operator": "MAX_LENGTH", "rhs": "10"}]}
    assert req.computed == {"Total": {"fn": "concatenate", "args": []}}
    assert req.conditional_visibility == {
        "Total": {"trigger_field": "Region", "operator": "EQUAL_TO", "rhs": "x"}
    }
    assert req.kind == "dataset"


def test_rejects_sections_whose_values_are_not_a_list_of_strings() -> None:
    with pytest.raises(ValidationError):
        ForgeApplyFieldsRequest.model_validate(
            {
                "flow_id": "F1",
                "fields": [],
                "sections": {"Case Info": [1, 2]},
                "app_id": "A1",
            }
        )


def test_rejects_a_malformed_field_entry() -> None:
    with pytest.raises(ValidationError):
        ForgeApplyFieldsRequest(
            flow_id="F1",
            fields=[{"name": "", "type": "Text"}],
            app_id="A1",
        )


def test_is_frozen() -> None:
    req = ForgeApplyFieldsRequest(flow_id="F1", fields=[], app_id="A1")
    with pytest.raises(ValidationError):
        req.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
