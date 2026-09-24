"""Tests for `ForgeUpdateSpecRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.models.requests.intake.forge_update_spec_request import (
    ForgeUpdateSpecRequest,
)


def test_accepts_none_spec_with_a_patch() -> None:
    request = ForgeUpdateSpecRequest(spec=None, patch={"app_name": "X"})
    assert request.spec is None
    assert request.patch == {"app_name": "X"}


def test_accepts_a_real_spec_with_a_patch() -> None:
    wire = blank_spec().model_dump(mode="json")
    request = ForgeUpdateSpecRequest(spec=wire, patch={})
    assert request.spec is not None
    assert request.spec.model_dump(mode="json") == wire


def test_rejects_a_spec_missing_a_dimension() -> None:
    bad = blank_spec().model_dump(mode="json")
    del bad["problem_goal"]
    with pytest.raises(ValidationError, match="problem_goal"):
        ForgeUpdateSpecRequest(spec=bad, patch={})


def test_rejects_a_non_dict_patch() -> None:
    with pytest.raises(ValidationError, match="patch"):
        ForgeUpdateSpecRequest(
            spec=None,
            patch="oops",  # ty: ignore[invalid-argument-type]
        )
