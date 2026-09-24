"""Mirror tests for `app.application.use_cases.intake._compile` -- ported
from `tests/test_intake.py`'s compile.py coverage (Stage D group 8; the
module moved from `app.application.intake.compile`).
"""

from __future__ import annotations

import pytest

from app.application.models.requests.intake.app_spec import (
    START_STAGE,
    AppSpec,
    CaseWalk,
    ClickActionKind,
    ComputedReq,
    DataModel,
    DecisionPoint,
    DesignNode,
    EventTrigger,
    FieldReq,
    ListSpec,
    LoopSpec,
    MasterData,
    OnClickAction,
    PageIntent,
    Personas,
    PersonaView,
    PopupIntent,
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
from app.application.use_cases.intake._compile import (
    OP_ORDER,
    BuildPlan,
    Op,
    compile_spec,
)
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


def _linear_spec(*, approved: bool = True) -> AppSpec:
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


def _branch_local_loop_spec(*, approved: bool = True) -> AppSpec:
    """S3 (#34): a split whose 'Complex' branch is a SEQUENCE of stages (Deep Review ->
    Fix ->
    Verify) with a rework loop INSIDE that branch — Verify jumps back to Fix, gated on a
     Boolean.
    Both loop endpoints live in the same branch, so it is branch-local (never
    cross-branch). The
    'Simple' branch is a single stage with no loop. Minimal but fully valid across all
    11 dims."""
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


def _dims(gaps: tuple[str, ...]) -> list[int]:
    """Dimension numbers named by a `gaps()` result, in order (each sentence is `"N.
    name: ..."`)."""
    return [int(s.split(".", 1)[0]) for s in gaps]


def _replace_data_model(spec: AppSpec, **kwargs: object) -> AppSpec:
    """Convenience: `.model_copy(update=...)` one level deeper, into
    `spec.data_model`."""
    return spec.model_copy(
        update={"data_model": spec.data_model.model_copy(update={**kwargs})}
    )


def _apply_field(plan: BuildPlan, stage: str, field_name: str) -> dict:
    op = next(
        o for o in plan.ops if o.kind == "apply_fields" and o.args["stage"] == stage
    )
    return next(f for f in op.args["fields"] if f["name"] == field_name)


def _workflow_op(spec: AppSpec) -> Op:
    return next(op for op in compile_spec(spec).ops if op.kind == "build_workflow")


def test_one_split_compiles_to_a_parallel_with_its_branches() -> None:
    """S1 (#32) AC1: the single DecisionPoint in _full_spec (Diagnose -> Yes:Repair /
    No:Return) is lifted into a Parallel gateway whose branches ARE the option route
    sequences, and the branch stages are removed from the linear spine. Still ONE
    build_workflow op (the whole ProcessDef), now carrying the parallel structure
    FlowDraft.build_workflow consumes."""
    op = _workflow_op(_full_spec())
    # branch stages lifted out of the linear spine; the fork stem and merge stay linear
    assert op.args["steps"] == ("Intake", "Diagnose", "Quality Check")
    parallels = op.args["parallels"]
    assert len(parallels) == 1
    parallel = parallels[0]
    assert parallel["name"] == "Repairable"  # the deciding field
    assert parallel["after"] == 1  # inserted right after "Diagnose"
    assert parallel["branches"] == (
        {"name": "Yes", "stages": ("Repair",)},
        {"name": "No", "stages": ("Return to Customer",)},
    )


def test_split_branch_may_be_a_multi_stage_sequence() -> None:
    """A branch is an ORDERED SEQUENCE of stages (P1 #30): the whole sequence becomes
    ONE Parallel branch, in order, every stage lifted out of the linear spine."""
    spec = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=("Yes", "No"),
                        route_per_option=(
                            ("Yes", ("Repair", "Quality Check")),
                            ("No", ("Return to Customer",)),
                        ),
                    ),
                )
            )
        }
    )
    parallel = _workflow_op(spec).args["parallels"][0]
    assert parallel["branches"][0] == {
        "name": "Yes",
        "stages": ("Repair", "Quality Check"),
    }
    # both branch's stages are gone from the linear spine; only stem + prefix remain
    assert _workflow_op(spec).args["steps"] == ("Intake", "Diagnose")


def test_branch_order_follows_declared_options_not_route_map_order() -> None:
    """Branch order is the DECIDING FIELD's declared option order, so it lines up with
    the diagram (which iterates `options`) and with S4's per-branch conditions — not
    whatever order route_per_option's pairs happen to be written in."""
    spec = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=("Yes", "No"),
                        # route pairs written No-first on purpose
                        route_per_option=(
                            ("No", ("Return to Customer",)),
                            ("Yes", ("Repair",)),
                        ),
                    ),
                )
            )
        }
    )
    names = [b["name"] for b in _workflow_op(spec).args["parallels"][0]["branches"]]
    assert names == ["Yes", "No"]


def test_linear_spec_has_no_parallel() -> None:
    """S1 (#32) AC3: a spec with no decision split is unaffected — no Parallels, steps
    are simply every stage in order."""
    op = _workflow_op(_linear_spec())
    assert op.args["parallels"] == ()
    assert op.args["steps"] == tuple(s.name for s in _linear_spec().stages.stages)


# ---- S2 (#33): N sequential splits — split, rejoin, later split, rejoin --------------


def test_two_sequential_splits_compile_to_two_parallels_in_order() -> None:
    """D3 (#29 spec decisions): S2 generalises S1's one-split shape to N SEQUENTIAL
    splits. Two independent DecisionPoints — Diagnose (existing) and a new one at
    Quality Check, each on its own field with its own distinct branch stages and
    distinct option names — compile to two Parallel gateways, in declared point
    order, and BOTH splits' branch stages are lifted out of the ONE shared linear
    spine."""
    full = _full_spec()
    spec = full.model_copy(
        update={
            "stages": Stages(
                stages=full.stages.stages
                + (
                    StageSpec(
                        name="Escalate to Manager",
                        owner_role="Service Manager",
                        what_happens="escalate the finished job for a second look",
                        entry_criteria="quality check flagged it for escalation",
                        exit_criteria="manager has reviewed it",
                    ),
                    StageSpec(
                        name="Notify Front Desk",
                        owner_role="Front Desk",
                        what_happens="tell front desk the job is ready",
                        entry_criteria="quality check passed with nothing to escalate",
                        exit_criteria="front desk notified",
                    ),
                )
            ),
            "data_model": full.data_model.model_copy(
                update={
                    "fields": full.data_model.fields
                    + (
                        FieldReq(
                            name="Escalate",
                            type=FieldType.SELECT,
                            required=True,
                            stage="Quality Check",
                            list_name="Escalate Options",
                        ),
                    )
                }
            ),
            "master_data": MasterData(
                lists=full.master_data.lists
                + (
                    ListSpec(
                        name="Escalate Options",
                        values=("Escalate", "Close"),
                        owner_role="Service Manager",
                    ),
                )
            ),
            "routing": Routing(
                points=(
                    full.routing.points[0],
                    DecisionPoint(
                        at_stage="Quality Check",
                        field_name="Escalate",
                        options=("Escalate", "Close"),
                        route_per_option=(
                            ("Escalate", ("Escalate to Manager",)),
                            ("Close", ("Notify Front Desk",)),
                        ),
                    ),
                )
            ),
        }
    )
    op = _workflow_op(spec)
    assert op.args["steps"] == ("Intake", "Diagnose", "Quality Check")
    parallels = op.args["parallels"]
    assert len(parallels) == 2
    first, second = parallels
    assert first["name"] == "Repairable"
    assert first["after"] == 1  # right after "Diagnose"
    assert first["branches"] == (
        {"name": "Yes", "stages": ("Repair",)},
        {"name": "No", "stages": ("Return to Customer",)},
    )
    assert second["name"] == "Escalate"
    assert second["after"] == 2  # right after "Quality Check"
    assert second["branches"] == (
        {"name": "Escalate", "stages": ("Escalate to Manager",)},
        {"name": "Close", "stages": ("Notify Front Desk",)},
    )


