"""Live acceptance (ported from the old tests/robot/forge_branching.robot, Node M): CONDITIONAL
branch routing — forge_build_workflow's `parallel` on its own is only ever an UNCONDITIONAL
and-fork. Builds a 3-way Parallel gated by forge_set_branch_conditions, plus a per-branch GotoTask
via forge_add_goto_gate's `branch_name`, against the LIVE dev tenant (KF_APP only). BLIND: every
name below is neutral/synthetic ("Sample .../Tier ..."), no real-app tokens.

THE REAL PROOF (CLAUDE.md > THE RULE): a branch that never fires looks IDENTICAL to one that works
right up until you walk two real items with different values of the deciding field and read back
which step each one actually landed on. Test 10 is that proof — every earlier test here could pass
with the conditions silently inverted, or not wired at all, and still report clean.

Test 11 is the NEGATIVE control: a value matching NO branch condition. It does not park and does
not error — it silently skips the whole Parallel and the item completes with no work done
(CLAUDE.md > Conditional routing's fail-open warning). Asserts the OBSERVED outcome only.

Ordered, dependent tests sharing the `ctx` module fixture, same pattern as test_live_lifecycle.py.

Run with: pytest --run-live tests/test_live_branching.py -q  (skipped by default — see conftest.py)
"""
from __future__ import annotations

import os
from typing import Any

import pytest

import kfforge.server as srv
import live_helpers

pytestmark = pytest.mark.live

PROCESS_NAME = "Sample Branch Process"


@pytest.fixture(scope="module")
def ctx(request: pytest.FixtureRequest) -> dict[str, Any]:
    live_helpers.load_env_file()
    if not os.environ.get("KF_APP"):
        pytest.skip("KF_APP not set — no .env / live credentials available")
    state: dict[str, Any] = {"flow_id": None, "role_id": None, "role_name": None}

    def _cleanup() -> None:
        """Suite Teardown equivalent. Always runs, even if earlier tests failed."""
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
    """forge_member_batch: same account-level AppRole fallback as test_live_lifecycle's own step
    02 (CLAUDE.md > Members first). Every workflow step below — root AND every branch step —
    needs this SAME role id as its real assignee, or a first submit 500s."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to grant members on — step 01 failed")
    result = srv.forge_member_batch(target_flow_id=ctx["flow_id"])
    assert not result.get("isError"), f"member batch (harvest+apply): {result}"
    assert result["role_ids"], "role_ids is EMPTY -- KF_APP now has no grantable AppRole at all"
    assert not result["missing"]
    ctx["role_id"] = result["role_ids"][0]
    ctx["role_name"] = result["harvested"][0]


def test_03_apply_sample_fields(ctx: dict[str, Any]) -> None:
    """forge_apply_fields: the DECIDING field ("Track") plus a Boolean ("Done Flag") for the
    per-branch loop gate. Track is Type Text, not Select: KF_APP's list inventory is EMPTY
    (CLAUDE.md: never synthesize a ReferredList wiring) — same fallback the lifecycle suite uses.
    """
    if not ctx["flow_id"]:
        pytest.skip("no flow to add fields to — step 01 failed")
    fields = [
        {"name": "Track", "type": "Text", "required": False},
        {"name": "Done Flag", "type": "Boolean", "required": False},
    ]
    sections = {"Intake": ["Track"], "Work": ["Done Flag"]}
    result = srv.forge_apply_fields(flow_id=ctx["flow_id"], fields=fields, sections=sections)
    assert not result.get("isError"), f"apply fields + sections: {result}"
    assert not result["missing"]


def test_04_build_sample_three_way_parallel_workflow(ctx: dict[str, Any]) -> None:
    """forge_build_workflow: Start -> Intake -> Parallel("Route", 3 branches, one step each) ->
    End. This alone is still an UNCONDITIONAL and-fork (every branch would run) — test 05 is what
    makes it conditional. DESTRUCTIVE — wipes the whole Permission matrix, hence step 07 re-sets
    visibility right after this."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to build a workflow on — step 01 failed")
    role_id = ctx["role_id"]
    steps = [["Intake", role_id]]
    parallel = {
        "name": "Route",
        "branches": [
            ["Tier Alpha", [["Handle Alpha", role_id]]],
            ["Tier Beta", [["Handle Beta", role_id]]],
            ["Tier Gamma", [["Handle Gamma", role_id]]],
        ],
    }
    roles = {role_id: ctx["role_name"]}
    result = srv.forge_build_workflow(
        flow_id=ctx["flow_id"], steps=steps, parallel=parallel, parallel_after=0, roles=roles
    )
    assert not result.get("isError"), f"build 3-way parallel workflow: {result}"
    assert not result["missing_steps"]


