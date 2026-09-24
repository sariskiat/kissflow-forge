"""app.application.models.requests.flow._field_spec_in — one requested field, the
element shape of the `changes` parameter on `kf_apply_field_change` and the `fields`
parameter on `forge_apply_fields`.

Replaces `app.application.tools.coerce_field_specs`/`_to_spec` for this group's two
tools: Pydantic validates `type` against the closed `FieldType` enum and `options` as
an object, the same shape checks the old hand-written coercer ran. `default_value`
folds into `options["DefaultValue"]` on conversion to a domain `FieldSpec`
(`app.application.use_cases.flow._fields._field_spec_from`), exactly as the old
`_to_spec` did.

The `required: null` and "unknown field type" rules live in `_field_rules` (one
copy shared with `intake._field_change_in.FieldChangeIn`, the other "one
requested field" DTO).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.application.models.requests._field_rules import (
    required_none_is_false,
    type_is_known,
)
from app.domain.value_objects.field_type import FieldType

_FIELD_EXAMPLE = '[{"name": "Ticket No", "type": "Text", "required": true}]'


def _brief(value: Any, limit: int = 120) -> str:
    """A repr short enough to belong in an error message.

    Ports `app.application.tools._brief` verbatim: an agent that passed a
    huge value does not need it echoed back in full to see what was wrong.

    Args:
        value: The value to render.
        limit: The character cap before truncation.

    Returns:
        `repr(value)`, truncated with an ellipsis past `limit` characters.
    """
    s = repr(value)
    return s if len(s) <= limit else s[:limit] + "…"


class FieldSpecIn(BaseModel):
    """One requested field.

    `field_id` is always `None` in practice: this engine's live write path only
    ever creates fields (`FlowDraft.apply_changes`), never edits one by id.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    type: FieldType
    required: bool = False
    referred_list: str | None = None
    field_id: str | None = None
    options: dict[str, Any] | None = None
    default_value: Any | None = None

    _required_none_is_false = field_validator("required", mode="before")(
        required_none_is_false
    )
    _type_is_known = field_validator("type", mode="before")(type_is_known)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        """Refuse a blank name, the same rule `coerce_field_specs` used to run.

        Ports `app.application.tools.coerce_field_specs`'s own `_shape_error`
        text verbatim (`brief_stage_d_common.md` review, fix 5): the bare
        `"name must not be blank"` this validator used to raise named
        neither the value it rejected nor the correct shape.

        Args:
            value: The raw `name` field.

        Returns:
            `value`, unchanged.

        Raises:
            ValueError: `value` is empty or all whitespace.
        """
        if not value.strip():
            raise ValueError(
                f"name: expected a non-empty field name, got "
                f"{type(value).__name__} {_brief(value)} — correct shape: "
                f"{_FIELD_EXAMPLE}"
            )
        return value
