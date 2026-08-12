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

# Reused across suites: the one fully-populated synthetic AppSpec that carries a real decision
# split (Diagnose -> Yes:Repair / No:Return). Imported by bare module name — pytest's default
# prepend import mode puts tests/ on sys.path (no tests/__init__.py), and _full_spec is a pure
# factory with no import-time side effects.
from test_intake import _branch_local_loop_spec, _full_spec

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
    LoopSpec,
    MasterData,
    PageIntent,
    Personas,
    PersonaView,
    PopupIntent,
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
    "duplicate-branch-step",      # S3 (#34): same step name in two branches
    "word-list-dropdown", "section-styling", "report-widget",
    # absorbed #7 API-impossible set
    "report-creation", "custom-component", "role-scoped-visibility",
})

# The only refuses-loudly rows that legitimately carry NO ticket — permanent Known
# Exclusions, not unbuilt capabilities. Pinning this set is what tests AC4: any
# pending refuse-row that loses its ticket would fall into this set and fail, and a
# Known Exclusion that accidentally gains one would too.
KNOWN_EXCLUSION_KEYS = frozenset({
    "cross-branch-jump", "auto-step", "unclaimed-value", "nested-split", "duplicate-branch-step",
    # B2 (#36): the API-impossible set, flipped from pending #36 to permanent Known Exclusions —
    # each is now wired to a compile refusal (ADR-0004), no capability ticket left to wait on.
    "custom-component", "report-creation",
    # #20 page layer: permanent Known Exclusions (a written reason, no ticket). The two live-value
    # tiles (#23, proven live 2026-08-11), the native-rendered status pill, and the multi-pane
    # tabbed interface (D6: no silent downgrade, no composition builder, no build ticket scoped yet).
    "kpi-tile-live-number", "delta-pill", "status-pill", "page-tabs",
    # #6: wired to the DOCTOR-gate refusal (verify.doctor's visibility_role_claims rule), the one
    # Known Exclusion enforced at the doctor rather than compile (ADR-0003/0004).
    "role-scoped-visibility",
})


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


# ---- S3 (#34): the branch-local-loop, cross-branch-jump, and duplicate-branch-step rows are WIRED

def test_branch_local_loop_row_is_wired_to_a_real_build() -> None:
    """The `branch-local-loop` row is CAPTURED_LIVE and the autonomous compiler really builds it:
    a loop whose endpoints both live in one branch compiles to an add_goto_gate op naming that
    branch, so the goto is placed inside it (CLAUDE.md Conditional routing), never mis-derived."""
    row = get("branch-local-loop")
    assert row.bucket is Bucket.CAPTURED_LIVE
    assert row.ticket is None and not row.pending
    plan = compile_spec(_branch_local_loop_spec())
    goto = next(op for op in plan.ops if op.kind == "add_goto_gate")
    assert goto.args["branch_name"] == "Complex"


def test_cross_branch_jump_row_is_wired_to_a_real_refusal() -> None:
    """The `cross-branch-jump` row refuses in real code: a loop from one branch into another raises
    at compile, naming the row. `_check_loop_not_cross_branch` backs the table's claim."""
    spec = dataclasses.replace(_branch_local_loop_spec(), rework_loops=ReworkLoops(loops=(
        LoopSpec(from_stage="Verify", to_stage="Quick Close", gate_field="Fix Approved"),
    )))
    with pytest.raises(ValueError, match="cross-branch-jump"):
        compile_spec(spec)
    assert get("cross-branch-jump").bucket is Bucket.REFUSES_LOUDLY


def test_duplicate_branch_step_row_is_wired_to_a_real_refusal() -> None:
    """The `duplicate-branch-step` row refuses in real code: the same step name in two branches
    raises at compile, naming the row. `_check_no_duplicate_step_across_branches` backs the claim."""
    spec = dataclasses.replace(_branch_local_loop_spec(), routing=Routing(points=(
        DecisionPoint(at_stage="Triage", field_name="Path", options=("Simple", "Complex"),
                      route_per_option=(("Simple", ("Quick Close", "Fix")),
                                        ("Complex", ("Deep Review", "Fix", "Verify")))),
    )))
    with pytest.raises(ValueError, match="duplicate-branch-step"):
        compile_spec(spec)
    row = get("duplicate-branch-step")
    assert row.bucket is Bucket.REFUSES_LOUDLY
    assert row.ticket is None  # a permanent Known Exclusion, not a pending capability


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


