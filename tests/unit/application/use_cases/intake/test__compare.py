"""Mirror tests for `app.application.use_cases.intake._compare` -- ported
from `tests/test_compare.py` (Stage D group 8; the module moved from
`app.application.compare`).

The fidelity comparator judges the BUILT graph against the INPUT spec.
Offline: drafts are built with the engine's own builders (never
hand-guessed shapes), then broken in the specific way each check exists to
catch -- every test's break is a real bug class from eval case 1 (#16
"each of which caught a real bug").
"""

from __future__ import annotations

from typing import Any

from app.application.models.requests.intake.app_spec import (
    START_STAGE,
    AppSpec,
    CaseWalk,
    ComputedReq,
    DataModel,
    DecisionPoint,
    FieldReq,
    ListSpec,
    LoopSpec,
    MasterData,
    PageIntent,
    Personas,
    PersonaView,
    ProblemGoal,
    ReworkLoops,
    Roles,
    RoleSpec,
    Routing,
    SectionReq,
    SequenceReq,
    Stages,
    StageSpec,
    StepFill,
    TableColumnReq,
    TableReq,
    TestCases,
    Timing,
    VisibilityEntry,
    VisibilityMatrix,
    WidgetIntent,
)
from app.application.use_cases.intake._compare import (
    CompareReport,
    compare_built_to_spec,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType, Visibility


def _full_spec(*, approved: bool = True) -> AppSpec:
    """A fully-populated AppSpec for a neutral domain: a small equipment repair shop
    tracking a
    unit from intake through repair to return, WITH a real branch (Diagnose) and a real
    rework
    loop (Quality Check -> Repair). Every one of the 11 dimensions carries enough
    content that
    `compile_spec` produces at least one op of every `OP_ORDER` kind — see
    `test_op_counts_match_the_fixture_exactly` for the exact expected op counts.
    Companion to
    `_linear_spec`, which proves the OPPOSITE: an app with none of this is equally
    valid.
    """
    return AppSpec(
        app_name="Equipment Repair Tracker",
        problem_goal=ProblemGoal(
            pain="technicians and customers cannot see which repair job is stuck or "
            "with whom",
            goal="every repair job is trackable from intake to return, with a clear "
            "owner at "
            "each step",
            done_definition="the unit is repaired or declared unrepairable, and the "
            "customer "
            "has been notified",
            terminal_states=("Completed", "Cancelled"),
            result_values=("Repaired", "Beyond repair", "Cancelled by customer"),
        ),
        roles=Roles(
            roles=(
                RoleSpec(
                    name="Front Desk", is_admin=False, members_hint="2 front-desk staff"
                ),
                RoleSpec(
                    name="Technician", is_admin=False, members_hint="5 technicians"
                ),
                RoleSpec(
                    name="Service Manager", is_admin=True, members_hint="1 manager"
                ),
            )
        ),
        stages=Stages(
            stages=(
                StageSpec(
                    name="Intake",
                    owner_role="Front Desk",
                    what_happens="log the unit and customer details",
                    entry_criteria="customer drops off a unit",
                    exit_criteria="unit logged with a case number",
                ),
                StageSpec(
                    name="Diagnose",
                    owner_role="Technician",
                    what_happens="assess whether the unit is repairable",
                    entry_criteria="unit logged",
                    exit_criteria="repairable decision recorded",
                ),
                StageSpec(
                    name="Repair",
                    owner_role="Technician",
                    what_happens="perform the repair",
                    entry_criteria="marked repairable",
                    exit_criteria="repair work finished",
                ),
                StageSpec(
                    name="Quality Check",
                    owner_role="Service Manager",
                    what_happens="verify the repair meets standard",
                    entry_criteria="repair marked finished",
                    exit_criteria="quality check passed",
                ),
                StageSpec(
                    name="Return to Customer",
                    owner_role="Front Desk",
                    what_happens="notify customer and close the job",
                    entry_criteria="quality check passed, or unit deemed unrepairable",
                    exit_criteria="customer notified and job closed",
                ),
            )
        ),
        routing=Routing(
            points=(
                DecisionPoint(
                    at_stage="Diagnose",
                    field_name="Repairable",
                    options=("Yes", "No"),
                    route_per_option=(
                        ("Yes", ("Repair",)),
                        ("No", ("Return to Customer",)),
                    ),
                ),
            )
        ),
        rework_loops=ReworkLoops(
            loops=(
                LoopSpec(
                    from_stage="Quality Check",
                    to_stage="Repair",
                    gate_field="Quality Passed",
                    max_rounds=3,
                ),
            )
        ),
        data_model=DataModel(
            fields=(
                FieldReq(
                    name="Unit Name",
                    type=FieldType.TEXT,
                    required=True,
                    stage="Intake",
                    section="Intake Basics",
                ),
                FieldReq(
                    name="Customer Name",
                    type=FieldType.TEXT,
                    required=True,
                    stage="Intake",
                    section="Intake Basics",
                ),
                FieldReq(
                    name="Urgency",
                    type=FieldType.SELECT,
                    required=True,
                    stage="Intake",
                    list_name="Urgency Levels",
                    section="Intake Priority",
                ),
                FieldReq(
                    name="Repairable",
                    type=FieldType.SELECT,
                    required=True,
                    stage="Diagnose",
                    list_name="Yes No",
                ),
                FieldReq(
                    name="Diagnosis Notes",
                    type=FieldType.TEXTAREA,
                    required=False,
                    stage="Diagnose",
                    options=(("AllowFormatting", "true"),),
                ),
                FieldReq(
                    name="Quality Passed",
                    type=FieldType.BOOLEAN,
                    required=False,
                    stage="Quality Check",
                ),
                FieldReq(
                    name="Repair Cost",
                    type=FieldType.NUMBER,
                    required=False,
                    stage="Repair",
                    options=(("Decimalpoint", "2"),),
                ),
                # the computed field's real TARGET — an earlier round of this fixture
                # wired an
                # event onto a field name that was never declared anywhere; this is that
                # bug,
                # fixed (see test_computed_source_resolves_against_table_columns).
                FieldReq(
                    name="Total Parts Cost",
                    type=FieldType.NUMBER,
                    required=False,
                    stage="Repair",
                ),
            ),
            tables=(
                TableReq(
                    name="Parts Used",
                    stage="Repair",
                    columns=(
                        TableColumnReq(
                            name="Part Name", type=FieldType.TEXT, required=True
                        ),
                        TableColumnReq(
                            name="Quantity", type=FieldType.NUMBER, required=True
                        ),
                        TableColumnReq(
                            name="Unit Cost", type=FieldType.NUMBER, required=True
                        ),
                    ),
                    max_rows=20,
                ),
            ),
            computed=(
                ComputedReq(
                    target_field="Total Parts Cost",
                    source_fields=("Quantity", "Unit Cost"),
                    trigger=None,
                    formula_intent="quantity times unit cost, summed across every row",
                ),
            ),
            # two DISTINCT sections at the SAME stage — the exact shape a forced
            # section-equals-stage schema could never express.
            sections=(
                SectionReq(
                    name="Intake Basics",
                    stage="Intake",
                    description="the customer/unit identifying fields",
                ),
                SectionReq(
                    name="Intake Priority",
                    stage="Intake",
                    description="urgency and scheduling fields",
                ),
            ),
            sequence=SequenceReq(prefix="RPR", padding="0001"),
        ),
        master_data=MasterData(
            lists=(
                ListSpec(
                    name="Urgency Levels",
                    values=("High", "Medium", "Low"),
                    owner_role="Service Manager",
                ),
                ListSpec(
                    name="Yes No", values=("Yes", "No"), owner_role="Service Manager"
                ),
            )
        ),
        visibility=VisibilityMatrix(
            entries=(
                VisibilityEntry(
                    section="Intake Basics",
                    stage=START_STAGE,
                    permission=Visibility.EDITABLE,
                ),
                VisibilityEntry(
                    section="Intake Basics",
                    stage="Intake",
                    permission=Visibility.EDITABLE,
                ),
                VisibilityEntry(
                    section="Intake Priority",
                    stage="Intake",
                    permission=Visibility.EDITABLE,
                ),
                VisibilityEntry(
                    section="Intake Basics",
                    stage="Diagnose",
                    permission=Visibility.READONLY,
                ),
                VisibilityEntry(
                    section="Diagnose", stage="Diagnose", permission=Visibility.EDITABLE
                ),
                VisibilityEntry(
                    section="Parts Used", stage="Repair", permission=Visibility.EDITABLE
                ),
                VisibilityEntry(
                    section="Parts Used",
                    stage="Quality Check",
                    permission=Visibility.READONLY,
                ),
                VisibilityEntry(
                    section="Quality Check",
                    stage="Quality Check",
                    permission=Visibility.EDITABLE,
                ),
                # a field-level override: at Quality Check, only Repair Cost (inside the
                # "Repair"
                # section, being reviewed) is locked read-only — the rest of that
                # section is not
                # otherwise mentioned at this stage, so this is a targeted, single-field
                # rule.
                VisibilityEntry(
                    section="Repair",
                    stage="Quality Check",
                    permission=Visibility.READONLY,
                    field="Repair Cost",
                ),
            )
        ),
        timing=Timing(
            sla_notes="Diagnose must finish within 1 business day of intake",
            batch_days=("Friday",),
            reminders=("remind the technician if a job sits over 3 days",),
        ),
        personas=Personas(
            views=(
                PersonaView(
                    role="Service Manager",
                    pages=(
                        PageIntent(
                            name="Manager Dashboard",
                            widgets=(
                                WidgetIntent(
                                    slug="metrics",
                                    config=(
                                        ("flow_type", "process"),
                                        ("flow_id", "RepairJobs"),
                                    ),
                                ),
                                WidgetIntent(
                                    slug="view/table",
                                    config=(
                                        ("flow_type", "process"),
                                        ("flow_id", "RepairJobs"),
                                        ("view_id", "myitems"),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    kpis=("open jobs", "overdue jobs"),
                    actions=("reassign job", "approve quality check"),
                ),
                PersonaView(
                    role="Technician",
                    pages=(
                        PageIntent(
                            name="My Jobs",
                            widgets=(
                                WidgetIntent(
                                    slug="view/table",
                                    config=(
                                        ("flow_type", "process"),
                                        ("flow_id", "RepairJobs"),
                                        ("view_id", "assigned"),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    kpis=("jobs assigned to me",),
                    actions=("submit diagnosis", "mark repaired"),
                ),
                PersonaView(
                    role="Front Desk",
                    # deliberately the SAME page name as Service Manager, to exercise
                    # dedup + kpi/
                    # action/WIDGET aggregation across roles (F6): "general/label"
                    # appears ONLY here,
                    # never on Service Manager's copy of this page, so a passing
                    # test_build_page_aggregates_widgets_across_roles_not_just_first
                    # proves it isn't
                    # silently dropped just because Service Manager's PageIntent is the
                    # one
                    # _unique_pages happens to keep for page-identity purposes.
                    pages=(
                        PageIntent(
                            name="Manager Dashboard",
                            widgets=(
                                WidgetIntent(
                                    slug="metrics",
                                    config=(
                                        ("flow_type", "process"),
                                        ("flow_id", "RepairJobs"),
                                    ),
                                ),
                                WidgetIntent(
                                    slug="view/table",
                                    config=(
                                        ("flow_type", "process"),
                                        ("flow_id", "RepairJobs"),
                                        ("view_id", "myitems"),
                                    ),
                                ),
                                WidgetIntent(slug="general/label"),
                            ),
                        ),
                    ),
                    kpis=("jobs awaiting pickup",),
                    actions=("log new unit", "notify customer"),
                ),
            )
        ),
        test_cases=TestCases(
            cases=(
                CaseWalk(
                    name="Straightforward repair",
                    fills=(
                        StepFill(
                            stage="Intake",
                            values=(("Unit Name", "Printer"), ("Urgency", "Medium")),
                        ),
                        StepFill(stage="Diagnose", values=(("Repairable", "Yes"),)),
                        StepFill(
                            stage="Quality Check", values=(("Quality Passed", "true"),)
                        ),
                    ),
                    expected_path=(
                        "Intake",
                        "Diagnose",
                        "Repair",
                        "Quality Check",
                        "Return to Customer",
                    ),
                    expected_result="Repaired",
                ),
                CaseWalk(
                    name="Beyond repair",
                    fills=(
                        StepFill(
                            stage="Intake",
                            values=(
                                ("Unit Name", "Old Fax Machine"),
                                ("Urgency", "Low"),
                            ),
                        ),
                        StepFill(stage="Diagnose", values=(("Repairable", "No"),)),
                    ),
                    expected_path=("Intake", "Diagnose", "Return to Customer"),
                    expected_result="Beyond repair",
                ),
                CaseWalk(
                    # proves the exact expressiveness M11 demanded: the SAME stage
                    # visited twice
                    # with DIFFERENT values, so a rework-loop case can tick its Boolean
                    # gate false
                    # the first time and true the second — see
                    # test_looped_case_can_tick_gate_differently_per_visit
                    name="Rework then pass",
                    fills=(
                        StepFill(
                            stage="Intake",
                            values=(("Unit Name", "Blender"), ("Urgency", "High")),
                        ),
                        StepFill(stage="Diagnose", values=(("Repairable", "Yes"),)),
                        StepFill(
                            stage="Quality Check", values=(("Quality Passed", "false"),)
                        ),
                        StepFill(
                            stage="Quality Check", values=(("Quality Passed", "true"),)
                        ),
                    ),
                    expected_path=(
                        "Intake",
                        "Diagnose",
                        "Repair",
                        "Quality Check",
                        "Repair",
                        "Quality Check",
                        "Return to Customer",
                    ),
                    expected_result="Repaired",
                ),
            )
        ),
        approved=approved,
    )


def _built_fields(spec: Any) -> dict[str, Any]:
    """A draft carrying every field/table-column the spec asks for, engine-built."""
    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
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
    return FlowDraft.from_wire(bare).apply_changes(specs).to_wire()


def _msgs(rep: CompareReport) -> str:
    return "\n".join(rep.mismatches)


def test_wrong_field_type_and_missing_field_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    # break: retype Urgency (Select -> Text) and delete Quantity outright
    urgency = next(
        v for v in draft.values() if isinstance(v, dict) and v.get("Name") == "Urgency"
    )
    urgency["Type"] = "Text"
    qty = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Name") == "Quantity"
    )
    del draft[qty]
    rep = compare_built_to_spec(draft, spec)
    assert "built as 'Text', input asked 'Select'" in _msgs(rep)
    assert "field 'Quantity' (Number) asked for by the input is absent" in _msgs(rep)


def test_select_without_referredlist_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    urgency = next(
        v for v in draft.values() if isinstance(v, dict) and v.get("Name") == "Urgency"
    )
    urgency.pop("ReferredList", None)
    rep = compare_built_to_spec(draft, spec)
    assert "no ReferredList" in _msgs(rep)


def test_unrequested_extra_field_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft2 = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="Phantom", type=FieldType.TEXT)])
        .to_wire()
    )
    rep = compare_built_to_spec(draft2, spec)
    assert "'Phantom'" in _msgs(rep) and "never asked for it" in _msgs(rep)


def test_stranded_empty_banner_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft = (
        FlowDraft.from_wire(draft)
        .regroup_into_sections(
            [
                ("Intake Basics", ["Unit Name"]),
                ("Banner", []),
                ("Tail", ["Customer Name"]),
            ]
        )
        .to_wire()
    )
    rep = compare_built_to_spec(draft, spec)
    assert "stranded banner breaks the WHOLE form's render" in _msgs(rep)


def test_spurious_permission_on_hidden_column_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Column_Hidden1"] = {
        "Id": "Column_Hidden1",
        "Kind": "Column",
        "IsHidden": True,
    }
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
    draft = (
        FlowDraft.from_wire(draft)
        .build_workflow(
            [(s.name, None) for s in spec.stages.stages],
            parallel=("Route", [("A", [("A1", None)]), ("B", [("B1", None)])]),
            parallel_after=0,
        )
        .to_wire()
    )
    rep = compare_built_to_spec(draft, spec)
    assert "NO condition" in _msgs(rep) and "fail-open" in _msgs(rep)
    assert "no GotoTask targeting" in _msgs(rep)


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


def test_compare_report_ok() -> None:
    """`.as_tool_result()` (the old dict-with-"isError" shape) is NOT ported
    -- `ForgeCompareToSpec` builds its response DTO straight from `.ok()`/
    `.mismatches`/`.checked`/`.ignored` instead (see
    `use_cases/intake/forge_compare_to_spec.py` and
    `test_forge_compare_to_spec_response.py` for that payload's own
    parity check); this test keeps `.ok()` itself covered."""
    rep_ok = CompareReport(mismatches=(), checked={"fields": 5}, ignored=())
    assert rep_ok.ok() is True

    rep_err = CompareReport(mismatches=("error 1",), checked={}, ignored=("User",))
    assert rep_err.ok() is False


def test_sequence_number_missing_and_present_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    rep = compare_built_to_spec(draft, spec)
    assert (
        "input asks for an auto-numbered id (sequence) — no SequenceNumber field was "
        "built" in _msgs(rep)
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
    assert (
        "section 'Intake Basics' asked for by the input is absent from the form"
        in _msgs(rep)
    )
    assert "table 'Parts Used' asked for by the input has no host row" in _msgs(rep)


def test_empty_section_followed_by_table_model_is_accepted() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    root_id = draft["Root"]
    draft["Row_Banner"] = {
        "Id": "Row_Banner",
        "Kind": "Row",
        "Row::Column": ["Col_Banner"],
    }
    draft["Col_Banner"] = {
        "Id": "Col_Banner",
        "Kind": "Column",
        "Type": "Section",
        "Name": "TableBanner",
        "Column::Row": [],
    }
    draft["Row_Table"] = {
        "Id": "Row_Table",
        "Kind": "Row",
        "Row::Column": ["Col_Table"],
    }
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
    draft["Col_Seq"] = {
        "Id": "Col_Seq",
        "Kind": "Column",
        "Column::Field": ["Field_Seq"],
    }
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
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Name") == "Quantity"
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
    assert (
        "input declares 1 decision point(s), build has 0 Parallel gateway(s)"
        in _msgs(rep)
    )


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
    assert "loop 'Quality Check'->'Repair': GotoTask has NO gate condition" in _msgs(
        rep
    )


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
    from app.application.models.requests.intake.app_spec import Routing

    spec = _full_spec()
    spec_no_routing = spec.model_copy(update={"routing": Routing(points=())})
    draft = _built_fields(spec_no_routing)
    rep = compare_built_to_spec(draft, spec_no_routing)
    assert rep.checked["decision_points"] == 0


def test_fully_valid_built_draft_passes_all_checks() -> None:
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
    draft["Col_T1"] = {
        "Id": "Col_T1",
        "Kind": "Column",
        "Type": "Model",
        "Name": "Parts Used",
    }
    draft[root_id]["Model::Row"] = ["Row_S1", "Row_S2", "Row_T1"]

    # 3. Valid Appearance with exactly 1 Style
    for a in draft.values():
        if isinstance(a, dict) and a.get("Kind") == "Appearance":
            a["Appearance::Style"] = ["Style_Existing"]

    # 4. Computed field events with correct trigger ("onSelect" for Number fields
    # Quantity and Unit Cost)
    qty_id = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Name") == "Quantity"
    )
    cost_id = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Name") == "Unit Cost"
    )
    draft["Ev_Qty"] = {
        "Id": "Ev_Qty",
        "Kind": "Event",
        "Field": qty_id,
        "Trigger": "onSelect",
    }
    draft["Ev_Cost"] = {
        "Id": "Ev_Cost",
        "Kind": "Event",
        "Field": cost_id,
        "Trigger": "onSelect",
    }

    # 5. Workflow stages as activities
    for s in spec.stages.stages:
        draft[f"Act_{s.name}"] = {
            "Id": f"Act_{s.name}",
            "Kind": "Activity",
            "Name": s.name,
        }

    # Parallel gateway with conditional branches + one parallel without branches to test
    # empty branch_ids
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

    # Gotos: one matching target stage ("Repair") with condition, one targeting a
    # different stage ("Diagnose")
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
    spec_no_seq = spec.model_copy(
        update={"data_model": spec.data_model.model_copy(update={"sequence": None})}
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
        "Row_ColNotDict": {
            "Id": "Row_ColNotDict",
            "Kind": "Row",
            "Row::Column": ["Col_Missing"],
        },
    }
    rep = compare_built_to_spec(draft_empty_row, _full_spec())
    assert rep.ok() is False
