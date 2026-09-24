"""`ForgeSetStylesRequest`: shape only -- `tools.py` never had a
`coerce_styles` helper (pre-refactor); a style's own legal shape is a domain
business invariant checked by `FlowDraft.set_section_style`."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_set_styles_request import (
    ForgeSetStylesRequest,
)


def _request(**overrides: Any) -> ForgeSetStylesRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "styles": {"M": {"Section.Bg.Color": "Color.Info.300"}},
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeSetStylesRequest(**fields)


def test_defaults_match_the_old_tool_parameters() -> None:
    req = _request()
    assert req.kind == "process"
    assert req.publish is False
    assert req.root_style is None
    assert req.hint_text_position is None


def test_every_field_is_settable() -> None:
    req = _request(
        kind="form",
        publish=True,
        root_style={"Form.Field.Color": "Color.Primary.500"},
        hint_text_position="Icon",
    )
    assert req.kind == "form"
    assert req.publish is True
    assert req.root_style == {"Form.Field.Color": "Color.Primary.500"}
    assert req.hint_text_position == "Icon"


def test_rejects_a_non_dict_styles() -> None:
    with pytest.raises(ValidationError):
        _request(styles=["M"])


def test_rejects_a_section_whose_style_is_not_a_dict() -> None:
    with pytest.raises(ValidationError):
        _request(styles={"M": "Color.Info.300"})


def test_rejects_an_extra_field() -> None:
    with pytest.raises(ValidationError):
        _request(unexpected="x")