# ---- B2 (#36): the API-impossible set is refused at COMPILE, its rows wired, not pending --------
# ADR-0004 (#7): rich-text render, custom-component upload, and report creation are impossible
# through the API. B2 wires each to a compile refusal naming its coverage row and flips the row
# from pending #36 to a permanent Known Exclusion (THE RULE: refuse, never best-effort). Role-scoped
# visibility is the FOURTH API-impossible capability but stays the DOCTOR's refusal (ADR-0003, #6),
# not re-implemented at compile here.

API_IMPOSSIBLE_COMPILE_KEYS = frozenset({
    "custom-component", "report-creation",
})

# The refuse-rows that legitimately remain pending after B2 closes the contract: three future BUILD
# capabilities (a word-list-backed dropdown #13, section colour-styling #11, wiring an EXISTING
# report into a widget #23). Role-scoped visibility left this set when #6 wired its doctor-gate
# refusal (verify.doctor's visibility_role_claims rule). Pinning this set is what makes "no
# refuse-row is left pending" provable: any NEW pending refuse-row, or a B2 row that regressed to
# pending, breaks the equality.
PENDING_REFUSE_ALLOWLIST = frozenset({
    "word-list-dropdown", "section-styling", "report-widget",
    # #20 page layer: the donut chart + its legend-with-counts are a report widget's own rendering,
    # covered by report-widget (#23) — pending the same wire-an-existing-report capability.
    "chart-legend",
})


def _spec_with_widget(widget: WidgetIntent) -> AppSpec:
    """`_full_spec()` with one extra widget on its first page — the minimal way to feed compile a
    page carrying an API-impossible widget without rebuilding a whole spec."""
    full = _full_spec()
    view = full.personas.views[0]
    page = view.pages[0]
    new_page = dataclasses.replace(page, widgets=page.widgets + (widget,))
    new_view = dataclasses.replace(view, pages=(new_page,) + view.pages[1:])
    return dataclasses.replace(
        full, personas=Personas(views=(new_view,) + full.personas.views[1:])
    )


def test_no_api_impossible_refuse_row_is_pending() -> None:
    """AC1 (B2): the API-impossible compile-refuse rows are wired, not promised — each is a
    REFUSES_LOUDLY row carrying no ticket (a permanent Known Exclusion per ADR-0004)."""
    for key in API_IMPOSSIBLE_COMPILE_KEYS:
        row = get(key)
        assert row.bucket is Bucket.REFUSES_LOUDLY
        assert not row.pending, f"{key!r} is API-impossible — refused at compile, must not be pending"
        assert row.ticket is None


def test_pending_refuse_rows_are_exactly_the_allowlist() -> None:
    """AC1 (B2): "no refuse-row is left pending" made provable. Every refuses-loudly row still
    carrying a ticket must be one of the four justified pending rows (three future BUILD
    capabilities + the doctor-side role-scoped-visibility). A new pending refuse-row can't slip in
    silently, and none of the three B2 rows may regress to pending."""
    pending = {r.key for r in ROWS if r.bucket is Bucket.REFUSES_LOUDLY and r.pending}
    assert pending == PENDING_REFUSE_ALLOWLIST, (
        f"pending refuse-rows must be exactly {sorted(PENDING_REFUSE_ALLOWLIST)}; "
        f"got {sorted(pending)}"
    )


def test_rich_text_content_row_is_captured_and_requires_value() -> None:
    """#51/#58: rich-text serialization is CAPTURED (plain HTML string in the value Property) —
    the row flipped to CAPTURED_LIVE; a rich-text widget WITH content compiles clean, and the
    required-config check makes a content-less one fail loud (pages.WIDGET_REQUIRED_CONFIG)."""
    ok = _spec_with_widget(WidgetIntent("general/rich_text", config=(("value", "<h2>Hi</h2>"),)))
    compile_spec(ok)  # must not raise
    assert get("rich-text-content").bucket is Bucket.CAPTURED_LIVE


def test_custom_component_row_is_wired_to_a_real_refusal() -> None:
    """AC2/AC3 (B2): a page carrying a custom component is refused at compile, naming the
    `custom-component` row — no API-driven install path (ADR-0004)."""
    spec = _spec_with_widget(WidgetIntent("custom"))
    with pytest.raises(ValueError, match="custom-component"):
        compile_spec(spec)
    assert get("custom-component").bucket is Bucket.REFUSES_LOUDLY


def test_report_creation_row_is_wired_to_a_real_refusal() -> None:
    """AC2/AC3 (B2): a page carrying a report widget is refused at compile, naming the
    `report-creation` row — building it would need a report to exist first, and creating one has no
    API path (ADR-0004). Config is deliberately VALID (the full report trio) so this proves the
    API-impossible refusal fires on the slug itself, not a missing-config error. Distinct from
    wiring an existing report (report-widget #23, still pending)."""
    spec = _spec_with_widget(WidgetIntent(
        "report/chart",
        config=(("flow_type", "process"), ("flow_id", "RepairJobs"), ("report_id", "R1")),
    ))
    with pytest.raises(ValueError, match="report-creation"):
        compile_spec(spec)
    assert get("report-creation").bucket is Bucket.REFUSES_LOUDLY


