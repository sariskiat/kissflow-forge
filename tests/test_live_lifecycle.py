"""Live acceptance (ported from the old tests/robot/forge_lifecycle.robot, Node G): ONE full
build-through-teardown lifecycle of a process, against the LIVE dev tenant (KF_APP only — see
kfforge/server.py forge_* tools). BLIND: every name below is neutral/synthetic ("Sample ..."), no
real-app tokens.

Ordered, dependent tests sharing the `ctx` module fixture — a lifecycle is inherently sequential,
and pytest runs a module's tests in file order by default (no randomization plugin installed). Each
numbered test corresponds 1:1 to a step in the original Node G build spec. The `ctx` fixture's
finalizer ALWAYS attempts to delete every artifact this module created, regardless of which test
failed — the same guarantee the old Suite Teardown gave.

Run with: pytest --run-live tests/test_live_lifecycle.py -q  (skipped by default — see conftest.py)
"""
from __future__ import annotations

import os
from typing import Any

import pytest

import kfforge.server as srv
import live_helpers

pytestmark = pytest.mark.live

PROCESS_NAME = "Sample Intake Process"
PAGE_NAME = "Sample Intake Hub"


@pytest.fixture(scope="module")
def ctx(request: pytest.FixtureRequest) -> dict[str, Any]:
    live_helpers.load_env_file()
    if not os.environ.get("KF_APP"):
        pytest.skip("KF_APP not set — no .env / live credentials available")
    state: dict[str, Any] = {"flow_id": None, "page_id": None, "role_id": None, "role_name": None}

    def _cleanup() -> None:
        """Suite Teardown equivalent. Always runs. Logs every deletion, never raises over a
        deletion that comes back unverified — a teardown failure must never mask an earlier
        test failure."""
        if state["page_id"]:
            page_del = srv.forge_delete_flow(
                kind="page", flow_id=state["page_id"], app_id=os.environ["KF_APP"]
            )
            print(f"page delete: {page_del}")
            if not page_del.get("verified"):
                print(f"*WARN* page {state['page_id']} deletion not verified")
        else:
            print("no page was created — nothing to delete")

        if state["flow_id"]:
            flow_del = srv.forge_delete_flow(kind="process", flow_id=state["flow_id"])
            print(f"flow delete: {flow_del}")
            if not flow_del.get("verified"):
                print(f"*WARN* flow {state['flow_id']} deletion not verified")
        else:
            print("no flow was created — nothing to delete")

    request.addfinalizer(_cleanup)
    return state


def test_01_create_sample_process(ctx: dict[str, Any]) -> None:
    """forge_create_process: a scaffolded, publishable draft shell."""
    result = srv.forge_create_process(name=PROCESS_NAME)
    assert not result.get("isError"), f"create process: {result}"
    assert "flow_id" in result
    ctx["flow_id"] = result["flow_id"]


def test_02_harvest_role_members(ctx: dict[str, Any]) -> None:
    """forge_member_batch: with no sibling flow in KF_APP to harvest members from, grants the
    app's OWN AppRoles instead, discovered at the ACCOUNT level (CLAUDE.md > Members first).
    role_ids/harvested are EXPECTED non-empty on this tenant — asserted explicitly: the day this
    tenant has zero grantable AppRoles again, this test must fail loudly, not silently mean
    something different (steps 05/14 both depend on a real role id from here).
    """
    if not ctx["flow_id"]:
        pytest.skip("no flow to grant members on — step 01 failed")
    result = srv.forge_member_batch(target_flow_id=ctx["flow_id"])
    assert not result.get("isError"), f"member batch (harvest+apply): {result}"
    assert result["role_ids"], "role_ids is EMPTY -- KF_APP now has no grantable AppRole at all"
    assert not result["missing"]
    ctx["role_id"] = result["role_ids"][0]
    ctx["role_name"] = result["harvested"][0]


