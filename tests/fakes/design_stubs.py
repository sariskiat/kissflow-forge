"""Shared stub specs and XML/HTML assertion helpers for the design-family tests.

Moved verbatim from `tests/test_design.py` (Stage D group 8), which tested the old
`app.application.design` package. The stubs are plain frozen dataclasses that mirror
`AppSpec`'s real attribute names and nesting WITHOUT importing it -- the design
modules (`app.application.use_cases.design._diagram`, `_mockup`, `_confirm`) promise
only to work against the structural protocol in `_bundle.py`, and these stubs prove
that promise. `bare_shape_spec()` proves the other half: a bare sequence works in
place of any dimension wrapper.

Domain is deliberately neutral (a small equipment-repair intake flow) -- no real app
names, ids or vocabulary anywhere in this file, per repo policy.
"""

from __future__ import annotations

import dataclasses
import html.parser
import xml.etree.ElementTree as ET
from typing import Any

# --------------------------------------------------------------------------------------
# Stub domain objects -- plain frozen dataclasses, mirroring
# app.application.intake.schema's real attribute names/nesting (see this file's own
# module docstring for why). Never imported by src/app/design/*.py; that would defeat
# the point.
# --------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Stage:
    name: str
    owner_role: str
    what_happens: str


@dataclasses.dataclass(frozen=True)
class Stages:
    stages: tuple[Stage, ...]


@dataclasses.dataclass(frozen=True)
class RoutingPoint:
    at_stage: str
    field_name: str
    options: tuple[str, ...]
    route_per_option: tuple[
        tuple[str, tuple[str, ...]], ...
    ]  # (option, stage-sequence) pairs


@dataclasses.dataclass(frozen=True)
class Routing:
    points: tuple[RoutingPoint, ...]
    confirmed_none: bool = False


@dataclasses.dataclass(frozen=True)
class Loop:
    from_stage: str
    to_stage: str
    gate_field: str


@dataclasses.dataclass(frozen=True)
class ReworkLoops:
    loops: tuple[Loop, ...]
    confirmed_none: bool = False


@dataclasses.dataclass(frozen=True)
class SectionReq:
    name: str
    stage: str
    description: str


@dataclasses.dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool
    stage: str
    list_name: str | None = None
    section: str | None = None


@dataclasses.dataclass(frozen=True)
class TableColumn:
    name: str
    type: str
    required: bool


@dataclasses.dataclass(frozen=True)
class Table:
    name: str
    stage: str
    columns: tuple[TableColumn, ...]
    max_rows: int | None = None


@dataclasses.dataclass(frozen=True)
class ComputedReq:
    target_field: str
    source_fields: tuple[str, ...]
    formula_intent: str


@dataclasses.dataclass(frozen=True)
class SequenceReq:
    prefix: str
    padding: str


@dataclasses.dataclass(frozen=True)
class DataModel:
    fields: tuple[Field, ...]
    tables: tuple[Table, ...]
    computed: tuple[ComputedReq, ...] = ()
    sections: tuple[SectionReq, ...] = ()
    sequence: SequenceReq | None = None


@dataclasses.dataclass(frozen=True)
class ListSpec:
    name: str
    values: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class MasterData:
    lists: tuple[ListSpec, ...]


@dataclasses.dataclass(frozen=True)
class VisibilityEntry:
    section: str
    stage: str
    permission: str
    field: str | None = None


@dataclasses.dataclass(frozen=True)
class VisibilityMatrix:
    entries: tuple[VisibilityEntry, ...]


@dataclasses.dataclass(frozen=True)
class Page:
    name: str
    widgets: tuple[Any, ...]


@dataclasses.dataclass(frozen=True)
class PersonaView:
    role: str
    pages: tuple[Page, ...]
    kpis: tuple[str, ...]
    actions: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Personas:
    views: tuple[PersonaView, ...]


@dataclasses.dataclass(frozen=True)
class StepFill:
    stage: str
    values: tuple[tuple[str, str], ...]


@dataclasses.dataclass(frozen=True)
class CaseWalk:
    # tell pytest this is dimension 11's container, not a test class to collect
    __test__ = False
    name: str
    fills: tuple[StepFill, ...]
    expected_path: tuple[str, ...]
    expected_result: str


