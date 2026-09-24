"""Tests for `app.application.use_cases.intake._field_change.to_field_spec`,
ported from `app.application.tools._to_spec`'s own coverage (folded into
`test_tools.py`'s `plan_field_change` tests -- there was no direct unit test
of `_to_spec` itself; this is new coverage of the pure conversion).
"""

from __future__ import annotations

from app.application.models.requests.intake._field_change_in import FieldChangeIn
from app.application.use_cases.intake._field_change import to_field_spec
from app.domain.value_objects.field_type import FieldType


def test_minimal_entry_converts_with_no_options() -> None:
    spec = to_field_spec(FieldChangeIn(name="Notes", type="Text", required=True))
    assert spec.name == "Notes"
    assert spec.type is FieldType.TEXT
    assert spec.required is True
    assert spec.options is None


def test_default_value_folds_into_options() -> None:
    spec = to_field_spec(FieldChangeIn(name="Qty", type="Number", default_value=5))
    assert spec.options == {"DefaultValue": 5}


def test_default_value_merges_with_explicit_options() -> None:
    spec = to_field_spec(
        FieldChangeIn(
            name="Notes",
            type="Textarea",
            options={"AllowFormatting": "true"},
            default_value="hi",
        )
    )
    assert spec.options == {"AllowFormatting": "true", "DefaultValue": "hi"}


def test_referred_list_and_field_id_pass_through() -> None:
    spec = to_field_spec(
        FieldChangeIn(
            name="Urgency", type="Select", referred_list="L1", field_id="Field_1"
        )
    )
    assert spec.referred_list == "L1"
    assert spec.field_id == "Field_1"
