"""P2 acceptance (Node G): the forge_* MCP tool surface.

Fully offline — NO live credentials, no network:
  1. manifest — every forge_* tool named in the Node G spec exists on the server module AND
     registers on the real FastMCP object with a buildable schema (proves `@mcp.tool()` didn't
     choke on any parameter type, which a bare `dir(srv)` name-check cannot prove by itself).
  2. the original 8 kf_* dry-run/plan tools stay genuinely callable offline (pure functions, no
     client needed) — a regression net for the P0/P1 surface this file sits beside.
  3. every forge_* tool, called with NO KF_DEV_* env vars set, fails GRACEFULLY (`_client()`
     returns a config Err, `.as_tool_result()`, never an unhandled exception) — the offline-safe
     contract every write tool in this module promises.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_client import (  # tests/ is on sys.path, see conftest.py
    FakeClient,
    _bare_process_draft,
    _process_with_branches,
)

import kfforge.server as srv
from kfforge.client import Err

FORGE_TOOLS = {
    "forge_create_process", "forge_member_batch", "forge_apply_fields", "forge_add_table",
    "forge_build_workflow", "forge_add_goto_gate", "forge_set_branch_conditions",
    "forge_set_visibility", "forge_set_events",
    "forge_set_styles", "forge_publish", "forge_doctor", "forge_create_page", "forge_build_page",
    "forge_set_navigation", "forge_share_report", "forge_simulate_case", "forge_create_app",
    "forge_delete_flow",
    "forge_add_role_users",
}

KF_ENV_VARS = (
    "KF_DEV_ACCESS_KEY_ID", "KF_DEV_ACCESS_KEY_SECRET", "KF_DEV_ACCOUNT_ID", "KF_DEV_DOMAIN",
    "KF_APP",
)

# Minimal dummy args each forge_* tool needs to reach its FIRST statement (`_client()`) — every
# tool's body checks `_client()` before touching anything else, so these values are never used
# for real; they only need to be well-typed enough to pass FastMCP's schema / Python's own
# call signature before the config-Err short-circuit fires.
DUMMY_ARGS: dict[str, dict[str, Any]] = {
    "forge_create_process": {"name": "x"},
    "forge_member_batch": {"target_flow_id": "x"},
    "forge_apply_fields": {"flow_id": "x", "fields": []},
    "forge_add_table": {"flow_id": "x", "name": "t", "columns": []},
    "forge_build_workflow": {"flow_id": "x", "steps": []},
    "forge_add_goto_gate": {"flow_id": "x", "target_activity_name": "a", "field_name": "f"},
    "forge_set_branch_conditions": {"flow_id": "x", "field_name": "f", "branch_literals": {}},
    "forge_set_visibility": {"flow_id": "x", "owners": {}},
    "forge_set_events": {"flow_id": "x", "events": {}},
    "forge_set_styles": {"flow_id": "x", "styles": {}},
    "forge_publish": {"kind": "process", "flow_id": "x"},
    "forge_doctor": {"flow_id": "x"},
    "forge_create_page": {"app_id": "x", "name": "p"},
    "forge_build_page": {"app_id": "x", "page_id": "p", "steps": []},
    "forge_set_navigation": {"app_id": "x", "page_id": "p", "label": "l"},
    "forge_share_report": {"flow_id": "x", "report_id": "r", "members": []},
    "forge_simulate_case": {"flow_id": "x", "steps": []},
    "forge_create_app": {"name": "x"},
    "forge_delete_flow": {"kind": "process", "flow_id": "x"},
    "forge_add_role_users": {"role_id": "x", "user_query": "ann"},
}


def test_dummy_args_cover_every_forge_tool() -> None:
    """Fixture-drift guard: if a new forge_* tool is added, this file must know how to probe it."""
    assert set(DUMMY_ARGS) == FORGE_TOOLS


# ---- 1. manifest ------------------------------------------------------------------------------

def test_server_exposes_every_forge_tool_by_name() -> None:
    found = {name for name in dir(srv) if name.startswith("forge_")}
    missing = FORGE_TOOLS - found
    assert not missing, f"forge_* tools missing from server module: {missing}"


def test_server_still_exposes_the_original_8_kf_tools() -> None:
    expected = {"kf_list_field_types", "kf_plan_field_change", "kf_get_flow_schema",
               "kf_apply_field_change", "kf_create_process", "kf_plan_step_visibility",
               "kf_set_step_visibility", "kf_publish"}
    found = {name for name in dir(srv) if name.startswith("kf_")}
    missing = expected - found
    assert not missing, f"original kf_* tools missing from server module: {missing}"


def test_every_forge_tool_registers_on_the_real_mcp_server_with_a_valid_schema() -> None:
    """In-memory FastMCP Client (fastmcp docs: 'best for tests, no subprocess/network') — proves
    every forge_* tool's type hints actually build a JSON schema `@mcp.tool()` accepts, which a
    bare `dir(srv)` name-check cannot prove (a decoration-time TypeError would still leave the
    plain function visible in the module namespace). Plain `asyncio.run` rather than a pytest
    async-test plugin — this project has no pytest-asyncio/anyio dependency and one test is not
    worth adding one for.
    """
    from fastmcp import Client

    async def _run() -> set[str]:
        async with Client(srv.mcp) as client:
            tools = await client.list_tools()
        for t in tools:
            if t.name in FORGE_TOOLS:
                assert t.description, f"{t.name} has no description"
                assert t.inputSchema, f"{t.name} has no input schema"
        return {t.name for t in tools}

    names = asyncio.run(_run())
    missing = FORGE_TOOLS - names
    assert not missing, f"forge_* tools failed to register on the FastMCP server: {missing}"


# ---- 2. core kf_* plan/dry-run tools stay callable offline -------------------------------------

_FORM_DRAFT = {
    "Root": "M1",
    "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
}


def test_kf_list_field_types_is_a_real_offline_call() -> None:
    types = srv.kf_list_field_types()
    assert isinstance(types, list) and "Text" in types and "Boolean" in types


def test_kf_plan_field_change_is_a_real_offline_call() -> None:
    out = srv.kf_plan_field_change(_FORM_DRAFT, [{"name": "Notes", "type": "Text"}])
    assert out["adds"] == [{"name": "Notes", "type": "Text", "required": False}]
    assert out["skipped"] == []


def test_kf_plan_step_visibility_is_a_real_offline_call() -> None:
    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process",
              "RootProcessDef": "PD1", "Model::ProcessDef": ["PD1"]},
        "PD1": {"Id": "PD1", "Kind": "ProcessDef", "WorkflowType": "Sequence",
                "ProcessDef::Activity": ["A1"]},
        "A1": {"Id": "A1", "Kind": "Activity", "NodeType": "StartEvent", "Name": "Start",
              "ProcessDef": "PD1"},
    }
    out = srv.kf_plan_step_visibility(draft, {})
    assert out == {"sections": {}, "permission_nodes": 0}


def test_kf_list_field_types_round_trips_through_the_real_mcp_protocol() -> None:
    """One representative tool proven end-to-end through the ACTUAL MCP call_tool path (in-memory
    transport), not just as a plain Python function call — the two are not guaranteed identical
    (argument (de)serialization happens in between)."""
    from fastmcp import Client

    async def _run() -> list[str]:
        async with Client(srv.mcp) as client:
            result = await client.call_tool("kf_list_field_types", {})
        return result.data

    data = asyncio.run(_run())
    assert "Text" in data


# ---- 3. every forge_* tool fails gracefully with no live credentials --------------------------

@pytest.fixture()
def no_kf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in KF_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("tool_name", sorted(FORGE_TOOLS))
def test_forge_tool_fails_gracefully_with_no_credentials(tool_name: str, no_kf_env: None) -> None:
    fn = getattr(srv, tool_name)
    got = fn(**DUMMY_ARGS[tool_name])
    assert isinstance(got, dict), f"{tool_name} must return a dict even on failure, got {type(got)}"
    assert got.get("isError") is True, f"{tool_name} with no credentials must report isError=True: {got}"
    assert "config" in str(got).lower() or "KF_" in str(got), (
        f"{tool_name}'s error should be traceable to the missing config, got: {got}"
    )


# ---- 4. forge_publish's status read-back (lifecycle spec: "forge_publish -> Status Live") -----
# THE RULE (CLAUDE.md): an HTTP 200 from publish proves nothing by itself. forge_publish reads
# the flow's OWN metadata record back and only reports success when Status is genuinely "Live" —
# these two tests pin that logic with a fake client, offline.

class _FakeDetailClient:
    """Just enough of KfClient's surface for forge_publish's flow-kind branch."""

    def __init__(self, status: str | None) -> None:
        self._status = status
        self.published = False

    def publish(self, kind: str, flow_id: str):  # type: ignore[no-untyped-def]
        self.published = True

    def get_flow_detail(self, kind: str, flow_id: str):  # type: ignore[no-untyped-def]
        return {"_id": flow_id, "Status": self._status}


def test_forge_publish_reports_isError_false_when_status_reads_back_live(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDetailClient(status="Live")
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_publish(kind="process", flow_id="F1")
    assert got == {"kind": "process", "id": "F1", "published": True, "status": "Live", "isError": False}


def test_forge_publish_reports_isError_true_when_status_is_not_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 publish response is not proof — if the read-back still shows "Draft" (or anything
    else), this must be isError=True, never a silent false-positive success."""
    fake = _FakeDetailClient(status="Draft")
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_publish(kind="process", flow_id="F1")
    assert got["isError"] is True and got["status"] == "Draft"


