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


def test_usertask_without_assignee_flagged(clean_draft: Draft) -> None:
    """A UserTask with no assignee Resource 500s on submit (CLAUDE.md Members first). The clean
    draft has assignees on every step; strip one and the doctor must catch it."""
    d = copy.deepcopy(clean_draft)
    tasks = _nodes_of(d, NodeType="UserTask")
    assert tasks, "fixture must have at least one UserTask"
    victim = tasks[0]
    del victim["Activity::Resource"]

    report = doctor(d)
    assert any("no AppRole assignee" in p and victim["Name"] in p for p in report.problems)


def test_usertask_with_user_typed_assignee_flagged(clean_draft: Draft) -> None:
    """A Resource with ValueType:"User" publishes but is IGNORED at runtime (CLAUDE.md Members
    first) — it reads as assigned yet still 500s on submit, so the doctor must still flag it."""
    d = copy.deepcopy(clean_draft)
    victim = _nodes_of(d, NodeType="UserTask")[0]
    (res_id,) = victim["Activity::Resource"]
    d[res_id]["ValueType"] = "User"          # persists + publishes, but runtime ignores it

    report = doctor(d)
    assert any("no AppRole assignee" in p and victim["Name"] in p for p in report.problems)


def test_suspended_usertask_without_assignee_not_flagged(clean_draft: Draft) -> None:
    """A suspended step is walked past at runtime, so its missing assignee never bites — the doctor
    must NOT flag it (mirrors CLAUDE.md's IsSuspended semantics)."""
    d = copy.deepcopy(clean_draft)
    victim = _nodes_of(d, NodeType="UserTask")[0]
    del victim["Activity::Resource"]
    victim["IsSuspended"] = True

    report = doctor(d)
    assert not any("has no assignee" in p for p in report.problems)


def test_bare_user_field_flagged(clean_draft: Draft) -> None:
    """A Field{Type:"User"} with no QueryDefinition sibling blocks publish (#59). The doctor must
    catch it before the publish 04211s."""
    d = copy.deepcopy(clean_draft)
    (field_id,) = [k for k, v in d.items()
                   if isinstance(v, dict) and v.get("Kind") == "Field"][:1]
    d[field_id]["Type"] = "User"                 # make an existing field a bare User field
    d[field_id].pop("Field::QueryDefinition", None)

    report = doctor(d)
    assert any("no QueryDefinition sibling" in p for p in report.problems)


# ---- 5. sparse matrix must ignore a table host column ------------------------

