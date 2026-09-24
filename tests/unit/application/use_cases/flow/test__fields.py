"""Spec for app.application.use_cases.flow._fields."""

from __future__ import annotations

import pytest

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow._field_spec_in import FieldSpecIn
from app.application.use_cases.flow import _fields
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def test_require_app_id_passes_on_a_non_empty_id() -> None:
    _fields.require_app_id("A1")  # does not raise


def test_require_app_id_refuses_an_empty_id() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        _fields.require_app_id("")
    assert exc_info.value.code == "REFUSED"
    assert "no app selected" in exc_info.value.message


def test_raise_if_write_failed_does_nothing_when_every_bucket_is_empty() -> None:
    _fields.raise_if_write_failed(published=True, missing=(), stale=())  # no raise


def test_raise_if_write_failed_raises_verify_failed_naming_the_bucket() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(published=False, missing=("ghost",))
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['ghost']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


def test_raise_if_write_failed_names_every_non_empty_bucket_it_is_given() -> None:
    """The function has no idea which kwarg names mean "failure" -- that
    discipline belongs to each use case's own call site, which passes only its
    own failure buckets (never `verified`/`skipped`/`unchanged`/`cleared`)."""
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(published=False, missing=("a",), stale=("b",))
    assert "missing=['a']" in exc_info.value.message
    assert "stale=['b']" in exc_info.value.message


def test_raise_if_write_failed_ignores_an_empty_bucket_alongside_a_failing_one() -> (
    None
):
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(published=False, missing=("a",), stale=())
    assert "stale" not in exc_info.value.message


def test_raise_if_write_failed_folds_in_remediation_when_given() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(
            published=False, missing=("a",), remediation=("forge_set_required",)
        )
    assert "remediation=['forge_set_required']" in exc_info.value.message


def test_raise_if_write_failed_omits_remediation_when_not_given() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(published=False, missing=("a",))
    assert "remediation" not in exc_info.value.message


def test_raise_if_write_failed_folds_in_collateral_when_given() -> None:
    """A destructive write's own side effects (a deleted Permission, a moved
    field) must not be lost on the one path that never reaches the response
    DTO -- see `brief_d13_fix.md` fix 3."""
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(
            published=False,
            missing=("a",),
            collateral=("1 Permission node(s) deleted",),
        )
    assert "collateral=['1 Permission node(s) deleted']" in exc_info.value.message


def test_raise_if_write_failed_omits_collateral_when_not_given() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(published=False, missing=("a",))
    assert "collateral" not in exc_info.value.message


def test_raise_if_write_failed_collateral_alone_never_raises() -> None:
    """Collateral is documented, intended fallout, never itself a failure --
    only a non-empty output-invariant bucket triggers the raise."""
    _fields.raise_if_write_failed(
        published=True, missing=(), collateral=("1 Permission node(s) deleted",)
    )  # no raise


def test_raise_if_write_failed_names_what_it_left_on_the_tenant_when_given() -> None:
    """`brief_stage_d_common.md` review fix 6: a failed CREATE must name what
    it left on the tenant -- the id is not otherwise recoverable by the
    caller once this call raises instead of returning a response."""
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(
            published=False, missing=("a",), left_on_tenant="F1"
        )
    assert "left_on_tenant='F1'" in exc_info.value.message


def test_raise_if_write_failed_omits_left_on_tenant_when_not_given() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        _fields.raise_if_write_failed(published=False, missing=("a",))
    assert "left_on_tenant" not in exc_info.value.message


def test_field_spec_from_folds_default_value_into_options() -> None:
    spec = _fields.field_spec_from(
        FieldSpecIn(name="Count", type="Number", default_value=0)
    )
    assert spec == FieldSpec(
        name="Count", type=FieldType.NUMBER, options={"DefaultValue": 0}
    )


def test_field_spec_from_leaves_options_none_with_no_default_value() -> None:
    spec = _fields.field_spec_from(FieldSpecIn(name="A", type="Text"))
    assert spec.options is None


def _draft_with_one_field(**field_overrides: object) -> dict:
    field: dict[str, object] = {
        "Id": "Field_1",
        "Kind": "Field",
        "Name": "Ticket No",
        "Type": "Text",
        "Model": "M1",
        "Required": False,
    }
    field.update(field_overrides)
    return {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
        "Field_1": field,
    }


def test_changed_ignored_is_empty_for_a_brand_new_name() -> None:
    draft = _draft_with_one_field()
    got = _fields.changed_ignored(draft, [FieldSpec(name="Other", type=FieldType.TEXT)])
    assert got.entries == ()
    assert got.names == frozenset()


def test_changed_ignored_names_a_required_only_change() -> None:
    draft = _draft_with_one_field()
    got = _fields.changed_ignored(
        draft, [FieldSpec(name="Ticket No", type=FieldType.TEXT, required=True)]
    )
    assert got.names == {"Ticket No"}
    assert got.remediation == ("forge_set_required",)


def test_changed_ignored_names_a_type_change_with_delete_and_recreate_remediation() -> (
    None
):
    draft = _draft_with_one_field()
    got = _fields.changed_ignored(
        draft, [FieldSpec(name="Ticket No", type=FieldType.TEXTAREA)]
    )
    assert got.names == {"Ticket No"}
    assert got.remediation == ("forge_delete_fields", "forge_apply_fields")


