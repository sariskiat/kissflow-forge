"""Offline tests for `scripts/exercise_every_tool.py`.

The module is loaded via `importlib.util.spec_from_file_location`, never a plain
`import scripts.exercise_every_tool`: `scripts/` carries no `__init__.py`
(`scripts/arch_scan.py` sets the precedent), and `[tool.ty.environment].root` is
scheduled to drop its repo-root entry once a future goal (G14) lands, which would
break a static import of anything under `scripts/`. Loading by file path sidesteps
both -- see `tests/test_arch_scan.py`'s own docstring for the same reasoning applied
to `scripts/arch_scan.py`.

No test here calls the network, the real dev tenant, or `fastmcp.Client` -- every
"tool call" goes through `FakeClient`, an in-memory stand-in for
`fastmcp.Client.call_tool`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, RootModel

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "exercise_every_tool.py"


def _load_module() -> Any:
    """Load `scripts/exercise_every_tool.py` by file path.

    Returns:
        The executed module, typed `Any` on purpose -- it is loaded dynamically, so
        no static checker can (or should) know its attributes ahead of time.
    """
    spec = importlib.util.spec_from_file_location("exercise_every_tool", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses' own `_is_type` resolves `cls.__module__` through `sys.modules`,
    # so the module must be registered there BEFORE `exec_module` runs its
    # `@dataclass` decorators, exactly as `importlib`'s own docs prescribe for this
    # pattern.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod: Any = _load_module()


# =====================================================================================
# A fake in-memory MCP client -- canned results per tool name, keyed by the exact
# argument dict a real call would receive when useful (forge_add_member_roles echoes
# the display name it was asked to grant, exactly as the real server would).
# =====================================================================================


@dataclass
class _FakeResult:
    """Stands in for `fastmcp.client.client.CallToolResult`."""

    is_error: bool
    data: Any
    structured_content: Any = None
    content: Any = None


@dataclass
class _FakeTextContent:
    """Stand-in for FastMCP's ``TextContent`` error block."""

    text: str


class _OpaqueRoot:
    """Stand-in for FastMCP's `Root`, which has no mapping or dump method."""


class _TypedTemplateResult(BaseModel):
    """Small stand-in for a typed FastMCP DTO that creates an app."""

    app_id: str
    flow_id: str


class _TypedProcessResult(BaseModel):
    """Small stand-in for a typed FastMCP DTO that creates a process."""

    flow_id: str


class _TypedDraft(RootModel[dict[str, Any]]):
    """Stand-in for a RootModel response returned by a flow-schema read."""


class _TypedError(BaseModel):
    """Stand-in for a typed error payload from a failed tool call."""

    error: str


class FakeClient:
    """An in-memory MCP client: `call_tool` never leaves the process.

    Attributes:
        calls: Every `(tool_name, arguments)` pair received, in call order -- lets a
            test inspect exactly what was sent, including the unlogged plumbing
            reads `run_plan` makes for the two dry-run tools.
    """

    def __init__(self, canned: dict[str, Any]) -> None:
        self._canned = canned
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        raise_on_error: bool = True,
        timeout: float | None = None,
        **_kwargs: Any,
    ) -> _FakeResult:
        del raise_on_error, timeout
        arguments = arguments or {}
        self.calls.append((name, dict(arguments)))
        entry = self._canned.get(name)
        if entry is None:
            return _FakeResult(
                is_error=True, data={"error": f"no canned entry: {name}"}
            )
        if isinstance(entry, _FakeResult):
            return entry
        if callable(entry):
            is_error, data = entry(arguments)
        else:
            is_error, data = entry
        return _FakeResult(is_error=is_error, data=data)


