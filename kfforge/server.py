"""Kissflow Builder MCP server.

Write/publish are LIVE as of the §2 compliance sign-off (Kissflow AUP §1.10, 2026-08-03) and are
DEV-ONLY by construction: kfforge.client reads only KF_DEV_* and refuses any domain without "dev-".
Every write is read-verify-write with a post-write read-back audit. See PLAN.md / FINDINGS.md.

Three tool families:
  kf_*    the original P0/P1 surface (list types, plan/apply fields, create process, step
          visibility, publish). Kept verbatim by Node G; kf_get_flow_schema later gained an
          optional `app_id` parameter (issue #19) to route a "page" read through the correct
          application-scoped draft URL instead of the generic one — every other kf_* tool, and
          every other flow_kind on this one, is still untouched.
  forge_* the P2 surface (Node G): thin wrappers around kfforge.client / kfforge.pages_live /
          kfforge.dataplane's live orchestration functions. Every forge_* tool body is ONE call
          into a module function that already does GET -> offline builder -> guarded PUT ->
          READ-BACK verify -> optional publish; the logic lives in the modules, never here (see
          CLAUDE.md "How to work" — this file exists to expose that logic over MCP, not to
          reimplement it).
  forge_* the P3 surface (Node K, bottom of the file): kfforge.intake (grill questions, AppSpec,
          compile-to-BuildPlan) + kfforge.design (draw.io diagrams, HTML mockups, the confirmation
          protocol) exposed over MCP. Fully OFFLINE — no Kissflow credentials, no network — and
          STATELESS: the spec is passed in and returned as a plain dict on every call
          (kfforge.intake.serde), since the server itself holds no session state. forge_plan_app
          is the design-before-build gate: it refuses to compile a BuildPlan unless an
          `approval_token` is supplied that matches an HMAC only forge_approve_spec can mint
          (kfforge.server._mint_approval_token, keyed by a per-process secret generated once at
          import time and never exposed by any tool) — a PLAIN content digest is deliberately
          NOT accepted, because a review round proved any tool willing to hash a spec's content
          (forge_request_confirmation/forge_apply_revisions/forge_update_spec included) mints a
          value indistinguishable from "approved" the moment a caller hand-sets `approved: true`,
          since a bare digest proves content-equals-content, never that an approve call happened
          (see forge_plan_app's/forge_approve_spec's own docstrings for the exact bypasses this
          closes, and the honest ceiling of what a stateless, secretless-to-the-caller design can
          actually prove).

⚠️ NO SNAPSHOT, NO ROLLBACK (flagged in node G review, not yet fixed): every write-capable tool
here that takes a `flow_id`/`page_id` you did not just create in the SAME call trusts
`expect_version` alone to guard against a CONCURRENT clobber (a stale-draft PUT is rejected with a
Conflict) — but nothing in this pack snapshots the draft before mutating it, so there is no
rollback artifact if a write goes live in a way you did not want. CLAUDE.md's own working-style
section already says "snapshot the draft before any write to a flow you did not create"; that
discipline currently lives ENTIRELY with the caller (fetch+save `kf_get_flow_schema`'s output
yourself before calling a mutating forge_* tool against an existing flow_id/page_id), not inside
any tool here.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from . import tools
from .capabilities import search_capabilities
from .client import (
    Err,
    KfClient,
    KfConfig,
    apply_add_role_users,
    apply_branch_conditions,
    apply_copilot_ask,
    apply_copilot_check,
    apply_dataset_records,
    apply_field_events,
    apply_field_validation,
    apply_fields,
    apply_fields_and_layout,
    apply_fields_full,
    apply_goto_gate,
    apply_grant_tier,
    apply_layout,
    apply_member_batch,
    apply_member_roles,
    apply_report_members,
    apply_section_style,
    apply_sequence_number,
    apply_set_role_preference,
    apply_step_permissions,
    apply_table,
    apply_word_list,
    apply_workflow,
    create_application_verified,
    create_flow_any,
    create_process,
    delete_anything,
    publish_application_verified,
    run_doctor,
    run_sweep,
)
from .dataplane import LiveDataPlane, StepPlan, walk
from .design import (
    apply_revisions,
    design_bundle_html,
    flow_diagram_xml,
    is_approved,
    request_confirmation,
    schema_diagram_xml,
    spec_digest,
)
from .graph import progressive_matrix, field_override_matrix
from .intake.compile import compile_spec
from .intake.questions import QUESTIONS, next_questions
from .compare import compare_built_to_spec
from .intake.schema import DIMENSION_NAMES, AppSpec, blank_spec
from .intake.serde import spec_from_dict, spec_to_dict, to_wire
from .pages_live import (
    PageBuildStep,
    apply_build_page_op,
    apply_navigation,
    apply_page_build,
    create_page_flow,
)
from .tools import _to_spec

mcp = FastMCP("kissflow-forge")


def _client() -> KfClient | Err:
    cfg = KfConfig.from_env()
    return cfg if isinstance(cfg, Err) else KfClient(cfg)


def _result(x: Any) -> dict[str, Any]:
    """Normalize any orchestration return value to an MCP tool result dict. Every Report dataclass
    in kfforge.client/kfforge.pages_live and every Err carries `.as_tool_result()`; a few
    orchestration functions (run_doctor, apply_report_members, create_application_verified,
    delete_anything) already return a plain dict on their success path — pass those through
    unchanged rather than double-wrapping them."""
    if hasattr(x, "as_tool_result"):
        return x.as_tool_result()
    return x


# =====================================================================================
# kf_* — original P0/P1 surface. Unchanged.
# =====================================================================================


@mcp.tool()
def kf_list_field_types() -> list[str]:
    """List valid Kissflow field types (closed enum; prevents wrong-type errors)."""
    return tools.list_field_types()


@mcp.tool()
def kf_plan_field_change(draft: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """DRY-RUN: preview adding fields to a flow's draft graph. Offline; writes nothing."""
    return tools.plan_field_change(draft, changes)


@mcp.tool()
def kf_get_flow_schema(flow_kind: str, flow_id: str, app_id: str | None = None) -> dict[str, Any]:
    """Read a flow's DRAFT graph from the dev tenant. Read-only. `flow_kind` is
    "process"/"form"/"case" (a flow — `flow_id` is the flow id) or "page" (needs `app_id`,
    `flow_id` is the page id — a page draft lives under its owning application, never a
    hard-coded KF_APP default; see CLAUDE.md Pages). `app_id` is ignored for every other kind.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    if flow_kind == "page":
        if not app_id:
            return Err("verify", "app_id is required to read a page draft").as_tool_result()
        got = c.get_page_draft(app_id, flow_id)
        return got.as_tool_result() if isinstance(got, Err) else got
    got = c.get_draft(flow_kind, flow_id)  # type: ignore[arg-type]
    return got.as_tool_result() if isinstance(got, Err) else got


@mcp.tool()
def kf_apply_field_change(
    flow_kind: str,
    flow_id: str,
    changes: list[dict[str, Any]],
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only): add fields to a flow, verify by read-back, optionally publish.

    Idempotent — a field whose name already exists is skipped, never duplicated. Aborts with a
    conflict if the draft changed since it was read. Show kf_plan_field_change to a human first.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    specs = [_to_spec(ch) for ch in changes]
    report = apply_fields(c, flow_kind, flow_id, specs, publish=publish)  # type: ignore[arg-type]
    return report.as_tool_result()


@mcp.tool()
def kf_create_process(
    name: str,
    steps: list[str],
    fields: list[dict[str, Any]],
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE (dev only): create a NEW process from zero — workflow steps + fields — and verify it.

    `steps` are the UserTask names in order; Start and Completed are added automatically. A failed
    run cleans up after itself and leaves no half-built process behind.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    specs = [_to_spec(f) for f in fields]
    report = create_process(c, name, tuple(steps), specs, publish=publish)
    return report.as_tool_result()


@mcp.tool()
def kf_plan_step_visibility(draft: dict[str, Any], owners: dict[str, list[str]]) -> dict[str, Any]:
    """DRY-RUN: preview per-step section visibility. `owners` maps a section NAME to the step names
    that own it. Offline; writes nothing. Show this to a human before kf_set_step_visibility."""
    return tools.plan_step_visibility(draft, owners)


@mcp.tool()
def kf_set_step_visibility(
    flow_id: str,
    owners: dict[str, list[str]],
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only): rebuild a process's per-step section visibility.

    A section is Editable at the steps that own it, Hidden before them, ReadOnly after. Kissflow has
    no section-level permission, so this writes one Permission node per (field column x step).
    DESTRUCTIVE: every existing Permission on the flow is replaced. Snapshot the draft first.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    draft = c.get_draft("process", flow_id)
    if isinstance(draft, Err):
        return draft.as_tool_result()
    try:
        matrix = progressive_matrix(draft, owners)
    except ValueError as e:
        return Err("verify", str(e)).as_tool_result()
    return apply_step_permissions(c, flow_id, matrix, publish=publish).as_tool_result()


@mcp.tool()
def kf_publish(flow_kind: str, flow_id: str) -> dict[str, Any]:
    """LIVE publish (dev only): compile the flow's draft graph to its live version."""
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    got = c.publish(flow_kind, flow_id)  # type: ignore[arg-type]
    return got.as_tool_result() if isinstance(got, Err) else {"published": True, "flow_id": flow_id}