def test_05_set_sample_branch_conditions(ctx: dict[str, Any]) -> None:
    """forge_set_branch_conditions: THIS is the tool that makes the Parallel from step 04
    conditional — Track="Alpha" selects Tier Alpha, "Beta" selects Tier Beta, "Gamma" selects Tier
    Gamma."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to set branch conditions on — step 01 failed")
    branch_literals = {"Tier Alpha": "Alpha", "Tier Beta": "Beta", "Tier Gamma": "Gamma"}
    result = srv.forge_set_branch_conditions(
        flow_id=ctx["flow_id"], field_name="Track", branch_literals=branch_literals
    )
    assert not result.get("isError"), f"set branch conditions: {result}"
    assert not result["missing"]
    verified = result["verified"]
    assert "Tier Alpha" in verified
    assert "Tier Beta" in verified
    assert "Tier Gamma" in verified


def test_06_add_sample_per_branch_goto_gate(ctx: dict[str, Any]) -> None:
    """forge_add_goto_gate with `branch_name` — PINS the GotoTask to one branch's own ProcessDef
    instead of deriving it (possibly wrong) from the target alone. "Handle Beta" exists in exactly
    Tier Beta, so this is belt-and-braces here, not strictly required for disambiguation."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to gate — step 01 failed")
    result = srv.forge_add_goto_gate(
        flow_id=ctx["flow_id"], target_activity_name="Handle Beta", field_name="Done Flag",
        branch_name="Tier Beta",
    )
    assert not result.get("isError"), f"add per-branch goto gate: {result}"
    assert result["verified"]
    assert str(result["branch_name"]) == "Tier Beta"


def test_07_set_sample_visibility(ctx: dict[str, Any]) -> None:
    """forge_set_visibility: re-applied AFTER forge_build_workflow, which wipes every Permission.
    "Work" (Done Flag) is owned by ALL THREE branches' first step — whichever branch actually runs
    for a given item, Done Flag must be reachable there."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to set visibility on — step 01 failed")
    owners = {
        "Intake": ["Start", "Intake"],
        "Work": ["Handle Alpha", "Handle Beta", "Handle Gamma"],
    }
    result = srv.forge_set_visibility(flow_id=ctx["flow_id"], owners=owners)
    assert not result.get("isError"), f"set visibility: {result}"
    assert not result["missing"]


def test_08_publish_sample_process(ctx: dict[str, Any]) -> None:
    """forge_publish -> Status Live, read back from the flow's OWN metadata record (never trust
    the publish response alone — CLAUDE.md > THE RULE)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to publish — step 01 failed")
    result = srv.forge_publish(kind="process", flow_id=ctx["flow_id"])
    assert not result.get("isError"), f"publish process: {result}"
    assert str(result["status"]) == "Live"


def test_09_doctor_reports_the_process_clean(ctx: dict[str, Any]) -> None:
    """forge_doctor -> 0 problems (assert exact). A clean report means the graph doctor considers
    the conditional-Parallel + per-branch-goto shape well-formed, independent of whether the
    conditions actually FIRE correctly at runtime (that's test 10)."""
    if not ctx["flow_id"]:
        pytest.skip("no flow to audit — step 01 failed")
    result = srv.forge_doctor(flow_id=ctx["flow_id"])
    print(result)
    assert not result.get("isError"), f"doctor: {result}"
    assert not result["problems"]
    assert result["ok"]


