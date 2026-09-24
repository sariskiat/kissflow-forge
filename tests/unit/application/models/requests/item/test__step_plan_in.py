"""Spec for app.application.models.requests.item._step_plan_in."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.item._step_plan_in import StepPlanIn


def test_constructs_from_the_minimal_shape() -> None:
    step = StepPlanIn(name="Manager Approve")
    assert step.name == "Manager Approve"
    assert step.values == {}
    assert step.reject is False
    assert step.comment == ""


def test_every_field_is_settable() -> None:
    step = StepPlanIn(
        name="Manager Approve",
        values={"Urgency": "High"},
        reject=True,
        comment="not good enough",
    )
    assert step.values == {"Urgency": "High"}
    assert step.reject is True
    assert step.comment == "not good enough"


def test_rejects_a_blank_name() -> None:
    with pytest.raises(ValidationError, match="name must not be blank"):
        StepPlanIn(name="   ")


def test_rejects_a_missing_name() -> None:
    with pytest.raises(ValidationError):
        StepPlanIn.model_validate({})


def test_rejects_a_non_object_values() -> None:
    with pytest.raises(ValidationError):
        StepPlanIn.model_validate({"name": "Step", "values": "nope"})


def test_rejects_a_non_string_comment() -> None:
    with pytest.raises(ValidationError):
        StepPlanIn.model_validate({"name": "Step", "comment": 5})


def test_is_frozen() -> None:
    step = StepPlanIn(name="Manager Approve")
    with pytest.raises(ValidationError):
        step.name = "Other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
