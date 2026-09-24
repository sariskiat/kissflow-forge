"""Live acceptance for forge_create_template_app (spec #10 seam 2, ticket #13): ONE call creates
a fresh Template App on the LIVE dev tenant carrying the transplanted source template process, published end
to end — then a real item walks Start -> Manager Approve to completion, computed/User field state
is read back, and teardown archives+deletes the app.

Same conventions as test_live_lifecycle.py: ordered dependent tests sharing a module `ctx`
fixture whose finalizer ALWAYS attempts teardown; every tool call goes through
`live_helpers.call_tool`, an in-process `fastmcp.Client` against `create_server(lifespan)`
(Stage E); skipped unless --run-live.

Test 03's item walk needs finer control than `forge_simulate_case`'s declarative `values` map
gives (a probe item to discover the calling user, dataset-record/Reference fill values, a
conditional-validation fill plan) -- it drives `live_helpers.create_item`/`put_fields_raw`/
`submit_item`, the same direct calls against the `ItemService` port the pre-Stage-E version of
this test made against `app.infrastructure.kissflow.dataplane.LiveDataPlane` (now gone).

Run with: pytest --run-live tests/integration/test_live_template_app.py -q
"""

from __future__ import annotations

import os
from typing import Any

import live_helpers
import pytest

pytestmark = pytest.mark.live

APP_NAME = "Sample Template App"


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
        "role_id": None,
        "iid": None,
        "doctor_problems": None,
    }

    def _cleanup() -> None:
        """Delete every artifact and fail if any deletion cannot be verified."""
        errors: list[str] = []

        if state["flow_id"]:
            try:
                flow_del = live_helpers.call_tool(
                    state["server"],
                    "forge_delete_flow",
                    kind="process",
                    flow_id=state["flow_id"],
                    app_id=state["app_id"],
                )
                if not getattr(flow_del, "verified", False):
                    errors.append(f"flow deletion was not verified: {flow_del!r}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"flow deletion failed: {exc}")

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
            try:
                app_del = live_helpers.call_tool(
                    state["server"],
                    "forge_delete_flow",
                    kind="application",
                    flow_id=state["app_id"],
                )
                if not getattr(app_del, "verified", False):
                    errors.append(f"application deletion was not verified: {app_del!r}")
                listed_apps = live_helpers.call_tool(state["server"], "forge_list_apps")
                apps = (
                    listed_apps.get("apps", [])
                    if isinstance(listed_apps, dict)
                    else listed_apps.apps
                )
                if any(
                    isinstance(app, dict) and app.get("_id") == state["app_id"]
                    for app in apps
                ):
                    errors.append(f"application {state['app_id']} is still listed")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"application cleanup failed: {exc}")

        if errors:
            raise AssertionError(
                "live teardown could not verify cleanup: " + "; ".join(errors)
            )

    request.addfinalizer(_cleanup)
    return state


def _field_ids(ctx: dict[str, Any]) -> dict[str, str]:
    """{field NAME: field id} off the LIVE draft — this flow lives in the freshly created app, so
    the app_id must ride along with every app-scoped read."""
    draft = live_helpers.call_tool(
        ctx["server"],
        "kf_get_flow_schema",
        flow_kind="process",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
    )
    return {
        node["Name"]: node_id
        for node_id, node in draft.items()
        if isinstance(node, dict) and node.get("Kind") == "Field" and node.get("Name")
    }


def test_01_one_call_creates_and_publishes_the_template_app(
    ctx: dict[str, Any],
) -> None:
    """forge_create_template_app: name in, published app + builder URL out, doctor riding in the
    response (never a separate call the caller must remember)."""
    result = live_helpers.call_tool(
        ctx["server"], "forge_create_template_app", name=APP_NAME
    )
    print(result)
    app_id = live_helpers.response_value(result, "app_id")
    flow_id = live_helpers.response_value(result, "flow_id")
    role_id = live_helpers.response_value(result, "role_id")
    app_url = live_helpers.response_value(result, "app_url")
    process_url = live_helpers.response_value(result, "process_url")
    doctor = live_helpers.response_value(result, "doctor")
    ctx["app_id"] = app_id
    ctx["flow_id"] = flow_id
    ctx["role_id"] = role_id
    assert live_helpers.response_value(result, "process_status") == "Live"
    assert app_id in app_url
    assert flow_id in process_url
    assert isinstance(doctor, dict) and "problems" in doctor
    ctx["doctor_problems"] = list(doctor["problems"])


