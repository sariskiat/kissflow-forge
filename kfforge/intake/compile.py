"""kfforge.intake.compile — turns an APPROVED, COMPLETE AppSpec into a BuildPlan: the ordered
list of engine operations that actually build the app.

Pure and offline: no network, no Kissflow calls. Every `Op` is derivable from the spec alone —
this module never invents a value the business owner didn't supply. Three rules from CLAUDE.md
are enforced structurally rather than left to whoever executes the plan later:

- **Never synthesize a style token.** `set_styles` ops name WHICH stage's section needs a look,
  never a color or token value — CLAUDE.md Write path: a bogus token PUTs 200 and fails silently
  at render, so a real token name may only ever come from reading the builder's own dropdown.
- **Never synthesize a ReferredList wiring.** `create_list` ops carry the real list VALUES (so
  they are never silently lost) but their `why` says plainly that the write itself is human-gated
  — the wiring shape of a NEW ReferredList has never been captured, so this compiler does not
  pretend it can automate that write.
- **Gate polarity is checked before a plan can exist at all.** `_check_loop_gate_is_boolean`
  resolves the gate field against `DataModel.fields` and raises rather than trusting a
  self-declared flag; `_check_loop_stages` additionally requires the jump to be backward.

`compile_spec` refuses twice, in order: first on `not spec.approved` (a human must have signed off
— building blind is how sessions get lost, CLAUDE.md THE RULE), then on `spec.blocking_gaps()`
being non-empty (an incomplete spec cannot derive a complete plan — advisory dimensions excepted,
see schema.ADVISORY_DIMENSIONS). Only past both does it run every cross-check below and derive ops.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Iterable

from .. import coverage
from ..pages import WIDGET_REQUIRED_CONFIG, WIDGET_SLUGS
from ..types import FieldType, Visibility
from .schema import (
    START_STAGE,
    AppSpec,
    EventTrigger,
    FieldReq,
    PageIntent,
    TableReq,
    WidgetIntent,
)

# The proven build order (CLAUDE.md "Build order"), most foundational first. This is the ONE
# place that ordering is encoded — `compile_spec` walks it to assemble `BuildPlan.ops`, so an op
# kind's position here is authoritative, not just documentation. Two kinds beyond CLAUDE.md's own
# 13-step list were added in review: `create_list` (master-data values were being collected and
# then silently dropped — CLAUDE.md's own "Write path" step still comes before the fields that
# reference it) and `set_assignees` (CLAUDE.md's OWN build order actually has "Assignees" as a
# distinct step 6, between Workflow and Goto gates — the original cut of this file collapsed it
# into build_workflow's args and lost owner_role entirely; splitting it back out matches both
# CLAUDE.md and `kfforge.graph.build_workflow`'s own separate `Resource`-node write).
OP_ORDER: tuple[str, ...] = (
    "create_process", "member_batch", "create_list", "apply_fields", "add_table",
    "build_workflow", "set_assignees", "add_goto_gate", "set_branch_conditions",
    "set_visibility", "set_events", "set_styles", "publish", "doctor", "create_page",
    "build_page", "set_navigation", "simulate_case",
)


@dataclass(frozen=True)
class Op:
    kind: str
    args: dict[str, Any]
    why: str


@dataclass(frozen=True)
class BuildPlan:
    ops: tuple[Op, ...]

    def summary(self) -> dict[str, int]:
        """Op count per kind — always reconciles with `ops` because it's computed FROM `ops`,
        never tracked separately (the output-invariant audit this module owes its own caller)."""
        counts: dict[str, int] = {}
        for op in self.ops:
            counts[op.kind] = counts.get(op.kind, 0) + 1
        return counts


# ---- cross-checks -----------------------------------------------------------------------------
# Every check below raises ValueError naming the offending value — never silently drops, never
# "fixes," a bad spec. All run in `compile_spec`, in the order listed in `_CROSS_CHECKS`, after
# `approved`/`blocking_gaps()` have already passed — so every dimension referenced below is
# guaranteed to have SOME content by the time these run (an empty-but-`confirmed_none` dimension
# is still "guaranteed," it's just guaranteed empty, which every loop below handles for free by
# simply not iterating).

def _check_stage_owner_roles(spec: AppSpec) -> None:
    """A stage owner role not in Roles."""
    role_names = {r.name for r in spec.roles.roles}
    for stage in spec.stages.stages:
        if stage.owner_role not in role_names:
            raise ValueError(
                f"stage {stage.name!r} is owned by role {stage.owner_role!r}, which is not in "
                f"Roles {sorted(role_names)}"
            )


def _check_sections(spec: AppSpec) -> None:
    """A SectionReq naming a stage that doesn't exist."""
    stage_names = {s.name for s in spec.stages.stages}
    for sec in spec.data_model.sections:
        if sec.stage not in stage_names:
            raise ValueError(
                f"section {sec.name!r} names unknown stage {sec.stage!r}, not in {sorted(stage_names)}"
            )


def _check_fields(spec: AppSpec) -> None:
    """A field naming an unknown stage or section, a section that belongs to a DIFFERENT stage
    than the field's own, or a `type` that isn't a real `FieldType` member.

    The stage check matters beyond mere validation: `_op_apply_fields` groups fields BY stage, so
    a field naming an unknown one would otherwise be silently dropped from the plan (grouped into
    a bucket nothing ever emits an op for) rather than raising — exactly the silent-loss failure
    mode this package exists to prevent.

    F5: the stage-mismatch guard covers BOTH kinds of section a field can name — an explicit
    `SectionReq` (checked against ITS OWN `.stage`) and a bare STAGE name used as its own implicit
    section (checked directly against that name). The two used to be asymmetric: only the
    `SectionReq` branch compared stages, so a field at stage "Bake" naming section="Take Order"
    (a real STAGE name, just not this field's own) escaped entirely — `owner` was `None` for a
    stage-named section, so the old guard's `owner is not None` condition never even looked.
    """
    stage_names = {s.name for s in spec.stages.stages}
    sections_by_name = {sec.name: sec for sec in spec.data_model.sections}
    section_names = stage_names | set(sections_by_name)
    for f in spec.data_model.fields:
        if not isinstance(f.type, FieldType):
            # ValueError, not TypeError (ruff TRY004): every other check in this module raises
            # ValueError for "this value is not what the spec requires" — a raw string standing
            # in for an enum member is that SAME class of problem, not a Python-level type error.
            raise ValueError(  # noqa: TRY004
                f"field {f.name!r} has type {f.type!r}, not a FieldType enum member"
            )
        if f.stage not in stage_names:
            raise ValueError(
                f"field {f.name!r} names unknown stage {f.stage!r}, not in {sorted(stage_names)}"
            )
        if f.section is None:
            continue
        if f.section not in section_names:
            raise ValueError(
                f"field {f.name!r} names unknown section {f.section!r}, not in {sorted(section_names)}"
            )
        owner = sections_by_name.get(f.section)
        if owner is not None:
            if owner.stage != f.stage:
                raise ValueError(
                    f"field {f.name!r} is at stage {f.stage!r} but names section {f.section!r}, "
                    f"which belongs to stage {owner.stage!r}"
                )
        elif f.section in stage_names and f.section != f.stage:
            raise ValueError(
                f"field {f.name!r} is at stage {f.stage!r} but names section {f.section!r}, "
                f"which is the implicit section of a DIFFERENT stage"
            )


