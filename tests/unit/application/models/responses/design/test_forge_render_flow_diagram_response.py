"""Spec for
app.application.models.responses.design.forge_render_flow_diagram_response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.responses.design.forge_render_flow_diagram_response import (
    ForgeRenderFlowDiagramResponse,
)


def _response(**overrides: object) -> ForgeRenderFlowDiagramResponse:
    base: dict[str, object] = {
        "xml": "<mxGraphModel/>",
        "path": "/tmp/x/flow_diagram.drawio",
        "gaps": ["1. problem/goal: ..."],
        "blocking_gaps": ["1. problem/goal: ..."],
    }
    base.update(overrides)
    return ForgeRenderFlowDiagramResponse.model_validate(base)


def test_model_dump_json_mode_matches_the_old_success_dict() -> None:
    resp = _response()
    dumped = resp.model_dump(mode="json")
    assert dumped == {
        "xml": "<mxGraphModel/>",
        "path": "/tmp/x/flow_diagram.drawio",
        "gaps": ["1. problem/goal: ..."],
        "blocking_gaps": ["1. problem/goal: ..."],
    }
    assert "isError" not in dumped


def test_is_frozen() -> None:
    resp = _response()
    with pytest.raises(ValidationError):
        resp.xml = "<other/>"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