def _canned_add_member_roles(arguments: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    roles = arguments.get("roles") or {}
    display_name = next(iter(roles.values()), "Role")
    return False, {
        "resolved": {display_name: "role-b-1"},
        "role_ids": ["role-b-1"],
        "isError": False,
    }


def _build_canned_responses() -> dict[str, Any]:
    """One canned `(is_error, data)` entry per Appendix A tool but `forge_share_report`.

    `forge_share_report` is never called (its own `decide` always skips), so it
    carries no entry -- a missing entry would be loud (`FakeClient` returns
    `is_error=True`), which is exactly what should never happen for it.

    Returns:
        The canned-response table, `FakeClient`'s single constructor argument.
    """
    ok: dict[str, Any] = {"isError": False}
    draft = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "Fake"}}
    spec_v1 = {"app_name": "Fake App", "approved": False}
    spec_v2 = {"app_name": "Fake App (exercised)", "approved": False}
    approved_spec = {"app_name": "Fake App (exercised)", "approved": True}
    return {
        "forge_capabilities": (False, dict(ok)),
        "forge_playbook": (False, dict(ok)),
        "kf_list_field_types": (False, ["Text", "Boolean", "Select"]),
        "forge_intake_questions": (
            False,
            {"questions": [], "gaps": [], "blocking_gaps": [], "spec": spec_v1},
        ),
        "forge_update_spec": (
            False,
            {"spec": spec_v1, "gaps": [], "blocking_gaps": [], "isError": False},
        ),
        "forge_render_flow_diagram": (False, {"xml": "<mxfile/>", "path": "x", **ok}),
        "forge_render_schema_diagram": (False, {"xml": "<mxfile/>", "path": "x", **ok}),
        "forge_render_mockups": (
            False,
            {"html": "<html/>", "path": "x", "summary": "0 stages", **ok},
        ),
        "forge_apply_revisions": (
            False,
            {"spec": spec_v2, "digest": "digest-1", "compiles": True, **ok},
        ),
        "forge_request_confirmation": (
            False,
            {"digest": "digest-1", "artifact_paths": {}, "questions": [], **ok},
        ),
        "forge_approve_spec": (
            False,
            {
                "spec": approved_spec,
                "approved": True,
                "digest": "digest-1",
                "approval_token": "token-1",
                **ok,
            },
        ),
        "forge_plan_app": (False, {"ops": [], "summary": "0 ops", "op_count": 0, **ok}),
        "forge_list_apps": (False, {"apps": [], "count": 0, **ok}),
        "forge_create_template_app": (
            False,
            {
                "app_id": "app-1",
                "flow_id": "flow-template-1",
                "role_id": "role-template-1",
                **ok,
            },
        ),
        "forge_create_app": (False, {"app_id": "app-throwaway-1", **ok}),
        "forge_create_app_role": (False, {"role_id": "role-a-1", **ok}),
        "forge_create_process": (False, {"flow_id": "flow-main-1", **ok}),
        "kf_create_process": (False, {"flow_id": "flow-secondary-1", **ok}),
        "kf_plan_field_change": (
            False,
            {"adds": [], "edits": [], "skipped": [], "human_readable": ""},
        ),
        "kf_apply_field_change": (False, {"flow_id": "flow-secondary-1", **ok}),
        "kf_publish": (False, {"published": True, "flow_id": "flow-secondary-1"}),
        "forge_add_member_roles": _canned_add_member_roles,
        "forge_member_batch": (False, {"target_flow_id": "flow-main-1", **ok}),
        "forge_add_role_users": (False, {"not_found": [], **ok}),
        "forge_grant_tier": (False, {"role_id": "role-a-1", "verified": True, **ok}),
        "forge_set_role_preference": (False, dict(ok)),
        "forge_apply_fields": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_apply_layout": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_add_table": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_add_sequence_number": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_add_field_validation": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_set_required": (False, {"flow_id": "flow-main-1", "cleared": [], **ok}),
        "forge_rename_fields": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_build_workflow": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_add_goto_gate": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_set_branch_conditions": (
            False,
            {"flow_id": "flow-main-1", "uncovered": [], **ok},
        ),
        "kf_plan_step_visibility": (False, {"sections": {}, "permission_nodes": 0}),
        "kf_set_step_visibility": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_set_visibility": (
            False,
            {"flow_id": "flow-main-1", "uncovered_sections": [], **ok},
        ),
        "forge_set_events": (False, {"flow_id": "flow-main-1", "unverified": [], **ok}),
        "forge_set_styles": (False, {"flow_id": "flow-main-1", **ok}),
        "forge_doctor": (False, {"ok": True, "problems": []}),
        "forge_compare_to_spec": (False, {"ok": True, "mismatches": []}),
        "kf_get_flow_schema": (False, dict(draft)),
        "forge_create_page": (False, {"page_id": "page-1", "verified": True, **ok}),
        "forge_build_page": (False, dict(ok)),
        "forge_set_navigation": (False, dict(ok)),
        "forge_publish": (False, {"published": True, **ok}),
        "forge_create_list": (False, {"list_id": "list-1", **ok}),
        "forge_create_flow": (False, {"flow_id": "dataset-1", "kind": "dataset", **ok}),
        "forge_dataset_records": (False, dict(ok)),
        "forge_sweep": (False, {"results": {}, **ok}),
        "forge_copilot_ask": (
            False,
            {"conversation_id": "conv-1", "status": "matched", **ok},
        ),
        "forge_copilot_check": (False, {"scatter": {}, "landed_nodes": {}, **ok}),
        "forge_simulate_case": (
            False,
            {
                "flow_id": "flow-main-1",
                "iid": "iid-1",
                "created": True,
                "planned": [],
                "filled": [],
                "advanced": [],
                "rejected": [],
                "failed": [],
                "error": None,
                "isError": False,
            },
        ),
        "forge_list_app_roles": (False, {"roles": [], "count": 0, **ok}),
        "forge_publish_app": (False, dict(ok)),
        "forge_delete_fields": (False, {"deleted": [], "surviving": [], **ok}),
        "forge_delete_app_role": (
            False,
            {"role_id": "role-a-1", "deleted": True, **ok},
        ),
        "forge_delete_flow": (False, {"deleted": True, "verified": True, **ok}),
    }


