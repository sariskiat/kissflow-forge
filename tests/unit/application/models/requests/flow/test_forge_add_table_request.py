"""`ForgeAddTableRequest`: shape validation replacing
`tools.coerce_table_columns` (pre-refactor) with Pydantic types and
validators -- the same bad inputs now fail with `ValidationError`."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_add_table_request import (
    ForgeAddTableRequest,
)


def _request(**overrides: Any) -> ForgeAddTableRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "name": "Rounds",
        "columns": [["Round", "Number"], ["Notes", "Text", {"Decimalpoint": 0}]],
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeAddTableRequest(**fields)


def test_accepts_two_and_three_element_columns() -> None:
    req = _request()
    assert req.columns == [("Round", "Number"), ("Notes", "Text", {"Decimalpoint": 0})]


def test_defaults_match_the_old_tool_parameters() -> None:
    req = _request()
    assert req.max_rows is None
    assert req.allow_import is False
    assert req.kind == "process"
    assert req.publish is False
    assert req.after_section is None


def test_every_field_is_settable() -> None:
    req = _request(
        max_rows=5,
        allow_import=True,
        kind="form",
        publish=True,
        after_section="Banner",
    )
    assert req.max_rows == 5
    assert req.allow_import is True
    assert req.kind == "form"
    assert req.publish is True
    assert req.after_section == "Banner"


def test_rejects_a_non_list_columns() -> None:
    with pytest.raises(ValidationError):
        _request(columns={"Round": "Number"})


def test_rejects_a_column_entry_that_is_too_short() -> None:
    with pytest.raises(ValidationError):
        _request(columns=[["Round"]])


def test_rejects_a_column_entry_that_is_too_long() -> None:
    with pytest.raises(ValidationError):
        _request(columns=[["Round", "Number", {}, "extra"]])


def test_rejects_a_non_string_column_type() -> None:
    with pytest.raises(ValidationError):
        _request(columns=[["Round", 5]])


def test_rejects_a_non_dict_options() -> None:
    with pytest.raises(ValidationError):
        _request(columns=[["Round", "Number", "not a dict"]])


def test_rejects_a_blank_column_name() -> None:
    with pytest.raises(ValidationError, match="column name"):
        _request(columns=[["   ", "Number"]])


def test_blank_column_name_message_matches_the_old_coerce_table_columns_text() -> None:
    """`tools.coerce_table_columns` raised this same condition through the
    shared `_shape_error` helper (brief_d13_fix.md fix 5): `columns[0][0]:
    expected a column name, got str '   ' — correct shape: [...]`. The
    DTO's own validator must render the identical text, not a rewritten
    message."""
    columns_example = '[["Item", "Text"], ["Qty", "Number", {"Decimalpoint": 0}]]'
    with pytest.raises(ValidationError) as exc_info:
        _request(columns=[["   ", "Number"]])
    assert (
        f"columns[0][0]: expected a column name, got str '   ' — "
        f"correct shape: {columns_example}" in str(exc_info.value)
    )


def test_rejects_an_unknown_column_type() -> None:
    """`brief_stage_d_common.md` review fix 3: `tools.coerce_table_columns`
    refused an unknown column type at the boundary; a bare `tuple[str, str]`
    accepts any string and lets it through to the offline `add_table`
    write path instead."""
    with pytest.raises(ValidationError, match="is not a field type"):
        _request(columns=[["Round", "Foo"]])


def test_unknown_column_type_message_matches_the_old_field_type_helper() -> None:
    """Renders `app.application.tools._field_type`'s own text with the same
    values and compares, per lesson 16: do not compare by reading."""
    from app.domain.value_objects.field_type import FieldType

    value = "Foo"
    param = "columns[0][1]"
    old = (
        f"{param}: {value!r} is not a field type this engine can build — "
        f"valid: {[t.value for t in FieldType]} (kf_list_field_types). The "
        f"platform's own field palette is wider; what is captured of it is "
        f"in forge_capabilities, and a type outside the list above is "
        f"refused here rather than guessed at (ADR-0004)."
    )
    with pytest.raises(ValidationError) as exc_info:
        _request(columns=[["Round", value]])
    assert old in str(exc_info.value)


def test_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        _request(kind="dataset")


def test_rejects_an_extra_field() -> None:
    with pytest.raises(ValidationError):
        _request(unexpected="x")
