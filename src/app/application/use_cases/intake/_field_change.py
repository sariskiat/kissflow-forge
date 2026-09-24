"""app.application.use_cases.intake._field_change -- `FieldChangeIn` -> the domain
`FieldSpec`, ported from `app.application.tools._to_spec`.
"""

from __future__ import annotations

from app.application.models.requests.intake._field_change_in import FieldChangeIn
from app.domain.value_objects.field_spec import FieldSpec


def to_field_spec(entry: FieldChangeIn) -> FieldSpec:
    """One `FieldChangeIn` -> the domain `FieldSpec` `plan_change` consumes.

    `default_value` (#55) folds into `options["DefaultValue"]` -- the SAME
    wire key `_TYPE_DEFAULTS` already writes for Number, and the platform's
    own relative-date keyword ("Today") for Date. Absent when not given, so
    an entry that never used it produces byte-identical `options` to before.

    Args:
        entry: One validated field-change entry.

    Returns:
        The equivalent domain `FieldSpec`.
    """
    options = dict(entry.options or {})
    if entry.default_value is not None:
        options["DefaultValue"] = entry.default_value
    return FieldSpec(
        name=entry.name,
        type=entry.type,
        required=entry.required,
        referred_list=entry.referred_list,
        field_id=entry.field_id,
        options=options or None,
    )