def _check_select_fields_have_list(spec: AppSpec) -> None:
    """F3: a Select field with no `list_name` (an empty dropdown) or one naming a list that isn't
    in `MasterData.lists` both used to compile clean — and BOTH silently disabled every guard
    downstream that depends on `list_name` resolving (`_check_routing_literals`'s and
    `_check_test_cases`'s Select-value checks each treat an unresolved list as "zero legal
    values," which is loud for a wrong LITERAL but was never actually reachable for a field whose
    `list_name` itself was the problem, since neither routing nor a test case necessarily touches
    every field). Catching it here, once, at the field's own declaration, closes that gap for
    every downstream consumer at once rather than requiring each to rediscover it independently.
    """
    list_names = {l.name for l in spec.master_data.lists}
    for f in spec.data_model.fields:
        if f.type != FieldType.SELECT:
            continue
        if f.list_name is None:
            raise ValueError(
                f"field {f.name!r} is Select but names no list_name — it would render as an "
                f"empty dropdown with no options"
            )
        if f.list_name not in list_names:
            raise ValueError(
                f"field {f.name!r} names list_name {f.list_name!r}, which is not in "
                f"MasterData.lists {sorted(list_names)}"
            )


def _check_tables(spec: AppSpec) -> None:
    """A table naming an unknown stage, a non-positive `max_rows`, or a column whose `type`
    isn't a real `FieldType` member."""
    stage_names = {s.name for s in spec.stages.stages}
    for t in spec.data_model.tables:
        if t.stage not in stage_names:
            raise ValueError(
                f"table {t.name!r} names unknown stage {t.stage!r}, not in {sorted(stage_names)}"
            )
        if t.max_rows is not None and t.max_rows <= 0:
            raise ValueError(f"table {t.name!r} has max_rows={t.max_rows!r}, must be > 0")
        for col in t.columns:
            if not isinstance(col.type, FieldType):
                raise ValueError(  # noqa: TRY004 — see _check_fields for why ValueError here
                    f"table {t.name!r} column {col.name!r} has type {col.type!r}, not a "
                    f"FieldType enum member"
                )


def _check_computed_fields(spec: AppSpec) -> None:
    """A computed field's target or source naming something that isn't a real field OR table
    column, or a `trigger` that isn't a real EventTrigger member."""
    known = {f.name for f in spec.data_model.fields}
    for t in spec.data_model.tables:
        known |= {c.name for c in t.columns}
    for c in spec.data_model.computed:
        if not isinstance(c.trigger, EventTrigger):
            raise ValueError(  # noqa: TRY004 — see _check_fields for why ValueError here
                f"computed field {c.target_field!r} has trigger {c.trigger!r}, not an "
                f"EventTrigger enum member"
            )
        if c.target_field not in known:
            raise ValueError(
                f"computed field target {c.target_field!r} is not a known field or table "
                f"column ({sorted(known)})"
            )
        for src in c.source_fields:
            if src not in known:
                raise ValueError(
                    f"computed field {c.target_field!r} source {src!r} is not a known field or "
                    f"table column ({sorted(known)})"
                )


def _check_routing_field_and_options(spec: AppSpec) -> None:
    """F4: `DecisionPoint.field_name` must name a real field, checked INDEPENDENTLY of iterating
    `options` — the other routing checks only ever visit `field_name` indirectly, inside a loop
    over `options`/`route_per_option`, so a `DecisionPoint` with an empty `options` tuple used to
    skip field validation entirely and compile a branch on a phantom field. Also rejects an empty
    `options` tuple outright: a decision point that names zero options can never actually branch,
    which is a structural defect on its own, not just a validation blind spot.
    """
    fields_by_name = {f.name: f for f in spec.data_model.fields}
    for point in spec.routing.points:
        if point.field_name not in fields_by_name:
            raise ValueError(
                f"routing at {point.at_stage!r} field_name {point.field_name!r} is not a known "
                f"field, not in {sorted(fields_by_name)}"
            )
        if not point.options:
            raise ValueError(
                f"routing at {point.at_stage!r} on {point.field_name!r} declares zero options — "
                f"a decision point must offer at least one option to branch on"
            )


def _check_no_split_nested_in_branch(spec: AppSpec) -> None:
    """D3 (#29 spec decisions): S2 (#33) generalises to N SEQUENTIAL splits (split -> rejoin ->
    later split -> rejoin) — but a split NESTED inside another split's own branch is a different
    shape entirely, with no live capture, so it is refused outright rather than silently built
    (THE RULE). `branch_stage_owner` maps every stage that appears in ANY point's branch sequences
    to the `at_stage` of the point that FIRST claims it (first owner wins — a stage claimed by two
    different splits' branches is not what this check is for; see `_check_no_duplicate_branch_names`
    for the branch-NAME collision that shape would actually cause downstream). A point whose own
    `at_stage` is already owned by a DIFFERENT point's `at_stage` is a split sitting inside that
    other split's branch — nested, and refused.
    """
    branch_stage_owner: dict[str, str] = {}
    for point in spec.routing.points:
        for _option, seq in point.route_per_option:
            for stage in seq:
                branch_stage_owner.setdefault(stage, point.at_stage)
    for point in spec.routing.points:
        owner = branch_stage_owner.get(point.at_stage)
        if owner is not None and owner != point.at_stage:
            row = coverage.get("nested-split")
            raise ValueError(
                f"split at {point.at_stage!r} sits inside the branch of the split at {owner!r} "
                f"— a split nested inside a branch (coverage row {row.key!r}: {row.reason}). "
                f"Refused rather than built."
            )


def _check_no_duplicate_branch_names(spec: AppSpec) -> None:
    """D3 (#29 spec decisions): a branch id is `hash(model, kind, index, name)` — two branches of
    the SAME name across two DIFFERENT splits collide on that id and silently overwrite one
    another, and make the branch-local `GotoTask` derivation (which branch a rework loop's Goto
    belongs to) ambiguous. Mirrors `kfforge.graph.build_workflow`'s own runtime guard, but refuses
    at COMPILE so a `BuildPlan` never claims a shape that would overwrite itself the moment it was
    built. Within a single point, `options` are already distinct (schema-level) — this check is
    specifically CROSS-point: the SAME option value declared by two different splits.
    """
    owner_by_value: dict[str, str] = {}
    for point in spec.routing.points:
        for option in point.options:
            prior = owner_by_value.get(option)
            if prior is not None and prior != point.at_stage:
                raise ValueError(
                    f"branch name {option!r} is declared by both the split at {prior!r} and the "
                    f"split at {point.at_stage!r} — a branch id is a hash of (model, kind, index, "
                    f"name), so two branches sharing a name produce the SAME id and silently "
                    f"overwrite each other, and the branch-local GotoTask derivation becomes "
                    f"ambiguous. Give each split's branches distinct names."
                )
            owner_by_value.setdefault(option, point.at_stage)


def _stage_branch_owner(spec: AppSpec) -> dict[str, str]:
    """stage name -> the branch (option) name whose route sequence contains it, for branch stages
    only (a spine stage is simply absent). Safe to build with `setdefault` — a stage owned by two
    branches is refused first by `_check_no_duplicate_step_across_branches`, so every stage present
    here has exactly one owner by the time any op-builder or the cross-branch check reads this."""
    owner: dict[str, str] = {}
    for point in spec.routing.points:
        for option, seq in point.route_per_option:
            for stage in seq:
                owner.setdefault(stage, option)
    return owner


def _check_no_duplicate_step_across_branches(spec: AppSpec) -> None:
    """D3/D7 (#29 spec decisions): S3 (#34). A rework loop's branch is DERIVED from its step names
    (a loop names from_stage/to_stage; which branch it sits in is read off those). If one step name
    appears in TWO different branches, that derivation is a coin flip — and the branch id itself
    (a hash of (model, kind, index, name)) collides. Refused at compile, naming the
    `duplicate-branch-step` coverage row, so the goto is placed explicitly rather than mis-derived.
    Distinct from `_check_no_duplicate_branch_names` (the branch NAME/option colliding across
    splits); this is a step INSIDE two branches' sequences."""
    owner: dict[str, str] = {}
    for point in spec.routing.points:
        for option, seq in point.route_per_option:
            for stage in seq:
                prior = owner.get(stage)
                if prior is not None and prior != option:
                    row = coverage.get("duplicate-branch-step")
                    raise ValueError(
                        f"step {stage!r} appears in branch {prior!r} and branch {option!r} — the "
                        f"same step name in two different branches (coverage row {row.key!r}: "
                        f"{row.reason}). Give each branch's steps distinct names."
                    )
                owner.setdefault(stage, option)