@dataclasses.dataclass(frozen=True)
class TestCases:
    # tell pytest this is dimension 11's container, not a test class to collect
    __test__ = False
    cases: tuple[CaseWalk, ...]


@dataclasses.dataclass(frozen=True)
class ProblemGoal:
    pain: str
    goal: str
    done_definition: str
    terminal_states: tuple[str, ...]
    result_values: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class AppSpec:
    app_name: str
    problem_goal: ProblemGoal
    stages: Stages
    routing: Routing
    rework_loops: ReworkLoops
    data_model: DataModel
    master_data: MasterData
    visibility: VisibilityMatrix
    personas: Personas
    test_cases: TestCases = dataclasses.field(
        default_factory=lambda: TestCases(cases=())
    )


def _empty_problem_goal() -> ProblemGoal:
    return ProblemGoal(
        pain="", goal="", done_definition="", terminal_states=(), result_values=()
    )


def sample_spec() -> AppSpec:
    """
    A small, complete equipment-repair intake flow exercising every protocol
    feature, including every shape a first review round caught this package
    mishandling or omitting: a required field on an OFF-SPINE routing terminal, a
    Select field with a real backing list, a Hidden field-level visibility entry, a
    ReadOnly field-level entry, a computed field, two explicit sections on one
    stage, a sequence-number scheme, and one real end-to-end test case (used by the
    M10/M11 revision-cascade tests below). Table-level visibility (major 3's
    "banner+table pattern") is exercised on a spec DERIVED from this one (see
    TestVisibilityAwareRendering.test_table_level_hidden_entry_hides_the_whole_table),
    so the "no cap" rendering test and the "table hidden" rendering test don't
    interact.
    """
    stages = Stages(
        stages=(
            Stage(
                "Intake",
                "Front Desk",
                "Customer drops off the equipment and describes the issue.",
            ),
            Stage(
                "Diagnosis",
                "Technician",
                "Technician inspects the equipment and records findings.",
            ),
            Stage(
                "Repair",
                "Technician",
                "Technician repairs the equipment and logs parts used.",
            ),
            Stage(
                "Quality Check",
                "QA Lead",
                "QA lead verifies the repair before releasing it.",
            ),
        )
    )
    routing = Routing(
        points=(
            RoutingPoint(
                at_stage="Diagnosis",
                field_name="Diagnosis Result",
                options=("Repairable", "Needs Parts", "Beyond Repair"),
                route_per_option=(
                    ("Repairable", ("Repair",)),
                    ("Needs Parts", ("Repair",)),
                    ("Beyond Repair", ("Closed - Rejected",)),
                ),
            ),
        )
    )
    rework_loops = ReworkLoops(
        loops=(
            Loop(
                from_stage="Quality Check",
                to_stage="Repair",
                gate_field="Rework Needed",
            ),
        )
    )
    data_model = DataModel(
        fields=(
            Field("Customer Name", "Text", True, "Intake", section="Customer Info"),
            Field(
                "Equipment Type",
                "Select",
                True,
                "Intake",
                list_name="Equipment Type",
                section="Customer Info",
            ),
            Field(
                "Issue Description", "Textarea", True, "Intake", section="Issue Details"
            ),
            # Hidden at its own stage via a FIELD-LEVEL VisibilityEntry below -- blocker
            # 1's own example (a Date field named "Due Date" that must not render as a
            # live input here).
            Field("Due Date", "Date", False, "Intake", section="Issue Details"),
            Field(
                "Diagnosis Result",
                "Select",
                True,
                "Diagnosis",
                list_name="Diagnosis Result Options",
            ),
            # ReadOnly at its own stage via a FIELD-LEVEL VisibilityEntry below.
            Field("Repair Notes", "Textarea", False, "Repair", section="Repair Work"),
            # A COMPUTED target (see `computed=` below) -- must render as
            # auto-calculated, never as a live input the user types into (blocker 2).
            Field("Estimated Cost", "Number", False, "Repair", section="Repair Work"),
            Field("Rework Needed", "Boolean", False, "Quality Check"),
            # Off-spine: "Closed - Rejected" is a routing TARGET, never a member of
            # stages.stages.
            Field("Rejection Reason", "Textarea", True, "Closed - Rejected"),
        ),
        tables=(
            Table(
                "Parts Used",
                "Repair",
                (
                    TableColumn("Part Name", "Text", True),
                    TableColumn("Quantity", "Number", True),
                    TableColumn("Unit Cost", "Number", False),
                ),
                10,
            ),
            # No max_rows set (renders "no cap") -- NOT hidden by default; the
            # table-level-hidden scenario (major 3's "banner+table pattern": a table is
            # ALSO a legal visibility- matrix section) is exercised separately, on a
            # spec derived from this one, so the two concerns (no-cap rendering,
            # hidden-table rendering) don't interact.
            Table(
                "Attachments Log",
                "Quality Check",
                (TableColumn("File Name", "Text", False),),
                None,
            ),
        ),
        computed=(
            ComputedReq(
                target_field="Estimated Cost",
                source_fields=("Diagnosis Result",),
                formula_intent=(
                    "Estimate repair cost from the diagnosis result and "
                    "typical parts pricing."
                ),
            ),
        ),
        sections=(
            SectionReq("Customer Info", "Intake", "Who the equipment belongs to."),
            SectionReq("Issue Details", "Intake", "What is wrong with it."),
            SectionReq("Repair Work", "Repair", "What was actually done to fix it."),
        ),
        sequence=SequenceReq(prefix="RPR", padding="0001"),
    )
    master_data = MasterData(
        lists=(
            ListSpec("Equipment Type", ("Laptop", "Printer", "Router", "Other")),
            ListSpec(
                "Diagnosis Result Options",
                ("Repairable", "Needs Parts", "Beyond Repair"),
            ),
        )
    )
    visibility = VisibilityMatrix(
        entries=(
            VisibilityEntry("Customer Info", "Intake", "Editable"),
            VisibilityEntry("Issue Details", "Intake", "Editable"),
            VisibilityEntry("Issue Details", "Intake", "Hidden", field="Due Date"),
            VisibilityEntry("Diagnosis", "Diagnosis", "Editable"),
            VisibilityEntry("Repair Work", "Repair", "Editable"),
            VisibilityEntry("Repair Work", "Repair", "ReadOnly", field="Repair Notes"),
            VisibilityEntry("Quality Check", "Quality Check", "Editable"),
        )
    )
    personas = Personas(
        views=(
            PersonaView(
                role="Front Desk",
                pages=(Page("My Intakes", ("view/table",)),),
                kpis=("Open Tickets", "Closed Today"),
                actions=("New Intake",),
            ),
            PersonaView(
                role="Technician",
                pages=(Page("My Repairs", ("view/kanban",)),),
                kpis=("In Progress", "Awaiting Parts"),
                actions=("Start Diagnosis", "Mark Repaired"),
            ),
        )
    )
    test_cases = TestCases(
        cases=(
            CaseWalk(
                name="happy path",
                fills=(
                    StepFill(
                        "Intake",
                        (
                            ("Customer Name", "Jane Doe"),
                            ("Equipment Type", "Laptop"),
                            ("Issue Description", "Won't turn on"),
                        ),
                    ),
                    StepFill("Diagnosis", (("Diagnosis Result", "Repairable"),)),
                    StepFill("Repair", (("Repair Notes", "Replaced battery"),)),
                    StepFill("Quality Check", (("Rework Needed", "false"),)),
                ),
                expected_path=("Intake", "Diagnosis", "Repair", "Quality Check"),
                expected_result="Repaired",
            ),
        )
    )
    return AppSpec(
        app_name="Equipment Repair Intake",
        problem_goal=ProblemGoal(
            pain="Repair tickets get lost between front desk and the bench.",
            goal="Track every repair from intake to release.",
            done_definition=(
                "Item is repaired or the customer is told it cannot be, "
                "either way logged."
            ),
            terminal_states=("Quality Check", "Closed - Rejected"),
            result_values=("Repaired", "Beyond repair"),
        ),
        stages=stages,
        routing=routing,
        rework_loops=rework_loops,
        data_model=data_model,
        master_data=master_data,
        visibility=visibility,
        personas=personas,
        test_cases=test_cases,
    )


