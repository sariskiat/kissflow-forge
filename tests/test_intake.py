"""Spec for kfforge.intake — the input spec (schema.py), the grilling script (questions.py), and
the spec-to-plan compiler (compile.py).

Offline, synthetic AppSpec only — no network, no live Kissflow calls. The fixture specs below use
a neutral, fictional business domain, never the real app this engine was extracted from
(CLAUDE.md BLINDNESS discipline): no real-app field/option/role/page names or vocabulary anywhere
in this file.
"""
from __future__ import annotations

import dataclasses

import pytest

from kfforge.intake.compile import OP_ORDER, BuildPlan, Op, compile_spec
from kfforge.intake.questions import QUESTIONS, Question, next_questions
from kfforge.intake.schema import (
    ADVISORY_DIMENSIONS,
    DIMENSION_NAMES,
    START_STAGE,
    AppSpec,
    CaseWalk,
    ClickActionKind,
    ComputedReq,
    DataModel,
    DecisionPoint,
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
from kfforge.types import FieldType, Visibility

# ---- the synthetic fixtures ------------------------------------------------------------------

def _full_spec(*, approved: bool = True) -> AppSpec:
    """A fully-populated AppSpec for a neutral domain: a small equipment repair shop tracking a
    unit from intake through repair to return, WITH a real branch (Diagnose) and a real rework
    loop (Quality Check -> Repair). Every one of the 11 dimensions carries enough content that
    `compile_spec` produces at least one op of every `OP_ORDER` kind — see
    `test_op_counts_match_the_fixture_exactly` for the exact expected op counts. Companion to
    `_linear_spec`, which proves the OPPOSITE: an app with none of this is equally valid.
    """
    return AppSpec(
        app_name="Equipment Repair Tracker",
        problem_goal=ProblemGoal(
            pain="technicians and customers cannot see which repair job is stuck or with whom",
            goal="every repair job is trackable from intake to return, with a clear owner at "
                 "each step",
            done_definition="the unit is repaired or declared unrepairable, and the customer "
                             "has been notified",
            terminal_states=("Completed", "Cancelled"),
            result_values=("Repaired", "Beyond repair", "Cancelled by customer"),
        ),
        roles=Roles(roles=(
            RoleSpec("Front Desk", is_admin=False, members_hint="2 front-desk staff"),
            RoleSpec("Technician", is_admin=False, members_hint="5 technicians"),
            RoleSpec("Service Manager", is_admin=True, members_hint="1 manager"),
        )),
        stages=Stages(stages=(
            StageSpec("Intake", "Front Desk", "log the unit and customer details",
                      "customer drops off a unit", "unit logged with a case number"),
            StageSpec("Diagnose", "Technician", "assess whether the unit is repairable",
                      "unit logged", "repairable decision recorded"),
            StageSpec("Repair", "Technician", "perform the repair",
                      "marked repairable", "repair work finished"),
            StageSpec("Quality Check", "Service Manager", "verify the repair meets standard",
                      "repair marked finished", "quality check passed"),
            StageSpec("Return to Customer", "Front Desk", "notify customer and close the job",
                      "quality check passed, or unit deemed unrepairable",
                      "customer notified and job closed"),
        )),
        routing=Routing(points=(
            DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                          route_per_option=(("Yes", ("Repair",)), ("No", ("Return to Customer",)))),
        )),
        rework_loops=ReworkLoops(loops=(
            LoopSpec(from_stage="Quality Check", to_stage="Repair", gate_field="Quality Passed",
                     max_rounds=3),
        )),
        data_model=DataModel(
            fields=(
                FieldReq("Unit Name", FieldType.TEXT, True, "Intake", section="Intake Basics"),
                FieldReq("Customer Name", FieldType.TEXT, True, "Intake",
                         section="Intake Basics"),
                FieldReq("Urgency", FieldType.SELECT, True, "Intake", list_name="Urgency Levels",
                         section="Intake Priority"),
                FieldReq("Repairable", FieldType.SELECT, True, "Diagnose", list_name="Yes No"),
                FieldReq("Diagnosis Notes", FieldType.TEXTAREA, False, "Diagnose",
                         options=(("AllowFormatting", "true"),)),
                FieldReq("Quality Passed", FieldType.BOOLEAN, False, "Quality Check"),
                FieldReq("Repair Cost", FieldType.NUMBER, False, "Repair",
                         options=(("Decimalpoint", "2"),)),
                # the computed field's real TARGET — an earlier round of this fixture wired an
                # event onto a field name that was never declared anywhere; this is that bug,
                # fixed (see test_computed_source_resolves_against_table_columns).
                FieldReq("Total Parts Cost", FieldType.NUMBER, False, "Repair"),
            ),
            tables=(
                TableReq("Parts Used", "Repair", (
                    TableColumnReq("Part Name", FieldType.TEXT, True),
                    TableColumnReq("Quantity", FieldType.NUMBER, True),
                    TableColumnReq("Unit Cost", FieldType.NUMBER, True),
                ), max_rows=20),
            ),
            computed=(
                ComputedReq("Total Parts Cost", ("Quantity", "Unit Cost"), EventTrigger.ON_CHANGE,
                            "quantity times unit cost, summed across every row"),
            ),
            # two DISTINCT sections at the SAME stage — the exact shape a forced
            # section-equals-stage schema could never express.
            sections=(
                SectionReq("Intake Basics", "Intake", "the customer/unit identifying fields"),
                SectionReq("Intake Priority", "Intake", "urgency and scheduling fields"),
            ),
            sequence=SequenceReq("RPR", "0001"),
        ),
        master_data=MasterData(lists=(
            ListSpec("Urgency Levels", ("High", "Medium", "Low"), "Service Manager"),
            ListSpec("Yes No", ("Yes", "No"), "Service Manager"),
        )),
        visibility=VisibilityMatrix(entries=(
            VisibilityEntry("Intake Basics", START_STAGE, Visibility.EDITABLE),
            VisibilityEntry("Intake Basics", "Intake", Visibility.EDITABLE),
            VisibilityEntry("Intake Priority", "Intake", Visibility.EDITABLE),
            VisibilityEntry("Intake Basics", "Diagnose", Visibility.READONLY),
            VisibilityEntry("Diagnose", "Diagnose", Visibility.EDITABLE),
            VisibilityEntry("Parts Used", "Repair", Visibility.EDITABLE),
            VisibilityEntry("Parts Used", "Quality Check", Visibility.READONLY),
            VisibilityEntry("Quality Check", "Quality Check", Visibility.EDITABLE),
            # a field-level override: at Quality Check, only Repair Cost (inside the "Repair"
            # section, being reviewed) is locked read-only — the rest of that section is not
            # otherwise mentioned at this stage, so this is a targeted, single-field rule.
            VisibilityEntry("Repair", "Quality Check", Visibility.READONLY, field="Repair Cost"),
        )),
        timing=Timing(
            sla_notes="Diagnose must finish within 1 business day of intake",
            batch_days=("Friday",),
            reminders=("remind the technician if a job sits over 3 days",),
        ),
        personas=Personas(views=(
            PersonaView(
                "Service Manager",
                pages=(PageIntent("Manager Dashboard", (
                    WidgetIntent("metrics", config=(("flow_type", "process"),
                                                     ("flow_id", "RepairJobs"))),
                    WidgetIntent("view/table", config=(("flow_type", "process"),
                                                        ("flow_id", "RepairJobs"),
                                                        ("view_id", "myitems"))),
                )),),
                kpis=("open jobs", "overdue jobs"),
                actions=("reassign job", "approve quality check"),
            ),
            PersonaView(
                "Technician",
                pages=(PageIntent("My Jobs", (
                    WidgetIntent("view/table", config=(("flow_type", "process"),
                                                        ("flow_id", "RepairJobs"),
                                                        ("view_id", "assigned"))),
                )),),
                kpis=("jobs assigned to me",),
                actions=("submit diagnosis", "mark repaired"),
            ),
            PersonaView(
                "Front Desk",
                # deliberately the SAME page name as Service Manager, to exercise dedup + kpi/
                # action/WIDGET aggregation across roles (F6): "general/label" appears ONLY here,
                # never on Service Manager's copy of this page, so a passing
                # test_build_page_aggregates_widgets_across_roles_not_just_first proves it isn't
                # silently dropped just because Service Manager's PageIntent is the one
                # _unique_pages happens to keep for page-identity purposes.
                pages=(PageIntent("Manager Dashboard", (
                    WidgetIntent("metrics", config=(("flow_type", "process"),
                                                     ("flow_id", "RepairJobs"))),
                    WidgetIntent("view/table", config=(("flow_type", "process"),
                                                        ("flow_id", "RepairJobs"),
                                                        ("view_id", "myitems"))),
                    WidgetIntent("general/label"),
                )),),
                kpis=("jobs awaiting pickup",),
                actions=("log new unit", "notify customer"),
            ),
        )),
        test_cases=TestCases(cases=(
            CaseWalk(
                "Straightforward repair",
                fills=(
                    StepFill("Intake", (("Unit Name", "Printer"), ("Urgency", "Medium"))),
                    StepFill("Diagnose", (("Repairable", "Yes"),)),
                    StepFill("Quality Check", (("Quality Passed", "true"),)),
                ),
                expected_path=("Intake", "Diagnose", "Repair", "Quality Check",
                               "Return to Customer"),
                expected_result="Repaired",
            ),
            CaseWalk(
                "Beyond repair",
                fills=(
                    StepFill("Intake", (("Unit Name", "Old Fax Machine"), ("Urgency", "Low"))),
                    StepFill("Diagnose", (("Repairable", "No"),)),
                ),
                expected_path=("Intake", "Diagnose", "Return to Customer"),
                expected_result="Beyond repair",
            ),
            CaseWalk(
                # proves the exact expressiveness M11 demanded: the SAME stage visited twice
                # with DIFFERENT values, so a rework-loop case can tick its Boolean gate false
                # the first time and true the second — see
                # test_looped_case_can_tick_gate_differently_per_visit
                "Rework then pass",
                fills=(
                    StepFill("Intake", (("Unit Name", "Blender"), ("Urgency", "High"))),
                    StepFill("Diagnose", (("Repairable", "Yes"),)),
                    StepFill("Quality Check", (("Quality Passed", "false"),)),
                    StepFill("Quality Check", (("Quality Passed", "true"),)),
                ),
                expected_path=("Intake", "Diagnose", "Repair", "Quality Check", "Repair",
                               "Quality Check", "Return to Customer"),
                expected_result="Repaired",
            ),
        )),
        approved=approved,
    )