def test_10_walk_two_items_with_different_track_values_and_show_they_diverge(
    ctx: dict[str, Any],
) -> None:
    """THE REAL PROOF (CLAUDE.md > THE RULE): every test above could pass with the branch
    conditions silently inverted, or genuinely absent, and still report clean. This walks TWO real
    items through the SAME published workflow, one with Track=Alpha and one with Track=Beta, and
    reads back (a DIRECT, non-MCP read of `_current_step`, never an echo of the plan) which
    concrete step each one actually landed on after crossing the conditional Parallel. They must
    differ, and each must match its OWN branch's step name exactly.

    2 hops per item: hop "Start" fills Track and submits, landing on "Intake"; hop "Intake" submits
    again with no further fields — the SAME submit that crosses the Parallel gateway itself, live-
    verified to land directly on the selected branch's own first step, no separate submit needed.
    """
    if not ctx["flow_id"]:
        pytest.skip("no flow to walk — step 01 failed")
    field_ids = live_helpers.resolve_field_ids(ctx["flow_id"])
    id_track = field_ids["Track"]

    a_steps = [{"name": "Start", "values": {id_track: "Alpha"}}, {"name": "Intake", "values": {}}]
    a_result = srv.forge_simulate_case(flow_id=ctx["flow_id"], steps=a_steps)
    assert not a_result.get("isError"), f"walk item A (Track=Alpha): {a_result}"
    assert not a_result["failed"]
    a_step = live_helpers.get_current_step(ctx["flow_id"], a_result["iid"])
    print(f"item A (Track=Alpha) landed on step: {a_step}")

    b_steps = [{"name": "Start", "values": {id_track: "Beta"}}, {"name": "Intake", "values": {}}]
    b_result = srv.forge_simulate_case(flow_id=ctx["flow_id"], steps=b_steps)
    assert not b_result.get("isError"), f"walk item B (Track=Beta): {b_result}"
    assert not b_result["failed"]
    b_step = live_helpers.get_current_step(ctx["flow_id"], b_result["iid"])
    print(f"item B (Track=Beta) landed on step: {b_step}")

    assert a_step == "Handle Alpha", (
        f"item A (Track=Alpha) did not land on Tier Alpha's own step -- got {a_step!r}, "
        "branch condition did not fire as intended"
    )
    assert b_step == "Handle Beta", (
        f"item B (Track=Beta) did not land on Tier Beta's own step -- got {b_step!r}, "
        "branch condition did not fire as intended"
    )
    assert a_step != b_step, (
        "THE REAL PROOF FAILED: both items landed on the SAME step -- "
        "the conditional Parallel did not diverge"
    )


def test_11_walk_a_no_match_value_and_show_it_skips_the_whole_parallel(
    ctx: dict[str, Any],
) -> None:
    """THE FAIL-OPEN HAZARD (CLAUDE.md > Conditional routing): a value matching NO branch's
    condition does not park and does not error — it silently skips the ENTIRE Parallel and the
    item completes with NO WORK DONE. Track="Zulu" matches none of Tier Alpha/Beta/Gamma's own
    literals, so the item's detail must carry NO `_current_step` KEY AT ALL (the key is ABSENT,
    not present with a null value — live-verified, not assumed) and `_status` must read
    "Completed". Asserts the OBSERVED outcome only, never a wished-for one.
    """
    if not ctx["flow_id"]:
        pytest.skip("no flow to walk — step 01 failed")
    field_ids = live_helpers.resolve_field_ids(ctx["flow_id"])
    id_track = field_ids["Track"]

    z_steps = [{"name": "Start", "values": {id_track: "Zulu"}}, {"name": "Intake", "values": {}}]
    z_result = srv.forge_simulate_case(flow_id=ctx["flow_id"], steps=z_steps)
    assert not z_result.get("isError"), f"walk item C (Track=Zulu, matches no branch): {z_result}"
    assert not z_result["failed"]

    z_detail = live_helpers.get_item_detail(ctx["flow_id"], z_result["iid"])
    print(f"no-match item detail: {z_detail}")
    assert "_current_step" not in z_detail, (
        "expected NO _current_step key at all (item skipped the whole Parallel) -- if this key "
        "now appears the platform's fail-open behavior changed and CLAUDE.md > Conditional "
        "routing needs re-verifying"
    )
    assert str(z_detail["_status"]) == "Completed", (
        "expected the item to have completed with no work done -- "
        "see CLAUDE.md > Conditional routing's fail-open warning"
    )