def bare_shape_spec() -> AppSpec:
    """
    Same content as sample_spec, but the 5 dimensions app.application.intake wraps
    (stages/routing/ rework_loops/visibility/test_cases) are handed over as BARE
    tuples instead -- proving `_seq()` accepts this package's own minimal protocol
    shape too, not only intake's real wrapper shape.
    """
    base = sample_spec()
    return dataclasses.replace(
        base,
        stages=base.stages.stages,
        routing=base.routing.points,
        rework_loops=base.rework_loops.loops,
        visibility=base.visibility.entries,
        test_cases=base.test_cases.cases,
    )


def spec_with_orphan_stage() -> AppSpec:
    """
    A routing point at "A" whose every option targets "C" directly -- "B" is a spine
    stage that receives NO edge at all (the implicit A->B edge is suppressed because
    A branches, and nothing routes to B either). Proves an orphan is flagged, never
    fabricated a way in (major 6).
    """
    stages = Stages(
        stages=(
            Stage("A", "Role A", "Starts here."),
            Stage("B", "Role B", "Never actually reached by this routing."),
            Stage("C", "Role C", "Ends here."),
        )
    )
    routing = Routing(
        points=(
            RoutingPoint(
                at_stage="A",
                field_name="Choice",
                options=("X", "Y"),
                route_per_option=(("X", ("C",)), ("Y", ("C",))),
            ),
        )
    )
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Orphan Test",
        problem_goal=_empty_problem_goal(),
        stages=stages,
        routing=routing,
        rework_loops=ReworkLoops(loops=()),
        data_model=empty_dm,
        master_data=empty_md,
        visibility=VisibilityMatrix(entries=()),
        personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_two_routing_points_same_stage() -> AppSpec:
    """
    Two DIFFERENT routing points both at_stage="Middle", with genuinely DISJOINT
    option sets ("A"/"B" vs "C"/"D") -- proves they render at DIFFERENT coordinates
    instead of stacking invisibly on top of each other (major 5), AND is the fixture
    m10 (round 2) demands: apply_revisions on a routing key at a shared stage must
    revise only the ONE decision point that actually has the named option, never
    raise just because a SIBLING doesn't (M9).
    """
    stages = Stages(
        stages=(
            Stage("Start", "Role", "..."),
            Stage("Middle", "Role", "..."),
            Stage("End", "Role", "..."),
        )
    )
    routing = Routing(
        points=(
            RoutingPoint(
                at_stage="Middle",
                field_name="First Choice",
                options=("A", "B"),
                route_per_option=(("A", ("End",)), ("B", ("End",))),
            ),
            RoutingPoint(
                at_stage="Middle",
                field_name="Second Choice",
                options=("C", "D"),
                route_per_option=(("C", ("End",)), ("D", ("Start",))),
            ),
        )
    )
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Two Routing Points Test",
        problem_goal=_empty_problem_goal(),
        stages=stages,
        routing=routing,
        rework_loops=ReworkLoops(loops=()),
        data_model=empty_dm,
        master_data=empty_md,
        visibility=VisibilityMatrix(entries=()),
        personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_tiered_branches() -> AppSpec:
    """
    The round-1 defect (major, decision_01 item 1): three service tiers that must
    each run to a SHARED merge, not spill forward into a sibling branch's stages. A
    strict sequence whose one fork at "Triage" fans into three on-spine branch
    entries [Self Service, Light Work, Full Tier]; the light and full branches are
    multi-step and each carry a backward rework loop whose `from_stage` marks the
    branch's terminal. The merge is "Summary": every branch feeds it directly
    (in-degree 3), and no branch draws a spine edge into a sibling branch.
    Neutral-domain mirror of a 'choose a service level, walk it to the merge' shape.
    """
    stages = Stages(
        stages=(
            Stage("Intake", "Requester", "Open the issue."),
            Stage("Prepare", "Requester", "Gather details."),
            Stage("Triage", "Lead", "Pick a service tier."),
            Stage("Self Service", "Analyst", "Requester tries it alone."),
            Stage("Light Work", "Analyst", "Do one light round."),
            Stage("Light Confirm", "Analyst", "Confirm the light round."),
            Stage("Full Tier", "Analyst", "Full tier entry."),
            Stage("Full Work", "Analyst", "Do one full round."),
            Stage("Full Confirm", "Analyst", "Confirm the full round."),
            Stage("Summary", "Analyst", "Summarise with the requester."),
            Stage("Lead Closure", "Lead", "Review and close."),
        )
    )
    routing = Routing(
        points=(
            RoutingPoint(
                at_stage="Triage",
                field_name="Service Tier",
                options=("Self", "Light", "Full"),
                route_per_option=(
                    ("Self", ("Self Service",)),
                    ("Light", ("Light Work",)),
                    ("Full", ("Full Tier",)),
                ),
            ),
        )
    )
    rework_loops = ReworkLoops(
        loops=(
            Loop(
                from_stage="Light Confirm",
                to_stage="Light Work",
                gate_field="Round Done",
            ),
            Loop(
                from_stage="Full Confirm", to_stage="Full Work", gate_field="Round Done"
            ),
        )
    )
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Tiered Service",
        problem_goal=_empty_problem_goal(),
        stages=stages,
        routing=routing,
        rework_loops=rework_loops,
        data_model=empty_dm,
        master_data=empty_md,
        visibility=VisibilityMatrix(entries=()),
        personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_branch_local_loop() -> AppSpec:
    """
    S3 (#34) AC4: a split ("Triage") whose "Complex" branch is a multi-stage
    SEQUENCE [Deep Review, Fix, Verify] carrying a rework loop BETWEEN two of its
    OWN stages (Verify -> Fix). Both loop endpoints are branch stages, so the dashed
    backward edge is drawn inside the branch, not across the spine -- the shape the
    Confirmation diagram must render truthfully.
    """
    stages = Stages(
        stages=(
            Stage("Log", "Intake", "Log the claim."),
            Stage("Triage", "Adjuster", "Pick the path."),
            Stage("Quick Close", "Adjuster", "Close a simple claim."),
            Stage("Deep Review", "Adjuster", "Review a complex claim."),
            Stage("Fix", "Adjuster", "Correct the claim."),
            Stage("Verify", "Adjuster", "Verify the correction."),
            Stage("Close", "Intake", "Close the claim."),
        )
    )
    routing = Routing(
        points=(
            RoutingPoint(
                at_stage="Triage",
                field_name="Path",
                options=("Simple", "Complex"),
                route_per_option=(
                    ("Simple", ("Quick Close",)),
                    ("Complex", ("Deep Review", "Fix", "Verify")),
                ),
            ),
        )
    )
    rework_loops = ReworkLoops(
        loops=(Loop(from_stage="Verify", to_stage="Fix", gate_field="Fix Approved"),)
    )
    empty_dm = DataModel(fields=(), tables=())
    return AppSpec(
        app_name="Branch Local Loop",
        problem_goal=_empty_problem_goal(),
        stages=stages,
        routing=routing,
        rework_loops=rework_loops,
        data_model=empty_dm,
        master_data=MasterData(lists=()),
        visibility=VisibilityMatrix(entries=()),
        personas=Personas(views=()),
        test_cases=TestCases(cases=()),
    )


