"""Unit tests for app.domain.value_objects.field_spec.

FieldSpec/FlowRef/ParsedField/Diff are frozen dataclasses -- plain data, no behavior.
These tests pin their fields, defaults, and frozen-ness. Pure + offline: no network,
no Kissflow calls.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.domain.value_objects.field_spec import Diff, FieldSpec, FlowRef, ParsedField
from app.domain.value_objects.field_type import FieldType, FlowType


def test_field_spec_defaults() -> None:
    spec = FieldSpec(name="Urgency", type=FieldType.SELECT)
    assert spec.name == "Urgency"
    assert spec.type is FieldType.SELECT
    assert spec.required is False
    assert spec.referred_list is None
    assert spec.field_id is None
    assert spec.options is None


def test_field_spec_every_field_set() -> None:
    spec = FieldSpec(
        name="Urgency",
        type=FieldType.SELECT,
        required=True,
        referred_list="Urgency Levels",
        field_id="Field_abc123",
        options={"DefaultValue": "Low"},
    )
    assert spec.required is True
    assert spec.referred_list == "Urgency Levels"
    assert spec.field_id == "Field_abc123"
    assert spec.options == {"DefaultValue": "Low"}


def test_field_spec_is_frozen() -> None:
    spec = FieldSpec(name="Urgency", type=FieldType.SELECT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "Changed"  # ty: ignore[invalid-assignment]


def test_flow_ref_fields() -> None:
    ref = FlowRef(
        account="acct1", app_id="App1", flow_id="Flow1", flow_type=FlowType.PROCESS
    )
    assert ref.account == "acct1"
    assert ref.app_id == "App1"
    assert ref.flow_id == "Flow1"
    assert ref.flow_type is FlowType.PROCESS


def test_flow_ref_is_frozen() -> None:
    ref = FlowRef(
        account="acct1", app_id="App1", flow_id="Flow1", flow_type=FlowType.PROCESS
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.account = "other"  # ty: ignore[invalid-assignment]


def test_parsed_field_fields() -> None:
    pf = ParsedField(
        field_id="Field_abc",
        name="Urgency",
        type=FieldType.SELECT,
        required=True,
        column_id="Column_xyz",
    )
    assert pf.field_id == "Field_abc"
    assert pf.name == "Urgency"
    assert pf.type is FieldType.SELECT
    assert pf.required is True
    assert pf.column_id == "Column_xyz"


def test_parsed_field_column_id_may_be_none() -> None:
    pf = ParsedField(
        field_id="Field_abc",
        name="Urgency",
        type=FieldType.SELECT,
        required=False,
        column_id=None,
    )
    assert pf.column_id is None


def test_diff_fields_and_human_readable() -> None:
    add = FieldSpec(name="Urgency", type=FieldType.SELECT)
    edit = FieldSpec(name="Notes", type=FieldType.TEXTAREA, field_id="Field_notes")
    diff = Diff(
        adds=(add,),
        edits=(edit,),
        skipped=("Ticket No",),
        human_readable="+ add field 'Urgency'",
    )
    assert diff.adds == (add,)
    assert diff.edits == (edit,)
    assert diff.skipped == ("Ticket No",)
    assert diff.human_readable == "+ add field 'Urgency'"


def test_diff_is_frozen() -> None:
    diff = Diff(adds=(), edits=(), skipped=(), human_readable="(no changes)")
    with pytest.raises(dataclasses.FrozenInstanceError):
        diff.human_readable = "changed"  # ty: ignore[invalid-assignment]
