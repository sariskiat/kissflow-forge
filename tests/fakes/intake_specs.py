"""Shared AppSpec fixtures for the intake family's mirror tests.

`full_spec`/`linear_spec`/`branch_local_loop_spec` are the SAME synthetic
fixtures the pre-Stage-E `tests/test_intake.py` built by hand
(`_full_spec`/`_linear_spec`/`_branch_local_loop_spec`), copied here ONCE so
every mirror test file imports one shared module instead of a sibling test
module (`brief_stage_d_common.md` lesson 17: "A test never imports a sibling
test module. Put shared fakes in tests/fakes/<name>.py."). `tests/test_
coverage.py` (kept -- it exercises the domain coverage contract, not deleted
code) imports `branch_local_loop_spec` from here rather than from the
deleted `tests/test_intake.py` (Stage E).

Offline, synthetic AppSpec only -- no network, no live Kissflow calls. The
fixture specs below use a neutral, fictional business domain, never the real
app this engine was extracted from (CLAUDE.md BLINDNESS discipline).
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
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType, Visibility


def full_spec(*, approved: bool = True) -> AppSpec:
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


def linear_spec(*, approved: bool = True) -> AppSpec:
    """A deliberately minimal, straight-line app: NO branch, NO rework loop, NO
    reference list —
    all three confirmed explicitly `confirmed_none=True` rather than invented. Proves
    dimensions
    4/5/7 no longer force a business to manufacture fake divergence just to satisfy this
     schema
    (see `test_linear_spec_needs_no_branch_or_loop_or_list`). Timing is also left blank
    on
    purpose, doubling as proof that the advisory dimension does not block compilation
    either.
    """
    return AppSpec(
        app_name="Simple Ticket Log",
        problem_goal=ProblemGoal(
            pain="requests get lost with no record of who is handling them",
            goal="every request is logged and resolved",
            done_definition="the request is marked resolved",
            terminal_states=("Done",),
            result_values=("Resolved",),
        ),
        roles=Roles(
            roles=(
                RoleSpec(name="Front Desk", is_admin=False),
                RoleSpec(name="Manager", is_admin=True),
            )
        ),
        stages=Stages(
            stages=(
                StageSpec(
                    name="Log Ticket",
                    owner_role="Front Desk",
                    what_happens="record the request",
                    entry_criteria="a request comes in",
                    exit_criteria="ticket logged",
                ),
                StageSpec(
                    name="Handle Ticket",
                    owner_role="Manager",
                    what_happens="resolve the request",
                    entry_criteria="ticket logged",
                    exit_criteria="request resolved",
                ),
            )
        ),
        routing=Routing(points=(), confirmed_none=True),
        rework_loops=ReworkLoops(loops=(), confirmed_none=True),
        data_model=DataModel(
            fields=(
                FieldReq(
                    name="Request Text",
                    type=FieldType.TEXT,
                    required=True,
                    stage="Log Ticket",
                ),
            ),
            tables=(),
            computed=(),
        ),
        master_data=MasterData(lists=(), confirmed_none=True),
        visibility=VisibilityMatrix(
            entries=(
                VisibilityEntry(
                    section="Log Ticket",
                    stage=START_STAGE,
                    permission=Visibility.EDITABLE,
                ),
                VisibilityEntry(
                    section="Log Ticket",
                    stage="Log Ticket",
                    permission=Visibility.EDITABLE,
                ),
                VisibilityEntry(
                    section="Log Ticket",
                    stage="Handle Ticket",
                    permission=Visibility.READONLY,
                ),
                VisibilityEntry(
                    section="Handle Ticket",
                    stage="Handle Ticket",
                    permission=Visibility.EDITABLE,
                ),
            )
        ),
        timing=Timing(
            sla_notes="", batch_days=(), reminders=()
        ),  # left blank on purpose
        personas=Personas(
            views=(
                PersonaView(
                    role="Manager",
                    pages=(
                        PageIntent(
                            name="Tickets",
                            widgets=(WidgetIntent(slug="general/label"),),
                        ),
                    ),
                    kpis=(),
                    actions=(),
                ),
            )
        ),
        test_cases=TestCases(
            cases=(
                CaseWalk(
                    name="Simple ticket",
                    fills=(
                        StepFill(
                            stage="Log Ticket",
                            values=(("Request Text", "Fix the printer"),),
                        ),
                    ),
                    expected_path=("Log Ticket", "Handle Ticket"),
                    expected_result="Resolved",
                ),
            )
        ),
        approved=approved,
    )


def built_fields(spec: Any) -> dict[str, Any]:
    """A draft carrying every field/table-column the spec asks for,
    engine-built -- the same helper `tests/test_compare.py` builds by hand
    as `_built_fields`, moved here so every mirror test file imports one
    shared module (lesson 17)."""
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


def fully_valid_draft(spec: Any) -> dict[str, Any]:
    """`built_fields(spec)` plus every OTHER node the fidelity comparator
    checks for (sections, tables, a sequence field, well-formed appearance
    styles, computed-field events, workflow activities, a conditional
    parallel gateway, and a gated goto loop) -- the same nodes
    `tests/test_compare.py`'s own `test_fully_valid_built_draft_passes_all_
    checks` adds by hand, moved here (lesson 17) so `ForgeCompareToSpec`'s
    own mirror test can prove `ok: True` through the real port without
    importing a sibling test module. Built for `full_spec()`'s own shape
    specifically (its stage names, its "Quantity"/"Unit Cost" fields)."""
    draft = built_fields(spec)
    root_id = draft["Root"]

    draft["Field_Seq"] = {
        "Id": "Field_Seq",
        "Kind": "Field",
        "Name": "CaseId",
        "Type": "SequenceNumber",
    }

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

    for a in draft.values():
        if isinstance(a, dict) and a.get("Kind") == "Appearance":
            a["Appearance::Style"] = ["Style_Existing"]

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

    for s in spec.stages.stages:
        draft[f"Act_{s.name}"] = {
            "Id": f"Act_{s.name}",
            "Kind": "Activity",
            "Name": s.name,
        }

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
    return draft


def branch_local_loop_spec(*, approved: bool = True) -> AppSpec:
    """S3 (#34): a split whose 'Complex' branch is a SEQUENCE of stages
    (Deep Review -> Fix -> Verify) with a rework loop INSIDE that branch — Verify
    jumps back to Fix, gated on a Boolean. Both loop endpoints live in the same
    branch, so it is branch-local (never cross-branch). The 'Simple' branch is a
    single stage with no loop. Minimal but fully valid across all 11 dims."""
    return AppSpec(
        app_name="Claim Review",
        problem_goal=ProblemGoal(
            pain="claims get handled inconsistently",
            goal="every claim is triaged and closed",
            done_definition="the claim is closed",
            terminal_states=("Closed",),
            result_values=("Settled",),
        ),
        roles=Roles(
            roles=(
                RoleSpec(name="Intake", is_admin=False),
                RoleSpec(name="Adjuster", is_admin=True),
            )
        ),
        stages=Stages(
            stages=(
                StageSpec(
                    name="Log",
                    owner_role="Intake",
                    what_happens="log the claim",
                    entry_criteria="a claim arrives",
                    exit_criteria="claim logged",
                ),
                StageSpec(
                    name="Triage",
                    owner_role="Adjuster",
                    what_happens="decide the path",
                    entry_criteria="claim logged",
                    exit_criteria="path chosen",
                ),
                StageSpec(
                    name="Quick Close",
                    owner_role="Adjuster",
                    what_happens="close a simple claim",
                    entry_criteria="path is Simple",
                    exit_criteria="claim closed",
                ),
                StageSpec(
                    name="Deep Review",
                    owner_role="Adjuster",
                    what_happens="review a complex claim",
                    entry_criteria="path is Complex",
                    exit_criteria="reviewed",
                ),
                StageSpec(
                    name="Fix",
                    owner_role="Adjuster",
                    what_happens="correct the claim",
                    entry_criteria="review found an issue",
                    exit_criteria="corrected",
                ),
                StageSpec(
                    name="Verify",
                    owner_role="Adjuster",
                    what_happens="verify the correction",
                    entry_criteria="corrected",
                    exit_criteria="verified",
                ),
                StageSpec(
                    name="Close",
                    owner_role="Intake",
                    what_happens="close the claim",
                    entry_criteria="verified or quick-closed",
                    exit_criteria="closed",
                ),
            )
        ),
        routing=Routing(
            points=(
                DecisionPoint(
                    at_stage="Triage",
                    field_name="Path",
                    options=("Simple", "Complex"),
                    route_per_option=(
                        ("Simple", ("Quick Close",)),
                        ("Complex", ("Deep Review", "Fix", "Verify")),
                    ),
                ),
            )
        ),
        rework_loops=ReworkLoops(
            loops=(
                LoopSpec(
                    from_stage="Verify",
                    to_stage="Fix",
                    gate_field="Fix Approved",
                    max_rounds=3,
                ),
            )
        ),
        data_model=DataModel(
            fields=(
                FieldReq(
                    name="Claim Text", type=FieldType.TEXT, required=True, stage="Log"
                ),
                FieldReq(
                    name="Path",
                    type=FieldType.SELECT,
                    required=True,
                    stage="Triage",
                    list_name="Paths",
                ),
                FieldReq(
                    name="Fix Approved",
                    type=FieldType.BOOLEAN,
                    required=False,
                    stage="Verify",
                ),
            ),
            tables=(),
            computed=(),
        ),
        master_data=MasterData(
            lists=(
                ListSpec(
                    name="Paths", values=("Simple", "Complex"), owner_role="Adjuster"
                ),
            )
        ),
        visibility=VisibilityMatrix(
            entries=(
                VisibilityEntry(
                    section="Log", stage=START_STAGE, permission=Visibility.EDITABLE
                ),
                VisibilityEntry(
                    section="Log", stage="Log", permission=Visibility.EDITABLE
                ),
                VisibilityEntry(
                    section="Triage", stage="Triage", permission=Visibility.EDITABLE
                ),
                VisibilityEntry(
                    section="Verify", stage="Verify", permission=Visibility.EDITABLE
                ),
            )
        ),
        timing=Timing(sla_notes="", batch_days=(), reminders=()),
        personas=Personas(
            views=(
                PersonaView(
                    role="Adjuster",
                    pages=(
                        PageIntent(
                            name="Board", widgets=(WidgetIntent(slug="general/label"),)
                        ),
                    ),
                    kpis=(),
                    actions=(),
                ),
            )
        ),
        test_cases=TestCases(
            cases=(
                CaseWalk(
                    name="Complex claim, one rework round",
                    fills=(
                        StepFill(stage="Log", values=(("Claim Text", "Water damage"),)),
                        StepFill(stage="Triage", values=(("Path", "Complex"),)),
                        StepFill(stage="Verify", values=(("Fix Approved", "true"),)),
                    ),
                    expected_path=(
                        "Log",
                        "Triage",
                        "Deep Review",
                        "Fix",
                        "Verify",
                        "Close",
                    ),
                    expected_result="Settled",
                ),
            )
        ),
        approved=approved,
    )