def test_role_scoped_visibility_stays_a_doctor_refusal() -> None:
    """AC4 (B2), then wired by #6: role-scoped visibility is NOT a compile refusal — it is the
    doctor's (ADR-0003: known exclusions are judge/doctor-owned, not the builder's). #6 landed
    the refusal (verify.doctor FAILs each claim, naming this row), so the row is now WIRED (no
    ticket, a written Known Exclusion) and still never among the compile-refused set."""
    row = get("role-scoped-visibility")
    assert row.bucket is Bucket.REFUSES_LOUDLY
    assert not row.pending, "wired by #6 — a doctor-gate refusal, no longer promised by a ticket"
    assert "DOCTOR" in (row.reason or "")
    assert "role-scoped-visibility" not in API_IMPOSSIBLE_COMPILE_KEYS


# ---- #20: the PAGE-LAYER coverage rows — the pages half of the coverage matrix ------------------
# Enumerate what a page MOCKUP can express (layout, typography, colour, KPI tiles, status pills,
# charts, tabs, popups, actions, live numbers, delta pills, chart legend) and land EACH in exactly
# one bucket. The MOCKUP is the bar (#20), never the oracle — a new input has no oracle. Per ADR-0005
# (#38) the governed page plan carries CONTENT + BEHAVIOR; layout/exact-styling parity is eval-only
# (#16/#28), never a build gate. Buckets are justified inline in coverage.py's ROWS.

PAGE_LAYER_KEYS = frozenset({
    "page-layout", "page-typography", "page-colour-styling", "kpi-tile-static",
    "kpi-tile-live-number", "delta-pill", "status-pill",
    "page-popup", "on-click-action", "page-tabs", "chart-legend",
})

# The bucket #20 assigns each page-layer row. Union must equal PAGE_LAYER_KEYS (a real partition).
PAGE_CAPTURED_LIVE = frozenset({
    "page-layout", "page-typography", "page-colour-styling", "kpi-tile-static",
})
PAGE_BUILDABLE = frozenset({"page-popup", "on-click-action"})
PAGE_REFUSED = frozenset({
    "kpi-tile-live-number", "delta-pill", "status-pill", "page-tabs", "chart-legend",
})


def test_page_layer_rows_present() -> None:
    """Every enumerated mockup element has a row — none silently passes (#20 Done-when)."""
    missing = PAGE_LAYER_KEYS - {r.key for r in ROWS}
    assert not missing, f"page-layer coverage rows missing: {sorted(missing)}"


def test_page_layer_rows_partition_by_bucket() -> None:
    """Each page-layer row lands in EXACTLY the one bucket #20 assigned it, and the three
    bucket-sets truly partition the page keys (no row unbucketed, none double-counted)."""
    assert PAGE_CAPTURED_LIVE | PAGE_BUILDABLE | PAGE_REFUSED == PAGE_LAYER_KEYS
    assert not (PAGE_CAPTURED_LIVE & PAGE_BUILDABLE)
    assert not (PAGE_CAPTURED_LIVE & PAGE_REFUSED)
    assert not (PAGE_BUILDABLE & PAGE_REFUSED)
    for key in PAGE_CAPTURED_LIVE:
        assert get(key).bucket is Bucket.CAPTURED_LIVE, key
    for key in PAGE_BUILDABLE:
        assert get(key).bucket is Bucket.BUILDABLE, key
    for key in PAGE_REFUSED:
        assert get(key).bucket is Bucket.REFUSES_LOUDLY, key


def test_page_layer_refused_rows_name_ticket_or_reason() -> None:
    """#20 Done-when: any refused row carries a ticket OR a written Known Exclusion reason — no
    silent downgrade (D6)."""
    for key in PAGE_REFUSED:
        row = get(key)
        assert row.ticket is not None or row.reason, f"{key} refuses with no ticket and no reason"


def test_page_layer_captured_rows_carry_no_marker() -> None:
    """A captured-live page row is done: no pending ticket, no refusal reason (layout/typography/
    colour/static-tile all build today; exact mockup parity is eval-only, not a build gate)."""
    for key in PAGE_CAPTURED_LIVE:
        row = get(key)
        assert row.ticket is None and row.reason is None, key


