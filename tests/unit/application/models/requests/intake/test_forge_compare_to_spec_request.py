"""Tests for `ForgeCompareToSpecRequest`."""

from __future__ import annotations

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.models.requests.intake.forge_compare_to_spec_request import (
    ForgeCompareToSpecRequest,
)


def test_builds_with_defaults() -> None:
    wire = blank_spec().model_dump(mode="json")
    request = ForgeCompareToSpecRequest(flow_id="F1", spec=wire, app_id="A1")
    assert request.flow_id == "F1"
    assert request.kind == "process"
    assert request.app_id == "A1"
