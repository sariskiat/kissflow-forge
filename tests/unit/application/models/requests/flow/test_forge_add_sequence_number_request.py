"""`ForgeAddSequenceNumberRequest`: shape only, no `coerce_*` helper existed
for this tool (pre-refactor); every parameter is already a flat scalar."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_add_sequence_number_request import (
    ForgeAddSequenceNumberRequest,
)


def _request(**overrides: Any) -> ForgeAddSequenceNumberRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "field_name": "Case ID",
        "section_name": "Details",
        "prefix": "CS-",
        "padding": "0001",
        "step_activity_name": "Start",
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeAddSequenceNumberRequest(**fields)


def test_defaults_match_the_old_tool_parameters() -> None:
    req = _request()
    assert req.start == 0
    assert req.end == 2
    assert req.kind == "process"
    assert req.publish is False


def test_every_field_is_settable() -> None:
    req = _request(start=1, end=3, kind="form", publish=True)
    assert req.start == 1
    assert req.end == 3
    assert req.kind == "form"
    assert req.publish is True


def test_rejects_a_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        ForgeAddSequenceNumberRequest.model_validate(
            {"flow_id": "F1", "field_name": "Case ID", "app_id": "A1"}
        )


def test_rejects_a_non_int_start() -> None:
    with pytest.raises(ValidationError):
        _request(start="zero")


def test_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        _request(kind="dataset")


def test_rejects_an_extra_field() -> None:
    with pytest.raises(ValidationError):
        _request(unexpected="x")