def test_03_apply_sample_fields_and_sections(ctx: dict[str, Any]) -> None:
    """forge_apply_fields: ~8 fields across 3 named sections, one write. No Select field: KF_APP's
    list inventory is EMPTY — a plain Text field stands in (CLAUDE.md: never guess a literal)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to add fields to — step 01 failed")
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
    result = srv.forge_apply_fields(flow_id=ctx["flow_id"], fields=fields, sections=sections)
    assert not result.get("isError"), f"apply fields + sections: {result}"
    assert not result["missing"]


def test_04_add_sample_checklist_table(ctx: dict[str, Any]) -> None:
    """forge_add_table: 2-column child table, MaxRow 3 (Kissflow's native cap)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to add a table to — step 01 failed")
    columns = [["Item", "Text"], ["Complete", "Boolean"]]
    result = srv.forge_add_table(
        flow_id=ctx["flow_id"], name="Checklist", columns=columns, max_rows=3
    )
    assert not result.get("isError"), f"add table: {result}"
    assert not result["missing_columns"]


def test_05_build_sample_workflow(ctx: dict[str, Any]) -> None:
    """forge_build_workflow: 3 sequential steps, each assigned the AppRole step 02 granted.
    DESTRUCTIVE — wipes the whole Permission matrix (CLAUDE.md), hence step 07 re-sets visibility
    right after this. Every step is built with the SAME role id step 02 granted, not None — a step
    with no real assignee fails a first submit with a generic 500, not a clean 403 (CLAUDE.md >
    Members first).
    """
    if not ctx["flow_id"]:
        pytest.skip("no flow to build a workflow on — step 01 failed")
    role_id = ctx["role_id"]
    steps = [["Intake Review", role_id], ["Detail Review", role_id], ["Final Review", role_id]]
    roles = {role_id: ctx["role_name"]}
    result = srv.forge_build_workflow(flow_id=ctx["flow_id"], steps=steps, roles=roles)
    assert not result.get("isError"), f"build workflow: {result}"
    assert not result["missing_steps"]
    # `assigned` is an ECHO of the input steps (kfforge/client.py apply_workflow computes it from
    # what was requested, never reads the draft back) -- it can never be wrong as long as a role
    # was passed, so it proves nothing on its own. The real proof is the live read-back below.
    assigned_role_ids = live_helpers.resolve_assigned_role_ids(ctx["flow_id"])
    assert assigned_role_ids == [role_id, role_id, role_id], (
        "read-back Resource nodes do not show all 3 steps assigned to the granted role -- "
        "step 14's walk cannot succeed without this (CLAUDE.md > Members first)"
    )


def test_06_add_sample_goto_gate(ctx: dict[str, Any]) -> None:
    """forge_add_goto_gate: a backward loop from "Final Review" to "Intake Review", gated on the
    Boolean "Done Flag" (never an optional Select — CLAUDE.md > Gate polarity)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to gate — step 01 failed")
    result = srv.forge_add_goto_gate(
        flow_id=ctx["flow_id"], target_activity_name="Intake Review", field_name="Done Flag"
    )
    assert not result.get("isError"), f"add goto gate: {result}"
    assert result["verified"]


def test_07_set_sample_visibility(ctx: dict[str, Any]) -> None:
    """forge_set_visibility: re-applied AFTER forge_build_workflow, which wipes every Permission.
    "Intake" section must list Start as an owner or the submission form renders empty (StartEvent
    is position 0)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to set visibility on — step 01 failed")
    owners = {
        "Intake": ["Start", "Intake Review"],
        "Description": ["Detail Review"],
        "Review": ["Final Review"],
        "Checklist": ["Detail Review"],
    }
    result = srv.forge_set_visibility(flow_id=ctx["flow_id"], owners=owners)
    assert not result.get("isError"), f"set visibility: {result}"
    assert not result["missing"]


def test_08_style_sample_section(ctx: dict[str, Any]) -> None:
    """forge_set_styles: only the 2 CONFIRMED design tokens (CLAUDE.md > Styling — tokens are
    UNVALIDATED by the API and fail silently at render if wrong)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to style — step 01 failed")
    styles: dict[str, dict[str, str | None]] = {
        "Intake": {
            "Section.Bg.Color": "Color.Info.300",
            "Section.Header.Color": "Color.Secondary.Ten.800",
        }
    }
    result = srv.forge_set_styles(flow_id=ctx["flow_id"], styles=styles)
    assert not result.get("isError"), f"set section style: {result}"
    assert not result["missing"]


def test_09_set_sample_field_event(ctx: dict[str, Any]) -> None:
    """forge_set_events: the formula-engine substitute (CLAUDE.md > Field events). Attached to
    "Reference Code" (Type Text, confirmed live trigger "onChange"), scripted as a SELF-reference
    so doctor's "script references a missing field" check can never trip."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to attach an event to — step 01 failed")
    field_ids = live_helpers.resolve_field_ids(ctx["flow_id"])
    id_ref_code = field_ids["Reference Code"]
    script = f"(async () => {{ kf.form.setFieldValue('{id_ref_code}', 'x'); }})();"
    events = {"Reference Code": [["onChange", script]]}
    result = srv.forge_set_events(flow_id=ctx["flow_id"], events=events)
    assert not result.get("isError"), f"set field event: {result}"
    assert not result["missing"]
    assert "Reference Code" in result["verified"]


def test_10_publish_sample_process(ctx: dict[str, Any]) -> None:
    """forge_publish -> Status Live, read back from the flow's OWN metadata record (never trust
    the publish response alone — CLAUDE.md > THE RULE)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to publish — step 01 failed")
    result = srv.forge_publish(kind="process", flow_id=ctx["flow_id"])
    assert not result.get("isError"), f"publish process: {result}"
    assert str(result["status"]) == "Live"


def test_11_doctor_reports_the_process_clean(ctx: dict[str, Any]) -> None:
    """forge_doctor -> 0 problems (assert exact). Audits the DRAFT graph, independent of
    live/publish status."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to audit — step 01 failed")
    result = srv.forge_doctor(flow_id=ctx["flow_id"])
    print(result)
    assert not result.get("isError"), f"doctor: {result}"
    assert not result["problems"]
    assert result["ok"]


