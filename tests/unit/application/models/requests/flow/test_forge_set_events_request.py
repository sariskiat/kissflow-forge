"""`ForgeSetEventsRequest`: shape validation replacing `tools.coerce_events`
(pre-refactor) -- a plain `dict[str, list[tuple[str | None, str]]]` field
type already rejects the same bad inputs with a Pydantic `ValidationError`,
no custom validator needed."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_set_events_request import (
    ForgeSetEventsRequest,
)


def _request(**overrides: Any) -> ForgeSetEventsRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "events": {"Total": [[None, "kf.form.getField('Total')"]]},
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeSetEventsRequest(**fields)


def test_a_null_trigger_is_legal_and_means_derive_it() -> None:
    req = _request()
    assert req.events == {"Total": [(None, "kf.form.getField('Total')")]}


def test_a_stated_trigger_is_accepted() -> None:
    req = _request(events={"Note": [["onChange", "kf.x();"]]})
    assert req.events == {"Note": [("onChange", "kf.x();")]}


def test_defaults_match_the_old_tool_parameters() -> None:
    req = _request()
    assert req.kind == "process"
    assert req.publish is False


def test_rejects_a_non_dict_events() -> None:
    with pytest.raises(ValidationError):
        _request(events=["Total"])


def test_rejects_a_field_whose_events_are_not_a_list() -> None:
    with pytest.raises(ValidationError):
        _request(events={"Total": "onChange"})


def test_rejects_a_pair_that_is_not_exactly_trigger_and_script() -> None:
    with pytest.raises(ValidationError):
        _request(events={"Total": [["onChange"]]})


def test_rejects_a_non_string_non_null_trigger() -> None:
    with pytest.raises(ValidationError):
        _request(events={"Total": [[5, "kf.x();"]]})


def test_rejects_a_null_script() -> None:
    with pytest.raises(ValidationError):
        _request(events={"Total": [[None, None]]})


def test_rejects_an_extra_field() -> None:
    with pytest.raises(ValidationError):
        _request(unexpected="x")


def test_wrong_length_pair_message_matches_the_old_coerce_events_text() -> None:
    """`brief_stage_d_common.md` review fix 5: `tools.coerce_events` rendered
    `events['f'][0]: expected a [trigger, script] pair — pass null for the
    trigger to derive it...` through `_shape_error`."""
    example = '{"Total": [[null, "kf.form.getField(\'Total\')"]]}'
    old = (
        "events['f'][0]: expected a [trigger, script] pair — pass null for the "
        f"trigger to derive it from the field's live type, got list ['onChange'] "
        f"— correct shape: {example}"
    )
    with pytest.raises(ValidationError) as exc_info:
        _request(events={"f": [["onChange"]]})
    assert old in str(exc_info.value)


def test_null_script_message_matches_the_old_coerce_events_text() -> None:
    """`...[1]: expected the event script source...` -- the other half of fix 5."""
    example = '{"Total": [[null, "kf.form.getField(\'Total\')"]]}'
    old = (
        "events['f'][0][1]: expected the event script source, got NoneType "
        f"None — correct shape: {example}"
    )
    with pytest.raises(ValidationError) as exc_info:
        _request(events={"f": [[None, None]]})
    assert old in str(exc_info.value)
