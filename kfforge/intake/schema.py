"""kfforge.intake.schema — the 11-dimension input spec a Kissflow build needs before a single
write API call is safe to make.

Pure and offline: no network, no Kissflow calls, no app-specific vocabulary baked in (this module
describes the SHAPE of a business's answers, never one business's actual answers). Every
dataclass is a frozen struct — a spec is never mutated in place; `dataclasses.replace(spec, ...)`
is how a caller fills in one more answer as the Q&A round progresses. Collections are tuples
throughout, including "mapping-shaped" data (`route_per_option`, field fill values, widget
config) as tuples of pairs rather than `dict` — a `dict` field would be the one piece of a frozen
struct still mutable in place, and `dict(pairs)` reconstructs a real mapping trivially wherever
one is convenient to work with (compile.py does this at every use site).

The 11 dimensions, in the numbering used everywhere in this package (questions.py's priority
order, compile.py's error messages): 1 problem/goal, 2 roles, 3 stages, 4 routing, 5 rework
loops, 6 data model, 7 master data, 8 visibility matrix, 9 timing, 10 personas, 11 test cases.
Three fields reuse the engine's own closed wire-string catalogs rather than re-inventing them:
`FieldReq.type`/`TableColumnReq.type` are `kfforge.types.FieldType`, `VisibilityEntry.permission`
is `kfforge.types.Visibility`, and `ComputedReq.trigger` is `kfforge.types.EventTrigger` (born
here, moved there so the LIVE write path derives from the same table — re-exported below) — a
data-model field, a visibility entry, or a computed-field trigger in this spec is always headed
toward becoming a real Kissflow node, so none of them should be able to name something the engine
doesn't understand. `compile.py` re-checks every one of these at runtime too (`isinstance`),
since a dataclass never enforces its own type hints — a caller CAN still hand it a raw string.

`AppSpec.gaps()` is the FULL output-invariant audit for this module: every one of the 11
dimensions is checked, every single call, and an insufficient one always produces exactly one
sentence — never a silent pass, never a dimension quietly skipped. `AppSpec.blocking_gaps()` is
the subset `compile.compile_spec` actually refuses on — see `ADVISORY_DIMENSIONS`.

Two escape hatches exist so a real, simple, straight-line app doesn't have to lie its way past
this schema (a divergence this package manufactured in an earlier round, caught in review):
`Routing.confirmed_none` / `ReworkLoops.confirmed_none` / `MasterData.confirmed_none` let a
business owner explicitly answer "there is none of this," which counts as complete without
inventing a fake branch, a fake loop, or a fake dropdown list.

Explicitly OUT OF SCOPE (logged here rather than silently omitted, ponytail/YAGNI): parallel
branches. `kfforge.graph.build_workflow` supports a `parallel`/`parallel_after` gateway
(`Branch = tuple[str, list[Step]]`, itself a nested list of steps), but `Stages` here models only
a single, strictly sequential chain — matching `WorkflowType:"Sequence"`, the overwhelmingly
common case this package was built to cover. Modeling a branch grouping as a 12th dimension is a
reasonable future extension once a real spec needs it; adding it speculatively now, in the same
pass as everything else in this file, would be exactly the kind of unrequested complexity this
codebase's own conventions warn against.

KNOWN GAPS, also logged rather than silently discovered later — every item below still compiles
WITHOUT raising today, so a `BuildPlan` is proof the spec is internally referential (every name
resolves to a real one of something), never proof it is semantically sensible on these specific
axes. Closing all of them in one pass risks the same failure mode that produced them in the first
place (a large simultaneous rewrite outrunning its own test coverage) — each is real, each is
scoped, none is silently pretended away:

- Duplicate names across stages/fields/roles/lists are never caught. Op derivation keys
  everything downstream by name (`by_stage`, `fields_by_name`, `role_names`, ...), so two
  same-named stages/fields/roles/lists silently collapse into one entry in every LOOKUP while
  BOTH still emit their own op — e.g. two same-named fields each still get their own
  `apply_fields` entry, but any check or op that resolves BY that name only ever sees one of them.
- `CaseWalk` test-case walks are validated internally (every field/value/result named in one
  actually exists) but never cross-checked against the WORKFLOW they claim to walk:
  `expected_path` can contradict where `Routing`/`ReworkLoops` would actually route the item, can
  start mid-flow instead of at the first stage, can leave a loop gate no case ever exercises or a
  Required field no case ever fills, or can name a stage nothing in `Routing` ever actually
  reaches.
- Widget config (`WidgetIntent.config`) is checked for PRESENCE only, never validity —
  `view_id="totally_bogus_view"` satisfies `_check_widgets` exactly as well as a real one would
  (only five real view ids exist: myitems/mytasks/participated/admin/assigned — CLAUDE.md Pages),
  and `repeater`'s `row_fields` can name fields that exist nowhere in `DataModel`.
- `LoopSpec.max_rounds` has no `<= 0` guard, unlike `TableReq.max_rows`'s equivalent check — a
  non-positive round cap compiles clean.
- `confirmed_none=True` alongside a genuinely non-empty `points`/`loops`/`lists` is never flagged
  as a contradiction. The resulting PLAN is still correct (op derivation reads the real content;
  the flag is consulted only by `gaps()`, and only when that content is empty), but the SPEC
  itself now records two disagreeing answers from whoever filled it in, and nothing notices.
- Visibility semantics are under-specified beyond what this round's fixes close: the SAME
  `(section, stage)` pair declared twice with different permissions silently lets the FIRST one
  win (`compile._effective_permission` resolves with `next(...)`), and BOTH survive into the
  `set_visibility` op. That is not merely untidy — an `Editable` duplicate listed ahead of a
  `Hidden` one defeats the required-field check above, which is the one gap here that can still
  produce an unsubmittable step. A stage with no visibility entry at all reads identically to one
  deliberately left at the platform default EXCEPT for sections holding a required field, where
  the required-field check now raises. A field-level entry can still name a field that doesn't
  live in the section it's attached to.
- `ListSpec.owner_role` is the one role-shaped reference in this whole schema with no
  cross-check against `Roles` — every OTHER role reference (`StageSpec.owner_role`,
  `PersonaView.role`) is checked.
- Empty-but-technically-valid containers compile without complaint: a `TableReq` with zero
  columns, a `PersonaView` with zero pages, a stage with zero fields AND zero tables (a step
  nobody can ever interact with), a blank `app_name`, or a `SequenceReq.padding` holding garbage
  that isn't actually a padding pattern (e.g. `"abc"` instead of `"0001"`).
- FIVE fields have no question in `questions.py` that elicits them, so a builder must invent a
  value with no business input behind it at all: `WidgetIntent.slug`/`.config` (notably
  `view_id` — myitems vs admin vs assigned is a real business choice about WHOSE items a widget
  shows, not a technical default), `ComputedReq.trigger`, `AppSpec.app_name` (blank compiles and
  lands `''` in both the `create_process` and `publish` ops — the app ships unnamed), and
  `FieldReq.options`, which carries the per-type keys the builder actually requires (Textarea
  `AllowFormatting`, Number `Decimalpoint`, Attachment `CaptureOnly`); "how many decimal places"
  is a real business answer that nothing asks for. Two siblings in the same situation —
  `TableColumnReq.type`/`.required` and `SectionReq.description` — now DO have dedicated
  questions (`6c`/`6d` in `questions.py`, added because they change the built app materially);
  these five remain open.
- `questions.py` offers every `FieldType` member as a legal answer, including `User`. CLAUDE.md:
  a `User`-type FIELD blocks publish (`KISSFLOW_ERROR_04211`, shape uncaptured). A spec naming one
  compiles clean and fails at publish time, not here.
- The required-field/visibility check covers `data_model.fields` only. A required TABLE COLUMN in
  a table hidden at its own stage compiles clean — same fatal class, narrower reach.
- Page BEHAVIOR (`PageIntent.popups`/`.on_click`, #39 T1) is pure vocabulary in THIS file — the
  dataclasses still don't enforce their own hints. But the three referential checks #39 owed to T2
  are now enforced at COMPILE (#40, `compile._check_on_click`): (a) an `OnClickAction`'s exactly-
  one-arm contract (`target_popup` iff `OPEN_POPUP`, `script` iff `JS_ACTION`); (b) an OpenPopup
  arm's `target_popup` must name a real `PopupIntent` on the same page; and (c) `action` must be one
  the owning `PersonaView` declares. A malformed wiring compiles-refuses now, no longer surfacing
  only when a later build tries the node.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# EventTrigger/TRIGGER_LIVE_CONFIRMED/trigger_for were BORN here and now live in
# `kfforge.types` — the neutral module both this spec layer and the live write path
# (`client.apply_field_events`, which derives a source field's trigger off the LIVE draft)
# can import without the engine depending on intake. Re-exported, not re-declared: every
# existing `from kfforge.intake.schema import EventTrigger` still resolves to the one enum.
from ..types import (
    TRIGGER_LIVE_CONFIRMED as TRIGGER_LIVE_CONFIRMED,
    EventTrigger,
    FieldType,
    Visibility,
    trigger_for as trigger_for,
)

# Canonical 1..11 dimension names, used to prefix every gap sentence so a caller can tell at a
# glance which of the 11 a given sentence is about (also doubles as documentation of the numbering
# every other part of this package — questions.py's priority order, compile.py's op derivation —
# depends on).
DIMENSION_NAMES: tuple[str, ...] = (
    "problem/goal", "roles", "stages", "routing", "rework loops", "data model",
    "master data", "visibility matrix", "timing", "personas", "test cases",
)

# Dimensions that are collected and asked about (they still appear in `gaps()`, still drive
# `questions.next_questions`) but never BLOCK a build (`compile.compile_spec` checks
# `blocking_gaps()`, not `gaps()`). Currently just dimension 9 (timing): this engine's proven
# build order (CLAUDE.md) has no step that creates SLA/reminder/batch-job automation at all, so
# refusing to compile over a blank Timing would be gating on data the compiler cannot act on
# anyway. If a future op kind gives the engine that capability, remove 9 from this set rather than
# leaving the gate hollow.
ADVISORY_DIMENSIONS: frozenset[int] = frozenset({9})

# The pseudo-stage name for the workflow's actual entry point (`StartEvent`, position 0 in
# `ProcessDef::Activity` — CLAUDE.md Visibility: "StartEvent is position 0"). It is not a business
# stage (never appears in `Stages.stages`) but IS a legal `VisibilityEntry.stage` value: the very
# first section a user sees must list it as an owner, or the submission form renders empty.
START_STAGE: str = "Start"


# ---- 1. problem / goal -------------------------------------------------------------------------

@dataclass(frozen=True)
class ProblemGoal:
    """Why this app exists at all. `terminal_states` are the names an item's journey can END in
    (e.g. "Completed", "Cancelled") — WHERE it stops moving. `result_values` are the possible
    final outcomes recorded on it (e.g. "Repaired", "Beyond repair") — WHAT got decided. The two
    are related but distinct: a case can reach the SAME terminal state via different results.
    Both `create_process` (as descriptive metadata) and `test_cases` (`expected_result` is
    cross-checked against `result_values`) actually consume this dimension — nothing here is
    collected and then discarded.
    """
    pain: str
    goal: str
    done_definition: str
    terminal_states: tuple[str, ...]
    result_values: tuple[str, ...]


# ---- 2. roles -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class RoleSpec:
    name: str
    is_admin: bool
    members_hint: str | None = None


@dataclass(frozen=True)
class Roles:
    roles: tuple[RoleSpec, ...]


# ---- 3. stages ------------------------------------------------------------------------------

@dataclass(frozen=True)
class StageSpec:
    """One step of a single, strictly sequential chain (see this module's docstring for why
    parallel branches are out of scope). `owner_role` is cross-checked against `Roles` and flows
    into its own `set_assignees` op — a step's assignee is a materially different engine write
    (a `Resource` node) from the `ProcessDef`/`Activity` graph `build_workflow` constructs, so the
    two are kept as separate ops rather than one op silently doing two kinds of write.
    """
    name: str
    owner_role: str
    what_happens: str
    entry_criteria: str
    exit_criteria: str


@dataclass(frozen=True)
class Stages:
    stages: tuple[StageSpec, ...]


# ---- 4. routing -----------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionPoint:
    """A branch point: at `at_stage`, the value of `field_name` decides where the item goes next.
    `route_per_option` pairs each legal option with the ORDERED SEQUENCE of stages that option's
    branch runs through — a plain linear route is just a one-element sequence. Every option in
    `options` must appear exactly once as a `route_per_option` key (compile.py cross-checks this:
    an unrouted option would otherwise silently dead-end the item, and a route naming an option
    that was never declared is just as much a bug), and no sequence may be empty (a route naming
    zero stages is a dead-end compile refuses — see compile.py). A branch is a sequence, not a
    single next stage (P1, #30): this is the shape every later branch ticket builds on. Kept as a
    tuple of (option, tuple-of-stages) pairs, not a dict, per this module's own frozen-collections
    convention.
    """
    at_stage: str
    field_name: str
    options: tuple[str, ...]
    route_per_option: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class Routing:
    points: tuple[DecisionPoint, ...]
    # True = the business owner explicitly confirmed this app has NO branching at all. Lets a
    # genuinely linear process satisfy this dimension without inventing a fake DecisionPoint —
    # `gaps()`/`compile_spec` accept EITHER a non-empty `points` OR this flag, never neither.
    confirmed_none: bool = False


# ---- 5. rework loops ------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopSpec:
    """A backward jump from `from_stage` to `to_stage`, gated on `gate_field`.

    Whether the gate is a Boolean is NOT a field here — a self-declared flag would just be a
    second, disagreeable source of truth next to the field's own real `FieldType` in `DataModel`.
    `compile.py`'s `_check_loop_gate_is_boolean` resolves `gate_field` against `DataModel.fields`
    and requires `FieldType.BOOLEAN` directly, per CLAUDE.md's Gate polarity rule: a loop must
    fail closed on a Boolean field, never an optional Select (a blank Select silently lets an item
    escape rework it needed; an unticked Boolean silently traps it, which is the recoverable
    failure). `compile.py` also requires `to_stage` to come BEFORE `from_stage` in stage order —
    GotoTask is the backward edge node, a loop that points forward or at itself is not a loop.
    """
    from_stage: str
    to_stage: str
    gate_field: str
    max_rounds: int | None = None


@dataclass(frozen=True)
class ReworkLoops:
    loops: tuple[LoopSpec, ...]
    confirmed_none: bool = False  # explicit "no rework loops in this app" — see Routing.confirmed_none


# ---- 6. data model --------------------------------------------------------------------------

@dataclass(frozen=True)
class SectionReq:
    """An explicit, named form section at a stage. A stage may host more than one — a plain
    business field section AND a table's own banner-section (CLAUDE.md Tables: "a Section used
    purely as a banner immediately above the table") both need names distinguishable from the
    stage's own name and from each other, which forcing "section == stage" cannot express.
    """
    name: str
    stage: str
    description: str


@dataclass(frozen=True)
class FieldReq:
    """A desired field. `list_name` only means anything when `type is FieldType.SELECT` — it
    names the MasterData `ListSpec` (dimension 7) that backs the dropdown, cross-checked in
    compile.py against `Routing` literals so a typo'd option can never silently fail to route.

    `section`, when given, must name either a real `SectionReq` at this field's own `stage` or
    the stage's own (implicit, same-named) default section — `None` falls back to that implicit
    default, so a simple one-section-per-stage app never has to name anything. `options` carries
    whatever per-type keys the business decides that this schema has no dedicated field for (e.g.
    Number's `Decimalpoint`, Textarea's `AllowFormatting`, Attachment's `CaptureOnly` — CLAUDE.md
    Node-graph invariants), as (key, value) pairs rather than inventing a field per key.
    """
    name: str
    type: FieldType
    required: bool
    stage: str
    list_name: str | None = None
    section: str | None = None
    options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TableColumnReq:
    name: str
    type: FieldType
    required: bool


@dataclass(frozen=True)
class TableReq:
    """A child table (a nested Model in engine terms, never a field type — CLAUDE.md Tables).
    `max_rows`, when given, becomes the host column's native `MaxRow` cap and must be positive
    (compile.py rejects `<= 0` — a non-positive cap is not a real constraint, it's a typo).
    """
    name: str
    stage: str
    columns: tuple[TableColumnReq, ...]
    max_rows: int | None = None


@dataclass(frozen=True)
class ComputedReq:
    """A value the engine computes with a field event (CLAUDE.md Field events — Kissflow has no
    formula field type). `target_field` and every name in `source_fields` are cross-checked
    against real fields AND table columns (a computed field commonly summarizes a table, e.g.
    "total" from a table's own per-row amounts) — an event wired onto a field that doesn't exist
    is exactly the bug this check exists to catch. `formula_intent` is prose, not a formula
    language, on purpose: this dimension exists to be turned into real JS by whatever builds the
    event, not to invent yet another expression syntax here.

    `trigger` (#12): leave it `None` — the compiler derives the right trigger PER SOURCE FIELD
    from that field's real type via `trigger_for`, because the trigger is a function of the
    source's type, not a free choice (a wrong one writes fine and simply never fires). An
    explicit value is validated against the derived trigger for EVERY source and refused on any
    mismatch — so mixed-trigger-family sources require `None`.
    """
    target_field: str
    source_fields: tuple[str, ...]
    trigger: EventTrigger | None
    formula_intent: str


@dataclass(frozen=True)
class SequenceReq:
    """An auto-numbered item id, e.g. prefix "RPR" + padding "0001" -> RPR-0001, RPR-0002, ..."""
    prefix: str
    padding: str


@dataclass(frozen=True)
class DataModel:
    fields: tuple[FieldReq, ...]
    tables: tuple[TableReq, ...]
    computed: tuple[ComputedReq, ...]
    sections: tuple[SectionReq, ...] = ()
    sequence: SequenceReq | None = None


# ---- 7. master data -------------------------------------------------------------------------

@dataclass(frozen=True)
class ListSpec:
    """A reference list backing one or more Select fields. `values` are read verbatim into any
    Expression literal that compares against this list — CLAUDE.md's "never guess a literal, read
    it" starts here: this is where the real, byte-exact values get recorded, once. Compiles to an
    EXECUTABLE `create_list` op (#13, live-proven 2026-08-12: create + `{"ListItems": [...]}`
    set + `ReferredList` wiring all captured and verified end to end on a real item) — UNLESS
    `personal_data` is set: a list flagged as holding personal data stays HUMAN-MADE in the
    builder UI (PDPA, decision D2/D9), and its op stays human-gated with the values still in the
    plan so nothing is silently dropped.
    """
    name: str
    values: tuple[str, ...]
    owner_role: str
    personal_data: bool = False


@dataclass(frozen=True)
class MasterData:
    lists: tuple[ListSpec, ...]
    confirmed_none: bool = False  # explicit "no reference lists in this app" — see Routing.confirmed_none


# ---- 8. visibility matrix -------------------------------------------------------------------

@dataclass(frozen=True)
class VisibilityEntry:
    """One (section, stage) -> permission cell, optionally narrowed to one `field` within that
    section (`None` = the whole section, the cheaper lever CLAUDE.md prefers when one rule covers
    every field in it; a name = a field-level override, cross-checked against `DataModel.fields`).

    `section` names one of: a Stage's own same-named implicit section, an explicit `SectionReq`,
    or a `TableReq` (its banner+table pairing) — see compile.py's `_section_names`, the single
    place that pool is assembled. `stage` is normally a real Stage name, but MAY also be the
    literal `START_STAGE` ("Start") — the workflow's actual entry point, which is not itself a
    business stage but still needs an owning section, or the submission form renders empty.

    `role` is a CLAIM slot, not a build input: "only this role sees it" is role-scoped
    visibility, which the API cannot express (a Permission node is (column, step), never
    (column, role)). Intake records the claim here verbatim rather than dropping it; compile
    threads it to the doctor op, and `verify.doctor` FAILs it with a stated reason naming the
    `role-scoped-visibility` coverage row (#6, ADR-0004: refuse, never best-effort).
    """
    section: str
    stage: str
    permission: Visibility
    field: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class VisibilityMatrix:
    entries: tuple[VisibilityEntry, ...]


# ---- 9. timing --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Timing:
    """ADVISORY (see `ADVISORY_DIMENSIONS`): collected and asked about, but an empty Timing never
    blocks `compile_spec` — this engine's proven build order has no step that creates SLA/
    reminder/batch-job automation, so refusing to build over missing timing notes would gate on
    data the compiler has no way to act on. Kept as a real dimension anyway (not deleted) because
    it is still useful context for whoever sets up that automation by hand, out of band.
    """
    sla_notes: str
    batch_days: tuple[str, ...]
    reminders: tuple[str, ...]


# ---- 10. personas ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WidgetIntent:
    """One widget on a page, identified by its `Script.web` slug (`kfforge.pages.WIDGET_SLUGS` —
    compile.py rejects any slug not in that catalog). `config` supplies whatever binding values
    that widget's shape needs (e.g. `flow_type`/`flow_id`/`view_id` for a `view/*` widget) as
    (key, value) string pairs; `kfforge.pages.WIDGET_REQUIRED_CONFIG` names, per slug, which keys
    are load-bearing enough that compile.py refuses to proceed without them — leaving one unset
    does not fall back to a sane default, it silently binds the published page to a placeholder
    (CLAUDE.md THE RULE: publishes clean, renders broken). `row_fields` is `repeater`'s own extra
    required config, kept as its own field rather than jammed into `config` because it's a LIST of
    field names, the one binding value across the whole widget palette that isn't a single string.
    """
    slug: str
    config: tuple[tuple[str, str], ...] = ()
    row_fields: tuple[str, ...] = ()


class ClickActionKind(StrEnum):
    """The two on-click arms proven live (CLAUDE.md Pages, shapes/event_mapping.json's two
    `EventMapping.Type` values). `OPEN_POPUP` is the scriptless arm — its Property is
    `Type:"Popup"` naming the target popup directly. `JS_ACTION` is arbitrary JS in a Code-typed
    Property. No third arm has been captured, so this enum is closed at two.
    """
    OPEN_POPUP = "OpenPopup"  # scriptless: opens a popup by name
    JS_ACTION = "JSAction"    # a raw JS body run on click


@dataclass(frozen=True)
class OnClickAction:
    """One on-click wiring on a page: `action` names the button/action (a string that appears in a
    `PersonaView.actions`) whose click this describes, and `kind` picks which of the two proven
    arms fires. Exactly one arm's payload is populated, the other stays `None`:

    - `kind is OPEN_POPUP` -> `target_popup` names a `PopupIntent` on the SAME `PageIntent`
      (`script` is `None`).
    - `kind is JS_ACTION`  -> `script` is the raw JS body (`target_popup` is `None`).

    This is spec VOCABULARY only (#39 T1): `compile_spec` ignores it at this stage — turning it
    into a real `EventMapping`/`Property` node pair is T2. Two optional payload fields under one
    discriminant (rather than an `A | B` union of two dataclasses) is deliberate: `serde` only
    reflects `T | None` unions, so this shape round-trips with zero serde code.
    """
    action: str
    kind: ClickActionKind
    target_popup: str | None = None
    script: str | None = None


@dataclass(frozen=True)
class PopupIntent:
    """A popup subtree hosted on a page (CLAUDE.md Pages: "Popup — its own Container subtree").
    Mirrors `PageIntent`'s content half (a name plus hosted widgets); an `OnClickAction` with
    `kind is OPEN_POPUP` targets one of these by `name`.
    """
    name: str
    widgets: tuple[WidgetIntent, ...]


@dataclass(frozen=True)
class DesignNode:
    """One node of a page's DESIGN tree — the beautiful-page dimension (page.design.md). A page is
    a tree of styled `Container`s wrapping the functional widgets, not a flat widget list; this
    dataclass is how a spec EXPRESSES that tree so it survives the pipeline instead of collapsing
    to bare label+form (the exact gap this dimension closes).

    Exactly two kinds, closed by convention (compile refuses any other):

    - `kind == "container"`: a layout box. `children` holds its sub-tree (more containers and/or
      widgets); `widget` MUST be None. `style` styles the box itself (background, padding, gap,
      radius, border — the `Container.*` keys in page.design.md).
    - `kind == "widget"`: a leaf functional widget. `widget` names it (a `WidgetIntent`, same slug/
      config catalog as `PageIntent.widgets`); `children` MUST be empty. `style` styles the
      widget's own host container (`Label.*`/`Icon.*`/`Container.*` keys).

    `style` is (Style.Value-key, value) STRING pairs — a tuple of pairs, this schema's frozen-
    collection convention (never a dict). The value string carries one of the two page colour/value
    shapes page.design.md documents, disambiguated by a `token:` prefix so the whole thing stays a
    plain serde-round-trippable string:

    - `"token:Color.White"` / `"token:Font.Weight.SemiBold"` -> `{"ref": "Color.White"}` (a design-
      token ref — the dominant colour convention on a page, and the ONLY form form-sections accept).
    - anything else (`"#2E6B3B"`, `"16px"`, `"column"`, `"999px"`) -> `{"value": "<str>"}` — raw hex
      for a colour, a raw CSS string for a dimension (both proven rendering on a page).

    The tree round-trips through serde with zero special-casing (it is dataclasses + tuples + a
    `WidgetIntent | None` union, all shapes serde already reflects) and is compiled by
    `compile._design_to_wire` into the `build_page` op, where `pages.build_design` builds it into
    real nested `Container`/`Component`/`Style` nodes.
    """
    kind: str
    name: str = ""
    style: tuple[tuple[str, str], ...] = ()
    children: tuple["DesignNode", ...] = ()
    widget: WidgetIntent | None = None


@dataclass(frozen=True)
class PageIntent:
    """A page's content (`widgets`) plus its BEHAVIOR half (`popups` + `on_click`), the schema
    side of ADR-0005 ("the governed plan carries content AND behavior"). Both behavior fields
    default empty, so a plain content-only page still constructs as `PageIntent(name, widgets)`.

    `design` (optional, page.design.md) is the BEAUTIFUL-page half: a styled `DesignNode` container
    tree that carries the real layout, colours, and nesting a rich mockup has — the thing the flat
    `widgets` list cannot express (it only holds `{slug, config}` per widget, no containers, no
    colours). It is purely ADDITIVE and backward-compatible: a page with `design=None` compiles and
    builds EXACTLY as before (flat widgets into the Body). When a `design` IS present, the build
    produces the nested styled tree instead of the bare skeleton — see `compile._op_build_page` and
    `pages.build_design`.
    """
    name: str
    widgets: tuple[WidgetIntent, ...]
    popups: tuple[PopupIntent, ...] = ()
    on_click: tuple[OnClickAction, ...] = ()
    design: DesignNode | None = None


@dataclass(frozen=True)
class PersonaView:
    """What one role sees when they open the app. `role` is cross-checked against `Roles`. The
    SAME `PageIntent.name` can legitimately appear under more than one role's `pages` (a shared
    dashboard) — compile.py deduplicates by page name when deriving `create_page`/`build_page`
    ops (aggregating every referencing view's `kpis`/`actions` into that one `build_page` op, so
    neither is silently dropped just because two roles share a page), and instead emits one
    `set_navigation` op per (role, page) pair so the shared page still gets bound into every
    role's own navigation.
    """
    role: str
    pages: tuple[PageIntent, ...]
    kpis: tuple[str, ...]
    actions: tuple[str, ...]


@dataclass(frozen=True)
class Personas:
    views: tuple[PersonaView, ...]


# ---- 11. test cases -------------------------------------------------------------------------

@dataclass(frozen=True)
class StepFill:
    """Values filled during ONE visit to a stage. A looped case (`expected_path` naming the same
    stage twice — once before the rework loop, once after) needs one `StepFill` per VISIT, each
    free to hold different values. That is what lets a rework-loop case walk tick a Boolean gate
    `"false"` on the first visit and `"true"` on the second — a single flat dict keyed by field
    name could hold only one value per field for the WHOLE case, and could never express that.
    `values` pairs a field name with its fill value as a string, same tuple-of-pairs convention as
    `DecisionPoint.route_per_option`.
    """
    stage: str
    values: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CaseWalk:
    """A concrete end-to-end walk: fill these values (per stage visited), expect the item to
    visit exactly these stages in order, expect this final result. This is the ONLY dimension
    that proves a build actually works rather than merely publishing clean (CLAUDE.md THE RULE) —
    it compiles to `simulate_case`, the engine's real create->fill->submit->gates->terminal walk.
    Every field name in `fills` is cross-checked against real fields, every Select value against
    its list, and `expected_result` against `ProblemGoal.result_values`.
    """
    __test__ = False  # tell pytest this is dimension 11's container, not a test class to collect

    name: str
    fills: tuple[StepFill, ...]
    expected_path: tuple[str, ...]
    expected_result: str


@dataclass(frozen=True)
class TestCases:
    __test__ = False  # tell pytest this is dimension 11's container, not a test class to collect

    cases: tuple[CaseWalk, ...]


# ---- top-level spec -------------------------------------------------------------------------

@dataclass(frozen=True)
class AppSpec:
    app_name: str
    problem_goal: ProblemGoal
    roles: Roles
    stages: Stages
    routing: Routing
    rework_loops: ReworkLoops
    data_model: DataModel
    master_data: MasterData
    visibility: VisibilityMatrix
    timing: Timing
    personas: Personas
    test_cases: TestCases
    approved: bool = False

    def gaps(self) -> tuple[str, ...]:
        """One human sentence per dimension that is empty or insufficient, dimension 1 first —
        the FULL completeness picture across all 11 dimensions, including advisory ones. This is
        what `questions.next_questions` reads, so a dimension marked advisory is still asked
        about; it just never blocks a build (see `blocking_gaps`).

        Sentences are English, not Thai: they're this module's own audit trail (raised into
        ValueErrors, logged, read by developers), never text shown directly to the business owner
        — that's questions.py's job, in Thai, grounded in this same gap set via `_gap_dimensions`.
        """
        return tuple(_gap_dimensions(self).values())

    def blocking_gaps(self) -> tuple[str, ...]:
        """Like `gaps()` but excludes `ADVISORY_DIMENSIONS`. `compile.compile_spec` checks THIS,
        not `gaps()`, for its refusal — a spec can be approved and built while an advisory
        dimension (currently just timing) is still blank; it keeps being asked about, it just
        never blocks. Do not gate a build on data the engine has no proven way to act on.
        """
        return tuple(s for n, s in _gap_dimensions(self).items() if n not in ADVISORY_DIMENSIONS)


def blank_spec() -> AppSpec:
    """An `AppSpec` with every dimension present but empty -- the correct starting point for a
    Q&A session that has not collected any answers yet (`gaps()` returns all 11 dimensions,
    `app_name` is `""`, `approved` is `False`). Added for `kfforge.server`'s stateless
    `forge_intake_questions`/`forge_update_spec` MCP tools, which need a real starting `AppSpec`
    when a caller passes no spec at all (there is no session to remember one from between calls) --
    every field below is instantiated with its own container's empty default, mirroring the
    synthetic `_EMPTY_SPEC` fixture `tests/test_intake.py` already builds by hand for the same
    reason, now promoted to a real, reusable function instead of a test-only constant.
    """
    return AppSpec(
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


def _gap_dimensions(spec: AppSpec) -> dict[int, str]:
    """Single source of truth for "is dimension N insufficient", keyed 1..11 in order.

    Shared by `AppSpec.gaps()`/`AppSpec.blocking_gaps()` and `questions.next_questions` so all
    three can never drift apart — a dimension that stops being a gap here immediately stops being
    asked about there too, with no second place to remember to update. Every one of the 11
    dimensions gets exactly one check below, in order, so no dimension can be silently forgotten
    (this function itself is the output-invariant audit `gaps()` promises).
    """
    gaps: dict[int, str] = {}

    def flag(n: int, detail: str) -> None:
        gaps[n] = f"{n}. {DIMENSION_NAMES[n - 1]}: {detail}"

    pg = spec.problem_goal
    if not (pg.pain and pg.goal and pg.done_definition and pg.terminal_states and pg.result_values):
        flag(1, "need the pain, the goal, a done-definition, at least one terminal state, and "
                "at least one result value")

    if not spec.roles.roles:
        flag(2, "need at least one role who touches this app")

    if not spec.stages.stages:
        flag(3, "need at least one stage an item passes through")

    if not (spec.routing.points or spec.routing.confirmed_none):
        flag(4, "need at least one decision point where the path branches, OR an explicit "
                "confirmation there is none (Routing.confirmed_none=True)")

    if not (spec.rework_loops.loops or spec.rework_loops.confirmed_none):
        flag(5, "need at least one stage-to-stage rework loop, OR an explicit confirmation "
                "there is none (ReworkLoops.confirmed_none=True)")

    if not spec.data_model.fields:
        flag(6, "need at least one field to capture")

    if not (spec.master_data.lists or spec.master_data.confirmed_none):
        flag(7, "need at least one reference list, OR an explicit confirmation there is none "
                "(MasterData.confirmed_none=True)")

    if not spec.visibility.entries:
        flag(8, "need at least one section/stage permission entry")

    if not spec.timing.sla_notes:
        flag(9, "need at least the SLA notes (ADVISORY: an empty Timing does not block "
                "compile_spec — see AppSpec.blocking_gaps and ADVISORY_DIMENSIONS)")

    if not spec.personas.views:
        flag(10, "need at least one role's page/dashboard intent")

    if not spec.test_cases.cases:
        flag(11, "need at least one end-to-end case walk")

    return gaps