def _fake_args(*, app_id: str | None = None, user_query: str | None = "Jane") -> Any:
    """Build the `argparse.Namespace` every `decide` function reads."""
    return Namespace(
        app_id=app_id,
        cleanup=False,
        keep=False,
        user_query=user_query,
        env_file=None,
        url="http://example.invalid/mcp",
        stdio_docker=None,
        log_path=Path("unused.json"),
    )


def _run_full_plan(
    *, app_id: str | None = None, user_query: str | None = "Jane"
) -> tuple[list[Any], FakeClient]:
    """Run the whole plan once against a fresh `FakeClient`.

    Returns:
        The 61 log rows (plan order) and the client that produced them.
    """
    args = _fake_args(app_id=app_id, user_query=user_query)
    ctx = mod.Context(args=args, base="FakeRun", fixture_patch={"app_name": "Fake"})
    plan = mod.build_plan()
    client = FakeClient(_build_canned_responses())
    rows = asyncio.run(mod.run_plan(client, ctx, plan))
    return rows, client


# =====================================================================================
# 1. The plan covers all 61 tool names of Appendix A exactly once.
# =====================================================================================


def test_plan_covers_appendix_a_exactly_once() -> None:
    plan = mod.build_plan()
    names = [step.tool for step in plan]
    assert len(names) == 61
    assert len(names) == len(set(names)), "a tool name repeats in the plan"
    assert set(names) == mod.APPENDIX_A_TOOLS
    assert len(mod.APPENDIX_A_TOOLS) == 61


# =====================================================================================
# 2. No step passes `groups` or `confirm_group_notification`.
# =====================================================================================


def test_no_step_passes_groups_or_confirm_group_notification() -> None:
    rows, _client = _run_full_plan()
    for row in rows:
        assert "groups" not in row.arguments, row.name
        assert "confirm_group_notification" not in row.arguments, row.name


def test_role_user_grant_targets_the_workflow_assignee_role() -> None:
    rows, _client = _run_full_plan()
    by_name = {row.name: row for row in rows}

    assert (
        by_name["forge_add_role_users"].arguments["role_id"]
        == by_name["forge_build_workflow"].arguments["steps"][0][1]
    )


def test_renamed_field_does_not_collide_with_template_fields() -> None:
    template = json.loads(
        (REPO_ROOT / "shapes" / "process_template_full.json").read_text()
    )
    field_names = {
        node.get("Name")
        for node in template.values()
        if isinstance(node, dict) and node.get("Kind") == "Field"
    }

    assert mod.FIELD_DETAILS_RENAMED not in field_names


# =====================================================================================
# 3. Every `forge_delete_flow` step targets an id an earlier step created.
# =====================================================================================


def test_delete_flow_targets_an_earlier_created_id() -> None:
    rows, _client = _run_full_plan()
    created_ids: set[str] = set()
    delete_checked = False
    for row in rows:
        if row.name == "forge_delete_flow":
            delete_checked = True
            flow_id = row.arguments.get("flow_id")
            assert flow_id is not None, "forge_delete_flow ran with no flow_id"
            assert flow_id in created_ids, (
                f"forge_delete_flow targeted {flow_id!r}, which no earlier step "
                f"in this run created: {sorted(created_ids)}"
            )
        created_ids.update(row.ids.values())
    assert delete_checked, "forge_delete_flow never ran in this plan"


