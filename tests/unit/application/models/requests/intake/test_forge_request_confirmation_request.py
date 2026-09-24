"""Tests for `ForgeRequestConfirmationRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.models.requests.intake.forge_request_confirmation_request import (  # noqa: E501
    ForgeRequestConfirmationRequest,
)


def test_builds_from_a_spec_and_defaults_out_dir_to_none() -> None:
    wire = blank_spec().model_dump(mode="json")
    request = ForgeRequestConfirmationRequest(spec=wire)
    assert request.spec.model_dump(mode="json") == wire
    assert request.out_dir is None


def test_rejects_a_spec_missing_a_dimension() -> None:
    bad = blank_spec().model_dump(mode="json")
    del bad["problem_goal"]
    with pytest.raises(ValidationError, match="problem_goal"):
        ForgeRequestConfirmationRequest(spec=bad)
