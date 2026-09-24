"""Tests for `ForgeApproveSpecRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.models.requests.intake.forge_approve_spec_request import (
    ForgeApproveSpecRequest,
)

_WIRE = blank_spec().model_dump(mode="json")


def test_builds_with_the_literal_approve_decision() -> None:
    request = ForgeApproveSpecRequest(spec=_WIRE, digest="d", decision="approve")
    assert request.decision == "approve"


@pytest.mark.parametrize("bad_decision", ["Approve", "approved", "yes", "revise", ""])
def test_rejects_any_decision_other_than_the_literal_approve(
    bad_decision: str,
) -> None:
    """The old tool already declared `decision: ApprovalDecision`
    (`Literal["approve"]`) -- Pydantic now actually enforces it, where a
    bare Python function never did."""
    with pytest.raises(ValidationError):
        ForgeApproveSpecRequest(
            spec=_WIRE,
            digest="d",
            decision=bad_decision,  # ty: ignore[invalid-argument-type]
        )