def _check_loop_not_cross_branch(spec: AppSpec) -> None:
    """D3 (#29): S3 (#34). A rework loop must be branch-LOCAL — jump back to an earlier step of its
    OWN branch, never from one branch into another (CLAUDE.md: verify.doctor rule 2b already flags
    a GotoTask whose target sits in a different ProcessDef; a cross-branch jump has no captured
    shape, THE RULE). A loop with one endpoint on the spine and the other in a branch is NOT
    cross-branch — that is the common spine->branch rework shape and stays allowed; only two
    DIFFERENT real branches are refused, naming the `cross-branch-jump` coverage row."""
    owner = _stage_branch_owner(spec)
    for loop in spec.rework_loops.loops:
        from_branch = owner.get(loop.from_stage)
        to_branch = owner.get(loop.to_stage)
        if from_branch is not None and to_branch is not None and from_branch != to_branch:
            row = coverage.get("cross-branch-jump")
            raise ValueError(
                f"rework loop {loop.from_stage!r} -> {loop.to_stage!r} jumps from branch "
                f"{from_branch!r} into branch {to_branch!r} — a jump from one branch into another "
                f"(coverage row {row.key!r}: {row.reason}). A loop must stay within its own branch."
            )


def _check_routing_stages(spec: AppSpec) -> None:
    """A DecisionPoint's at_stage, or any stage in one of its route SEQUENCES, naming an unknown
    stage — a branch is an ordered sequence of stages now (P1), so every stage in the sequence is
    checked, not just a single target. An EMPTY sequence is refused outright: it names no stage at
    all, a dead-end the old single-stage shape could never express."""
    stage_names = {s.name for s in spec.stages.stages}
    for point in spec.routing.points:
        if point.at_stage not in stage_names:
            raise ValueError(
                f"routing at_stage {point.at_stage!r} is not a known stage, not in {sorted(stage_names)}"
            )
        for option, targets in point.route_per_option:
            if not targets:
                raise ValueError(
                    f"routing at {point.at_stage!r}: option {option!r} routes to an empty sequence "
                    f"— a route must name at least one stage"
                )
            for target in targets:
                if target not in stage_names:
                    raise ValueError(
                        f"routing at {point.at_stage!r}: option {option!r} routes to unknown stage "
                        f"{target!r}, not in {sorted(stage_names)}"
                    )


def _check_routing_complete(spec: AppSpec) -> None:
    """route_per_option must cover EXACTLY the declared options — an unrouted option would
    otherwise silently dead-end the item, and a route naming an option that was never declared is
    just as much a bug."""
    for point in spec.routing.points:
        routed = {opt for opt, _ in point.route_per_option}
        declared = set(point.options)
        if routed != declared:
            raise ValueError(
                f"routing at {point.at_stage!r} on {point.field_name!r}: routed options "
                f"{sorted(routed)} != declared options {sorted(declared)} — every option must "
                f"route somewhere, and no route may name an option that was never declared"
            )


def _check_routing_literals(spec: AppSpec) -> None:
    """A routing literal not present in the named list's values (CLAUDE.md Expressions: "never
    guess a literal — read it"). Resolves `DecisionPoint.field_name` to its `FieldReq`, then that
    field's `list_name` to a `MasterData.ListSpec`; an option compared against a field with no
    resolvable list has an empty values set, so it fails this SAME check rather than being
    silently skipped — an unresolvable field/list name is exactly as fatal as a wrong literal.
    """
    fields_by_name = {f.name: f for f in spec.data_model.fields}
    lists_by_name = {l.name: l for l in spec.master_data.lists}
    for point in spec.routing.points:
        field = fields_by_name.get(point.field_name)
        list_name = field.list_name if field is not None else None
        values = lists_by_name[list_name].values if list_name in lists_by_name else ()
        for option in point.options:
            if option not in values:
                raise ValueError(
                    f"routing at stage {point.at_stage!r} on field {point.field_name!r} tests "
                    f"option {option!r}, which is not a value of list {list_name!r}: {values}"
                )


def _check_all_deciding_values_claimed(spec: AppSpec) -> None:
    """AC3: a real value of the deciding field claimed by no branch (CLAUDE.md Conditional
    routing: "Fail OPEN, not closed — a value matching no branch condition SKIPS THE WHOLE
    PARALLEL and the item completes with no work done, silently"). `_check_routing_literals`
    already refuses a declared `option` that ISN'T a real list value; this check refuses the
    opposite gap — a real list value that no declared `option` claims — measured against the
    field's FULL declared option set, not just what the spec happened to enumerate.

    Only a Select field with a resolvable `list_name` HAS a full declared option set to measure
    against; a Text-typed deciding field is skipped outright (`continue`), never refused here —
    CLAUDE.md notes `build_branch_condition` accepts a Text deciding field, and there is no list
    to be incomplete against. S2 (#33) generalises to N sequential splits, so this loop runs once
    per `DecisionPoint` in `spec.routing.points`, same as every sibling routing check.
    """
    fields_by_name = {f.name: f for f in spec.data_model.fields}
    lists_by_name = {l.name: l for l in spec.master_data.lists}
    for point in spec.routing.points:
        field = fields_by_name.get(point.field_name)
        if field is None or field.type != FieldType.SELECT:
            continue
        list_spec = lists_by_name.get(field.list_name) if field.list_name is not None else None
        if list_spec is None:
            continue
        declared = tuple(list_spec.values)
        claimed = set(point.options)
        unclaimed = [v for v in declared if v not in claimed]
        if unclaimed:
            row = coverage.get("unclaimed-value")
            raise ValueError(
                f"routing at {point.at_stage!r} on field {point.field_name!r}: value(s) "
                f"{sorted(unclaimed)} of list {field.list_name!r} are claimed by no branch "
                f"(coverage row {row.key!r}) — at runtime an item with such a value would "
                f"silently skip the whole split and complete with no work done (Fail-Open, "
                f"ADR-0002 D8). Refused at compile; model an intentional fall-through as an "
                f"explicit branch claiming that value."
            )


def _check_loop_stages(spec: AppSpec) -> None:
    """A loop's from_stage/to_stage naming an unknown stage, or a jump that isn't backward.
    GotoTask is the backward edge node (CLAUDE.md Workflow) — a "loop" that points forward or at
    itself is not a loop at all."""
    stage_order = [s.name for s in spec.stages.stages]
    index = {name: i for i, name in enumerate(stage_order)}
    for loop in spec.rework_loops.loops:
        if loop.from_stage not in index:
            raise ValueError(
                f"rework loop from_stage {loop.from_stage!r} is not a known stage, not in {stage_order}"
            )
        if loop.to_stage not in index:
            raise ValueError(
                f"rework loop to_stage {loop.to_stage!r} is not a known stage, not in {stage_order}"
            )
        if index[loop.to_stage] >= index[loop.from_stage]:
            raise ValueError(
                f"rework loop {loop.from_stage!r} -> {loop.to_stage!r} is not backward — "
                f"to_stage must come BEFORE from_stage in stage order {stage_order}; GotoTask is "
                f"the backward edge node, a loop cannot jump forward or to itself"
            )


