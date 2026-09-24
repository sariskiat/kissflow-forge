"""Spec for app.application.models.requests.page._page_build_step_in."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.page._page_build_step_in import PageBuildStepIn


def test_constructs_from_the_minimal_shape() -> None:
    step = PageBuildStepIn(kind="container")
    assert step.kind == "container"
    assert step.kwargs is None


def test_kwargs_round_trips() -> None:
    step = PageBuildStepIn(kind="widget", kwargs={"container_id": "Container001"})
    assert step.kwargs == {"container_id": "Container001"}


def test_rejects_a_blank_kind() -> None:
    with pytest.raises(ValidationError, match="kind must be one of"):
        PageBuildStepIn(kind="   ")


def test_rejects_a_missing_kind() -> None:
    with pytest.raises(ValidationError):
        PageBuildStepIn.model_validate({})


def test_rejects_a_non_object_kwargs() -> None:
    with pytest.raises(ValidationError):
        PageBuildStepIn.model_validate({"kind": "widget", "kwargs": "nope"})


def test_is_frozen() -> None:
    step = PageBuildStepIn(kind="container")
    with pytest.raises(ValidationError):
        step.kind = "widget"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