# =====================================================================================
# forge_* — P2 surface (Node G). Thin wrappers; logic lives in kfforge.client /
# kfforge.pages_live / kfforge.dataplane. Every write tool is dev-only, KF_APP-scoped (KfConfig
# refuses anything else by construction) and read-verify-write with an explicit audit — no tool
# here reports success without a read-back proving it.
# =====================================================================================


@mcp.tool()
def forge_create_process(name: str, publish: bool = False) -> dict[str, Any]:
    """LIVE (dev only, KF_APP): create a new PROCESS shell — a scaffolded, publishable draft with
    no fields and no real workflow yet (a single placeholder step, replaced wholesale by
    forge_build_workflow later). Follow with forge_member_batch, forge_apply_fields,
    forge_add_table, forge_build_workflow, etc. A failed run cleans up after itself (create_process
    archives+deletes the half-built shell rather than leaving it behind).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(create_process(c, name, ("Draft",), [], publish=publish))


@mcp.tool()
def forge_member_batch(
    target_flow_id: str,
    source_flow_id: str | None = None,
    kind: str = "process",
) -> dict[str, Any]:
    """LIVE (dev only, KF_APP): grant AppRole members on `target_flow_id` — MEMBERS FIRST per
    CLAUDE.md Permissions (assignees cannot be written before members exist; publish then fails
    MetadataError). Run this BEFORE forge_build_workflow's `roles` assignments; the granted
    `role_ids` in the result are exactly the ids that belong there.

    Two sources, tried in order: (1) harvest from an existing flow in KF_APP — `source_flow_id`
    names it, or omit to auto-discover the first other flow of `kind` with at least one member;
    (2) when neither is available, grant the app's OWN AppRoles instead, discovered at the
    ACCOUNT level (`Role: "DataAdmin"`, `Permission: ["InitiateItems"]` — proven live 2026-08-07 as
    the exact grant that lets the initiator submit their own draft; `Permission: []` 200s the grant
    but still leaves the initiator refused). Only when BOTH sources come up empty does this report
    harvested=[]/role_ids=[] with an explanatory `note` rather than failing — a caller must be able
    to tell "nothing to grant yet" apart from a real error.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_member_batch(c, target_flow_id, source_flow_id, kind=kind))  # type: ignore[arg-type]


@mcp.tool()
def forge_add_member_roles(
    target_flow_id: str,
    roles: dict[str, str],
    kind: str = "process",
) -> dict[str, Any]:
    """LIVE (dev only, KF_APP): grant AppRoles onto `target_flow_id`, CREATING each role scoped to
    KF_APP first if it does not already exist there. `roles` is `{role_id: display_name}`; matching
    is by NAME — an existing KF_APP-scoped role with that name is reused (idempotent), else one is
    created via `POST /app_role/2/{acct}` (proven live 2026-08-08; CORRECTS the old CLAUDE.md claim
    that only the builder UI creates roles). member/batch rejects any role NOT scoped to KF_APP
    (KISSFLOW_ERROR_00051), so foreign roles cannot be re-granted directly — they must be recreated
    here. Grant is Role=DataAdmin, Permission=["InitiateItems"]. Run BEFORE forge_build_workflow.
    Returns `resolved` = `{display_name: a00_role_id}` so the caller can remap step->name onto
    step->a00_id for build_workflow's `roles=`/step assignees.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_member_roles(c, target_flow_id, roles, kind=kind))  # type: ignore[arg-type]


@mcp.tool()
def forge_create_app_role(
    name: str,
    app_id: str | None = None,
) -> dict[str, Any]:
    """LIVE (dev only): create an AppRole scoped to `app_id` (defaults to KF_APP). PROVEN live
    2026-08-08: `POST /app_role/2/{acct}` body `{"Name": name, "_application_id": app_id}` -> 200
    `{"_id": "RoDy...", "Name": name}`. A role MUST be scoped to KF_APP before member/batch will
    bind it onto one of the app's flows (00051 otherwise). For the idempotent create-then-grant
    path prefer `forge_add_member_roles` (reuses an existing same-name role); this standalone is for
    explicit one-off creation. Returns the new role `_id`.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    rid = c.create_app_role(name, app_id)
    if isinstance(rid, Err):
        return rid.as_tool_result()
    return {"role_id": rid, "name": name, "app_id": app_id or c._cfg.app_id, "isError": False}


@mcp.tool()
def forge_delete_app_role(role_id: str) -> dict[str, Any]:
    """LIVE (dev only): delete an AppRole by id. PROVEN live 2026-08-08: `DELETE /app_role/2/{acct}/
    {role_id}` -> 200 `{"status":"success"}`; re-GET 403s `RoleDoesNotExistsError`, confirming real
    deletion. Use to clean up throwaway roles from probes/failed builds. Verify deletion via the
    list route (`forge_list_app_roles`), never the delete response alone (CLAUDE.md Page DELETE
    warns the same soft-200 trap).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    res = c.delete_app_role(role_id)
    if isinstance(res, Err):
        return res.as_tool_result()
    return {"role_id": role_id, "deleted": True, "isError": False}


@mcp.tool()
def forge_apply_fields(
    flow_id: str,
    fields: list[dict[str, Any]],
    sections: dict[str, list[str]] | None = None,
    validation: dict[str, list[dict[str, str]]] | None = None,
    computed: dict[str, dict[str, Any]] | None = None,
    conditional_visibility: dict[str, dict[str, str]] | None = None,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): add fields to a flow AND lay them out into named sections
    AND (optionally) attach validation/computed/conditional-visibility, in ONE guarded write — the
    build-doctrine "offer the whole field", not bolted on afterward. `sections` maps a section
    title to the field names it should hold; fields not named in any section land in a trailing
    "Other" section — nothing is ever dropped from the layout. Idempotent on the fields (a name
    that already exists is skipped, never duplicated); the section layout is re-applied every
    call, even when no field was actually new.

    Each field dict in `fields` also accepts an optional `default_value` (folds into the Field's
    own `DefaultValue` key — a static literal, or the platform's relative-date keyword `"Today"`
    on a Date field — never guess the casing, read it).

    `validation` maps a field NAME to `[{"operator": "MAX_LENGTH", "rhs": "10",
    "error_message": "optional human text"}, ...]` (docs/capabilities/config.validation.md — wire-
    proven operators: MAX_LENGTH, CONTAINS, GREATER_THAN, AFTER; everything else is Q&A-claimed
    only, verify live before trusting it). `computed` maps a field NAME to a formula AST
    `{"fn": "concatenate", "args": [{"static": "BR-"}, {"field": "Source Number"}]}`
    (docs/capabilities/config.computed.md — the FOURTH Expression owner, Field itself; runtime
    evaluation is UNVERIFIED, graph landing only). `conditional_visibility` maps a field NAME to
    `{"trigger_field": <other field name>, "operator": "EQUAL_TO", "rhs": "true"}`
    (docs/capabilities/config.conditional-visibility.md — the ColumnVisibility Criteria family;
    runtime toggle behavior is graph-verified only, not walked live). Every layer is independently
    read-back verified; a `missing` in any of them marks the whole result `isError`.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    specs = [_to_spec(f) for f in fields]
    groups = list(sections.items()) if sections else None
    return _result(apply_fields_full(c, kind, flow_id, specs, groups,  # type: ignore[arg-type]
                                     validations=validation, computed=computed,
                                     conditional=conditional_visibility, publish=publish))


@mcp.tool()
def forge_apply_layout(
    flow_id: str,
    layout: dict[str, list[list[list[Any]]]],
    descriptions: dict[str, str] | None = None,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): re-place every field at EXACT grid coordinates.

    `layout` is `{section_name: [[(field_name, Start, End), ...], ...]}` — one inner list per Row,
    top-to-bottom; each tuple puts one field column at those 6-unit-grid coordinates. The engine
    rebuilds only Row nodes (Field/Column ids and their Permission/Event back-refs survive). A
    field or section named in `layout` but absent from the draft is a hard error, so a stale layout
    never silently drops a field. Call after forge_apply_fields whenever the auto-tile (3-per-row)
    is not the desired layout. Always writes (a re-layout is a real change even with no new fields).

    `descriptions` optionally sets each section's `Description` (plain string OR a serialized
    rich-text doc) in the SAME write — apply it together with the layout, not as a separate call.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    typed = {sec: [[tuple(t) for t in row] for row in rows] for sec, rows in layout.items()}
    return _result(apply_layout(c, flow_id, typed, descriptions=descriptions,  # type: ignore[arg-type]
                                publish=publish, kind=kind))


@mcp.tool()
def forge_add_table(
    flow_id: str,
    name: str,
    columns: list[list[Any]],
    max_rows: int | None = None,
    allow_import: bool = False,
    kind: str = "process",
    publish: bool = False,
    after_section: str | None = None,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): add a child table (a nested Model hosted by a Column, per
    CLAUDE.md "A TABLE is a nested Model, not a field type"). `columns` is `[[name, type], ...]` or
    `[[name, type, options], ...]` where `options` is an opt-in per-column dict written verbatim onto
    the Field node (e.g. `{"Decimalpoint": 0}` for an integer-only Number). `max_rows` writes
    Kissflow's NATIVE row cap (no client-side enforcement needed). Idempotent — a table already named
    `name` is a no-op (no second PUT). `after_section` places the host row directly after that
    Section's root row — REQUIRED when the table has a banner section, or the stranded banner breaks
    the whole form's render (CLAUDE.md > Tables).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    col_pairs = [(c[0], c[1], c[2] if len(c) > 2 else None) for c in columns]
    return _result(apply_table(c, kind, flow_id, name, col_pairs, max_rows=max_rows,  # type: ignore[arg-type]
                               allow_import=allow_import, publish=publish, after_section=after_section))


@mcp.tool()
def forge_compare_to_spec(
    flow_id: str,
    spec: dict[str, Any],
    kind: str = "process",
) -> dict[str, Any]:
    """LIVE read-only (dev only, KF_APP): does the BUILT flow match what the INPUT asked for?
    (#16 — fidelity, not referential integrity: forge_doctor said `ok` on a build with wrong
    field types, a missing event, spurious Permissions and a misordered table host). Fetches the
    live draft (THE RULE: judge the read-back, never the plan) and diffs it against the spec:
    field inventory by (name, type, ReferredList), root Model::Row order INCLUDING table hosts,
    Permissions on no-Permission columns, style-chain completeness, event (source, trigger)
    inventory, stages/gateway-conditions/loop-gates. Wire this as its own build-order step after
    doctor — every mismatch is named, known-benign exclusions are declared in `ignored`.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    try:
        parsed = spec_from_dict(spec)
    except ValueError as e:
        return {"isError": True, "error": f"spec did not parse: {e}"}
    draft = c.get_draft(kind, flow_id)  # type: ignore[arg-type]
    if isinstance(draft, Err):
        return draft.as_tool_result()
    return compare_built_to_spec(draft, parsed).as_tool_result()


