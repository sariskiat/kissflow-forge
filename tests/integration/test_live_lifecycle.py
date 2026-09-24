"""Live acceptance (ported from the old tests/robot/forge_lifecycle.robot, Node G): ONE full
build-through-teardown lifecycle of a process, against the LIVE dev tenant in a temporary app.
src/app/infrastructure/mcp/server.py, `create_server`, for the forge_* tool surface). BLIND: every
name below is neutral/synthetic ("Sample ..."), no real-app tokens.

Ordered, dependent tests sharing the `ctx` module fixture — a lifecycle is inherently sequential,
and pytest runs a module's tests in file order by default (no randomization plugin installed). Each
numbered test corresponds 1:1 to a step in the original Node G build spec. The `ctx` fixture's
finalizer ALWAYS attempts to delete every artifact this module created, regardless of which test
failed — the same guarantee the old Suite Teardown gave.

Every tool call goes through `live_helpers.call_tool`, an in-process `fastmcp.Client` against
`create_server(lifespan)` (Stage E) -- a failed call raises `ToolError` rather than returning an
`isError` payload, so a call that used to be checked with `assert not result.get("isError")` now
either raises (failing the test with the tool's own message) or is simply not checked again here.

Run with: pytest --run-live tests/integration/test_live_lifecycle.py -q  (skipped by default — see tests/conftest.py)
"""

from __future__ import annotations

import os
from typing import Any

import live_helpers
import pytest

pytestmark = pytest.mark.live

PROCESS_NAME = "Sample Intake Process"
PAGE_NAME = "Sample Intake Hub"


@pytest.fixture(scope="module")
def ctx(request: pytest.FixtureRequest) -> dict[str, Any]:
    live_helpers.load_env_file()
    if not os.environ.get("KF_DEV_ACCESS_KEY_ID"):
        raise pytest.skip.Exception(
            "KF_DEV_ACCESS_KEY_ID not set — no .env / live credentials available"
        )
    state: dict[str, Any] = {
        "server": live_helpers.build_server(),
        "app_id": None,
        "flow_id": None,
        "page_id": None,
        "role_id": None,
        "role_name": None,
    }

    state["app_id"], _ = live_helpers.create_temporary_app(
        state["server"], "Forge live lifecycle app"
    )

    def _cleanup() -> None:
        """Delete every artifact and fail if any deletion cannot be verified."""
        errors: list[str] = []

        def delete(label: str, **kwargs: Any) -> None:
            try:
                result = live_helpers.call_tool(
                    state["server"], "forge_delete_flow", **kwargs
                )
                print(f"{label}: {result}")
                if not getattr(result, "verified", False):
                    errors.append(f"{label} was not verified: {result!r}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label} failed: {exc}")

        if state["page_id"]:
            delete(
                "page delete",
                kind="page",
                flow_id=state["page_id"],
                app_id=state["app_id"],
            )
        else:
            print("no page was created — nothing to delete")

        if state["flow_id"]:
            delete(
                "flow delete",
                kind="process",
                flow_id=state["flow_id"],
                app_id=state["app_id"],
            )
        else:
            print("no flow was created — nothing to delete")

        if state["role_id"]:
            try:
                live_helpers.call_tool(
                    state["server"],
                    "forge_delete_app_role",
                    role_id=state["role_id"],
                    app_id=state["app_id"],
                )
                roles = live_helpers.call_tool(
                    state["server"], "forge_list_app_roles", app_id=state["app_id"]
                )
                listed = (
                    roles.get("roles", []) if isinstance(roles, dict) else roles.roles
                )
                if any(
                    isinstance(role, dict) and role.get("_id") == state["role_id"]
                    for role in listed
                ):
                    errors.append(f"role {state['role_id']} is still listed")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"role cleanup failed: {exc}")

        if state["app_id"]:
            delete(
                "application delete",
                kind="application",
                flow_id=state["app_id"],
            )
            try:
                apps = live_helpers.call_tool(state["server"], "forge_list_apps")
                listed = apps.get("apps", []) if isinstance(apps, dict) else apps.apps
                if any(
                    isinstance(app, dict) and app.get("_id") == state["app_id"]
                    for app in listed
                ):
                    errors.append(f"application {state['app_id']} is still listed")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"application read-back failed: {exc}")

        if errors:
            raise AssertionError(
                "live teardown could not verify cleanup: " + "; ".join(errors)
            )

    request.addfinalizer(_cleanup)
    return state