def test_02_doctor_bar_is_differential_no_new_problems_beyond_the_capture(
    ctx: dict[str, Any],
) -> None:
    """The vendored capture ships its own quirks — the bar is DIFFERENTIAL: the live transplanted
    flow may show the capture's own problems (baseline = offline transplant + offline doctor over
    the same shape), but never NEW ones. Compared as SETS of id-normalized problem strings (both
    graphs mint their node ids at random, so ids are masked before comparing) — a count-only bar
    would pass when old problems were swapped for fresh breakage."""
    if ctx["doctor_problems"] is None:
        raise pytest.skip.Exception("no doctor report captured — step 01 failed")
    import re

    from app.domain.entities.flow_draft import FlowDraft

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": APP_NAME, "FlowType": "Process"},
    }
    baseline = (
        FlowDraft.from_wire(bare)
        .transplant_template(app_role=(ctx["role_id"], f"{APP_NAME} Role"))
        .problems()
    )

    def _normalize(problem: str) -> str:
        # minted node ids are {Kind}_ + 10 alphanumerics (page_draft._mint)
        return re.sub(r"\b([A-Za-z]+)_[A-Za-z0-9]{10}\b", r"\1_<id>", problem)

    baseline_set = {_normalize(p) for p in baseline.problems}
    live_set = {_normalize(p) for p in ctx["doctor_problems"]}
    print(f"baseline problems ({len(baseline_set)}): {sorted(baseline_set)}")
    print(f"live problems ({len(live_set)}): {sorted(live_set)}")
    new_problems = live_set - baseline_set
    assert not new_problems, (
        f"the live transplanted flow reports problems the capture itself does not ship — "
        f"something new broke beyond the vendored quirks: {sorted(new_problems)}"
    )


def test_03_walk_an_item_through_manager_approve_to_completion(
    ctx: dict[str, Any],
) -> None:
    """A REAL item walks Start -> Manager Approve -> Completed, driving the item data plane
    directly (the same calls forge_simulate_case composes; its fill audit demands exact read-back
    equality, and a Reference value's read-back shape is uncaptured, so the raw calls + a
    non-None discard audit are the honest instrument here). The walk recipe was captured live
    2026-08-20 against this exact template:

    - the caller must be IN the created AppRole first, or the Start submit is refused with
      KISSFLOW_ERROR_050302 ("...anymore" wording, but genuinely a permission refusal — a role
      with zero users means the caller is not a flow member);
    - the capture's 5 `Required` fields need values, including the "ฺBranch" Reference, which
      must be a REAL record dict off the account's own Master_Branch dataset (a bare string PUTs
      200 and is silently discarded — the Select trap, Reference edition);
    - the 4 conditional-validation fields need satisfying values (company-email regex,
      CJ[A-Z]\\d{7} employee id, pbf submit flag != 0).

    The real proof is the live status read-back, never any 200 (THE RULE)."""
    if not ctx["flow_id"]:
        raise pytest.skip.Exception("no flow — step 01 failed")
    import time

    from app.application.use_cases.item._walk import live_aiid

    draft = live_helpers.call_tool(
        ctx["server"],
        "kf_get_flow_schema",
        flow_kind="process",
        flow_id=ctx["flow_id"],
        app_id=ctx["app_id"],
    )
    fields = {
        nid: v
        for nid, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Field"
    }

    recs = live_helpers.call_tool(
        ctx["server"],
        "forge_dataset_records",
        flow_id="Master_Branch",
        op="list",
        app_id=ctx["app_id"],
    )
    data = recs.get("records", []) if isinstance(recs, dict) else recs.records
    assert data, (
        "Master_Branch has no records on this tenant — the Reference fill needs one"
    )
    branch = {"_id": data[0]["_id"], "Name": data[0]["Name"]}

    values: dict[str, Any] = {}
    for nid, v in fields.items():
        name, ftype = v.get("Name", ""), v.get("Type")
        if "FieldValidation::Criteria" in v:
            if "pbf submit flag" in name:
                values[nid] = 1
            elif "รหัสพนักงาน" in name:
                values[nid] = "CJG0000000"
            elif "Email" in name:
                values[nid] = "sample.user@cjexpress.co.th"
        elif v.get("Required"):
            if ftype == "Reference":
                values[nid] = branch
            elif ftype == "Textarea":
                values[nid] = "Sample description for the template walk"
            else:
                values[nid] = "Sample value"
    print(f"fill plan: { {fields[n]['Name']: values[n] for n in values} }")

    # The caller's own user record, discovered from a throwaway item's assignment (no whoami
    # route is captured on this tenant), then granted into the created role.
    probe_item = live_helpers.create_item(ctx["flow_id"])
    probe_detail = live_helpers.get_item_detail(ctx["flow_id"], probe_item["_id"])
    caller = (probe_detail.get("_current_assigned_to") or [None])[0]
    assert caller, (
        f"could not discover the calling user from the item assignment: {probe_detail}"
    )
    granted = live_helpers.call_tool(
        ctx["server"],
        "forge_add_role_users",
        role_id=ctx["role_id"],
        user_ids=[caller],
        app_id=ctx["app_id"],
    )
    print(f"caller into role: {granted}")

    item = live_helpers.create_item(ctx["flow_id"])
    iid, hop1_aiid = item["_id"], item["_activity_instance_id"]

    live_helpers.put_fields_raw(ctx["flow_id"], iid, values)
    after_fill = live_helpers.get_item_detail(ctx["flow_id"], iid)
    # Computed fields (Field::Expression) are server-owned: a direct write there reads back None
    # by design (captured live 2026-08-20), so the silent-discard audit covers only the fields a
    # caller genuinely owns.
    discarded = [
        fields[k]["Name"]
        for k in values
        if after_fill.get(k) is None and "Field::Expression" not in fields[k]
    ]
    assert not discarded, (
        f"fill values silently discarded (PUT 200 proves nothing): {discarded}"
    )

    live_helpers.submit_item(ctx["flow_id"], iid, hop1_aiid)
    detail = live_helpers.get_item_detail(ctx["flow_id"], iid)
    for _ in range(10):
        if detail.get("_current_step") != "Start":
            break
        time.sleep(0.9)
        detail = live_helpers.get_item_detail(ctx["flow_id"], iid)
    assert detail.get("_current_step") == "Manager Approve", (
        f"item did not land on Manager Approve after the Start submit: "
        f"step={detail.get('_current_step')!r} status={detail.get('_status')!r}"
    )

    hop2_aiid = live_aiid(detail)
    live_helpers.submit_item(ctx["flow_id"], iid, hop2_aiid)
    time.sleep(1.5)

    status = live_helpers.get_item_status(ctx["flow_id"], iid)
    assert status == "Completed", f"item did not reach Completed — status {status!r}"
    ctx["iid"] = iid  # only a COMPLETED walk is handed to step 04's read-back


