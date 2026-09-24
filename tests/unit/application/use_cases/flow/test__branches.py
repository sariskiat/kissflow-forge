"""`app.application.use_cases.flow._branches`: ported from `tests/test_client.py`'s
`_literals_for_field`/`_uncovered_options` coverage (spec G11, Stage D group
`d3_flow_workflow`)."""

from __future__ import annotations

from app.application.use_cases.flow._branches import (
    _literals_for_field,
    _uncovered_options,
)
from app.application.use_cases.flow._gates import _parallel_branches
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_process_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def _process_with_branches_and_field() -> tuple[dict, str, dict[str, str]]:
    draft = (
        FlowDraft.from_wire(_bare_process_draft())
        .build_workflow(
            [("Intake", None)],
            parallel=(
                "Route",
                [
                    ("Branch A", [("Shared Step", None)]),
                    ("Branch B", [("Shared Step", None)]),
                ],
            ),
            parallel_after=0,
        )
        .apply_changes(
            [
                FieldSpec(
                    name="Track", type=FieldType.SELECT, referred_list="List_Sample01"
                )
            ]
        )
    )
    wire = draft.to_wire()
    field_id = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Track"
    )
    branches = _parallel_branches(wire)
    return wire, field_id, branches


def test_literals_for_field_is_empty_with_no_condition_yet() -> None:
    wire, field_id, branches = _process_with_branches_and_field()
    assert _literals_for_field(wire, branches["Branch A"], field_id) == set()


def test_literals_for_field_reads_back_an_attached_condition() -> None:
    wire, field_id, branches = _process_with_branches_and_field()
    draft = FlowDraft.from_wire(wire).build_branch_condition(
        process_def_id=branches["Branch A"],
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    )
    got = _literals_for_field(draft.to_wire(), branches["Branch A"], field_id)
    assert got == {"Alpha"}


def test_uncovered_options_is_empty_when_nothing_is_enumerable() -> None:
    wire, field_id, branches = _process_with_branches_and_field()
    assert _uncovered_options(wire, branches.values(), field_id, None) == ()


def test_uncovered_options_names_every_option_no_branch_claims() -> None:
    wire, field_id, branches = _process_with_branches_and_field()
    assert _uncovered_options(wire, branches.values(), field_id, ["Alpha", "Beta"]) == (
        "Alpha",
        "Beta",
    )


def test_uncovered_options_excludes_a_covered_option() -> None:
    wire, field_id, branches = _process_with_branches_and_field()
    draft = FlowDraft.from_wire(wire).build_branch_condition(
        process_def_id=branches["Branch A"],
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    )
    got = _uncovered_options(
        draft.to_wire(), branches.values(), field_id, ["Alpha", "Beta"]
    )
    assert got == ("Beta",)
