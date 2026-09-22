"""app.application.compare (#16): the fidelity comparator judges the BUILT graph against the INPUT
spec. Offline: drafts are built with the engine's own builders (never hand-guessed shapes),
then broken in the specific way each check exists to catch — every test's break is a real bug
class from eval case 1 (#16 'each of which caught a real bug')."""

from __future__ import annotations

from typing import Any

from test_intake import _full_spec

from app.application.compare import CompareReport, compare_built_to_spec
from app.domain.graph import apply_changes, build_workflow, regroup_into_sections
from app.domain.types import FieldSpec, FieldType


def _built_fields(spec: Any) -> dict[str, Any]:
    """A draft carrying every field/table-column the spec asks for, engine-built."""
    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    specs = [
        FieldSpec(
            name=f.name,
            type=f.type,
            referred_list=("L1" if getattr(f, "list_name", None) else None),
        )
        for f in spec.data_model.fields
    ]
    for t in spec.data_model.tables:
        specs += [FieldSpec(name=c.name, type=c.type) for c in t.columns]
    return apply_changes(bare, specs)


def _msgs(rep: CompareReport) -> str:
    return "\n".join(rep.mismatches)


def test_wrong_field_type_and_missing_field_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    # break: retype Urgency (Select -> Text) and delete Quantity outright
    urgency = next(v for v in draft.values() if isinstance(v, dict) and v.get("Name") == "Urgency")
    urgency["Type"] = "Text"
    qty = next(k for k, v in draft.items() if isinstance(v, dict) and v.get("Name") == "Quantity")
    del draft[qty]
    rep = compare_built_to_spec(draft, spec)
    assert "built as 'Text', input asked 'Select'" in _msgs(rep)
    assert "field 'Quantity' (Number) asked for by the input is absent" in _msgs(rep)


def test_select_without_referredlist_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    urgency = next(v for v in draft.values() if isinstance(v, dict) and v.get("Name") == "Urgency")
    urgency.pop("ReferredList", None)
    rep = compare_built_to_spec(draft, spec)
    assert "no ReferredList" in _msgs(rep)


def test_unrequested_extra_field_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft2 = apply_changes(draft, [FieldSpec(name="Phantom", type=FieldType.TEXT)])
    rep = compare_built_to_spec(draft2, spec)
    assert "'Phantom'" in _msgs(rep) and "never asked for it" in _msgs(rep)


def test_stranded_empty_banner_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft = regroup_into_sections(
        draft, [("Intake Basics", ["Unit Name"]), ("Banner", []), ("Tail", ["Customer Name"])]
    )
    rep = compare_built_to_spec(draft, spec)
    assert "stranded banner breaks the WHOLE form's render" in _msgs(rep)


def test_spurious_permission_on_hidden_column_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Column_Hidden1"] = {"Id": "Column_Hidden1", "Kind": "Column", "IsHidden": True}
    draft["Permission_Bad1"] = {
        "Id": "Permission_Bad1",
        "Kind": "Permission",
        "Column": "Column_Hidden1",
        "Permission": "Editable",
    }
    rep = compare_built_to_spec(draft, spec)
    assert "SequenceNumber/IsHidden columns" in _msgs(rep)


def test_missing_event_on_computed_source_flagged() -> None:
    spec = _full_spec()
    rep = compare_built_to_spec(_built_fields(spec), spec)
    assert "carries NO event" in _msgs(rep)


def test_unconditional_branch_and_ungated_loop_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft = build_workflow(
        draft,
        [(s.name, None) for s in spec.stages.stages],
        parallel=("Route", [("A", [("A1", None)]), ("B", [("B1", None)])]),
        parallel_after=0,
    )
    rep = compare_built_to_spec(draft, spec)
    assert "NO condition" in _msgs(rep) and "fail-open" in _msgs(rep)
    assert "no GotoTask targeting" in _msgs(rep)  # the spec's loop was never built