def _dashboard_with_behavior() -> AppSpec:
    """`_full_spec()` with the two roles that share 'Manager Dashboard' each declaring
    their OWN
    popup + on-click wiring — so aggregation across roles (not just the first) is
    exercised. Both
    actions used (`reassign job`, `notify customer`) are ones their own role already
    declares."""
    full = _full_spec()
    sm_view = full.personas.views[0]  # Service Manager, declares "reassign job"
    sm_page = sm_view.pages[0].model_copy(
        update={
            "popups": (
                PopupIntent(
                    name="Job Detail", widgets=(WidgetIntent(slug="general/label"),)
                ),
            ),
            "on_click": (
                OnClickAction(
                    action="reassign job",
                    kind=ClickActionKind.OPEN_POPUP,
                    target_popup="Job Detail",
                ),
            ),
        }
    )
    sm2 = sm_view.model_copy(update={"pages": (sm_page,)})
    fd_view = full.personas.views[
        2
    ]  # Front Desk, same page name, declares "notify customer"
    fd_page = fd_view.pages[0].model_copy(
        update={
            "popups": (
                PopupIntent(
                    name="Unit Detail", widgets=(WidgetIntent(slug="general/label"),)
                ),
            ),
            "on_click": (
                OnClickAction(
                    action="notify customer",
                    kind=ClickActionKind.JS_ACTION,
                    script="kf.doThing()",
                ),
            ),
        }
    )
    fd2 = fd_view.model_copy(update={"pages": (fd_page,)})
    return full.model_copy(
        update={"personas": Personas(views=(sm2, full.personas.views[1], fd2))}
    )


def _rich_design() -> DesignNode:
    """A small but real beautiful-page tree: page shell -> hero (styled) + card, each
    with a widget
    inside. Depth and styling mirror the recipes in page.design.md."""
    return DesignNode(
        kind="container",
        name="page shell",
        style=(
            ("Container.Background", "#FCFAF2"),
            ("Container.Flex.Direction", "column"),
            ("Container.Row.Gap", "16px"),
        ),
        children=(
            DesignNode(
                kind="container",
                name="hero",
                style=(
                    ("Container.Background", "#2E6B3B"),
                    ("Container.Padding.Top", "32px"),
                ),
                children=(
                    DesignNode(
                        kind="widget",
                        name="hero title",
                        style=(("Label.Color", "token:Color.White"),),
                        widget=WidgetIntent(
                            slug="general/label",
                            config=(("title", "Submit your case"),),
                        ),
                    ),
                ),
            ),
            DesignNode(
                kind="container",
                name="card",
                style=(("Container.Background", "#FFFFFF"),),
                children=(
                    DesignNode(
                        kind="widget",
                        name="form",
                        widget=WidgetIntent(
                            slug="view/form",
                            config=(
                                ("flow_type", "process"),
                                ("flow_id", "RepairJobs"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _spec_with_design(design: DesignNode) -> AppSpec:
    base = _full_spec()
    v0 = base.personas.views[0]
    page = PageIntent(name="Submit Case", widgets=(), design=design)
    view = v0.model_copy(update={"pages": (page,)})
    return base.model_copy(
        update={"personas": Personas(views=(view, *base.personas.views[1:]))}
    )


def test_linear_spec_needs_no_branch_or_loop_or_list() -> None:
    """The exact bug M14 named: a straight-line flow used to have to invent a fake
    DecisionPoint and a fake LoopSpec. Proven fixed: this spec has NEITHER, is fully
    valid, and
    compiles to zero add_goto_gate / create_list ops."""
    plan = compile_spec(_linear_spec())
    summary = plan.summary()
    assert summary.get("add_goto_gate", 0) == 0
    assert summary.get("create_list", 0) == 0
    assert sum(summary.values()) == len(plan.ops) == 17
    assert set(summary) <= set(OP_ORDER)


def test_compile_refuses_unapproved_spec() -> None:
    with pytest.raises(ValueError, match="confirmation required first"):
        compile_spec(_full_spec(approved=False))


def test_compile_refuses_incomplete_spec_and_lists_gaps() -> None:
    spec = _full_spec().model_copy(update={"roles": Roles(roles=())})
    with pytest.raises(ValueError, match=r"2\. roles"):
        compile_spec(spec)


def test_compile_does_not_refuse_over_advisory_timing_alone() -> None:
    """M13: do not keep gating on data the engine cannot act on."""
    spec = _full_spec().model_copy(
        update={"timing": Timing(sla_notes="", batch_days=(), reminders=())}
    )
    plan = compile_spec(spec)  # must NOT raise
    assert isinstance(plan, BuildPlan)


def test_set_assignees_carries_stage_and_owner_role() -> None:
    plan = compile_spec(_full_spec())
    assignee_ops = [op for op in plan.ops if op.kind == "set_assignees"]
    assert len(assignee_ops) == 5
    pairs = sorted((op.args["stage"], op.args["owner_role"]) for op in assignee_ops)
    assert pairs == sorted(
        [
            ("Intake", "Front Desk"),
            ("Diagnose", "Technician"),
            ("Repair", "Technician"),
            ("Quality Check", "Service Manager"),
            ("Return to Customer", "Front Desk"),
        ]
    )
    for op in assignee_ops:
        assert "AppRole" in op.why


def test_set_assignees_sits_between_build_workflow_and_add_goto_gate() -> None:
    i_workflow = OP_ORDER.index("build_workflow")
    i_assignees = OP_ORDER.index("set_assignees")
    i_goto = OP_ORDER.index("add_goto_gate")
    assert i_workflow < i_assignees < i_goto


def test_set_branch_conditions_sits_between_add_goto_gate_and_set_visibility() -> None:
    """S4 (#35): the branch-condition op that turns S1's unconditional Parallel into a
    real
    conditional split belongs right after the Goto gates (Build order step 7 covers both
     the
    per-branch loop half and the deciding-field half together) and before the visibility
     matrix
    (Build order step 8)."""
    i_goto = OP_ORDER.index("add_goto_gate")
    i_branch_conditions = OP_ORDER.index("set_branch_conditions")
    i_visibility = OP_ORDER.index("set_visibility")
    assert i_goto < i_branch_conditions < i_visibility


def test_create_list_carries_values_and_is_executable() -> None:
    """#13: the gate lifted — a non-personal list compiles to an EXECUTABLE op naming
    forge_create_list, values still carried verbatim."""
    plan = compile_spec(_full_spec())
    list_ops = [op for op in plan.ops if op.kind == "create_list"]
    assert len(list_ops) == 2
    by_name = {op.args["name"]: op for op in list_ops}
    assert by_name["Urgency Levels"].args["values"] == ("High", "Medium", "Low")
    assert by_name["Yes No"].args["values"] == ("Yes", "No")
    for op in list_ops:
        assert "HUMAN-GATED" not in op.why
        assert "forge_create_list" in op.why


def test_create_list_personal_data_stays_human_gated() -> None:
    """PDPA (D2/D9): a personal_data list keeps the human gate — values still in the
    plan, the
    why forbids forge_create_list from writing it."""
    full = _full_spec()
    flagged = tuple(
        lst.model_copy(update={"personal_data": lst.name == "Urgency Levels"})
        for lst in full.master_data.lists
    )
    spec = full.model_copy(
        update={"master_data": full.master_data.model_copy(update={"lists": flagged})}
    )
    plan = compile_spec(spec)
    by_name = {op.args["name"]: op for op in plan.ops if op.kind == "create_list"}
    assert "HUMAN-GATED" in by_name["Urgency Levels"].why
    assert "personal_data" in by_name["Urgency Levels"].why
    assert by_name["Urgency Levels"].args["values"] == ("High", "Medium", "Low")
    assert "HUMAN-GATED" not in by_name["Yes No"].why


def test_create_list_precedes_apply_fields() -> None:
    assert OP_ORDER.index("create_list") < OP_ORDER.index("apply_fields")


def test_apply_fields_binds_every_select_to_the_list_the_plan_creates() -> None:
    """The binding, stated in the payload: the Select names its list AND the op whose
    result
    supplies the id. `referred_list` itself stays None — a compile-time id would be a
    fiction."""
    plan = compile_spec(_full_spec())
    created = {op.args["name"] for op in plan.ops if op.kind == "create_list"}
    for stage, field, list_name in (
        ("Intake", "Urgency", "Urgency Levels"),
        ("Diagnose", "Repairable", "Yes No"),
    ):
        got = _apply_field(plan, stage, field)
        assert got["referred_list"] is None, "no id can exist at compile time"
        assert got["referred_list_from"] == {
            "list_name": list_name,
            "from_op": "create_list",
            "personal_data": False,
        }
        assert list_name in created, (
            "the op the binding names must actually be in the plan"
        )


def test_apply_fields_states_the_substitution_contract_in_its_why() -> None:
    """The contract travels with the op, not in a reader's head: WHO substitutes the id,
     from
    WHERE, and what happens if nobody does."""
    plan = compile_spec(_full_spec())
    why = next(
        op
        for op in plan.ops
        if op.kind == "apply_fields" and op.args["stage"] == "Intake"
    ).why
    assert "referred_list_from" in why and "create_list" in why
    assert "referred_list" in why


def test_a_personal_data_list_binds_to_the_human_made_list_not_to_create_list() -> None:
    """PDPA (D2/D9) survives the binding: a personal_data list is never routed into
    forge_create_list, so its Select's id comes from the HUMAN-made list, and the
    binding says so
    (`from_op` None) instead of naming an op that must not run."""
    full = _full_spec()
    flagged = tuple(
        lst.model_copy(update={"personal_data": lst.name == "Urgency Levels"})
        for lst in full.master_data.lists
    )
    plan = compile_spec(
        full.model_copy(
            update={
                "master_data": full.master_data.model_copy(update={"lists": flagged})
            }
        )
    )
    got = _apply_field(plan, "Intake", "Urgency")
    assert got["referred_list_from"] == {
        "list_name": "Urgency Levels",
        "from_op": None,
        "personal_data": True,
    }
    by_name = {op.args["name"]: op for op in plan.ops if op.kind == "create_list"}
    assert "HUMAN-GATED" in by_name["Urgency Levels"].why


def test_a_non_select_field_carries_no_list_binding_at_all() -> None:
    """The control: only a Select takes a ReferredList, so every other field states the
    ABSENCE
    of a binding rather than leaving the key off and making 'no list' unaskable."""
    plan = compile_spec(_full_spec())
    got = _apply_field(plan, "Intake", "Unit Name")
    assert got["referred_list"] is None and got["referred_list_from"] is None


def test_a_select_with_no_backing_list_refuses_at_compile_naming_its_coverage_row() -> (
    None
):
    """ADR-0004: a dropdown backed by no list at all is refused at COMPILE, naming its
    coverage
    row — never left to fail at write time with a 500 nobody can read."""
    full = _full_spec()
    bad = _replace_data_model(
        full,
        fields=tuple(
            f.model_copy(update={"list_name": None}) if f.name == "Urgency" else f
            for f in full.data_model.fields
        ),
    )
    with pytest.raises(ValueError, match="word-list-dropdown"):
        compile_spec(bad)


def test_check_loop_gate_unknown_field_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Quality Check",
                        to_stage="Repair",
                        gate_field="Does Not Exist",
                        max_rounds=3,
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


def test_check_loop_gate_wrong_type_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Quality Check",
                        to_stage="Repair",
                        gate_field="Repair Cost",
                        max_rounds=3,
                    ),  # Repair Cost is Number, not Boolean
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Repair Cost"):
        compile_spec(bad)


def test_check_routing_unknown_at_stage_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Nonexistent Stage",
                        field_name="Repairable",
                        options=("Yes", "No"),
                        route_per_option=(
                            ("Yes", ("Repair",)),
                            ("No", ("Return to Customer",)),
                        ),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_check_routing_unknown_target_stage_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=("Yes", "No"),
                        route_per_option=(
                            ("Yes", ("Nonexistent Target",)),
                            ("No", ("Return to Customer",)),
                        ),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Nonexistent Target"):
        compile_spec(bad)


def test_check_routing_unrouted_option_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=("Yes", "No", "Maybe Later"),
                        route_per_option=(
                            ("Yes", ("Repair",)),
                            ("No", ("Return to Customer",)),
                        ),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="routed options"):
        compile_spec(bad)


def test_check_routing_literal_not_in_list_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=("Yes", "Maybe"),
                        route_per_option=(("Yes", ("Repair",)), ("Maybe", ("Repair",))),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Maybe"):
        compile_spec(bad)


def test_a_branch_route_may_be_a_sequence_of_stages() -> None:
    """P1 (#30): route_per_option maps an option to an ORDERED LIST of stages; compile
    accepts a
    multi-stage branch as long as every named stage is real (a one-element list is the
    old
    single-stage route). Building it as a Parallel is S1 (#32) — here it only has to
    compile."""
    spec = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=("Yes", "No"),
                        route_per_option=(
                            ("Yes", ("Repair", "Quality Check")),
                            ("No", ("Return to Customer",)),
                        ),
                    ),
                )
            )
        }
    )
    compile_spec(spec)


def test_check_routing_empty_target_sequence_raises() -> None:
    """A route to an EMPTY sequence names no stage at all — a dead-end the single-stage
    shape could
    never express. The list shape makes it possible, so compile must refuse it
    loudly."""
    bad = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=("Yes", "No"),
                        route_per_option=(("Yes", ()), ("No", ("Return to Customer",))),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="empty"):
        compile_spec(bad)