def test_01_create_sample_process(ctx: dict[str, Any]) -> None:
    """forge_create_process: a scaffolded, publishable draft shell."""
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_create_process",
        name=PROCESS_NAME,
        from_template=False,
        app_id=ctx["app_id"],
    )
    ctx["flow_id"] = live_helpers.response_value(result, "flow_id")


def test_02_harvest_role_members(ctx: dict[str, Any]) -> None:
    """forge_add_member_roles: create a role in the temporary app and grant it to the flow."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to grant members on — step 01 failed")
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_add_member_roles",
        target_flow_id=ctx["flow_id"],
        roles={"Forge lifecycle role": "Forge lifecycle role"},
        app_id=ctx["app_id"],
    )
    resolved = (
        result.get("resolved", {}) if isinstance(result, dict) else result.resolved
    )
    assert resolved
    ctx["role_name"], ctx["role_id"] = next(iter(resolved.items()))


def test_03_apply_sample_fields_and_sections(ctx: dict[str, Any]) -> None:
    """forge_apply_fields: ~8 fields across 3 named sections, one write. No Select field: the
    list inventory is EMPTY — a plain Text field stands in (CLAUDE.md: never guess a literal)."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to add fields to — step 01 failed")
    fields = [
        {"name": "Reference Code", "type": "Text", "required": True},
        {"name": "Requested Date", "type": "Date", "required": False},
        {"name": "Priority", "type": "Text", "required": False},
        {"name": "Summary", "type": "Textarea", "required": True},
        {"name": "Details", "type": "Textarea", "required": False},
        {"name": "Done Flag", "type": "Boolean", "required": False},
        {"name": "Reviewer Note", "type": "Textarea", "required": False},
        {"name": "Outcome", "type": "Text", "required": False},
    ]
    sections = {
        "Intake": ["Reference Code", "Requested Date", "Priority"],
        "Description": ["Summary", "Details"],
        "Review": ["Done Flag", "Reviewer Note", "Outcome"],
    }
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_apply_fields",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        fields=fields,
        sections=sections,
    )
    assert not live_helpers.response_value(result, "missing")


def test_04_add_sample_checklist_table(ctx: dict[str, Any]) -> None:
    """forge_add_table: 2-column child table, MaxRow 3 (Kissflow's native cap)."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to add a table to — step 01 failed")
    columns = [["Item", "Text"], ["Complete", "Boolean"]]
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_add_table",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        name="Checklist",
        columns=columns,
        max_rows=3,
    )
    assert not live_helpers.response_value(result, "missing_columns")


def test_05_build_sample_workflow(ctx: dict[str, Any]) -> None:
    """forge_build_workflow: 3 sequential steps, each assigned the AppRole step 02 granted.
    DESTRUCTIVE — wipes the whole Permission matrix (CLAUDE.md), hence step 07 re-sets visibility
    right after this. Every step is built with the SAME role id step 02 granted, not None — a step
    with no real assignee fails a first submit with a generic 500, not a clean 403 (CLAUDE.md >
    Members first).
    """
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to build a workflow on — step 01 failed")
    role_id = ctx["role_id"]
    steps = [
        ["Intake Review", role_id],
        ["Detail Review", role_id],
        ["Final Review", role_id],
    ]
    roles = {role_id: ctx["role_name"]}
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_build_workflow",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        steps=steps,
        roles=roles,
    )
    assert not live_helpers.response_value(result, "missing_steps")
    # `assigned` is an ECHO of the input steps (the use case computes it from what was requested,
    # never reads the draft back) -- it can never be wrong as long as a role was passed, so it
    # proves nothing on its own. The real proof is the live read-back below.
    assigned_role_ids = live_helpers.resolve_assigned_role_ids(
        ctx["server"], ctx["flow_id"], app_id=ctx["app_id"]
    )
    assert assigned_role_ids == [role_id, role_id, role_id], (
        "read-back Resource nodes do not show all 3 steps assigned to the granted role -- "
        "step 14's walk cannot succeed without this (CLAUDE.md > Members first)"
    )


def test_06_add_sample_goto_gate(ctx: dict[str, Any]) -> None:
    """forge_add_goto_gate: a backward loop from "Final Review" to "Intake Review", gated on the
    Boolean "Done Flag" (never an optional Select — CLAUDE.md > Gate polarity)."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to gate — step 01 failed")
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_add_goto_gate",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        target_activity_name="Intake Review",
        field_name="Done Flag",
    )
    assert live_helpers.response_value(result, "verified")