def _linear_spec(*, approved: bool = True) -> AppSpec:
    """A deliberately minimal, straight-line app: NO branch, NO rework loop, NO reference list —
    all three confirmed explicitly `confirmed_none=True` rather than invented. Proves dimensions
    4/5/7 no longer force a business to manufacture fake divergence just to satisfy this schema
    (see `test_linear_spec_needs_no_branch_or_loop_or_list`). Timing is also left blank on
    purpose, doubling as proof that the advisory dimension does not block compilation either.
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
        roles=Roles(roles=(
            RoleSpec("Front Desk", is_admin=False),
            RoleSpec("Manager", is_admin=True),
        )),
        stages=Stages(stages=(
            StageSpec("Log Ticket", "Front Desk", "record the request", "a request comes in",
                      "ticket logged"),
            StageSpec("Handle Ticket", "Manager", "resolve the request", "ticket logged",
                      "request resolved"),
        )),
        routing=Routing(points=(), confirmed_none=True),
        rework_loops=ReworkLoops(loops=(), confirmed_none=True),
        data_model=DataModel(
            fields=(FieldReq("Request Text", FieldType.TEXT, True, "Log Ticket"),),
            tables=(),
            computed=(),
        ),
        master_data=MasterData(lists=(), confirmed_none=True),
        visibility=VisibilityMatrix(entries=(
            VisibilityEntry("Log Ticket", START_STAGE, Visibility.EDITABLE),
            VisibilityEntry("Log Ticket", "Log Ticket", Visibility.EDITABLE),
            VisibilityEntry("Log Ticket", "Handle Ticket", Visibility.READONLY),
            VisibilityEntry("Handle Ticket", "Handle Ticket", Visibility.EDITABLE),
        )),
        timing=Timing(sla_notes="", batch_days=(), reminders=()),  # left blank on purpose
        personas=Personas(views=(
            PersonaView("Manager", pages=(PageIntent("Tickets", (WidgetIntent("general/label"),)),),
                        kpis=(), actions=()),
        )),
        test_cases=TestCases(cases=(
            CaseWalk("Simple ticket",
                     fills=(StepFill("Log Ticket", (("Request Text", "Fix the printer"),)),),
                     expected_path=("Log Ticket", "Handle Ticket"), expected_result="Resolved"),
        )),
        approved=approved,
    )


def _branch_local_loop_spec(*, approved: bool = True) -> AppSpec:
    """S3 (#34): a split whose 'Complex' branch is a SEQUENCE of stages (Deep Review -> Fix ->
    Verify) with a rework loop INSIDE that branch — Verify jumps back to Fix, gated on a Boolean.
    Both loop endpoints live in the same branch, so it is branch-local (never cross-branch). The
    'Simple' branch is a single stage with no loop. Minimal but fully valid across all 11 dims."""
    return AppSpec(
        app_name="Claim Review",
        problem_goal=ProblemGoal(
            pain="claims get handled inconsistently", goal="every claim is triaged and closed",
            done_definition="the claim is closed", terminal_states=("Closed",),
            result_values=("Settled",)),
        roles=Roles(roles=(
            RoleSpec("Intake", is_admin=False),
            RoleSpec("Adjuster", is_admin=True),
        )),
        stages=Stages(stages=(
            StageSpec("Log", "Intake", "log the claim", "a claim arrives", "claim logged"),
            StageSpec("Triage", "Adjuster", "decide the path", "claim logged", "path chosen"),
            StageSpec("Quick Close", "Adjuster", "close a simple claim", "path is Simple",
                      "claim closed"),
            StageSpec("Deep Review", "Adjuster", "review a complex claim", "path is Complex",
                      "reviewed"),
            StageSpec("Fix", "Adjuster", "correct the claim", "review found an issue", "corrected"),
            StageSpec("Verify", "Adjuster", "verify the correction", "corrected", "verified"),
            StageSpec("Close", "Intake", "close the claim", "verified or quick-closed", "closed"),
        )),
        routing=Routing(points=(
            DecisionPoint(at_stage="Triage", field_name="Path", options=("Simple", "Complex"),
                          route_per_option=(("Simple", ("Quick Close",)),
                                            ("Complex", ("Deep Review", "Fix", "Verify")))),
        )),
        rework_loops=ReworkLoops(loops=(
            LoopSpec(from_stage="Verify", to_stage="Fix", gate_field="Fix Approved", max_rounds=3),
        )),
        data_model=DataModel(
            fields=(
                FieldReq("Claim Text", FieldType.TEXT, True, "Log"),
                FieldReq("Path", FieldType.SELECT, True, "Triage", list_name="Paths"),
                FieldReq("Fix Approved", FieldType.BOOLEAN, False, "Verify"),
            ),
            tables=(), computed=()),
        master_data=MasterData(lists=(ListSpec("Paths", ("Simple", "Complex"), "Adjuster"),)),
        visibility=VisibilityMatrix(entries=(
            VisibilityEntry("Log", START_STAGE, Visibility.EDITABLE),
            VisibilityEntry("Log", "Log", Visibility.EDITABLE),
            VisibilityEntry("Triage", "Triage", Visibility.EDITABLE),
            VisibilityEntry("Verify", "Verify", Visibility.EDITABLE),
        )),
        timing=Timing(sla_notes="", batch_days=(), reminders=()),
        personas=Personas(views=(
            PersonaView("Adjuster", pages=(PageIntent("Board", (WidgetIntent("general/label"),)),),
                        kpis=(), actions=()),
        )),
        test_cases=TestCases(cases=(
            CaseWalk("Complex claim, one rework round",
                     fills=(
                         StepFill("Log", (("Claim Text", "Water damage"),)),
                         StepFill("Triage", (("Path", "Complex"),)),
                         StepFill("Verify", (("Fix Approved", "true"),)),
                     ),
                     expected_path=("Log", "Triage", "Deep Review", "Fix", "Verify", "Close"),
                     expected_result="Settled"),
        )),
        approved=approved,
    )


_EMPTY_SPEC = AppSpec(
    app_name="",
    problem_goal=ProblemGoal(pain="", goal="", done_definition="", terminal_states=(),
                             result_values=()),
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


def _dims(gaps: tuple[str, ...]) -> list[int]:
    """Dimension numbers named by a `gaps()` result, in order (each sentence is `"N. name: ..."`)."""
    return [int(s.split(".", 1)[0]) for s in gaps]


def _replace_data_model(spec: AppSpec, **kwargs: object) -> AppSpec:
    """Convenience: `dataclasses.replace` one level deeper, into `spec.data_model`."""
    return dataclasses.replace(spec, data_model=dataclasses.replace(spec.data_model, **kwargs))


# ---- schema: frozen structs, no dimension silently skipped -----------------------------------

def test_dataclasses_are_frozen() -> None:
    spec = _full_spec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.app_name = "Something Else"  # type: ignore[misc]


def test_dimension_names_has_all_11_in_order() -> None:
    assert len(DIMENSION_NAMES) == 11
    assert DIMENSION_NAMES[0] == "problem/goal"
    assert DIMENSION_NAMES[10] == "test cases"


def test_full_spec_has_no_gaps() -> None:
    assert _full_spec().gaps() == ()
    assert _full_spec().blocking_gaps() == ()


def test_empty_spec_has_11_gaps() -> None:
    gaps = _EMPTY_SPEC.gaps()
    assert len(gaps) == 11
    assert _dims(gaps) == list(range(1, 12))


def test_empty_spec_blocking_gaps_excludes_advisory_dimension() -> None:
    assert ADVISORY_DIMENSIONS == frozenset({9})
    blocking = _EMPTY_SPEC.blocking_gaps()
    assert len(blocking) == 10
    assert 9 not in _dims(blocking)
    assert _dims(blocking) == [n for n in range(1, 12) if n != 9]


def test_partially_filled_spec_has_exactly_the_missing_dimensions() -> None:
    # fill in ONLY 1 (problem/goal), 2 (roles), 3 (stages) — dimensions 4..11 stay empty/unconfirmed
    full = _full_spec()
    partial = dataclasses.replace(
        _EMPTY_SPEC,
        problem_goal=full.problem_goal,
        roles=full.roles,
        stages=full.stages,
    )
    assert _dims(partial.gaps()) == [4, 5, 6, 7, 8, 9, 10, 11]


def test_filling_the_last_gap_clears_it() -> None:
    # start from the complete spec, blank out ONLY timing (dimension 9)
    spec = dataclasses.replace(_full_spec(), timing=Timing(sla_notes="", batch_days=(),
                                                           reminders=()))
    assert _dims(spec.gaps()) == [9]


# ---- M14: dimensions 4/5/7 satisfiable by an explicit "none" instead of non-emptiness ---------

def test_confirmed_none_satisfies_routing_rework_and_master_data_gaps() -> None:
    spec = _linear_spec()
    assert _dims(spec.gaps()) == [9]  # ONLY the advisory dimension remains
    assert spec.blocking_gaps() == ()


def test_linear_spec_needs_no_branch_or_loop_or_list() -> None:
    """The exact bug M14 named: a straight-line flow used to have to invent a fake
    DecisionPoint and a fake LoopSpec. Proven fixed: this spec has NEITHER, is fully valid, and
    compiles to zero add_goto_gate / create_list ops."""
    plan = compile_spec(_linear_spec())
    summary = plan.summary()
    assert summary.get("add_goto_gate", 0) == 0
    assert summary.get("create_list", 0) == 0
    assert sum(summary.values()) == len(plan.ops) == 16
    assert set(summary) <= set(OP_ORDER)


def test_confirmed_none_defaults_to_false_so_a_blank_dimension_still_gaps() -> None:
    # without the explicit flag, an empty Routing/ReworkLoops/MasterData is STILL a gap — the
    # escape hatch is opt-in, never silently assumed
    spec = dataclasses.replace(_full_spec(), routing=Routing(points=()),
                                rework_loops=ReworkLoops(loops=()),
                                master_data=MasterData(lists=()))
    assert _dims(spec.gaps()) == [4, 5, 7]


# ---- questions: only gap dimensions, priority order, limit respected -------------------------

def test_next_questions_empty_when_spec_is_complete() -> None:
    assert next_questions(_full_spec()) == ()


def test_next_questions_priority_order_and_default_limit() -> None:
    # priority order is 1,2,3,6,7,4,5,8,11,10,9 (m21: roles before stages, data model before
    # routing/loops); dim1 has 2 questions, dim2 has 1, dim3 has 1 — limit=4 exhausts exactly
    # dims 1, 2, 3
    got = next_questions(_EMPTY_SPEC, limit=4)
    assert [q.id for q in got] == ["1a", "1b", "2a", "3a"]


def test_next_questions_respects_a_larger_limit() -> None:
    # one more dimension's worth (dim6 has 2 questions) fits in a limit of 6
    got = next_questions(_EMPTY_SPEC, limit=6)
    assert [q.id for q in got] == ["1a", "1b", "2a", "3a", "6a", "6b"]


def test_next_questions_only_asks_about_the_one_remaining_gap() -> None:
    spec = dataclasses.replace(_full_spec(), timing=Timing(sla_notes="", batch_days=(),
                                                           reminders=()))
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
    """m19: a business owner should never be able to answer with a type that doesn't exist."""
    q6a = next(q for q in QUESTIONS[6] if q.id == "6a")
    for t in FieldType:
        assert t.value in q6a.why