@mcp.tool()
def forge_create_list(
    name: str,
    values: list[str],
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): create-or-reuse a word list by NAME and SET its item
    values (#13, routes probed live 2026-08-12). A list is born LIVE — no publish step. Items
    use REPLACE semantics (the whole array is set each call), so re-running is idempotent.
    Point a Select at it afterwards via forge_apply_fields' `referred_list` (proven end to end:
    a real value persists on an item, a value outside the list PUTs 200 and silently clears the
    field — CLAUDE.md's Select discard rule, which is why values are read back and audited
    here). Lists holding personal data stay HUMAN-MADE (PDPA) — the spec path refuses to compile
    them into this tool; do not route one here by hand either.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_word_list(c, name, values))


@mcp.tool()
def forge_add_sequence_number(
    flow_id: str,
    field_name: str,
    section_name: str,
    prefix: str,
    padding: str,
    step_activity_name: str,
    start: int = 0,
    end: int = 2,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): add an auto-numbered item-id field (`Type:"SequenceNumber"`)
    in its own hidden row at the end of `section_name` (CLAUDE.md "SequenceNumber = auto-numbered
    item id"). The host column is `IsHidden:true` and carries NO per-step Permissions. The
    `prefix` (e.g. "REQ-") is the literal concatenated onto every stamped number; `padding`
    (e.g. "0001") zero-pads it; `step_activity_name` (e.g. "Start") is the activity NAME where the
    runtime stamps the sequence — resolved by name since rebuild activity ids differ from any
    oracle's. `start`/`end` are the 6-unit grid coords of the hidden column. Idempotent. Call this
    AFTER forge_apply_layout so the section's rows are already placed.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_sequence_number(c, flow_id, field_name, section_name, prefix, padding,
                                         step_activity_name, start=start, end=end,
                                         publish=publish, kind=kind))  # type: ignore[arg-type]


@mcp.tool()
def forge_add_field_validation(
    flow_id: str,
    rules: dict[str, list[list[str]]],
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): attach per-field validation rules. `rules` is
    `{field_name: [[operator, value], ...]}`, e.g. `{"meeting link": [["CONTAINS", "microsoft"]]}`.
    Each rule is a flat Condition (Operator + literal RHSValue) under the field's one Criteria node
    (CLAUDE.md F7 — no formula/Expression AST, just a Condition per rule). Idempotent on
    (field, operator, value); a second rule on the same field appends to the existing Criteria.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    norm: dict[str, list[tuple[str, str]]] = {f: [(r[0], r[1]) for r in rs] for f, rs in rules.items()}
    return _result(apply_field_validation(c, flow_id, norm, publish=publish, kind=kind))  # type: ignore[arg-type]


@mcp.tool()
def forge_build_workflow(
    flow_id: str,
    steps: list[list[Any]],
    parallel: dict[str, Any] | None = None,
    parallel_after: int | None = None,
    roles: dict[str, str] | None = None,
    step_meta: dict[str, dict[str, Any]] | None = None,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): replace the WHOLE workflow — Start -> steps ->
    [optional Parallel branches] -> End. `steps` is `[[name, role_id_or_null], ...]`. `roles` maps
    a role id to its display name (used to label each step's Resource/assignee). `parallel`, when
    given, is `{"name": <parallel node name>, "branches": [[branch_name, [[step, role], ...]], ...]}`,
    inserted after `parallel_after` (0-indexed into `steps`).

    `step_meta` (opt-in) maps a step NAME to `{"suspended": bool, "description": str}` (either key
    optional). `suspended` writes `IsSuspended`+`SuspendedAt` — the step is SKIPPED at runtime, the
    slimming-without-stranding lever (CLAUDE.md "IsSuspended"). `description` is the step's prose.

    DESTRUCTIVE: every existing Activity/ProcessDef/Resource/Permission on the flow is replaced
    (CLAUDE.md "build_workflow DELETES every Permission"). Callers MUST re-run
    forge_set_visibility immediately after this.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    step_tuples: list[tuple[str, str | None]] = [(s[0], s[1]) for s in steps]
    par: tuple[str, list[tuple[str, list[tuple[str, str | None]]]]] | None = None
    if parallel:
        branches = [(b[0], [(s[0], s[1]) for s in b[1]]) for b in parallel["branches"]]
        par = (parallel["name"], branches)
    return _result(apply_workflow(c, flow_id, step_tuples, parallel=par,
                                  parallel_after=parallel_after, roles=roles, publish=publish,
                                  kind=kind, step_meta=step_meta))  # type: ignore[arg-type]


@mcp.tool()
def forge_add_goto_gate(
    flow_id: str,
    target_activity_name: str,
    field_name: str,
    branch_name: str | None = None,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): add a backward-jump GotoTask targeting the step named
    `target_activity_name`, gated on the Boolean field named `field_name` (condition
    `<field> = false()`). Gate polarity is enforced (CLAUDE.md Gate polarity): only a Boolean may
    gate a loop, never an optional Select — rejected offline, before any write, if `field_name`
    is not Type Boolean.

    `branch_name`, when given, scopes `target_activity_name` to ONE branch of the flow's single
    Parallel gateway (built via forge_build_workflow's `parallel`) and pins the new GotoTask
    inside that SAME branch's own chain, last within it — the per-branch loop shape a working
    conditional-routing app uses (CLAUDE.md Workflow: a GotoTask never crosses branches; a target
    resolved to a step outside the named branch is rejected offline, before any write). Required
    whenever `target_activity_name` is not unique across branches; omit it for a plain root-chain
    (or otherwise unambiguous) target — unchanged from before this parameter existed.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_goto_gate(c, flow_id, target_activity_name, field_name,  # type: ignore[arg-type]
                                   branch_name=branch_name, publish=publish, kind=kind))


@mcp.tool()
def forge_set_branch_conditions(
    flow_id: str,
    field_name: str,
    branch_literals: dict[str, str],
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): make an existing Parallel's branches CONDITIONAL — each
    branch named in `branch_literals` fires only when the field named `field_name` equals that
    branch's literal (a ProcessDef-owned Expression, `<field> = "<literal>"` — CLAUDE.md
    Expressions). This is the centerpiece of service-tier/triage/approval-routing workflows: a
    forge_build_workflow `parallel` gateway is an UNCONDITIONAL and-fork on its own (every branch
    always runs) until this tool attaches the deciding condition to each one.

    Requires the flow to have exactly ONE Parallel gateway. Every literal is validated against the
    deciding field's REAL live list options — when it is a Select backed by a ReferredList — before
    any write (CLAUDE.md's own war story: a branch that never fired over one mis-cased literal). A
    Text-typed deciding field has no list to validate against and is written as given. Idempotent
    per branch: re-running with a changed literal REPLACES that branch's condition rather than
    accumulating a second one; a branch not named in `branch_literals` is left untouched.

    ⚠️ FAIL-OPEN HAZARD (CLAUDE.md > Conditional routing, verified live 2026-08-07): a value that
    matches NO branch's condition does not park and does not error — the item silently skips the
    WHOLE Parallel and completes with zero work done. The result's `uncovered` list names every
    real Select option (when the deciding field is one) that, after this write, no branch on the
    gateway claims — across the WHOLE gateway, not just the branches this call touched. `uncovered`
    is never an error on its own (a caller may genuinely want an ending value) — it is stated so it
    is never discovered later, exactly the failure mode Gate polarity already warns about for a
    loop, now for a switch.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_branch_conditions(c, flow_id, field_name, branch_literals,  # type: ignore[arg-type]
                                           publish=publish, kind=kind))


