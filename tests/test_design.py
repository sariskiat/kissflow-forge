"""Unit spec for kfforge.design: the confirm-before-you-build layer (diagrams, HTML mockups,
the approval protocol).

Everything here is a plain, hand-built stub -- NOT an import from kfforge.intake. That package is
a parallel, independently-authored node building the real `AppSpec` dataclasses; kfforge.design
only ever promises to work against the small structural protocol it defines in
kfforge/design/__init__.py (name/attribute shapes only, checked by nothing but normal attribute
access).

The stub shape below deliberately MIRRORS kfforge.intake.schema's real nesting: every dimension
kfforge.intake.schema wraps in its own container (`Stages.stages`, `Routing.points`,
`ReworkLoops.loops`, `TestCases.cases`, `VisibilityMatrix.entries`) is wrapped the same way here,
`kpis`/`actions` live on `PersonaView` (never on the page), and `AppSpec`'s rework-loop attribute
is named `rework_loops` (never `loops`) -- two review rounds proved these details load-bearing,
not decorative: a mismatch here is exactly what let kfforge.design ship code that raised against
a real AppSpec, and a shallow fixture (visibility/computed/sections all empty) is exactly what let
a first round of "faithfulness" bugs (a Hidden field rendering as a live input, a computed field
rendering as something the user types) through unnoticed. `bare_shape_spec()` separately proves
the OTHER half of the contract: this package's own minimal protocol also accepts a bare sequence
in place of any wrapper, via `kfforge.design.diagram._seq()`.

Domain is deliberately neutral (a small equipment-repair intake flow) -- no real app names/ids/
real-app vocabulary anywhere in this file, per repo policy.
"""
from __future__ import annotations

import dataclasses
import html.parser
import re
import xml.etree.ElementTree as ET

import pytest

from kfforge.design.confirm import (
    ConfirmationRequest,
    apply_revisions,
    is_approved,
    request_confirmation,
)
from kfforge.design.diagram import (
    _loop_direction,
    _stage_index,
    flow_diagram_xml,
    schema_diagram_xml,
)
from kfforge.design.mockup import (
    _format_sequence,
    design_bundle_html,
    form_mockups_html,
    persona_pages_html,
)

# --------------------------------------------------------------------------------------------
# Stub domain objects -- plain frozen dataclasses, mirroring kfforge.intake.schema's real
# attribute names/nesting (see this file's own module docstring for why). Never imported by
# kfforge/design/*.py; that would defeat the point.
# --------------------------------------------------------------------------------------------


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
    route_per_option: tuple[tuple[str, tuple[str, ...]], ...]  # (option, stage-sequence) pairs


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
    widgets: tuple[str, ...]


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
    __test__ = False  # tell pytest this is dimension 11's container, not a test class to collect
    name: str
    fills: tuple[StepFill, ...]
    expected_path: tuple[str, ...]
    expected_result: str


@dataclasses.dataclass(frozen=True)
class TestCases:
    __test__ = False  # tell pytest this is dimension 11's container, not a test class to collect
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
    test_cases: TestCases = dataclasses.field(default_factory=lambda: TestCases(cases=()))


def _empty_problem_goal() -> ProblemGoal:
    return ProblemGoal(pain="", goal="", done_definition="", terminal_states=(), result_values=())


def sample_spec() -> AppSpec:
    """A small, complete equipment-repair intake flow exercising every protocol feature,
    including every shape a first review round caught this package mishandling or omitting:
    a required field on an OFF-SPINE routing terminal, a Select field with a real backing list,
    a Hidden field-level visibility entry, a ReadOnly field-level entry, a computed field, two
    explicit sections on one stage, a sequence-number scheme, and one real end-to-end test case
    (used by the M10/M11 revision-cascade tests below). Table-level visibility (major 3's
    "banner+table pattern") is exercised on a spec DERIVED from this one (see
    TestVisibilityAwareRendering.test_table_level_hidden_entry_hides_the_whole_table), so the
    "no cap" rendering test and the "table hidden" rendering test don't interact.
    """
    stages = Stages(stages=(
        Stage("Intake", "Front Desk", "Customer drops off the equipment and describes the issue."),
        Stage("Diagnosis", "Technician", "Technician inspects the equipment and records findings."),
        Stage("Repair", "Technician", "Technician repairs the equipment and logs parts used."),
        Stage("Quality Check", "QA Lead", "QA lead verifies the repair before releasing it."),
    ))
    routing = Routing(points=(
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
    ))
    rework_loops = ReworkLoops(loops=(
        Loop(from_stage="Quality Check", to_stage="Repair", gate_field="Rework Needed"),
    ))
    data_model = DataModel(
        fields=(
            Field("Customer Name", "Text", True, "Intake", section="Customer Info"),
            Field("Equipment Type", "Select", True, "Intake", list_name="Equipment Type",
                  section="Customer Info"),
            Field("Issue Description", "Textarea", True, "Intake", section="Issue Details"),
            # Hidden at its own stage via a FIELD-LEVEL VisibilityEntry below -- blocker 1's own
            # example (a Date field named "Due Date" that must not render as a live input here).
            Field("Due Date", "Date", False, "Intake", section="Issue Details"),
            Field("Diagnosis Result", "Select", True, "Diagnosis", list_name="Diagnosis Result Options"),
            # ReadOnly at its own stage via a FIELD-LEVEL VisibilityEntry below.
            Field("Repair Notes", "Textarea", False, "Repair", section="Repair Work"),
            # A COMPUTED target (see `computed=` below) -- must render as auto-calculated, never
            # as a live input the user types into (blocker 2).
            Field("Estimated Cost", "Number", False, "Repair", section="Repair Work"),
            Field("Rework Needed", "Boolean", False, "Quality Check"),
            # Off-spine: "Closed - Rejected" is a routing TARGET, never a member of stages.stages.
            Field("Rejection Reason", "Textarea", True, "Closed - Rejected"),
        ),
        tables=(
            Table(
                "Parts Used", "Repair",
                (TableColumn("Part Name", "Text", True), TableColumn("Quantity", "Number", True),
                 TableColumn("Unit Cost", "Number", False)),
                10,
            ),
            # No max_rows set (renders "no cap") -- NOT hidden by default; the table-level-hidden
            # scenario (major 3's "banner+table pattern": a table is ALSO a legal visibility-
            # matrix section) is exercised separately, on a spec derived from this one, so the
            # two concerns (no-cap rendering, hidden-table rendering) don't interact.
            Table("Attachments Log", "Quality Check", (TableColumn("File Name", "Text", False),), None),
        ),
        computed=(
            ComputedReq(
                target_field="Estimated Cost", source_fields=("Diagnosis Result",),
                formula_intent="Estimate repair cost from the diagnosis result and typical parts pricing.",
            ),
        ),
        sections=(
            SectionReq("Customer Info", "Intake", "Who the equipment belongs to."),
            SectionReq("Issue Details", "Intake", "What is wrong with it."),
            SectionReq("Repair Work", "Repair", "What was actually done to fix it."),
        ),
        sequence=SequenceReq(prefix="RPR", padding="0001"),
    )
    master_data = MasterData(lists=(
        ListSpec("Equipment Type", ("Laptop", "Printer", "Router", "Other")),
        ListSpec("Diagnosis Result Options", ("Repairable", "Needs Parts", "Beyond Repair")),
    ))
    visibility = VisibilityMatrix(entries=(
        VisibilityEntry("Customer Info", "Intake", "Editable"),
        VisibilityEntry("Issue Details", "Intake", "Editable"),
        VisibilityEntry("Issue Details", "Intake", "Hidden", field="Due Date"),
        VisibilityEntry("Diagnosis", "Diagnosis", "Editable"),
        VisibilityEntry("Repair Work", "Repair", "Editable"),
        VisibilityEntry("Repair Work", "Repair", "ReadOnly", field="Repair Notes"),
        VisibilityEntry("Quality Check", "Quality Check", "Editable"),
    ))
    personas = Personas(views=(
        PersonaView(
            role="Front Desk",
            pages=(Page("My Intakes", ("view/table",)),),
            kpis=("Open Tickets", "Closed Today"), actions=("New Intake",),
        ),
        PersonaView(
            role="Technician",
            pages=(Page("My Repairs", ("view/kanban",)),),
            kpis=("In Progress", "Awaiting Parts"), actions=("Start Diagnosis", "Mark Repaired"),
        ),
    ))
    test_cases = TestCases(cases=(
        CaseWalk(
            name="happy path",
            fills=(
                StepFill("Intake", (("Customer Name", "Jane Doe"), ("Equipment Type", "Laptop"),
                                     ("Issue Description", "Won't turn on"))),
                StepFill("Diagnosis", (("Diagnosis Result", "Repairable"),)),
                StepFill("Repair", (("Repair Notes", "Replaced battery"),)),
                StepFill("Quality Check", (("Rework Needed", "false"),)),
            ),
            expected_path=("Intake", "Diagnosis", "Repair", "Quality Check"),
            expected_result="Repaired",
        ),
    ))
    return AppSpec(
        app_name="Equipment Repair Intake",
        problem_goal=ProblemGoal(
            pain="Repair tickets get lost between front desk and the bench.",
            goal="Track every repair from intake to release.",
            done_definition="Item is repaired or the customer is told it cannot be, either way logged.",
            terminal_states=("Quality Check", "Closed - Rejected"),
            result_values=("Repaired", "Beyond repair"),
        ),
        stages=stages, routing=routing, rework_loops=rework_loops,
        data_model=data_model, master_data=master_data, visibility=visibility, personas=personas,
        test_cases=test_cases,
    )