def test_optional_dimension_questions_invite_a_none_answer() -> None:
    """M14: the interview script itself must not pressure a fake branch/loop/list into existence."""
    for dim, marker in ((4, "ไม่มี"), (5, "ไม่มี"), (7, "ไม่มี")):
        assert any(marker in q.text_th or marker in q.why for q in QUESTIONS[dim])


# ---- compile_spec: the two upfront refusals ---------------------------------------------------

def test_compile_refuses_unapproved_spec() -> None:
    with pytest.raises(ValueError, match="confirmation required first"):
        compile_spec(_full_spec(approved=False))


def test_compile_refuses_incomplete_spec_and_lists_gaps() -> None:
    spec = dataclasses.replace(_full_spec(), roles=Roles(roles=()))
    with pytest.raises(ValueError, match=r"2\. roles"):
        compile_spec(spec)


def test_compile_does_not_refuse_over_advisory_timing_alone() -> None:
    """M13: do not keep gating on data the engine cannot act on."""
    spec = dataclasses.replace(_full_spec(), timing=Timing(sla_notes="", batch_days=(),
                                                           reminders=()))
    plan = compile_spec(spec)  # must NOT raise
    assert isinstance(plan, BuildPlan)


# ---- B1: assignees ------------------------------------------------------------------------

def test_set_assignees_carries_stage_and_owner_role() -> None:
    plan = compile_spec(_full_spec())
    assignee_ops = [op for op in plan.ops if op.kind == "set_assignees"]
    assert len(assignee_ops) == 5
    pairs = sorted((op.args["stage"], op.args["owner_role"]) for op in assignee_ops)
    assert pairs == sorted([
        ("Intake", "Front Desk"), ("Diagnose", "Technician"), ("Repair", "Technician"),
        ("Quality Check", "Service Manager"), ("Return to Customer", "Front Desk"),
    ])
    for op in assignee_ops:
        assert "AppRole" in op.why


def test_set_assignees_sits_between_build_workflow_and_add_goto_gate() -> None:
    i_workflow = OP_ORDER.index("build_workflow")
    i_assignees = OP_ORDER.index("set_assignees")
    i_goto = OP_ORDER.index("add_goto_gate")
    assert i_workflow < i_assignees < i_goto


# ---- S4 (#35): branch conditions attach right after the Goto gates, before visibility ----------

def test_set_branch_conditions_sits_between_add_goto_gate_and_set_visibility() -> None:
    """S4 (#35): the branch-condition op that turns S1's unconditional Parallel into a real
    conditional split belongs right after the Goto gates (Build order step 7 covers both the
    per-branch loop half and the deciding-field half together) and before the visibility matrix
    (Build order step 8)."""
    i_goto = OP_ORDER.index("add_goto_gate")
    i_branch_conditions = OP_ORDER.index("set_branch_conditions")
    i_visibility = OP_ORDER.index("set_visibility")
    assert i_goto < i_branch_conditions < i_visibility


# ---- B2: master-data list values must reach the plan ------------------------------------------

def test_create_list_carries_values_and_is_human_gated() -> None:
    plan = compile_spec(_full_spec())
    list_ops = [op for op in plan.ops if op.kind == "create_list"]
    assert len(list_ops) == 2
    by_name = {op.args["name"]: op for op in list_ops}
    assert by_name["Urgency Levels"].args["values"] == ("High", "Medium", "Low")
    assert by_name["Yes No"].args["values"] == ("Yes", "No")
    for op in list_ops:
        assert "HUMAN-GATED" in op.why
        assert "ReferredList" in op.why


def test_create_list_precedes_apply_fields() -> None:
    assert OP_ORDER.index("create_list") < OP_ORDER.index("apply_fields")


# ---- M3: gate polarity resolved against real fields, not a self-declared flag ------------------

def test_check_loop_gate_unknown_field_raises() -> None:
    bad = dataclasses.replace(_full_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Quality Check", to_stage="Repair", gate_field="Does Not Exist",
                 max_rounds=3),
    )))
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


def test_check_loop_gate_wrong_type_raises() -> None:
    bad = dataclasses.replace(_full_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Quality Check", to_stage="Repair", gate_field="Repair Cost",
                 max_rounds=3),  # Repair Cost is Number, not Boolean
    )))
    with pytest.raises(ValueError, match="Repair Cost"):
        compile_spec(bad)


# ---- M4: routing — at_stage/targets known, every option routed, literals validated ------------

def test_check_routing_unknown_at_stage_raises() -> None:
    bad = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Nonexistent Stage", field_name="Repairable",
                      options=("Yes", "No"),
                      route_per_option=(("Yes", ("Repair",)), ("No", ("Return to Customer",)))),
    )))
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_check_routing_unknown_target_stage_raises() -> None:
    bad = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                      route_per_option=(("Yes", ("Nonexistent Target",)),
                                        ("No", ("Return to Customer",)))),
    )))
    with pytest.raises(ValueError, match="Nonexistent Target"):
        compile_spec(bad)


def test_check_routing_unrouted_option_raises() -> None:
    bad = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable",
                      options=("Yes", "No", "Maybe Later"),
                      route_per_option=(("Yes", ("Repair",)), ("No", ("Return to Customer",)))),
    )))
    with pytest.raises(ValueError, match="routed options"):
        compile_spec(bad)


def test_check_routing_literal_not_in_list_raises() -> None:
    bad = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "Maybe"),
                      route_per_option=(("Yes", ("Repair",)), ("Maybe", ("Repair",)))),
    )))
    with pytest.raises(ValueError, match="Maybe"):
        compile_spec(bad)


def test_a_branch_route_may_be_a_sequence_of_stages() -> None:
    """P1 (#30): route_per_option maps an option to an ORDERED LIST of stages; compile accepts a
    multi-stage branch as long as every named stage is real (a one-element list is the old
    single-stage route). Building it as a Parallel is S1 (#32) — here it only has to compile."""
    spec = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                      route_per_option=(("Yes", ("Repair", "Quality Check")),
                                        ("No", ("Return to Customer",)))),
    )))
    compile_spec(spec)  # must not raise


