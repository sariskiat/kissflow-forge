"""Tests for `FieldChangeIn`, the `kf_plan_field_change` element shape."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.intake._field_change_in import FieldChangeIn
from app.domain.value_objects.field_type import FieldType


def test_minimal_field_defaults() -> None:
    entry = FieldChangeIn(name="Notes", type="Text")
    assert entry.type is FieldType.TEXT
    assert entry.required is False
    assert entry.referred_list is None
    assert entry.field_id is None
    assert entry.options is None
    assert entry.default_value is None


def test_rejects_a_blank_name() -> None:
    with pytest.raises(ValidationError, match="name must not be blank"):
        FieldChangeIn(name="   ", type="Text")


def test_rejects_a_type_this_engine_cannot_build() -> None:
    """The old bare-dict `kf_plan_field_change`'s own refusal text (ported from
    `app.application.tools._field_type`): the type, the closed valid set,
    `kf_list_field_types`, `forge_capabilities`, and ADR-0004."""
    with pytest.raises(ValidationError, match="Nope") as exc_info:
        FieldChangeIn(name="x", type="Nope")
    message = str(exc_info.value)
    assert "is not a field type this engine can build" in message
    assert "kf_list_field_types" in message
    assert "forge_capabilities" in message
    assert "ADR-0004" in message


def test_required_null_is_false() -> None:
    """The old `_to_spec` used `bool(d.get("required", False))`, under which an
    explicit `required: null` read as False, same as omitting the key."""
    entry = FieldChangeIn.model_validate(
        {"name": "x", "type": "Text", "required": None}
    )
    assert entry.required is False