def bare_shape_spec() -> AppSpec:
    """Same content as sample_spec, but the 5 dimensions kfforge.intake wraps (stages/routing/
    rework_loops/visibility/test_cases) are handed over as BARE tuples instead -- proving
    `_seq()` accepts this package's own minimal protocol shape too, not only intake's real
    wrapper shape."""
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
    """A routing point at "A" whose every option targets "C" directly -- "B" is a spine stage
    that receives NO edge at all (the implicit A->B edge is suppressed because A branches, and
    nothing routes to B either). Proves an orphan is flagged, never fabricated a way in (major 6).
    """
    stages = Stages(stages=(
        Stage("A", "Role A", "Starts here."),
        Stage("B", "Role B", "Never actually reached by this routing."),
        Stage("C", "Role C", "Ends here."),
    ))
    routing = Routing(points=(
        RoutingPoint(at_stage="A", field_name="Choice", options=("X", "Y"),
                     route_per_option=(("X", ("C",)), ("Y", ("C",)))),
    ))
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Orphan Test", problem_goal=_empty_problem_goal(), stages=stages, routing=routing,
        rework_loops=ReworkLoops(loops=()), data_model=empty_dm, master_data=empty_md,
        visibility=VisibilityMatrix(entries=()), personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_two_routing_points_same_stage() -> AppSpec:
    """Two DIFFERENT routing points both at_stage="Middle", with genuinely DISJOINT option sets
    ("A"/"B" vs "C"/"D") -- proves they render at DIFFERENT coordinates instead of stacking
    invisibly on top of each other (major 5), AND is the fixture m10 (round 2) demands:
    apply_revisions on a routing key at a shared stage must revise only the ONE decision point
    that actually has the named option, never raise just because a SIBLING doesn't (M9)."""
    stages = Stages(stages=(
        Stage("Start", "Role", "..."),
        Stage("Middle", "Role", "..."),
        Stage("End", "Role", "..."),
    ))
    routing = Routing(points=(
        RoutingPoint(at_stage="Middle", field_name="First Choice", options=("A", "B"),
                     route_per_option=(("A", ("End",)), ("B", ("End",)))),
        RoutingPoint(at_stage="Middle", field_name="Second Choice", options=("C", "D"),
                     route_per_option=(("C", ("End",)), ("D", ("Start",)))),
    ))
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Two Routing Points Test", problem_goal=_empty_problem_goal(), stages=stages,
        routing=routing, rework_loops=ReworkLoops(loops=()), data_model=empty_dm,
        master_data=empty_md, visibility=VisibilityMatrix(entries=()), personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_tiered_branches() -> AppSpec:
    """The round-1 defect (major, decision_01 item 1): three service tiers that must each run to a
    SHARED merge, not spill forward into a sibling branch's stages. A strict sequence whose one
    fork at "Triage" fans into three on-spine branch entries [Self Service, Light Work, Full
    Tier]; the light and full branches are multi-step and each carry a backward rework loop
    whose `from_stage` marks the branch's terminal. The merge is "Summary": every branch feeds it
    directly (in-degree 3), and no branch draws a spine edge into a sibling branch. Neutral-domain
    mirror of a 'choose a service level, walk it to the merge' shape."""
    stages = Stages(stages=(
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
    ))
    routing = Routing(points=(
        RoutingPoint(at_stage="Triage", field_name="Service Tier",
                     options=("Self", "Light", "Full"),
                     route_per_option=(("Self", ("Self Service",)), ("Light", ("Light Work",)),
                                       ("Full", ("Full Tier",)))),
    ))
    rework_loops = ReworkLoops(loops=(
        Loop(from_stage="Light Confirm", to_stage="Light Work", gate_field="Round Done"),
        Loop(from_stage="Full Confirm", to_stage="Full Work", gate_field="Round Done"),
    ))
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Tiered Service", problem_goal=_empty_problem_goal(), stages=stages,
        routing=routing, rework_loops=rework_loops, data_model=empty_dm, master_data=empty_md,
        visibility=VisibilityMatrix(entries=()), personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_forward_loop() -> AppSpec:
    """A "loop" whose to_stage comes AFTER its from_stage in the spine -- not a genuine rework
    loop by kfforge.intake.schema.LoopSpec's own contract. Proves this package says so rather
    than asserting "loops back" for something that does not (minor 10)."""
    stages = Stages(stages=(
        Stage("A", "Role", "..."),
        Stage("B", "Role", "..."),
        Stage("C", "Role", "..."),
    ))
    rework_loops = ReworkLoops(loops=(Loop(from_stage="A", to_stage="C", gate_field="Weird Gate"),))
    empty_dm = DataModel(fields=(), tables=())
    empty_md = MasterData(lists=())
    empty_personas = Personas(views=())
    return AppSpec(
        app_name="Forward Loop Test", problem_goal=_empty_problem_goal(), stages=stages,
        routing=Routing(points=()), rework_loops=rework_loops, data_model=empty_dm,
        master_data=empty_md, visibility=VisibilityMatrix(entries=()), personas=empty_personas,
        test_cases=TestCases(cases=()),
    )


