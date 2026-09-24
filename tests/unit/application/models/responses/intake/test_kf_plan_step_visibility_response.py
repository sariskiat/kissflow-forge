"""Tests for `KfPlanStepVisibilityResponse` -- a `RootModel[dict[str, Any]]`."""

from __future__ import annotations

from app.application.models.responses.intake.kf_plan_step_visibility_response import (
    KfPlanStepVisibilityResponse,
)


def test_round_trips_an_arbitrary_key_set() -> None:
    payload = {
        "sections": {
            "Intake Basics": {"editable_at": ["Intake"], "readonly": 4},
        },
        "permission_nodes": 4,
    }
    response = KfPlanStepVisibilityResponse(payload)
    assert response.model_dump(mode="json") == payload
