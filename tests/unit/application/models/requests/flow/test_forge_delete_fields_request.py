"""Spec for app.application.models.requests.flow.forge_delete_fields_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_delete_fields_request import (
    ForgeDeleteFieldsRequest,
)


def test_constructs_with_defaults() -> None:
    req = ForgeDeleteFieldsRequest(flow_id="F1", app_id="A1")
    assert req.fields is None
    assert req.tables is None
    assert req.kind == "process"
    assert req.publish is False


def test_carries_fields_and_tables() -> None:
    req = ForgeDeleteFieldsRequest(
        flow_id="F1", fields=["A"], tables=["T1"], app_id="A1"
    )
    assert req.fields == ["A"]
    assert req.tables == ["T1"]


def test_rejects_fields_that_is_not_a_list_of_strings() -> None:
    with pytest.raises(ValidationError):
        ForgeDeleteFieldsRequest.model_validate(
            {"flow_id": "F1", "fields": [1], "app_id": "A1"}
        )


def test_is_frozen() -> None:
    req = ForgeDeleteFieldsRequest(flow_id="F1", app_id="A1")
    with pytest.raises(ValidationError):
        req.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