# =====================================================================================
# 4. A fake full pass produces 61 rows and a valid exercise_log.json.
# =====================================================================================


def test_fake_full_pass_produces_61_rows_and_a_valid_log(tmp_path: Path) -> None:
    rows, client = _run_full_plan()
    assert len(rows) == 61
    outcomes = {row.outcome for row in rows}
    assert outcomes <= {"ok", "error", "skipped"}
    by_name = {row.name for row in rows}
    assert by_name == mod.APPENDIX_A_TOOLS

    # forge_share_report is always skipped (no report id exists to pass); nothing
    # named "forge_share_report" ever reached the fake client.
    share_report_row = next(r for r in rows if r.name == "forge_share_report")
    assert share_report_row.outcome == "skipped"
    assert not any(name == "forge_share_report" for name, _args in client.calls)

    log_path = tmp_path / "exercise_log.json"
    mod.write_log(log_path, rows)
    loaded = json.loads(log_path.read_text())
    assert loaded["summary"]["total"] == 61
    assert len(loaded["rows"]) == 61
    assert (
        loaded["summary"]["ok"] + loaded["summary"]["error"]
        == 61 - (loaded["summary"]["skipped"])
    )

    summary = mod.summary_line(rows)
    assert summary.endswith("of 61")
    assert "ok" in summary and "error" in summary and "skipped" in summary


def test_typed_dto_result_sets_ids_and_prevents_downstream_skip() -> None:
    """A typed app response must feed its id into the next planned call."""
    ctx = mod.Context(
        args=_fake_args(), base="TypedRun", fixture_patch={"app_name": "Typed"}
    )
    client = FakeClient(
        {
            "forge_create_template_app": (
                False,
                _TypedTemplateResult(app_id="app-typed", flow_id="flow-typed"),
            ),
            "forge_create_process": (
                False,
                _TypedProcessResult(flow_id="process-typed"),
            ),
        }
    )
    rows = asyncio.run(
        mod.run_plan(
            client,
            ctx,
            [
                mod.Step(
                    "forge_create_template_app",
                    mod._decide_forge_create_template_app,
                    mod._after_forge_create_template_app,
                ),
                mod.Step(
                    "forge_create_process",
                    mod._decide_forge_create_process,
                    mod._after_forge_create_process,
                ),
            ],
        )
    )

    assert ctx.app_id == "app-typed"
    assert ctx.main_process_id == "process-typed"
    assert [row.outcome for row in rows] == ["ok", "ok"]
    assert client.calls[1][1]["app_id"] == "app-typed"


def test_structured_content_fallback_sets_app_id_for_a_later_step() -> None:
    """A Root `data` wrapper must fall back to its structured response dict."""
    ctx = mod.Context(
        args=_fake_args(), base="RootRun", fixture_patch={"app_name": "Root"}
    )
    client = FakeClient(
        {
            "forge_create_app": _FakeResult(
                is_error=False,
                data=_OpaqueRoot(),
                structured_content={"app_id": "app-root"},
            ),
            "forge_delete_flow": _FakeResult(
                is_error=False,
                data=_OpaqueRoot(),
                structured_content={"deleted": True},
            ),
        }
    )
    rows = asyncio.run(
        mod.run_plan(
            client,
            ctx,
            [
                mod.Step(
                    "forge_create_app",
                    mod._decide_forge_create_app,
                    mod._after_forge_create_app,
                ),
                mod.Step(
                    "forge_delete_flow",
                    mod._decide_forge_delete_flow,
                ),
            ],
        )
    )

    assert ctx.throwaway_app_id == "app-root"
    assert [row.outcome for row in rows] == ["ok", "ok"]
    assert client.calls[1][1]["flow_id"] == "app-root"


def test_root_model_draft_is_normalized_for_plumbing_read() -> None:
    """A RootModel[dict] draft must remain usable by dependent dry-run tools."""
    draft = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model"}}
    client = FakeClient({"kf_get_flow_schema": (False, _TypedDraft(draft))})

    result = asyncio.run(mod._peek_draft(client, "flow-typed", "app-typed"))

    assert result == draft