def test_check_loop_unknown_from_stage_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Nonexistent",
                        to_stage="Repair",
                        gate_field="Quality Passed",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Nonexistent"):
        compile_spec(bad)


def test_check_loop_unknown_to_stage_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Quality Check",
                        to_stage="Nonexistent",
                        gate_field="Quality Passed",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Nonexistent"):
        compile_spec(bad)


def test_check_loop_forward_direction_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Intake",
                        to_stage="Repair",
                        gate_field="Quality Passed",
                    ),  # forward!
                )
            )
        }
    )
    with pytest.raises(ValueError, match="not backward"):
        compile_spec(bad)


def test_two_sections_at_one_stage_expressible() -> None:
    plan = compile_spec(_full_spec())
    intake_ops = [
        op
        for op in plan.ops
        if op.kind == "apply_fields" and op.args["stage"] == "Intake"
    ]
    assert len(intake_ops) == 1
    sections_used = {f["section"] for f in intake_ops[0].args["fields"]}
    assert sections_used == {"Intake Basics", "Intake Priority"}


def test_check_section_unknown_stage_raises() -> None:
    full = _full_spec()
    bad = _replace_data_model(
        full,
        sections=full.data_model.sections
        + (
            SectionReq(
                name="Orphan Section", stage="Nonexistent Stage", description="desc"
            ),
        ),
    )
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_check_field_unknown_section_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        f.model_copy(update={"section": "No Such Section"})
        if f.name == "Repairable"
        else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="No Such Section"):
        compile_spec(bad)


def test_check_field_section_belongs_to_different_stage_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        f.model_copy(update={"section": "Intake Basics"})
        if f.name == "Repairable"
        else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Repairable"):
        compile_spec(bad)


def test_visibility_field_level_entry_present() -> None:
    plan = compile_spec(_full_spec())
    vis_op = next(op for op in plan.ops if op.kind == "set_visibility")
    field_entries = [e for e in vis_op.args["entries"] if e["field"] is not None]
    assert len(field_entries) == 1
    assert field_entries[0]["field"] == "Repair Cost"


