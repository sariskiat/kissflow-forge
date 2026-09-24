"""Spec for app.application.models.requests.item.forge_simulate_case_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.item.forge_simulate_case_request import (
    ForgeSimulateCaseRequest,
)


def test_constructs_from_the_minimal_shape() -> None:
    req = ForgeSimulateCaseRequest(
        flow_id="Flow_1", steps=[{"name": "Manager Approve"}], app_id="A1"
    )
    assert req.flow_id == "Flow_1"
    assert len(req.steps) == 1
    assert req.steps[0].name == "Manager Approve"
    assert req.poll is True
    assert req.poll_tries == 8
    assert req.poll_delay == 0.9


def test_every_field_is_settable() -> None:
    req = ForgeSimulateCaseRequest(
        flow_id="Flow_1",
        steps=[],
        poll=False,
        poll_tries=3,
        poll_delay=0.1,
        app_id="A1",
    )
    assert req.poll is False
    assert req.poll_tries == 3
    assert req.poll_delay == 0.1


def test_rejects_a_missing_steps() -> None:
    with pytest.raises(ValidationError):
        ForgeSimulateCaseRequest.model_validate({"flow_id": "Flow_1", "app_id": "A1"})


def test_a_step_missing_name_names_its_index_and_a_correct_shape() -> None:
    """Restores `app.application.tools.coerce_case_steps`'s own text
    (review fix 3), lost when `StepPlanIn`'s generic Pydantic message
    replaced it -- pinned pre-refactor by
    `tests/test_mcp_boundary.py:596-603`."""
    with pytest.raises(ValidationError) as exc_info:
        ForgeSimulateCaseRequest(flow_id="Flow_1", steps=[{"values": {}}], app_id="A1")

    msg = str(exc_info.value)
    assert "steps[0]['name']" in msg
    assert "correct shape:" in msg


def test_a_step_that_is_not_an_object_names_its_index() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ForgeSimulateCaseRequest(flow_id="Flow_1", steps=["nope"], app_id="A1")

    assert "steps[0]" in str(exc_info.value)


def test_steps_not_a_list_names_the_parameter() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ForgeSimulateCaseRequest.model_validate(
            {"flow_id": "Flow_1", "steps": "nope", "app_id": "A1"}
        )

    msg = str(exc_info.value)
    assert "steps:" in msg
    assert "correct shape:" in msg


def test_a_null_values_becomes_an_empty_dict() -> None:
    """`tools.py:502`'s own `step.get("values") or {}` -- a `null` was
    always accepted, never a shape error."""
    req = ForgeSimulateCaseRequest(
        flow_id="Flow_1",
        steps=[{"name": "Manager Approve", "values": None}],
        app_id="A1",
    )

    assert req.steps[0].values == {}


def test_rejects_a_missing_app_id() -> None:
    with pytest.raises(ValidationError):
        ForgeSimulateCaseRequest.model_validate({"flow_id": "Flow_1", "steps": []})


def test_is_frozen() -> None:
    req = ForgeSimulateCaseRequest(flow_id="Flow_1", steps=[], app_id="A1")
    with pytest.raises(ValidationError):
        req.flow_id = "Other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