def test_check_routing_empty_target_sequence_raises() -> None:
    """A route to an EMPTY sequence names no stage at all — a dead-end the single-stage shape could
    never express. The list shape makes it possible, so compile must refuse it loudly."""
    bad = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                      route_per_option=(("Yes", ()), ("No", ("Return to Customer",)))),
    )))
    with pytest.raises(ValueError, match="empty"):
        compile_spec(bad)


# ---- M5: loops — from/to stage known, and strictly backward ------------------------------------

def test_check_loop_unknown_from_stage_raises() -> None:
    bad = dataclasses.replace(_full_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Nonexistent", to_stage="Repair", gate_field="Quality Passed"),
    )))
    with pytest.raises(ValueError, match="Nonexistent"):
        compile_spec(bad)


def test_check_loop_unknown_to_stage_raises() -> None:
    bad = dataclasses.replace(_full_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Quality Check", to_stage="Nonexistent", gate_field="Quality Passed"),
    )))
    with pytest.raises(ValueError, match="Nonexistent"):
        compile_spec(bad)


def test_check_loop_forward_direction_raises() -> None:
    bad = dataclasses.replace(_full_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Intake", to_stage="Repair", gate_field="Quality Passed"),  # forward!
    )))
    with pytest.raises(ValueError, match="not backward"):
        compile_spec(bad)


# ---- M6: sections are a real dimension, not forced-equal-to-stage -----------------------------

def test_two_sections_at_one_stage_expressible() -> None:
    plan = compile_spec(_full_spec())
    intake_ops = [op for op in plan.ops
                  if op.kind == "apply_fields" and op.args["stage"] == "Intake"]
    assert len(intake_ops) == 1
    sections_used = {f["section"] for f in intake_ops[0].args["fields"]}
    assert sections_used == {"Intake Basics", "Intake Priority"}


def test_check_section_unknown_stage_raises() -> None:
    full = _full_spec()
    bad = _replace_data_model(
        full, sections=full.data_model.sections + (
            SectionReq("Orphan Section", "Nonexistent Stage", "desc"),
        ),
    )
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_check_field_unknown_section_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        dataclasses.replace(f, section="No Such Section") if f.name == "Repairable" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="No Such Section"):
        compile_spec(bad)


def test_check_field_section_belongs_to_different_stage_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        dataclasses.replace(f, section="Intake Basics") if f.name == "Repairable" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Repairable"):
        compile_spec(bad)


# ---- M7: field-level visibility override ------------------------------------------------------

def test_visibility_field_level_entry_present() -> None:
    plan = compile_spec(_full_spec())
    vis_op = next(op for op in plan.ops if op.kind == "set_visibility")
    field_entries = [e for e in vis_op.args["entries"] if e["field"] is not None]
    assert len(field_entries) == 1
    assert field_entries[0]["field"] == "Repair Cost"


def test_check_visibility_unknown_field_raises() -> None:
    bad = dataclasses.replace(_full_spec(), visibility=VisibilityMatrix(entries=(
        VisibilityEntry("Intake", "Intake", Visibility.EDITABLE, field="Does Not Exist"),
    )))
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


# ---- M8: Start must be owned by the first stage's own section ---------------------------------

def test_check_start_not_owned_raises() -> None:
    full = _full_spec()
    entries_without_start = tuple(e for e in full.visibility.entries if e.stage != START_STAGE)
    bad = dataclasses.replace(full, visibility=VisibilityMatrix(entries=entries_without_start))
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


def test_check_start_owned_by_wrong_section_raises() -> None:
    full = _full_spec()
    entries = tuple(
        VisibilityEntry("Parts Used", START_STAGE, Visibility.EDITABLE)
        if e.stage == START_STAGE else e
        for e in full.visibility.entries
    )
    bad = dataclasses.replace(full, visibility=VisibilityMatrix(entries=entries))
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


# ---- M9: table columns carry type/required; stage and max_rows validated ----------------------

def test_add_table_columns_carry_type_and_required() -> None:
    plan = compile_spec(_full_spec())
    table_op = next(op for op in plan.ops if op.kind == "add_table")
    cols = {c["name"]: c for c in table_op.args["columns"]}
    assert cols["Part Name"] == {"name": "Part Name", "type": "Text", "required": True}
    assert cols["Quantity"]["type"] == "Number"


def test_check_table_unknown_stage_raises() -> None:
    full = _full_spec()
    bad_tables = tuple(dataclasses.replace(t, stage="Nonexistent") for t in full.data_model.tables)
    bad = _replace_data_model(full, tables=bad_tables)
    with pytest.raises(ValueError, match="Nonexistent"):
        compile_spec(bad)


def test_check_table_non_positive_max_rows_raises() -> None:
    full = _full_spec()
    bad_tables = tuple(dataclasses.replace(t, max_rows=0) for t in full.data_model.tables)
    bad = _replace_data_model(full, tables=bad_tables)
    with pytest.raises(ValueError, match="max_rows"):
        compile_spec(bad)


# ---- M10: computed fields resolve against real fields + table columns; trigger is an enum -----

def test_check_computed_unknown_target_raises() -> None:
    full = _full_spec()
    bad = _replace_data_model(full, computed=(
        ComputedReq("Does Not Exist", ("Quantity", "Unit Cost"), EventTrigger.ON_CHANGE, "x"),
    ))
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


def test_check_computed_unknown_source_raises() -> None:
    full = _full_spec()
    bad = _replace_data_model(full, computed=(
        ComputedReq("Total Parts Cost", ("Nonexistent Column",), EventTrigger.ON_CHANGE, "x"),
    ))
    with pytest.raises(ValueError, match="Nonexistent Column"):
        compile_spec(bad)


def test_computed_source_resolves_against_table_columns() -> None:
    """The original bug M10 named: a computed field wired onto columns that don't exist. Proven
    fixed — `_full_spec()` itself compiles clean with source_fields pointing at real
    Parts Used table columns, not a phantom field."""
    plan = compile_spec(_full_spec())
    events = [op for op in plan.ops if op.kind == "set_events"]
    assert len(events) == 1
    assert events[0].args["source_fields"] == ("Quantity", "Unit Cost")
    assert events[0].args["target_field"] == "Total Parts Cost"


def test_set_events_flags_unverified_trigger() -> None:
    full = _full_spec()
    bad_computed = tuple(
        dataclasses.replace(c, trigger=EventTrigger.ON_SELECT) for c in full.data_model.computed
    )
    spec = _replace_data_model(full, computed=bad_computed)
    plan = compile_spec(spec)
    event_op = next(op for op in plan.ops if op.kind == "set_events")
    assert "UNVERIFIED" in event_op.why


def test_set_events_confirms_on_change_trigger() -> None:
    plan = compile_spec(_full_spec())
    event_op = next(op for op in plan.ops if op.kind == "set_events")
    assert "CONFIRMED" in event_op.why


# ---- M11: test cases validated for real; per-stage-visit fills, not a flat dict ---------------

def test_check_case_unknown_fill_field_raises() -> None:
    bad = dataclasses.replace(_full_spec(), test_cases=TestCases(cases=(
        CaseWalk("Bad case", (StepFill("Intake", (("Does Not Exist", "x"),)),),
                 ("Intake",), "Repaired"),
    )))
    with pytest.raises(ValueError, match="Does Not Exist"):
        compile_spec(bad)


def test_check_case_select_value_not_in_list_raises() -> None:
    bad = dataclasses.replace(_full_spec(), test_cases=TestCases(cases=(
        CaseWalk("Bad case", (StepFill("Intake", (("Urgency", "Critical"),)),),
                 ("Intake",), "Repaired"),
    )))
    with pytest.raises(ValueError, match="Critical"):
        compile_spec(bad)


def test_check_case_expected_result_not_in_result_values_raises() -> None:
    bad = dataclasses.replace(_full_spec(), test_cases=TestCases(cases=(
        CaseWalk("Bad case", (), ("Intake",), "Not A Real Result"),
    )))
    with pytest.raises(ValueError, match="Not A Real Result"):
        compile_spec(bad)


def test_check_case_fill_stage_not_in_path_raises() -> None:
    bad = dataclasses.replace(_full_spec(), test_cases=TestCases(cases=(
        CaseWalk("Bad case", (StepFill("Repair", (("Repair Cost", "10"),)),),
                 ("Intake",), "Repaired"),
    )))
    with pytest.raises(ValueError, match="never visits"):
        compile_spec(bad)


def test_check_case_expected_path_unknown_stage_raises() -> None:
    bad = dataclasses.replace(_full_spec(), test_cases=TestCases(cases=(
        CaseWalk("Bad case", (), ("Intake", "Nonexistent Stage"), "Repaired"),
    )))
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_looped_case_can_tick_gate_differently_per_visit() -> None:
    """The exact expressiveness M11 demanded: two StepFills for the SAME re-visited stage, one
    false one true — proof a flat single-value-per-field dict could never have expressed this."""
    plan = compile_spec(_full_spec())
    sim_ops = {op.args["name"]: op for op in plan.ops if op.kind == "simulate_case"}
    rework_case = sim_ops["Rework then pass"]
    qc_fills = [f for f in rework_case.args["fills"] if f["stage"] == "Quality Check"]
    assert len(qc_fills) == 2
    assert qc_fills[0]["values"]["Quality Passed"] == "false"
    assert qc_fills[1]["values"]["Quality Passed"] == "true"


