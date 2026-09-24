"""Tests for `ForgeIntakeQuestionsRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.models.requests.intake.forge_intake_questions_request import (
    ForgeIntakeQuestionsRequest,
)


def test_defaults_to_no_spec_and_limit_four() -> None:
    request = ForgeIntakeQuestionsRequest()
    assert request.spec is None
    assert request.limit == 4


def test_accepts_a_spec_and_a_custom_limit() -> None:
    wire = blank_spec().model_dump(mode="json")
    request = ForgeIntakeQuestionsRequest(spec=wire, limit=10)
    assert request.spec is not None
    assert request.spec.model_dump(mode="json") == wire
    assert request.limit == 10


def test_rejects_a_spec_missing_a_dimension() -> None:
    """The shape check `app.infrastructure.mcp.server._decode` used to run
    by hand is now Pydantic's own job."""
    bad = blank_spec().model_dump(mode="json")
    del bad["problem_goal"]
    with pytest.raises(ValidationError, match="problem_goal"):
        ForgeIntakeQuestionsRequest(spec=bad)