def test_07_set_sample_visibility(ctx: dict[str, Any]) -> None:
    """forge_set_visibility: re-applied AFTER forge_build_workflow, which wipes every Permission.
    "Intake" section must list Start as an owner or the submission form renders empty (StartEvent
    is position 0)."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to set visibility on — step 01 failed")
    owners = {
        "Intake": ["Start", "Intake Review"],
        "Description": ["Detail Review"],
        "Review": ["Final Review"],
        "Checklist": ["Detail Review"],
    }
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_set_visibility",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        owners=owners,
    )
    assert not live_helpers.response_value(result, "missing")


def test_08_style_sample_section(ctx: dict[str, Any]) -> None:
    """forge_set_styles: only the 2 CONFIRMED design tokens (CLAUDE.md > Styling — tokens are
    UNVALIDATED by the API and fail silently at render if wrong)."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to style — step 01 failed")
    styles: dict[str, dict[str, str | None]] = {
        "Intake": {
            "Section.Bg.Color": "Color.Info.300",
            "Section.Header.Color": "Color.Secondary.Ten.800",
        }
    }
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_set_styles",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        styles=styles,
    )
    assert not live_helpers.response_value(result, "missing")


def test_09_set_sample_field_event(ctx: dict[str, Any]) -> None:
    """forge_set_events: the formula-engine substitute (CLAUDE.md > Field events). Attached to
    "Reference Code" (Type Text, confirmed live trigger "onChange"), scripted as a SELF-reference
    so doctor's "script references a missing field" check can never trip."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to attach an event to — step 01 failed")
    field_ids = live_helpers.resolve_field_ids(
        ctx["server"], ctx["flow_id"], app_id=ctx["app_id"]
    )
    id_ref_code = field_ids["Reference Code"]
    script = f"(async () => {{ kf.form.setFieldValue('{id_ref_code}', 'x'); }})();"
    events: dict[str, list[list[str | None]]] = {
        "Reference Code": [["onChange", script]]
    }
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_set_events",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        events=events,
    )
    assert not live_helpers.response_value(result, "missing")
    assert "Reference Code" in live_helpers.response_value(result, "verified")


def test_10_publish_sample_process(ctx: dict[str, Any]) -> None:
    """forge_publish -> Status Live, read back from the flow's OWN metadata record (never trust
    the publish response alone — CLAUDE.md > THE RULE)."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to publish — step 01 failed")
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_publish",
        kind="process",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
    )
    assert str(live_helpers.response_value(result, "status")) == "Live"
    caller = live_helpers.grant_calling_user_to_role(
        ctx["server"], ctx["flow_id"], ctx["role_id"], ctx["app_id"]
    )
    print(f"caller granted to lifecycle role: {caller}")