# ---- M12: widgets validated against the real palette; persona roles validated -----------------

def test_check_widget_unknown_slug_raises() -> None:
    full = _full_spec()
    bad_view = dataclasses.replace(
        full.personas.views[0],
        pages=(PageIntent("Bad Page", (WidgetIntent("not/a/real/slug"),)),),
    )
    bad = dataclasses.replace(full, personas=Personas(views=(bad_view, *full.personas.views[1:])))
    with pytest.raises(ValueError, match="not/a/real/slug"):
        compile_spec(bad)


def test_check_widget_missing_required_config_raises() -> None:
    full = _full_spec()
    bad_view = dataclasses.replace(
        full.personas.views[0],
        pages=(PageIntent("Bad Page",
                          (WidgetIntent("view/table", config=(("flow_type", "process"),)),)),),
        # missing flow_id and view_id
    )
    bad = dataclasses.replace(full, personas=Personas(views=(bad_view, *full.personas.views[1:])))
    with pytest.raises(ValueError, match="flow_id"):
        compile_spec(bad)


def test_check_widget_missing_row_fields_raises() -> None:
    full = _full_spec()
    bad_view = dataclasses.replace(
        full.personas.views[0],
        pages=(PageIntent("Bad Page", (
            WidgetIntent("repeater", config=(("flow_type", "process"), ("flow_id", "x"),
                                             ("view_id", "myitems"))),
        )),),  # row_fields left empty
    )
    bad = dataclasses.replace(full, personas=Personas(views=(bad_view, *full.personas.views[1:])))
    with pytest.raises(ValueError, match="row_fields"):
        compile_spec(bad)


def test_check_persona_unknown_role_raises() -> None:
    full = _full_spec()
    bad_view = dataclasses.replace(full.personas.views[0], role="Nonexistent Role")
    bad = dataclasses.replace(full, personas=Personas(views=(bad_view, *full.personas.views[1:])))
    with pytest.raises(ValueError, match="Nonexistent Role"):
        compile_spec(bad)


def test_widget_with_no_required_config_needs_none() -> None:
    # general/label has no entry in WIDGET_REQUIRED_CONFIG at all — must not spuriously raise
    plan = compile_spec(_linear_spec())
    assert isinstance(plan, BuildPlan)


# ---- M13: nothing collected is silently discarded ----------------------------------------------

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


# ---- S1 (#32): one decision split compiles to a Parallel gateway with its branches ------------

def _workflow_op(spec: AppSpec) -> Op:
    return next(op for op in compile_spec(spec).ops if op.kind == "build_workflow")


def test_one_split_compiles_to_a_parallel_with_its_branches() -> None:
    """S1 (#32) AC1: the single DecisionPoint in _full_spec (Diagnose -> Yes:Repair / No:Return)
    is lifted into a Parallel gateway whose branches ARE the option route sequences, and the
    branch stages are removed from the linear spine. Still ONE build_workflow op (the whole
    ProcessDef), now carrying the parallel structure kfforge.graph.build_workflow consumes."""
    op = _workflow_op(_full_spec())
    # branch stages lifted out of the linear spine; the fork stem and merge stay linear
    assert op.args["steps"] == ("Intake", "Diagnose", "Quality Check")
    parallels = op.args["parallels"]
    assert len(parallels) == 1
    parallel = parallels[0]
    assert parallel["name"] == "Repairable"            # the deciding field
    assert parallel["after"] == 1                       # inserted right after "Diagnose"
    assert parallel["branches"] == (
        {"name": "Yes", "stages": ("Repair",)},
        {"name": "No", "stages": ("Return to Customer",)},
    )


def test_split_branch_may_be_a_multi_stage_sequence() -> None:
    """A branch is an ORDERED SEQUENCE of stages (P1 #30): the whole sequence becomes ONE
    Parallel branch, in order, every stage lifted out of the linear spine."""
    spec = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                      route_per_option=(("Yes", ("Repair", "Quality Check")),
                                        ("No", ("Return to Customer",)))),
    )))
    parallel = _workflow_op(spec).args["parallels"][0]
    assert parallel["branches"][0] == {"name": "Yes", "stages": ("Repair", "Quality Check")}
    # both branch's stages are gone from the linear spine; only stem + prefix remain
    assert _workflow_op(spec).args["steps"] == ("Intake", "Diagnose")


def test_branch_order_follows_declared_options_not_route_map_order() -> None:
    """Branch order is the DECIDING FIELD's declared option order, so it lines up with the diagram
    (which iterates `options`) and with S4's per-branch conditions — not whatever order
    route_per_option's pairs happen to be written in."""
    spec = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                      # route pairs written No-first on purpose
                      route_per_option=(("No", ("Return to Customer",)), ("Yes", ("Repair",)))),
    )))
    names = [b["name"] for b in _workflow_op(spec).args["parallels"][0]["branches"]]
    assert names == ["Yes", "No"]


def test_linear_spec_has_no_parallel() -> None:
    """S1 (#32) AC3: a spec with no decision split is unaffected — no Parallels, steps are simply
    every stage in order."""
    op = _workflow_op(_linear_spec())
    assert op.args["parallels"] == ()
    assert op.args["steps"] == tuple(s.name for s in _linear_spec().stages.stages)


# ---- S2 (#33): N sequential splits — split, rejoin, later split, rejoin -----------------------

def test_two_sequential_splits_compile_to_two_parallels_in_order() -> None:
    """D3 (#29 spec decisions): S2 generalises S1's one-split shape to N SEQUENTIAL splits. Two
    independent DecisionPoints — Diagnose (existing) and a new one at Quality Check, each on its
    own field with its own distinct branch stages and distinct option names — compile to two
    Parallel gateways, in declared point order, and BOTH splits' branch stages are lifted out of
    the ONE shared linear spine."""
    full = _full_spec()
    spec = dataclasses.replace(
        full,
        stages=Stages(stages=full.stages.stages + (
            StageSpec("Escalate to Manager", "Service Manager",
                      "escalate the finished job for a second look",
                      "quality check flagged it for escalation", "manager has reviewed it"),
            StageSpec("Notify Front Desk", "Front Desk", "tell front desk the job is ready",
                      "quality check passed with nothing to escalate", "front desk notified"),
        )),
        data_model=dataclasses.replace(full.data_model, fields=full.data_model.fields + (
            FieldReq("Escalate", FieldType.SELECT, True, "Quality Check",
                     list_name="Escalate Options"),
        )),
        master_data=MasterData(lists=full.master_data.lists + (
            ListSpec("Escalate Options", ("Escalate", "Close"), "Service Manager"),
        )),
        routing=Routing(points=(
            full.routing.points[0],
            DecisionPoint(at_stage="Quality Check", field_name="Escalate",
                          options=("Escalate", "Close"),
                          route_per_option=(("Escalate", ("Escalate to Manager",)),
                                            ("Close", ("Notify Front Desk",)))),
        )),
    )
    op = _workflow_op(spec)
    assert op.args["steps"] == ("Intake", "Diagnose", "Quality Check")
    parallels = op.args["parallels"]
    assert len(parallels) == 2
    first, second = parallels
    assert first["name"] == "Repairable"
    assert first["after"] == 1                          # right after "Diagnose"
    assert first["branches"] == (
        {"name": "Yes", "stages": ("Repair",)},
        {"name": "No", "stages": ("Return to Customer",)},
    )
    assert second["name"] == "Escalate"
    assert second["after"] == 2                          # right after "Quality Check"
    assert second["branches"] == (
        {"name": "Escalate", "stages": ("Escalate to Manager",)},
        {"name": "Close", "stages": ("Notify Front Desk",)},
    )


def test_split_nested_in_a_branch_is_refused() -> None:
    """D3 (#29): a split whose OWN at_stage sits inside a DIFFERENT split's branch has no captured
    shape — refused at compile (THE RULE), naming the nested-split coverage row. Split B's
    at_stage ("Repair") is exactly the stage split A's own "Yes" branch routes through."""
    spec = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                      route_per_option=(("Yes", ("Repair",)), ("No", ("Return to Customer",)))),
        DecisionPoint(at_stage="Repair", field_name="Repairable", options=("Yes", "No"),
                      route_per_option=(("Yes", ("Quality Check",)), ("No", ("Quality Check",)))),
    )))
    with pytest.raises(ValueError, match="nested-split") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Repair" in message
    assert "Diagnose" in message


def test_two_splits_sharing_a_branch_name_are_refused() -> None:
    """D3 (#29): a branch id is a hash of (model, kind, index, name) — two splits declaring the
    SAME option/branch name collide on that id and silently overwrite one another. Refused at
    compile, mirroring graph.build_workflow's own runtime guard. The two splits here are siblings
    (neither nested in the other's branch), so this isolates the duplicate-name refusal alone."""
    spec = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=("Yes", "No"),
                      route_per_option=(("Yes", ("Repair",)), ("No", ("Return to Customer",)))),
        DecisionPoint(at_stage="Quality Check", field_name="Repairable",
                      options=("Yes", "Something Else"),
                      route_per_option=(("Yes", ("Repair",)),
                                        ("Something Else", ("Return to Customer",)))),
    )))
    with pytest.raises(ValueError, match="Yes") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Diagnose" in message
    assert "Quality Check" in message


