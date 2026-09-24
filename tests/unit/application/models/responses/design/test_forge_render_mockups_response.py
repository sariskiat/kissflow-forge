"""Spec for app.application.models.responses.design.forge_render_mockups_response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.responses.design.forge_render_mockups_response import (
    ForgeRenderMockupsResponse,
)


def _response(**overrides: object) -> ForgeRenderMockupsResponse:
    base: dict[str, object] = {
        "html": "<!doctype html><html></html>",
        "path": "/tmp/x/mockups.html",
        "summary": "0 stage(s), 0 table(s), 0 reference list(s), 0 persona view(s)",
        "gaps": [],
        "blocking_gaps": [],
    }
    base.update(overrides)
    return ForgeRenderMockupsResponse.model_validate(base)


def test_model_dump_json_mode_matches_the_old_success_dict() -> None:
    resp = _response()
    dumped = resp.model_dump(mode="json")
    assert dumped == {
        "html": "<!doctype html><html></html>",
        "path": "/tmp/x/mockups.html",
        "summary": "0 stage(s), 0 table(s), 0 reference list(s), 0 persona view(s)",
        "gaps": [],
        "blocking_gaps": [],
    }
    assert "isError" not in dumped


def test_is_frozen() -> None:
    resp = _response()
    with pytest.raises(ValidationError):
        resp.html = "<other/>"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