def test_incomplete_style_chain_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Appearance_Bad1"] = {
        "Id": "Appearance_Bad1",
        "Kind": "Appearance",
        "Appearance::Style": [],
    }
    rep = compare_built_to_spec(draft, spec)
    assert "must be exactly 1" in _msgs(rep)


def test_benign_platform_nodes_are_declared_ignored_not_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["User_Pub1"] = {"Id": "User_Pub1", "Kind": "User", "Name": "PublishedBy"}
    rep = compare_built_to_spec(draft, spec)
    assert any("platform publish side-effect" in i for i in rep.ignored)
    assert "User_Pub1" not in _msgs(rep)


def test_compare_report_ok_and_as_tool_result() -> None:
    rep_ok = CompareReport(mismatches=(), checked={"fields": 5}, ignored=())
    assert rep_ok.ok() is True
    res_ok = rep_ok.as_tool_result()
    assert res_ok["ok"] is True
    assert res_ok["isError"] is False
    assert res_ok["mismatches"] == []
    assert res_ok["checked"] == {"fields": 5}

    rep_err = CompareReport(mismatches=("error 1",), checked={}, ignored=("User",))
    assert rep_err.ok() is False
    res_err = rep_err.as_tool_result()
    assert res_err["ok"] is False
    assert res_err["isError"] is True
    assert res_err["mismatches"] == ["error 1"]
    assert res_err["ignored"] == ["User"]


def test_sequence_number_missing_and_present_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    rep = compare_built_to_spec(draft, spec)
    assert (
        "input asks for an auto-numbered id (sequence) — no SequenceNumber field was built"
        in _msgs(rep)
    )

    draft["Field_Seq"] = {
        "Id": "Field_Seq",
        "Kind": "Field",
        "Name": "CaseNumber",
        "Type": "SequenceNumber",
    }
    rep2 = compare_built_to_spec(draft, spec)
    assert "SequenceNumber" not in _msgs(rep2)


def test_missing_sections_and_tables_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    # Clear Root Model::Row so no sections or tables exist
    root_id = draft["Root"]
    draft[root_id]["Model::Row"] = []
    rep = compare_built_to_spec(draft, spec)
    assert "section 'Intake Basics' asked for by the input is absent from the form" in _msgs(rep)
    assert "table 'Parts Used' asked for by the input has no host row" in _msgs(rep)


def test_empty_section_followed_by_table_model_is_accepted() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    root_id = draft["Root"]
    draft["Row_Banner"] = {"Id": "Row_Banner", "Kind": "Row", "Row::Column": ["Col_Banner"]}
    draft["Col_Banner"] = {
        "Id": "Col_Banner",
        "Kind": "Column",
        "Type": "Section",
        "Name": "TableBanner",
        "Column::Row": [],
    }
    draft["Row_Table"] = {"Id": "Row_Table", "Kind": "Row", "Row::Column": ["Col_Table"]}
    draft["Col_Table"] = {
        "Id": "Col_Table",
        "Kind": "Column",
        "Type": "Model",
        "Name": "Parts Used",
    }
    draft[root_id]["Model::Row"] = ["Row_Banner", "Row_Table"]

    rep = compare_built_to_spec(draft, spec)
    # The empty banner preceding Model should not trigger the stranded banner error
    assert "stranded banner breaks the WHOLE form's render" not in _msgs(rep)


def test_permission_on_sequence_number_column_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Field_Seq"] = {
        "Id": "Field_Seq",
        "Kind": "Field",
        "Name": "CaseId",
        "Type": "SequenceNumber",
    }
    draft["Col_Seq"] = {"Id": "Col_Seq", "Kind": "Column", "Column::Field": ["Field_Seq"]}
    draft["Perm_Seq"] = {
        "Id": "Perm_Seq",
        "Kind": "Permission",
        "Column": "Col_Seq",
        "Permission": "Editable",
    }
    rep = compare_built_to_spec(draft, spec)
    assert "Permission(s) sit on SequenceNumber/IsHidden columns" in _msgs(rep)