def test_table_host_column_is_not_counted_sparse(clean_draft: Draft) -> None:
    # A table HOST column (Type:"Model") takes NO Permission — Kissflow shows/hides the whole
    # table, not its host cell (CLAUDE.md > Tables). set_step_permissions skips hosts by design,
    # so the sparse-matrix rule must NOT demand a Permission per step for the host, or a
    # table-bearing flow with an otherwise-complete matrix reads as "sparse" (host x every step).
    from kfforge.graph import add_table
    from kfforge.types import FieldType

    d = add_table(synthetic_process_draft(), "Line Items",
                  [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    d = set_step_permissions(d, progressive_matrix(d, owners))
    report = doctor(d)
    assert not any("sparse" in p for p in report.problems), report.problems


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


# ---- 8. column geometry: a field column off the 6-unit row grid ----------------

def test_column_geometry_is_counted_on_a_clean_draft(clean_draft: Draft) -> None:
    """The rule counts every field column it examined — a rule that fires nothing must still
    prove it LOOKED, or a silently-skipped walk reads exactly like a clean bill of health."""
    report = doctor(clean_draft)
    assert report.checked["column_geometry"] > 0
    assert not any("row grid" in p or "overlap" in p for p in report.problems), report.problems


@pytest.mark.parametrize(
    ("start", "end", "why"),
    [(0, 8, "off the end of the 6-unit row"),
     (-1, 2, "a negative Start"),
     (8, 6, "End < Start, the shape the old leftover packer emitted")],
)
def test_doctor_flags_a_column_off_the_row_grid(clean_draft: Draft, start: int, end: int,
                                                why: str) -> None:
    """The safety net for a draft THIS ENGINE DID NOT BUILD — a human- or copilot-built form whose
    columns overflow one Row breaks rendering for the WHOLE flow (CLAUDE.md > Node-graph
    invariants), and every other rule reads it as perfectly healthy."""
    d = copy.deepcopy(clean_draft)
    cid = sorted(_section_column_ids(d, "Intake"))[0]
    d[cid].update({"Start": start, "End": end})

    report = doctor(d)
    assert any(f"Start={start}, End={end}" in p and "row grid" in p
               for p in report.problems), (why, report.problems)


def test_doctor_flags_two_columns_overlapping_in_one_row(clean_draft: Draft) -> None:
    """Two columns cannot share a unit of the 6-unit grid — same render-breaking class, per row."""
    d = copy.deepcopy(clean_draft)
    row = next(v for v in d.values() if isinstance(v, dict) and v.get("Kind") == "Row"
               and len(v.get("Row::Column") or []) >= 2
               and all((d.get(c) or {}).get("Type") == "Field" for c in v["Row::Column"]))
    first, second = row["Row::Column"][:2]
    d[first].update({"Start": 0, "End": 4})
    d[second].update({"Start": 2, "End": 6})

    report = doctor(d)
    assert any("overlap" in p and row["Id"] in p for p in report.problems), report.problems


def test_doctor_flags_a_column_with_no_numeric_span(clean_draft: Draft) -> None:
    """A missing Start/End is not a zero — the builder cannot place the column at all."""
    d = copy.deepcopy(clean_draft)
    cid = sorted(_section_column_ids(d, "Intake"))[0]
    d[cid].pop("Start", None)

    report = doctor(d)
    assert any("no numeric grid span" in p for p in report.problems), report.problems


def test_table_child_columns_are_not_flagged_off_the_grid() -> None:
    """A table's child columns are Start=0/End=0 BY DESIGN (CLAUDE.md > Tables: "the 6-unit row
    grid does not apply inside a table"). A geometry rule that re-derives the grid instead of
    reading `section_layout`'s fact base false-flags every table-bearing flow — including its host
    row, where every child sits in ONE schema Row at identical (0, 0) coordinates."""
    from kfforge.graph import add_table
    from kfforge.types import FieldType

    d = add_table(synthetic_process_draft(), "Line Items",
                  [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER), ("Note", FieldType.TEXT)])
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    d = set_step_permissions(d, progressive_matrix(d, owners))

    report = doctor(d)
    assert not any("row grid" in p or "overlap" in p or "numeric grid span" in p
                   for p in report.problems), report.problems
    # ... and the rule genuinely ran: the root form's own columns were still walked
    assert report.checked["column_geometry"] > 0


def test_hidden_sequence_number_column_is_still_checked(clean_draft: Draft) -> None:
    """A hidden column takes no Permission (#9) but is still LAID OUT — it keeps a real span, so
    the geometry rule must not inherit the permission-matrix exclusions wholesale."""
    d = add_sequence_number(copy.deepcopy(clean_draft), "Case No", "Intake",
                            prefix="CS-", padding="0001", step_activity_name="Start")
    before = doctor(d).checked["column_geometry"]

    (col,) = [v for v in d.values() if isinstance(v, dict) and v.get("Kind") == "Column"
              and v.get("IsHidden") and v.get("Type") == "Field"]
    col.update({"Start": 0, "End": 9})
    report = doctor(d)
    assert before > 0
    assert any("Start=0, End=9" in p for p in report.problems), report.problems


# ---- 7b. a list-backed field bound to NO list --------------------------------

def _bare_field_draft(**field_keys: Any) -> Draft:
    """The smallest draft doctor will run on, carrying ONE field built from `field_keys`. Rule 7b
    needs no layout, no workflow and no permissions, so a two-node graph isolates it completely."""
    return {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process",
               "Model::Field": ["Field_One01"]},
        "Field_One01": {"Id": "Field_One01", "Kind": "Field", "Model": "M1", **field_keys},
    }


