"""Tests for `ForgeApplyRevisionsRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.models.requests.intake.forge_apply_revisions_request import (
    ForgeApplyRevisionsRequest,
)


def test_builds_from_a_spec_and_a_revision_map() -> None:
    wire = blank_spec().model_dump(mode="json")
    request = ForgeApplyRevisionsRequest(spec=wire, revisions={"app_name": "Y"})
    assert request.spec.model_dump(mode="json") == wire
    assert request.revisions == {"app_name": "Y"}


def test_rejects_a_spec_missing_a_dimension() -> None:
    bad = blank_spec().model_dump(mode="json")
    del bad["problem_goal"]
    with pytest.raises(ValidationError, match="problem_goal"):
        ForgeApplyRevisionsRequest(spec=bad, revisions={})


def test_rejects_a_non_dict_revisions_argument() -> None:
    wire = blank_spec().model_dump(mode="json")
    with pytest.raises(ValidationError, match="revisions"):
        ForgeApplyRevisionsRequest(
            spec=wire,
            revisions="oops",  # ty: ignore[invalid-argument-type]
        )
