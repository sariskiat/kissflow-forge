"""Offline audit rules for a flow's draft graph — kfforge.verify.doctor.

Every rule is exercised twice: once on a CLEAN synthetic draft (all 5 rules genuinely pass), and
once per seeded defect (one raw-dict mutation on a deep copy, one expected problem). No live
Kissflow calls, no real-app content — see tests/synthetic.py for how the clean draft (including
its goto loop and field event) is built.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest
from synthetic import OWNERS, synthetic_process_draft, with_goto_and_event

from kfforge.graph import add_sequence_number, progressive_matrix, set_step_permissions
from kfforge.verify import DoctorReport, doctor

Draft = dict[str, Any]


def _nodes_of(draft: Draft, **criteria: Any) -> list[dict[str, Any]]:
    """Every node dict matching all the given key=value criteria — a small lookup helper so each
    seeded-defect test can find the node it needs to mutate without repeating a manual scan."""
    return [v for v in draft.values()
            if isinstance(v, dict) and all(v.get(k) == val for k, val in criteria.items())]


def _section_column_ids(draft: Draft, section_name: str) -> set[str]:
    (sec,) = _nodes_of(draft, Type="Section", Name=section_name)
    return {c for rid in sec.get("Column::Row") or []
            for c in (draft.get(rid) or {}).get("Row::Column") or []}


@pytest.fixture(scope="module")
def clean_draft() -> Draft:
    """A fully-formed process draft that genuinely passes all 5 doctor rules: fields, sections, a
    3-way parallel workflow, a COMPLETE step-permission matrix — including the trailing section
    `synthetic.py` deliberately leaves unowned, given a real owner HERE via the engine's own
    `progressive_matrix` (not by weakening the never-editable rule) — plus one backward loop and
    one field event layered on top by `with_goto_and_event`.
    """
    draft = synthetic_process_draft()
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    matrix = progressive_matrix(draft, owners)
    permissioned = set_step_permissions(draft, matrix)
    return with_goto_and_event(permissioned)


# ---- the clean baseline ------------------------------------------------------

def test_clean_draft_has_no_problems(clean_draft: Draft) -> None:
    report = doctor(clean_draft)
    assert isinstance(report, DoctorReport)
    assert report.ok() is True
    assert report.problems == ()
    # deterministic given how the fixture itself is built, independent of synthetic.py's field
    # count: exactly one injected event, one injected goto, zero branch conditions anywhere
    assert report.checked["events"] == 1
    assert report.checked["gotos"] == 1
    assert report.checked["branch_literals"] == 0
    assert report.unvalidated == ()
    assert report.unvalidatable_scripts == 1  # that one event's script can never be FULLY proven
    # weak invariants: just confirm the other rules examined something real
    assert report.checked["sections"] > 0
    assert report.checked["required_fields"] > 0
    assert report.checked["dangling_refs"] > 0
    assert report.checked["permission_pairs"] > 0


def test_missing_root_key_fails_loud() -> None:
    with pytest.raises(ValueError, match="Root"):
        doctor({"not_a_flow": True})


# ---- 1. event scripts referencing a missing node -----------------------------

def test_event_script_missing_field_ref_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Script"] = event["Script"].replace("Field_SampleGate01", "Field_DoesNotExist99")

    report = doctor(d)
    assert any("Field_DoesNotExist99" in p for p in report.problems)


def test_event_script_missing_non_field_prefixed_ref_also_flagged(clean_draft: Draft) -> None:
    """The extraction must span every platform id prefix, not just Field_ — a script can just as
    easily reference a missing Column_/Activity_/... id (hardcode item 3 in the port)."""
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Script"] = event["Script"].replace("Field_SampleGate01", "Column_DoesNotExist99")

    report = doctor(d)
    assert any("Column_DoesNotExist99" in p for p in report.problems)


def test_unvalidatable_scripts_zero_when_no_scripts(clean_draft: Draft) -> None:
    """An event with an empty script has nothing to prove or disprove — it must not inflate the
    uncertainty count."""
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Script"] = ""

    report = doctor(d)
    assert report.unvalidatable_scripts == 0


# ---- 2. branch literal vs list options ---------------------------------------

def test_branch_literal_outside_options_flagged_else_unvalidated(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    root = d["Root"]
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    # a fresh Select field + branch condition, injected by raw dict surgery (no such branch
    # condition exists in the base synthetic draft to "break" — this test builds one from
    # scratch and shows both the flagged and the honestly-unvalidated outcome)
    d["Field_SvcSample01"] = {
        "Id": "Field_SvcSample01", "Kind": "Field", "Type": "Select", "Name": "Sample Route",
        "Model": root, "ReferredList": "List_Sample01",
    }
    d[root].setdefault("Model::Field", []).append("Field_SvcSample01")
    d["Node_BLhs01"] = {"Id": "Node_BLhs01", "Type": "Field", "Field": "Field_SvcSample01",
                        "DataType": "String", "Node": "Node_BRoot01"}
    d["Node_BRhs01"] = {"Id": "Node_BRhs01", "Type": "Static", "Value": "Bogus Option",
                        "DataType": "String", "Node": "Node_BRoot01"}
    d["Node_BRoot01"] = {"Id": "Node_BRoot01", "Type": "Function", "Value": "=", "Syntax": "Infix",
                         "DataType": "Boolean", "Category": "String",
                         "Node::Node": ["Node_BLhs01", "Node_BRhs01"]}
    d["Expression_SampleBranch01"] = {
        "Id": "Expression_SampleBranch01", "Kind": "Expression", "ProcessDef": branch_pd_id,
        "ExpressionStr": "sample", "Expression::Node": ["Node_BRoot01"],
    }

    flagged = doctor(d, list_options={"List_Sample01": ["Option A", "Option B"]})
    assert any("Bogus Option" in p for p in flagged.problems)
    assert flagged.unvalidated == ()

    unknown = doctor(d, list_options=None)
    assert unknown.problems == ()
    assert any("Bogus Option" in u for u in unknown.unvalidated)


# ---- 2b. GotoTask loop conditions ---------------------------------------------

def test_goto_without_condition_loops_forever(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    del goto["Activity::Expression"]

    report = doctor(d)
    assert any("loops forever" in p for p in report.problems)


def test_goto_gate_on_optional_select_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    d["Field_SampleGate01"]["Type"] = "Select"          # Required is already False

    report = doctor(d)
    assert any("optional Select" in p for p in report.problems)


# ---- 3. dangling :: references -------------------------------------------------

def test_dangling_list_ref_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    model = d[d["Root"]]
    model["Model::Field"].append("Field_GhostSample99")

    report = doctor(d)
    assert any("Field_GhostSample99" in p for p in report.problems)


# ---- 4. never-editable sections + unsubmittable Required fields ---------------

def test_section_stripped_of_editable_permissions_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    members = _section_column_ids(d, "Intake")
    flipped = 0
    for v in d.values():
        if (isinstance(v, dict) and v.get("Kind") == "Permission"
                and v.get("Column") in members and v.get("Permission") == "Editable"):
            v["Permission"] = "ReadOnly"
            flipped += 1
    assert flipped > 0, "fixture drift: Intake should have had Editable permissions to strip"

    report = doctor(d)
    assert any("section 'Intake' is never editable" in p for p in report.problems)
    # Intake holds two Required fields (Unit Serial, Problem) -> both become unsubmittable
    assert any("Unit Serial" in p and "never editable" in p for p in report.problems)
    assert any("Problem" in p and "never editable" in p for p in report.problems)


# ---- 5. sparse permission matrix -------------------------------------------

def test_sequence_column_not_counted_as_permission_gap(clean_draft: Draft) -> None:
    # CLAUDE.md > Visibility (#9): a SequenceNumber column takes no Permissions, so its absence
    # from the matrix is not a gap — even when the column is not IsHidden.
    d = add_sequence_number(clean_draft, "Running No", "Intake", "TCK-", "0001", "Ticket arrives")
    (seq_field,) = _nodes_of(d, Kind="Field", Type="SequenceNumber")
    del d[seq_field["Column"]]["IsHidden"]
    report = doctor(d)
    assert not any("sparse" in p for p in report.problems)


def test_sparse_permission_matrix_counted(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    doomed = [k for k, v in d.items() if isinstance(v, dict) and v.get("Kind") == "Permission"][:5]
    for pid in doomed:
        p = d.pop(pid)
        col = d.get(p["Column"]) or {}
        if "Column::Permission" in col:
            col["Column::Permission"] = [x for x in col["Column::Permission"] if x != pid]
        act = d.get(p["Activity"]) or {}
        if "Activity::Permission" in act:
            act["Activity::Permission"] = [x for x in act["Activity::Permission"] if x != pid]

    report = doctor(d)
    assert any(f"sparse: {len(doomed)} (unit, step) pairs unset" in p for p in report.problems)


# ---- 6. role-scoped visibility claims (#6, ADR-0004) -----------------------------

def test_role_scoped_visibility_claim_fails_the_doctor(clean_draft: Draft) -> None:
    """A spec claiming role-scoped visibility must FAIL the doctor with a stated reason naming
    the coverage row — API-impossible, refused, never best-effort (ADR-0004)."""
    claim = "section 'Repair Cost' at stage 'Review' visible only to role 'Finance'"
    report = doctor(clean_draft, visibility_role_claims=(claim,))
    assert report.ok() is False
    assert any(
        claim in p and "role-scoped visibility is API-impossible" in p
        and "step-scoped" in p and "role-scoped-visibility" in p
        for p in report.problems
    )
    assert report.checked["role_scoped_visibility_claims"] == 1


def test_no_role_claims_leaves_the_doctor_clean(clean_draft: Draft) -> None:
    report = doctor(clean_draft)
    assert report.ok() is True
    assert report.checked["role_scoped_visibility_claims"] == 0


def test_doctor_flags_dangling_sequence_step_stamp() -> None:
    """#18: a Step Property whose Value names a nonexistent Activity is THE deterministic
    publish-500 condition; doctor was blind to it (scalar ref, not a list ref)."""
    from kfforge.verify import doctor

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        "Property_Step1": {"Id": "Property_Step1", "Kind": "Property", "Name": "Step",
                           "ValueType": "Value", "Value": "Activity_gone"},
    }
    rep = doctor(draft)
    assert any("Activity_gone" in p and "500" in p for p in rep.problems)
    assert rep.checked["step_stamps"] == 1
