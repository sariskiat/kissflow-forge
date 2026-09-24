"""Tests for `app.application.models.requests._field_rules`, the two field-shape
rules shared by `flow._field_spec_in.FieldSpecIn` and `intake._field_change_in.
FieldChangeIn`."""

from __future__ import annotations

import pytest

from app.application.models.requests._field_rules import (
    required_none_is_false,
    type_is_known,
)
from app.domain.value_objects.field_type import FieldType


def test_required_none_is_false_turns_none_into_false() -> None:
    assert required_none_is_false(None) is False


@pytest.mark.parametrize("value", [True, False, "false", "true", "x"])
def test_required_none_is_false_passes_through_anything_else(value: object) -> None:
    assert required_none_is_false(value) is value


def test_type_is_known_passes_through_a_known_type() -> None:
    assert type_is_known("Text") == "Text"


def test_type_is_known_rejects_an_unknown_type() -> None:
    with pytest.raises(ValueError, match="is not a field type this engine can build"):
        type_is_known("Nope")


def test_type_is_known_message_matches_the_old_field_type_helper_byte_for_byte() -> (
    None
):
    """`app.application.tools._field_type` rendered this exact text with an
    em dash, never a double hyphen. Render the old f-string with the same
    values and compare (brief_stage_d_common lesson 16): do not compare by
    reading."""
    value = "Nope"
    old = (
        f"type: {value!r} is not a field type this engine can build — "
        f"valid: {[t.value for t in FieldType]} (kf_list_field_types). The "
        f"platform's own field palette is wider; what is captured of it is "
        f"in forge_capabilities, and a type outside the list above is "
        f"refused here rather than guessed at (ADR-0004)."
    )
    with pytest.raises(ValueError) as exc_info:
        type_is_known(value)
    assert str(exc_info.value) == old
