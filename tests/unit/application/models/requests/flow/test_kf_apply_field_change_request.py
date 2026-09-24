"""Spec for app.application.models.requests.flow.kf_apply_field_change_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.kf_apply_field_change_request import (
    KfApplyFieldChangeRequest,
)


def test_constructs_from_the_tool_shaped_arguments() -> None:
    req = KfApplyFieldChangeRequest(
        flow_kind="form",
        flow_id="F1",
        changes=[{"name": "Ticket No", "type": "Text", "required": True}],
        publish=True,
        app_id="A1",
    )
    assert req.flow_kind == "form"
    assert req.flow_id == "F1"
    assert req.changes[0].name == "Ticket No"
    assert req.changes[0].required is True
    assert req.publish is True
    assert req.app_id == "A1"


def test_publish_defaults_false() -> None:
    req = KfApplyFieldChangeRequest(
        flow_kind="process", flow_id="F1", changes=[], app_id=""
    )
    assert req.publish is False


def test_app_id_empty_string_is_a_legal_unresolved_app() -> None:
    """The tool resolves app_id to "" when none is configured -- the DTO accepts it;
    the USE CASE is what refuses an empty app_id (see "The app id",
    brief_stage_d_common.md)."""
    req = KfApplyFieldChangeRequest(
        flow_kind="process", flow_id="F1", changes=[], app_id=""
    )
    assert req.app_id == ""


def test_rejects_a_flow_kind_outside_the_closed_data_kind_set() -> None:
    with pytest.raises(ValidationError):
        KfApplyFieldChangeRequest.model_validate(
            {"flow_kind": "list", "flow_id": "F1", "changes": [], "app_id": "A1"}
        )


def test_rejects_a_malformed_change_entry() -> None:
    with pytest.raises(ValidationError):
        KfApplyFieldChangeRequest(
            flow_kind="form",
            flow_id="F1",
            changes=[{"name": "A", "type": "NotAType"}],
            app_id="A1",
        )


def test_rejects_a_change_that_is_not_a_list() -> None:
    with pytest.raises(ValidationError):
        KfApplyFieldChangeRequest.model_validate(
            {"flow_kind": "form", "flow_id": "F1", "changes": {}, "app_id": "A1"}
        )


def test_is_frozen() -> None:
    req = KfApplyFieldChangeRequest(
        flow_kind="form", flow_id="F1", changes=[], app_id="A1"
    )
    with pytest.raises(ValidationError):
        req.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
