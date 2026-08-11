"""Contract test over the coverage contract (kfforge/coverage.py) — the backbone
table every capability ticket wires a row into. Same pattern as the engine-manual
contract test (test_engine_doc.py): it guards the table's own integrity, not any
one build.

B1 (#31) scope: assert bucketing, the not-captured→(ticket|Known-Exclusion) rule,
and that unbuilt capabilities are marked pending their ticket. It does NOT yet
require pending rows to be wired to a real refusal — that assertion is added by the
closing gate B2 (#36) as rows flip from pending to wired.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from kfforge.coverage import ROWS, Bucket, CoverageRow, get
from kfforge.intake.compile import compile_spec
from kfforge.intake.schema import (
    START_STAGE,
    AppSpec,
    CaseWalk,
    DataModel,
    DecisionPoint,
    FieldReq,
    ListSpec,
    MasterData,
    PageIntent,
    Personas,
    PersonaView,
    ProblemGoal,
    ReworkLoops,
    Roles,
    RoleSpec,
    Routing,
    Stages,
    StageSpec,
    StepFill,
    TestCases,
    Timing,
    VisibilityEntry,
    VisibilityMatrix,
    WidgetIntent,
)
from kfforge.types import FieldType, Visibility

# Reused across suites: the one fully-populated synthetic AppSpec that carries a real decision
# split (Diagnose -> Yes:Repair / No:Return). Imported by bare module name — pytest's default
# prepend import mode puts tests/ on sys.path (no tests/__init__.py), and _full_spec is a pure
# factory with no import-time side effects.
from test_intake import _full_spec

TICKET_RE = re.compile(r"^#\d+$")
KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Faithfulness anchor: these shapes MUST have a row, so a transcription of #26 +
# the API-impossible set absorbed from #7 can't silently lose one. Every #26 row +
# absorbed-#7 row is pinned by name (buckets are asserted structurally below).
REQUIRED_KEYS = frozenset({
    # captured-live (#26 "yes/yes/n-a" rows)
    "straight-line", "one-split", "branch-local-loop", "suspended-step",
    "auto-numbered-id", "child-table", "computed-field-event", "per-step-visibility",
    # buildable
    "sequential-splits",          # #26's bold "several splits"
    # refuses-loudly (#26's bold refusals + word-list/section/report gaps)
    "nested-split", "auto-step", "cross-branch-jump", "unclaimed-value",
    "word-list-dropdown", "section-styling", "report-widget",
    # absorbed #7 API-impossible set
    "report-creation", "rich-text-content", "custom-component", "role-scoped-visibility",
})

# The only refuses-loudly rows that legitimately carry NO ticket — permanent Known
# Exclusions, not unbuilt capabilities. Pinning this set is what tests AC4: any
# pending refuse-row that loses its ticket would fall into this set and fail, and a
# Known Exclusion that accidentally gains one would too.
KNOWN_EXCLUSION_KEYS = frozenset({"cross-branch-jump", "auto-step", "unclaimed-value", "nested-split"})


def test_table_exists_as_data() -> None:
    assert ROWS, "the coverage contract must be a non-empty in-repo table"
    assert all(isinstance(r, CoverageRow) for r in ROWS)


def test_keys_unique_and_well_formed() -> None:
    keys = [r.key for r in ROWS]
    dupes = [k for k in keys if keys.count(k) > 1]
    assert not dupes, f"duplicate row keys: {sorted(set(dupes))}"
    bad = [k for k in keys if not KEY_RE.match(k)]
    assert not bad, f"keys must be kebab-case stable ids: {bad}"


def test_every_row_in_exactly_one_valid_bucket() -> None:
    # A single `bucket` field of a closed enum IS "exactly one bucket" — this pins
    # that no row carries a stray/invalid value.
    bad = [r.key for r in ROWS if not isinstance(r.bucket, Bucket)]
    assert not bad, f"rows not in a valid bucket: {bad}"


def test_every_bucket_is_represented() -> None:
    present = {r.bucket for r in ROWS}
    missing = set(Bucket) - present
    assert not missing, f"buckets with no rows: {sorted(b.value for b in missing)}"


def test_required_shapes_present() -> None:
    keys = {r.key for r in ROWS}
    missing = REQUIRED_KEYS - keys
    assert not missing, f"coverage table dropped required shape rows: {sorted(missing)}"


def test_not_captured_names_ticket_or_known_exclusion() -> None:
    # Acceptance: every not-captured shape names a capture/wiring ticket OR a
    # written Known Exclusion (a reason).
    orphans = [
        r.key for r in ROWS
        if not r.captured and r.ticket is None and not r.reason
    ]
    assert not orphans, f"not-captured rows with no ticket and no Known Exclusion: {orphans}"


def test_buildable_rows_are_pending_a_ticket() -> None:
    # Acceptance: unbuilt capabilities are explicitly marked pending their ticket.
    # A buildable row is, by definition, not built yet.
    unmarked = [r.key for r in ROWS if r.bucket is Bucket.BUILDABLE and not r.pending]
    assert not unmarked, f"buildable rows not marked pending a ticket: {unmarked}"


def test_pending_refuse_rows_are_exactly_the_non_exclusions() -> None:
    # Acceptance (AC4): refuse-rows for unbuilt capabilities are marked pending their
    # ticket. Enforced by pinning the complement — the refuses-loudly rows that
    # legitimately carry no ticket are exactly the Known Exclusions. A pending refuse
    # row that drops its ticket, or an exclusion that gains one, breaks this equality.
    no_ticket = {r.key for r in ROWS if r.bucket is Bucket.REFUSES_LOUDLY and r.ticket is None}
    assert no_ticket == KNOWN_EXCLUSION_KEYS, (
        f"refuses-loudly rows without a ticket must be exactly the Known Exclusions; "
        f"got {sorted(no_ticket)}, expected {sorted(KNOWN_EXCLUSION_KEYS)}"
    )


def test_refuses_loudly_rows_state_a_reason() -> None:
    # Every refusal names why it refuses — the message a builder/reader surfaces.
    silent = [r.key for r in ROWS if r.bucket is Bucket.REFUSES_LOUDLY and not r.reason]
    assert not silent, f"refuses-loudly rows with no stated reason: {silent}"


def test_captured_live_rows_carry_no_pending_marker() -> None:
    # A captured-live shape is done: no pending ticket, no refusal reason. Keeps the
    # `pending` marker meaningful (ticket set ⟺ not-yet-in-code).
    dirty = [
        r.key for r in ROWS
        if r.captured and (r.ticket is not None or r.reason is not None)
    ]
    assert not dirty, f"captured-live rows carrying a ticket/reason: {dirty}"


def test_tickets_are_well_formed_issue_refs() -> None:
    bad = [(r.key, r.ticket) for r in ROWS if r.ticket is not None and not TICKET_RE.match(r.ticket)]
    assert not bad, f"tickets must look like '#<number>': {bad}"


def test_pending_property_tracks_ticket() -> None:
    for r in ROWS:
        assert r.pending == (r.ticket is not None)


def test_get_returns_row_and_rejects_unknown_key() -> None:
    for r in ROWS:
        assert get(r.key) is r
    with pytest.raises(KeyError):
        get("no-such-shape")


# ---- S1 (#32): the "one split" row is WIRED — not aspirational --------------------------------
# The coverage table's claim that a shape builds must be backed by real code, or the table drifts
# into fiction (spec #29 D13/D14: builder and contract read the same source). B1 classified
# `one-split` as CAPTURED_LIVE; S1 is the autonomous-compiler path that makes that claim true.

def test_one_split_row_is_wired_not_pending() -> None:
    """The `one-split` row is CAPTURED_LIVE with no pending ticket — the shape is built, not
    promised. (A pending row would carry a ticket; the integrity tests above pin that a
    captured-live row carries none.)"""
    row = get("one-split")
    assert row.bucket is Bucket.CAPTURED_LIVE
    assert row.ticket is None
    assert not row.pending


def test_one_split_row_is_wired_to_a_real_parallel_build() -> None:
    """The enforcement behind AC4: compiling a spec with one decision split actually emits a
    Parallel gateway carrying that split's branches. If the compiler ever stopped building the
    `one-split` shape, this fails — so the row can never claim `wired` while the code regressed."""
    assert get("one-split").captured  # the row asserts the shape builds...
    plan = compile_spec(_full_spec())  # ...and the compiler really builds it
    workflow = next(op for op in plan.ops if op.kind == "build_workflow")
    parallels = workflow.args["parallels"]
    assert len(parallels) == 1, "one-split spec must compile to exactly one Parallel gateway"
    assert len(parallels[0]["branches"]) == 2  # Yes -> Repair, No -> Return to Customer


# ---- S4 (#35): the "unclaimed-value" row is WIRED — not aspirational --------------------------

def test_unclaimed_value_row_is_wired_to_a_real_refusal() -> None:
    """The enforcement behind AC4 for this row: compiling a spec whose deciding field's list has
    a value ("Maybe") claimed by no branch option actually raises, naming the `unclaimed-value`
    coverage row — the table's claim that this shape refuses is backed by real code in
    `_check_all_deciding_values_claimed`, not just a table entry with no code behind it."""
    full = _full_spec()
    bad_lists = tuple(
        dataclasses.replace(l, values=("Yes", "No", "Maybe")) if l.name == "Yes No" else l
        for l in full.master_data.lists
    )
    bad = dataclasses.replace(full, master_data=MasterData(lists=bad_lists))
    with pytest.raises(ValueError, match="unclaimed-value"):
        compile_spec(bad)
    row = get("unclaimed-value")
    assert row.bucket is Bucket.REFUSES_LOUDLY
    assert row.ticket is None


# ---- S2 (#33): the "sequential-splits" row is WIRED — not aspirational ------------------------
# S2 makes the engine BUILD N sequential decision splits offline (`_check_at_most_one_split`'s
# hard cap of one lifts). The coverage row moves from "waiting on #33" to "waiting on #16" (the
# live built-app-vs-input comparator) — it stays BUILDABLE, not captured-live, since no live
# capture of several sequential splits exists yet.

def _two_split_spec() -> AppSpec:
    """A fresh, minimal AppSpec with TWO sequential decision splits: Triage (Severity: High/Low)
    then, later in the same chain, Approve (Approval Type: Manager Approval/Auto Approve).
    Distinct branch names across the two splits (High/Low vs Manager Approval/Auto Approve) — same
    -named branches across splits are refused in S2 — and neither split's `at_stage` sits inside
    the OTHER split's branch stages (Approve is not Escalate/Standard Review; Triage is not
    Manager Review/Finalize), which is the nested-split shape S2 refuses separately.
    """
    return AppSpec(
        app_name="Escalation Tracker",
        problem_goal=ProblemGoal(
            pain="requests get routed inconsistently",
            goal="every request is triaged and approved through a consistent path",
            done_definition="the request is closed",
            terminal_states=("Closed",),
            result_values=("Resolved",),
        ),
        roles=Roles(roles=(
            RoleSpec("Front Desk", is_admin=False),
            RoleSpec("Manager", is_admin=True),
        )),
        stages=Stages(stages=(
            StageSpec("Log", "Front Desk", "log the request", "a request comes in",
                      "request logged"),
            StageSpec("Triage", "Manager", "assess severity", "request logged",
                      "severity recorded"),
            StageSpec("Escalate", "Manager", "handle an escalated request", "severity is High",
                      "escalation handled"),
            StageSpec("Standard Review", "Manager", "handle a routine request", "severity is Low",
                      "review complete"),
            StageSpec("Approve", "Manager", "decide who approves", "triage complete",
                      "approval route recorded"),
            StageSpec("Manager Review", "Manager", "manager reviews the request",
                      "approval route is Manager Approval", "manager reviewed"),
            StageSpec("Finalize", "Manager", "auto-finalize the request",
                      "approval route is Auto Approve", "finalized"),
            StageSpec("Close", "Front Desk", "close the request", "review or finalize complete",
                      "request closed"),
        )),
        routing=Routing(points=(
            DecisionPoint(at_stage="Triage", field_name="Severity", options=("High", "Low"),
                          route_per_option=(("High", ("Escalate",)), ("Low", ("Standard Review",)))),
            DecisionPoint(at_stage="Approve", field_name="Approval Type",
                          options=("Manager Approval", "Auto Approve"),
                          route_per_option=(("Manager Approval", ("Manager Review",)),
                                            ("Auto Approve", ("Finalize",)))),
        )),
        rework_loops=ReworkLoops(loops=(), confirmed_none=True),
        data_model=DataModel(
            fields=(
                FieldReq("Request Text", FieldType.TEXT, True, "Log"),
                FieldReq("Severity", FieldType.SELECT, True, "Triage", list_name="Severity Levels"),
                FieldReq("Approval Type", FieldType.SELECT, True, "Approve",
                         list_name="Approval Types"),
            ),
            tables=(),
            computed=(),
        ),
        master_data=MasterData(lists=(
            ListSpec("Severity Levels", ("High", "Low"), "Manager"),
            ListSpec("Approval Types", ("Manager Approval", "Auto Approve"), "Manager"),
        )),
        visibility=VisibilityMatrix(entries=(
            VisibilityEntry("Log", START_STAGE, Visibility.EDITABLE),
            VisibilityEntry("Log", "Log", Visibility.EDITABLE),
            VisibilityEntry("Triage", "Triage", Visibility.EDITABLE),
            VisibilityEntry("Approve", "Approve", Visibility.EDITABLE),
        )),
        timing=Timing(sla_notes="", batch_days=(), reminders=()),
        personas=Personas(views=(
            PersonaView("Manager", pages=(PageIntent("Dashboard", (WidgetIntent("general/label"),)),),
                        kpis=(), actions=()),
        )),
        test_cases=TestCases(cases=(
            CaseWalk(
                "Escalated, manager-approved",
                fills=(
                    StepFill("Log", (("Request Text", "Server down"),)),
                    StepFill("Triage", (("Severity", "High"),)),
                    StepFill("Approve", (("Approval Type", "Manager Approval"),)),
                ),
                expected_path=("Log", "Triage", "Escalate", "Approve", "Manager Review", "Close"),
                expected_result="Resolved",
            ),
        )),
        approved=True,
    )


def test_sequential_splits_row_wired_to_a_real_build() -> None:
    """The enforcement behind AC4 for this row: compiling a spec with TWO sequential decision
    splits actually emits two Parallel gateways, one per split, in order — the table's claim that
    this shape builds (S2, #33) is backed by real code, not just a table entry with no code
    behind it. The row itself now waits on #16 (the live comparator), not #33 — S2 is the offline
    build, #16 is the still-missing live capture."""
    row = get("sequential-splits")
    assert row.bucket is Bucket.BUILDABLE
    assert row.ticket == "#16"

    plan = compile_spec(_two_split_spec())
    workflow = next(op for op in plan.ops if op.kind == "build_workflow")
    parallels = workflow.args["parallels"]
    assert len(parallels) == 2, "two decision splits must compile to TWO Parallel gateways"
    assert len(parallels[0]["branches"]) == 2  # Triage: High -> Escalate, Low -> Standard Review
    assert len(parallels[1]["branches"]) == 2  # Approve: Manager Approval / Auto Approve
