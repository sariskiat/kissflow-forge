"""Mirror tests for `app.application.use_cases.intake._questions` -- ported
from `tests/test_intake.py`'s questions.py coverage (Stage D group 8; the
module moved from `app.application.intake.questions`).
"""

from __future__ import annotations

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
from app.application.use_cases.intake._questions import (
    QUESTIONS,
    Question,
    next_questions,
)
from app.domain.value_objects.field_type import FieldType, Visibility

_EMPTY_SPEC = AppSpec(
    app_name="",
    problem_goal=ProblemGoal(
        pain="", goal="", done_definition="", terminal_states=(), result_values=()
    ),
    roles=Roles(roles=()),
    stages=Stages(stages=()),
    routing=Routing(points=()),
    rework_loops=ReworkLoops(loops=()),
    data_model=DataModel(fields=(), tables=(), computed=()),
    master_data=MasterData(lists=()),
    visibility=VisibilityMatrix(entries=()),
    timing=Timing(sla_notes="", batch_days=(), reminders=()),
    personas=Personas(views=()),
    test_cases=TestCases(cases=()),
)


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


def test_next_questions_empty_when_spec_is_complete() -> None:
    assert next_questions(_full_spec()) == ()


def test_next_questions_priority_order_and_default_limit() -> None:
    # priority order is 1,2,3,6,7,4,5,8,11,10,9 (m21: roles before stages, data model
    # before
    # routing/loops); dim1 has 2 questions, dim2 has 1, dim3 has 1 — limit=4 exhausts
    # exactly
    # dims 1, 2, 3
    got = next_questions(_EMPTY_SPEC, limit=4)
    assert [q.id for q in got] == ["1a", "1b", "2a", "3a"]


def test_next_questions_respects_a_larger_limit() -> None:
    # one more dimension's worth (dim6 has 2 questions) fits in a limit of 6
    got = next_questions(_EMPTY_SPEC, limit=6)
    assert [q.id for q in got] == ["1a", "1b", "2a", "3a", "6a", "6b"]


def test_next_questions_only_asks_about_the_one_remaining_gap() -> None:
    spec = _full_spec().model_copy(
        update={"timing": Timing(sla_notes="", batch_days=(), reminders=())}
    )
    got = next_questions(spec, limit=4)
    assert [q.id for q in got] == ["9a"]


def test_every_dimension_has_at_least_one_question() -> None:
    for dim in range(1, 12):
        assert dim in QUESTIONS
        assert len(QUESTIONS[dim]) >= 1
        for q in QUESTIONS[dim]:
            assert isinstance(q, Question)
            assert q.text_th and q.why and q.example


def test_q6a_lists_every_legal_field_type() -> None:
    """m19: a business owner should never be able to answer with a type that doesn't
    exist."""
    q6a = next(q for q in QUESTIONS[6] if q.id == "6a")
    for t in FieldType:
        assert t.value in q6a.why


def test_optional_dimension_questions_invite_a_none_answer() -> None:
    """M14: the interview script itself must not pressure a fake branch/loop/list into
    existence."""
    for dim, marker in ((4, "ไม่มี"), (5, "ไม่มี"), (7, "ไม่มี")):
        assert any(marker in q.text_th or marker in q.why for q in QUESTIONS[dim])


def test_q6_has_dedicated_table_column_and_section_description_questions() -> None:
    ids = {q.id for q in QUESTIONS[6]}
    assert "6c" in ids  # table column types + required
    assert "6d" in ids  # section description
    q6c = next(q for q in QUESTIONS[6] if q.id == "6c")
    for t in FieldType:
        assert t.value in q6c.why
