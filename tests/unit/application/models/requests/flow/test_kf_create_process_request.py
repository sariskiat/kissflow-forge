"""`KfCreateProcessRequest`, whose `fields` are `_field_spec_in.FieldSpecIn`
(`brief_stage_d_common.md` review, fix 4) -- see
`tests/unit/application/models/requests/flow/test__field_spec_in.py` for
`FieldSpecIn`'s own unit tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow._field_spec_in import FieldSpecIn
from app.application.models.requests.flow.kf_create_process_request import (
    KfCreateProcessRequest,
)
from app.application.use_cases.flow._fields import field_spec_from
from app.domain.value_objects.field_type import FieldType


def test_round_trips_every_field() -> None:
    req = KfCreateProcessRequest(
        name="Expense Approval",
        steps=["Draft"],
        fields=[{"name": "Ticket No", "type": "Text", "required": True}],
        publish=True,
        from_template=False,
        app_id="A1",
    )
    dumped = req.model_dump(mode="json")
    assert dumped["name"] == "Expense Approval"
    assert dumped["steps"] == ["Draft"]
    assert dumped["fields"][0]["name"] == "Ticket No"
    assert dumped["fields"][0]["type"] == "Text"
    assert dumped["publish"] is True
    assert dumped["from_template"] is False
    assert dumped["app_id"] == "A1"


def test_publish_and_from_template_default() -> None:
    req = KfCreateProcessRequest(name="N", steps=[], fields=[], app_id="A1")
    assert req.publish is False
    assert req.from_template is True


def test_field_spec_input_refuses_a_blank_name() -> None:
    with pytest.raises(ValidationError):
        FieldSpecIn(name="", type="Text")


def test_field_spec_input_refuses_an_unknown_type() -> None:
    with pytest.raises(ValidationError):
        FieldSpecIn(name="X", type="NotARealType")


def test_field_spec_input_refuses_a_non_list_fields_shape() -> None:
    with pytest.raises(ValidationError):
        KfCreateProcessRequest(
            name="N",
            steps=[],
            fields={"name": "X", "type": "Text"},  # type: ignore
            app_id="A1",
        )


def test_field_spec_input_to_field_spec_folds_default_value_into_options() -> None:
    spec_in = FieldSpecIn(name="Priority", type=FieldType.SELECT, default_value="Low")
    spec = field_spec_from(spec_in)
    assert spec.name == "Priority"
    assert spec.type == FieldType.SELECT
    assert spec.options == {"DefaultValue": "Low"}


def test_required_null_is_false_same_as_kf_apply_field_change() -> None:
    """`brief_stage_d_common.md` review fix 4: the old bespoke `FieldSpecInput`
    treated an explicit `required: null` as a `ValidationError` (a bare
    `bool` field); `FieldSpecIn` treats it as `False`, same as
    `kf_apply_field_change`."""
    req = KfCreateProcessRequest.model_validate(
        {
            "name": "N",
            "steps": [],
            "fields": [{"name": "A", "type": "Text", "required": None}],
            "app_id": "A1",
        }
    )
    assert req.fields[0].required is False


def test_unknown_type_message_matches_kf_apply_field_change_s_own_text() -> None:
    """The bad-type refusal now carries the `kf_list_field_types`/
    `forge_capabilities`/ADR-0004 text every other flow DTO carries, not a
    bare Pydantic enum error naming none of them."""
    with pytest.raises(ValidationError) as exc_info:
        KfCreateProcessRequest(
            name="N", steps=[], fields=[{"name": "A", "type": "Foo"}], app_id="A1"
        )
    message = str(exc_info.value)
    assert "kf_list_field_types" in message
    assert "forge_capabilities" in message
    assert "ADR-0004" in message
