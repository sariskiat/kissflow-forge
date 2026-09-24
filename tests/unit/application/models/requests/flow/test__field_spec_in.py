"""Spec for app.application.models.requests.flow._field_spec_in."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow._field_spec_in import FieldSpecIn
from app.domain.value_objects.field_type import FieldType


def test_constructs_from_the_minimal_shape() -> None:
    spec = FieldSpecIn(name="Ticket No", type="Text")
    assert spec.name == "Ticket No"
    assert spec.type is FieldType.TEXT
    assert spec.required is False
    assert spec.referred_list is None
    assert spec.field_id is None
    assert spec.options is None
    assert spec.default_value is None


def test_required_and_options_and_referred_list_round_trip() -> None:
    spec = FieldSpecIn(
        name="Region",
        type="Select",
        required=True,
        referred_list="List_1",
        options={"AllowFormatting": True},
    )
    assert spec.required is True
    assert spec.referred_list == "List_1"
    assert spec.options == {"AllowFormatting": True}


def test_required_true_stays_true() -> None:
    spec = FieldSpecIn(name="Region", type="Select", required=True)
    assert spec.required is True


def test_required_string_false_is_false() -> None:
    """Pydantic's own lenient bool parsing, not the old buggy `bool("false")`
    (which read any non-empty string as True)."""
    spec = FieldSpecIn.model_validate(
        {"name": "A", "type": "Text", "required": "false"}
    )
    assert spec.required is False


def test_required_null_is_false() -> None:
    """The old `_to_spec` used `bool(d.get("required", False))`, under which an
    explicit `required: null` read as False, same as omitting the key."""
    spec = FieldSpecIn.model_validate({"name": "A", "type": "Text", "required": None})
    assert spec.required is False


def test_default_value_is_carried_separately_from_options() -> None:
    """Folding `default_value` into `options["DefaultValue"]` is the USE CASE's job
    (`_field_spec_from`), not this DTO's -- see its own module docstring."""
    spec = FieldSpecIn(name="Count", type="Number", default_value=0)
    assert spec.default_value == 0
    assert spec.options is None


def test_rejects_a_blank_name() -> None:
    with pytest.raises(ValidationError, match="expected a non-empty field name"):
        FieldSpecIn(name="   ", type="Text")


def test_blank_name_message_matches_the_old_shape_error_byte_for_byte() -> None:
    """`app.application.tools.coerce_field_specs` rendered this exact text via
    `_shape_error` (brief_stage_d_common.md review, fix 5). Render the old
    f-string with the same values and compare, per lesson 16: do not compare
    by reading."""
    value = "  "
    example = '[{"name": "Ticket No", "type": "Text", "required": true}]'
    old = (
        f"name: expected a non-empty field name, got {type(value).__name__} "
        f"{value!r} — correct shape: {example}"
    )
    with pytest.raises(ValidationError) as exc_info:
        FieldSpecIn(name=value, type="Text")
    assert old in str(exc_info.value)


def test_rejects_a_type_this_engine_does_not_know() -> None:
    with pytest.raises(ValidationError):
        FieldSpecIn(name="Ticket No", type="RichText")


def test_the_bad_type_message_names_where_the_real_palette_lives() -> None:
    """Restores the old `app.application.tools._field_type` refusal text
    (brief_d13_fix.md fix 6): a bare `FieldType(value)` `ValueError` names
    none of `kf_list_field_types`, `forge_capabilities` or ADR-0004."""
    with pytest.raises(ValidationError, match="RichText") as exc_info:
        FieldSpecIn(name="Ticket No", type="RichText")
    message = str(exc_info.value)
    assert "kf_list_field_types" in message
    assert "forge_capabilities" in message
    assert "ADR-0004" in message


def test_bad_type_message_matches_the_old_field_type_helper_byte_for_byte() -> None:
    """`app.application.tools._field_type` rendered this exact text with an
    em dash, never a double hyphen (brief_d13_fix.md fix 5). Render the old
    f-string with the same values and compare, per lesson 16: do not compare
    by reading."""
    value = "RichText"
    param = "type"
    old = (
        f"{param}: {value!r} is not a field type this engine can build — "
        f"valid: {[t.value for t in FieldType]} (kf_list_field_types). The "
        f"platform's own field palette is wider; what is captured of it is "
        f"in forge_capabilities, and a type outside the list above is "
        f"refused here rather than guessed at (ADR-0004)."
    )
    with pytest.raises(ValidationError) as exc_info:
        FieldSpecIn(name="Ticket No", type=value)
    assert old in str(exc_info.value)


def test_rejects_options_that_are_not_an_object() -> None:
    with pytest.raises(ValidationError):
        FieldSpecIn.model_validate({"name": "A", "type": "Text", "options": "nope"})


def test_rejects_a_missing_name() -> None:
    with pytest.raises(ValidationError):
        FieldSpecIn.model_validate({"type": "Text"})


def test_rejects_a_missing_type() -> None:
    with pytest.raises(ValidationError):
        FieldSpecIn.model_validate({"name": "A"})


def test_is_frozen() -> None:
    spec = FieldSpecIn(name="A", type="Text")
    with pytest.raises(ValidationError):
        spec.name = "B"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