def spec_with_tricky_text() -> AppSpec:
    """Same shape as sample_spec but one stage's name/owner carry XML/HTML-hostile characters
    plus Thai text, to pin the escaping contract end to end."""
    base = sample_spec()
    tricky = dataclasses.replace(
        base.stages.stages[0],
        name='Intake & "Return" <Urgent> รับเครื่องซ่อม',
        owner_role='หน้าเคาน์เตอร์ & Support',
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


# --------------------------------------------------------------------------------------------
# Shared XML/HTML validity helpers
# --------------------------------------------------------------------------------------------


def _assert_valid_mxgraph(xml_str: str) -> ET.Element:
    root = ET.fromstring(xml_str)  # raises ET.ParseError if not well-formed XML
    cells = root.findall(".//mxCell")
    ids = [c.get("id") for c in cells]
    assert len(ids) == len(set(ids)), "duplicate mxCell ids"
    id_set = set(ids)
    for c in cells:
        if c.get("edge") == "1":
            assert c.get("source") in id_set, f"edge {c.get('id')} source does not resolve"
            assert c.get("target") in id_set, f"edge {c.get('id')} target does not resolve"
    return root


_VOID_ELEMENTS = {"input", "meta", "link", "br", "img", "hr", "source", "col", "area",
                   "base", "embed", "track", "wbr"}


class _BalanceCheckingParser(html.parser.HTMLParser):
    """A minimal well-formedness check: every non-void start tag has a matching end tag, in
    order, and the stack is empty at EOF. Not a full HTML5 validator (not needed here) -- just
    enough to catch a stray unclosed div/section/table, which is the class of bug this kind of
    hand-built string templating actually produces.
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
    """Minor 13: scan beyond bare http(s):// -- src=/href= attributes are the other place an
    external reference could sneak in (an image, a script, a stylesheet link), even one that
    happens not to spell out a scheme (e.g. a protocol-relative "//cdn...")."""
    assert "http://" not in doc
    assert "https://" not in doc
    assert "src=" not in doc
    assert "href=" not in doc


def _marker_slice(doc: str, marker: str, boundary_prefixes: tuple[str, ...]) -> str:
    """Slice of `doc` from ONE marker comment up to the START of the next marker whose prefix is
    in `boundary_prefixes`, or the end of the document."""
    start = doc.index(marker)
    after = start + len(marker)
    candidates = [p for p in (doc.find(b, after) for b in boundary_prefixes) if p != -1]
    end = min(candidates) if candidates else len(doc)
    return doc[start:end]


def _card_slice(doc: str, stage_name: str) -> str:
    """A stage/off-spine card's own content, up to the next CARD-level marker (`<!-- stage:` or
    `<!-- table:`) -- deliberately NOT bounded by `<!-- field:`, since one or more field markers
    legitimately nest INSIDE a card; using them as a boundary would truncate the card at its own
    first field."""
    return _marker_slice(doc, f"<!-- stage:{stage_name} -->", ("<!-- stage:", "<!-- table:"))


def _field_slice(doc: str, field_name: str) -> str:
    """One field row's own content, up to the next marker of ANY kind -- a field row is the
    smallest unit, so it is bounded by a sibling field, or the card/table that comes after it."""
    return _marker_slice(
        doc, f"<!-- field:{field_name} -->", ("<!-- field:", "<!-- stage:", "<!-- table:"),
    )


# --------------------------------------------------------------------------------------------
# diagram.py
# --------------------------------------------------------------------------------------------


class TestFlowDiagram:
    def test_parses_as_valid_mxgraph_and_every_edge_resolves(self):
        spec = sample_spec()
        _assert_valid_mxgraph(flow_diagram_xml(spec))

    def test_bare_sequence_shape_also_works(self):
        _assert_valid_mxgraph(flow_diagram_xml(bare_shape_spec()))

    def test_one_decision_node_per_routing_point(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        diamonds = [c for c in root.findall(".//mxCell")
                    if c.get("vertex") == "1" and "rhombus" in (c.get("style") or "")]
        assert len(diamonds) == len(spec.routing.points)

    def test_one_dashed_back_edge_per_genuine_backward_loop(self):
        spec = sample_spec()  # its one loop (Quality Check -> Repair) IS a genuine backward loop
        root = ET.fromstring(flow_diagram_xml(spec))
        dashed_edges = [c for c in root.findall(".//mxCell")
                         if c.get("edge") == "1" and "dashed=1" in (c.get("style") or "")]
        assert len(dashed_edges) == len(spec.rework_loops.loops)

    def test_loop_edge_labeled_with_gate_field(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        dashed_values = [c.get("value") for c in root.findall(".//mxCell")
                          if c.get("edge") == "1" and "dashed=1" in (c.get("style") or "")]
        assert any(spec.rework_loops.loops[0].gate_field in (v or "") for v in dashed_values)

    def test_stage_box_second_line_is_owner_role(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        values = [c.get("value") or "" for c in root.findall(".//mxCell") if c.get("vertex") == "1"]
        stage = spec.stages.stages[0]
        assert any(stage.name in v and stage.owner_role in v and "<br>" in v for v in values)

    def test_empty_spec_still_produces_valid_xml(self):
        empty = AppSpec(
            app_name="Empty", problem_goal=_empty_problem_goal(), stages=Stages(stages=()),
            routing=Routing(points=()), rework_loops=ReworkLoops(loops=()),
            data_model=DataModel(fields=(), tables=()), master_data=MasterData(lists=()),
            visibility=VisibilityMatrix(entries=()), personas=Personas(views=()),
            test_cases=TestCases(cases=()),
        )
        _assert_valid_mxgraph(flow_diagram_xml(empty))

    def test_business_text_with_special_chars_and_thai_survives_two_decodes(self):
        """Minor 11: every style here sets html=1, so a value is HTML-rendered, not shown as
        plain text. After the ONE decode ElementTree performs, a raw '<'/'>' from the business
        name must NOT appear (that would mean it can be reinterpreted as a tag once mxGraph's
        HTML-mode renderer sees it) -- but after a SECOND decode (html.unescape, simulating what
        that renderer itself performs before painting the text), the original business text must
        be fully recovered.
        """
        spec = spec_with_tricky_text()
        xml_str = flow_diagram_xml(spec)
        root = _assert_valid_mxgraph(xml_str)
        joined_once = "\n".join(c.get("value") or "" for c in root.findall(".//mxCell"))
        assert "<Urgent>" not in joined_once  # would mean it survived as a raw, re-interpretable tag
        joined_twice = html.unescape(joined_once)
        assert spec.stages.stages[0].name in joined_twice
        assert spec.stages.stages[0].owner_role in joined_twice

    def test_two_routing_points_on_same_stage_do_not_overlap(self):
        spec = spec_with_two_routing_points_same_stage()
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        diamonds = [c for c in root.findall(".//mxCell")
                    if c.get("vertex") == "1" and "rhombus" in (c.get("style") or "")]
        assert len(diamonds) == 2
        coords = {(float(c.find("mxGeometry").get("x")), float(c.find("mxGeometry").get("y")))
                  for c in diamonds}
        assert len(coords) == 2, "two routing points at the same stage rendered at identical coordinates"

    def test_next_stage_box_does_not_overlap_the_decision_diamond(self):
        """Minor 8: the diamond(s) below a routing stage must not overlap the NEXT stage's box."""
        spec = spec_with_two_routing_points_same_stage()  # worst case: 2 stacked diamonds at "Middle"
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        diamonds = [c for c in root.findall(".//mxCell") if "rhombus" in (c.get("style") or "")]
        assert len(diamonds) == 2
        diamond_bottoms = [
            float(c.find("mxGeometry").get("y")) + float(c.find("mxGeometry").get("height"))
            for c in diamonds
        ]
        end_stage = next(
            c for c in root.findall(".//mxCell")
            if c.get("vertex") == "1" and (c.get("value") or "").startswith("End<br>")
        )
        end_y = float(end_stage.find("mxGeometry").get("y"))
        assert max(diamond_bottoms) <= end_y, "decision diamond overlaps the next stage box"

    def test_orphan_stage_is_flagged_not_fabricated_an_edge(self):
        spec = spec_with_orphan_stage()
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        flagged = [c for c in root.findall(".//mxCell") if "unreachable" in (c.get("value") or "").lower()]
        assert len(flagged) == 1, "exactly stage B should be flagged unreachable"
        b_cell = flagged[0]
        assert (b_cell.get("value") or "").startswith("B "), "the flagged node should really be stage B"
        b_id = b_cell.get("id")
        incoming = [c for c in root.findall(".//mxCell") if c.get("edge") == "1" and c.get("target") == b_id]
        assert not incoming, "orphan stage must not have a fabricated incoming edge"

    def test_reachable_stage_is_not_flagged(self):
        spec = spec_with_orphan_stage()
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        c_cell = next(c for c in root.findall(".//mxCell") if (c.get("value") or "").startswith("C<br>"))
        assert "unreachable" not in (c_cell.get("value") or "").lower()

    def test_forward_loop_is_not_drawn_dashed_and_is_not_mislabeled(self):
        spec = spec_with_forward_loop()
        idx = _stage_index(spec)
        assert _loop_direction(idx, spec.rework_loops.loops[0]) == "forward"
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        loop_edges = [
            c for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and "Weird Gate" in (c.get("value") or "")
        ]
        assert loop_edges
        assert "dashed=1" not in (loop_edges[0].get("style") or "")
        assert "forward" in (loop_edges[0].get("value") or "").lower()

    def test_fallback_nodes_for_unresolved_names_do_not_stack(self):
        """Minor 9: multiple unresolved names must not all land on the identical coordinate."""
        stages = Stages(stages=(Stage("Only", "Role", "..."),))
        rework_loops = ReworkLoops(loops=(
            Loop(from_stage="Ghost A", to_stage="Ghost B", gate_field="G1"),
            Loop(from_stage="Ghost C", to_stage="Ghost D", gate_field="G2"),
        ))
        spec = AppSpec(
            app_name="Fallback Test", problem_goal=_empty_problem_goal(), stages=stages,
            routing=Routing(points=()), rework_loops=rework_loops,
            data_model=DataModel(fields=(), tables=()), master_data=MasterData(lists=()),
            visibility=VisibilityMatrix(entries=()), personas=Personas(views=()),
            test_cases=TestCases(cases=()),
        )
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        ghost_coords = set()
        for name in ("Ghost A", "Ghost B", "Ghost C", "Ghost D"):
            cell = next(c for c in root.findall(".//mxCell") if (c.get("value") or "") == name)
            geo = cell.find("mxGeometry")
            ghost_coords.add((geo.get("x"), geo.get("y")))
        assert len(ghost_coords) == 4, f"fallback nodes stacked: {ghost_coords}"