def _check_loop_gate_is_boolean(spec: AppSpec) -> None:
    """A loop gate field that is not Boolean (CLAUDE.md Gate polarity: fail closed, never gate a
    loop on an optional Select). Resolves `gate_field` against `DataModel.fields` directly —
    there is no self-declared flag to trust instead."""
    fields_by_name = {f.name: f for f in spec.data_model.fields}
    for loop in spec.rework_loops.loops:
        field = fields_by_name.get(loop.gate_field)
        if field is None:
            raise ValueError(
                f"rework loop {loop.from_stage!r} -> {loop.to_stage!r} gates on "
                f"{loop.gate_field!r}, which is not a known field"
            )
        if field.type != FieldType.BOOLEAN:
            # F15: .value, not the bare enum (whose default repr is "<FieldType.SELECT:
            # 'Select'>") — every sibling message in this module shows the plain wire value.
            raise ValueError(
                f"rework loop {loop.from_stage!r} -> {loop.to_stage!r} gates on "
                f"{loop.gate_field!r}, Type {field.type.value!r} — a loop must fail closed on a "
                f"Boolean field, never an optional Select"
            )


def _section_names(spec: AppSpec) -> set[str]:
    """Every name a `VisibilityEntry.section` may legally use.

    A section is always one of: a Stage's own same-named implicit form section, an explicit
    `SectionReq`, or a `TableReq` (its banner+table pairing — CLAUDE.md Tables: "a table host
    cannot live inside a Section... a Section used purely as a banner immediately above the
    table"). Assembled fresh from the spec each time rather than tracked as a fourth, driftable
    list.
    """
    return ({s.name for s in spec.stages.stages}
            | {sec.name for sec in spec.data_model.sections}
            | {t.name for t in spec.data_model.tables})


def _check_visibility_entries(spec: AppSpec) -> None:
    """A visibility entry naming an unknown stage/section/field, or carrying a `permission` that
    isn't a real Visibility member (a raw string would otherwise die as an unnamed AttributeError
    deep inside `_op_set_visibility`, not here where the offending section/stage/value is known).
    `stage` may also legally be `START_STAGE` ("Start") — see `_check_start_owned`.
    """
    stage_names = {s.name for s in spec.stages.stages} | {START_STAGE}
    section_names = _section_names(spec)
    field_names = {f.name for f in spec.data_model.fields}
    for entry in spec.visibility.entries:
        if not isinstance(entry.permission, Visibility):
            raise ValueError(  # noqa: TRY004 — see _check_fields for why ValueError here
                f"visibility entry (section={entry.section!r}, stage={entry.stage!r}) has "
                f"permission {entry.permission!r}, not a Visibility enum member"
            )
        if entry.stage not in stage_names:
            raise ValueError(
                f"visibility entry for section {entry.section!r} names unknown stage "
                f"{entry.stage!r}, not in {sorted(stage_names)}"
            )
        if entry.section not in section_names:
            raise ValueError(
                f"visibility entry at stage {entry.stage!r} names unknown section "
                f"{entry.section!r}, not in {sorted(section_names)}"
            )
        if entry.field is not None and entry.field not in field_names:
            raise ValueError(
                f"visibility entry (section={entry.section!r}, stage={entry.stage!r}) names "
                f"unknown field {entry.field!r}, not in {sorted(field_names)}"
            )


def _check_start_owned(spec: AppSpec) -> None:
    """The first stage's own section must own START_STAGE WITH `Editable` permission, or the
    submission form renders empty (CLAUDE.md Visibility: "StartEvent is position 0... the very
    first section a user sees must list Start as one of its owning steps").

    F2: checking WHICH section is named at Start is not enough on its own — the original guard
    only asked "does an entry exist naming the first stage's section at Start," so
    `VisibilityEntry(first_section, "Start", Hidden)` satisfied it just as well as `Editable`
    would, and a Hidden (or ReadOnly) Start entry renders exactly the same empty form as no entry
    at all. Both "no owning entry" and "an owning entry that isn't Editable" raise here, named
    separately so the message says which one actually happened.
    """
    if not spec.stages.stages:
        return  # blocking_gaps() already refused an empty Stages before this ever runs
    first_stage = spec.stages.stages[0]
    first_stage_sections = ({first_stage.name}
                            | {sec.name for sec in spec.data_model.sections
                               if sec.stage == first_stage.name})
    owning = [e for e in spec.visibility.entries
              if e.stage == START_STAGE and e.section in first_stage_sections]
    if not owning:
        raise ValueError(
            f"no visibility entry gives the first stage {first_stage.name!r}'s own section "
            f"(one of {sorted(first_stage_sections)}) ownership of {START_STAGE!r} — the first "
            f"section must own Start or the submission form renders empty"
        )
    if not any(e.permission == Visibility.EDITABLE for e in owning):
        found = sorted({e.permission.value for e in owning})
        raise ValueError(
            f"the first stage {first_stage.name!r}'s own section owns {START_STAGE!r} but with "
            f"permission {found}, not Editable — Hidden or ReadOnly at Start renders the same "
            f"empty submission form as no entry at all"
        )


def _check_required_fields_editable(spec: AppSpec) -> None:
    """F1 BLOCKER: a Required field that is Hidden (or ReadOnly, or simply never mentioned) at
    its OWN stage compiles clean today — CLAUDE.md Visibility: "a Required field that is Hidden
    at its own step is still fatal": that step becomes permanently unsubmittable, so
    `simulate_case` (the only real oracle, per THE RULE) can never pass no matter how correct
    everything else is.

    Resolves each required field's EFFECTIVE permission at its own stage: a field-level
    `VisibilityEntry` there if one exists (most specific, checked first), else its resolved
    section's entry, else nothing at all — "nothing at all" is exactly as fatal as an explicit
    Hidden, since neither one is a proven `Editable`. Raises naming the field, its stage, and
    whatever permission (or the literal absence of one) was actually found.
    """
    for f in spec.data_model.fields:
        if not f.required:
            continue
        section = f.section if f.section is not None else f.stage
        field_entry = next(
            (e for e in spec.visibility.entries if e.stage == f.stage and e.field == f.name),
            None,
        )
        if field_entry is not None:
            effective = field_entry.permission
        else:
            section_entry = next(
                (e for e in spec.visibility.entries
                 if e.stage == f.stage and e.section == section and e.field is None),
                None,
            )
            effective = section_entry.permission if section_entry is not None else None
        if effective != Visibility.EDITABLE:
            found = effective.value if effective is not None else "no visibility entry at all"
            raise ValueError(
                f"field {f.name!r} is Required but its effective permission at its own stage "
                f"{f.stage!r} is {found!r} — a Required field that is not Editable at its own "
                f"stage can never be submitted"
            )


def _check_persona_roles(spec: AppSpec) -> None:
    """A PersonaView naming a role that isn't in Roles."""
    role_names = {r.name for r in spec.roles.roles}
    for view in spec.personas.views:
        if view.role not in role_names:
            raise ValueError(
                f"persona view names unknown role {view.role!r}, not in {sorted(role_names)}"
            )


# ADR-0004 (#7, B2 #36): three page-widget capabilities are impossible through the API and are
# refused at COMPILE with a stated reason naming their coverage row, never built best-effort. A
# report widget needs a report to exist first, and creating one has no API path (report-creation) —
# distinct from the future capability to WIRE an existing report into a widget (report-widget #23,
# still pending). Role-scoped visibility is the FOURTH API-impossible capability but is the doctor's
# refusal, not compile's (ADR-0003, #6), so it is not here.
_API_IMPOSSIBLE_WIDGET_ROWS: dict[str, str] = {
    "general/rich_text": "rich-text-content",
    "custom": "custom-component",
}


def _api_impossible_row(slug: str) -> str | None:
    """The coverage-row key a widget `slug` is refused under, or None if it is buildable. Every
    `report/*` slug maps to `report-creation` (any report widget requires creating a report first)."""
    if slug in _API_IMPOSSIBLE_WIDGET_ROWS:
        return _API_IMPOSSIBLE_WIDGET_ROWS[slug]
    if slug.startswith("report/"):
        return "report-creation"
    return None


