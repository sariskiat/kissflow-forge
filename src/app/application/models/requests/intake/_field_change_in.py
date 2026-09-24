"""app.application.models.requests.intake._field_change_in -- one requested field,
the element shape of the `changes` parameter on `kf_plan_field_change`.

Replaces `app.application.tools.coerce_field_specs`/`_to_spec` for this tool:
Pydantic validates `type` against the closed `FieldType` enum and `options` as
an object, the same shape checks the old hand-written coercer ran. The
`required: null` and "unknown field type" rules are NOT a private copy of
`app.application.models.requests.flow._field_spec_in.FieldSpecIn`'s own
validators (the flow family's own `kf_apply_field_change`/`forge_apply_fields`
DTO) -- both DTOs import the one shared copy in `..._field_rules` instead
(`brief_stage_d_common.md`: "keep ONE copy of each rule"), so the intake
family still imports no other family's private module (lesson 11), while the
rule text itself never drifts between the two DTOs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.application.models.requests._field_rules import (
    required_none_is_false,
    type_is_known,
)
from app.domain.value_objects.field_type import FieldType


class FieldChangeIn(BaseModel):
    """One requested field for `kf_plan_field_change`'s `changes` list.

    `field_id` is always `None` in practice: this preview only ever
    describes ADDING a field, never editing one by id.
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

        Args:
            value: The raw `name` field.

        Returns:
            `value`, unchanged.

        Raises:
            ValueError: `value` is empty or all whitespace.
        """
        if not value.strip():
            raise ValueError("name must not be blank")
        return value