class TestFlowDiagramBranchMerge:
    """Round-1 defect (major, decision_01 item 1): three service tiers must each reach the shared
    merge directly -- NOT by spilling forward through a sibling branch. The merge's in-degree must
    equal the number of branches, and no cross-branch spine edge may appear."""

    @staticmethod
    def _first_line(value: str) -> str:
        # after ElementTree decodes the XML, an html=1 two-line label is
        # "Name<br>Role"; split on the DECODED tag (the raw file keeps &lt;br&gt;, the
        # parsed tree has <br>).
        return value.split("<br>", 1)[0].strip()

    def _vertex_id(self, root, name: str) -> str:
        for c in root.findall(".//mxCell"):
            if c.get("vertex") == "1" and self._first_line(c.get("value") or "") == name:
                return c.get("id")
        raise AssertionError(f"no vertex named {name!r}")

    def _incoming(self, root, target_id: str) -> set[str]:
        return {c.get("source") for c in root.findall(".//mxCell")
                if c.get("edge") == "1" and c.get("target") == target_id}

    def _edge_pairs(self, root) -> set[tuple[str, str]]:
        return {(c.get("source"), c.get("target")) for c in root.findall(".//mxCell")
                if c.get("edge") == "1"}

    def _vertex_labels(self, root) -> dict[str, str]:
        # vertex id -> its first line ("Self Service" out of "Self Service<br>Analyst")
        return {c.get("id"): self._first_line(c.get("value") or "")
                for c in root.findall(".//mxCell") if c.get("vertex") == "1"}

    def test_merge_in_degree_equals_branch_count(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_tiered_branches()))
        summary = self._vertex_id(root, "Summary")
        labels = self._vertex_labels(root)
        sources = {labels[c.get("source")] for c in root.findall(".//mxCell")
                   if c.get("edge") == "1" and c.get("target") == summary and c.get("source")}
        # every branch's terminal feeds the merge: Self Service, Light Confirm, Full Confirm
        assert sources == {"Self Service", "Light Confirm", "Full Confirm"}, sources

    def test_no_cross_branch_spine_edge(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_tiered_branches()))
        pairs = self._edge_pairs(root)
        assert (self._vertex_id(root, "Self Service"), self._vertex_id(root, "Light Work")) \
            not in pairs, "self tier must not spill into the light tier"
        assert (self._vertex_id(root, "Light Confirm"), self._vertex_id(root, "Full Tier")) \
            not in pairs, "light tier must not spill into the full tier"

    def test_each_branch_tail_feeds_the_merge_as_an_edge(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_tiered_branches()))
        pairs = self._edge_pairs(root)
        summary = self._vertex_id(root, "Summary")
        assert (self._vertex_id(root, "Self Service"), summary) in pairs
        assert (self._vertex_id(root, "Light Confirm"), summary) in pairs
        assert (self._vertex_id(root, "Full Confirm"), summary) in pairs


class TestSchemaDiagram:
    def test_parses_as_valid_mxgraph(self):
        spec = sample_spec()
        _assert_valid_mxgraph(schema_diagram_xml(spec))

    def test_field_rows_show_name_type_and_required_marker(self):
        spec = sample_spec()
        root = ET.fromstring(schema_diagram_xml(spec))
        values = [c.get("value") or "" for c in root.findall(".//mxCell")]
        required_field = next(f for f in spec.data_model.fields if f.required)
        optional_field = next(f for f in spec.data_model.fields if not f.required)
        assert any(required_field.name in v and required_field.type in v and "*" in v for v in values)
        assert any(
            optional_field.name in v and optional_field.type in v and v.strip() and "*" not in v
            for v in values
        )

    def test_table_box_shows_columns_and_max_rows(self):
        spec = sample_spec()
        root = ET.fromstring(schema_diagram_xml(spec))
        values = [c.get("value") or "" for c in root.findall(".//mxCell")]
        table = spec.data_model.tables[0]
        for col in table.columns:
            assert any(col.name in v and col.type in v for v in values)
        assert any(str(table.max_rows) in v for v in values)

    def test_table_with_no_max_rows_says_no_cap(self):
        spec = sample_spec()
        no_cap_table = next(t for t in spec.data_model.tables if t.max_rows is None)
        root = ET.fromstring(schema_diagram_xml(spec))
        values = [c.get("value") or "" for c in root.findall(".//mxCell")]
        assert any("no cap" in v.lower() for v in values)
        assert not any("max rows: none" in v.lower() for v in values)
        assert no_cap_table.name  # sanity: the fixture really has one

    def test_list_rendered_as_note_box(self):
        spec = sample_spec()
        root = ET.fromstring(schema_diagram_xml(spec))
        lst = spec.master_data.lists[0]
        note_cells = [c for c in root.findall(".//mxCell") if "shape=note" in (c.get("style") or "")]
        assert any(lst.name in (c.get("value") or "") for c in note_cells)

    def test_business_text_with_special_chars_and_thai_survives_two_decodes(self):
        spec = spec_with_tricky_text()
        root = _assert_valid_mxgraph(schema_diagram_xml(spec))
        joined_twice = html.unescape("\n".join(c.get("value") or "" for c in root.findall(".//mxCell")))
        assert spec.stages.stages[0].name in joined_twice


# --------------------------------------------------------------------------------------------
# mockup.py -- faithfulness (visibility, computed fields, sections, types, terminal states,
# sequence) plus the round-1 coverage (off-spine fields, select options, master data, process
# summary, widgets, no-external-refs).
# --------------------------------------------------------------------------------------------