def test_doctor_flags_a_select_field_with_no_referred_list() -> None:
    """The publish-500 the whole 2026-08-19 diagnosis landed on: a Select is a dropdown whose
    OPTIONS live in a separate list flow, so a Select with no `ReferredList` is bound to nothing.
    PUT 200s, publish dies MetadataError with zero diagnostic content — and every other rule reads
    the flow as perfectly healthy, which is the doctrine-#2 hole this closes: the field landed in
    NO bucket at all."""
    rep = doctor(_bare_field_draft(Type="Select", Name="Urgency"))
    assert any("Urgency" in p and "no ReferredList" in p for p in rep.problems), rep.problems
    assert rep.checked["list_backed_fields"] == 1


def test_doctor_does_not_require_the_referred_list_target_to_be_in_the_draft() -> None:
    """THE false-positive guard. A list is a SEPARATE FLOW, never a node in this graph, so a rule
    of the form `ReferredList not in draft` would fire on every correctly wired Select in
    existence — including every one this engine writes."""
    rep = doctor(_bare_field_draft(Type="Select", Name="Urgency",
                                   ReferredList="List_NotInThisDraft"))
    assert rep.problems == ()
    assert rep.checked["list_backed_fields"] == 1


def _table_child_select_draft(**field_keys: Any) -> Draft:
    """A form whose ONE list-backed field is a table CHILD — `add_table`'s own shape (host
    Column{Type:"Model"} -> nested Model -> schema Row -> child Column/Field), built by the real
    function so the fixture cannot drift from what the engine writes."""
    from kfforge.graph import add_table

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"}}
    d = add_table(bare, "Items", [("Grade", "Select", {"ReferredList": "List_G1"})])
    (grade,) = [v for v in d.values()
                if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Grade"]
    grade.pop("ReferredList")                       # a hand-built / template-cloned bare Select
    grade.update(field_keys)
    return d


def test_doctor_remedy_for_a_table_child_names_a_path_that_actually_works() -> None:
    """G2: "a refusal a caller cannot act on is just a dead end" (CLAUDE.md > Members first),
    applied to a remedy. Rule 7b told every caller to "re-apply the field with referred_list" —
    for a table CHILD that returns isError:true with `changed_ignored` ("apply_changes only
    creates"), and its fallback (forge_delete_fields + forge_apply_fields) would delete the table
    column and re-add the name as a ROOT form field: a different form. The remedy must name the
    child's own table and the rebuild that really repairs it."""
    rep = doctor(_table_child_select_draft())
    (problem,) = [p for p in rep.problems if "no ReferredList" in p]

    assert "'Grade'" in problem and "'Items'" in problem, problem
    # the path that actually works: mint the list, then REBUILD the table
    assert "forge_delete_fields" in problem and "forge_add_table" in problem, problem
    assert "ReferredList" in problem.split("forge_add_table")[1], problem
    # and the dead end is not advised: the root-field remedy must not appear on a table child
    assert "re-apply the field with referred_list" not in problem, problem


def test_doctor_remedy_for_a_root_field_is_unchanged() -> None:
    """The root-field remedy WAS correct and stays verbatim — the table-child branch is an
    addition, not a rewrite of a working message."""
    rep = doctor(_bare_field_draft(Type="Select", Name="Urgency"))
    (problem,) = [p for p in rep.problems if "no ReferredList" in p]
    assert "re-apply the field with referred_list" in problem, problem
    assert "forge_add_table" not in problem, problem


@pytest.mark.parametrize(
    ("keys", "flagged"),
    [({"Type": "Select", "Name": "Plain"}, True),
     ({"Type": "Select", "Widget": "Radio", "Name": "Radio"}, True),       # field_radio.json
     ({"Type": "Multiselect", "Name": "Many"}, True),                      # field_multiselect.json
     ({"Type": "Checkbox", "Name": "Ticks"}, True),                        # field_checkbox.json
     ({"Type": "Checklist", "Name": "Items"}, True),                       # field_checklist.json
     ({"Type": "Text", "Name": "Notes"}, False),                           # a branch may test Text
     ({"Type": "Boolean", "Name": "Done"}, False),
     ({"Type": "Select", "Name": "Wired", "ReferredList": "List_X1"}, False)],
)
def test_list_backed_family_is_exactly_the_captured_one(keys: dict[str, Any],
                                                        flagged: bool) -> None:
    """The family is the set of `Type` strings EVERY capture in shapes/ carries `ReferredList` on —
    never inferred from a field's name, and never widened to `Text` (CLAUDE.md documents Text as a
    legitimate deciding-field type for a branch condition)."""
    rep = doctor(_bare_field_draft(**keys))
    assert any("no ReferredList" in p for p in rep.problems) is flagged, rep.problems


def test_clean_draft_has_every_select_wired_to_a_list(clean_draft: Draft) -> None:
    """The engine's own dogfood build must not be the thing rule 7b catches: the synthetic draft
    carries three Selects, and every one of them names a list."""
    rep = doctor(clean_draft)
    assert rep.checked["list_backed_fields"] >= 3
    assert not any("no ReferredList" in p for p in rep.problems), rep.problems


# ---- 3c. dangling SCALAR references ------------------------------------------

def test_doctor_flags_a_dangling_scalar_reference() -> None:
    """Rule 3 sweeps `::` LIST refs only; rule 3b guards exactly one scalar (`Property{Step}`).
    Every other scalar owner back-ref was unguarded — the same PUT-200/publish-500 class."""
    d = _bare_field_draft(Type="Text", Name="Notes", Column="Column_Gone99")
    rep = doctor(d)
    assert any("Column_Gone99" in p and "scalar reference" in p for p in rep.problems), rep.problems
    assert rep.checked["scalar_refs"] > 0


def test_scalar_rule_never_resolves_an_id_shaped_value_that_is_not_a_reference() -> None:
    """Driven by an explicit (Kind -> keys) ALLOWLIST, never an "looks like an id" heuristic. In
    the real broken draft `Activity.NodeType == "SendBackToInitiator"` is a string that literally
    equals a node id, and `Field.ReferredList` / `Resource.Value` / `Model._application_id` are all
    id-shaped and all resolve to nothing in the draft BY DESIGN."""
    d: Draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process",
               "_application_id": "App_Elsewhere01"},
        "Field_One01": {"Id": "Field_One01", "Kind": "Field", "Type": "Select", "Name": "Pick",
                        "Model": "M1", "ReferredList": "List_Elsewhere01"},
        "Activity_One01": {"Id": "Activity_One01", "Kind": "Activity",
                           "NodeType": "SendBackToInitiator", "Name": "Send back"},
        "Resource_One01": {"Id": "Resource_One01", "Kind": "Resource", "ValueType": "AppRole",
                           "Value": "RoElsewhere01"},
    }
    rep = doctor(d)
    assert not any("scalar reference" in p for p in rep.problems), rep.problems


