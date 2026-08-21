"""Live acceptance for forge_create_template_app (spec #10 seam 2, ticket #13): ONE call creates
a fresh Template App on the LIVE dev tenant carrying the transplanted source template process, published end
to end — then a real item walks Start -> Manager Approve to completion, computed/User field state
is read back, and teardown archives+deletes the app.

Same conventions as test_live_lifecycle.py: ordered dependent tests sharing a module `ctx`
fixture whose finalizer ALWAYS attempts teardown; direct in-process calls to kfforge.server's own
tool functions; skipped unless --run-live.

Run with: pytest --run-live tests/test_live_template_app.py -q
"""
from __future__ import annotations

import os
from typing import Any

import pytest

import kfforge.server as srv
import live_helpers

pytestmark = pytest.mark.live

APP_NAME = "Sample Template App"


@pytest.fixture(scope="module")
def ctx(request: pytest.FixtureRequest) -> dict[str, Any]:
    live_helpers.load_env_file()
    if not os.environ.get("KF_DEV_ACCESS_KEY_ID"):
        pytest.skip("KF_DEV_ACCESS_KEY_ID not set — no .env / live credentials available")
    state: dict[str, Any] = {"app_id": None, "flow_id": None, "role_id": None, "iid": None,
                             "doctor_problems": None}

    def _cleanup() -> None:
        """Suite Teardown equivalent. Always runs; never raises over an unverified deletion —
        a teardown failure must never mask an earlier test failure."""
        if state["app_id"]:
            app_del = srv.forge_delete_flow(kind="application", flow_id=state["app_id"])
            print(f"application delete: {app_del}")
            if not app_del.get("verified"):
                print(f"*WARN* application {state['app_id']} deletion not verified")
        else:
            print("no application was created — nothing to delete")

        if state["role_id"]:
            # An application delete is NOT proven to cascade to its scoped AppRoles — delete the
            # role explicitly so a live run never leaks one into the account.
            role_del = srv.forge_delete_app_role(role_id=state["role_id"],
                                                 app_id=state["app_id"])
            print(f"app-role delete: {role_del}")

    request.addfinalizer(_cleanup)
    return state


def _field_ids(ctx: dict[str, Any]) -> dict[str, str]:
    """{field NAME: field id} off the LIVE draft — live_helpers.resolve_field_ids assumes KF_APP,
    but this flow lives in the freshly created app, so the app_id must ride along."""
    draft = srv.kf_get_flow_schema(
        flow_kind="process", flow_id=ctx["flow_id"], app_id=ctx["app_id"]
    )
    assert not draft.get("isError"), f"could not fetch draft to resolve field ids: {draft}"
    return {
        node["Name"]: node_id for node_id, node in draft.items()
        if isinstance(node, dict) and node.get("Kind") == "Field" and node.get("Name")
    }


def test_01_one_call_creates_and_publishes_the_template_app(ctx: dict[str, Any]) -> None:
    """forge_create_template_app: name in, published app + builder URL out, doctor riding in the
    response (never a separate call the caller must remember)."""
    result = srv.forge_create_template_app(name=APP_NAME)
    print(result)
    assert not result.get("isError"), f"create template app: {result}"
    ctx["app_id"] = result["app_id"]
    ctx["flow_id"] = result["flow_id"]
    ctx["role_id"] = result["role_id"]
    assert result["process_status"] == "Live"
    assert result["app_id"] in result["app_url"]
    assert result["flow_id"] in result["process_url"]
    assert isinstance(result["doctor"], dict) and "problems" in result["doctor"]
    ctx["doctor_problems"] = list(result["doctor"]["problems"])


def test_02_doctor_bar_is_differential_no_new_problems_beyond_the_capture(
    ctx: dict[str, Any],
) -> None:
    """The vendored capture ships its own quirks — the bar is DIFFERENTIAL: the live transplanted
    flow may show the capture's own problems (baseline = offline transplant + offline doctor over
    the same shape), but never NEW ones. Compared as SETS of id-normalized problem strings (both
    graphs mint their node ids at random, so ids are masked before comparing) — a count-only bar
    would pass when old problems were swapped for fresh breakage."""
    if ctx["doctor_problems"] is None:
        pytest.skip("no doctor report captured — step 01 failed")
    import re

    from kfforge.graph import transplant_template
    from kfforge.verify import doctor

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": APP_NAME,
                                 "FlowType": "Process"}}
    baseline = doctor(transplant_template(
        bare, app_role=(ctx["role_id"], f"{APP_NAME} Role")))

    def _normalize(problem: str) -> str:
        # minted node ids are {Kind}_ + 10 alphanumerics (kfforge.pages._mint)
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