def _check_no_api_impossible_widgets(spec: AppSpec) -> None:
    """B2 (#36): a page widget for an API-impossible capability (rich-text render, custom component,
    report creation) is refused at compile, naming its coverage row (ADR-0004). Runs BEFORE
    `_check_widgets` so the refusal fires on the impossible SLUG itself rather than surfacing as a
    missing-config error for the same widget."""
    for view in spec.personas.views:
        for page in view.pages:
            for w in page.widgets:
                row_key = _api_impossible_row(w.slug)
                if row_key is None:
                    continue
                row = coverage.get(row_key)
                raise ValueError(
                    f"page {page.name!r} widget {w.slug!r} is API-impossible (coverage row "
                    f"{row.key!r}: {row.reason}) — refused at compile per ADR-0004, never built "
                    f"best-effort."
                )


def _check_widgets(spec: AppSpec) -> None:
    """A widget slug outside `kfforge.pages.WIDGET_SLUGS`, or missing a config key
    `kfforge.pages.WIDGET_REQUIRED_CONFIG` demands for that slug (`add_widget` itself refuses to
    write a node under these exact conditions — this check exists so the SAME refusal happens at
    plan-compile time, naming the page and widget, rather than surfacing deep inside whatever
    executes the plan)."""
    for view in spec.personas.views:
        for page in view.pages:
            for w in page.widgets:
                if w.slug not in WIDGET_SLUGS:
                    raise ValueError(
                        f"page {page.name!r} widget slug {w.slug!r} is not a known widget "
                        f"(kfforge.pages.WIDGET_SLUGS): {sorted(WIDGET_SLUGS)}"
                    )
                required = WIDGET_REQUIRED_CONFIG.get(w.slug, ())
                config = dict(w.config)
                for key in required:
                    if key == "row_fields":
                        if not w.row_fields:
                            raise ValueError(
                                f"page {page.name!r} widget {w.slug!r} is missing required "
                                f"row_fields (repeater needs at least one)"
                            )
                        continue
                    if not config.get(key):
                        raise ValueError(
                            f"page {page.name!r} widget {w.slug!r} is missing required config "
                            f"{key!r} (kfforge.pages.WIDGET_REQUIRED_CONFIG)"
                        )


def _check_test_cases(spec: AppSpec) -> None:
    """A test case's expected_path/fills naming an unknown stage, a fill naming an unknown field
    or an out-of-list Select value, a fill for a stage the path never visits, or an
    expected_result outside ProblemGoal.result_values.

    A fill may target a top-level field OR a column of a table hosted at `fill.stage`
    (CLAUDE.md Item data plane: child-table rows are filled via `Table::<id>`, keyed by child
    field ids — so a table column IS a real addressable fill target at runtime). A flat fill of
    a table column is ambiguous only if two tables at the SAME stage share a column name; this
    check resolves per-stage so a column unique within its stage is accepted, and only Select
    VALUES are list-validated for top-level Selects (`TableColumnReq` carries no `list_name`).
    """
    stage_names = {s.name for s in spec.stages.stages}
    fields_by_name = {f.name: f for f in spec.data_model.fields}
    lists_by_name = {l.name: l for l in spec.master_data.lists}
    result_values = set(spec.problem_goal.result_values)
    tables_by_stage: dict[str, list[TableReq]] = {}
    for t in spec.data_model.tables:
        tables_by_stage.setdefault(t.stage, []).append(t)
    for case in spec.test_cases.cases:
        for stage_name in case.expected_path:
            if stage_name not in stage_names:
                raise ValueError(
                    f"test case {case.name!r} expected_path names unknown stage "
                    f"{stage_name!r}, not in {sorted(stage_names)}"
                )
        if case.expected_result not in result_values:
            raise ValueError(
                f"test case {case.name!r} expected_result {case.expected_result!r} is not one "
                f"of ProblemGoal.result_values {sorted(result_values)}"
            )
        path_stages = set(case.expected_path)
        for fill in case.fills:
            if fill.stage not in stage_names:
                raise ValueError(
                    f"test case {case.name!r} fills unknown stage {fill.stage!r}, not in "
                    f"{sorted(stage_names)}"
                )
            if fill.stage not in path_stages:
                raise ValueError(
                    f"test case {case.name!r} fills stage {fill.stage!r}, which expected_path "
                    f"{case.expected_path} never visits"
                )
            stage_tables = tables_by_stage.get(fill.stage, ())
            for field_name, value in fill.values:
                field = fields_by_name.get(field_name)
                if field is None:
                    # a column of a table hosted at this stage is also a valid fill target
                    field = _stage_column(stage_tables, field_name)
                if field is None:
                    raise ValueError(
                        f"test case {case.name!r} fills unknown field {field_name!r}"
                    )
                if field.type == FieldType.SELECT and field.list_name is not None:
                    values = (lists_by_name[field.list_name].values
                             if field.list_name in lists_by_name else ())
                    if value not in values:
                        raise ValueError(
                            f"test case {case.name!r} fills {field_name!r}={value!r}, not in "
                            f"list {field.list_name!r} values {values}"
                        )


def _stage_column(stage_tables: Iterable[TableReq], name: str) -> FieldReq | None:
    """Resolve `name` to a column of a table hosted at the fill's stage, or None. Returns the
    first match — a column name unique within its stage (the only case that lets a flat fill be
    unambiguous) is accepted; a name shared across two tables at the same stage would need the
    executor's table-id disambiguation, not a check-side guess. A `FieldReq`-shaped object is
    synthesized with `.type` (for the SELECT-list check) and `list_name=None` (`TableColumnReq`
    binds no list)."""
    for t in stage_tables:
        for col in t.columns:
            if col.name == name:
                return FieldReq(name=col.name, type=col.type, required=col.required,
                                stage=t.stage, list_name=None)
    return None


_CROSS_CHECKS: tuple[Callable[[AppSpec], None], ...] = (
    _check_stage_owner_roles,
    _check_sections,
    _check_fields,
    _check_select_fields_have_list,     # F3 — right after field/section integrity
    _check_tables,
    _check_computed_fields,
    _check_no_split_nested_in_branch,   # D3 (#29) — nested split has no captured shape, ever
    _check_no_duplicate_branch_names,   # D3 (#29) — cross-split branch-NAME collision
    _check_no_duplicate_step_across_branches,  # D7 (#29) S3 — same step name in two branches
    _check_routing_field_and_options,   # F4 — before the other routing checks, not inside them
    _check_routing_stages,
    _check_routing_complete,
    _check_routing_literals,
    _check_all_deciding_values_claimed,  # AC3 — the inverse of _check_routing_literals
    _check_loop_stages,
    _check_loop_gate_is_boolean,
    _check_loop_not_cross_branch,       # D3 (#29) S3 — a loop must be branch-local
    _check_visibility_entries,
    _check_start_owned,
    _check_required_fields_editable,    # F1 — after visibility entries/Start are known-valid
    _check_persona_roles,
    _check_no_api_impossible_widgets,   # B2 (#36) — ADR-0004, before the config check
    _check_widgets,
    _check_test_cases,
)


# ---- op derivation ------------------------------------------------------------------------------
# One builder per OP_ORDER kind. Each takes the whole spec (never just "its" dimension) because
# several ops are legitimately derived from more than one dimension (e.g. build_workflow needs
# both Stages and Routing) — see each function's docstring for which. Every op-builder runs AFTER
# every cross-check above, so none of them re-validates what's already guaranteed.

def _op_create_process(spec: AppSpec) -> tuple[Op, ...]:
    """Carries the FULL ProblemGoal (dimension 1) — pain/goal as descriptive metadata, not just
    done_definition/terminal_states/result_values — so nothing collected there is discarded."""
    pg = spec.problem_goal
    return (Op(
        kind="create_process",
        args={"name": spec.app_name, "pain": pg.pain, "goal": pg.goal,
              "done_definition": pg.done_definition, "terminal_states": pg.terminal_states,
              "result_values": pg.result_values},
        why="the flow every later step attaches to (Build order step 1)",
    ),)