def test_scalar_rule_treats_underscore_refs_as_system_fields_not_node_ids() -> None:
    """The platform writes system-field refs with a leading underscore: `Node.Field = "_Field_x"`
    while the node is keyed "Field_x", and `"_created_by"` names a system field with NO node at
    all (both real shapes in shapes/process_template_full.json). Neither is a dangling reference —
    they land in their own checked bucket, never in problems."""
    d: Draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        "Field_x01": {"Id": "Field_x01", "Kind": "Field", "Type": "Text", "Name": "X",
                      "Model": "M1"},
        "Node_One01": {"Id": "Node_One01", "Kind": "Node", "Field": "_Field_x01"},
        "Node_Two01": {"Id": "Node_Two01", "Kind": "Node", "Field": "_created_by"},
    }
    rep = doctor(d)
    assert not any("scalar reference" in p for p in rep.problems), rep.problems
    assert rep.checked["system_scalar_refs"] == 2


def test_transplanted_template_raises_no_scalar_reference_problem() -> None:
    """The regression that shipped: doctor read 11 fabricated 'missing _Field_...' problems off
    the very graph forge_create_template_app had just built and published clean."""
    from kfforge.graph import transplant_template

    base: Draft = {"Root": "M1", "_meta_version": "v1",
                   "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    rep = doctor(transplant_template(base, app_role=("Ro123", "R")))
    assert not any("scalar reference" in p for p in rep.problems), rep.problems
    assert rep.checked["system_scalar_refs"] > 0


def test_scalar_rule_is_silent_on_the_shipped_template_shell() -> None:
    """The strongest available oracle: the identity shell is a de-identified capture of a REAL
    published production process template. A scalar rule that fires here fires on every process
    this engine builds with `from_template=True` — the default."""
    from kfforge.graph import clone_template_shell

    d = clone_template_shell({"Root": "M1",
                              "M1": {"Id": "M1", "Kind": "Model", "Name": "P",
                                     "FlowType": "Process"}})
    rep = doctor(d)
    assert not any("scalar reference" in p for p in rep.problems), rep.problems
    assert rep.checked["scalar_refs"] > 0


# ---- 7c. a shipped TODO placeholder in a user-facing field NAME ---------------

def test_doctor_flags_a_todo_placeholder_shipped_as_a_field_label() -> None:
    d = _bare_field_draft(Type="Text",
                          Name="Manager User (TODO: was a User field — see field_user_reference)")
    rep = doctor(d)
    assert any("TODO placeholder" in p for p in rep.problems), rep.problems
    assert rep.checked["placeholder_names"] == 1


def test_shipped_template_shell_carries_no_todo_placeholder_names() -> None:
    """The real fix for rule 7c is in the SHAPE, not the rule: a developer note must never ship as
    a user-facing label on every from_template=True process."""
    from kfforge.graph import clone_template_shell

    d = clone_template_shell({"Root": "M1",
                              "M1": {"Id": "M1", "Kind": "Model", "Name": "P",
                                     "FlowType": "Process"}})
    rep = doctor(d)
    assert not any("TODO placeholder" in p for p in rep.problems), rep.problems
    assert rep.checked["placeholder_names"] > 0


# ---- 8b. one column claimed by two rows ---------------------------------------

def test_doctor_flags_one_column_claimed_by_two_rows(clean_draft: Draft) -> None:
    """D8(a): `apply_exact_layout` used to accept the same field named twice, leaving one Column in
    two Rows' `Row::Column` while its own `Row` back-ref names only one. The geometry rule groups
    BY that back-ref, so the duplicate appears once per group and reads perfectly clean."""
    d = copy.deepcopy(clean_draft)
    rows = [v for v in d.values() if isinstance(v, dict) and v.get("Kind") == "Row"
            and (v.get("Row::Column") or [])]
    victim = rows[0]["Row::Column"][0]
    rows[1]["Row::Column"].append(victim)          # a second row now claims it too

    rep = doctor(d)
    assert any(victim in p and "two rows claim" in p for p in rep.problems), rep.problems
    assert rep.checked["row_column_claims"] > 0


def test_four_column_row_from_the_real_prod_template_is_not_flagged() -> None:
    """Counter-capture, stated deliberately: `shapes/process_template_identity_shell.json` — a
    de-identified capture of a REAL published production template — carries a Row with FOUR field
    columns at (0,2) (2,4) (4,5) (5,6). "At most 3 columns per row" is the consequence of
    FIELD_SPAN=2 — the auto-tiler's default packing — not a platform limit, so the doctor refuses
    to invent a count bound it has a live capture AGAINST (doctrine #10). The WRITE guard now
    agrees rather than contradicting it — see
    test_layout_guard_accepts_the_four_column_row_the_prod_capture_proves."""
    from kfforge.graph import clone_template_shell

    d = clone_template_shell({"Root": "M1",
                              "M1": {"Id": "M1", "Kind": "Model", "Name": "P",
                                     "FlowType": "Process"}})
    widest = max((len(v.get("Row::Column") or []) for v in d.values()
                  if isinstance(v, dict) and v.get("Kind") == "Row"), default=0)
    assert widest >= 4, "fixture drift: the shipped shell no longer has its 4-column row"
    rep = doctor(d)
    assert not any("columns per row" in p or "two rows claim" in p
                   for p in rep.problems), rep.problems


def test_doctor_reports_a_malformed_permission_instead_of_raising() -> None:
    """Doctrine 7: doctor REPORTS, it never raises. A Permission missing Column/Activity used to
    escape `forge_doctor` as a bare KeyError across the tool boundary — and doctor is the tool
    SKILL.md tells the builder to run after EVERY edit, on flows this engine did not build."""
    from tests.synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    draft["Permission_bad"] = {"Id": "Permission_bad", "Kind": "Permission",
                               "Permission": "Editable"}          # no Column, no Activity

    report = doctor(draft)                                        # must not raise

    assert report.checked["malformed_permissions"] == 1
    assert any("Permission node(s) missing a Column/Activity" in p for p in report.problems)
    assert any("Permission_bad" in p for p in report.problems), "must NAME the offending node"


def test_a_clean_draft_reports_no_malformed_permissions() -> None:
    """The control: the guard must not invent a problem on a well-formed graph."""
    from tests.synthetic import synthetic_process_draft

    report = doctor(synthetic_process_draft())
    assert report.checked["malformed_permissions"] == 0
    assert not [p for p in report.problems if "malformed" in p or "missing a Column" in p]


def test_doctor_reports_many_malformed_permissions_with_ellipsis(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    for i in range(8):
        d[f"Permission_bad_{i}"] = {
            "Id": f"Permission_bad_{i}",
            "Kind": "Permission",
            "Permission": "Editable",
        }
    rep = doctor(d)
    assert rep.checked["malformed_permissions"] == 8
    assert any("..." in p and "Permission node(s) missing" in p for p in rep.problems)


# ---- additional branch coverage tests ----------------------------------------

def test_goto_jumping_to_missing_activity_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    goto["Goto"] = "Activity_DoesNotExist99"
    rep = doctor(d)
    assert any("jumps to missing activity" in p for p in rep.problems)


def test_goto_jumping_out_of_own_branch_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    target = d[goto["Goto"]]
    target["ProcessDef"] = "ProcessDef_OtherBranch99"
    rep = doctor(d)
    assert any("jumps out of its own branch" in p for p in rep.problems)


def test_goto_missing_back_ref_on_target_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    target = d[goto["Goto"]]
    target["Goto::Activity"] = []
    rep = doctor(d)
    assert any("missing the Goto::Activity back-ref" in p for p in rep.problems)


def test_goto_gate_field_missing_from_draft_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    (xid,) = goto["Activity::Expression"]
    (root_nid,) = d[xid]["Expression::Node"]
    for child_nid in d[root_nid]["Node::Node"]:
        if d[child_nid].get("Type") == "Field":
            d[child_nid]["Field"] = "Field_DoesNotExist99"
    rep = doctor(d)
    assert any("tests missing field" in p and "Field_DoesNotExist99" in p for p in rep.problems)


def test_branch_literal_matching_valid_option_passes(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    root = d["Root"]
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Field_SvcSample01"] = {
        "Id": "Field_SvcSample01", "Kind": "Field", "Model": root,
        "Type": "Select", "ReferredList": "List_Sample01", "Name": "Service",
    }
    d["Node_Root01"] = {"Id": "Node_Root01", "Kind": "Node", "Type": "Operator",
                        "Node::Node": ["Node_Field01", "Node_Static01"]}
    d["Node_Field01"] = {"Id": "Node_Field01", "Kind": "Node", "Type": "Field",
                         "Field": "Field_SvcSample01"}
    d["Node_Static01"] = {"Id": "Node_Static01", "Kind": "Node", "Type": "Static",
                          "Value": "Option A"}
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01", "Kind": "Expression", "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = doctor(d, list_options={"List_Sample01": ["Option A", "Option B"]})
    assert not any("Path A" in p for p in rep.problems)
    assert rep.checked["branch_literals"] == 1


def test_branch_referencing_missing_field_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Node_Root01"] = {"Id": "Node_Root01", "Kind": "Node", "Type": "Operator",
                        "Node::Node": ["Node_Field01"]}
    d["Node_Field01"] = {"Id": "Node_Field01", "Kind": "Node", "Type": "Field",
                         "Field": "Field_Missing99"}
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01", "Kind": "Expression", "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = doctor(d)
    assert any("branch 'Path A' references missing field Field_Missing99" in p for p in rep.problems)


def test_branch_comparing_against_non_select_field_is_unvalidated(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    root = d["Root"]
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Field_Text01"] = {
        "Id": "Field_Text01", "Kind": "Field", "Model": root,
        "Type": "Text", "Name": "Notes",
    }
    d["Node_Root01"] = {"Id": "Node_Root01", "Kind": "Node", "Type": "Operator",
                        "Node::Node": ["Node_Field01", "Node_Static01"]}
    d["Node_Field01"] = {"Id": "Node_Field01", "Kind": "Node", "Type": "Field",
                         "Field": "Field_Text01"}
    d["Node_Static01"] = {"Id": "Node_Static01", "Kind": "Node", "Type": "Static",
                          "Value": "SomeValue"}
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01", "Kind": "Expression", "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = doctor(d, list_options={"List_Sample01": ["Option A"]})
    assert any("not validated (no list options given for its field)" in u for u in rep.unvalidated)


def test_event_attached_to_missing_field_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Field"] = "Field_DoesNotExist99"
    rep = doctor(d)
    assert any("is attached to a missing field" in p for p in rep.problems)


def test_section_without_columns_is_not_flagged_as_never_editable(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    d["Section_Banner"] = {
        "Id": "Section_Banner",
        "Kind": "Column",
        "Type": "Section",
        "Name": "Info Banner",
        "Column::Row": [],
    }
    rep = doctor(d)
    assert not any("Info Banner" in p for p in rep.problems)


def test_owning_table_name_resolution_and_fallbacks() -> None:
    from kfforge.verify import _owning_table_name

    # 1. Normal table with name on Model
    nodes1 = {
        "Model_T": {"Id": "Model_T", "Kind": "Model", "Name": "LineItems", "Column": "Col_T"},
        "Col_T": {"Id": "Col_T", "Kind": "Column", "Type": "Model", "Name": "LineItems"},
    }
    assert _owning_table_name(nodes1, {"Model": "Model_T"}) == "LineItems"

    # 2. Table with empty Name on Model, falling back to host Column Name
    nodes2 = {
        "Model_T": {"Id": "Model_T", "Kind": "Model", "Name": "", "Column": "Col_T"},
        "Col_T": {"Id": "Col_T", "Kind": "Column", "Type": "Model", "Name": "FallbackHostName"},
    }
    assert _owning_table_name(nodes2, {"Model": "Model_T"}) == "FallbackHostName"

    # 3. Model not found or not a Model
    assert _owning_table_name({}, {"Model": "Model_Missing"}) is None
    assert _owning_table_name({"M": {"Kind": "Field"}}, {"Model": "M"}) is None

    # 4. Root model with no host Column
    nodes4 = {"Model_Root": {"Id": "Model_Root", "Kind": "Model", "Name": "RootModel"}}
    assert _owning_table_name(nodes4, {"Model": "Model_Root"}) is None

    # 5. Model with no name on either Model or Column
    nodes5 = {
        "Model_T": {"Id": "Model_T", "Kind": "Model", "Name": "", "Column": "Col_T"},
        "Col_T": {"Id": "Col_T", "Kind": "Column", "Type": "Model", "Name": ""},
    }
    assert _owning_table_name(nodes5, {"Model": "Model_T"}) is None


def test_dangling_list_refs_with_non_string_elements(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    d["Row_Test"] = {
        "Id": "Row_Test",
        "Kind": "Row",
        "Row::Column": [123, None, "Column_DoesNotExist99"],
    }
    rep = doctor(d)
    assert any("Row_Test.Row::Column -> missing Column_DoesNotExist99" in p for p in rep.problems)


def test_branch_condition_with_no_field_sibling_is_unvalidated(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Node_Root01"] = {"Id": "Node_Root01", "Kind": "Node", "Type": "Operator",
                        "Node::Node": ["Node_Static01"]}
    d["Node_Static01"] = {"Id": "Node_Static01", "Kind": "Node", "Type": "Static",
                          "Value": "StandaloneStatic"}
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01", "Kind": "Expression", "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = doctor(d)
    assert any("literal 'StandaloneStatic' not validated" in u for u in rep.unvalidated)


def test_permission_for_model_column_credits_model_name(clean_draft: Draft) -> None:
    """A Permission on a Model-type column (a nested table) must credit the model's OWN name as
    editable, not just the Section that physically contains it — nest it under a differently
    named Section ("Banner") so `owner_section` alone would credit only "Banner"; without
    `_process_permission_node`'s Model-name credit, "TableSection" itself would wrongly show up
    in `doctor`'s per-Model coverage sweep as never editable."""
    d = copy.deepcopy(clean_draft)
    d["Row_Banner_Test"] = {
        "Id": "Row_Banner_Test",
        "Kind": "Row",
        "Column": "Sec_Banner_Test",
        "Row::Column": ["Col_Model_Test"],
    }
    d["Sec_Banner_Test"] = {
        "Id": "Sec_Banner_Test",
        "Kind": "Column",
        "Type": "Section",
        "Name": "Banner",
        "Column::Row": ["Row_Banner_Test"],
    }
    d["Col_Model_Test"] = {
        "Id": "Col_Model_Test",
        "Kind": "Column",
        "Type": "Model",
        "Name": "TableSection",
        "Row": "Row_Banner_Test",
    }
    act = _nodes_of(d, Kind="Activity", NodeType="UserTask")[0]
    d["Permission_Model_Test"] = {
        "Id": "Permission_Model_Test",
        "Kind": "Permission",
        "Permission": "Editable",
        "Activity": act["Id"],
        "Column": "Col_Model_Test",
    }
    rep = doctor(d)
    assert not any("TableSection" in p for p in rep.problems), rep.problems


def test_permission_for_suspended_activity_is_ignored_for_editability(clean_draft: Draft) -> None:
    """A Permission attached to a suspended Activity must not count toward a section's
    editability. "Assessment" in `clean_draft` is owned only by 'Assess unit' — suspending that
    step must surface the section as never editable, not silently leave it credited."""
    d = copy.deepcopy(clean_draft)
    (assess,) = _nodes_of(d, Kind="Activity", NodeType="UserTask", Name="Assess unit")
    assess["IsSuspended"] = True
    rep = doctor(d)
    assert any("Assessment" in p and "never editable" in p for p in rep.problems), rep.problems



