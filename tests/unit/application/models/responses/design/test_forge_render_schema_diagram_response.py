"""Spec for
app.application.models.responses.design.forge_render_schema_diagram_response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.responses.design.forge_render_schema_diagram_response import (  # noqa: E501
    ForgeRenderSchemaDiagramResponse,
)


def _response(**overrides: object) -> ForgeRenderSchemaDiagramResponse:
    base: dict[str, object] = {
        "xml": "<mxGraphModel/>",
        "path": "/tmp/x/schema_diagram.drawio",
        "gaps": [],
        "blocking_gaps": [],
    }
    base.update(overrides)
    return ForgeRenderSchemaDiagramResponse.model_validate(base)


def test_model_dump_json_mode_matches_the_old_success_dict() -> None:
    resp = _response()
    dumped = resp.model_dump(mode="json")
    assert dumped == {
        "xml": "<mxGraphModel/>",
        "path": "/tmp/x/schema_diagram.drawio",
        "gaps": [],
        "blocking_gaps": [],
    }
    assert "isError" not in dumped


def test_is_frozen() -> None:
    resp = _response()
    with pytest.raises(ValidationError):
        resp.xml = "<other/>"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