def spec_with_multistage_branches() -> AppSpec:
    """
    S1 (#32): a split ("Route") whose two branches are ORDERED STAGE SEQUENCES of
    different lengths -- branch A = [A1, A2] (2 stages), branch B = [B1] (1 stage)
    -- merging at "Wrap". Pins the fix for the live-verified bug:
    `_forward_next_stages` used to treat every branch as a single entry stage and
    let interior branch stages fall through to the next SPINE stage, so A1 -> Wrap
    (skipping A2) and A2 -> B1 (spilling into the sibling branch) instead of the
    truthful A1 -> A2 -> Wrap and B1 -> Wrap. Branch B stays length-1 specifically
    so this fixture also proves the existing length-1 model (spine-extension via
    `route_seq[0]` at the fork, terminal-by-loop-override elsewhere) is untouched by
    the new multi-stage handling.
    """
    stages = Stages(
        stages=(
            Stage("Intake", "Requester", "Open the request."),
            Stage("Route", "Lead", "Pick a path."),
            Stage("A1", "Analyst", "First step of branch A."),
            Stage("A2", "Analyst", "Second step of branch A."),
            Stage("B1", "Analyst", "Only step of branch B."),
            Stage("Wrap", "Lead", "Close out, both branches land here."),
        )
    )
    routing = Routing(
        points=(
            RoutingPoint(
                at_stage="Route",
                field_name="Choice",
                options=("A", "B"),
                route_per_option=(("A", ("A1", "A2")), ("B", ("B1",))),
            ),
        )
    )
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Multistage Branch Test",
        problem_goal=_empty_problem_goal(),
        stages=stages,
        routing=routing,
        rework_loops=ReworkLoops(loops=()),
        data_model=empty_dm,
        master_data=empty_md,
        visibility=VisibilityMatrix(entries=()),
        personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_sequential_splits() -> AppSpec:
    """
    S2 (#33): TWO sequential splits -- StemA -> [A1, A2] -> StemB (split A's own
    rejoin, and also split B's own stem) -> [B1] -> End (split B's own rejoin). Pins
    the fix for the live- verified cross-split defect: `_forward_next_stages` used
    to compute a SINGLE GLOBAL merge (the first stage after the DEEPEST terminal
    across every routing point), so split A's branch terminal (A2) pointed at split
    B's merge (End) instead of split A's own rejoin (StemB) -- spilling split A's
    branch across split B's diamond and branch entirely, exactly the kind of
    untruthful edge ADR-0001 rules out. Each split here carries a single option so
    the fixture isolates the cross-split bug from S1's already-covered within-split
    sibling spill.
    """
    stages = Stages(
        stages=(
            Stage("Intake", "Requester", "Open the request."),
            Stage("StemA", "Lead", "First fork."),
            Stage("A1", "Analyst", "First step of branch A."),
            Stage("A2", "Analyst", "Second step of branch A."),
            Stage("StemB", "Lead", "Second fork -- also split A's own rejoin."),
            Stage("B1", "Analyst", "Only step of branch B."),
            Stage("End", "Lead", "Close out -- split B's own rejoin."),
        )
    )
    routing = Routing(
        points=(
            RoutingPoint(
                at_stage="StemA",
                field_name="Choice A",
                options=("Go",),
                route_per_option=(("Go", ("A1", "A2")),),
            ),
            RoutingPoint(
                at_stage="StemB",
                field_name="Choice B",
                options=("Go",),
                route_per_option=(("Go", ("B1",)),),
            ),
        )
    )
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Sequential Splits Test",
        problem_goal=_empty_problem_goal(),
        stages=stages,
        routing=routing,
        rework_loops=ReworkLoops(loops=()),
        data_model=empty_dm,
        master_data=empty_md,
        visibility=VisibilityMatrix(entries=()),
        personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_forward_loop() -> AppSpec:
    """
    A "loop" whose to_stage comes AFTER its from_stage in the spine -- not a genuine
    rework loop by app.application.intake.schema.LoopSpec's own contract. Proves
    this package says so rather than asserting "loops back" for something that does
    not (minor 10).
    """
    stages = Stages(
        stages=(
            Stage("A", "Role", "..."),
            Stage("B", "Role", "..."),
            Stage("C", "Role", "..."),
        )
    )
    rework_loops = ReworkLoops(
        loops=(Loop(from_stage="A", to_stage="C", gate_field="Weird Gate"),)
    )
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Forward Loop Test",
        problem_goal=_empty_problem_goal(),
        stages=stages,
        routing=Routing(points=()),
        rework_loops=rework_loops,
        data_model=empty_dm,
        master_data=empty_md,
        visibility=VisibilityMatrix(entries=()),
        personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_tricky_text() -> AppSpec:
    """
    Same shape as sample_spec but one stage's name/owner carry XML/HTML-hostile
    characters plus Thai text, to pin the escaping contract end to end.
    """
    base = sample_spec()
    tricky = dataclasses.replace(
        base.stages.stages[0],
        name='Intake & "Return" <Urgent> รับเครื่องซ่อม',
        owner_role="หน้าเคาน์เตอร์ & Support",
    )
    new_stages = (tricky,) + base.stages.stages[1:]
    new_fields = tuple(
        dataclasses.replace(f, stage=tricky.name) if f.stage == "Intake" else f
        for f in base.data_model.fields
    )
    return dataclasses.replace(
        base,
        stages=Stages(stages=new_stages),
        data_model=dataclasses.replace(base.data_model, fields=new_fields),
    )


