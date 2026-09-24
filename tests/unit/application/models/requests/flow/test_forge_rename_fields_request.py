"""Spec for app.application.models.requests.flow.forge_rename_fields_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_rename_fields_request import (
    ForgeRenameFieldsRequest,
)


def test_constructs_with_defaults() -> None:
    req = ForgeRenameFieldsRequest(flow_id="F1", renames={"Old": "New"}, app_id="A1")
    assert req.renames == {"Old": "New"}
    assert req.kind == "process"
    assert req.publish is False


def test_rejects_a_renames_value_that_is_not_a_string() -> None:
    with pytest.raises(ValidationError):
        ForgeRenameFieldsRequest.model_validate(
            {"flow_id": "F1", "renames": {"Old": 1}, "app_id": "A1"}
        )


def test_is_frozen() -> None:
    req = ForgeRenameFieldsRequest(flow_id="F1", renames={}, app_id="A1")
    with pytest.raises(ValidationError):
        req.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