def test_03_walk_an_item_through_manager_approve_to_completion(ctx: dict[str, Any]) -> None:
    """A REAL item walks Start -> Manager Approve -> Completed, driving the documented dataplane
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
        pytest.skip("no flow — step 01 failed")
    import time

    from kfforge.client import Err, KfClient, KfConfig, apply_add_role_users
    from kfforge.dataplane import LiveDataPlane, live_aiid

    cfg = KfConfig.from_env(app_id_override=ctx["app_id"])
    assert not isinstance(cfg, Err), f"live config: {cfg}"
    client = KfClient(cfg)
    dp = LiveDataPlane(client)

    draft = client.get_draft("process", ctx["flow_id"])
    assert not isinstance(draft, Err), f"draft read: {draft}"
    fields = {nid: v for nid, v in draft.items()
              if isinstance(v, dict) and v.get("Kind") == "Field"}

    recs = client.list_dataset_records("Master_Branch")
    assert not isinstance(recs, Err), f"Master_Branch dataset read: {recs}"
    data = recs.get("Data") or []
    assert data, "Master_Branch has no records on this tenant — the Reference fill needs one"
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
    probe_item = dp.create_item(ctx["flow_id"])
    assert not isinstance(probe_item, Err), f"probe item create: {probe_item}"
    probe_detail = dp.get_detail(ctx["flow_id"], probe_item["_id"])
    assert not isinstance(probe_detail, Err), f"probe detail: {probe_detail}"
    caller = (probe_detail.get("_current_assigned_to") or [None])[0]
    assert caller, f"could not discover the calling user from the item assignment: {probe_detail}"
    granted = apply_add_role_users(client, ctx["role_id"], user_ids=[caller],
                                   app_id=ctx["app_id"])
    assert not isinstance(granted, Err), f"caller into role: {granted}"
    print(f"caller into role: {granted.as_tool_result()}")

    item = dp.create_item(ctx["flow_id"])
    assert not isinstance(item, Err), f"item create: {item}"
    iid, hop1_aiid = item["_id"], item["_activity_instance_id"]

    put = dp.put_fields(ctx["flow_id"], iid, values)
    assert not isinstance(put, Err), f"fill: {put}"
    after_fill = dp.get_detail(ctx["flow_id"], iid)
    assert not isinstance(after_fill, Err), f"fill read-back: {after_fill}"
    # Computed fields (Field::Expression) are server-owned: a direct write there reads back None
    # by design (captured live 2026-08-20), so the silent-discard audit covers only the fields a
    # caller genuinely owns.
    discarded = [fields[k]["Name"] for k in values
                 if after_fill.get(k) is None and "Field::Expression" not in fields[k]]
    assert not discarded, f"fill values silently discarded (PUT 200 proves nothing): {discarded}"

    sub1 = dp.submit(ctx["flow_id"], iid, hop1_aiid)
    assert not isinstance(sub1, Err), f"Start submit: {sub1}"
    detail = dp.get_detail(ctx["flow_id"], iid)
    for _ in range(10):
        if not isinstance(detail, Err) and detail.get("_current_step") != "Start":
            break
        time.sleep(0.9)
        detail = dp.get_detail(ctx["flow_id"], iid)
    assert not isinstance(detail, Err), f"post-hop1 detail: {detail}"
    assert detail.get("_current_step") == "Manager Approve", (
        f"item did not land on Manager Approve after the Start submit: "
        f"step={detail.get('_current_step')!r} status={detail.get('_status')!r}"
    )

    hop2_aiid = live_aiid(detail)
    assert not isinstance(hop2_aiid, Err), f"hop-2 aiid: {hop2_aiid}"
    sub2 = dp.submit(ctx["flow_id"], iid, hop2_aiid)
    assert not isinstance(sub2, Err), f"Manager Approve submit: {sub2}"
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
        pytest.skip("no completed item — step 03 failed")
    field_ids = _field_ids(ctx)
    assert "request number" in field_ids, "computed field 'request number' missing from the draft"
    assert "Requestor User" in field_ids, "User field 'Requestor User' missing from the draft"

    detail = live_helpers.get_item_detail(ctx["flow_id"], ctx["iid"])
    computed_state = detail.get(field_ids["request number"])
    user_state = detail.get(field_ids["Requestor User"])
    print(f"computed 'request number' ({field_ids['request number']}): {computed_state!r}")
    print(f"user 'Requestor User' ({field_ids['Requestor User']}): {user_state!r}")
    assert detail.get("_status") == "Completed", (
        f"read-back item is not the completed walk: {detail.get('_status')!r}"
    )


def test_05_duplicate_app_name_fails_loud(ctx: dict[str, Any]) -> None:
    """A second create with the SAME name must surface the platform's own duplicate error loud —
    no auto-rename, no silent second app. Runs after the walk so a failure here cannot cost the
    expensive build. Asserts no NEW application appeared under this name."""
    if not ctx["app_id"]:
        pytest.skip("no app — step 01 failed")
    result = srv.forge_create_template_app(name=APP_NAME)
    print(result)
    if not result.get("isError") and result.get("app_id"):
        # The platform accepted a duplicate — delete the accidental second app BEFORE failing,
        # so this negative test never leaks tenant junk the module finalizer doesn't know about.
        second_del = srv.forge_delete_flow(kind="application", flow_id=result["app_id"])
        print(f"unexpected duplicate app cleaned up: {second_del}")
    assert result.get("isError"), "duplicate app name must be refused, not auto-renamed"

    listed = srv.forge_list_apps()
    assert not listed.get("isError"), f"list apps: {listed}"
    same_name = [a for a in listed.get("apps", [])
                 if isinstance(a, dict) and a.get("Name") == APP_NAME]
    assert len(same_name) <= 1, f"a second app with the same name appeared: {same_name}"