# --------------------------------------------------------------------------------------
# Shared XML/HTML validity helpers
# --------------------------------------------------------------------------------------


def _child(el: ET.Element, tag: str) -> ET.Element:
    """
    `Element.find` is Optional-typed. Every use below requires the child, so say so
    here once instead of asserting (or not asserting) at each of a dozen call sites.
    """
    got = el.find(tag)
    assert got is not None, f"<{el.tag} id={el.get('id')!r}> has no <{tag}> child"
    return got


def _attr(el: ET.Element, name: str) -> str:
    """Same for `Element.get`, which returns `str | None`."""
    got = el.get(name)
    assert got is not None, f"<{el.tag} id={el.get('id')!r}> has no {name!r} attribute"
    return got


def _assert_valid_mxgraph(xml_str: str) -> ET.Element:
    root = ET.fromstring(xml_str)  # raises ET.ParseError if not well-formed XML
    cells = root.findall(".//mxCell")
    ids = [c.get("id") for c in cells]
    assert len(ids) == len(set(ids)), "duplicate mxCell ids"
    id_set = set(ids)
    for c in cells:
        if c.get("edge") == "1":
            assert c.get("source") in id_set, (
                f"edge {c.get('id')} source does not resolve"
            )
            assert c.get("target") in id_set, (
                f"edge {c.get('id')} target does not resolve"
            )
    return root