# ---- S3 (#34): a rework loop is scoped to ITS branch — carried explicitly, and branch-local ----

def test_branch_local_loop_goto_op_carries_its_branch_name() -> None:
    """S3 AC1/US11: a loop whose endpoints both live in one branch compiles to an add_goto_gate op
    that NAMES that branch, so the live layer places the GotoTask inside it (last within it)
    instead of mis-deriving it from an ambiguous target name."""
    plan = compile_spec(_branch_local_loop_spec())
    goto_ops = [op for op in plan.ops if op.kind == "add_goto_gate"]
    assert len(goto_ops) == 1
    args = goto_ops[0].args
    assert (args["from_stage"], args["to_stage"]) == ("Verify", "Fix")
    assert args["branch_name"] == "Complex"


def test_spine_to_branch_loop_resolves_to_the_target_branch() -> None:
    """The `_full_spec` golden loop is Quality Check (spine) -> Repair (inside the 'Yes' branch):
    one endpoint on the spine, one in a branch. That is NOT cross-branch (it stays allowed) and the
    op names the single branch its stages touch — the target's branch, made explicit."""
    plan = compile_spec(_full_spec())
    goto = next(op for op in plan.ops if op.kind == "add_goto_gate")
    assert goto.args["branch_name"] == "Yes"


def test_spine_only_loop_goto_op_has_no_branch_name() -> None:
    """A rework loop whose endpoints are both on the linear spine (no split involved) carries
    branch_name=None — a plain root-chain loop, the pre-S3 shape, now stated explicitly."""
    base = _linear_spec()
    spec = dataclasses.replace(
        base,
        rework_loops=ReworkLoops(loops=(
            LoopSpec(from_stage="Handle Ticket", to_stage="Log Ticket", gate_field="Redo"),
        )),
        data_model=dataclasses.replace(base.data_model, fields=base.data_model.fields + (
            FieldReq("Redo", FieldType.BOOLEAN, False, "Handle Ticket"),
        )),
    )
    goto = next(op for op in compile_spec(spec).ops if op.kind == "add_goto_gate")
    assert goto.args["branch_name"] is None


def test_duplicate_step_name_across_branches_is_refused() -> None:
    """S3 AC2/AC5: the SAME step name in two different branches is refused, naming the
    `duplicate-branch-step` coverage row — a loop's branch is derived from its step names, so a
    name owned by two branches makes that derivation (and the branch id) a coin flip."""
    spec = dataclasses.replace(_branch_local_loop_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Triage", field_name="Path", options=("Simple", "Complex"),
                      # both branches route through "Fix" — one step name, two branches
                      route_per_option=(("Simple", ("Quick Close", "Fix")),
                                        ("Complex", ("Deep Review", "Fix", "Verify")))),
    )))
    with pytest.raises(ValueError, match="duplicate-branch-step") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Fix" in message
    assert "Simple" in message and "Complex" in message


def test_cross_branch_loop_is_refused() -> None:
    """S3 AC3: a loop whose from_stage sits in one branch and to_stage in ANOTHER is refused,
    naming the `cross-branch-jump` coverage row — a loop must stay within its own branch. Verify
    (in 'Complex') jumps back to Quick Close (in 'Simple'): backward in stage order, but across
    branches."""
    spec = dataclasses.replace(_branch_local_loop_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Verify", to_stage="Quick Close", gate_field="Fix Approved"),
    )))
    with pytest.raises(ValueError, match="cross-branch-jump") as exc_info:
        compile_spec(spec)
    message = str(exc_info.value)
    assert "Complex" in message and "Simple" in message


# ---- S4 (#35): one decision split's branch attaches real conditions, not just an unconditional
#      Parallel ------------------------------------------------------------------------------

def test_one_split_emits_one_set_branch_conditions_op_with_the_deciding_field_and_literals() -> None:
    """S4 (#35) AC1/AC2: `_full_spec`'s one DecisionPoint (Diagnose -> Repairable, Yes/No) compiles
    to exactly one `set_branch_conditions` op naming the fork stage, the deciding field, and a
    branch-name -> literal mapping — matching `forge_set_branch_conditions`'s own shape."""
    plan = compile_spec(_full_spec())
    branch_cond_ops = [op for op in plan.ops if op.kind == "set_branch_conditions"]
    assert len(branch_cond_ops) == 1
    op = branch_cond_ops[0]
    assert op.args["at_stage"] == "Diagnose"
    assert op.args["field_name"] == "Repairable"
    assert op.args["branch_literals"] == {"Yes": "Yes", "No": "No"}


def test_linear_spec_emits_no_set_branch_conditions_ops() -> None:
    """S4 (#35) AC3: a spec with no decision split (`_linear_spec`, `routing.points == ()`) has no
    Parallel to condition — `_op_set_branch_conditions` must emit ZERO ops, mirroring
    `_op_add_table` returning `()` when there are no tables."""
    plan = compile_spec(_linear_spec())
    assert [op for op in plan.ops if op.kind == "set_branch_conditions"] == []


def test_check_unclaimed_deciding_value_raises() -> None:
    """S4 (#35) AC3 / CLAUDE.md Conditional routing "Fail OPEN, not closed": a real value of the
    deciding field's list ("Maybe") that no branch option claims must refuse at compile — an item
    with that value would otherwise silently skip the whole Parallel and complete with no work
    done. The DecisionPoint's own `options` ("Yes", "No") are left UNCHANGED and are still valid
    list values, so `_check_routing_literals` (options must be ⊆ list values) does not fire here —
    this is the NEW, opposite check (list values must be ⊆ options)."""
    full = _full_spec()
    bad_lists = tuple(
        dataclasses.replace(l, values=("Yes", "No", "Maybe")) if l.name == "Yes No" else l
        for l in full.master_data.lists
    )
    bad = dataclasses.replace(full, master_data=MasterData(lists=bad_lists))
    with pytest.raises(ValueError) as exc_info:
        compile_spec(bad)
    message = str(exc_info.value)
    assert "Maybe" in message
    assert "unclaimed-value" in message


def test_build_page_carries_aggregated_kpis_and_actions() -> None:
    plan = compile_spec(_full_spec())
    build_ops = {op.args["name"]: op for op in plan.ops if op.kind == "build_page"}
    dash = build_ops["Manager Dashboard"]
    # Service Manager + Front Desk both reference this page — both contributions must be present
    assert dash.args["kpis"] == ("jobs awaiting pickup", "open jobs", "overdue jobs")
    assert dash.args["actions"] == (
        "approve quality check", "log new unit", "notify customer", "reassign job",
    )


def test_timing_blank_does_not_block_but_is_still_collected() -> None:
    spec = dataclasses.replace(_full_spec(), timing=Timing(sla_notes="", batch_days=(),
                                                           reminders=()))
    assert _dims(spec.gaps()) == [9]      # still asked about
    assert spec.blocking_gaps() == ()     # never blocks
    plan = compile_spec(spec)
    assert isinstance(plan, BuildPlan)


# ---- F1 BLOCKER: a Required field Hidden (or unmentioned) at its own stage must raise ----------

def test_check_required_field_hidden_at_own_stage_raises() -> None:
    """The exact reviewer probe: a required field's SECTION is Hidden at the field's own stage —
    used to compile clean; the step becomes unsubmittable and simulate_case can never pass."""
    full = _full_spec()
    entries = tuple(
        VisibilityEntry("Intake Basics", "Intake", Visibility.HIDDEN)
        if (e.section == "Intake Basics" and e.stage == "Intake") else e
        for e in full.visibility.entries
    )
    bad = dataclasses.replace(full, visibility=VisibilityMatrix(entries=entries))
    with pytest.raises(ValueError, match="Unit Name"):
        compile_spec(bad)


def test_check_required_field_with_no_visibility_entry_at_own_stage_raises() -> None:
    """"No entry at all" is exactly as fatal as an explicit Hidden — neither one is a proven
    Editable."""
    full = _full_spec()
    entries = tuple(e for e in full.visibility.entries
                    if not (e.section == "Intake Priority" and e.stage == "Intake"))
    bad = dataclasses.replace(full, visibility=VisibilityMatrix(entries=entries))
    with pytest.raises(ValueError, match="Urgency"):
        compile_spec(bad)


def test_check_required_field_editable_via_field_level_override_passes() -> None:
    # a field-level Editable entry satisfies the check even when the SECTION itself is ReadOnly —
    # the field-level entry is more specific and wins
    full = _full_spec()
    entries = tuple(
        VisibilityEntry("Intake Basics", "Intake", Visibility.READONLY)
        if (e.section == "Intake Basics" and e.stage == "Intake") else e
        for e in full.visibility.entries
    ) + (
        VisibilityEntry("Intake Basics", "Intake", Visibility.EDITABLE, field="Unit Name"),
        VisibilityEntry("Intake Basics", "Intake", Visibility.EDITABLE, field="Customer Name"),
    )
    spec = dataclasses.replace(full, visibility=VisibilityMatrix(entries=entries))
    plan = compile_spec(spec)  # must NOT raise
    assert isinstance(plan, BuildPlan)