def test_event_with_wrong_trigger_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    qty_id = next(
        k for k, v in draft.items() if isinstance(v, dict) and v.get("Name") == "Quantity"
    )
    draft["Event_Wrong"] = {
        "Id": "Event_Wrong",
        "Kind": "Event",
        "Field": qty_id,
        "Trigger": "invalid_trigger",
    }
    rep = compare_built_to_spec(draft, spec)
    assert "has trigger(s) ['invalid_trigger']" in _msgs(rep)
    assert "never fires" in _msgs(rep)


def test_missing_stages_and_decision_point_parallel_count_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    # No activities built at all
    rep = compare_built_to_spec(draft, spec)
    assert "stage 'Intake' asked for by the input has no Activity" in _msgs(rep)
    assert "input declares 1 decision point(s), build has 0 Parallel gateway(s)" in _msgs(rep)


def test_loop_with_ungated_matching_goto_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Act_Repair"] = {"Id": "Act_Repair", "Kind": "Activity", "Name": "Repair"}
    draft["Act_Goto"] = {
        "Id": "Act_Goto",
        "Kind": "Activity",
        "NodeType": "GotoTask",
        "Goto": "Act_Repair",
        "Activity::Expression": [],
    }
    rep = compare_built_to_spec(draft, spec)
    assert "loop 'Quality Check'->'Repair': GotoTask has NO gate condition" in _msgs(rep)


def test_conditional_branch_and_gated_loop_pass() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Act_Repair"] = {"Id": "Act_Repair", "Kind": "Activity", "Name": "Repair"}
    draft["Act_Goto"] = {
        "Id": "Act_Goto",
        "Kind": "Activity",
        "NodeType": "GotoTask",
        "Goto": "Act_Repair",
        "Activity::Expression": ["Expr_Gate1"],
    }
    draft["PD_Branch"] = {
        "Id": "PD_Branch",
        "Kind": "ProcessDef",
        "Name": "Yes",
        "ProcessDef::Expression": ["Expr_Branch1"],
    }
    draft["Act_Parallel"] = {
        "Id": "Act_Parallel",
        "Kind": "Activity",
        "NodeType": "Parallel",
        "Name": "Repairable Decision",
        "Activity::ProcessDef": ["PD_Branch"],
    }
    rep = compare_built_to_spec(draft, spec)
    assert "GotoTask has NO gate condition" not in _msgs(rep)
    assert "carry NO condition" not in _msgs(rep)


def test_spec_without_routing_points_skips_gateway_checks() -> None:
    import dataclasses

    from app.application.intake.schema import Routing

    spec = _full_spec()
    spec_no_routing = dataclasses.replace(spec, routing=Routing(points=()))
    draft = _built_fields(spec_no_routing)
    rep = compare_built_to_spec(draft, spec_no_routing)
    assert rep.checked["decision_points"] == 0