def test_changed_ignored_is_empty_when_the_spec_matches_exactly() -> None:
    draft = _draft_with_one_field()
    got = _fields.changed_ignored(
        draft, [FieldSpec(name="Ticket No", type=FieldType.TEXT, required=False)]
    )
    assert got.names == frozenset()


def _placed_draft(section_name: str, start: int, end: int) -> dict:
    return {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
        "S1": {
            "Id": "S1",
            "Kind": "Column",
            "Type": "Section",
            "Name": section_name,
            "Column::Row": ["R1"],
        },
        "R1": {"Id": "R1", "Kind": "Row", "Row::Column": ["C1"]},
        "C1": {
            "Id": "C1",
            "Kind": "Column",
            "Type": "Text",
            "Start": start,
            "End": end,
        },
        "Field_1": {
            "Id": "Field_1",
            "Kind": "Field",
            "Name": "Ticket No",
            "Type": "Text",
            "Model": "M1",
            "Column": "C1",
        },
    }


def test_layout_collateral_is_empty_when_nothing_moved() -> None:
    draft = _placed_draft("Case Info", 0, 3)
    assert _fields.layout_collateral(draft, draft) == ()


def test_layout_collateral_names_a_field_that_moved() -> None:
    before = _placed_draft("Case Info", 0, 3)
    after = _placed_draft("Case Info", 3, 6)
    got = _fields.layout_collateral(before, after)
    assert len(got) == 1
    assert "Ticket No" in got[0] and "moved" in got[0]


def test_layout_collateral_exclude_suppresses_a_named_field() -> None:
    before = _placed_draft("Case Info", 0, 3)
    after = _placed_draft("Case Info", 3, 6)
    got = _fields.layout_collateral(before, after, exclude=("Ticket No",))
    assert got == ()


def test_section_field_names_returns_empty_for_an_unknown_section() -> None:
    draft = _draft_with_one_field()
    assert _fields.section_field_names(draft, "Nope") == ()


def test_section_field_names_walks_row_then_column_order() -> None:
    draft: dict[str, object] = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
        "S1": {
            "Id": "S1",
            "Kind": "Column",
            "Type": "Section",
            "Name": "Case Info",
            "Column::Row": ["R1"],
        },
        "R1": {"Id": "R1", "Kind": "Row", "Row::Column": ["C1", "C2"]},
        "C1": {"Id": "C1", "Kind": "Column", "Type": "Text"},
        "C2": {"Id": "C2", "Kind": "Column", "Type": "Text"},
        "F1": {"Id": "F1", "Kind": "Field", "Name": "First", "Column": "C1"},
        "F2": {"Id": "F2", "Kind": "Field", "Name": "Second", "Column": "C2"},
    }
    assert _fields.section_field_names(draft, "Case Info") == ("First", "Second")


def test_live_names_splits_fields_from_table_hosts() -> None:
    draft: dict[str, object] = {
        "F1": {"Id": "F1", "Kind": "Field", "Name": "A"},
        "T1": {"Id": "T1", "Kind": "Column", "Type": "Model", "Name": "Items"},
    }
    fields, tables = _fields.live_names(draft)
    assert fields == {"A"}
    assert tables == {"Items"}


def test_root_field_nodes_only_returns_fields_on_the_root_model() -> None:
    draft: dict[str, object] = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model"},
        "M2": {"Id": "M2", "Kind": "Model"},
        "F1": {"Id": "F1", "Kind": "Field", "Name": "Root Field", "Model": "M1"},
        "F2": {"Id": "F2", "Kind": "Field", "Name": "Child Field", "Model": "M2"},
    }
    got = _fields.root_field_nodes(draft)
    assert set(got) == {"Root Field"}


def test_unsatisfiable_required_fields_flags_computed_and_sequence_number() -> None:
    root_fields = {
        "Computed": {"Field::Expression": ["E1"]},
        "Seq": {"Type": "SequenceNumber"},
        "Plain": {"Type": "Text"},
    }
    got = _fields.unsatisfiable_required_fields(
        root_fields, {"Computed", "Seq", "Plain"}
    )
    assert got == ["Computed (computed)", "Seq (SequenceNumber)"]


def test_cleared_required_fields_names_a_field_dropped_from_the_set() -> None:
    root_fields = {
        "A": {"Required": True},
        "B": {"Required": False},
    }
    assert _fields.cleared_required_fields(root_fields, {"B"}) == ("A",)


def test_audit_required_readback_unions_live_and_requested_names() -> None:
    live = {"A": {"Required": True}}
    verified, missing = _fields.audit_required_readback(live, {"A", "B"})
    assert verified == ("A",)
    assert missing == ("B",)


def test_flow_draft_round_trip_still_produces_a_plain_dict_for_these_helpers() -> None:
    """Sanity: `FlowDraft.to_wire()` (the only legal way to read an entity's graph
    from outside the domain) produces exactly the dict shape every helper above
    expects."""
    draft = FlowDraft.from_wire(_draft_with_one_field())
    assert _fields.root_field_nodes(draft.to_wire())