# ---- 5. review F5 — forge_publish's page/application branches had ZERO coverage ---------------

class _FakePagePublishClient:
    """Just enough of KfClient's surface for forge_publish's page/application branches."""

    def __init__(self, *, page_err: Err | None = None, app_err: Err | None = None) -> None:
        self.page_err = page_err
        self.app_err = app_err
        self.page_publishes: list[tuple[str, str]] = []
        self.app_publishes: list[str] = []

    def publish_page(self, app_id: str, page_id: str):  # type: ignore[no-untyped-def]
        self.page_publishes.append((app_id, page_id))
        return self.page_err

    def publish_app(self, app_id: str):  # type: ignore[no-untyped-def]
        self.app_publishes.append(app_id)
        return self.app_err


def test_forge_publish_page_kind_requires_app_id(monkeypatch: pytest.MonkeyPatch) -> None:
    # _client() runs BEFORE the app_id check, so it must succeed here (a fake with no methods is
    # enough — the app_id validation fires before anything is ever called on it).
    monkeypatch.setattr(srv, "_client", lambda: _FakePagePublishClient())
    got = srv.forge_publish(kind="page", flow_id="Page1", app_id=None)
    assert got["isError"] is True and "app_id" in got["error"]


def test_forge_publish_page_kind_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePagePublishClient()
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_publish(kind="page", flow_id="Page1", app_id="App1")
    assert got == {"kind": "page", "id": "Page1", "published": True, "isError": False}
    assert fake.page_publishes == [("App1", "Page1")]


