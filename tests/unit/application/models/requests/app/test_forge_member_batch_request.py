"""Spec for app.application.models.requests.app.forge_member_batch_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_member_batch_request import (
    ForgeMemberBatchRequest,
)


def test_constructs_with_defaults() -> None:
    req = ForgeMemberBatchRequest(target_flow_id="F1", app_id="App1")
    assert req.target_flow_id == "F1"
    assert req.source_flow_id is None
    assert req.kind == "process"
    assert req.app_id == "App1"


def test_constructs_with_every_field() -> None:
    req = ForgeMemberBatchRequest(
        target_flow_id="F1", source_flow_id="F2", kind="case", app_id="App1"
    )
    assert req.source_flow_id == "F2"
    assert req.kind == "case"


def test_missing_target_flow_id_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeMemberBatchRequest.model_validate({"app_id": "App1"})


def test_unknown_kind_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeMemberBatchRequest.model_validate(
            {"target_flow_id": "F1", "app_id": "App1", "kind": "dataset"}
        )


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeMemberBatchRequest(target_flow_id="F1", app_id="App1")
    got = ForgeMemberBatchRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