def test_11_doctor_reports_the_process_clean(ctx: dict[str, Any]) -> None:
    """forge_doctor -> 0 problems (assert exact). Audits the DRAFT graph, independent of
    live/publish status."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to audit — step 01 failed")
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_doctor",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
    )
    print(result)
    assert not live_helpers.response_value(result, "problems")
    assert live_helpers.response_value(result, "ok")


def test_12_create_and_build_sample_page(ctx: dict[str, Any]) -> None:
    """forge_create_page + forge_build_page: a label + a view/table bound to the new flow with
    FULL binding config (placeholders CANNOT ship — CLAUDE.md > THE RULE). Published right here so
    the built content actually becomes visible to a user.

    Asserts the REAL node-count shape, not just "no error" — a page-build tool that is structurally
    unable to report a problem is not a test of anything.
    """
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to bind a page view to — step 01 failed")
    app_id = ctx["app_id"]
    created = live_helpers.call_tool(
        ctx["server"], "forge_create_page", app_id=app_id, name=PAGE_NAME
    )
    ctx["page_id"] = live_helpers.response_value(created, "page_id")

    steps = [
        {
            "kind": "widget",
            "kwargs": {
                "container_id": "Container001",
                "widget": "general/label",
                "name": "Overview Label",
                "config": {"title": "Sample Intake Overview"},
            },
        },
        {
            "kind": "widget",
            "kwargs": {
                "container_id": "Container001",
                "widget": "view/table",
                "config": {
                    "flow_type": "process",
                    "flow_id": ctx["flow_id"],
                    "view_id": "myitems",
                },
            },
        },
    ]
    built = live_helpers.call_tool(
        ctx["server"],
        "forge_build_page",
        app_id=app_id,
        page_id=ctx["page_id"],
        steps=steps,
        publish=True,
    )
    node_counts = live_helpers.response_value(built, "node_counts")
    missing = live_helpers.response_value(built, "missing")
    published = live_helpers.response_value(built, "published")
    print(f"node_counts={node_counts}")
    assert not missing
    assert node_counts["Component"] == 2
    # The label contributes one FieldMapping/Property pair. The table view shape
    # contributes six more bindings, including its display settings. This exact
    # graph delta is the current captured shape, so a silently reduced widget is
    # still caught by the live read-back.
    assert node_counts["FieldMapping"] == 7
    assert node_counts["Property"] == 7
    assert published, "the page's own content must be published, not just drafted"


def test_13_wire_sample_page_into_navigation(ctx: dict[str, Any]) -> None:
    """forge_set_navigation: Menu -> FieldMapping -> Property{Type:"Page"}."""
    if not ctx["page_id"]:
        raise pytest.skip.Exception("no page to wire into navigation — step 12 failed")
    app_id = ctx["app_id"]
    result = live_helpers.call_tool(
        ctx["server"],
        "forge_set_navigation",
        app_id=app_id,
        page_id=ctx["page_id"],
        label="Sample Intake",
    )
    assert live_helpers.response_value(result, "menu_id") is not None


def test_14_simulate_a_sample_case_end_to_end(ctx: dict[str, Any]) -> None:
    """forge_simulate_case: create an item, fill+verify per step, submit through Start then all 3
    user steps to completion. "Done Flag" is filled TRUE so the goto's `= false()` condition never
    fires — this proves the LINEAR path reaches the end (the loop's structural wiring is what step
    06 + step 11's clean doctor report already prove).

    The fill payload must be keyed by field ID, never name (CLAUDE.md > Item data plane). Submit
    count for a full walk is 1 (StartEvent) + N (the N UserTasks) — CLAUDE.md > Workflow.
    """
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow to simulate a case on — step 01 failed")
    field_ids = live_helpers.resolve_field_ids(
        ctx["server"], ctx["flow_id"], app_id=ctx["app_id"]
    )

    # "Intake" (Reference Code required + Priority) is owned by [Start, Intake Review] in step
    # 07's visibility matrix -- already visible/Required-enforced at Start, so its values must
    # land on the Start hop or the Start submit itself 400s FormValidationError (found live).
    steps = [
        {
            "name": "Start",
            "values": {
                field_ids["Reference Code"]: "REF-0001",
                field_ids["Priority"]: "Normal",
            },
        },
        {"name": "Intake Review", "values": {}},
        {
            "name": "Detail Review",
            "values": {
                field_ids["Summary"]: "Sample summary text",
                field_ids["Details"]: "Sample details text",
            },
        },
        {
            "name": "Final Review",
            "values": {
                field_ids["Done Flag"]: True,
                field_ids["Reviewer Note"]: "Sample reviewer note",
                field_ids["Outcome"]: "Resolved",
            },
        },
    ]

    result = live_helpers.call_tool(
        ctx["server"],
        "forge_simulate_case",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
        steps=steps,
    )
    print(result)
    assert not live_helpers.response_value(result, "failed")
    # `advanced` is an ECHO of the planned step NAMES (the use case appends plan.name on success,
    # never reads it back) -- the REAL, non-echo proof this walk did what it claims is the live
    # status read below.

    iid = live_helpers.response_value(result, "iid")
    status = live_helpers.get_item_status(ctx["flow_id"], iid)
    assert status == "Completed", (
        f"item did not reach Completed after every step advanced -- {result}"
    )
