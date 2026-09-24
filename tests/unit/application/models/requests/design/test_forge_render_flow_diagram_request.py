"""Spec for app.application.models.requests.design.forge_render_flow_diagram_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.design.forge_render_flow_diagram_request import (
    ForgeRenderFlowDiagramRequest,
)
from app.application.models.requests.intake.app_spec import blank_spec


def test_constructs_from_a_plain_spec_dict() -> None:
    req = ForgeRenderFlowDiagramRequest(spec=blank_spec().model_dump(mode="json"))
    assert req.spec.app_name == ""
    assert req.out_dir is None


def test_carries_out_dir() -> None:
    req = ForgeRenderFlowDiagramRequest(
        spec=blank_spec().model_dump(mode="json"), out_dir="/tmp/x"
    )
    assert req.out_dir == "/tmp/x"


def test_rejects_a_malformed_spec() -> None:
    with pytest.raises(ValidationError):
        ForgeRenderFlowDiagramRequest(spec={"not": "a spec"})


def test_is_frozen() -> None:
    req = ForgeRenderFlowDiagramRequest(spec=blank_spec().model_dump(mode="json"))
    with pytest.raises(ValidationError):
        req.out_dir = "/tmp/y"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