def test_typed_error_stays_an_error_and_dependency_skip_fails_run() -> None:
    """Normalization must preserve error rows and make hidden chain breaks fatal."""
    client = FakeClient(
        {"forge_capabilities": (True, _TypedError(error="typed failure"))}
    )
    ctx = mod.Context(
        args=_fake_args(), base="TypedErrorRun", fixture_patch={"app_name": "Typed"}
    )
    rows = asyncio.run(
        mod.run_plan(
            client,
            ctx,
            [mod.Step("forge_capabilities", lambda _ctx: mod._call(query=""))],
        )
    )
    dependency_skip = mod.LogRow(
        name="forge_create_process",
        arguments={},
        outcome="skipped",
        error=None,
        skip_reason="upstream dependency missing: 'app_id' was not produced",
        duration_seconds=0.0,
        ids={},
    )
    intentional_skip = mod.LogRow(
        name="forge_share_report",
        arguments={},
        outcome="skipped",
        error=None,
        skip_reason="no report id exists on this tool surface",
        duration_seconds=0.0,
        ids={},
    )

    assert rows[0].outcome == "error"
    assert rows[0].error == "typed failure"
    assert mod._run_has_failure(rows)
    assert mod._run_has_failure([dependency_skip])
    assert not mod._run_has_failure([intentional_skip])


def test_content_text_is_recorded_when_error_payload_has_no_structured_data() -> None:
    """FastMCP text errors must not collapse to the generic isError label."""
    client = FakeClient(
        {
            "forge_capabilities": _FakeResult(
                is_error=True,
                data=None,
                content=[_FakeTextContent("ToolError: masked upstream failure")],
            )
        }
    )
    ctx = mod.Context(
        args=_fake_args(), base="ContentErrorRun", fixture_patch={"app_name": "Content"}
    )

    rows = asyncio.run(
        mod.run_plan(
            client,
            ctx,
            [mod.Step("forge_capabilities", lambda _ctx: mod._call(query=""))],
        )
    )

    assert rows[0].outcome == "error"
    assert rows[0].error == "ToolError: masked upstream failure"


def test_pending_copilot_without_conversation_is_intentionally_skipped() -> None:
    """A pending ask with no id is expected and must not fail the run."""
    ctx = mod.Context(
        args=_fake_args(),
        base="PendingCopilotRun",
        fixture_patch={"app_name": "Pending"},
    )
    ctx.app_id = "app-1"
    mod._after_forge_copilot_ask(
        ctx,
        {
            "conversation_id": None,
            "status": "pending: your message is not in the thread yet",
        },
    )

    decision = mod._decide_forge_copilot_check(ctx)

    assert isinstance(decision, mod.Skip)
    assert decision.reason == (
        "forge_copilot_ask is pending with no conversation_id; "
        "forge_copilot_check is intentionally skipped"
    )
    assert not decision.reason.startswith(mod.DEPENDENCY_SKIP_PREFIX)


def test_matched_copilot_with_conversation_still_runs_check() -> None:
    """A matched ask keeps the normal check path available."""
    ctx = mod.Context(
        args=_fake_args(),
        base="MatchedCopilotRun",
        fixture_patch={"app_name": "Matched"},
    )
    ctx.app_id = "app-1"
    mod._after_forge_copilot_ask(
        ctx, {"conversation_id": "conv-1", "status": "matched"}
    )

    decision = mod._decide_forge_copilot_check(ctx)

    assert isinstance(decision, mod.Call)
    assert decision.arguments["conversation_id"] == "conv-1"


def test_copilot_check_without_app_remains_a_dependency_skip() -> None:
    """A missing app id remains a broken upstream dependency."""
    ctx = mod.Context(
        args=_fake_args(), base="MissingAppRun", fixture_patch={"app_name": "Missing"}
    )
    ctx.copilot_ask_pending = True

    decision = mod._decide_forge_copilot_check(ctx)

    assert isinstance(decision, mod.Skip)
    assert decision.reason.startswith(mod.DEPENDENCY_SKIP_PREFIX)


# =====================================================================================
# 5. The header-building function puts the key pair in the two headers and never
#    logs it.
# =====================================================================================


def test_build_http_headers_carries_the_pair_and_never_logs_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    key_id = "AKIA-EXAMPLE-ID"
    key_secret = "super-secret-value-never-printed"
    headers = mod.build_http_headers(key_id, key_secret)
    assert headers == {
        "X-Access-Key-Id": key_id,
        "X-Access-Key-Secret": key_secret,
    }
    captured = capsys.readouterr()
    assert key_secret not in captured.out
    assert key_secret not in captured.err
