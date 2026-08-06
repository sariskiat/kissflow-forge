"""Kissflow Builder MCP server.

Write/publish are LIVE as of the §2 compliance sign-off (Kissflow AUP §1.10, 2026-08-03) and are
DEV-ONLY by construction: kfforge.client reads only KF_DEV_* and refuses any domain without "dev-".
Every write is read-verify-write with a post-write read-back audit. See PLAN.md / FINDINGS.md.

Two tool families:
  kf_*    the original P0/P1 surface (list types, plan/apply fields, create process, step
          visibility, publish). Unchanged by Node G — kept verbatim.
  forge_* the P2 surface (Node G): thin wrappers around kfforge.client / kfforge.pages_live /
          kfforge.dataplane's live orchestration functions. Every forge_* tool body is ONE call
          into a module function that already does GET -> offline builder -> guarded PUT ->
          READ-BACK verify -> optional publish; the logic lives in the modules, never here (see
          CLAUDE.md "How to work" — this file exists to expose that logic over MCP, not to
          reimplement it).

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

from typing import Any

from fastmcp import FastMCP

from . import tools
from .client import (
    Err,
    KfClient,
    KfConfig,
    apply_field_events,
    apply_fields,
    apply_fields_and_layout,
    apply_goto_gate,
    apply_member_batch,
    apply_report_members,
    apply_section_style,
    apply_step_permissions,
    apply_table,
    apply_workflow,
    create_application_verified,
    create_process,
    delete_anything,
    run_doctor,
)
from .dataplane import LiveDataPlane, StepPlan, walk
from .graph import progressive_matrix
from .pages_live import (
    PageBuildStep,
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
def kf_get_flow_schema(flow_kind: str, flow_id: str) -> dict[str, Any]:
    """Read a flow's DRAFT graph from the dev tenant. Read-only."""
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
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
    """LIVE (dev only, KF_APP): harvest AppRole members from an existing flow in KF_APP and grant
    them on `target_flow_id` — MEMBERS FIRST per CLAUDE.md Permissions (assignees cannot be
    written before members exist; publish then fails MetadataError). Run this BEFORE
    forge_build_workflow's `roles` assignments.

    `source_flow_id` names the flow to harvest FROM; omit it to auto-discover the first other flow
    of `kind` in KF_APP that has at least one member. When KF_APP has no such flow yet (a fresh
    tenant state), this reports harvested=[] with an explanatory `note` rather than failing — a
    caller must be able to tell "nothing to harvest yet" apart from a real error.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_member_batch(c, target_flow_id, source_flow_id, kind=kind))  # type: ignore[arg-type]


@mcp.tool()
def forge_apply_fields(
    flow_id: str,
    fields: list[dict[str, Any]],
    sections: dict[str, list[str]] | None = None,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): add fields to a flow AND lay them out into named sections,
    in ONE guarded write (graph.apply_changes + graph.regroup_into_sections). `sections` maps a
    section title to the field names it should hold; fields not named in any section land in a
    trailing "Other" section — nothing is ever dropped from the layout. Idempotent on the fields
    (a name that already exists is skipped, never duplicated); the section layout is re-applied
    every call, even when no field was actually new.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    specs = [_to_spec(f) for f in fields]
    groups = list(sections.items()) if sections else None
    return _result(apply_fields_and_layout(c, kind, flow_id, specs, groups, publish=publish))  # type: ignore[arg-type]


@mcp.tool()
def forge_add_table(
    flow_id: str,
    name: str,
    columns: list[list[str]],
    max_rows: int | None = None,
    allow_import: bool = False,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): add a child table (a nested Model hosted by a Column, per
    CLAUDE.md "A TABLE is a nested Model, not a field type"). `columns` is `[[name, type], ...]`.
    `max_rows` writes Kissflow's NATIVE row cap (no client-side enforcement needed). Idempotent —
    a table already named `name` is a no-op (no second PUT).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    col_pairs = [(c_name, c_type) for c_name, c_type in columns]
    return _result(apply_table(c, kind, flow_id, name, col_pairs, max_rows=max_rows,  # type: ignore[arg-type]
                               allow_import=allow_import, publish=publish))


@mcp.tool()
def forge_build_workflow(
    flow_id: str,
    steps: list[list[Any]],
    parallel: dict[str, Any] | None = None,
    parallel_after: int | None = None,
    roles: dict[str, str] | None = None,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): replace the WHOLE workflow — Start -> steps ->
    [optional Parallel branches] -> End. `steps` is `[[name, role_id_or_null], ...]`. `roles` maps
    a role id to its display name (used to label each step's Resource/assignee). `parallel`, when
    given, is `{"name": <parallel node name>, "branches": [[branch_name, [[step, role], ...]], ...]}`,
    inserted after `parallel_after` (0-indexed into `steps`).

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
                                  kind=kind))  # type: ignore[arg-type]


@mcp.tool()
def forge_add_goto_gate(
    flow_id: str,
    target_activity_name: str,
    field_name: str,
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): add a backward-jump GotoTask targeting the step named
    `target_activity_name`, gated on the Boolean field named `field_name` (condition
    `<field> = false()`). Gate polarity is enforced (CLAUDE.md Gate polarity): only a Boolean may
    gate a loop, never an optional Select — rejected offline, before any write, if `field_name`
    is not Type Boolean.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_goto_gate(c, flow_id, target_activity_name, field_name,  # type: ignore[arg-type]
                                   publish=publish, kind=kind))


@mcp.tool()
def forge_set_visibility(
    flow_id: str,
    owners: dict[str, list[str]],
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): rebuild a process's per-step section visibility. `owners`
    maps a section NAME to the step names that own it — Editable at the steps that own it, Hidden
    before them, ReadOnly after. DESTRUCTIVE: every existing Permission on the flow is replaced.
    Re-run this after ANY forge_build_workflow call — build_workflow wipes the whole matrix.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    draft = c.get_draft(kind, flow_id)  # type: ignore[arg-type]
    if isinstance(draft, Err):
        return draft.as_tool_result()
    try:
        matrix = progressive_matrix(draft, owners)
    except ValueError as e:
        return Err("verify", str(e)).as_tool_result()
    return _result(apply_step_permissions(c, flow_id, matrix, publish=publish, kind=kind))  # type: ignore[arg-type]


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
    styles: dict[str, dict[str, str | None]],
    kind: str = "process",
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only, KF_APP): colour sections. `styles` maps a section NAME to
    {property: design-token ref}; a value of null removes that property (back to the theme
    default). Colours are TOKEN REFS, never hex — CLAUDE.md warns these are UNVALIDATED by the API
    and fail silently at render if wrong, so only pass a token seen live in the builder's own
    dropdown (two confirmed: Color.Info.300, Color.Secondary.Ten.800).
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(apply_section_style(c, flow_id, styles, publish=publish, kind=kind))  # type: ignore[arg-type]


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
def forge_doctor(flow_id: str, kind: str = "process") -> dict[str, Any]:
    """Read-only health check (dev only, KF_APP): fetch the LIVE draft, harvest every Select
    field's REAL list options (CLAUDE.md: "never guess a literal — read it"), and run
    verify.doctor for real. Run this after ANY builder edit; `ok: true` and `problems: []` mean
    clean. A list whose items fetch fails is recorded in `list_fetch_errors`, never silently
    dropped from the audit.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    return _result(run_doctor(c, flow_id, kind=kind))  # type: ignore[arg-type]


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
    page_id: str,
    steps: list[dict[str, Any]],
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only): add containers/widgets/popups/styles to a page, in ONE guarded
    write. Each step is `{"kind": "container"|"widget"|"popup"|"style", "kwargs": {...}}` —
    `kwargs` are passed straight to the matching kfforge.pages builder
    (add_container/add_widget/add_popup/set_styles). A widget whose binding is load-bearing
    (view/*, report/*, metrics, masterdetail, repeater) REQUIRES its full config —
    CLAUDE.md's THE RULE: a page with a placeholder binding publishes clean and renders broken, so
    this is rejected offline, before any write.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