# ---- F2 BLOCKER: Start must be owned WITH Editable permission, not just named ------------------

def test_check_start_hidden_raises() -> None:
    """The exact reviewer probe: VisibilityEntry(first section, Start, Hidden) satisfied the OLD
    check (which only asked WHICH section owns Start) but must raise now."""
    full = _full_spec()
    entries = tuple(
        VisibilityEntry("Intake Basics", START_STAGE, Visibility.HIDDEN)
        if e.stage == START_STAGE else e
        for e in full.visibility.entries
    )
    bad = dataclasses.replace(full, visibility=VisibilityMatrix(entries=entries))
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


def test_check_start_readonly_raises() -> None:
    full = _full_spec()
    entries = tuple(
        VisibilityEntry("Intake Basics", START_STAGE, Visibility.READONLY)
        if e.stage == START_STAGE else e
        for e in full.visibility.entries
    )
    bad = dataclasses.replace(full, visibility=VisibilityMatrix(entries=entries))
    with pytest.raises(ValueError, match="Start"):
        compile_spec(bad)


# ---- F3: a Select field's list_name is tied to a real MasterData list --------------------------

def test_check_select_field_no_list_name_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        dataclasses.replace(f, list_name=None) if f.name == "Urgency" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Urgency"):
        compile_spec(bad)


def test_check_select_field_unknown_list_name_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        dataclasses.replace(f, list_name="No Such List") if f.name == "Urgency" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    # Match the unknown-list branch's OWN wording, not just the list name: the name alone also
    # appears in _check_test_cases' message, so a looser match passes even if this check is gone.
    with pytest.raises(ValueError, match=r"names list_name 'No Such List', which is not in"):
        compile_spec(bad)


# ---- F4: DecisionPoint.field_name validated independently of options; empty options rejected ---

def test_check_routing_field_name_unknown_even_with_no_options_raises() -> None:
    """The exact reviewer probe: field_name was only ever reached inside the per-option loop, so
    options=() used to skip validation entirely and a branch on a phantom field compiled clean."""
    bad = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Phantom Field", options=(),
                      route_per_option=()),
    )))
    with pytest.raises(ValueError, match="Phantom Field"):
        compile_spec(bad)


def test_check_routing_empty_options_raises() -> None:
    bad = dataclasses.replace(_full_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Diagnose", field_name="Repairable", options=(),
                      route_per_option=()),
    )))
    with pytest.raises(ValueError, match="zero options"):
        compile_spec(bad)


# ---- F5: field/section stage-mismatch guard now also covers stage-named sections ----------------

def test_check_field_section_mismatched_stage_named_section_raises() -> None:
    """The exact reviewer probe: a field's section names a real STAGE (not an explicit
    SectionReq) that isn't the field's own stage — used to escape the mismatch guard entirely,
    since `owner` (looked up only among SectionReqs) was None and the old guard's `owner is not
    None` condition never even looked further."""
    full = _full_spec()
    bad_fields = tuple(
        dataclasses.replace(f, section="Diagnose") if f.name == "Repair Cost" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Repair Cost"):
        compile_spec(bad)


# ---- F6: build_page aggregates widgets across every role sharing a page, not just the first ----

def test_build_page_aggregates_widgets_across_roles_not_just_first() -> None:
    """The exact reviewer probe: _unique_pages kept only the first PageIntent per name, so
    _op_build_page silently dropped every OTHER role's widgets — contradicting its own docstring
    claim that nothing is dropped (which was already true for kpis/actions, just not widgets)."""
    plan = compile_spec(_full_spec())
    dash = next(op for op in plan.ops
               if op.kind == "build_page" and op.args["name"] == "Manager Dashboard")
    slugs = {w["slug"] for w in dash.args["widgets"]}
    assert "metrics" in slugs
    assert "view/table" in slugs
    assert "general/label" in slugs  # declared ONLY on Front Desk's copy of this page


def test_build_page_widget_dedup_by_slug_and_config() -> None:
    plan = compile_spec(_full_spec())
    dash = next(op for op in plan.ops
               if op.kind == "build_page" and op.args["name"] == "Manager Dashboard")
    # metrics/view-table are declared IDENTICALLY by both Service Manager and Front Desk — each
    # must appear exactly once, not duplicated by the aggregation
    metrics = [w for w in dash.args["widgets"] if w["slug"] == "metrics"]
    assert len(metrics) == 1


# ---- #40 T2: build_page carries page BEHAVIOR (popups + on-click), governed and refusing --------
# #39 T1 gave PageIntent the popups/on_click vocabulary; compile ignored it. #40 wires it into the
# governed build_page op, aggregated across every persona view (no silent drop, same as widgets),
# refuses any behavior shape it can't build, and walks popup-hosted widgets through the same
# widget cross-checks.

def _dashboard_with_behavior() -> AppSpec:
    """`_full_spec()` with the two roles that share 'Manager Dashboard' each declaring their OWN
    popup + on-click wiring — so aggregation across roles (not just the first) is exercised. Both
    actions used (`reassign job`, `notify customer`) are ones their own role already declares."""
    full = _full_spec()
    sm_view = full.personas.views[0]           # Service Manager, declares "reassign job"
    sm_page = dataclasses.replace(
        sm_view.pages[0],
        popups=(PopupIntent("Job Detail", (WidgetIntent("general/label"),)),),
        on_click=(OnClickAction("reassign job", ClickActionKind.OPEN_POPUP,
                                target_popup="Job Detail"),),
    )
    sm2 = dataclasses.replace(sm_view, pages=(sm_page,))
    fd_view = full.personas.views[2]           # Front Desk, same page name, declares "notify customer"
    fd_page = dataclasses.replace(
        fd_view.pages[0],
        popups=(PopupIntent("Unit Detail", (WidgetIntent("general/label"),)),),
        on_click=(OnClickAction("notify customer", ClickActionKind.JS_ACTION,
                                script="kf.doThing()"),),
    )
    fd2 = dataclasses.replace(fd_view, pages=(fd_page,))
    return dataclasses.replace(
        full, personas=Personas(views=(sm2, full.personas.views[1], fd2)))


def test_build_page_carries_popups_and_on_click_aggregated_across_roles() -> None:
    plan = compile_spec(_dashboard_with_behavior())
    dash = next(op for op in plan.ops
               if op.kind == "build_page" and op.args["name"] == "Manager Dashboard")
    # both roles' popups survive aggregation, neither silently dropped for sharing the page name
    assert {p["name"] for p in dash.args["popups"]} == {"Job Detail", "Unit Detail"}
    events = {(e["action"], e["kind"], e["target_popup"]) for e in dash.args["on_click"]}
    assert ("reassign job", "OpenPopup", "Job Detail") in events
    assert ("notify customer", "JSAction", None) in events


def test_build_page_no_behavior_carries_empty_popups_and_on_click() -> None:
    # a plain content-only page still emits the keys (empty), never omits them
    plan = compile_spec(_full_spec())
    jobs = next(op for op in plan.ops
               if op.kind == "build_page" and op.args["name"] == "My Jobs")
    assert jobs.args["popups"] == ()
    assert jobs.args["on_click"] == ()


def test_check_unknown_widget_slug_inside_popup_raises() -> None:
    """AC4: an unknown-slug widget HIDDEN inside a popup is refused, not escaped."""
    full = _full_spec()
    v = full.personas.views[0]
    p = dataclasses.replace(v.pages[0],
                            popups=(PopupIntent("Detail", (WidgetIntent("not/a/real/slug"),)),))
    bad = dataclasses.replace(
        full, personas=Personas(views=(dataclasses.replace(v, pages=(p,)), *full.personas.views[1:])))
    with pytest.raises(ValueError, match="not/a/real/slug"):
        compile_spec(bad)


def test_check_api_impossible_widget_inside_popup_raises_naming_row() -> None:
    """AC3/AC4: an API-impossible widget inside a popup is refused naming its coverage row — the
    popup-opening action can't build, so it's refused, never downgraded to a static button (D6)."""
    full = _full_spec()
    v = full.personas.views[0]
    p = dataclasses.replace(v.pages[0],
                            popups=(PopupIntent("Detail", (WidgetIntent("general/rich_text"),)),))
    bad = dataclasses.replace(
        full, personas=Personas(views=(dataclasses.replace(v, pages=(p,)), *full.personas.views[1:])))
    with pytest.raises(ValueError, match="rich-text-content"):
        compile_spec(bad)


def test_check_on_click_dangling_target_popup_raises() -> None:
    """An OpenPopup naming a popup that doesn't exist on the page — a build that would open nothing."""
    full = _full_spec()
    v = full.personas.views[0]
    p = dataclasses.replace(v.pages[0],
                            on_click=(OnClickAction("reassign job", ClickActionKind.OPEN_POPUP,
                                                    target_popup="No Such Popup"),))
    bad = dataclasses.replace(
        full, personas=Personas(views=(dataclasses.replace(v, pages=(p,)), *full.personas.views[1:])))
    with pytest.raises(ValueError, match="No Such Popup"):
        compile_spec(bad)


def test_check_on_click_both_arms_set_raises() -> None:
    """The exactly-one-arm contract #39 deferred to T2: OpenPopup carrying a script too is refused."""
    full = _full_spec()
    v = full.personas.views[0]
    p = dataclasses.replace(
        v.pages[0],
        popups=(PopupIntent("Job Detail", (WidgetIntent("general/label"),)),),
        on_click=(OnClickAction("reassign job", ClickActionKind.OPEN_POPUP,
                                target_popup="Job Detail", script="kf.x()"),))
    bad = dataclasses.replace(
        full, personas=Personas(views=(dataclasses.replace(v, pages=(p,)), *full.personas.views[1:])))
    with pytest.raises(ValueError, match="exactly one arm"):
        compile_spec(bad)


def test_check_on_click_unknown_action_raises() -> None:
    """`action` must name one the owning role actually declares (#39 gap (c))."""
    full = _full_spec()
    v = full.personas.views[0]
    p = dataclasses.replace(v.pages[0],
                            on_click=(OnClickAction("ghost action", ClickActionKind.JS_ACTION,
                                                    script="kf.x()"),))
    bad = dataclasses.replace(
        full, personas=Personas(views=(dataclasses.replace(v, pages=(p,)), *full.personas.views[1:])))
    with pytest.raises(ValueError, match="ghost action"):
        compile_spec(bad)


# ---- F15: the loop-gate-type message shows the plain wire value, not the raw enum repr ---------

def test_loop_gate_wrong_type_message_shows_plain_value_not_enum_repr() -> None:
    bad = dataclasses.replace(_full_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Quality Check", to_stage="Repair", gate_field="Repair Cost",
                 max_rounds=3),
    )))
    with pytest.raises(ValueError) as exc_info:
        compile_spec(bad)
    message = str(exc_info.value)
    assert "Number" in message
    assert "FieldType." not in message  # no raw "<FieldType.NUMBER: 'Number'>" leaking through


