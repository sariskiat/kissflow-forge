"""Spec for app.application.models.responses.intake.op."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.responses.intake.op import Op


def test_constructs_from_keyword_args() -> None:
    op = Op(kind="create_process", args={"name": "Repairs"}, why="the flow itself")
    assert op.kind == "create_process"
    assert op.args == {"name": "Repairs"}
    assert op.why == "the flow itself"


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    op = Op(kind="apply_fields", args={"fields": [{"Name": "X"}]}, why="dimension 6")
    assert op.model_dump(mode="json") == {
        "kind": "apply_fields",
        "args": {"fields": [{"Name": "X"}]},
        "why": "dimension 6",
    }


def test_is_frozen() -> None:
    op = Op(kind="publish", args={}, why="ship it")
    with pytest.raises(ValidationError):
        op.kind = "other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]


def test_model_validate_round_trips() -> None:
    original = Op(kind="doctor", args={"flow_id": "abc"}, why="health check")
    got = Op.model_validate(original.model_dump(mode="json"))
    assert got == original