def _op_member_batch(spec: AppSpec) -> tuple[Op, ...]:
    """One op per role (dimension 2) — CLAUDE.md Members first: an API-created flow has zero
    members, so this must land before anything that needs a real user to see the form."""
    return tuple(
        Op(kind="member_batch",
           args={"role": r.name, "is_admin": r.is_admin, "members_hint": r.members_hint},
           why=f"grant {r.name!r} access before anything else can render (Members first)")
        for r in spec.roles.roles
    )


def _op_create_list(spec: AppSpec) -> tuple[Op, ...]:
    """One op per reference list (dimension 7), BEFORE apply_fields so a Select field never
    references a list the plan hasn't already flagged. The write itself is human-gated (CLAUDE.md
    forbids synthesizing a NEW ReferredList wiring), but the VALUES still belong in the plan —
    the alternative is exactly the silent-discard bug this op exists to close."""
    return tuple(
        Op(kind="create_list",
           args={"name": l.name, "values": l.values, "owner_role": l.owner_role},
           why="HUMAN-GATED: CLAUDE.md forbids synthesizing new ReferredList wiring via the "
               "write API — a human must create/verify this list in the builder UI with EXACTLY "
               "these values before any Select field below may reference it")
        for l in spec.master_data.lists
    )


def _op_apply_fields(spec: AppSpec) -> tuple[Op, ...]:
    """One op per stage that has fields (dimension 6, grouped by `FieldReq.stage`, dimension 3
    for the grouping itself) plus the sequence-number scheme (dimension 6, `DataModel.sequence`),
    folded into the FIRST stage's op since a running number is generated at intake. Each field's
    resolved `section` (its own `FieldReq.section`, or its stage's implicit default) and its
    per-type `options` both ride along in the per-field dict — `_check_fields` has already
    guaranteed every stage/section reference here is valid, so this function only groups.
    """
    stage_names = [s.name for s in spec.stages.stages]
    by_stage: dict[str, list[FieldReq]] = {name: [] for name in stage_names}
    for f in spec.data_model.fields:
        by_stage[f.stage].append(f)

    ops = []
    for i, name in enumerate(stage_names):
        fields = by_stage[name]
        sequence = spec.data_model.sequence if i == 0 else None
        if not fields and sequence is None:
            continue
        ops.append(Op(
            kind="apply_fields",
            args={
                "stage": name,
                "fields": tuple(
                    {"name": f.name, "type": f.type.value, "required": f.required,
                     "section": f.section if f.section is not None else name,
                     "list_name": f.list_name, "options": dict(f.options)}
                    for f in fields
                ),
                "sequence": None if sequence is None
                    else {"prefix": sequence.prefix, "padding": sequence.padding},
            },
            why=f"fields for stage {name!r} (Node-graph invariants: Field needs Model + CreatedAt)",
        ))
    return tuple(ops)


def _op_add_table(spec: AppSpec) -> tuple[Op, ...]:
    """One op per table (dimension 6), columns carrying their own type/required now (not bare
    names)."""
    return tuple(
        Op(kind="add_table",
           args={"name": t.name, "stage": t.stage,
                 "columns": tuple({"name": c.name, "type": c.type.value, "required": c.required}
                                  for c in t.columns),
                 "max_rows": t.max_rows},
           why=f"table {t.name!r} — its own nested Model in its own root Row, never inside a Section")
        for t in spec.data_model.tables
    )


def _workflow_decomposition(spec: AppSpec) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    """Decompose the flat stage list + zero or more sequential decision splits into the
    DECLARATIVE plan a later apply-executor maps onto `kfforge.graph.build_workflow`: a linear
    `steps` spine plus a tuple of Parallel gateways, zero or more. This is a plan shape, not a
    verbatim call: `steps` are bare stage NAMES (the per-stage owner role is rejoined from the
    separate `set_assignees` op — CLAUDE.md Members first — never carried here), and each entry of
    `parallels` is `{name, after, branches:[{name, stages}]}`; the executor is what turns that
    tuple into build_workflow's own `parallels=[(ParallelSpec, after_index), ...]` argument (see
    `kfforge.graph.build_workflow`, which already supports N sequential gateways). (No executor
    consumes it yet — `kfforge.engine` is still a planning stub; the plan is the deliverable a
    build agent reads.)

    S2 (#33, generalising S1 #32's one-split shape, spec #29 decision D3): every `DecisionPoint` in
    `spec.routing.points` becomes its own Parallel whose branches ARE that point's option route
    SEQUENCES (P1 #30 — a branch is an ordered list of stages). The branch stages of ALL points —
    not just one — are lifted OUT of the shared linear spine and hung under their own Parallel;
    what remains linear is every stage no split ever routes through. Each gateway is inserted right
    after ITS OWN stem's (`at_stage`) index in that same reduced `steps` list — `_check_no_split_
    nested_in_branch` has already refused a split whose stem sits inside a DIFFERENT split's own
    branch, so every stem is guaranteed to still be in `linear` by the time this runs. Zero splits
    → a plain linear spine, no Parallels (unchanged behaviour).

    Parallels are returned in DECLARED POINT order (`spec.routing.points`'s own order), each
    Parallel's branch ORDER following ITS OWN deciding field's declared `options` (not
    `route_per_option`'s pair order) — so both line up with the diagram and with S4's per-branch
    conditions. Every Parallel built here is an UNCONDITIONAL and-fork (every branch runs) — the
    branch CONDITIONS that make one a real decision are a separate build step, S4 #35 (CLAUDE.md
    Conditional routing); `_check_no_duplicate_branch_names` has already refused two splits sharing
    a branch name, so no two entries in the returned tuple can collide on a branch id downstream.
    """
    stage_names = tuple(s.name for s in spec.stages.stages)
    points = spec.routing.points
    if not points:
        return stage_names, ()
    branch_stages_all = {st for point in points for _opt, seq in point.route_per_option
                          for st in seq}
    linear = tuple(n for n in stage_names if n not in branch_stages_all)
    parallels = []
    for point in points:
        mapping = dict(point.route_per_option)
        branches = tuple((opt, tuple(mapping[opt])) for opt in point.options)  # declared order
        parallels.append({
            "name": point.field_name,
            "after": linear.index(point.at_stage),  # stem is never a branch stage, stays linear
            "branches": tuple({"name": opt, "stages": seq} for opt, seq in branches),
        })
    return linear, tuple(parallels)


def _op_build_workflow(spec: AppSpec) -> tuple[Op, ...]:
    """Exactly one op for the whole process (dimensions 3 Stages + 4 Routing together):
    `WorkflowType: Sequence` means the ORDER of stages IS the flow, so there is one ProcessDef to
    build, not one op per stage. Stages carry their FULL descriptive info (what_happens/entry/
    exit criteria), not just names — nothing collected in dimension 3 is discarded. `owner_role`
    deliberately does NOT ride along here: it flows through the separate `set_assignees` op,
    matching `kfforge.graph.build_workflow`'s own `Resource`-node write being a materially
    different operation from the `Activity`/`ProcessDef` graph this op represents.

    S2 (#33, generalising S1 #32): the routing dimension is now CONSUMED (`_workflow_decomposition`)
    into the executable `steps` + `parallels` pair `kfforge.graph.build_workflow` actually takes —
    N sequential decision splits become N Parallel gateways, in declared point order, each with its
    own branches. The descriptive `stages`/`routing` still ride along in full (nothing collected is
    discarded, and S4 needs `routing` to attach branch conditions to the right gateway).
    """
    steps, parallels = _workflow_decomposition(spec)
    return (Op(
        kind="build_workflow",
        args={
            "stages": tuple(
                {"name": s.name, "what_happens": s.what_happens,
                 "entry_criteria": s.entry_criteria, "exit_criteria": s.exit_criteria}
                for s in spec.stages.stages
            ),
            "routing": tuple(
                {"at_stage": p.at_stage, "field_name": p.field_name,
                 "route_per_option": dict(p.route_per_option)}
                for p in spec.routing.points
            ),
            # the executable shape build_workflow consumes: the linear spine, and zero or more
            # Parallels (branches = option route sequences, each inserted after its own fork stem).
            "steps": steps,
            "parallels": parallels,
        },
        why="ProcessDef + Activities in stage order — WorkflowType=Sequence order IS the flow "
            "(Build order step 5); N sequential decision splits become N Parallel gateways in "
            "order (unconditional and-forks until S4 attaches branch conditions); assignees are a "
            "separate op",
    ),)


