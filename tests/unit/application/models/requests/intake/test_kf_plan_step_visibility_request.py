"""Tests for `KfPlanStepVisibilityRequest`."""

from __future__ import annotations

from app.application.models.requests.intake.kf_plan_step_visibility_request import (
    KfPlanStepVisibilityRequest,
)


def test_builds_from_a_draft_and_owners_map() -> None:
    request = KfPlanStepVisibilityRequest(
        draft={"Root": "M1"}, owners={"Intake Basics": ["Intake"]}
    )
    assert request.draft == {"Root": "M1"}
    assert request.owners == {"Intake Basics": ["Intake"]}
