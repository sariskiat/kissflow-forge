"""`ForgeAddFieldValidationRequest`: shape validation replacing
`tools.coerce_validation_rules` (pre-refactor) -- a plain `dict[str,
list[tuple[str, str]]]` field type already rejects the same bad inputs with
a Pydantic `ValidationError`, no custom validator needed."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_add_field_validation_request import (
    ForgeAddFieldValidationRequest,
)


def _request(**overrides: Any) -> ForgeAddFieldValidationRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "rules": {"meeting link": [["CONTAINS", "microsoft"]]},
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeAddFieldValidationRequest(**fields)


def test_accepts_multiple_rules_on_one_field() -> None:
    req = _request(rules={"Notes": [["CONTAINS", "important"], ["MAX_LENGTH", "200"]]})
    assert req.rules == {"Notes": [("CONTAINS", "important"), ("MAX_LENGTH", "200")]}


def test_defaults_match_the_old_tool_parameters() -> None:
    req = _request()
    assert req.kind == "process"
    assert req.publish is False


def test_rejects_a_non_dict_rules() -> None:
    with pytest.raises(ValidationError):
        _request(rules=["CONTAINS", "microsoft"])


def test_rejects_a_field_whose_rules_are_not_a_list() -> None:
    with pytest.raises(ValidationError):
        _request(rules={"Notes": "CONTAINS"})


def test_rejects_a_rule_that_is_not_a_pair() -> None:
    with pytest.raises(ValidationError):
        _request(rules={"Notes": [["CONTAINS"]]})


def test_rejects_a_rule_with_a_non_string_element() -> None:
    with pytest.raises(ValidationError):
        _request(rules={"Notes": [["CONTAINS", 5]]})


def test_rejects_an_extra_field() -> None:
    with pytest.raises(ValidationError):
        _request(unexpected="x")


def test_wrong_length_rule_message_matches_the_old_coerce_validation_rules_text() -> (
    None
):
    """`brief_stage_d_common.md` review fix 5: `tools.coerce_validation_rules`
    rendered `rules['f'][0]: expected an [operator, value] pair, got list
    ['CONTAINS'] — correct shape: ...` through `_shape_error`; a plain
    `tuple[str, str]` field type instead raises Pydantic's own generic
    "too_long"/"missing" text, naming neither the correct shape nor the
    engine's own vocabulary."""
    example = '{"meeting link": [["CONTAINS", "microsoft"]]}'
    old = (
        "rules['f'][0]: expected an [operator, value] pair, got list "
        f"['CONTAINS'] — correct shape: {example}"
    )
    with pytest.raises(ValidationError) as exc_info:
        _request(rules={"f": [["CONTAINS"]]})
    assert old in str(exc_info.value)