def test_04_read_back_computed_and_user_field_state(ctx: dict[str, Any]) -> None:
    """The transplanted graph's computed field ("request number", Field::Expression) and User
    field ("Requestor User", QueryDefinition sibling) must survive the transplant onto the LIVE
    draft, and their runtime state on the completed item is read back and recorded. Their
    expressions are form-event-driven, so an admin-API walk legitimately leaves them None
    (captured live 2026-08-20) — the read-back proves the fields exist and state is observable,
    never that the source tenant's evaluation chain runs here."""
    if not ctx["iid"]:
        raise pytest.skip.Exception("no completed item — step 03 failed")
    field_ids = _field_ids(ctx)
    assert "request number" in field_ids, (
        "computed field 'request number' missing from the draft"
    )
    assert "Requestor User" in field_ids, (
        "User field 'Requestor User' missing from the draft"
    )

    detail = live_helpers.get_item_detail(ctx["flow_id"], ctx["iid"])
    computed_state = detail.get(field_ids["request number"])
    user_state = detail.get(field_ids["Requestor User"])
    print(
        f"computed 'request number' ({field_ids['request number']}): {computed_state!r}"
    )
    print(f"user 'Requestor User' ({field_ids['Requestor User']}): {user_state!r}")
    assert detail.get("_status") == "Completed", (
        f"read-back item is not the completed walk: {detail.get('_status')!r}"
    )


def test_05_duplicate_app_name_fails_loud(ctx: dict[str, Any]) -> None:
    """A second create with the SAME name must surface the platform's own duplicate error loud —
    no auto-rename, no silent second app. Runs after the walk so a failure here cannot cost the
    expensive build. Asserts no NEW application appeared under this name."""
    if not ctx["app_id"]:
        raise pytest.skip.Exception("no app — step 01 failed")
    from fastmcp.exceptions import ToolError

    duplicate_app_id: str | None = None
    try:
        result = live_helpers.call_tool(
            ctx["server"], "forge_create_template_app", name=APP_NAME
        )
        print(result)
        duplicate_app_id = live_helpers.response_value(result, "app_id")
    except ToolError as exc:
        print(f"duplicate app name refused as expected: {exc}")
    else:
        # The platform accepted a duplicate — delete the accidental second app BEFORE failing,
        # so this negative test never leaks tenant junk the module finalizer doesn't know about.
        second_del = live_helpers.call_tool(
            ctx["server"],
            "forge_delete_flow",
            kind="application",
            flow_id=duplicate_app_id,
        )
        print(f"unexpected duplicate app cleaned up: {second_del}")
        raise AssertionError("duplicate app name must be refused, not auto-renamed")

    listed = live_helpers.call_tool(ctx["server"], "forge_list_apps")
    same_name = [
        a for a in listed.apps if isinstance(a, dict) and a.get("Name") == APP_NAME
    ]
    assert len(same_name) <= 1, f"a second app with the same name appeared: {same_name}"