def test_check_visibility_unknown_field_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "visibility": VisibilityMatrix(
                entries=(
                    VisibilityEntry(
                        section="Intake",
                        stage="Intake",
                        permission=Visibility.EDITABLE,
                        field="Does Not Exist",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


def test_check_start_not_owned_raises() -> None:
    full = _full_spec()
    entries_without_start = tuple(
        e for e in full.visibility.entries if e.stage != START_STAGE
    )
    bad = full.model_copy(
        update={"visibility": VisibilityMatrix(entries=entries_without_start)}
    )
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


def test_check_start_owned_by_wrong_section_raises() -> None:
    full = _full_spec()
    entries = tuple(
        VisibilityEntry(
            section="Parts Used", stage=START_STAGE, permission=Visibility.EDITABLE
        )
        if e.stage == START_STAGE
        else e
        for e in full.visibility.entries
    )
    bad = full.model_copy(update={"visibility": VisibilityMatrix(entries=entries)})
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


def test_add_table_columns_carry_type_and_required() -> None:
    plan = compile_spec(_full_spec())
    table_op = next(op for op in plan.ops if op.kind == "add_table")
    cols = {c["name"]: c for c in table_op.args["columns"]}
    assert cols["Part Name"] == {"name": "Part Name", "type": "Text", "required": True}
    assert cols["Quantity"]["type"] == "Number"


def test_check_table_unknown_stage_raises() -> None:
    full = _full_spec()
    bad_tables = tuple(
        t.model_copy(update={"stage": "Nonexistent"}) for t in full.data_model.tables
    )
    bad = _replace_data_model(full, tables=bad_tables)
    with pytest.raises(ValueError, match="Nonexistent"):
        compile_spec(bad)


def test_check_table_non_positive_max_rows_raises() -> None:
    full = _full_spec()
    bad_tables = tuple(
        t.model_copy(update={"max_rows": 0}) for t in full.data_model.tables
    )
    bad = _replace_data_model(full, tables=bad_tables)
    with pytest.raises(ValueError, match="max_rows"):
        compile_spec(bad)


def test_check_computed_unknown_target_raises() -> None:
    full = _full_spec()
    bad = _replace_data_model(
        full,
        computed=(
            ComputedReq(
                target_field="Does Not Exist",
                source_fields=("Quantity", "Unit Cost"),
                trigger=EventTrigger.ON_CHANGE,
                formula_intent="x",
            ),
        ),
    )
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


def test_check_computed_unknown_source_raises() -> None:
    full = _full_spec()
    bad = _replace_data_model(
        full,
        computed=(
            ComputedReq(
                target_field="Total Parts Cost",
                source_fields=("Nonexistent Column",),
                trigger=EventTrigger.ON_CHANGE,
                formula_intent="x",
            ),
        ),
    )
    with pytest.raises(ValueError, match="Nonexistent Column"):
        compile_spec(bad)


def test_computed_source_resolves_against_table_columns() -> None:
    """The original bug M10 named: a computed field wired onto columns that don't exist.
     Proven
    fixed — `_full_spec()` itself compiles clean with source_fields pointing at real
    Parts Used table columns, not a phantom field."""
    plan = compile_spec(_full_spec())
    events = [op for op in plan.ops if op.kind == "set_events"]
    assert len(events) == 1
    assert events[0].args["source_fields"] == ("Quantity", "Unit Cost")
    assert events[0].args["target_field"] == "Total Parts Cost"


def test_set_events_flags_unverified_trigger() -> None:
    """A Boolean source derives onClick by FAMILY inference, never captured live — the
    op's why
    must carry UNVERIFIED naming that source (#12)."""
    full = _full_spec()
    bad_computed = tuple(
        c.model_copy(update={"trigger": None, "source_fields": ("Quality Passed",)})
        for c in full.data_model.computed
    )
    spec = _replace_data_model(full, computed=bad_computed)
    plan = compile_spec(spec)
    event_op = next(op for op in plan.ops if op.kind == "set_events")
    assert "UNVERIFIED" in event_op.why
    assert "Quality Passed" in event_op.why


def test_set_events_confirms_live_observed_trigger() -> None:
    """Number sources -> onSelect is a live-observed pair; the op's why says CONFIRMED
    and the
    derived per-source triggers land in args (#12)."""
    plan = compile_spec(_full_spec())
    event_op = next(op for op in plan.ops if op.kind == "set_events")
    assert "CONFIRMED" in event_op.why
    assert event_op.args["triggers"] == {
        "Quantity": "onSelect",
        "Unit Cost": "onSelect",
    }


def test_trigger_derived_per_source_family() -> None:
    """#12: one source per trigger family — Select->onClick, Number->onSelect,
    Text->onChange —
    derived from the source field's own type, never defaulted to onChange."""
    full = _full_spec()
    spec = _replace_data_model(
        full,
        computed=(
            ComputedReq(
                target_field="Total Parts Cost",
                source_fields=("Urgency", "Quantity", "Unit Name"),
                trigger=None,
                formula_intent="derived-trigger fan-out",
            ),
        ),
    )
    plan = compile_spec(spec)
    event_op = next(op for op in plan.ops if op.kind == "set_events")
    assert event_op.args["triggers"] == {
        "Urgency": "onClick",  # Select — live-observed (was wrongly onChange before
        # #12)
        "Quantity": "onSelect",  # Number — live-observed (Date shares the family)
        "Unit Name": "onChange",  # Text — live-observed
    }


def test_trigger_explicit_mismatch_refused() -> None:
    """An explicit trigger that the source's type can never fire is refused at compile
    with the
    derived trigger named — not written and discovered never (#12)."""
    full = _full_spec()
    spec = _replace_data_model(
        full,
        computed=(
            ComputedReq(
                target_field="Total Parts Cost",
                source_fields=("Quantity",),
                trigger=EventTrigger.ON_CHANGE,
                formula_intent="x",
            ),
        ),
    )
    with pytest.raises(ValueError, match="onSelect"):
        compile_spec(spec)


def test_trigger_attachment_source_refused() -> None:
    """An Attachment source takes no events at all (CLAUDE.md Field events) — refused
    loudly,
    never downgraded to some trigger that cannot exist."""
    full = _full_spec()
    spec = _replace_data_model(
        full,
        fields=full.data_model.fields
        + (
            FieldReq(
                name="Damage Photos",
                type=FieldType.ATTACHMENT,
                required=False,
                stage="Intake",
            ),
        ),
        computed=(
            ComputedReq(
                target_field="Total Parts Cost",
                source_fields=("Damage Photos",),
                trigger=None,
                formula_intent="x",
            ),
        ),
    )
    with pytest.raises(ValueError, match="no events"):
        compile_spec(spec)


def test_check_case_unknown_fill_field_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "test_cases": TestCases(
                cases=(
                    CaseWalk(
                        name="Bad case",
                        fills=(
                            StepFill(stage="Intake", values=(("Does Not Exist", "x"),)),
                        ),
                        expected_path=("Intake",),
                        expected_result="Repaired",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


def test_check_case_select_value_not_in_list_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "test_cases": TestCases(
                cases=(
                    CaseWalk(
                        name="Bad case",
                        fills=(
                            StepFill(stage="Intake", values=(("Urgency", "Critical"),)),
                        ),
                        expected_path=("Intake",),
                        expected_result="Repaired",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Critical"):
        compile_spec(bad)


def test_check_case_expected_result_not_in_result_values_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "test_cases": TestCases(
                cases=(
                    CaseWalk(
                        name="Bad case",
                        fills=(),
                        expected_path=("Intake",),
                        expected_result="Not A Real Result",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Not A Real Result"):
        compile_spec(bad)


def test_check_case_fill_stage_not_in_path_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "test_cases": TestCases(
                cases=(
                    CaseWalk(
                        name="Bad case",
                        fills=(
                            StepFill(stage="Repair", values=(("Repair Cost", "10"),)),
                        ),
                        expected_path=("Intake",),
                        expected_result="Repaired",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="never visits"):
        compile_spec(bad)


def test_check_case_expected_path_unknown_stage_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "test_cases": TestCases(
                cases=(
                    CaseWalk(
                        name="Bad case",
                        fills=(),
                        expected_path=("Intake", "Nonexistent Stage"),
                        expected_result="Repaired",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_looped_case_can_tick_gate_differently_per_visit() -> None:
    """The exact expressiveness M11 demanded: two StepFills for the SAME re-visited
    stage, one
    false one true — proof a flat single-value-per-field dict could never have expressed
     this."""
    plan = compile_spec(_full_spec())
    sim_ops = {op.args["name"]: op for op in plan.ops if op.kind == "simulate_case"}
    rework_case = sim_ops["Rework then pass"]
    qc_fills = [f for f in rework_case.args["fills"] if f["stage"] == "Quality Check"]
    assert len(qc_fills) == 2
    assert qc_fills[0]["values"]["Quality Passed"] == "false"
    assert qc_fills[1]["values"]["Quality Passed"] == "true"


def test_check_widget_unknown_slug_raises() -> None:
    full = _full_spec()
    bad_view = full.personas.views[0].model_copy(
        update={
            "pages": (
                PageIntent(
                    name="Bad Page", widgets=(WidgetIntent(slug="not/a/real/slug"),)
                ),
            )
        }
    )
    bad = full.model_copy(
        update={"personas": Personas(views=(bad_view, *full.personas.views[1:]))}
    )
    with pytest.raises(ValueError, match="not/a/real/slug"):
        compile_spec(bad)


def test_check_widget_missing_required_config_raises() -> None:
    full = _full_spec()
    bad_view = full.personas.views[0].model_copy(
        update={
            "pages": (
                PageIntent(
                    name="Bad Page",
                    widgets=(
                        WidgetIntent(
                            slug="view/table", config=(("flow_type", "process"),)
                        ),
                    ),
                ),
            )
            # missing flow_id and view_id
        }
    )
    bad = full.model_copy(
        update={"personas": Personas(views=(bad_view, *full.personas.views[1:]))}
    )
    with pytest.raises(ValueError, match="flow_id"):
        compile_spec(bad)


def test_check_widget_missing_row_fields_raises() -> None:
    full = _full_spec()
    bad_view = full.personas.views[0].model_copy(
        update={
            "pages": (
                PageIntent(
                    name="Bad Page",
                    widgets=(
                        WidgetIntent(
                            slug="repeater",
                            config=(
                                ("flow_type", "process"),
                                ("flow_id", "x"),
                                ("view_id", "myitems"),
                            ),
                        ),
                    ),
                ),
            )
            # row_fields left empty
        }
    )
    bad = full.model_copy(
        update={"personas": Personas(views=(bad_view, *full.personas.views[1:]))}
    )
    with pytest.raises(ValueError, match="row_fields"):
        compile_spec(bad)


def test_check_persona_unknown_role_raises() -> None:
    full = _full_spec()
    bad_view = full.personas.views[0].model_copy(update={"role": "Nonexistent Role"})
    bad = full.model_copy(
        update={"personas": Personas(views=(bad_view, *full.personas.views[1:]))}
    )
    with pytest.raises(ValueError, match="Nonexistent Role"):
        compile_spec(bad)


def test_widget_with_no_required_config_needs_none() -> None:
    # general/label has no entry in WIDGET_REQUIRED_CONFIG at all — must not spuriously
    # raise
    plan = compile_spec(_linear_spec())
    assert isinstance(plan, BuildPlan)


def test_create_process_carries_pain_goal_and_result_values() -> None:
    spec = _full_spec()
    plan = compile_spec(spec)
    op = next(op for op in plan.ops if op.kind == "create_process")
    assert op.args["pain"] == spec.problem_goal.pain
    assert op.args["goal"] == spec.problem_goal.goal
    assert op.args["result_values"] == spec.problem_goal.result_values


def test_build_workflow_carries_stage_descriptions() -> None:
    plan = compile_spec(_full_spec())
    op = next(op for op in plan.ops if op.kind == "build_workflow")
    intake = next(s for s in op.args["stages"] if s["name"] == "Intake")
    assert intake["what_happens"] == "log the unit and customer details"
    assert intake["entry_criteria"] and intake["exit_criteria"]


def test_split_nested_in_a_branch_is_refused() -> None:
    """D3 (#29): a split whose OWN at_stage sits inside a DIFFERENT split's branch has
    no captured
    shape — refused at compile (THE RULE), naming the nested-split coverage row. Split
    B's
    at_stage ("Repair") is exactly the stage split A's own "Yes" branch routes
    through."""
    spec = _full_spec().model_copy(
        update={
            "routing": Routing(
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
                    DecisionPoint(
                        at_stage="Repair",
                        field_name="Repairable",
                        options=("Yes", "No"),
                        route_per_option=(
                            ("Yes", ("Quality Check",)),
                            ("No", ("Quality Check",)),
                        ),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="nested-split") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Repair" in message
    assert "Diagnose" in message


def test_two_splits_sharing_a_branch_name_are_refused() -> None:
    """D3 (#29): a branch id is a hash of (model, kind, index, name) — two splits
    declaring the
    SAME option/branch name collide on that id and silently overwrite one another.
    Refused at
    compile, mirroring graph.build_workflow's own runtime guard. The two splits here are
     siblings
    (neither nested in the other's branch), so this isolates the duplicate-name refusal
    alone."""
    spec = _full_spec().model_copy(
        update={
            "routing": Routing(
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
                    DecisionPoint(
                        at_stage="Quality Check",
                        field_name="Repairable",
                        options=("Yes", "Something Else"),
                        route_per_option=(
                            ("Yes", ("Repair",)),
                            ("Something Else", ("Return to Customer",)),
                        ),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Yes") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Diagnose" in message
    assert "Quality Check" in message


def test_branch_local_loop_goto_op_carries_its_branch_name() -> None:
    """S3 AC1/US11: a loop whose endpoints both live in one branch compiles to an
    add_goto_gate op
    that NAMES that branch, so the live layer places the GotoTask inside it (last within
     it)
    instead of mis-deriving it from an ambiguous target name."""
    plan = compile_spec(_branch_local_loop_spec())
    goto_ops = [op for op in plan.ops if op.kind == "add_goto_gate"]
    assert len(goto_ops) == 1
    args = goto_ops[0].args
    assert (args["from_stage"], args["to_stage"]) == ("Verify", "Fix")
    assert args["branch_name"] == "Complex"


def test_spine_to_branch_loop_resolves_to_the_target_branch() -> None:
    """The `_full_spec` golden loop is Quality Check (spine) -> Repair (inside the 'Yes'
     branch):
    one endpoint on the spine, one in a branch. That is NOT cross-branch (it stays
    allowed) and the
    op names the single branch its stages touch — the target's branch, made explicit."""
    plan = compile_spec(_full_spec())
    goto = next(op for op in plan.ops if op.kind == "add_goto_gate")
    assert goto.args["branch_name"] == "Yes"


def test_spine_only_loop_goto_op_has_no_branch_name() -> None:
    """A rework loop whose endpoints are both on the linear spine (no split involved)
    carries
    branch_name=None — a plain root-chain loop, the pre-S3 shape, now stated
    explicitly."""
    base = _linear_spec()
    spec = base.model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Handle Ticket",
                        to_stage="Log Ticket",
                        gate_field="Redo",
                    ),
                )
            ),
            "data_model": base.data_model.model_copy(
                update={
                    "fields": base.data_model.fields
                    + (
                        FieldReq(
                            name="Redo",
                            type=FieldType.BOOLEAN,
                            required=False,
                            stage="Handle Ticket",
                        ),
                    )
                }
            ),
        }
    )
    goto = next(op for op in compile_spec(spec).ops if op.kind == "add_goto_gate")
    assert goto.args["branch_name"] is None


def test_duplicate_step_name_across_branches_is_refused() -> None:
    """S3 AC2/AC5: the SAME step name in two different branches is refused, naming the
    `duplicate-branch-step` coverage row — a loop's branch is derived from its step
    names, so a
    name owned by two branches makes that derivation (and the branch id) a coin flip."""
    spec = _branch_local_loop_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Triage",
                        field_name="Path",
                        options=("Simple", "Complex"),
                        # both branches route through "Fix" — one step name, two
                        # branches
                        route_per_option=(
                            ("Simple", ("Quick Close", "Fix")),
                            ("Complex", ("Deep Review", "Fix", "Verify")),
                        ),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="duplicate-branch-step") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Fix" in message
    assert "Simple" in message and "Complex" in message


def test_cross_branch_loop_is_refused() -> None:
    """S3 AC3: a loop whose from_stage sits in one branch and to_stage in ANOTHER is
    refused,
    naming the `cross-branch-jump` coverage row — a loop must stay within its own
    branch. Verify
    (in 'Complex') jumps back to Quick Close (in 'Simple'): backward in stage order, but
     across
    branches."""
    spec = _branch_local_loop_spec().model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Verify",
                        to_stage="Quick Close",
                        gate_field="Fix Approved",
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="cross-branch-jump") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Complex" in message and "Simple" in message


def test_one_split_emits_one_set_branch_conditions_op_with_the_deciding_field_and_literals() -> (  # noqa: E501
    None
):
    """S4 (#35) AC1/AC2: `_full_spec`'s one DecisionPoint (Diagnose -> Repairable,
    Yes/No) compiles
    to exactly one `set_branch_conditions` op naming the fork stage, the deciding field,
     and a
    branch-name -> literal mapping — matching `forge_set_branch_conditions`'s own
    shape."""
    plan = compile_spec(_full_spec())
    branch_cond_ops = [op for op in plan.ops if op.kind == "set_branch_conditions"]
    assert len(branch_cond_ops) == 1
    op = branch_cond_ops[0]
    assert op.args["at_stage"] == "Diagnose"
    assert op.args["field_name"] == "Repairable"
    assert op.args["branch_literals"] == {"Yes": "Yes", "No": "No"}


def test_linear_spec_emits_no_set_branch_conditions_ops() -> None:
    """S4 (#35) AC3: a spec with no decision split (`_linear_spec`, `routing.points ==
    ()`) has no
    Parallel to condition — `_op_set_branch_conditions` must emit ZERO ops, mirroring
    `_op_add_table` returning `()` when there are no tables."""
    plan = compile_spec(_linear_spec())
    assert [op for op in plan.ops if op.kind == "set_branch_conditions"] == []


def test_check_unclaimed_deciding_value_raises() -> None:
    """S4 (#35) AC3 / CLAUDE.md Conditional routing "Fail OPEN, not closed": a real
    value of the
    deciding field's list ("Maybe") that no branch option claims must refuse at compile
    — an item
    with that value would otherwise silently skip the whole Parallel and complete with
    no work
    done. The DecisionPoint's own `options` ("Yes", "No") are left UNCHANGED and are
    still valid
    list values, so `_check_routing_literals` (options must be ⊆ list values) does not
    fire here —
    this is the NEW, opposite check (list values must be ⊆ options)."""
    full = _full_spec()
    bad_lists = tuple(
        lst.model_copy(update={"values": ("Yes", "No", "Maybe")})
        if lst.name == "Yes No"
        else lst
        for lst in full.master_data.lists
    )
    bad = full.model_copy(update={"master_data": MasterData(lists=bad_lists)})
    with pytest.raises(ValueError) as exc_info:
        compile_spec(bad)
    message = str(exc_info.value)
    assert "Maybe" in message
    assert "unclaimed-value" in message


def test_build_page_carries_aggregated_kpis_and_actions() -> None:
    plan = compile_spec(_full_spec())
    build_ops = {op.args["name"]: op for op in plan.ops if op.kind == "build_page"}
    dash = build_ops["Manager Dashboard"]
    # Service Manager + Front Desk both reference this page — both contributions must be
    # present
    assert dash.args["kpis"] == ("jobs awaiting pickup", "open jobs", "overdue jobs")
    assert dash.args["actions"] == (
        "approve quality check",
        "log new unit",
        "notify customer",
        "reassign job",
    )


def test_timing_blank_does_not_block_but_is_still_collected() -> None:
    spec = _full_spec().model_copy(
        update={"timing": Timing(sla_notes="", batch_days=(), reminders=())}
    )
    assert _dims(spec.gaps()) == [9]  # still asked about
    assert spec.blocking_gaps() == ()  # never blocks
    plan = compile_spec(spec)
    assert isinstance(plan, BuildPlan)


def test_check_required_field_hidden_at_own_stage_raises() -> None:
    """The exact reviewer probe: a required field's SECTION is Hidden at the field's own
     stage —
    used to compile clean; the step becomes unsubmittable and simulate_case can never
    pass."""
    full = _full_spec()
    entries = tuple(
        VisibilityEntry(
            section="Intake Basics", stage="Intake", permission=Visibility.HIDDEN
        )
        if (e.section == "Intake Basics" and e.stage == "Intake")
        else e
        for e in full.visibility.entries
    )
    bad = full.model_copy(update={"visibility": VisibilityMatrix(entries=entries)})
    with pytest.raises(ValueError, match="Unit Name"):
        compile_spec(bad)


def test_check_required_field_with_no_visibility_entry_at_own_stage_raises() -> None:
    """ "No entry at all" is exactly as fatal as an explicit Hidden — neither one is a
    proven
    Editable."""
    full = _full_spec()
    entries = tuple(
        e
        for e in full.visibility.entries
        if not (e.section == "Intake Priority" and e.stage == "Intake")
    )
    bad = full.model_copy(update={"visibility": VisibilityMatrix(entries=entries)})
    with pytest.raises(ValueError, match="Urgency"):
        compile_spec(bad)


def test_check_required_field_editable_via_field_level_override_passes() -> None:
    # a field-level Editable entry satisfies the check even when the SECTION itself is
    # ReadOnly —
    # the field-level entry is more specific and wins
    full = _full_spec()
    entries = tuple(
        VisibilityEntry(
            section="Intake Basics", stage="Intake", permission=Visibility.READONLY
        )
        if (e.section == "Intake Basics" and e.stage == "Intake")
        else e
        for e in full.visibility.entries
    ) + (
        VisibilityEntry(
            section="Intake Basics",
            stage="Intake",
            permission=Visibility.EDITABLE,
            field="Unit Name",
        ),
        VisibilityEntry(
            section="Intake Basics",
            stage="Intake",
            permission=Visibility.EDITABLE,
            field="Customer Name",
        ),
    )
    spec = full.model_copy(update={"visibility": VisibilityMatrix(entries=entries)})
    plan = compile_spec(spec)  # must NOT raise
    assert isinstance(plan, BuildPlan)


def test_check_start_hidden_raises() -> None:
    """The exact reviewer probe: VisibilityEntry(first section, Start, Hidden) satisfied
     the OLD
    check (which only asked WHICH section owns Start) but must raise now."""
    full = _full_spec()
    entries = tuple(
        VisibilityEntry(
            section="Intake Basics", stage=START_STAGE, permission=Visibility.HIDDEN
        )
        if e.stage == START_STAGE
        else e
        for e in full.visibility.entries
    )
    bad = full.model_copy(update={"visibility": VisibilityMatrix(entries=entries)})
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


def test_check_start_readonly_raises() -> None:
    full = _full_spec()
    entries = tuple(
        VisibilityEntry(
            section="Intake Basics", stage=START_STAGE, permission=Visibility.READONLY
        )
        if e.stage == START_STAGE
        else e
        for e in full.visibility.entries
    )
    bad = full.model_copy(update={"visibility": VisibilityMatrix(entries=entries)})
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


def test_check_select_field_no_list_name_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        f.model_copy(update={"list_name": None}) if f.name == "Urgency" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Urgency"):
        compile_spec(bad)


def test_check_select_field_unknown_list_name_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        f.model_copy(update={"list_name": "No Such List"}) if f.name == "Urgency" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    # Match the unknown-list branch's OWN wording, not just the list name: the name
    # alone also
    # appears in _check_test_cases' message, so a looser match passes even if this check
    # is gone.
    with pytest.raises(
        ValueError, match=r"names list_name 'No Such List', which is not in"
    ):
        compile_spec(bad)


def test_check_routing_field_name_unknown_even_with_no_options_raises() -> None:
    """The exact reviewer probe: field_name was only ever reached inside the per-option
    loop, so
    options=() used to skip validation entirely and a branch on a phantom field compiled
     clean."""
    bad = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Phantom Field",
                        options=(),
                        route_per_option=(),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="Phantom Field"):
        compile_spec(bad)


def test_check_routing_empty_options_raises() -> None:
    bad = _full_spec().model_copy(
        update={
            "routing": Routing(
                points=(
                    DecisionPoint(
                        at_stage="Diagnose",
                        field_name="Repairable",
                        options=(),
                        route_per_option=(),
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError, match="zero options"):
        compile_spec(bad)


def test_check_field_section_mismatched_stage_named_section_raises() -> None:
    """The exact reviewer probe: a field's section names a real STAGE (not an explicit
    SectionReq) that isn't the field's own stage — used to escape the mismatch guard
    entirely,
    since `owner` (looked up only among SectionReqs) was None and the old guard's `owner
     is not
    None` condition never even looked further."""
    full = _full_spec()
    bad_fields = tuple(
        f.model_copy(update={"section": "Diagnose"}) if f.name == "Repair Cost" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Repair Cost"):
        compile_spec(bad)


def test_build_page_aggregates_widgets_across_roles_not_just_first() -> None:
    """The exact reviewer probe: _unique_pages kept only the first PageIntent per name,
    so
    _op_build_page silently dropped every OTHER role's widgets — contradicting its own
    docstring
    claim that nothing is dropped (which was already true for kpis/actions, just not
    widgets)."""
    plan = compile_spec(_full_spec())
    dash = next(
        op
        for op in plan.ops
        if op.kind == "build_page" and op.args["name"] == "Manager Dashboard"
    )
    slugs = {w["slug"] for w in dash.args["widgets"]}
    assert "metrics" in slugs
    assert "view/table" in slugs
    assert "general/label" in slugs


def test_build_page_widget_dedup_by_slug_and_config() -> None:
    plan = compile_spec(_full_spec())
    dash = next(
        op
        for op in plan.ops
        if op.kind == "build_page" and op.args["name"] == "Manager Dashboard"
    )
    # metrics/view-table are declared IDENTICALLY by both Service Manager and Front Desk
    # — each
    # must appear exactly once, not duplicated by the aggregation
    metrics = [w for w in dash.args["widgets"] if w["slug"] == "metrics"]
    assert len(metrics) == 1


def test_build_page_carries_popups_and_on_click_aggregated_across_roles() -> None:
    plan = compile_spec(_dashboard_with_behavior())
    dash = next(
        op
        for op in plan.ops
        if op.kind == "build_page" and op.args["name"] == "Manager Dashboard"
    )
    # both roles' popups survive aggregation, neither silently dropped for sharing the
    # page name
    assert {p["name"] for p in dash.args["popups"]} == {"Job Detail", "Unit Detail"}
    events = {
        (e["action"], e["kind"], e["target_popup"]) for e in dash.args["on_click"]
    }
    assert ("reassign job", "OpenPopup", "Job Detail") in events
    assert ("notify customer", "JSAction", None) in events


def test_build_page_no_behavior_carries_empty_popups_and_on_click() -> None:
    # a plain content-only page still emits the keys (empty), never omits them
    plan = compile_spec(_full_spec())
    jobs = next(
        op
        for op in plan.ops
        if op.kind == "build_page" and op.args["name"] == "My Jobs"
    )
    assert jobs.args["popups"] == ()
    assert jobs.args["on_click"] == ()


def test_build_page_op_carries_the_design_tree_as_wire() -> None:
    """A page with a `design` compiles it INTO the build_page op as the plain wire dict
    pages.build_design consumes — nested containers, each carrying style, wrapping the
    widgets."""
    plan = compile_spec(_spec_with_design(_rich_design()))
    op = next(
        op
        for op in plan.ops
        if op.kind == "build_page" and op.args["name"] == "Submit Case"
    )
    design = op.args["design"]
    assert design is not None
    # top is a container carrying a real style key, with children (the nested tree, not
    # a flat list)
    assert design["kind"] == "container"
    assert ["Container.Background", "#FCFAF2"] in design["style"]
    # nested: shell -> hero -> hero-title widget (a container/style/widget "op" chain)
    hero = design["children"][0]
    assert (
        hero["kind"] == "container"
        and ["Container.Background", "#2E6B3B"] in hero["style"]
    )
    hero_title = hero["children"][0]
    assert hero_title["kind"] == "widget"
    assert hero_title["widget"]["slug"] == "general/label"
    # a widget wrapped in the card lower in the tree
    card = design["children"][1]
    assert card["children"][0]["widget"]["slug"] == "view/form"


def test_build_page_op_without_design_is_none_backward_compatible() -> None:
    """A page that declares no design compiles design=None — the flat-widget build,
    unchanged."""
    plan = compile_spec(_full_spec())
    for op in plan.ops:
        if op.kind == "build_page":
            assert op.args["design"] is None


def test_design_widget_is_governed_by_the_same_checks() -> None:
    """A widget buried in a design tree is not a loophole: an API-impossible slug inside
     a design
    container is refused at compile naming its coverage row, same as a top-level/popup
    widget."""
    bad_design = DesignNode(
        kind="container",
        name="shell",
        children=(
            DesignNode(kind="widget", name="bad", widget=WidgetIntent(slug="custom")),
        ),
    )
    with pytest.raises(ValueError, match="custom-component"):
        compile_spec(_spec_with_design(bad_design))


def test_design_container_carrying_a_widget_is_refused() -> None:
    """_check_page_design: a container node must not carry a widget (widgets are leaf
    nodes)."""
    bad = DesignNode(
        kind="container", name="oops", widget=WidgetIntent(slug="general/label")
    )
    with pytest.raises(ValueError, match="must not carry a widget"):
        compile_spec(_spec_with_design(bad))


def test_check_unknown_widget_slug_inside_popup_raises() -> None:
    """AC4: an unknown-slug widget HIDDEN inside a popup is refused, not escaped."""
    full = _full_spec()
    v = full.personas.views[0]
    p = v.pages[0].model_copy(
        update={
            "popups": (
                PopupIntent(
                    name="Detail", widgets=(WidgetIntent(slug="not/a/real/slug"),)
                ),
            )
        }
    )
    bad = full.model_copy(
        update={
            "personas": Personas(
                views=(v.model_copy(update={"pages": (p,)}), *full.personas.views[1:])
            )
        }
    )
    with pytest.raises(ValueError, match="not/a/real/slug"):
        compile_spec(bad)


def test_check_api_impossible_widget_inside_popup_raises_naming_row() -> None:
    """AC3/AC4: an API-impossible widget inside a popup is refused naming its coverage
    row — the
    popup-opening action can't build, so it's refused, never downgraded to a static
    button (D6)."""
    full = _full_spec()
    v = full.personas.views[0]
    p = v.pages[0].model_copy(
        update={
            "popups": (
                PopupIntent(name="Detail", widgets=(WidgetIntent(slug="custom"),)),
            )
        }
    )
    bad = full.model_copy(
        update={
            "personas": Personas(
                views=(v.model_copy(update={"pages": (p,)}), *full.personas.views[1:])
            )
        }
    )
    with pytest.raises(ValueError, match="custom-component"):
        compile_spec(bad)


def test_check_on_click_dangling_target_popup_raises() -> None:
    """An OpenPopup naming a popup that doesn't exist on the page — a build that would
    open nothing."""
    full = _full_spec()
    v = full.personas.views[0]
    p = v.pages[0].model_copy(
        update={
            "on_click": (
                OnClickAction(
                    action="reassign job",
                    kind=ClickActionKind.OPEN_POPUP,
                    target_popup="No Such Popup",
                ),
            )
        }
    )
    bad = full.model_copy(
        update={
            "personas": Personas(
                views=(v.model_copy(update={"pages": (p,)}), *full.personas.views[1:])
            )
        }
    )
    with pytest.raises(ValueError, match="No Such Popup"):
        compile_spec(bad)


def test_check_on_click_both_arms_set_raises() -> None:
    """The exactly-one-arm contract #39 deferred to T2: OpenPopup carrying a script too
    is refused."""
    full = _full_spec()
    v = full.personas.views[0]
    p = v.pages[0].model_copy(
        update={
            "popups": (
                PopupIntent(
                    name="Job Detail", widgets=(WidgetIntent(slug="general/label"),)
                ),
            ),
            "on_click": (
                OnClickAction(
                    action="reassign job",
                    kind=ClickActionKind.OPEN_POPUP,
                    target_popup="Job Detail",
                    script="kf.x()",
                ),
            ),
        }
    )
    bad = full.model_copy(
        update={
            "personas": Personas(
                views=(v.model_copy(update={"pages": (p,)}), *full.personas.views[1:])
            )
        }
    )
    with pytest.raises(ValueError, match="exactly one arm"):
        compile_spec(bad)


def test_check_on_click_unknown_action_raises() -> None:
    """`action` must name one the owning role actually declares (#39 gap (c))."""
    full = _full_spec()
    v = full.personas.views[0]
    p = v.pages[0].model_copy(
        update={
            "on_click": (
                OnClickAction(
                    action="ghost action",
                    kind=ClickActionKind.JS_ACTION,
                    script="kf.x()",
                ),
            )
        }
    )
    bad = full.model_copy(
        update={
            "personas": Personas(
                views=(v.model_copy(update={"pages": (p,)}), *full.personas.views[1:])
            )
        }
    )
    with pytest.raises(ValueError, match="ghost action"):
        compile_spec(bad)


def test_loop_gate_wrong_type_message_shows_plain_value_not_enum_repr() -> None:
    bad = _full_spec().model_copy(
        update={
            "rework_loops": ReworkLoops(
                loops=(
                    LoopSpec(
                        from_stage="Quality Check",
                        to_stage="Repair",
                        gate_field="Repair Cost",
                        max_rounds=3,
                    ),
                )
            )
        }
    )
    with pytest.raises(ValueError) as exc_info:
        compile_spec(bad)
    message = str(exc_info.value)
    assert "Number" in message
    assert "FieldType." not in message


def test_check_field_unknown_stage_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        f.model_copy(update={"stage": "Nonexistent Stage"})
        if f.name == "Unit Name"
        else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_check_field_non_fieldtype_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        f.model_copy(update={"type": "Text"}) if f.name == "Unit Name" else f  # type: ignore[arg-type]
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="FieldType enum member"):
        compile_spec(bad)


def test_check_visibility_non_enum_permission_raises_named_valueerror() -> None:
    """compile.py's own `isinstance(entry.permission, Visibility)` check is defense in
    depth:
    normal construction can no longer produce this (see the coercion test above), but a
    caller
    that bypasses validation (`model_construct`, e.g. from data read back off an
    untrusted
    source) must still be refused by name, not crash with an AttributeError deeper
    in."""
    full = _full_spec()
    # a wire STRING where a Visibility member belongs, forced past construction-time
    # validation.
    bad_entry = VisibilityEntry.model_construct(
        section="Intake", stage="Intake", permission="Editable", field=None, role=None
    )
    bad = full.model_copy(update={"visibility": VisibilityMatrix(entries=(bad_entry,))})
    with pytest.raises(ValueError) as exc_info:
        compile_spec(bad)
    message = str(exc_info.value)
    assert "Intake" in message
    assert "Visibility enum member" in message


def test_field_options_thread_into_apply_fields() -> None:
    plan = compile_spec(_full_spec())
    diagnose_op = next(
        op
        for op in plan.ops
        if op.kind == "apply_fields" and op.args["stage"] == "Diagnose"
    )
    notes = next(
        f for f in diagnose_op.args["fields"] if f["name"] == "Diagnosis Notes"
    )
    assert notes["options"] == {"AllowFormatting": "true"}


def test_compiles_to_every_op_kind_in_proven_order() -> None:
    plan = compile_spec(_full_spec())
    assert isinstance(plan, BuildPlan)

    kinds = [op.kind for op in plan.ops]
    # every canonical kind appears at least once — the fixture was built to exercise all
    # 11
    # dimensions, so every op kind the proven build order names should show up
    assert set(kinds) == set(OP_ORDER)

    # and strictly in OP_ORDER: every op of an earlier kind precedes every op of a later
    # kind
    seen_kind_positions = [OP_ORDER.index(k) for k in kinds]
    assert seen_kind_positions == sorted(seen_kind_positions)

    for op in plan.ops:
        assert isinstance(op, Op)
        assert op.kind in OP_ORDER
        assert isinstance(op.args, dict)
        assert op.why


def test_op_counts_match_the_fixture_exactly() -> None:
    """Pinned expected counts, derived by hand from `_full_spec()`'s own content — a
    change to
    either the fixture or the op-derivation logic that breaks this pairing should fail
    loudly
    here rather than only via a vaguer 'set of kinds' check."""
    plan = compile_spec(_full_spec())
    assert plan.summary() == {
        "create_process": 1,
        "member_batch": 3,  # one per role
        "create_list": 2,  # Urgency Levels, Yes No
        "apply_fields": 4,  # Intake, Diagnose, Repair, Quality Check have fields;
        # Return to
        # Customer has none, so it gets no apply_fields op
        "add_table": 1,  # Parts Used
        "build_workflow": 1,  # one ProcessDef for the whole stage sequence
        "set_assignees": 5,  # one per stage
        "add_goto_gate": 1,  # Quality Check -> Repair
        "set_branch_conditions": 1,  # Diagnose's one split, Yes/No
        "set_visibility": 1,  # the whole matrix in one op
        "set_events": 1,  # Total Parts Cost
        "set_styles": 5,  # one per stage
        "publish": 1,
        "doctor": 1,
        "compare": 1,  # fidelity vs the input spec (#16), right after doctor
        "create_page": 2,  # Manager Dashboard, My Jobs — deduplicated across 2
        # roles
        "build_page": 2,
        "set_navigation": 3,  # (Service Manager, Manager Dashboard), (Technician,
        # My Jobs),
        # (Front Desk, Manager Dashboard)
        "simulate_case": 3,
    }
    assert len(plan.ops) == 39


def test_summary_reconciles_with_ops() -> None:
    plan = compile_spec(_full_spec())
    summary = plan.summary()
    assert sum(summary.values()) == len(plan.ops)
    assert set(summary.keys()) <= set(OP_ORDER)
    for kind, count in summary.items():
        assert count == sum(1 for op in plan.ops if op.kind == kind)


def test_apply_fields_op_carries_the_sequence_only_on_the_first_stage() -> None:
    plan = compile_spec(_full_spec())
    apply_ops = [op for op in plan.ops if op.kind == "apply_fields"]
    with_sequence = [op for op in apply_ops if op.args["sequence"] is not None]
    assert len(with_sequence) == 1
    assert with_sequence[0].args["stage"] == "Intake"
    assert with_sequence[0].args["sequence"] == {"prefix": "RPR", "padding": "0001"}


def test_set_styles_never_carries_a_color_or_token() -> None:
    """CLAUDE.md Write path: a style token may never be synthesized — set_styles ops
    must name
    only the stage, not invent a color/token value."""
    plan = compile_spec(_full_spec())
    style_ops = [op for op in plan.ops if op.kind == "set_styles"]
    assert len(style_ops) == 5
    for op in style_ops:
        assert set(op.args.keys()) == {"stage"}


def test_create_and_build_page_ops_are_deduplicated_by_page_name() -> None:
    plan = compile_spec(_full_spec())
    create_names = sorted(
        op.args["name"] for op in plan.ops if op.kind == "create_page"
    )
    build_names = sorted(op.args["name"] for op in plan.ops if op.kind == "build_page")
    assert create_names == ["Manager Dashboard", "My Jobs"]
    assert build_names == ["Manager Dashboard", "My Jobs"]


def test_set_navigation_binds_the_shared_page_to_both_its_roles() -> None:
    plan = compile_spec(_full_spec())
    nav_pairs = sorted(
        (op.args["role"], op.args["page"])
        for op in plan.ops
        if op.kind == "set_navigation"
    )
    assert nav_pairs == [
        ("Front Desk", "Manager Dashboard"),
        ("Service Manager", "Manager Dashboard"),
        ("Technician", "My Jobs"),
    ]


class TestRoleScopedVisibilityClaim:
    @staticmethod
    def _spec_with_role_claim() -> AppSpec:
        full = _full_spec()
        vm = full.visibility
        claimed = vm.entries[3].model_copy(update={"role": "Front Desk"})
        new_vm = vm.model_copy(
            update={"entries": vm.entries[:3] + (claimed,) + vm.entries[4:]}
        )
        return full.model_copy(update={"visibility": new_vm})

    def test_compile_does_not_refuse_a_role_claim(self) -> None:
        """AC4 (B2) held: the refusal is the DOCTOR's gate, not compile's — compile
        still emits a
        plan, threading the claim through to the doctor op."""
        plan = compile_spec(self._spec_with_role_claim())
        assert any(op.kind == "doctor" for op in plan.ops)

    def test_doctor_op_carries_the_role_claim(self) -> None:
        plan = compile_spec(self._spec_with_role_claim())
        (doctor_op,) = [op for op in plan.ops if op.kind == "doctor"]
        claims = doctor_op.args["visibility_role_claims"]
        assert len(claims) == 1
        (claim,) = claims
        entry = self._spec_with_role_claim().visibility.entries[3]
        assert entry.section in claim and entry.stage in claim and "Front Desk" in claim

    def test_doctor_op_claims_empty_without_role_entries(self) -> None:
        plan = compile_spec(_full_spec())
        (doctor_op,) = [op for op in plan.ops if op.kind == "doctor"]
        assert tuple(doctor_op.args["visibility_role_claims"]) == ()
