"""Tests for `KfPlanFieldChangeRequest`."""

from __future__ import annotations

from app.application.models.requests.intake._field_change_in import FieldChangeIn
from app.application.models.requests.intake.kf_plan_field_change_request import (
    KfPlanFieldChangeRequest,
)


def test_builds_from_a_draft_and_a_change_list() -> None:
    request = KfPlanFieldChangeRequest(
        draft={"Root": "M1"}, changes=[{"name": "Notes", "type": "Text"}]
    )
    assert request.draft == {"Root": "M1"}
    assert request.changes == [FieldChangeIn(name="Notes", type="Text")]
