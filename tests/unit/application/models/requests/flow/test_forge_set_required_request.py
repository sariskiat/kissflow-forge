"""Spec for app.application.models.requests.flow.forge_set_required_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_set_required_request import (
    ForgeSetRequiredRequest,
)


def test_constructs_with_defaults() -> None:
    req = ForgeSetRequiredRequest(flow_id="F1", required=["A", "B"], app_id="A1")
    assert req.required == ["A", "B"]
    assert req.kind == "process"
    assert req.publish is False


def test_carries_kind_and_publish() -> None:
    req = ForgeSetRequiredRequest(
        flow_id="F1", required=[], kind="case", publish=True, app_id="A1"
    )
    assert req.kind == "case"
    assert req.publish is True


def test_rejects_a_required_that_is_not_a_list_of_strings() -> None:
    with pytest.raises(ValidationError):
        ForgeSetRequiredRequest.model_validate(
            {"flow_id": "F1", "required": [1, 2], "app_id": "A1"}
        )


def test_rejects_a_kind_outside_the_closed_flow_kind_set() -> None:
    with pytest.raises(ValidationError):
        ForgeSetRequiredRequest.model_validate(
            {"flow_id": "F1", "required": [], "kind": "dataset", "app_id": "A1"}
        )


def test_is_frozen() -> None:
    req = ForgeSetRequiredRequest(flow_id="F1", required=[], app_id="A1")
    with pytest.raises(ValidationError):
        req.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