def _op_set_assignees(spec: AppSpec) -> tuple[Op, ...]:
    """One op per stage (dimension 3's `owner_role`) — a `Resource{ValueType:AppRole}` node on
    that stage's Activity, matching `kfforge.graph.build_workflow`'s own `roles`/`Step`
    parameters. Without this op nobody can ever submit any step, and `simulate_case` always
    fails — CLAUDE.md Members first: assignees cannot be written before members exist, hence this
    sits after `member_batch` in OP_ORDER (member_batch is also what resolves a role NAME to the
    real role id this op's `owner_role` will eventually need)."""
    return tuple(
        Op(kind="set_assignees",
           args={"stage": s.name, "owner_role": s.owner_role},
           why=f"Resource(ValueType=AppRole) assignee on {s.name!r}'s Activity, resolved from "
               f"role {s.owner_role!r} — members must exist first (Members first); without this "
               f"nobody can submit the step and simulate_case always fails")
        for s in spec.stages.stages
    )


def _op_add_goto_gate(spec: AppSpec) -> tuple[Op, ...]:
    """One op per rework loop (dimension 5). `_check_loop_stages`/`_check_loop_gate_is_boolean`
    have already refused any loop that isn't backward or isn't gated on a real Boolean field, and
    `_check_loop_not_cross_branch` any loop spanning two branches.

    S3 (#34, D7/US11): each op carries the `branch_name` it belongs to, so the goto is placed
    EXPLICITLY inside that branch (last within it) instead of the live layer mis-deriving it from
    an ambiguous target name (`forge_add_goto_gate`'s own `branch_name` parameter). Derived from the
    loop's own stages: the single branch owning from_stage/to_stage, or `None` for a plain spine
    loop. A spine->branch loop resolves to that one branch; two branches are already refused."""
    owner = _stage_branch_owner(spec)
    ops = []
    for l in spec.rework_loops.loops:
        branches = {owner[s] for s in (l.from_stage, l.to_stage) if s in owner}
        branch_name = branches.pop() if len(branches) == 1 else None  # 0 -> spine loop, 2 -> refused
        ops.append(Op(
            kind="add_goto_gate",
            args={"from_stage": l.from_stage, "to_stage": l.to_stage,
                  "gate_field": l.gate_field, "max_rounds": l.max_rounds,
                  "branch_name": branch_name},
            why=f"backward GotoTask {l.from_stage!r} -> {l.to_stage!r}, Boolean-gated, fail-closed "
                f"(Gate polarity)" + (f", placed inside branch {branch_name!r}" if branch_name else
                                      ", plain root-chain loop")))
    return tuple(ops)


def _op_set_branch_conditions(spec: AppSpec) -> tuple[Op, ...]:
    """Attaches the branch CONDITIONS that make `_op_build_workflow`'s Parallel a real conditional
    split, not an unconditional and-fork (CLAUDE.md Conditional routing). Mirrors `_op_add_table`
    returning `()` when there are no tables: an empty `spec.routing.points` means a linear flow
    with no split to condition at all, so this returns `()` rather than a no-op Op.

    ⚠️ STILL ONLY WIRED FOR `points[0]`, even now that S2 (#33) lets `spec.routing.points` hold
    more than one split — attaching conditions to every gateway a multi-split spec now BUILDS is
    S4's own job (#35, CLAUDE.md Conditional routing), not S2's; S2 is scoped to workflow
    decomposition and the compile-time refusals in `_check_no_split_nested_in_branch`/
    `_check_no_duplicate_branch_names`. A spec with more than one split therefore compiles a
    `build_workflow` op with N Parallels but only ONE `set_branch_conditions` op, for the FIRST —
    every later gateway stays an unconditional and-fork until S4 lands. Not a silent-downgrade
    violation of CLAUDE.md THE RULE (the op that IS emitted is fully correct for what it covers),
    but a known, deliberately deferred gap — do not read "one op" as "every split is conditioned."

    `_check_routing_field_and_options`/`_check_routing_literals`/`_check_all_deciding_values_
    claimed` have already guaranteed every option on every point is both a real literal AND that
    no real list value is left unclaimed — so this builder only shapes the args, it never
    re-validates. In this compile model a branch's NAME is the same string as the literal that
    selects it (`point.options`), so `branch_literals` is `{opt: opt}` — matching
    `forge_set_branch_conditions(field_name, branch_literals, ...)`'s own `branch NAME -> literal`
    mapping.
    """
    if not spec.routing.points:
        return ()
    point = spec.routing.points[0]
    return (Op(
        kind="set_branch_conditions",
        args={"at_stage": point.at_stage, "field_name": point.field_name,
              "branch_literals": {opt: opt for opt in point.options}},
        why=f"attach the branch conditions that make this Parallel a real conditional split, not "
            f"an unconditional and-fork (CLAUDE.md Conditional routing); branch NAME -> the "
            f"literal of field {point.field_name!r} that selects it, matching "
            f"forge_set_branch_conditions. Only the FIRST split's gateway — every later split "
            f"(S2 #33) stays unconditional pending S4 (#35)",
    ),)


def _op_set_visibility(spec: AppSpec) -> tuple[Op, ...]:
    """Exactly one op holding the WHOLE matrix (dimension 8), each entry now carrying its
    optional `field` (dimension-8 field-level override — `None` means the whole section) — the
    builder rebuilds the matrix wholesale every time anyway (any workflow rebuild silently
    deletes every Permission node), so a plan that emits it piecemeal would just misrepresent how
    it actually gets applied."""
    return (Op(
        kind="set_visibility",
        args={"entries": tuple(
            {"section": e.section, "stage": e.stage, "permission": e.permission.value,
             "field": e.field}
            for e in spec.visibility.entries
        )},
        why="per-step visibility matrix — rebuild after every workflow change (Build order step 8)",
    ),)


def _op_set_events(spec: AppSpec) -> tuple[Op, ...]:
    """One op per computed field (dimension 6). `why` flags whether the trigger string is
    CONFIRMED (`onChange`) or UNVERIFIED (`onSelect`/`onClick` — never captured live, see
    `schema.EventTrigger`), so that uncertainty travels with the plan instead of getting
    silently smoothed over."""
    ops = []
    for c in spec.data_model.computed:
        confirmed = c.trigger is EventTrigger.ON_CHANGE
        ops.append(Op(
            kind="set_events",
            args={"target_field": c.target_field, "source_fields": c.source_fields,
                  "trigger": c.trigger.value, "formula_intent": c.formula_intent},
            why=(f"computed {c.target_field!r} via an event on its source field(s), never the "
                 f"target (Field events); trigger {c.trigger.value!r} is "
                 + ("CONFIRMED live" if confirmed else
                    "UNVERIFIED — capture off a real builder-authored event before relying on "
                    "this wire string")),
        ))
    return tuple(ops)


