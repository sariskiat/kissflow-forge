"""Tests for `ForgePlanAppRequest`."""

from __future__ import annotations

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.models.requests.intake.forge_plan_app_request import (
    ForgePlanAppRequest,
)


def test_builds_from_a_spec_and_a_token() -> None:
    wire = blank_spec().model_dump(mode="json")
    request = ForgePlanAppRequest(spec=wire, approval_token="x")
    assert request.spec.model_dump(mode="json") == wire
    assert request.approval_token == "x"