@mcp.tool()
def forge_set_visibility(
    flow_id: str,
    owners: dict[str, list[str]],
    field_owners: dict[str, list[str]] | None = None,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): rebuild a process's per-step visibility. `owners` maps a
    section NAME to the step names that own it — Editable there, Hidden before, ReadOnly after
    (section-level). DESTRUCTIVE: every existing Permission on the flow is replaced. Re-run this
    after ANY forge_build_workflow call — build_workflow wipes the whole matrix.

    `field_owners`, when given, is the FIELD-LEVEL lever some apps use instead of (or on top of)
    section-level owners: a section that only HIDES, with editability expressed per field. Maps a
    FIELD NAME to the step names where that one field is Editable; that field gets its own matrix
    row (Editable at the named steps, Hidden in sibling branches the field is not editable in,
    ReadOnly elsewhere) overriding its section's default. Fields not named keep their section's
    matrix. Branch-aware: a branch-private field stays Hidden across a whole sibling branch, not
    ReadOnly-after-last-editable — the case the section rule alone gets wrong.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    draft = c.get_draft(kind, flow_id)  # type: ignore[arg-type]
    if isinstance(draft, Err):
        return draft.as_tool_result()
    try:
        matrix = progressive_matrix(draft, owners)
        field_matrix = field_override_matrix(draft, field_owners) if field_owners else None
    except ValueError as e:
        return Err("verify", str(e)).as_tool_result()
    return _result(apply_step_permissions(c, flow_id, matrix, publish=publish, kind=kind,
                                          field_matrix=field_matrix))  # type: ignore[arg-type]


@mcp.tool()
def forge_set_events(
    flow_id: str,
    events: dict[str, list[list[str]]],
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): attach SDK field events (the formula-engine substitute — see
    CLAUDE.md Field events). `events` maps a field NAME to `[[trigger, script], ...]`. The editor's
    own two parse rules are enforced offline before any write: no top-level `await` (wrap in
    `(async () => {...})();`), and no `KFSDK` reference (only `kf` is injected).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    conv = {name: [(t, s) for t, s in specs] for name, specs in events.items()}
    return _result(apply_field_events(c, flow_id, conv, publish=publish, kind=kind))  # type: ignore[arg-type]


@mcp.tool()
def forge_set_styles(
    flow_id: str,
    styles: dict[str, dict[str, Any]],
    kind: str = "process",
    publish: bool = False,
    root_style: dict[str, Any] | None = None,
    hint_text_position: str | None = None,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): colour sections AND (optionally) the root Model's own
    Appearance/Style chain (#11). `styles` maps a section NAME to {property: value}; a value is
    a bare design-token string (wrapped as {"ref": token}), an explicit {"ref": ...} or
    {"value": ...} dict written verbatim, or null (property removed — back to the theme
    default). `root_style` takes the same shape for the ROOT chain; `hint_text_position` sets
    HintTextPosition on the root Appearance (oracle: "Icon"). On a FORM colours are TOKEN REFS,
    never hex — CLAUDE.md warns tokens are UNVALIDATED by the API and fail silently at render if
    wrong, so only pass one read off the live oracle (Color.Info.300, Color.Secondary.Ten.800,
    Color.Primary.500, Color.Transparent) or the builder's own dropdown.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_section_style(c, flow_id, styles, publish=publish, kind=kind,  # type: ignore[arg-type]
                                       root_style=root_style,
                                       hint_text_position=hint_text_position))


@mcp.tool()
def forge_publish(kind: str, flow_id: str, app_id: str | None = None) -> dict[str, Any]:
    """LIVE publish (dev only, KF_APP): compile a draft to its live version. `kind` is
    "process"/"form"/"case" (a flow — `flow_id` is the flow id), "page" (needs `app_id`,
    `flow_id` is the page id), or "application" (`flow_id` is the app id).

    For a flow (process/form/case), the result includes a read-back `status` field from the
    flow's OWN metadata record (`GET /flow/2/{acct}/{kind}/{id}`, distinct from the draft graph)
    — never trust the publish response alone (CLAUDE.md "THE RULE"); `isError` is set if the
    read-back status is not "Live".
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    if kind == "page":
        if not app_id:
            return Err("verify", "app_id is required to publish a page").as_tool_result()
        got = c.publish_page(app_id, flow_id)
        if isinstance(got, Err):
            return got.as_tool_result()
        return {"kind": kind, "id": flow_id, "published": True, "isError": False}
    if kind == "application":
        got = c.publish_app(flow_id)
        if isinstance(got, Err):
            return got.as_tool_result()
        return {"kind": kind, "id": flow_id, "published": True, "isError": False}

    got = c.publish(kind, flow_id)  # type: ignore[arg-type]
    if isinstance(got, Err):
        return got.as_tool_result()
    detail = c.get_flow_detail(kind, flow_id)  # type: ignore[arg-type]
    if isinstance(detail, Err):
        return {"kind": kind, "id": flow_id, "published": True, "status": None,
                "isError": True, "error": f"publish succeeded but status read-back failed: "
                                          f"{detail.as_tool_result()['error']}"}
    status = detail.get("Status")
    return {"kind": kind, "id": flow_id, "published": True, "status": status,
            "isError": status != "Live"}


@mcp.tool()
def forge_doctor(
    flow_id: str, kind: str = "process",
    visibility_role_claims: list[str] | None = None,
) -> dict[str, Any]:
    """Read-only health check (dev only, KF_APP): fetch the LIVE draft, harvest every Select
    field's REAL list options (CLAUDE.md: "never guess a literal — read it"), and run
    verify.doctor for real. Run this after ANY builder edit; `ok: true` and `problems: []` mean
    clean. A list whose items fetch fails is recorded in `list_fetch_errors`, never silently
    dropped from the audit. Pass the plan's doctor-op `visibility_role_claims` through verbatim
    — each claim FAILs the audit (role-scoped visibility is API-impossible, #6/ADR-0004).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(run_doctor(c, flow_id, kind=kind,  # type: ignore[arg-type]
                               visibility_role_claims=visibility_role_claims))


@mcp.tool()
def forge_create_page(app_id: str, name: str, publish: bool = False) -> dict[str, Any]:
    """LIVE (dev only): create a new app PAGE — a virgin 4-node page graph
    (Page/Container001/Style001) — and verify it via the page LIST route (never the create
    response alone, per CLAUDE.md Page CRUD). Follow with forge_build_page to add content and
    forge_set_navigation to make it reachable.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(create_page_flow(c, app_id, name, publish=publish))


@mcp.tool()
def forge_build_page(
    app_id: str,
    page_id: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    publish: bool = False,
    op: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LIVE write (dev only). TWO entries, exactly one required:

    `op` — the GOVERNED path (#41, ADR-0005): pass a compiled `build_page` op's args verbatim
    (name/widgets/kpis/actions/popups/on_click from forge_plan_app). Creates-or-reuses the page
    by name, builds widgets into the Body, popups with their own widgets, one button per action,
    and the on-click EventMapping wiring (OpenPopup resolves the target popup id from this same
    run). Every sub-item lands in built/skipped/refused + read-back verified/missing — a KPI is
    skipped with its Known-Exclusion reason (#23), a dangling OpenPopup is refused (D6), never a
    dead button.

    `steps` + `page_id` — the raw primitive: each step is `{"kind": "container"|"widget"|
    "popup"|"event"|"style", "kwargs": {...}}` passed straight to the matching kfforge.pages
    builder. A widget whose binding is load-bearing (view/*, report/*, metrics, masterdetail,
    repeater) REQUIRES its full config — THE RULE: a placeholder binding publishes clean and
    renders broken, so it is rejected offline, before any write.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    if (op is None) == (steps is None):
        return {"isError": True,
                "error": "pass exactly one of 'op' (governed compiled build_page op) or "
                         "'steps' (+ 'page_id', raw primitive)"}
    if op is not None:
        return _result(apply_build_page_op(c, app_id, op, publish=publish))
    if not page_id:
        return {"isError": True, "error": "'steps' entry requires 'page_id'"}
    build_steps = [PageBuildStep(kind=s["kind"], kwargs=s.get("kwargs", {})) for s in steps]
    return _result(apply_page_build(c, app_id, page_id, build_steps, publish=publish))


@mcp.tool()
def forge_set_navigation(
    app_id: str,
    page_id: str,
    label: str,
    unify: bool = True,
    sweep: bool = False,
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only): wire a page into the app's navigation — Menu -> FieldMapping ->
    Property{Type:"Page"}. `unify=True` (default) points EVERY Navigation at the same Menu set
    ("same view for all roles", CLAUDE.md App pages — role -> Navigation binding lives OUTSIDE the
    app draft). `sweep=True` additionally drops any Menu no longer reachable from any Navigation.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_navigation(c, app_id, page_id, label, unify=unify, sweep=sweep,
                                    publish=publish))


@mcp.tool()
def forge_share_report(flow_id: str, report_id: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): grant members on a flow REPORT (CLAUDE.md Permissions:
    "Flow REPORTS have the same member surface" as a flow — same member/batch body shape, Role
    "Member" ok). A report with zero members renders "You don't have access to this component" in
    any page chart that uses it. No documented GET route exists for a report's own member list, so
    this is honestly reported as `verified: null` (not independently read-back checked), unlike
    every write-verifying tool above.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_report_members(c, flow_id, report_id, members))


@mcp.tool()
def forge_simulate_case(
    flow_id: str,
    steps: list[dict[str, Any]],
    poll: bool = True,
    poll_tries: int = 8,
    poll_delay: float = 0.9,
) -> dict[str, Any]:
    """LIVE (dev only, KF_APP): walk one item through the documented `/process` data-plane API —
    create, then per step fill-and-verify (never trusts a PUT 200 alone — a discarded/mismatched
    value is caught by re-reading), then advance (submit) or reject. Each step is
    `{"name": str, "values": {...}, "reject": bool, "comment": str}`. Stops at the FIRST failure,
    including a fill that PUT 200 but did not verify — the exact silent-discard trap this data
    plane exists to catch (CLAUDE.md Item data plane).

    `poll` (default True — this tool is live-only, there is no fake/offline caller that would pay
    for it needlessly) waits for the step transition to actually show up (`dataplane.wait_new_aiid`)
    after each advance/reject, before moving to the next step — closing the gap that a fresh submit
    does not always show a rolled-over activity context on the very next read. `poll_tries`/
    `poll_delay` mirror the proven reference implementation's own timing (8 tries, 0.9s apart).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    plans = [
        StepPlan(name=s["name"], values=s.get("values", {}) or {}, reject=bool(s.get("reject", False)),
                 comment=s.get("comment", ""))
        for s in steps
    ]
    report = walk(LiveDataPlane(c), flow_id=flow_id, steps=plans, poll_after_transition=poll,
                  poll_tries=poll_tries, poll_delay=poll_delay)
    return {
        "flow_id": report.flow_id, "iid": report.iid, "created": report.created,
        "planned": list(report.planned), "filled": list(report.filled),
        "advanced": list(report.advanced), "rejected": list(report.rejected),
        "failed": list(report.failed), "error": report.error, "isError": not report.ok(),
    }