class TestFormMockups:
    def test_well_formed_and_no_external_refs(self):
        doc = form_mockups_html(sample_spec())
        _assert_well_formed_html(doc)
        _assert_no_external_refs(doc)

    def test_bare_sequence_shape_also_works(self):
        doc = form_mockups_html(bare_shape_spec())
        _assert_well_formed_html(doc)

    def test_every_field_of_a_stage_appears_scoped_to_its_card(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        intake_slice = _card_slice(doc, "Intake")
        for f in spec.data_model.fields:
            if f.stage == "Intake":
                assert f.name in intake_slice
        foreign = next(f for f in spec.data_model.fields if f.stage != "Intake")
        assert foreign.name not in intake_slice

    def test_off_spine_field_is_rendered_not_silently_dropped(self):
        """Major 3 (round 1): "Rejection Reason" lives on "Closed - Rejected", which is a
        routing TARGET, never a member of spec.stages -- it must still get a visible card."""
        spec = sample_spec()
        doc = form_mockups_html(spec)
        off_slice = _card_slice(doc, "Closed - Rejected")
        assert "Rejection Reason" in off_slice
        assert "required-marker" in off_slice  # it is required=True in the fixture
        assert "kf-offspine" in off_slice

    def test_required_marker_present_only_on_required_fields(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        for f in spec.data_model.fields:
            row = _field_slice(doc, f.name)
            if f.required:
                assert "required-marker" in row, f"{f.name} is required but has no marker"
            else:
                assert "required-marker" not in row, f"{f.name} is optional but has a marker"

    def test_select_field_renders_its_real_options_from_the_backing_list(self):
        """Blocker 2 (round 1): a generic "-- select --" placeholder gives nothing to proof-
        read. The Select field "Equipment Type" (list_name="Equipment Type") must render its
        list's ACTUAL values as real <option> entries."""
        spec = sample_spec()
        doc = form_mockups_html(spec)
        lst = next(lst for lst in spec.master_data.lists if lst.name == "Equipment Type")
        row = _field_slice(doc, "Equipment Type")
        for value in lst.values:
            assert f'<option value="{value}">{value}</option>' in row

    def test_table_grid_notes_row_cap_and_columns(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        capped_table = next(t for t in spec.data_model.tables if t.max_rows is not None)
        assert f"Max rows: {capped_table.max_rows}" in doc
        for col in capped_table.columns:
            assert col.name in doc

    def test_table_with_no_cap_says_no_cap_in_html(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert "Max rows: no cap" in doc
        assert "Max rows: None" not in doc

    def test_master_data_section_lists_every_list_and_every_value_verbatim(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert 'class="kf-master-data"' in doc
        for lst in spec.master_data.lists:
            list_slice_start = doc.index(f"<!-- list:{lst.name} -->")
            list_slice = doc[list_slice_start:list_slice_start + 2000]
            for value in lst.values:
                assert value in list_slice

    def test_process_summary_describes_decisions_and_loops(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert 'class="kf-process"' in doc
        rp = spec.routing.points[0]
        assert rp.at_stage in doc and rp.field_name in doc
        for option in rp.options:
            assert option in doc
        lp = spec.rework_loops.loops[0]
        assert lp.gate_field in doc and lp.from_stage in doc and lp.to_stage in doc

    def test_control_types_render_real_inputs(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert "<textarea" in doc  # Issue Description / Repair Notes
        assert "<select" in doc    # Equipment Type / Diagnosis Result
        assert 'type="checkbox"' in doc  # Rework Needed


class TestVisibilityAwareRendering:
    """Blocker 1: with none of this applied, a Hidden field rendered as a plain live input --
    the customer proofread a form containing a field the built app hides. Round-1's own proof
    case (`VisibilityEntry(section='Triage', stage='Triage', permission=HIDDEN,
    field='Due Date')`) is exactly what sample_spec's "Due Date" field/entry mirrors.
    """

    def test_hidden_field_does_not_render_as_an_editable_control(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Due Date")
        assert "<input" not in row, "a Hidden field must not render as a live control"
        assert "hidden at this step" in row

    def test_readonly_field_renders_visibly_read_only(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Repair Notes")
        assert "disabled" in row
        assert "read-only" in row

    def test_ordinary_field_still_renders_a_live_editable_control(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Customer Name")  # covered only by a section-level Editable entry
        assert "<input" in row
        assert "disabled" not in row
        assert "hidden" not in row.lower()

    def test_field_with_no_visibility_entry_at_all_still_renders_editable(self):
        """No entry mentions "Closed - Rejected" at all -- must render as the platform default
        (an ordinary editable control), never as hidden."""
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Rejection Reason")
        assert "<textarea" in row
        assert "disabled" not in row

    def test_section_level_entry_governs_every_field_in_it(self):
        """"Section-level entries count too" -- Customer Name/Equipment Type are governed only by
        the SECTION-level Editable entry for "Customer Info" (no field-level entry names them),
        and both must render editable."""
        spec = sample_spec()
        doc = form_mockups_html(spec)
        for name in ("Customer Name", "Equipment Type"):
            row = _field_slice(doc, name)
            assert "disabled" not in row
            assert "hidden" not in row.lower()

    def test_table_level_hidden_entry_hides_the_whole_table(self):
        """Major 3's "banner+table pattern": a table name is ALSO a legal VisibilityEntry
        section -- hiding "Attachments Log" at its own stage must hide the whole grid."""
        base = sample_spec()
        hiding_entry = VisibilityEntry("Attachments Log", "Quality Check", "Hidden")
        spec = dataclasses.replace(
            base, visibility=VisibilityMatrix(entries=base.visibility.entries + (hiding_entry,)),
        )
        doc = form_mockups_html(spec)
        table_slice = _marker_slice(
            doc, "<!-- table:Attachments Log -->", ("<!-- stage:", "<!-- table:"),
        )
        assert "hidden at this step" in table_slice
        assert "<table>" not in table_slice

    def test_table_without_a_hidden_entry_still_renders_its_grid(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        table_slice = _marker_slice(
            doc, "<!-- table:Parts Used -->", ("<!-- stage:", "<!-- table:"),
        )
        assert "<table>" in table_slice


class TestComputedFieldRendering:
    """Blocker 2: ComputedReq rendered nowhere, and its target rendered as a typed input, so the
    customer approved a form where a human types a value the app will auto-calculate."""

    def test_computed_target_is_marked_auto_calculated_not_a_live_input(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Estimated Cost")
        assert "<input" not in row
        assert "auto-calculated" in row

    def test_computed_target_shows_its_formula_intent(self):
        """formula_intent exists specifically to be read by a human -- it must actually render."""
        spec = sample_spec()
        doc = form_mockups_html(spec)
        computed = spec.data_model.computed[0]
        row = _field_slice(doc, "Estimated Cost")
        assert computed.formula_intent in row

    def test_computed_target_notes_its_source_fields(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        computed = spec.data_model.computed[0]
        row = _field_slice(doc, "Estimated Cost")
        for src in computed.source_fields:
            assert src in row


class TestSectionGrouping:
    """Major 3: SectionReq rendered nowhere -- a stage with two sections rendered as one
    undifferentiated card."""

    def test_two_sections_on_one_stage_render_as_two_distinct_named_blocks(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        intake_slice = _card_slice(doc, "Intake")
        for sec in spec.data_model.sections:
            if sec.stage != "Intake":
                continue
            assert sec.name in intake_slice
            assert sec.description in intake_slice

    def test_fields_appear_under_their_own_section_not_a_sibling_s(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        customer_info_start = doc.index("Customer Info")
        issue_details_start = doc.index("Issue Details")
        # "Customer Name"/"Equipment Type" belong to Customer Info, which renders before Issue
        # Details in field order -- assert their marker sits before the Issue Details heading.
        assert doc.index("<!-- field:Customer Name -->") < issue_details_start
        assert doc.index("<!-- field:Issue Description -->") > customer_info_start


class TestColumnTypeConsistency:
    """Major 4: mockup._column_header_label used to show name+required only, while
    diagram._column_label already showed type -- the two must agree."""

    def test_mockup_and_diagram_show_the_same_column_type_text(self):
        spec = sample_spec()
        html_doc = form_mockups_html(spec)
        xml_doc = schema_diagram_xml(spec)
        table = spec.data_model.tables[0]
        for col in table.columns:
            expected = f"{col.name} : {col.type}"
            assert expected in html_doc, f"mockup missing {expected!r}"
            assert col.name in xml_doc and col.type in xml_doc


class TestFieldTypeStatedInWords:
    """Major 5: a field's type was never stated in words; an unmapped type (e.g. User) rendered
    pixel-identical to Text."""

    def test_known_type_is_stated_in_words(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Customer Name")
        assert "(Text)" in row

    def test_unmapped_type_renders_differently_from_text_and_is_flagged(self):
        base = sample_spec()
        weird_field = Field("Assigned Reviewer", "User", False, "Intake", section="Customer Info")
        new_fields = base.data_model.fields + (weird_field,)
        spec = dataclasses.replace(base, data_model=dataclasses.replace(base.data_model, fields=new_fields))
        doc = form_mockups_html(spec)
        text_row = _field_slice(doc, "Customer Name")
        weird_row = _field_slice(doc, "Assigned Reviewer")
        assert "(User)" in weird_row
        assert "no dedicated control" in weird_row
        assert "no dedicated control" not in text_row


class TestDeclaredVsDerivedTerminals:
    """Major 6: ProblemGoal.terminal_states/result_values rendered nowhere, and "Where the work
    ends" answered a DIFFERENT (derived-topology) question under that same heading."""

    def test_declared_terminal_states_and_result_values_render_labeled_as_declared(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        terminals_slice = doc[doc.index('class="kf-terminals"'):]
        assert "Declared by the business" in terminals_slice
        for state in spec.problem_goal.terminal_states:
            assert state in terminals_slice
        for result in spec.problem_goal.result_values:
            assert result in terminals_slice

    def test_derived_list_is_present_but_labeled_as_derived(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        terminals_slice = doc[doc.index('class="kf-terminals"'):]
        assert "derived from routing/loops" in terminals_slice

    def test_declared_and_derived_are_not_the_same_unlabeled_list(self):
        """A spec whose declared terminal_states DIFFER from the derived topology list must show
        BOTH, not silently prefer one -- proving the two are genuinely separate blocks, not one
        heading quietly answering only one of the two questions."""
        base = sample_spec()
        different_goal = dataclasses.replace(
            base.problem_goal, terminal_states=("Totally Custom End State",),
        )
        spec = dataclasses.replace(base, problem_goal=different_goal)
        doc = form_mockups_html(spec)
        terminals_slice = doc[doc.index('class="kf-terminals"'):]
        assert "Totally Custom End State" in terminals_slice  # declared, rendered even though
        # it names something the topology itself never computed
        assert "Quality Check" in terminals_slice  # still present in the DERIVED list below it


class TestSequenceRendering:
    """Major 7: SequenceReq prefix/padding rendered nowhere, yet it is the record id every user
    of the built app actually sees."""

    def test_sequence_format_is_rendered(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        seq = spec.data_model.sequence
        assert f"{seq.prefix}-{seq.padding}" in doc

    def test_prefix_already_carrying_a_dash_does_not_double_wire(self):
        """decision_01 item 2: a prefix may already end with the separator (e.g. `RPT-`); joining
        that with another dash double-wires it into `RPT--0001`. A trailing dash must not double."""
        assert _format_sequence("RPT-", "0001") == "RPT-0001"
        assert _format_sequence("RPR", "0001") == "RPR-0001"

    def test_no_sequence_means_no_note(self):
        base = sample_spec()
        spec = dataclasses.replace(base, data_model=dataclasses.replace(base.data_model, sequence=None))
        doc = form_mockups_html(spec)
        # the CSS rule name itself is always present in the static <style> block regardless of
        # whether anything uses that class -- check for the actual ELEMENT, not the class name.
        assert '<p class="kf-sequence-note">' not in doc


class TestPersonaPages:
    def test_well_formed_and_no_external_refs(self):
        doc = persona_pages_html(sample_spec())
        _assert_well_formed_html(doc)
        _assert_no_external_refs(doc)

    def test_kpis_and_actions_come_from_the_view_not_the_page(self):
        spec = sample_spec()
        doc = persona_pages_html(spec)
        for view in spec.personas.views:
            for kpi in view.kpis:
                assert kpi in doc
            for action in view.actions:
                assert action in doc
            for page in view.pages:
                assert page.name in doc

    def test_widget_renders_a_human_label_not_a_raw_repr(self):
        """Minor 14: kfforge.intake.schema.WidgetIntent has no `.name` -- it must not fall
        through to a raw `WidgetIntent(slug=..., config=..., row_fields=...)` repr."""

        @dataclasses.dataclass(frozen=True)
        class WidgetIntent:
            slug: str
            config: tuple[tuple[str, str], ...] = ()
            row_fields: tuple[str, ...] = ()

        widget = WidgetIntent(slug="view/table", config=(("flow_type", "process"), ("view_id", "myitems")))
        page = Page(name="My Queue", widgets=(widget,))
        view = PersonaView(role="Reviewer", pages=(page,), kpis=(), actions=())
        spec = dataclasses.replace(sample_spec(), personas=Personas(views=(view,)))
        doc = persona_pages_html(spec)
        assert "view/table" in doc
        assert "flow_type" in doc and "process" in doc
        assert "WidgetIntent(" not in doc
        assert "row_fields=" not in doc


class TestDesignBundle:
    def test_well_formed_and_no_external_refs(self):
        doc = design_bundle_html(sample_spec())
        _assert_well_formed_html(doc)
        _assert_no_external_refs(doc)

    def test_contains_both_diagrams_and_both_html_sections(self):
        spec = sample_spec()
        doc = design_bundle_html(spec)
        assert doc.count("&lt;mxGraphModel") == 2  # flow + schema, escaped inside <pre>
        assert 'class="kf-card' in doc             # form mockups section
        assert spec.personas.views[0].role in doc  # persona pages section
        assert 'class="kf-process"' in doc          # process summary
        assert 'class="kf-master-data"' in doc      # master data

    def test_raw_xml_inside_pre_reparses(self):
        spec = sample_spec()
        doc = design_bundle_html(spec)
        pres = re.findall(r"<pre>(.*?)</pre>", doc, flags=re.DOTALL)
        assert len(pres) == 2
        for raw in pres:
            xml_text = html.unescape(raw)
            ET.fromstring(xml_text)  # must be independently parseable once un-escaped


# --------------------------------------------------------------------------------------------
# confirm.py
# --------------------------------------------------------------------------------------------


class TestRequestConfirmation:
    def test_artifacts_present_and_parseable(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        assert isinstance(req, ConfirmationRequest)
        assert set(req.artifacts) == {"flow_diagram.drawio", "schema_diagram.drawio", "design.html"}
        ET.fromstring(req.artifacts["flow_diagram.drawio"])
        ET.fromstring(req.artifacts["schema_diagram.drawio"])
        _assert_well_formed_html(req.artifacts["design.html"])

    def test_digest_is_a_sha256_hex_string(self):
        req = request_confirmation(sample_spec())
        assert re.fullmatch(r"[0-9a-f]{64}", req.spec_digest)

    def test_questions_cover_every_routing_literal(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        for rp in spec.routing.points:
            for option in rp.options:
                assert any(option in q and rp.at_stage in q for q in req.questions), (
                    f"no question covers routing literal {option!r} at {rp.at_stage!r}"
                )

    def test_questions_cover_every_loop_gate(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        for lp in spec.rework_loops.loops:
            assert any(lp.gate_field in q and lp.from_stage in q for q in req.questions)

    def test_forward_loop_question_does_not_claim_it_loops_back(self):
        spec = spec_with_forward_loop()
        req = request_confirmation(spec)
        lp = spec.rework_loops.loops[0]
        matching = [q for q in req.questions if lp.gate_field in q]
        assert matching
        assert not any("วนกลับไปที่" in q for q in matching)  # never the backward-loop phrasing
        assert any("ไปข้างหน้า" in q for q in matching)  # flags it as going forward instead

    def test_questions_cover_every_terminal_state(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        assert any("Quality Check" in q for q in req.questions)
        assert any("Closed - Rejected" in q for q in req.questions)

    def test_questions_cover_every_required_field(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        for f in spec.data_model.fields:
            if f.required:
                assert any(f.name in q for q in req.questions)

    def test_questions_cover_every_master_data_list_byte_exact(self):
        """Note "Equipment Type" is both a FIELD name (required-field question) and a LIST name
        (master-data question) in the fixture on purpose -- a naive "first question whose text
        contains the list name" pick would land on the wrong one, so this checks that AT LEAST
        ONE matching question carries every value, not just the first match."""
        spec = sample_spec()
        req = request_confirmation(spec)
        for lst in spec.master_data.lists:
            matching = [q for q in req.questions if lst.name in q]
            assert matching, f"no question covers list {lst.name!r}"
            assert any(all(v in q for v in lst.values) for q in matching), (
                f"no question for list {lst.name!r} carries every value byte-exact"
            )

    def test_questions_are_thai_confirm_revise_prompts(self):
        req = request_confirmation(sample_spec())
        assert req.questions
        for q in req.questions:
            assert any("฀" <= ch <= "๿" for ch in q), f"not Thai: {q!r}"


class TestDigestChangesWithSpec:
    def test_same_content_same_digest(self):
        d1 = request_confirmation(sample_spec()).spec_digest
        d2 = request_confirmation(sample_spec()).spec_digest
        assert d1 == d2

    def test_changed_spec_changes_digest(self):
        spec1 = sample_spec()
        spec2 = dataclasses.replace(spec1, app_name="Different Name")
        d1 = request_confirmation(spec1).spec_digest
        d2 = request_confirmation(spec2).spec_digest
        assert d1 != d2

    def test_deep_mutation_inside_a_wrapper_also_changes_digest(self):
        spec1 = sample_spec()
        new_loops = ReworkLoops(loops=(
            dataclasses.replace(spec1.rework_loops.loops[0], gate_field="Different Gate"),
        ))
        spec2 = dataclasses.replace(spec1, rework_loops=new_loops)
        d1 = request_confirmation(spec1).spec_digest
        d2 = request_confirmation(spec2).spec_digest
        assert d1 != d2

    def test_visibility_mutation_changes_digest(self):
        """The digest must see through the visibility matrix too, not just the dimensions round
        1 already covered."""
        spec1 = sample_spec()
        new_entries = spec1.visibility.entries + (
            VisibilityEntry("Quality Check", "Quality Check", "ReadOnly", field="Rework Needed"),
        )
        spec2 = dataclasses.replace(spec1, visibility=VisibilityMatrix(entries=new_entries))
        d1 = request_confirmation(spec1).spec_digest
        d2 = request_confirmation(spec2).spec_digest
        assert d1 != d2

    def test_approval_on_old_digest_does_not_carry_to_a_revised_spec(self):
        spec1 = sample_spec()
        req1 = request_confirmation(spec1)
        decision = "approve"
        assert is_approved(spec1, decision) is True
        approved_digest = req1.spec_digest

        spec2 = apply_revisions(spec1, {"app_name": "Equipment Repair Intake (v2)"})
        req2 = request_confirmation(spec2)

        assert req2.spec_digest != approved_digest, (
            "a revised spec must never silently inherit an earlier approval's digest"
        )


class TestIsApproved:
    @pytest.mark.parametrize("decision,expected", [
        ("approve", True),
        ("Approve", False),
        ("approved", False),
        ("reject", False),
        ("revise", False),
        ("", False),
    ])
    def test_only_explicit_approve_is_true(self, decision, expected):
        assert is_approved(sample_spec(), decision) is expected


class TestApplyRevisions:
    def test_unknown_key_raises_naming_valid_keys(self):
        spec = sample_spec()
        with pytest.raises(ValueError) as exc_info:
            apply_revisions(spec, {"not_a_real_key": "x"})
        message = str(exc_info.value)
        assert "app_name" in message  # at least one real valid key is named

    def test_app_name_revision_applies_and_is_pure(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"app_name": "Renamed Intake"})
        assert revised.app_name == "Renamed Intake"
        assert spec.app_name == "Equipment Repair Intake"  # original untouched

    def test_stage_attribute_revision_applies_to_only_that_stage(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"stage:Intake:owner_role": "Reception"})
        by_name = {s.name: s for s in revised.stages.stages}
        assert by_name["Intake"].owner_role == "Reception"
        assert by_name["Diagnosis"].owner_role == "Technician"  # untouched
        assert spec.stages.stages[0].owner_role == "Front Desk"  # original untouched

    # ---- M9: a sibling decision point at the shared stage must never cause a false raise ----

    def test_routing_target_revision_at_a_shared_stage_touches_only_the_matching_point(self):
        """m10 (round 2, REQUIRED regression guard for M9): spec_with_two_routing_points_same_
        stage() existed in round 1 but was never fed to apply_revisions -- that hole is exactly
        what let M9 through (the option-existence raise fired on the FIRST routing point at a
        shared stage regardless of which one actually had the option)."""
        spec = spec_with_two_routing_points_same_stage()
        revised = apply_revisions(spec, {"routing-target:Middle:A": "Start"})
        by_field = {rp.field_name: rp for rp in revised.routing.points}
        assert dict(by_field["First Choice"].route_per_option)["A"] == ("Start",)
        # the SIBLING decision point (whose options are C/D, not A/B) must be untouched
        assert dict(by_field["Second Choice"].route_per_option) == {"C": ("End",), "D": ("Start",)}

    def test_routing_option_revision_at_a_shared_stage_touches_only_the_matching_point(self):
        spec = spec_with_two_routing_points_same_stage()
        revised = apply_revisions(spec, {"routing-option:Middle:C": "C-renamed"})
        by_field = {rp.field_name: rp for rp in revised.routing.points}
        assert "C-renamed" in by_field["Second Choice"].options
        assert by_field["First Choice"].options == ("A", "B")  # sibling untouched

    def test_routing_target_revision_raises_only_when_no_point_at_the_stage_has_the_option(self):
        spec = spec_with_two_routing_points_same_stage()
        with pytest.raises(ValueError, match="no option"):
            apply_revisions(spec, {"routing-target:Middle:Z": "Start"})  # "Z" is nobody's option

    def test_routing_target_revision_changes_where_an_option_routes(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"routing-target:Diagnosis:Beyond Repair": "Closed - Escalated"})
        rp = revised.routing.points[0]
        mapping = dict(rp.route_per_option)
        assert mapping["Beyond Repair"] == ("Closed - Escalated",)
        assert mapping["Repairable"] == ("Repair",)  # untouched
        assert dict(spec.routing.points[0].route_per_option)["Beyond Repair"] == ("Closed - Rejected",)

    def test_routing_option_revision_fixes_a_miscased_literal_preserving_its_target(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"routing-option:Diagnosis:Needs Parts": "Needs parts"})
        rp = revised.routing.points[0]
        assert "Needs parts" in rp.options
        assert "Needs Parts" not in rp.options
        assert dict(rp.route_per_option)["Needs parts"] == ("Repair",)  # target preserved

    # ---- M10: stage rename must cascade into visibility/sections/test-cases too ----

    def test_stage_rename_cascades_into_visibility_and_section_and_test_cases(self):
        """M10: proven necessary against a real AppSpec (cross-tree verification script) -- a
        bare rename that skipped visibility.stage, SectionReq.stage, CaseWalk.expected_path, and
        StepFill.stage returned a spec kfforge.intake.compile.compile_spec() rejected."""
        spec = sample_spec()
        revised = apply_revisions(spec, {"stage:Repair:rename": "Fix"})

        assert {s.name for s in revised.stages.stages} == {"Intake", "Diagnosis", "Fix", "Quality Check"}

        rp = revised.routing.points[0]
        mapping = dict(rp.route_per_option)
        assert mapping["Repairable"] == ("Fix",)
        assert mapping["Needs Parts"] == ("Fix",)

        lp = revised.rework_loops.loops[0]
        assert lp.to_stage == "Fix"

        # SectionReq.stage
        repair_work = next(sec for sec in revised.data_model.sections if sec.name == "Repair Work")
        assert repair_work.stage == "Fix"
        # VisibilityEntry.stage (both the section-level and field-level Repair-stage entries)
        repair_entries = [e for e in revised.visibility.entries if e.section == "Repair Work"]
        assert repair_entries
        assert all(e.stage == "Fix" for e in repair_entries)
        # VisibilityEntry.section is an EXPLICIT name ("Repair Work"), unrelated to the stage's
        # own name ("Repair") -- must NOT be touched by the rename.
        assert all(e.section == "Repair Work" for e in repair_entries)

        # test case: expected_path and the matching StepFill.stage
        case = revised.test_cases.cases[0]
        assert "Fix" in case.expected_path
        assert "Repair" not in case.expected_path
        fill_stages = {f.stage for f in case.fills}
        assert "Fix" in fill_stages
        assert "Repair" not in fill_stages

        # original spec is untouched (pure)
        assert spec.stages.stages[2].name == "Repair"
        assert spec.test_cases.cases[0].expected_path == ("Intake", "Diagnosis", "Repair", "Quality Check")

    def test_stage_rename_cascades_visibility_section_when_it_is_the_implicit_default(self):
        """The OTHER visibility-section shape: "Quality Check" stage's own entry uses the
        IMPLICIT default section (section name == stage name, no SectionReq object) -- renaming
        the stage must rename BOTH `.stage` and `.section` on that one entry. A DIFFERENT entry
        naming an unrelated EXPLICIT section that merely happens to share the old stage's `.stage`
        (the table-visibility entry, section="Attachments Log") must have its `.stage` renamed
        but its `.section` left alone -- these are two different entries, checked separately.
        """
        spec = sample_spec()
        original = next(
            e for e in spec.visibility.entries
            if e.stage == "Quality Check" and e.section == "Quality Check"
        )
        revised = apply_revisions(spec, {"stage:Quality Check:rename": "QA"})

        implicit_matches = [
            e for e in revised.visibility.entries
            if e.permission == original.permission and e.field == original.field
            and e.stage == "QA" and e.section == "QA"
        ]
        assert implicit_matches, "the implicit-default-section entry must have BOTH stage and section renamed"
        assert not any(e.stage == "Quality Check" or e.section == "Quality Check"
                        for e in revised.visibility.entries)

    def test_stage_rename_unknown_name_raises(self):
        spec = sample_spec()
        with pytest.raises(ValueError):
            apply_revisions(spec, {"stage:Nonexistent Stage:rename": "X"})

    # ---- M11: list-value rename must cascade into routing and test cases ----

    def test_list_value_revision_cascades_into_routing_and_test_case(self):
        """M11: proven necessary against a real AppSpec -- renaming a list value in isolation
        left a routing option and a test-case fill referencing the OLD literal, which
        compile_spec()'s _check_routing_literals/_check_test_cases both rejected.
        """
        spec = sample_spec()
        revised = apply_revisions(
            spec, {"list:Diagnosis Result Options:value:Repairable": "Repairable (confirmed)"}
        )
        lst = next(lst for lst in revised.master_data.lists if lst.name == "Diagnosis Result Options")
        assert "Repairable (confirmed)" in lst.values
        assert "Repairable" not in lst.values

        rp = revised.routing.points[0]
        assert "Repairable (confirmed)" in rp.options
        assert "Repairable" not in rp.options
        assert dict(rp.route_per_option)["Repairable (confirmed)"] == ("Repair",)

        case = revised.test_cases.cases[0]
        diagnosis_fill = next(f for f in case.fills if f.stage == "Diagnosis")
        assert dict(diagnosis_fill.values)["Diagnosis Result"] == "Repairable (confirmed)"

        # original untouched (pure)
        assert "Repairable" in spec.master_data.lists[1].values
        original_diagnosis_fill = next(f for f in spec.test_cases.cases[0].fills if f.stage == "Diagnosis")
        assert dict(original_diagnosis_fill.values)["Diagnosis Result"] == "Repairable"

    def test_list_value_revision_with_no_backing_field_still_applies(self):
        """A list value that backs no field at all (or none that drives routing/appears in a
        test case) should still rename cleanly -- no cascade needed, no error either."""
        spec = sample_spec()
        revised = apply_revisions(spec, {"list:Equipment Type:value:Router": "Wireless Router"})
        lst = next(lst for lst in revised.master_data.lists if lst.name == "Equipment Type")
        assert "Wireless Router" in lst.values
        assert "Router" not in lst.values
        assert len(lst.values) == 4  # replaced in place, not appended

    def test_list_value_unknown_value_raises(self):
        spec = sample_spec()
        with pytest.raises(ValueError):
            apply_revisions(spec, {"list:Equipment Type:value:Nonexistent": "X"})

    # ---- remaining widened-vocabulary keys (round 1, re-verified against the new fixture) ----

    def test_loop_gate_field_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"loop:Quality Check:Repair:gate_field": "Needs Rework"})
        assert revised.rework_loops.loops[0].gate_field == "Needs Rework"
        assert spec.rework_loops.loops[0].gate_field == "Rework Needed"

    def test_loop_direction_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"loop:Quality Check:Repair:to_stage": "Diagnosis"})
        assert revised.rework_loops.loops[0].to_stage == "Diagnosis"
        assert revised.rework_loops.loops[0].from_stage == "Quality Check"

    def test_field_required_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"field:Repair:Repair Notes:required": "true"})
        f = next(f for f in revised.data_model.fields if f.name == "Repair Notes")
        assert f.required is True
        original = next(f for f in spec.data_model.fields if f.name == "Repair Notes")
        assert original.required is False

    def test_field_rename_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"field:Repair:Repair Notes:rename": "Technician Notes"})
        names = {f.name for f in revised.data_model.fields if f.stage == "Repair"}
        assert "Technician Notes" in names
        assert "Repair Notes" not in names

    def test_table_max_rows_revision_applies_including_no_cap(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"table:Parts Used:max_rows": "25"})
        t = next(t for t in revised.data_model.tables if t.name == "Parts Used")
        assert t.max_rows == 25

        revised_none = apply_revisions(spec, {"table:Parts Used:max_rows": "none"})
        t2 = next(t for t in revised_none.data_model.tables if t.name == "Parts Used")
        assert t2.max_rows is None

    def test_multiple_revisions_in_one_call(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {
            "app_name": "Renamed",
            "stage:Intake:owner_role": "Reception",
        })
        assert revised.app_name == "Renamed"
        assert revised.stages.stages[0].owner_role == "Reception"

    def test_every_question_category_has_a_matching_revision_key(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        rp = spec.routing.points[0]
        apply_revisions(spec, {f"routing-option:{rp.at_stage}:{rp.options[0]}": "Renamed Option"})
        apply_revisions(spec, {f"routing-target:{rp.at_stage}:{rp.options[0]}": "Somewhere Else"})
        lp = spec.rework_loops.loops[0]
        apply_revisions(spec, {f"loop:{lp.from_stage}:{lp.to_stage}:gate_field": "New Gate"})
        rf = next(f for f in spec.data_model.fields if f.required)
        apply_revisions(spec, {f"field:{rf.stage}:{rf.name}:required": "false"})
        lst = spec.master_data.lists[0]
        apply_revisions(spec, {f"list:{lst.name}:value:{lst.values[0]}": "Renamed Value"})
        assert req.questions  # sanity: there really were questions to answer


# --------------------------------------------------------------------------------------------
# Blocker 1 regression: walk the SIX public entry points against a spec built with intake's
# real attribute names/nesting, explicitly, in one place. sample_spec() already uses this shape
# throughout the file above (that is what makes the rest of this suite a real regression guard,
# not just this class) -- this class exists so a reviewer can find, in one spot, an unambiguous
# proof that every public function survives the real shape, spelled out with the real names.
# --------------------------------------------------------------------------------------------


class TestRealIntakeShapeCompatibility:
    """kfforge.intake.schema.AppSpec wraps every dimension (Stages.stages, Routing.points,
    ReworkLoops.loops, VisibilityMatrix.entries, TestCases.cases) and puts kpis/actions on
    PersonaView, never on PageIntent. A first review round ran this package's six public entry
    points against a real AppSpec and found five of six raised. These tests pin that shape
    explicitly -- never importing kfforge.intake itself, only mirroring its attribute names.
    """

    def test_the_fixture_really_uses_intake_s_real_nesting(self):
        spec = sample_spec()
        assert isinstance(spec.stages, Stages) and spec.stages.stages
        assert isinstance(spec.routing, Routing) and spec.routing.points
        assert isinstance(spec.rework_loops, ReworkLoops) and spec.rework_loops.loops
        assert isinstance(spec.visibility, VisibilityMatrix) and spec.visibility.entries
        assert isinstance(spec.test_cases, TestCases) and spec.test_cases.cases
        assert isinstance(spec.problem_goal, ProblemGoal)
        view = spec.personas.views[0]
        assert view.kpis and view.actions           # kpis/actions live on the VIEW...
        assert not hasattr(view.pages[0], "kpis")    # ...never on the page
        assert not hasattr(view.pages[0], "actions")

    def test_flow_diagram_xml_does_not_raise(self):
        _assert_valid_mxgraph(flow_diagram_xml(sample_spec()))

    def test_schema_diagram_xml_does_not_raise(self):
        _assert_valid_mxgraph(schema_diagram_xml(sample_spec()))

    def test_form_mockups_html_does_not_raise(self):
        _assert_well_formed_html(form_mockups_html(sample_spec()))

    def test_persona_pages_html_does_not_raise(self):
        _assert_well_formed_html(persona_pages_html(sample_spec()))

    def test_design_bundle_html_does_not_raise(self):
        _assert_well_formed_html(design_bundle_html(sample_spec()))

    def test_request_confirmation_does_not_raise(self):
        req = request_confirmation(sample_spec())
        assert req.questions and req.artifacts and req.spec_digest