def test_forge_publish_page_kind_propagates_publish_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePagePublishClient(page_err=Err("http", "boom", 500))
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_publish(kind="page", flow_id="Page1", app_id="App1")
    assert got["isError"] is True


def test_forge_publish_application_kind_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePagePublishClient()
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_publish(kind="application", flow_id="App1")
    assert got == {"kind": "application", "id": "App1", "published": True, "isError": False}
    assert fake.app_publishes == ["App1"]


def test_forge_publish_application_kind_propagates_publish_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePagePublishClient(app_err=Err("http", "boom", 500))
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_publish(kind="application", flow_id="App1")
    assert got["isError"] is True


# ---- 5b. issue #19 — kf_get_flow_schema(flow_kind="page", ...) had two independent faults: the
# emitted URL omitted the application/{app} segment (routed through the generic get_draft/
# _draft_url instead of the existing get_page_draft/_page_draft_url), and there was no app_id
# parameter at all -- flow_kind="page" only ever "worked" by accident for KF_APP. Mirrors the
# forge_publish page-kind coverage above, same fake-client shape.

class _FakePageDraftClient:
    """Just enough of KfClient's surface for kf_get_flow_schema's page branch."""

    def __init__(self, *, page_draft: dict[str, Any] | None = None, page_err: Err | None = None) -> None:
        self.page_draft = page_draft
        self.page_err = page_err
        self.page_draft_calls: list[tuple[str, str]] = []

    def get_page_draft(self, app_id: str, page_id: str):  # type: ignore[no-untyped-def]
        self.page_draft_calls.append((app_id, page_id))
        return self.page_err if self.page_err is not None else self.page_draft


