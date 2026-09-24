"""app.application.models.requests._field_rules -- the two field-shape rules
shared by every "one requested field" DTO: `flow._field_spec_in.FieldSpecIn`
(`kf_apply_field_change`/`forge_apply_fields`) and `intake._field_change_in.
FieldChangeIn` (`kf_plan_field_change`). Both describe the same wire shape, so
the "required: null means unset" rule and the "unknown field type" refusal
text live in ONE module both import (brief_stage_d_common.md: "keep ONE copy
of each rule"), rather than a second copy drifting off the first.
"""

from __future__ import annotations

from typing import Any

from app.domain.value_objects.field_type import FieldType


def required_none_is_false(value: Any) -> Any:
    """Treat an explicit `null` as unset, the same as omitting the key.

    The old `_to_spec` used `bool(d.get("required", False))`, under which a
    `required: null` field read as `False`. Pydantic's own lenient `bool`
    parsing already turns a wire string like `"false"` into `False` (unlike
    the old `bool("false")`, which read any non-empty string as `True` --
    a bug this DTO does not repeat), so only `None` needs handling here.

    Args:
        value: The raw `required` field, before Pydantic's own `bool`
            coercion runs.

    Returns:
        `False` when `value` is `None`, else `value` unchanged.
    """
    if value is None:
        return False
    return value


def type_is_known(value: Any) -> Any:
    """Refuse a field type this engine cannot build, named clearly.

    Ports `app.application.tools._field_type`'s own message: the bare
    `FieldType` enum's own `ValueError` says nothing about which
    parameter failed or where the wider platform palette is documented.

    Args:
        value: The raw `type` field, before Pydantic's own `FieldType`
            coercion runs.

    Returns:
        `value`, unchanged -- Pydantic's own `FieldType` coercion still
        runs on it afterwards.

    Raises:
        ValueError: `value` is not one of `FieldType`'s members.
    """
    try:
        FieldType(value)
    except ValueError:
        raise ValueError(
            f"type: {value!r} is not a field type this engine can build "
            f"— valid: {[t.value for t in FieldType]} (kf_list_field_types). "
            "The platform's own field palette is wider; what is captured "
            "of it is in forge_capabilities, and a type outside the list "
            "above is refused here rather than guessed at (ADR-0004)."
        ) from None
    return value