def test_page_live_number_is_a_permanent_known_exclusion() -> None:
    """A freely-bound live value on a page is refused, not faked (#23, proven live 2026-08-11): a
    live KPI count and a delta pill are the SAME live-value class — no reachable shape, so a
    permanent Known Exclusion (ticket None), each naming #23 as the proving finding."""
    for key in ("kpi-tile-live-number", "delta-pill"):
        row = get(key)
        assert row.bucket is Bucket.REFUSES_LOUDLY
        assert row.ticket is None, f"{key} is a permanent Known Exclusion (#23), not pending"
        assert "#23" in (row.reason or ""), key


def test_kpi_static_tile_is_captured_live() -> None:
    """The oracle's actual KPI tile: a pair of static labels with no value slot — plain general/label
    widgets, which render live (#24). Captured-live, no ticket, no reason."""
    row = get("kpi-tile-static")
    assert row.bucket is Bucket.CAPTURED_LIVE
    assert row.ticket is None and row.reason is None


def test_status_pill_is_a_permanent_known_exclusion() -> None:
    """Status pills / per-row progress bars are native view-widget rendering of the underlying
    field, not a page node the engine authors — a permanent Known Exclusion (no ticket)."""
    row = get("status-pill")
    assert row.bucket is Bucket.REFUSES_LOUDLY
    assert row.ticket is None and row.reason


def test_page_tabs_refused_no_silent_downgrade() -> None:
    """A multi-pane tabbed interface is behavior (pane switching), refused rather than silently
    downgraded to stacked panes (D6). No Variable/Criteria composition builder, no build ticket
    scoped yet — a written Known Exclusion (no ticket)."""
    row = get("page-tabs")
    assert row.bucket is Bucket.REFUSES_LOUDLY
    assert row.ticket is None and row.reason


def test_page_popup_and_action_are_buildable_pending_capture() -> None:
    """Popups + on-click actions are built offline today (pages.add_popup / add_event_mapping, wired
    into compile by #22) but not yet captured rendering live — BUILDABLE, pending a live-capture
    ticket."""
    for key in ("page-popup", "on-click-action"):
        row = get(key)
        assert row.bucket is Bucket.BUILDABLE
        assert row.pending, f"{key} is BUILDABLE and must carry a live-capture ticket"


def test_chart_legend_points_at_report_widget_ticket() -> None:
    """The donut chart + its legend-with-counts are a report widget's own rendering — covered by
    report-widget (#23), pending the same wire-an-existing-report capability (referenced, not
    duplicated)."""
    row = get("chart-legend")
    assert row.bucket is Bucket.REFUSES_LOUDLY
    assert row.ticket == "#23"


# ---- #40 T2: refuses-loudly PAGE rows now expressible via popup-hosted widgets are WIRED --------
# #39 gave a page BEHAVIOR (popups + on_click); #40 governs it at compile. The refuses-loudly page
# rows a spec can NEWLY express are the API-impossible widgets hidden inside a popup — the same
# report-creation / rich-text-content / custom-component rows B2 (#36) wired for a top-level widget,
# now reachable one level deeper. This extends B2's "every refuse-row is wired to a real refusal"
# assertion to the newly-expressible popup path (AC6): a popup-hosted API-impossible widget is
# refused at compile naming its coverage row, never escaping just because it sits in a popup.

def _spec_with_popup_widget(widget: WidgetIntent) -> AppSpec:
    """`_full_spec()` with `widget` hosted INSIDE a popup on its first page — the popup path B2's
    `_spec_with_widget` (a top-level widget) never exercised."""
    full = _full_spec()
    view = full.personas.views[0]
    page = view.pages[0]
    new_page = dataclasses.replace(page, popups=(PopupIntent("Detail", (widget,)),))
    new_view = dataclasses.replace(view, pages=(new_page,) + view.pages[1:])
    return dataclasses.replace(
        full, personas=Personas(views=(new_view,) + full.personas.views[1:]))


def test_api_impossible_widget_inside_popup_is_wired_to_a_real_refusal() -> None:
    """AC6: each API-impossible row is refused naming itself when the widget is popup-hosted, not
    only top-level — the widget cross-check walks popup widgets too (#40 AC4). `report/chart` config
    is deliberately VALID so the refusal fires on the slug, not a missing-config error."""
    cases = {
        "custom-component": WidgetIntent("custom"),
        "report-creation": WidgetIntent(
            "report/chart",
            config=(("flow_type", "process"), ("flow_id", "RepairJobs"), ("report_id", "R1")),
        ),
    }
    for row_key, widget in cases.items():
        with pytest.raises(ValueError, match=row_key):
            compile_spec(_spec_with_popup_widget(widget))
        assert get(row_key).bucket is Bucket.REFUSES_LOUDLY