# ---- F16 (required half): table column types/required and section description are now asked ---

def test_q6_has_dedicated_table_column_and_section_description_questions() -> None:
    ids = {q.id for q in QUESTIONS[6]}
    assert "6c" in ids  # table column types + required
    assert "6d" in ids  # section description
    q6c = next(q for q in QUESTIONS[6] if q.id == "6c")
    for t in FieldType:
        assert t.value in q6c.why


# ---- m15: mapping-shaped fields are tuples of pairs, not mutable dicts ------------------------

def test_mapping_shaped_fields_are_tuples_not_dicts() -> None:
    full = _full_spec()
    assert isinstance(full.routing.points[0].route_per_option, tuple)
    assert isinstance(full.test_cases.cases[0].fills[0].values, tuple)
    widget_with_config = next(
        w for view in full.personas.views for page in view.pages for w in page.widgets if w.config
    )
    assert isinstance(widget_with_config.config, tuple)


# ---- m17: the field-unknown-stage guard is a real, tested cross-check -------------------------

def test_check_field_unknown_stage_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        dataclasses.replace(f, stage="Nonexistent Stage") if f.name == "Unit Name" else f
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="Nonexistent Stage"):
        compile_spec(bad)


def test_check_field_non_fieldtype_raises() -> None:
    full = _full_spec()
    bad_fields = tuple(
        dataclasses.replace(f, type="Text") if f.name == "Unit Name" else f  # type: ignore[arg-type]
        for f in full.data_model.fields
    )
    bad = _replace_data_model(full, fields=bad_fields)
    with pytest.raises(ValueError, match="FieldType enum member"):
        compile_spec(bad)


# ---- m18: a raw-string permission raises ValueError naming the offender, not AttributeError ---

def test_check_visibility_non_enum_permission_raises_named_valueerror() -> None:
    full = _full_spec()
    bad_entry = VisibilityEntry(section="Intake", stage="Intake",
                                permission="Editable")  # type: ignore[arg-type]
    bad = dataclasses.replace(full, visibility=VisibilityMatrix(entries=(bad_entry,)))
    with pytest.raises(ValueError) as exc_info:
        compile_spec(bad)
    message = str(exc_info.value)
    assert "Intake" in message
    assert "Visibility enum member" in message


# ---- m19: per-type field options; legal FieldType list surfaced in the question ----------------

def test_field_options_thread_into_apply_fields() -> None:
    plan = compile_spec(_full_spec())
    diagnose_op = next(op for op in plan.ops
                       if op.kind == "apply_fields" and op.args["stage"] == "Diagnose")
    notes = next(f for f in diagnose_op.args["fields"] if f["name"] == "Diagnosis Notes")
    assert notes["options"] == {"AllowFormatting": "true"}


# ---- m20: parallel branches are documented as explicitly out of scope -------------------------

def test_parallel_branches_documented_as_out_of_scope() -> None:
    import kfforge.intake.schema as schema_module
    doc = (schema_module.__doc__ or "").lower()
    assert "parallel" in doc
    assert "out of scope" in doc


# ---- m21: question priority order — covered above by test_next_questions_priority_order_and_
#      default_limit / test_next_questions_respects_a_larger_limit (order 1,2,3,6,7,4,5,8,11,10,9)


# ---- compile_spec: proven order, full dimension coverage, summary reconciliation -------------

def test_compiles_to_every_op_kind_in_proven_order() -> None:
    plan = compile_spec(_full_spec())
    assert isinstance(plan, BuildPlan)

    kinds = [op.kind for op in plan.ops]
    # every canonical kind appears at least once — the fixture was built to exercise all 11
    # dimensions, so every op kind the proven build order names should show up
    assert set(kinds) == set(OP_ORDER)

    # and strictly in OP_ORDER: every op of an earlier kind precedes every op of a later kind
    seen_kind_positions = [OP_ORDER.index(k) for k in kinds]
    assert seen_kind_positions == sorted(seen_kind_positions)

    for op in plan.ops:
        assert isinstance(op, Op)
        assert op.kind in OP_ORDER
        assert isinstance(op.args, dict)
        assert op.why  # never a blank rationale


def test_op_counts_match_the_fixture_exactly() -> None:
    """Pinned expected counts, derived by hand from `_full_spec()`'s own content — a change to
    either the fixture or the op-derivation logic that breaks this pairing should fail loudly
    here rather than only via a vaguer 'set of kinds' check."""
    plan = compile_spec(_full_spec())
    assert plan.summary() == {
        "create_process": 1,
        "member_batch": 3,       # one per role
        "create_list": 2,        # Urgency Levels, Yes No
        "apply_fields": 4,       # Intake, Diagnose, Repair, Quality Check have fields; Return to
                                 # Customer has none, so it gets no apply_fields op
        "add_table": 1,          # Parts Used
        "build_workflow": 1,     # one ProcessDef for the whole stage sequence
        "set_assignees": 5,      # one per stage
        "add_goto_gate": 1,      # Quality Check -> Repair
        "set_branch_conditions": 1,  # Diagnose's one split, Yes/No
        "set_visibility": 1,     # the whole matrix in one op
        "set_events": 1,         # Total Parts Cost
        "set_styles": 5,         # one per stage
        "publish": 1,
        "doctor": 1,
        "create_page": 2,        # Manager Dashboard, My Jobs — deduplicated across 2 roles
        "build_page": 2,
        "set_navigation": 3,     # (Service Manager, Manager Dashboard), (Technician, My Jobs),
                                 # (Front Desk, Manager Dashboard)
        "simulate_case": 3,
    }
    assert len(plan.ops) == 38


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
    """CLAUDE.md Write path: a style token may never be synthesized — set_styles ops must name
    only the stage, not invent a color/token value."""
    plan = compile_spec(_full_spec())
    style_ops = [op for op in plan.ops if op.kind == "set_styles"]
    assert len(style_ops) == 5
    for op in style_ops:
        assert set(op.args.keys()) == {"stage"}


def test_create_and_build_page_ops_are_deduplicated_by_page_name() -> None:
    plan = compile_spec(_full_spec())
    create_names = sorted(op.args["name"] for op in plan.ops if op.kind == "create_page")
    build_names = sorted(op.args["name"] for op in plan.ops if op.kind == "build_page")
    assert create_names == ["Manager Dashboard", "My Jobs"]
    assert build_names == ["Manager Dashboard", "My Jobs"]


def test_set_navigation_binds_the_shared_page_to_both_its_roles() -> None:
    plan = compile_spec(_full_spec())
    nav_pairs = sorted(
        (op.args["role"], op.args["page"]) for op in plan.ops if op.kind == "set_navigation"
    )
    assert nav_pairs == [
        ("Front Desk", "Manager Dashboard"),
        ("Service Manager", "Manager Dashboard"),
        ("Technician", "My Jobs"),
    ]


# ---- #6: role-scoped visibility is a claim the doctor refuses, not compile ----------------------

class TestRoleScopedVisibilityClaim:
    @staticmethod
    def _spec_with_role_claim() -> AppSpec:
        full = _full_spec()
        vm = full.visibility
        claimed = dataclasses.replace(vm.entries[3], role="Front Desk")
        new_vm = dataclasses.replace(
            vm, entries=vm.entries[:3] + (claimed,) + vm.entries[4:])
        return dataclasses.replace(full, visibility=new_vm)

    def test_compile_does_not_refuse_a_role_claim(self) -> None:
        """AC4 (B2) held: the refusal is the DOCTOR's gate, not compile's — compile still emits a
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