@mcp.tool()
def forge_create_app(name: str) -> dict[str, Any]:
    """LIVE (dev only): create a NEW application (`POST /flow/2/{acct}/application`), verified via
    the application LIST route — proven live 2026-08-06 (see the Node G DEV report's probe
    matrix). Deletion needs archive-first, same rule as a process; use
    forge_delete_flow(kind="application", ...).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(create_application_verified(c, name))


@mcp.tool()
def forge_delete_flow(kind: str, flow_id: str, app_id: str | None = None) -> dict[str, Any]:
    """LIVE (dev only): archive+delete a flow (process/form/case), a PAGE (needs `app_id`), or an
    APPLICATION (`kind="application"`, `flow_id` is the app id). Verifies deletion via the
    appropriate LIST route, never the delete response alone — CLAUDE.md Page CRUD: a page DELETE
    returns `{"status":"success"}` for ANY id, even a bogus one, and its draft GET still 200s
    afterward (storage lingers).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return delete_anything(c, kind, flow_id, app_id=app_id)


# =====================================================================================
# forge_* — issue #55 surface additions. Same thin-wrapper contract as the P2 tools above: the
# logic lives in kfforge.client (or kfforge.capabilities for the offline docs tool); every write
# tool is dev-only, KF_APP-scoped, and read-verify-write with an explicit audit.
# =====================================================================================


@mcp.tool()
def forge_add_role_users(
    role_id: str,
    user_query: str | None = None,
    user_ids: list[dict[str, Any]] | None = None,
    app_id: str | None = None,
) -> dict[str, Any]:
    """LIVE write (dev only): grant one or more users onto an AppRole (#52). Give EITHER
    `user_query` (a name/email substring searched via `GET /user/2/{acct}/assignee?q=...`) OR
    `user_ids` (assignee objects `{_id, Kind, Email, Name}` a caller already resolved elsewhere)
    — at least one is required. Existing members are never dropped: the write merges onto the
    role's current `Members`, never replaces it.

    ⚠️ Asymmetric wire keys (CLAUDE.md Pages, RESOLVED 2026-08-12): the role reads back under
    `Members` but must be WRITTEN under `Users` — a body carrying `Members` instead 200s and
    silently no-ops; this tool writes the correct key for you. Verified by re-reading
    `Members`/`UserCount`; `not_found` covers both a `user_query` with zero matches and a
    candidate that was written but failed to verify on read-back.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_add_role_users(c, role_id, user_query=user_query, user_ids=user_ids,
                                        app_id=app_id))


@mcp.tool()
def forge_grant_tier(kind: str, flow_id: str, role_id: str, tier: str) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): grant an AppRole a named permission TIER on a flow
    (shapes/app_role_grant.json note 0, browser-proven 2026-08-12). `kind` is "process" (tiers:
    "No access" | "Initiate" | "Manage") or "case" (adds "Read-only" | "Edit"). "No access" is a
    REAL removal (`DELETE .../member/{role_id}`), never a Permission:[] grant — that shape is
    itself the "Initiate" tier on a process. An unknown `(kind, tier)` pair is refused loudly,
    naming the valid set for that kind, rather than guessing the nearest tier.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_grant_tier(c, kind, flow_id, role_id, tier))  # type: ignore[arg-type]


@mcp.tool()
def forge_create_flow(kind: str, name: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """LIVE (dev only, KF_APP): unified create for `kind` in process|form|list|dataset|case.
    process/form start Draft (build fields/workflow next); list/dataset/case are born LIVE, no
    publish step. `kind="case"` (a board) REQUIRES `extra={"item_type": "Board"|"Case", "prefix":
    <short string>}` — refused loudly before any write when either is missing (the write API
    itself 400s MissingRequiredFieldError on either omission).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(create_flow_any(c, kind, name, extra))


@mcp.tool()
def forge_publish_app(app_id: str) -> dict[str, Any]:
    """LIVE publish (dev only): compile an APPLICATION's draft to its live version, WITH a
    genuine post-publish read-back (THE RULE: a 200 from publish proves nothing by itself) — the
    fresh `meta_version` plus any `Runtime_`-prefixed node id found on the app draft, when one is
    present (⚠️ that shape is UNCAPTURED on this tenant — `runtime_id` is honestly `None` with a
    note when absent, never guessed). Equivalent to `forge_publish(kind="application", ...)` plus
    this extra read-back.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(publish_application_verified(c, app_id))


@mcp.tool()
def forge_dataset_records(
    flow_id: str,
    op: str,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LIVE (dev only, KF_APP): the THIRD data-plane route family — dataform records (#50), a
    flat `POST /dataset/2/{acct}/{flow_id}` + `GET .../list`, distinct from the process item
    data plane and the word-list items route. `op="create"` writes ONE `record` (a dict whose
    `Name` key is the dataform's synthetic unique key — a duplicate 409s cleanly, named in the
    error, never a raw HTTP body). `op="list"` reads back `{Columns, Data}`. No membership gate
    on a dataform (CLAUDE.md-adjacent finding, #50) — record create/list works with zero members.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_dataset_records(c, flow_id, op, record))


@mcp.tool()
def forge_set_role_preference(
    role_id: str,
    default_page: str | None = None,
    default_navigation: str | None = None,
    app_id: str | None = None,
) -> dict[str, Any]:
    """LIVE write (dev only): set an AppRole's own default page/navigation
    (`PUT /app_role/2/{acct}/{role_id}?_application_id={app}` body
    `{"Preference": {"DefaultPage": ..., "DefaultNavigation": ...}}`). The sentinel string
    `"Default"` is valid for either key ("use the platform default"). At least one of
    `default_page`/`default_navigation` is required. Reuses the SAME write route as
    forge_add_role_users, so existing membership is never dropped by this call. Verified by
    re-reading the role's own `Preference` block.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_set_role_preference(c, role_id, default_page=default_page,
                                             default_navigation=default_navigation, app_id=app_id))