def test_kf_get_flow_schema_page_kind_requires_app_id(monkeypatch: pytest.MonkeyPatch) -> None:
    # _client() runs BEFORE the app_id check, so it must succeed here (a fake with no methods
    # touched is enough -- the app_id validation fires before get_page_draft is ever called).
    fake = _FakePageDraftClient()
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.kf_get_flow_schema(flow_kind="page", flow_id="Page1", app_id=None)
    assert got["isError"] is True and "app_id" in got["error"]
    assert fake.page_draft_calls == []


def test_kf_get_flow_schema_page_kind_routes_through_page_draft_with_the_explicit_app_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePageDraftClient(page_draft={"Root": "Pg1"})
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.kf_get_flow_schema(flow_kind="page", flow_id="Page1", app_id="App_Other")
    assert got == {"Root": "Pg1"}
    assert fake.page_draft_calls == [("App_Other", "Page1")], (
        "the EXPLICIT app_id passed by the caller must reach get_page_draft, never a "
        "hard-substituted KF_APP default"
    )


def test_kf_get_flow_schema_page_kind_propagates_a_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePageDraftClient(page_err=Err("http", "not found", 404))
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.kf_get_flow_schema(flow_kind="page", flow_id="Page1", app_id="App_Other")
    assert got["isError"] is True


def test_kf_get_flow_schema_non_page_kind_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow_kind != "page" keeps its original behavior -- app_id is accepted but ignored, and
    the generic get_draft path is still what runs."""
    fake = FakeClient(_bare_process_draft())
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.kf_get_flow_schema(flow_kind="process", flow_id="F1", app_id="ignored")
    assert got == fake.draft


# ---- 6. review F5 — forge_create_app / forge_share_report had NO tool-level coverage beyond
# the generic no-credentials path ----------------------------------------------------------------

def test_forge_create_app_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(_bare_process_draft())
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_create_app(name="Sample App")
    assert got["verified"] is True and got["isError"] is False
    assert got["app_id"] in fake.applications


def test_forge_share_report_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(_bare_process_draft())
    monkeypatch.setattr(srv, "_client", lambda: fake)
    members = [{"_id": "m1", "Name": "Lead", "Kind": "AppRole", "Role": "Ro_lead", "Permission": ["Member"]}]
    got = srv.forge_share_report(flow_id="F1", report_id="Rep1", members=members)
    assert got["isError"] is False
    assert got["verified"] is None, "no documented read-back route -- must not fake True"
    assert fake.report_member_batches == [("F1", "Rep1", members)]


# ---- 7. Node M — forge_set_branch_conditions / forge_add_goto_gate branch_name ----------------

def test_forge_set_branch_conditions_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(_process_with_branches())
    fake.list_items["List_Sample01"] = ["Alpha", "Beta"]
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_set_branch_conditions(
        flow_id="F1", field_name="Track", branch_literals={"Branch A": "Alpha", "Branch B": "Beta"})
    assert got["isError"] is False
    assert got["verified"] == ["Branch A", "Branch B"] and got["missing"] == []


def test_forge_set_branch_conditions_rejects_bad_literal_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClient(_process_with_branches())
    fake.list_items["List_Sample01"] = ["Alpha", "Beta"]
    monkeypatch.setattr(srv, "_client", lambda: fake)
    got = srv.forge_set_branch_conditions(
        flow_id="F1", field_name="Track", branch_literals={"Branch A": "Not Real"})
    assert got["isError"] is True
    assert fake.puts == 0


def test_forge_add_goto_gate_branch_name_scopes_into_that_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    from kfforge.graph import apply_changes as _apply_changes
    from kfforge.types import FieldSpec, FieldType

    draft = _apply_changes(_process_with_branches(), [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
    branch_a_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch A")
    fake = FakeClient(draft)
    monkeypatch.setattr(srv, "_client", lambda: fake)

    got = srv.forge_add_goto_gate(flow_id="F1", target_activity_name="Shared Step",
                                  field_name="Done Flag", branch_name="Branch A")
    assert got["isError"] is False and got["branch_name"] == "Branch A"
    assert got["goto_activity_id"] in fake.draft[branch_a_pd_id]["ProcessDef::Activity"]
