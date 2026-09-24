"""Direct unit tests for a representative sample of `app.domain.entities._flow_rules`.

The bulk of this private module's coverage is already indirect, through
`FlowDraft.problems()`'s own extensive tests in `test_flow_draft.py` (every
`_check_*` rule is exercised there, once clean and once per seeded defect).
This file adds direct tests for the small helpers that sit underneath that
orchestration: root validation, the table-name resolver, the malformed-
permission formatter, and the role-scoped-visibility check that never runs
through `doctor()`'s normal per-node walk.
"""

from __future__ import annotations

import pytest
from synthetic import synthetic_process_draft

from app.domain.entities._flow_rules import (
    DoctorReport,
    _check_required_fields,
    _check_role_scoped_visibility_claims,
    _check_step_stamps,
    _check_user_fields,
    _format_malformed_permissions,
    _nested_table_model_ids,
    _nodes,
    _owning_table_name,
    _validate_root,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_type import FieldType


def test_validate_root_returns_the_root_key() -> None:
    draft = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model"}}

    assert _validate_root(draft) == "M1"


def test_validate_root_raises_when_root_is_missing() -> None:
    with pytest.raises(ValueError, match="Root"):
        _validate_root({"not_a_flow": True})


def test_validate_root_raises_when_root_points_at_nothing() -> None:
    with pytest.raises(ValueError, match="Root"):
        _validate_root({"Root": "M1"})


def test_nodes_keeps_only_dict_values() -> None:
    draft = {"Field_1": {"Id": "Field_1", "Kind": "Field"}, "Root": "Field_1"}

    assert _nodes(draft) == {"Field_1": {"Id": "Field_1", "Kind": "Field"}}


def test_owning_table_name_none_for_a_root_field() -> None:
    nodes = {
        "Field_1": {"Id": "Field_1", "Kind": "Field", "Model": "M1"},
        "M1": {"Id": "M1", "Kind": "Model", "Name": "Root Form"},
    }

    assert _owning_table_name(nodes, nodes["Field_1"]) is None


def test_owning_table_name_reads_the_table_models_own_name() -> None:
    nodes = {
        "Field_1": {"Id": "Field_1", "Kind": "Field", "Model": "Table_1"},
        "Table_1": {
            "Id": "Table_1",
            "Kind": "Model",
            "Name": "Line Items",
            "Column": "Column_host",
        },
        "Column_host": {"Id": "Column_host", "Kind": "Column", "Name": "Line Items"},
    }

    assert _owning_table_name(nodes, nodes["Field_1"]) == "Line Items"


def test_owning_table_name_falls_back_to_the_host_column_name() -> None:
    nodes = {
        "Field_1": {"Id": "Field_1", "Kind": "Field", "Model": "Table_1"},
        "Table_1": {"Id": "Table_1", "Kind": "Model", "Column": "Column_host"},
        "Column_host": {"Id": "Column_host", "Kind": "Column", "Name": "Line Items"},
    }

    assert _owning_table_name(nodes, nodes["Field_1"]) == "Line Items"


def test_format_malformed_permissions_samples_at_most_five() -> None:
    ids = [f"Permission_{i}" for i in range(8)]

    msg = _format_malformed_permissions(ids)

    assert "8 Permission node(s)" in msg
    assert "..." in msg
    for shown in sorted(ids)[:5]:
        assert shown in msg


def test_format_malformed_permissions_no_ellipsis_under_the_sample_size() -> None:
    ids = ["Permission_1", "Permission_2"]

    msg = _format_malformed_permissions(ids)

    assert "2 Permission node(s)" in msg
    assert "..." not in msg


def test_check_role_scoped_visibility_claims_always_flags_every_claim() -> None:
    problems: list[str] = []
    checked: dict[str, int] = {}

    _check_role_scoped_visibility_claims(
        ("Managers see the Approve step",), problems, checked
    )

    assert checked["role_scoped_visibility_claims"] == 1
    assert len(problems) == 1
    assert "Managers see the Approve step" in problems[0]
    assert "API-impossible" in problems[0]


def test_check_role_scoped_visibility_claims_empty_is_clean() -> None:
    problems: list[str] = []
    checked: dict[str, int] = {}

    _check_role_scoped_visibility_claims((), problems, checked)

    assert checked["role_scoped_visibility_claims"] == 0
    assert problems == []


def test_doctor_skips_table_host_and_nested_model_but_checks_sections() -> None:
    """Table structure takes no Permission; ordinary Sections still need one."""
    draft = FlowDraft.from_wire(synthetic_process_draft()).add_table(
        "Checklist", [("Item", FieldType.TEXT), ("Complete", FieldType.BOOLEAN)]
    )
    wire = draft.to_wire()
    host_id = next(
        node_id
        for node_id, node in wire.items()
        if isinstance(node, dict)
        and node.get("Kind") == "Column"
        and node.get("Type") == "Model"
        and node.get("Name") == "Checklist"
    )
    nested_id = wire[host_id]["Column::Model"][0]
    wire[nested_id]["Name"] = "Nested Checklist Model"
    wire[nested_id]["Type"] = "Model"

    report = FlowDraft.from_wire(wire).problems()
    assert any("section 'Intake' is never editable" in p for p in report.problems)
    assert not any(
        "section 'Checklist' is never editable" in p for p in report.problems
    )


def test_nested_table_model_ids_accepts_either_live_link() -> None:
    nodes = {
        "Host_a": {
            "Id": "Host_a",
            "Kind": "Column",
            "Type": "Model",
            "Column::Model": ["Table_a"],
        },
        "Table_a": {"Id": "Table_a", "Kind": "Model"},
        "Host_b": {"Id": "Host_b", "Kind": "Column", "Type": "Model"},
        "Table_b": {
            "Id": "Table_b",
            "Kind": "Model",
            "Column": "Host_b",
        },
    }

    assert _nested_table_model_ids(nodes, frozenset({"Host_a", "Host_b"})) == {
        "Table_a",
        "Table_b",
    }


# --- G9 review: refusal-message word-glue regression tests ------------------------
#
# The E501 reflow that split these f-strings across lines dropped the trailing
# space at several implicit-concatenation boundaries. Each test below pins the
# exact rendered sentence -- with the space -- at every boundary this task repaired.


def test_check_step_stamps_message_reads_as_one_sentence() -> None:
    draft: dict = {}
    nodes = {
        "Prop_1": {
            "Id": "Prop_1",
            "Kind": "Property",
            "Name": "Step",
            "Value": "Activity_gone",
        },
    }
    problems: list[str] = []
    checked: dict[str, int] = {}

    _check_step_stamps(draft, nodes, problems, checked)

    assert len(problems) == 1
    assert "publish will 500 MetadataError" in problems[0]
    assert "rebuild via build_workflow, which now repoints by name" in problems[0]


class _StubLayout:
    def owner_section(self, _col_id: str | None) -> str:
        return "Section A"


def test_check_required_fields_message_reads_as_one_sentence() -> None:
    nodes = {
        "Field_1": {
            "Id": "Field_1",
            "Kind": "Field",
            "Model": "M1",
            "Name": "Reason",
            "Required": True,
            "Column": "Column_1",
        },
    }
    problems: list[str] = []
    checked: dict[str, int] = {}

    _check_required_fields("M1", nodes, _StubLayout(), {}, problems, checked)

    assert len(problems) == 1
    assert "never editable — that step cannot be submitted" in problems[0]


def test_check_user_fields_message_reads_as_one_sentence() -> None:
    nodes = {
        "Field_1": {"Id": "Field_1", "Kind": "Field", "Type": "User", "Name": "Owner"},
    }
    problems: list[str] = []
    checked: dict[str, int] = {}

    _check_user_fields(nodes, problems, checked)

    assert len(problems) == 1
    assert "QueryDefinition sibling — publish will fail" in problems[0]
    assert "(KISSFLOW_ERROR_04211, CLAUDE.md #59)" in problems[0]


def test_doctor_report_ok_reflects_whether_problems_is_empty() -> None:
    clean = DoctorReport(
        problems=(), checked={}, unvalidated=(), unvalidatable_scripts=0
    )
    dirty = DoctorReport(
        problems=("something broke",),
        checked={},
        unvalidated=(),
        unvalidatable_scripts=0,
    )

    assert clean.ok() is True
    assert dirty.ok() is False