def test_12_create_and_build_sample_page(ctx: dict[str, Any]) -> None:
    """forge_create_page + forge_build_page: a label + a view/table bound to the new flow with
    FULL binding config (placeholders CANNOT ship — CLAUDE.md > THE RULE). Published right here so
    the built content actually becomes visible to a user.

    Asserts the REAL node-count shape, not just "no error" — a page-build tool that is structurally
    unable to report a problem is not a test of anything.
    """
    if not ctx["flow_id"]:
        pytest.skip("no flow to bind a page view to — step 01 failed")
    app_id = os.environ["KF_APP"]
    created = srv.forge_create_page(app_id=app_id, name=PAGE_NAME)
    assert not created.get("isError"), f"create page: {created}"
    ctx["page_id"] = created["page_id"]

    steps = [
        {
            "kind": "widget",
            "kwargs": {
                "container_id": "Container001", "widget": "general/label",
                "name": "Overview Label", "config": {"title": "Sample Intake Overview"},
            },
        },
        {
            "kind": "widget",
            "kwargs": {
                "container_id": "Container001", "widget": "view/table",
                "config": {
                    "flow_type": "process", "flow_id": ctx["flow_id"], "view_id": "myitems",
                },
            },
        },
    ]
    built = srv.forge_build_page(app_id=app_id, page_id=ctx["page_id"], steps=steps, publish=True)
    assert not built.get("isError"), f"build page content: {built}"
    print(f"node_counts={built['node_counts']}")
    assert not built["missing"]
    assert built["node_counts"]["Component"] == 2
    assert built["node_counts"]["FieldMapping"] == 4
    assert built["node_counts"]["Property"] == 4
    assert built["published"], "the page's own content must be published, not just drafted"


def test_13_wire_sample_page_into_navigation(ctx: dict[str, Any]) -> None:
    """forge_set_navigation: Menu -> FieldMapping -> Property{Type:"Page"}."""
    if not ctx["page_id"]:
        pytest.skip("no page to wire into navigation — step 12 failed")
    app_id = os.environ["KF_APP"]
    result = srv.forge_set_navigation(app_id=app_id, page_id=ctx["page_id"], label="Sample Intake")
    assert not result.get("isError"), f"set navigation: {result}"
    assert result["menu_id"] is not None


def test_14_simulate_a_sample_case_end_to_end(ctx: dict[str, Any]) -> None:
    """forge_simulate_case: create an item, fill+verify per step, submit through Start then all 3
    user steps to completion. "Done Flag" is filled TRUE so the goto's `= false()` condition never
    fires — this proves the LINEAR path reaches the end (the loop's structural wiring is what step
    06 + step 11's clean doctor report already prove).

    The fill payload must be keyed by field ID, never name (CLAUDE.md > Item data plane). Submit
    count for a full walk is 1 (StartEvent) + N (the N UserTasks) — CLAUDE.md > Workflow.
    """
    if not ctx["flow_id"]:
        pytest.skip("no flow to simulate a case on — step 01 failed")
    field_ids = live_helpers.resolve_field_ids(ctx["flow_id"])

    # "Intake" (Reference Code required + Priority) is owned by [Start, Intake Review] in step
    # 07's visibility matrix -- already visible/Required-enforced at Start, so its values must
    # land on the Start hop or the Start submit itself 400s FormValidationError (found live).
    steps = [
        {
            "name": "Start",
            "values": {
                field_ids["Reference Code"]: "REF-0001", field_ids["Priority"]: "Normal",
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

    result = srv.forge_simulate_case(flow_id=ctx["flow_id"], steps=steps)
    print(result)
    assert not result.get("isError"), f"simulate case walk to completion: {result}"
    assert not result["failed"]
    # `advanced` is an ECHO of the planned step NAMES (dataplane.py's walk() appends plan.name on
    # success, never reads it back) -- the REAL, non-echo proof this walk did what it claims is
    # the live status read below.

    status = live_helpers.get_item_status(ctx["flow_id"], result["iid"])
    assert status == "Completed", f"item did not reach Completed after every step advanced -- {result}"