_VOID_ELEMENTS = {
    "input",
    "meta",
    "link",
    "br",
    "img",
    "hr",
    "source",
    "col",
    "area",
    "base",
    "embed",
    "track",
    "wbr",
}


class _BalanceCheckingParser(html.parser.HTMLParser):
    """
    A minimal well-formedness check: every non-void start tag has a matching end
    tag, in order, and the stack is empty at EOF. Not a full HTML5 validator (not
    needed here) -- just enough to catch a stray unclosed div/section/table, which
    is the class of bug this kind of hand-built string templating actually produces.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass  # explicit self-closing (<tag/>) -- never unbalanced by construction

    def handle_endtag(self, tag):
        if tag in _VOID_ELEMENTS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"mismatched close for </{tag}>, stack={self.stack}")
            return
        self.stack.pop()


def _assert_well_formed_html(doc: str) -> None:
    parser = _BalanceCheckingParser()
    parser.feed(doc)
    parser.close()
    assert not parser.errors, parser.errors
    assert not parser.stack, f"unclosed tags: {parser.stack}"
    assert "<!doctype html>" in doc.lower()


def _assert_no_external_refs(doc: str) -> None:
    """
    Minor 13: scan beyond bare http(s):// -- src=/href= attributes are the other
    place an external reference could sneak in (an image, a script, a stylesheet
    link), even one that happens not to spell out a scheme (e.g. a protocol-relative
    "//cdn...").
    """
    assert "http://" not in doc
    assert "https://" not in doc
    assert "src=" not in doc
    assert "href=" not in doc


def _marker_slice(doc: str, marker: str, boundary_prefixes: tuple[str, ...]) -> str:
    """
    Slice of `doc` from ONE marker comment up to the START of the next marker whose
    prefix is in `boundary_prefixes`, or the end of the document.
    """
    start = doc.index(marker)
    after = start + len(marker)
    candidates = [p for p in (doc.find(b, after) for b in boundary_prefixes) if p != -1]
    end = min(candidates) if candidates else len(doc)
    return doc[start:end]


def _card_slice(doc: str, stage_name: str) -> str:
    """
    A stage/off-spine card's own content, up to the next CARD-level marker (`<!--
    stage:` or `<!-- table:`) -- deliberately NOT bounded by `<!-- field:`, since
    one or more field markers legitimately nest INSIDE a card; using them as a
    boundary would truncate the card at its own first field.
    """
    return _marker_slice(
        doc, f"<!-- stage:{stage_name} -->", ("<!-- stage:", "<!-- table:")
    )


def _field_slice(doc: str, field_name: str) -> str:
    """
    One field row's own content, up to the next marker of ANY kind -- a field row is
    the smallest unit, so it is bounded by a sibling field, or the card/table that
    comes after it.
    """
    return _marker_slice(
        doc,
        f"<!-- field:{field_name} -->",
        ("<!-- field:", "<!-- stage:", "<!-- table:"),
    )