def test_fully_valid_built_draft_passes_all_checks() -> None:
    import dataclasses

    spec = _full_spec()
    draft = _built_fields(spec)
    root_id = draft["Root"]

    # 1. Sequence field
    draft["Field_Seq"] = {
        "Id": "Field_Seq",
        "Kind": "Field",
        "Name": "CaseId",
        "Type": "SequenceNumber",
    }

    # 2. Sections & Table hosts in Root Model::Row
    draft["Row_S1"] = {"Id": "Row_S1", "Kind": "Row", "Row::Column": ["Col_S1"]}
    draft["Col_S1"] = {
        "Id": "Col_S1",
        "Kind": "Column",
        "Type": "Section",
        "Name": "Intake Basics",
        "Column::Row": ["R1"],
    }
    draft["Row_S2"] = {"Id": "Row_S2", "Kind": "Row", "Row::Column": ["Col_S2"]}
    draft["Col_S2"] = {
        "Id": "Col_S2",
        "Kind": "Column",
        "Type": "Section",
        "Name": "Intake Priority",
        "Column::Row": ["R2"],
    }
    draft["Row_T1"] = {"Id": "Row_T1", "Kind": "Row", "Row::Column": ["Col_T1"]}
    draft["Col_T1"] = {"Id": "Col_T1", "Kind": "Column", "Type": "Model", "Name": "Parts Used"}
    draft[root_id]["Model::Row"] = ["Row_S1", "Row_S2", "Row_T1"]

    # 3. Valid Appearance with exactly 1 Style
    for a in draft.values():
        if isinstance(a, dict) and a.get("Kind") == "Appearance":
            a["Appearance::Style"] = ["Style_Existing"]

    # 4. Computed field events with correct trigger ("onSelect" for Number fields Quantity and Unit Cost)
    qty_id = next(
        k for k, v in draft.items() if isinstance(v, dict) and v.get("Name") == "Quantity"
    )
    cost_id = next(
        k for k, v in draft.items() if isinstance(v, dict) and v.get("Name") == "Unit Cost"
    )
    draft["Ev_Qty"] = {"Id": "Ev_Qty", "Kind": "Event", "Field": qty_id, "Trigger": "onSelect"}
    draft["Ev_Cost"] = {"Id": "Ev_Cost", "Kind": "Event", "Field": cost_id, "Trigger": "onSelect"}

    # 5. Workflow stages as activities
    for s in spec.stages.stages:
        draft[f"Act_{s.name}"] = {"Id": f"Act_{s.name}", "Kind": "Activity", "Name": s.name}

    # Parallel gateway with conditional branches + one parallel without branches to test empty branch_ids
    draft["PD_Yes"] = {
        "Id": "PD_Yes",
        "Kind": "ProcessDef",
        "Name": "Yes",
        "ProcessDef::Expression": ["Expr_Yes"],
    }
    draft["PD_No"] = {
        "Id": "PD_No",
        "Kind": "ProcessDef",
        "Name": "No",
        "ProcessDef::Expression": ["Expr_No"],
    }
    draft["Act_Par1"] = {
        "Id": "Act_Par1",
        "Kind": "Activity",
        "NodeType": "Parallel",
        "Name": "Repairable",
        "Activity::ProcessDef": ["PD_Yes", "PD_No"],
    }
    draft["Act_Par_Empty"] = {
        "Id": "Act_Par_Empty",
        "Kind": "Activity",
        "NodeType": "Parallel",
        "Name": "EmptyPar",
        "Activity::ProcessDef": [],
    }

    # Gotos: one matching target stage ("Repair") with condition, one targeting a different stage ("Diagnose")
    draft["Act_Goto1"] = {
        "Id": "Act_Goto1",
        "Kind": "Activity",
        "NodeType": "GotoTask",
        "Goto": "Act_Repair",
        "Activity::Expression": ["Expr_Loop"],
    }
    draft["Act_Goto_Other"] = {
        "Id": "Act_Goto_Other",
        "Kind": "Activity",
        "NodeType": "GotoTask",
        "Goto": "Act_Diagnose",
        "Activity::Expression": ["Expr_Other"],
    }

    rep = compare_built_to_spec(draft, spec)
    assert rep.ok() is True
    assert rep.mismatches == ()

    # Spec without sequence
    spec_no_seq = dataclasses.replace(
        spec, data_model=dataclasses.replace(spec.data_model, sequence=None)
    )
    rep_no_seq = compare_built_to_spec(draft, spec_no_seq)
    assert "sequence" not in rep_no_seq.checked


def test_extract_row_first_cols_edge_cases() -> None:
    # 1. Root missing or non-dict
    draft_no_root = {"Root": "M_Missing"}
    assert compare_built_to_spec(draft_no_root, _full_spec()).ok() is False

    # 2. Row without columns or row missing
    draft_empty_row = {
        "Root": "M1",
        "M1": {
            "Id": "M1",
            "Kind": "Model",
            "Model::Row": ["Row_NonExistent", "Row_NoCols", "Row_ColNotDict"],
        },
        "Row_NoCols": {"Id": "Row_NoCols", "Kind": "Row", "Row::Column": []},
        "Row_ColNotDict": {"Id": "Row_ColNotDict", "Kind": "Row", "Row::Column": ["Col_Missing"]},
    }
    rep = compare_built_to_spec(draft_empty_row, _full_spec())
    assert rep.ok() is False