def _op_set_styles(spec: AppSpec) -> tuple[Op, ...]:
    """One op per stage (dimension 3) — each stage's section gets a distinguishable look. Args
    name ONLY the stage, never a color or token: CLAUDE.md Write path forbids synthesizing a style
    token (an invented one PUTs 200 and fails silently at render), so the actual token value is
    always a later, human/builder-driven step, not something this compiler may invent."""
    return tuple(
        Op(kind="set_styles",
           args={"stage": s.name},
           why="give this stage's section a distinguishable look — token VALUES are read off the "
               "builder dropdown at apply time, never synthesized here")
        for s in spec.stages.stages
    )


def _op_publish(spec: AppSpec) -> tuple[Op, ...]:
    return (Op(kind="publish", args={"name": spec.app_name},
                why="publish so the live version matches the built draft (Build order step 11)"),)


def _op_doctor(spec: AppSpec) -> tuple[Op, ...]:
    return (Op(kind="doctor", args={},
                why="read-only health check — THE RULE: a 200 and a clean publish prove nothing"),)


def _unique_pages(spec: AppSpec) -> tuple[PageIntent, ...]:
    """Every distinct page NAME across all persona views (dimension 10), in first-occurrence
    order. The same page can appear under more than one role — dedupe here means `create_page`
    creates it exactly once, and `_op_set_navigation` still binds it per role separately.

    Deliberately used ONLY for page identity/ordering, never for a page's CONTENT: the
    `PageIntent` object kept per name is whichever role's happened to be first, so its `.widgets`
    must never be read directly off this function's result — a second role sharing the page can
    declare widgets the first role's `PageIntent` doesn't have (F6: `_op_build_page` used to do
    exactly that, silently dropping every OTHER role's widgets while its own docstring claimed
    nothing was dropped). `_op_build_page` re-walks `spec.personas.views` itself instead, for
    widgets as well as kpis/actions.
    """
    seen: dict[str, PageIntent] = {}
    for view in spec.personas.views:
        for page in view.pages:
            seen.setdefault(page.name, page)
    return tuple(seen.values())


def _op_create_page(spec: AppSpec) -> tuple[Op, ...]:
    return tuple(
        Op(kind="create_page", args={"name": p.name},
           why="a virgin page — 4 nodes: Page, root Container, empty Style, User")
        for p in _unique_pages(spec)
    )


def _widget_args(w: Any) -> dict[str, Any]:
    return {"slug": w.slug, "config": dict(w.config), "row_fields": w.row_fields}


def _op_build_page(spec: AppSpec) -> tuple[Op, ...]:
    """`kpis`/`actions`/`widgets` (dimension 10) are ALL aggregated across EVERY persona view
    that references this page — a shared page has no single "owning" role, so nothing is
    silently dropped just because two roles both point at it.

    F6: widgets used to come from whichever single `PageIntent` `_unique_pages` happened to keep
    (first role wins), so a SECOND role sharing the page but declaring an extra widget the first
    role didn't have that widget silently vanish from the plan — directly contradicting this
    function's own claim that nothing is dropped (which was already true for kpis/actions, just
    not for widgets). Widgets are deduped by `(slug, config)`: the SAME widget declared under two
    roles collapses to one write, but two widgets differing in either field are both kept, in
    first-seen order.
    """
    kpis_by_page: dict[str, set[str]] = {}
    actions_by_page: dict[str, set[str]] = {}
    widgets_by_page: dict[str, dict[tuple[str, tuple[tuple[str, str], ...]], WidgetIntent]] = {}
    page_order: list[str] = []
    for view in spec.personas.views:
        for page in view.pages:
            if page.name not in page_order:
                page_order.append(page.name)
            kpis_by_page.setdefault(page.name, set()).update(view.kpis)
            actions_by_page.setdefault(page.name, set()).update(view.actions)
            bucket = widgets_by_page.setdefault(page.name, {})
            for w in page.widgets:
                bucket.setdefault((w.slug, w.config), w)
    return tuple(
        Op(kind="build_page",
           args={
               "name": name,
               "widgets": tuple(_widget_args(w) for w in widgets_by_page[name].values()),
               "kpis": tuple(sorted(kpis_by_page.get(name, ()))),
               "actions": tuple(sorted(actions_by_page.get(name, ()))),
           },
           why=f"container/component graph for {name!r}'s widgets, KPIs, and actions")
        for name in page_order
    )


def _op_set_navigation(spec: AppSpec) -> tuple[Op, ...]:
    """One op per (role, page) pair — a page shared by two roles gets bound twice, once per role's
    own navigation, matching CLAUDE.md Pages: "give every role the same view" = point every role's
    Navigation::Menu at the same shared page, not duplicate the page."""
    ops = []
    for view in spec.personas.views:
        for page in view.pages:
            ops.append(Op(
                kind="set_navigation",
                args={"role": view.role, "page": page.name},
                why=f"bind {page.name!r} into {view.role!r}'s navigation so it appears as a tab",
            ))
    return tuple(ops)


def _op_simulate_case(spec: AppSpec) -> tuple[Op, ...]:
    """One op per test case (dimension 11) — the only oracle beyond a clean publish (THE RULE).
    `fills` is per-stage-VISIT (not a flat dict), so a looped case can express ticking its gate
    false on the first visit and true on the second."""
    return tuple(
        Op(kind="simulate_case",
           args={"name": c.name,
                 "fills": tuple({"stage": f.stage, "values": dict(f.values)} for f in c.fills),
                 "expected_path": c.expected_path, "expected_result": c.expected_result},
           why="walk create->fill->submit->gates->terminal (Build order step 13)")
        for c in spec.test_cases.cases
    )


_OP_BUILDERS: dict[str, Callable[[AppSpec], tuple[Op, ...]]] = {
    "create_process": _op_create_process,
    "member_batch": _op_member_batch,
    "create_list": _op_create_list,
    "apply_fields": _op_apply_fields,
    "add_table": _op_add_table,
    "build_workflow": _op_build_workflow,
    "set_assignees": _op_set_assignees,
    "add_goto_gate": _op_add_goto_gate,
    "set_branch_conditions": _op_set_branch_conditions,
    "set_visibility": _op_set_visibility,
    "set_events": _op_set_events,
    "set_styles": _op_set_styles,
    "publish": _op_publish,
    "doctor": _op_doctor,
    "create_page": _op_create_page,
    "build_page": _op_build_page,
    "set_navigation": _op_set_navigation,
    "simulate_case": _op_simulate_case,
}
assert set(_OP_BUILDERS) == set(OP_ORDER), "every canonical op kind needs exactly one builder"


def compile_spec(spec: AppSpec) -> BuildPlan:
    """Compile an approved, complete AppSpec into a BuildPlan.

    Refuses, in order:
    1. `not spec.approved` — a human has to sign off before this becomes a build (CLAUDE.md THE
       RULE: building blind against an undocumented API is how sessions get lost).
    2. `spec.blocking_gaps()` non-empty — an incomplete spec cannot derive a complete plan;
       message lists every BLOCKING gap (advisory dimensions, currently just timing, do not
       appear here even if empty) so the caller can go straight back to
       `questions.next_questions`.
    3. any cross-check in `_CROSS_CHECKS` (see the functions above) — a spec that's structurally
       complete but internally inconsistent (a routing literal no list has, a non-Boolean loop
       gate, a widget missing its required binding, ...).

    Only past all three does it derive `ops`, walking `OP_ORDER` so the result is always in the
    proven build order regardless of what order the spec's own dimensions happen to be filled in.
    """
    if not spec.approved:
        raise ValueError("confirmation required first — spec.approved is False")

    blocking = spec.blocking_gaps()
    if blocking:
        raise ValueError("spec is incomplete, confirm these first: " + "; ".join(blocking))

    for check in _CROSS_CHECKS:
        check(spec)

    ops: list[Op] = []
    for kind in OP_ORDER:
        ops.extend(_OP_BUILDERS[kind](spec))
    return BuildPlan(ops=tuple(ops))