@mcp.tool()
def forge_sweep(scope: str, app_id: str | None = None) -> dict[str, Any]:
    """READ-ONLY (dev only): full-inventory discovery sweep. `scope` is one of
    "apps"|"flows"|"pages"|"roles"|"lists"|"all". `app_id` defaults to the configured `KF_APP`.
    Every leakage-prone route (CLAUDE.md: `list_flows`/`list_lists` return the WHOLE ACCOUNT
    without `_application_id`) is already scoped inside the client this sweep uses. Each
    requested sub-scope lands in exactly one bucket per the result's own `status`: `read` (with
    its item count + inventory), `error` (never swallowed), or `skipped` ("pages" only, when no
    app_id is available at all).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return run_sweep(c, scope, app_id=app_id)


@mcp.tool()
def forge_capabilities(query: str = "") -> dict[str, Any]:
    """OFFLINE, read-only: search the docs/capabilities/*.md capability docs + their linked
    shapes/*.json captures. Empty `query` returns the full index (`id`, `name`, `status`,
    `modules` per doc) — the cheapest way to see what is captured at all before building
    anything. A non-empty `query` matches (case-insensitive substring) against a doc's id, name,
    ui_path, status, or body text, and returns each match's full frontmatter + body + every
    linked shape's parsed JSON content inline, so a caller gets the real wire shape in the same
    call instead of a dangling file reference.
    """
    return search_capabilities(query)


@mcp.tool()
def forge_copilot_ask(
    app_id: str,
    message: str,
    expect: list[str] | None = None,
) -> dict[str, Any]:
    """LIVE (dev only): send one message to the app's in-builder AI copilot thread and do ONE
    immediate read-back — deliberately NOT a long poll (an MCP call has a budget; a structural
    build lands ~70s later per the live capture, far past any single-call wait). Returns the
    `conversation_id` to pass into `forge_copilot_check` after a real delay.

    ⚠️ THE RULE, harder here than anywhere else: the reply text is NEVER proof anything landed —
    the thread can still show an OLD clarifying question as newest while the real graph already
    has the change (memory note "REPLY LAGS THE GRAPH", proven live 2026-08-12). `expect`
    (optional: the node kinds this ask should produce, e.g. `["Field"]`) is echoed back for the
    caller's own bookkeeping — verification happens in forge_copilot_check, against a real graph
    read-back, never here.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_copilot_ask(c, app_id, message, expect=expect))


@mcp.tool()
def forge_copilot_check(
    app_id: str,
    conversation_id: str,
    baseline_inventory: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """LIVE, read-only (dev only): the REAL verdict for a prior forge_copilot_ask call — read the
    thread's reply (never trusted alone) AND diff the app's current flow inventory against
    `baseline_inventory` (pass the `results.flows` dict from a `forge_sweep(scope="flows")` call
    made BEFORE the ask).

    Copilot is APP-scoped, not flow-scoped, and has been observed silently building into a
    DIFFERENT flow than the one asked about (memory note "SCATTER CAVEAT", field sweeps
    #45-47) — `scatter` names every flow id that showed up since the baseline, across every kind,
    so a caller never mistakes "nothing in MY target flow" for "copilot did nothing at all".
    `landed_nodes` is a cheap top-level node-count per scattered flow, not a full semantic diff —
    follow up with kf_get_flow_schema/forge_compare_to_spec on a flagged flow id for that.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_copilot_check(c, app_id, conversation_id,
                                       baseline_inventory=baseline_inventory))


# =====================================================================================
# forge_* — P3 surface (Node K): kfforge.intake (grill questions, AppSpec, compile) + kfforge.
# design (draw.io diagrams, HTML mockups, confirmation protocol) exposed over MCP, STATELESS —
# the spec is a plain dict in and out of every call (kfforge.intake.serde), never held here
# between calls. Every tool below is OFFLINE (no Kissflow credentials, no network); forge_plan_app
# is the design-before-build gate: no BuildPlan without an `approval_token` — an HMAC only
# forge_approve_spec can mint (see _mint_approval_token below) — matching this spec's CURRENT
# content. A plain content digest (kfforge.design.spec_digest, freely computable by anyone from
# forge_request_confirmation, forge_apply_revisions, or forge_update_spec) is NOT accepted here,
# on purpose: a review round proved that any tool willing to hash a spec's content mints a value
# indistinguishable from "this was approved" once a caller flips `approved: true` by hand, since a
# bare digest only ever proves content-equals-content, never that an approve call happened for it.
# =====================================================================================

_DEFAULT_FORGE_OUT = Path(tempfile.gettempdir()) / "kfforge_forge_out"

# Question id -> dimension number (1..11), derived from kfforge.intake.questions.QUESTIONS (a
# public dict already keyed by dimension) rather than adding a new accessor to that module —
# next_questions() itself returns a flat tuple of Question with no dimension attached, so this is
# the one piece forge_intake_questions needs that nothing in kfforge.intake exposes directly.
_QUESTION_DIMENSION: dict[str, int] = {q.id: dim for dim, qs in QUESTIONS.items() for q in qs}

# Per-process secret for forge_approve_spec's approval token (see _mint_approval_token). Generated
# ONCE at import time, never logged, never returned by any tool, never derivable from anything a
# caller can observe over MCP — the entire security property of the token rests on this value
# staying inside the process. A restart mints a NEW secret, which is fine and intended: a token
# from a previous process is exactly as stale as a spec that changed after approval, and is
# refused the same way (forge_plan_app has no notion of "this token used to be valid").
_APPROVAL_SECRET: bytes = secrets.token_bytes(32)


def _content_digest(spec: AppSpec) -> str:
    """The one content digest forge_approve_spec and forge_plan_app must always agree on: spec's
    content with `approved` normalized to False before hashing (kfforge.design.spec_digest).
    Shared so the two can never independently drift the way an earlier round found them to (F:
    forge_approve_spec used to digest the spec AS GIVEN while forge_plan_app always normalized, so
    re-approving an already-approved spec minted a digest forge_plan_app then rejected as "the
    spec changed" even though nothing had — normalizing identically on both sides fixes that).
    """
    return spec_digest(dataclasses.replace(spec, approved=False))


def _mint_approval_token(content_digest: str) -> str:
    """HMAC-SHA256 of a content digest under `_APPROVAL_SECRET` — the ONLY value forge_plan_app
    accepts as proof of approval. Only `forge_approve_spec` calls this; nothing else in this
    module ever does, which is the entire point: a caller (or another tool) can always recompute
    `_content_digest` for any content they like — that function is pure and public knowledge — but
    cannot recompute THIS without the secret, so a plain content digest can never be mistaken for
    an approval token, however it was obtained.
    """
    return hmac.new(_APPROVAL_SECRET, content_digest.encode("utf-8"), hashlib.sha256).hexdigest()


def _decode(spec: dict[str, Any]) -> AppSpec | dict[str, Any]:
    """A real AppSpec, or a ready-to-return Err dict on anything that isn't one — every forge_*
    P3 tool starts here so a malformed `spec` argument is reported the same way `_client()`
    reports a missing config, never an unhandled exception escaping through MCP."""
    if not isinstance(spec, dict):
        return Err("verify", f"spec must be an object, got {type(spec).__name__}").as_tool_result()
    try:
        return spec_from_dict(spec)
    except ValueError as e:
        return Err("verify", f"invalid spec: {e}").as_tool_result()


def _blank_or_decode(spec: dict[str, Any] | None) -> AppSpec | dict[str, Any]:
    """Like `_decode`, but `spec=None` means "no answers yet" — the correct starting point for
    forge_intake_questions/forge_update_spec, the only pair of P3 tools a caller may legally
    invoke before any spec exists at all."""
    return blank_spec() if spec is None else _decode(spec)


def _artifact_dir(spec: AppSpec, out_dir: str | None) -> Path:
    """Where a render/confirm tool writes its files: `<out_dir>/<app_name>_<digest>/`, namespaced
    by a content digest so re-rendering the SAME spec overwrites the same files (idempotent) while
    two DIFFERENT specs never collide. `out_dir` defaults to a fixed folder under the system temp
    dir — a server default, not this-or-that caller's own scratch space, since the MCP server has
    no notion of who is calling it or from where."""
    base = Path(out_dir) if out_dir else _DEFAULT_FORGE_OUT
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", spec.app_name).strip("_") or "app"
    # _content_digest, so approving a spec does not relocate its own artifacts to a second folder.
    directory = base / f"{safe_name}_{_content_digest(spec)[:12]}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_artifact(directory: Path, filename: str, content: str) -> str:
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


@mcp.tool()
def forge_intake_questions(spec: dict[str, Any] | None = None, limit: int = 4) -> dict[str, Any]:
    """OFFLINE, stateless: the next questions to ask, most-blocking dimension first, for the gaps
    THIS spec still has (kfforge.intake.questions.next_questions). `spec=None` returns the OPENING
    questions (kfforge.intake.schema.blank_spec() — every one of the 11 dimensions is a gap). Each
    returned question carries its dimension number/name alongside the Thai text/why/example/
    follow-ups `next_questions` itself returns — a caller restricted to MCP has no other way to
    learn which of the 11 dimensions a given question id belongs to. Also returns the spec's
    current gap list (all 11) and blocking-gap list (excludes the advisory timing dimension —
    kfforge.intake.schema.ADVISORY_DIMENSIONS) so a caller can tell how much is left without a
    second round trip.

    The echoed `spec` always carries `approved: false`, regardless of what the input spec's was —
    matching forge_update_spec/forge_apply_revisions (both force it too): this tool is a read
    step, never a place `approved` should survive a round trip unexamined. Without this, asking
    "what's left to answer" on an already-approved spec handed back `approved: true` verbatim —
    one more tool a caller could launder that flag through without ever calling
    forge_approve_spec.
    """
    decoded = _blank_or_decode(spec)
    if isinstance(decoded, dict):
        return decoded
    questions = next_questions(decoded, limit=limit)
    echoed = dataclasses.replace(decoded, approved=False)
    return {
        "questions": [
            {
                "id": q.id,
                "dimension": _QUESTION_DIMENSION[q.id],
                "dimension_name": DIMENSION_NAMES[_QUESTION_DIMENSION[q.id] - 1],
                "text_th": q.text_th,
                "why": q.why,
                "example": q.example,
                "follow_ups": list(q.follow_ups),
            }
            for q in questions
        ],
        "gaps": list(decoded.gaps()),
        "blocking_gaps": list(decoded.blocking_gaps()),
        "spec": spec_to_dict(echoed),
        "isError": False,
    }


@mcp.tool()
def forge_update_spec(spec: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """OFFLINE, stateless: merge Q&A answers into a spec and return the new spec plus its
    remaining gaps. `spec=None` starts from kfforge.intake.schema.blank_spec(). `patch` is a
    SHALLOW merge at AppSpec's own top-level DIMENSION keys (app_name, problem_goal, roles,
    stages, routing, rework_loops, data_model, master_data, visibility, timing, personas,
    test_cases) — each key given REPLACES that whole dimension wholesale; a key omitted from
    `patch` keeps whatever the base spec already had. This is deliberately NOT a deep merge:
    kfforge.intake.schema defines no append/upsert-by-name semantics for e.g. "add one more field
    to data_model.fields", so a caller wanting to change one field reads the whole data_model back
    from the returned spec and supplies it again in full — one unambiguous rule beats a guessed-at
    deep merge. The merged result is re-validated through spec_from_dict, so a structurally bad
    patch (unknown key, wrong shape, bad enum value) is refused naming exactly where, never
    silently applied.

    `approved` is NOT a legal patch key: it is the confirmation gate (forge_approve_spec's own
    job), never a spec dimension a Q&A answer can fill in — a patch naming it is refused outright,
    even to re-assert the same value the base spec already has. A caller round-tripping a WHOLE
    spec back through this tool as its own patch (e.g. `spec_to_dict(...)` verbatim) must strip
    that one key first. The returned spec's `approved` is ALSO always forced to False regardless
    of what the base spec's was — updated content is, by definition, unapproved content, even when
    nothing in `patch` touched `approved` at all (this was a live bypass: update a field on an
    ALREADY-approved spec, and the old `approved: true` rode along untouched into a plan built
    from content nobody actually re-confirmed). Call forge_request_confirmation +
    forge_approve_spec again after any update.
    """
    base = _blank_or_decode(spec)
    if isinstance(base, dict):
        return base
    if not isinstance(patch, dict):
        return Err("verify", f"patch must be an object, got {type(patch).__name__}").as_tool_result()
    if "approved" in patch:
        return Err(
            "verify",
            "'approved' may not be set via forge_update_spec — it is the confirmation gate, not "
            "a spec dimension; strip it from the patch and call forge_approve_spec to grant it",
        ).as_tool_result()
    merged_wire = {**spec_to_dict(base), **patch}
    try:
        merged = spec_from_dict(merged_wire)
    except ValueError as e:
        return Err("verify", f"invalid patch: {e}").as_tool_result()
    merged = dataclasses.replace(merged, approved=False)  # an update is, by definition, unapproved
    return {
        "spec": spec_to_dict(merged),
        "gaps": list(merged.gaps()),
        "blocking_gaps": list(merged.blocking_gaps()),
        "isError": False,
    }


@mcp.tool()
def forge_render_flow_diagram(spec: dict[str, Any], out_dir: str | None = None) -> dict[str, Any]:
    """OFFLINE: render the flow-shape draw.io diagram (kfforge.design.flow_diagram_xml) — stage
    boxes down the spine, decision diamonds, dashed rework-loop back-edges, an unreachable stage
    flagged rather than silently drawn as fine. Written to
    `<out_dir>/<app_name>_<digest>/flow_diagram.drawio` (out_dir defaults to a namespaced folder
    under the system temp dir — see _artifact_dir) and returned inline too, so a caller can hand
    either the text or the path to a human. This tool never refuses on an incomplete spec — it
    renders whatever is there — but ALWAYS echoes `gaps`/`blocking_gaps` alongside the diagram, so
    a caller cannot hand a human a design artifact for a spec that still has gaps without also
    knowing it does.
    """
    decoded = _decode(spec)
    if isinstance(decoded, dict):
        return decoded
    try:
        xml = flow_diagram_xml(decoded)
    except (ValueError, TypeError) as e:
        return Err("verify", f"failed to render flow diagram: {e}").as_tool_result()
    path = _write_artifact(_artifact_dir(decoded, out_dir), "flow_diagram.drawio", xml)
    return {
        "xml": xml, "path": path,
        "gaps": list(decoded.gaps()), "blocking_gaps": list(decoded.blocking_gaps()),
        "isError": False,
    }


@mcp.tool()
def forge_render_schema_diagram(spec: dict[str, Any], out_dir: str | None = None) -> dict[str, Any]:
    """OFFLINE: render the data-shape draw.io diagram (kfforge.design.schema_diagram_xml) — fields
    grouped by stage, tables with their columns/row cap, reference lists with their REAL values.
    Same file-writing contract as forge_render_flow_diagram (see its docstring); file named
    schema_diagram.drawio. Same gaps/blocking_gaps echo too — see forge_render_flow_diagram.
    """
    decoded = _decode(spec)
    if isinstance(decoded, dict):
        return decoded
    try:
        xml = schema_diagram_xml(decoded)
    except (ValueError, TypeError) as e:
        return Err("verify", f"failed to render schema diagram: {e}").as_tool_result()
    path = _write_artifact(_artifact_dir(decoded, out_dir), "schema_diagram.drawio", xml)
    return {
        "xml": xml, "path": path,
        "gaps": list(decoded.gaps()), "blocking_gaps": list(decoded.blocking_gaps()),
        "isError": False,
    }


@mcp.tool()
def forge_render_mockups(spec: dict[str, Any], out_dir: str | None = None) -> dict[str, Any]:
    """OFFLINE: render the combined HTML mockup bundle (kfforge.design.design_bundle_html) —
    per-stage form cards with FAITHFUL field rendering (a Hidden/ReadOnly/computed field never
    renders as a plain live input — CLAUDE.md THE RULE), tables, reference lists, a plain-language
    process summary, and both diagrams inline as collapsible draw.io XML. Written to
    `<out_dir>/<app_name>_<digest>/mockups.html`, same directory-naming contract as the diagram
    tools (see forge_render_flow_diagram). Also returns a short plain-text `summary` (stage/table/
    reference-list/persona-view counts) alongside the full HTML — an agent driving this tool
    cannot itself read rendered HTML, so `summary` and `path` are what it can actually act on; a
    human opens `path` for the real mockup. Same gaps/blocking_gaps echo as the diagram tools.
    """
    decoded = _decode(spec)
    if isinstance(decoded, dict):
        return decoded
    try:
        html = design_bundle_html(decoded)
    except (ValueError, TypeError) as e:
        return Err("verify", f"failed to render mockups: {e}").as_tool_result()
    path = _write_artifact(_artifact_dir(decoded, out_dir), "mockups.html", html)
    summary = (
        f"{len(decoded.stages.stages)} stage(s), {len(decoded.data_model.tables)} table(s), "
        f"{len(decoded.master_data.lists)} reference list(s), "
        f"{len(decoded.personas.views)} persona view(s)"
    )
    return {
        "html": html, "path": path, "summary": summary,
        "gaps": list(decoded.gaps()), "blocking_gaps": list(decoded.blocking_gaps()),
        "isError": False,
    }


@mcp.tool()
def forge_request_confirmation(spec: dict[str, Any], out_dir: str | None = None) -> dict[str, Any]:
    """OFFLINE: build the ConfirmationRequest (kfforge.design.request_confirmation) — both draw.io
    diagrams plus the HTML mockup bundle written to disk, a content digest that changes whenever
    the spec's content does, and one Thai confirm/revise question per risky choice the spec makes
    (each routing literal, loop gate polarity, terminal state, required field, master-data list's
    values). THE RULE (CLAUDE.md): nothing downstream may write to Kissflow until a human has read
    these artifacts and forge_approve_spec has been called with THIS digest. Also echoes
    `gaps`/`blocking_gaps` — this tool does NOT refuse to build a confirmation package for an
    incomplete spec (a customer may reasonably want to see a partial design mid-interview), but a
    human handed only `design.html` with no other signal would have no way to tell "empty because
    nobody has answered dimension 6 yet" from "empty because the app genuinely has no fields."
    """
    decoded = _decode(spec)
    if isinstance(decoded, dict):
        return decoded
    try:
        req = request_confirmation(decoded)
    except (ValueError, TypeError) as e:
        return Err("verify", f"failed to build confirmation request: {e}").as_tool_result()
    directory = _artifact_dir(decoded, out_dir)
    paths = {name: _write_artifact(directory, name, content)
             for name, content in req.artifacts.items()}
    return {
        # _content_digest, NOT req.spec_digest: request_confirmation hashes the spec AS GIVEN, so
        # confirming an already-approved spec would mint a digest forge_approve_spec always
        # rejects as "the spec changed" when nothing changed, and the error's own remedy would
        # return that same wrong digest forever. Both sides must normalize `approved` identically.
        "digest": _content_digest(decoded),
        "artifact_paths": paths,
        "questions": list(req.questions),
        "gaps": list(decoded.gaps()),
        "blocking_gaps": list(decoded.blocking_gaps()),
        "isError": False,
    }


@mcp.tool()
def forge_apply_revisions(spec: dict[str, Any], revisions: dict[str, str]) -> dict[str, Any]:
    """OFFLINE: apply a customer's corrections (kfforge.design.apply_revisions — an explicit key
    vocabulary, e.g. "stage:<name>:rename" / "list:<name>:value:<old>", never a general
    dotted-path setter) and return the new spec plus its NEW digest (kfforge.design.spec_digest —
    ANY revision changes the spec's content, so the digest a customer must approve next is this
    one, never the one they were shown before the revision). The RETURNED spec's `approved` flag
    is ALWAYS forced to False, regardless of what the input spec's was — a revision is, by
    definition, unapproved content, even one applied to an already-approved spec (this used to be
    a live bypass: approve, then revise routing/fields/anything with `approved: true` riding along
    untouched, then plan clean against content nobody actually confirmed).

    Also reports whether the revised spec still compiles, tested against a TEMPORARILY
    force-approved COPY purely to probe structural validity — that probe never affects the
    returned spec's own (always-False) `approved` flag. A KNOWN DEFECT (kfforge.design.confirm's
    own docstring) makes `field:<stage>:<name>:rename` return an uncompilable spec whenever that
    field is referenced elsewhere (a routing point, a loop gate, a computed field, a visibility
    entry, or a test case fill) — this is exactly the case `compiles=False` exists to surface, not
    hide. A revision that fails to APPLY (unknown key, or a key naming something not in this spec)
    is a real tool error (`isError=True`); an applied revision that merely fails to compile is NOT
    an error — the tool did what was asked, and is reporting a true fact about the result.
    """
    decoded = _decode(spec)
    if isinstance(decoded, dict):
        return decoded
    if not isinstance(revisions, dict):
        return Err(
            "verify", f"revisions must be an object, got {type(revisions).__name__}"
        ).as_tool_result()
    try:
        revised = apply_revisions(decoded, revisions)
    except ValueError as e:
        return Err("verify", f"failed to apply revisions: {e}").as_tool_result()
    revised = dataclasses.replace(revised, approved=False)  # a revision is, by definition, unapproved
    try:
        compile_spec(dataclasses.replace(revised, approved=True))
        compiles, compile_error = True, None
    except ValueError as e:
        compiles, compile_error = False, str(e)
    return {
        "spec": spec_to_dict(revised),
        "digest": spec_digest(revised),
        "compiles": compiles,
        "compile_error": compile_error,
        "isError": False,
    }


@mcp.tool()
def forge_approve_spec(spec: dict[str, Any], digest: str, decision: str) -> dict[str, Any]:
    """OFFLINE: record approval and mint the ONLY value forge_plan_app accepts.

    Refuses unless `digest` matches THIS spec's content digest (kfforge.design.spec_digest, with
    `approved` normalized to False before hashing — see _content_digest. EVERY producer of a
    digest normalizes the same way: this tool, forge_plan_app, forge_request_confirmation and
    _artifact_dir. They must stay in lockstep — when they did not, re-approving an already-approved
    spec was refused as "the spec changed" when nothing had, and the error's own suggested remedy
    returned that same rejected digest forever) and `decision` is the exact literal "approve"
    (kfforge.design.is_approved — a typo, "Approve", "approved", or a revise request are all
    refused, never guessed into a yes). A stale digest means the spec changed (e.g. via
    forge_apply_revisions) after the customer looked at the confirmation artifacts — refused,
    naming both digests, rather than silently approving content the customer never actually saw.

    Returns the spec with `approved` set True, its plain content `digest` (harmless to expose —
    kept for a caller that just wants to show/detect drift, same meaning forge_request_confirmation/
    forge_apply_revisions already return under that name), AND `approval_token`: an HMAC of that
    digest under a secret generated once per server process (_APPROVAL_SECRET), never logged,
    never returned by any other tool. forge_plan_app now demands `approval_token`, never a plain
    `digest` — a review round proved that ANY tool willing to hash a spec's content (this one
    included, and forge_request_confirmation/forge_apply_revisions besides) mints a value
    indistinguishable from "approved" once a caller flips `approved: true` by hand, since a bare
    digest proves only "this content was hashed once," never that an explicit approve call
    happened for it. Only this function holds the secret, so only a real call here can produce a
    token forge_plan_app accepts — hashing the same bytes anywhere else, however many times,
    cannot forge one.

    HONEST CEILING: this proves "exactly one explicit forge_approve_spec call happened, bound to
    this exact content, and no other route can forge that fact." It does NOT and CANNOT prove a
    HUMAN, rather than the calling agent, made the decision — no stateless MCP surface with no
    out-of-band channel to a person can prove that; `decision` is still just a string an agent
    could type "approve" into itself. The gate closes every route from "content nobody signed off
    on through this call" to a live build — it is not, and cannot be, human authentication.
    """
    decoded = _decode(spec)
    if isinstance(decoded, dict):
        return decoded
    current = _content_digest(decoded)
    if digest != current:
        return Err(
            "verify",
            f"stale digest: given {digest!r}, current spec digest is {current!r} — the spec "
            f"changed since this digest was shown to the customer; re-run "
            f"forge_request_confirmation and show the NEW digest before approving",
        ).as_tool_result()
    if not is_approved(decoded, decision):
        return Err(
            "verify",
            f"decision {decision!r} is not an explicit approval — must be exactly 'approve'",
        ).as_tool_result()
    approved_spec = dataclasses.replace(decoded, approved=True)
    return {
        "spec": spec_to_dict(approved_spec),
        "approved": True,
        "digest": current,
        "approval_token": _mint_approval_token(current),
        "isError": False,
    }


@mcp.tool()
def forge_plan_app(spec: dict[str, Any], approval_token: str) -> dict[str, Any]:
    """OFFLINE: compile an APPROVED, COMPLETE spec to its ordered BuildPlan
    (kfforge.intake.compile.compile_spec) — THE GATE.

    Refuses UNLESS `approval_token` is the exact HMAC forge_approve_spec minted for this spec's
    CURRENT content digest (approved normalized to False before hashing — see _content_digest).
    This is deliberately NOT a plain content digest. A review round proved that a content-digest
    gate is forgeable four ways, because ANY tool that hashes the same content mints a value
    indistinguishable from what the gate wants, with no approve call required at all:
      - call forge_request_confirmation (read-only), hand-set `approved: true`, plan with its digest
      - mutate an approved spec's routing/owner_role, RE-confirm the mutant for a fresh matching
        digest, plan the mutant with THAT — the customer approved design A, the plan is A-prime
      - forge_apply_revisions returns a plain digest for its (approved-forced-False) result — flip
        `approved` back to true by hand, plan with that digest
      - same shape through forge_update_spec chained into forge_request_confirmation
    All four share one root cause (a bare digest proves content-equals-content, never "an approve
    call happened") and one fix: only forge_approve_spec holds `_APPROVAL_SECRET`, so only an
    actual call to it can mint a token this check accepts. A caller who never called
    forge_approve_spec, or whose content changed afterward by so much as one field, has no
    token that verifies — refused here, before `compile_spec` ever runs, naming that the spec was
    never approved (or changed since).

    HONEST CEILING: this proves "exactly one explicit forge_approve_spec call happened, bound to
    this exact content, and nothing else can forge that fact." It does NOT and CANNOT prove a
    HUMAN, rather than the calling agent, approved — see forge_approve_spec's own docstring.

    Only past the token check does this refuse a spec whose `approved` flag is not True (call
    forge_approve_spec first), or one with blocking gaps, NAMING every dimension still missing (so
    a caller can go straight back to forge_intake_questions) — compile_spec's own two refusals,
    unchanged, kept as a second (weaker) check: a valid token only proves the CONTENT was approved,
    since the token verification normalizes `approved` away — a caller could in principle present
    approved content with `approved: false` re-set by hand, which the token alone would not catch,
    but compile_spec's own check does. No build may ever start before an explicit approval bound
    to the EXACT design being built (CLAUDE.md "THE RULE").
    """
    decoded = _decode(spec)
    if isinstance(decoded, dict):
        return decoded
    current = _content_digest(decoded)
    expected_token = _mint_approval_token(current)
    # Compare as BYTES: hmac.compare_digest raises TypeError on str carrying any non-ASCII
    # character (a smart quote from a paste, a Thai-speaking agent), and this tool's contract is
    # to return a structured refusal, never to raise through MCP.
    if not hmac.compare_digest(approval_token.encode("utf-8"), expected_token.encode("utf-8")):
        return Err(
            "verify",
            "invalid or stale approval_token — this exact content was never approved with "
            "forge_approve_spec (or was, then changed afterward); a plain digest from "
            "forge_request_confirmation/forge_apply_revisions/forge_update_spec is NOT an "
            "approval_token, no matter how it was obtained — re-run forge_request_confirmation, "
            "get an explicit forge_approve_spec call, and plan with the approval_token IT returns",
        ).as_tool_result()
    try:
        plan = compile_spec(decoded)
    except ValueError as e:
        return Err("verify", str(e)).as_tool_result()
    return {
        "ops": [to_wire(op) for op in plan.ops],
        "summary": plan.summary(),
        "op_count": len(plan.ops),
        "isError": False,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
