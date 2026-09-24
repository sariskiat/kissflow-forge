"""The flow-family tool module: `register` calls all four work groups.

Stage D groups 1 (fields), 2 (structure), 3 (workflow) and 4 (lifecycle) have
each filled their own `_register_*` group. Group 1's tools are driven through a
real `FastMCP` built with `_register_fields` alone; group 3's and group 4's
through `create_server()` with a fake lifespan. All call through an in-process
`fastmcp.Client` -- proving argument mapping, `ApplicationError` -> `ToolError`,
and the missing-key-pair guard all the way through the thin tool, not just
through `_shared.run_use_case` in isolation (already covered by
`tests/unit/infrastructure/mcp/tools/test__shared.py`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from tests.fakes.app import FakeAppRepository
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.copilot import FakeCopilotService
from tests.fakes.dataset import FakeDatasetRepository
from tests.fakes.docs import FakeDocsReader
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.item import FakeItemService
from tests.fakes.page import FakePageRepository

from app.application.exceptions import RepositoryError
from app.domain.entities.flow_draft import FlowDraft, progressive_matrix
from app.domain.entities.page_draft import PageDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server
from app.infrastructure.mcp.tools import flow as flow_tools


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_every_work_group_without_error() -> None:
    mcp = FastMCP("test")
    flow_tools.register(mcp)
    names = set(await _tool_names(mcp))
    assert names == {
        # group 1, flow fields
        "kf_apply_field_change",
        "forge_apply_fields",
        "forge_apply_layout",
        "forge_delete_fields",
        "forge_rename_fields",
        "forge_set_required",
        # group 2, flow structure
        "forge_add_table",
        "forge_add_sequence_number",
        "forge_add_field_validation",
        "forge_set_styles",
        "forge_set_events",
        # group 3, flow workflow
        "forge_add_goto_gate",
        "forge_build_workflow",
        "forge_set_branch_conditions",
        "forge_set_visibility",
        "kf_set_step_visibility",
        # group 4, flow lifecycle
        "kf_get_flow_schema",
        "kf_create_process",
        "kf_publish",
        "forge_create_process",
        "forge_create_list",
        "forge_publish",
        "forge_doctor",
        "forge_delete_flow",
        "forge_create_flow",
    }


def test_every_work_group_is_independently_callable() -> None:
    """Each group takes the server alone, so two writers filling different groups in
    Stage D can each test their own function in isolation."""
    mcp = FastMCP("test")
    flow_tools._register_fields(mcp)
    flow_tools._register_structure(mcp)
    flow_tools._register_workflow(mcp)
    flow_tools._register_lifecycle(mcp)


# =====================================================================================
# _register_fields (Stage D group 1): the six field tools, driven through a real
# in-process MCP client.
# =====================================================================================


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "A1",
        "kf_app": None,
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": "k1",
        "kf_dev_access_key_secret": "s1",
        "http_timeout_seconds": 10.0,
    }
    base.update(overrides)
    return Settings(**base)


def _lifespan(flow: FakeFlowRepository, settings: Settings) -> Any:
    @asynccontextmanager
    async def _run(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        resources = AppResources(
            flow=flow,
            app=FakeAppRepository(),
            page=FakePageRepository(),
            dataset=FakeDatasetRepository(),
            item=FakeItemService(),
            copilot=FakeCopilotService(),
            docs=FakeDocsReader(),
            artifacts=FakeArtifactWriter(),
        )
        yield {"resources": resources, "settings": settings}

    return _run


def _server(flow: FakeFlowRepository, settings: Settings) -> FastMCP:
    mcp = FastMCP("test", lifespan=_lifespan(flow, settings))
    flow_tools._register_fields(mcp)
    return mcp


def _bare_form_draft(version: str = "v1") -> dict[str, Any]:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
    }


@pytest.mark.asyncio
async def test_kf_apply_field_change_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    after = before.apply_changes([FieldSpec(name="alpha", type=FieldType.TEXTAREA)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    async with Client(_server(fake, _settings())) as client:
        result = await client.call_tool(
            "kf_apply_field_change",
            {
                "flow_kind": "form",
                "flow_id": "F1",
                "changes": [{"name": "alpha", "type": "Textarea"}],
                "app_id": "A1",
            },
        )

    assert result.structured_content["added"] == ["alpha"]
    assert result.structured_content["snapshot_version"] == "v1"
    # `app.infrastructure.kissflow.client.ApplyReport.as_tool_result()`'s own key
    # set, minus `isError`, plus `snapshot_version` -- see
    # test_kf_apply_field_change_response.py's own `OLD_KEYS`.
    assert set(result.structured_content) == {
        "flow_id",
        "added",
        "skipped",
        "verified",
        "missing",
        "changed_ignored",
        "collateral",
        "remediation",
        "meta_version",
        "published",
        "snapshot_version",
    }
    get_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert get_calls[0][1] == ("A1", "form", "F1")


@pytest.mark.asyncio
async def test_kf_apply_field_change_falls_back_to_settings_kf_app() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    async with Client(_server(fake, _settings(kf_app="App9"))) as client:
        await client.call_tool(
            "kf_apply_field_change",
            {"flow_kind": "form", "flow_id": "F1", "changes": []},
        )

    get_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert get_calls[0][1] == ("App9", "form", "F1")


@pytest.mark.asyncio
async def test_kf_apply_field_change_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "kf_apply_field_change",
                {"flow_kind": "form", "flow_id": "F1", "changes": []},
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_kf_apply_field_change_write_that_did_not_land_is_a_tool_error() -> None:
    """Rule 7 (`brief_stage_d_common.md`): a field missing on read-back is a failure
    at the tool edge too, not a "success" response the caller has to inspect."""
    before = FlowDraft.from_wire(_bare_form_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match=r"missing=\['ghost'\]"):
            await client.call_tool(
                "kf_apply_field_change",
                {
                    "flow_kind": "form",
                    "flow_id": "F1",
                    "changes": [{"name": "ghost", "type": "Text"}],
                    "app_id": "A1",
                },
            )


@pytest.mark.asyncio
async def test_kf_apply_field_change_no_key_pair_fails_before_the_use_case_runs() -> (
    None
):
    fake = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)

    async with Client(_server(fake, settings)) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "kf_apply_field_change",
                {"flow_kind": "form", "flow_id": "F1", "changes": [], "app_id": "A1"},
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_apply_fields_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    after = before.apply_changes([FieldSpec(name="alpha", type=FieldType.TEXT)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    async with Client(_server(fake, _settings())) as client:
        result = await client.call_tool(
            "forge_apply_fields",
            {
                "flow_id": "F1",
                "fields": [{"name": "alpha", "type": "Text"}],
                "app_id": "A1",
            },
        )

    assert result.structured_content["verified"] == ["alpha"]
    # `app.infrastructure.kissflow.client.FullFieldsReport.as_tool_result()`'s own
    # key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "added",
        "skipped",
        "verified",
        "missing",
        "changed_ignored",
        "collateral",
        "remediation",
        "validations_verified",
        "validations_missing",
        "computed_verified",
        "computed_missing",
        "conditional_verified",
        "conditional_missing",
        "meta_version",
        "published",
        "snapshot_version",
    }
    put_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert put_calls[0][1] == ("A1", "process", "F1")


@pytest.mark.asyncio
async def test_forge_apply_fields_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_apply_fields", {"flow_id": "F1", "fields": []}
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_apply_fields_a_write_that_did_not_land_becomes_a_tool_error() -> (
    None
):
    before = FlowDraft.from_wire(_bare_form_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match=r"missing=\['ghost'\]"):
            await client.call_tool(
                "forge_apply_fields",
                {
                    "flow_id": "F1",
                    "fields": [{"name": "ghost", "type": "Text"}],
                    "app_id": "A1",
                },
            )


@pytest.mark.asyncio
async def test_forge_apply_fields_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)

    async with Client(_server(fake, settings)) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_apply_fields",
                {"flow_id": "F1", "fields": [], "app_id": "A1"},
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_apply_layout_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="a", type=FieldType.TEXT)]
    )
    before = before.regroup_into_sections(before.merge_groups([("G", ["a"])]))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    async with Client(_server(fake, _settings())) as client:
        result = await client.call_tool(
            "forge_apply_layout",
            {
                "flow_id": "F1",
                "layout": {"G": [[["a", 0, 6]]]},
                "kind": "form",
                "app_id": "A1",
            },
        )

    assert result.structured_content["verified"] == ["G"]
    # `app.infrastructure.kissflow.client.ApplyReport.as_tool_result()`'s own key
    # set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "added",
        "skipped",
        "verified",
        "missing",
        "changed_ignored",
        "collateral",
        "remediation",
        "meta_version",
        "published",
        "snapshot_version",
    }
    get_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert get_calls[0][1] == ("A1", "form", "F1")


@pytest.mark.asyncio
async def test_forge_apply_layout_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match="VERIFY_FAILED|off the grid|grid"):
            await client.call_tool(
                "forge_apply_layout",
                {"flow_id": "F1", "layout": {"S": [[["a", 0, 99]]]}, "app_id": "A1"},
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_apply_layout_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)

    async with Client(_server(fake, settings)) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_apply_layout",
                {
                    "flow_id": "F1",
                    "layout": {"G": [[["a", 0, 6]]]},
                    "app_id": "A1",
                },
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_delete_fields_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="drop", type=FieldType.TEXT)]
    )
    after = before.delete_nodes(("drop",))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    async with Client(_server(fake, _settings())) as client:
        result = await client.call_tool(
            "forge_delete_fields",
            {"flow_id": "F1", "fields": ["drop"], "app_id": "A1"},
        )

    assert result.structured_content["deleted"] == ["drop"]
    # `app.infrastructure.kissflow.client.DeleteFieldsReport.as_tool_result()`'s
    # own key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "fields",
        "tables",
        "deleted",
        "surviving",
        "collateral",
        "meta_version",
        "published",
        "snapshot_version",
    }
    get_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert get_calls[0][1] == ("A1", "process", "F1")


@pytest.mark.asyncio
async def test_forge_delete_fields_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_delete_fields", {"flow_id": "F1", "fields": ["a"]}
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_delete_fields_a_write_that_did_not_land_becomes_a_tool_error() -> (
    None
):
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="drop", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    # read-back queued UNCHANGED: the write was "accepted" but nothing changed.
    fake.results["get_draft"] = [before, before]

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match=r"surviving=\['drop'\]"):
            await client.call_tool(
                "forge_delete_fields",
                {"flow_id": "F1", "fields": ["drop"], "app_id": "A1"},
            )


@pytest.mark.asyncio
async def test_forge_delete_fields_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)

    async with Client(_server(fake, settings)) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_delete_fields",
                {"flow_id": "F1", "fields": ["a"], "app_id": "A1"},
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_rename_fields_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="old", type=FieldType.TEXT)]
    )
    after = before.rename_fields({"old": "new"})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    async with Client(_server(fake, _settings())) as client:
        result = await client.call_tool(
            "forge_rename_fields",
            {"flow_id": "F1", "renames": {"old": "new"}, "app_id": "A1"},
        )

    assert result.structured_content["verified"] == ["old -> new"]
    # `app.infrastructure.kissflow.client.RenameFieldsReport.as_tool_result()`'s
    # own key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "renames",
        "verified",
        "missing",
        "stale",
        "unchanged",
        "meta_version",
        "published",
        "snapshot_version",
    }
    get_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert get_calls[0][1] == ("A1", "process", "F1")


@pytest.mark.asyncio
async def test_forge_rename_fields_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_rename_fields", {"flow_id": "F1", "renames": {}}
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_rename_fields_a_write_that_did_not_land_becomes_a_tool_error() -> (
    None
):
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="old", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    # read-back queued UNCHANGED: "new" never actually landed.
    fake.results["get_draft"] = [before, before]

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match=r"missing=\['old -> new'\]"):
            await client.call_tool(
                "forge_rename_fields",
                {"flow_id": "F1", "renames": {"old": "new"}, "app_id": "A1"},
            )


@pytest.mark.asyncio
async def test_forge_rename_fields_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)

    async with Client(_server(fake, settings)) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_rename_fields",
                {"flow_id": "F1", "renames": {"a": "b"}, "app_id": "A1"},
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_set_required_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="a", type=FieldType.TEXT)]
    )
    after = before.set_required({"a"})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    async with Client(_server(fake, _settings())) as client:
        result = await client.call_tool(
            "forge_set_required",
            {"flow_id": "F1", "required": ["a"], "app_id": "A1"},
        )

    assert result.structured_content["verified"] == ["a"]
    # `app.infrastructure.kissflow.client.RequiredReport.as_tool_result()`'s own
    # key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "required",
        "verified",
        "missing",
        "cleared",
        "meta_version",
        "published",
        "snapshot_version",
    }
    get_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert get_calls[0][1] == ("A1", "process", "F1")


@pytest.mark.asyncio
async def test_forge_set_required_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_set_required", {"flow_id": "F1", "required": []}
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_set_required_a_write_that_did_not_land_becomes_a_tool_error() -> (
    None
):
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="a", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    # read-back queued UNCHANGED: the Required flag never actually landed.
    fake.results["get_draft"] = [before, before]

    async with Client(_server(fake, _settings())) as client:
        with pytest.raises(ToolError, match=r"missing=\['a'\]"):
            await client.call_tool(
                "forge_set_required",
                {"flow_id": "F1", "required": ["a"], "app_id": "A1"},
            )


@pytest.mark.asyncio
async def test_forge_set_required_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)

    async with Client(_server(fake, settings)) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_set_required",
                {"flow_id": "F1", "required": ["a"], "app_id": "A1"},
            )
    assert fake.calls == []


# =====================================================================================
# d3_flow_workflow -- forge_build_workflow, forge_add_goto_gate,
# forge_set_branch_conditions, forge_set_visibility, kf_set_step_visibility.
# Thin-tool argument mapping, ApplicationError -> ToolError, and the no-key-pair gate.
# =====================================================================================


def _wf_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "ACC1",
        # The KF_APP single-app default, so a tool call below can omit its own
        # app_id and still resolve one; the app-id-empty refusal itself is a
        # use-case-level concern, already covered in test_forge_*.py.
        "kf_app": "App1",
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": "k1",
        "kf_dev_access_key_secret": "s1",
        "http_timeout_seconds": 10.0,
    }
    values.update(overrides)
    return Settings(**values)


def _lifespan_factory(flow: FakeFlowRepository, **settings_overrides: Any):
    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> Any:
        del server
        yield {
            "settings": _wf_settings(**settings_overrides),
            "resources": SimpleNamespace(flow=flow),
        }

    return _lifespan


def _bare_process_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


@pytest.mark.asyncio
async def test_forge_build_workflow_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_process_draft())
    after = before.build_workflow([("Draft", None)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_build_workflow", {"flow_id": "F1", "steps": [["Draft", None]]}
        )
    assert result.data.verified_steps == ["Draft"]
    assert result.data.missing_steps == []
    # `app.infrastructure.kissflow.client.WorkflowReport.as_tool_result()`'s own
    # key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "steps",
        "verified_steps",
        "missing_steps",
        "assigned",
        "unassigned",
        "permissions_deleted",
        "collateral",
        "remediation",
        "meta_version",
        "published",
        "snapshot_version",
    }
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]


@pytest.mark.asyncio
async def test_forge_build_workflow_maps_an_explicit_app_id_over_kf_app_default() -> (
    None
):
    """A caller-passed `app_id` (brief_d13_fix.md fix 9: "ignores the caller's
    app_id") must reach the use case, not just the `KF_APP` single-app
    default `_wf_settings` sets for every other test in this block."""
    before = FlowDraft.from_wire(_bare_process_draft())
    after = before.build_workflow([("Draft", None)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        await client.call_tool(
            "forge_build_workflow",
            {"flow_id": "F1", "steps": [["Draft", None]], "app_id": "Explicit1"},
        )
    get_calls = [c for c in fake.calls if c[0] == "get_draft"]
    assert get_calls[0][1][0] == "Explicit1"


@pytest.mark.asyncio
async def test_forge_build_workflow_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire(_bare_process_draft())]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="offline build_workflow rejected the spec"):
            await client.call_tool(
                "forge_build_workflow",
                {
                    "flow_id": "F1",
                    "steps": [["S1", None]],
                    "parallel": {
                        "name": "Route",
                        "branches": [
                            ["Same", [["A", None]]],
                            ["Same", [["B", None]]],
                        ],
                    },
                    "parallel_after": 0,
                },
            )
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_forge_build_workflow_no_key_pair_fails_before_use_case_runs() -> None:
    fake = FakeFlowRepository()
    server = create_server(_lifespan_factory(fake, kf_dev_access_key_id=None))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool(
                "forge_build_workflow", {"flow_id": "F1", "steps": []}
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_build_workflow_maps_roles_and_step_meta_to_the_use_case() -> None:
    """`roles` and `step_meta` (`tools/flow.py`'s own two silently-droppable
    parameters, brief_d13_fix.md fix 9) must reach `FlowDraft.build_workflow`:
    a role id resolves to its display name on the step's Resource, and
    `suspended` writes `IsSuspended` on the step's own Activity."""
    before = FlowDraft.from_wire(_bare_process_draft())
    after = before.build_workflow(
        [("Draft", "AppRole_x")],
        roles={"AppRole_x": "Manager"},
        step_meta={"Draft": {"suspended": True}},
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        await client.call_tool(
            "forge_build_workflow",
            {
                "flow_id": "F1",
                "steps": [["Draft", "AppRole_x"]],
                "roles": {"AppRole_x": "Manager"},
                "step_meta": {"Draft": {"suspended": True}},
            },
        )

    written = next(c for c in fake.calls if c[0] == "put_draft")[1][3]
    wire = written.to_wire()
    resource = next(
        v for v in wire.values() if isinstance(v, dict) and v.get("Kind") == "Resource"
    )
    assert resource["DisplayValue"] == "Manager"
    activity = next(
        v
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("Name") == "Draft"
    )
    assert activity.get("IsSuspended") is True


@pytest.mark.asyncio
async def test_forge_add_goto_gate_maps_arguments_and_returns_the_response() -> None:
    before = (
        FlowDraft.from_wire(_bare_process_draft())
        .ensure_process_def(("Review",))
        .apply_changes([FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
    )
    target_id = next(
        k
        for k, v in before.to_wire().items()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("Name") == "Review"
    )
    field_id = next(
        k
        for k, v in before.to_wire().items()
        if isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Name") == "Done Flag"
    )
    with_goto, goto_id = before.add_goto_task(target_activity_id=target_id)
    after = with_goto.build_goto_gate(goto_activity_id=goto_id, field_id=field_id)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_goto_gate",
            {
                "flow_id": "F1",
                "target_activity_name": "Review",
                "field_name": "Done Flag",
            },
        )
    assert result.data.verified is True
    # `app.infrastructure.kissflow.client.GotoGateReport.as_tool_result()`'s own
    # key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "goto_activity_id",
        "target_activity",
        "field_name",
        "branch_name",
        "verified",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_add_goto_gate_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeFlowRepository()
    server = create_server(_lifespan_factory(fake, kf_dev_access_key_id=None))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool(
                "forge_add_goto_gate",
                {
                    "flow_id": "F1",
                    "target_activity_name": "Review",
                    "field_name": "Done Flag",
                },
            )
    assert fake.calls == []


def _branched_process_with_a_repeated_step_name() -> FlowDraft:
    before = FlowDraft.from_wire(_bare_process_draft()).build_workflow(
        [("Intake", None)],
        parallel=(
            "Route",
            [("Branch A", [("Step", None)]), ("Branch B", [("Step", None)])],
        ),
        parallel_after=0,
    )
    return before.apply_changes([FieldSpec(name="Done", type=FieldType.BOOLEAN)])


@pytest.mark.asyncio
async def test_forge_add_goto_gate_without_branch_name_is_ambiguous() -> None:
    """The step name "Step" exists in both branches: with no `branch_name`,
    the use case must refuse rather than silently pick one."""
    before = _branched_process_with_a_repeated_step_name()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="ambiguous"):
            await client.call_tool(
                "forge_add_goto_gate",
                {
                    "flow_id": "F1",
                    "target_activity_name": "Step",
                    "field_name": "Done",
                },
            )
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_forge_add_goto_gate_maps_branch_name_to_scope_the_target() -> None:
    """`branch_name` (brief_d13_fix.md fix 9, a silently-droppable parameter)
    must reach the use case: passing it resolves the SAME ambiguous name the
    previous test refuses without it."""
    before = _branched_process_with_a_repeated_step_name()
    wire = before.to_wire()
    target_id = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("Name") == "Step"
        and v.get("ProcessDef")
        == next(
            vv["Id"]
            for vv in wire.values()
            if isinstance(vv, dict)
            and vv.get("Kind") == "ProcessDef"
            and vv.get("Name") == "Branch A"
        )
    )
    field_id = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Done"
    )
    with_goto, goto_id = before.add_goto_task(target_activity_id=target_id)
    after = with_goto.build_goto_gate(goto_activity_id=goto_id, field_id=field_id)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_goto_gate",
            {
                "flow_id": "F1",
                "target_activity_name": "Step",
                "field_name": "Done",
                "branch_name": "Branch A",
            },
        )
    assert result.data.verified is True


@pytest.mark.asyncio
async def test_forge_add_goto_gate_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire(_bare_process_draft())]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no workflow step named 'Nope'"):
            await client.call_tool(
                "forge_add_goto_gate",
                {
                    "flow_id": "F1",
                    "target_activity_name": "Nope",
                    "field_name": "Nope",
                },
            )
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_forge_set_branch_conditions_maps_args_and_returns_response() -> None:
    before = FlowDraft.from_wire(_bare_process_draft()).build_workflow(
        [("Intake", None)],
        parallel=("Route", [("Branch A", [("S1", None)])]),
        parallel_after=0,
    )
    before = before.apply_changes([FieldSpec(name="Track", type=FieldType.TEXT)])
    field_id = next(
        k
        for k, v in before.to_wire().items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Track"
    )
    pd_id = next(
        v["Id"]
        for v in before.to_wire().values()
        if isinstance(v, dict)
        and v.get("Kind") == "ProcessDef"
        and v.get("Name") == "Branch A"
    )
    after = before.build_branch_condition(
        process_def_id=pd_id, field_id=field_id, literal="Alpha", options=None
    )

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_branch_conditions",
            {
                "flow_id": "F1",
                "field_name": "Track",
                "branch_literals": {"Branch A": "Alpha"},
            },
        )
    assert result.data.verified == ["Branch A"]
    # `app.infrastructure.kissflow.client.BranchConditionReport.as_tool_result()`'s
    # own key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "field_name",
        "branches",
        "verified",
        "missing",
        "uncovered",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_set_branch_conditions_no_key_pair_fails_before_use_case_runs() -> (
    None
):
    fake = FakeFlowRepository()
    server = create_server(_lifespan_factory(fake, kf_dev_access_key_id=None))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool(
                "forge_set_branch_conditions",
                {
                    "flow_id": "F1",
                    "field_name": "Track",
                    "branch_literals": {"Branch A": "Alpha"},
                },
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_set_branch_conditions_application_error_becomes_a_tool_error() -> (
    None
):
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire(_bare_process_draft())]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="expected exactly one Parallel gateway"):
            await client.call_tool(
                "forge_set_branch_conditions",
                {
                    "flow_id": "F1",
                    "field_name": "Track",
                    "branch_literals": {"Branch A": "Alpha"},
                },
            )
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_forge_set_visibility_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Start2",))
    matrix = progressive_matrix(before, {})
    after = before.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_visibility", {"flow_id": "F1", "owners": {}}
        )
    assert "pair_counts" in result.data
    assert result.data["snapshot_version"] == "v1"
    assert set(result.structured_content) == {
        "flow_id",
        "pair_counts",
        "missing",
        "by_section",
        "by_step",
        "uncovered_sections",
        "remediation",
        "summarised",
        "meta_version",
        "published",
        "note",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_set_visibility_include_pairs_adds_the_full_pair_list() -> None:
    """`include_pairs` (brief_d13_fix.md fix 9) must reach the use case: only
    `True` adds the `pairs`/`collateral` keys the tool's own docstring
    promises."""
    before = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Start2",))
    matrix = progressive_matrix(before, {})
    after = before.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_visibility",
            {"flow_id": "F1", "owners": {}, "include_pairs": True},
        )
    assert "pairs" in result.structured_content
    assert "collateral" in result.structured_content


@pytest.mark.asyncio
async def test_forge_set_visibility_maps_field_owners_to_the_use_case() -> None:
    """`field_owners` (brief_d13_fix.md fix 9, a silently-droppable parameter)
    must reach the use case: an unresolvable name in it is refused with its
    own distinct message (`FlowDraft.set_step_permissions`'s own
    `field_matrix names a field that does not exist`), never silently
    dropped nor confused with an `owners` refusal."""
    before = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Start2",))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(
            ToolError, match=r"field_matrix names a field that does not exist"
        ):
            await client.call_tool(
                "forge_set_visibility",
                {
                    "flow_id": "F1",
                    "owners": {},
                    "field_owners": {"Ghost": ["Start2"]},
                },
            )
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_forge_set_visibility_no_key_pair_fails_before_the_use_case_runs() -> (
    None
):
    fake = FakeFlowRepository()
    server = create_server(_lifespan_factory(fake, kf_dev_access_key_id=None))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool(
                "forge_set_visibility", {"flow_id": "F1", "owners": {}}
            )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_set_visibility_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="expected exactly one root ProcessDef"):
            await client.call_tool(
                "forge_set_visibility",
                {"flow_id": "F1", "owners": {"Ghost": ["Start"]}},
            )
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_kf_set_step_visibility_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Start2",))
    matrix = progressive_matrix(before, {})
    after = before.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "kf_set_step_visibility", {"flow_id": "F1", "owners": {}}
        )
    assert "pair_counts" in result.data
    assert [c[1][1] for c in fake.calls if c[0] == "get_draft"] == [
        "process",
        "process",
    ]
    assert set(result.structured_content) == {
        "flow_id",
        "pair_counts",
        "missing",
        "by_section",
        "by_step",
        "uncovered_sections",
        "remediation",
        "summarised",
        "meta_version",
        "published",
        "note",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_kf_set_step_visibility_include_pairs_adds_the_full_pair_list() -> None:
    """`include_pairs` (brief_d13_fix.md fix 9) must reach the use case."""
    before = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Start2",))
    matrix = progressive_matrix(before, {})
    after = before.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool(
            "kf_set_step_visibility",
            {"flow_id": "F1", "owners": {}, "include_pairs": True},
        )
    assert "pairs" in result.structured_content
    assert "collateral" in result.structured_content


@pytest.mark.asyncio
async def test_kf_set_step_visibility_application_error_becomes_a_tool_error() -> None:
    fake = FakeFlowRepository()

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="expected exactly one root ProcessDef"):
            await client.call_tool(
                "kf_set_step_visibility",
                {"flow_id": "F1", "owners": {"Ghost": ["Start"]}},
            )
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_kf_set_step_visibility_no_key_pair_fails_before_the_use_case_runs() -> (
    None
):
    fake = FakeFlowRepository()
    server = create_server(_lifespan_factory(fake, kf_dev_access_key_id=None))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool(
                "kf_set_step_visibility", {"flow_id": "F1", "owners": {}}
            )
    assert fake.calls == []


# ============================================================================
# _register_structure's own tools (Stage D group 2: flow, structure).
# forge_add_table, forge_add_sequence_number, forge_add_field_validation,
# forge_set_styles, forge_set_events. Appended here, never editing the
# generic tests above -- each group's own block is spaced apart the same
# way `tools/flow.py` itself spaces `_register_*` bodies, so two groups'
# additions merge without touching the same lines.
# ============================================================================

_BARE_FORM = {
    "Root": "M1",
    "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
}


def _st_settings(key_id: str | None = "k1", key_secret: str | None = "s1") -> Settings:
    return Settings(
        kf_dev_domain="dev-acme.kissflow.com",
        kf_dev_account_id="ACC1",
        kf_app=None,
        kf_process_template=None,
        port=8080,
        mcp_http=False,
        kf_dev_access_key_id=key_id,
        kf_dev_access_key_secret=key_secret,
        http_timeout_seconds=10.0,
    )


def _resources(
    flow: FakeFlowRepository | None = None, page: FakePageRepository | None = None
) -> AppResources:
    return AppResources(
        flow=flow or FakeFlowRepository(),
        app=FakeAppRepository(),
        page=page or FakePageRepository(),
        dataset=FakeDatasetRepository(),
        item=FakeItemService(),
        copilot=FakeCopilotService(),
        docs=FakeDocsReader(),
        artifacts=FakeArtifactWriter(),
    )


def _structure_server(settings: Settings, flow: FakeFlowRepository) -> FastMCP:
    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": _resources(flow), "settings": settings}

    return create_server(_lifespan)


@pytest.mark.asyncio
async def test_forge_add_table_maps_arguments_and_returns_the_response() -> None:
    before = FlowDraft.from_wire(_BARE_FORM)
    after = before.add_table("Rounds", [("Round", "Number")])
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [before, after]
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_table",
            {
                "flow_id": "F1",
                "name": "Rounds",
                "columns": [["Round", "Number"]],
                "app_id": "A1",
            },
        )

    assert result.data.table_name == "Rounds"
    assert result.data.verified_columns == ["Round"]
    assert flow.calls[0][1][:2] == ("A1", "process")
    # `app.infrastructure.kissflow.client.TableReport.as_tool_result()`'s own key
    # set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "table_name",
        "created",
        "columns",
        "verified_columns",
        "missing_columns",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_add_table_application_error_becomes_a_tool_error() -> None:
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_add_table",
                {
                    "flow_id": "F1",
                    "name": "Rounds",
                    "columns": [["Round", "Number"]],
                },
            )


@pytest.mark.asyncio
async def test_forge_add_table_no_key_pair_fails_before_the_use_case_runs() -> None:
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(key_id=None, key_secret=None), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_add_table",
                {
                    "flow_id": "F1",
                    "name": "Rounds",
                    "columns": [["Round", "Number"]],
                    "app_id": "A1",
                },
            )
    assert flow.calls == []


@pytest.mark.asyncio
async def test_forge_add_sequence_number_maps_arguments() -> None:
    # A process draft with a section and a Start step, the same recipe the
    # use-case test uses (`test_forge_add_sequence_number.py`).
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    wire = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(wire)
        .apply_changes([FieldSpec(name="a", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("S", ["a"])]).to_wire()
    d = FlowDraft.from_wire(d).build_workflow([("Log it", None)]).to_wire()
    before = FlowDraft.from_wire(d)
    after = before.add_sequence_number("Case ID", "S", "CS-", "0001", "Start")

    flow = FakeFlowRepository()
    flow.results["get_draft"] = [before, after]
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_sequence_number",
            {
                "flow_id": "F1",
                "field_name": "Case ID",
                "section_name": "S",
                "prefix": "CS-",
                "padding": "0001",
                "step_activity_name": "Start",
                "app_id": "A1",
            },
        )

    assert result.data.field_name == "Case ID"
    assert result.data.verified is True
    # `app.infrastructure.kissflow.client.SequenceNumberReport.as_tool_result()`'s
    # own key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "field_name",
        "section",
        "verified",
        "missing",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_add_sequence_number_application_error_becomes_a_tool_error() -> (
    None
):
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_add_sequence_number",
                {
                    "flow_id": "F1",
                    "field_name": "Case ID",
                    "section_name": "S",
                    "prefix": "CS-",
                    "padding": "0001",
                    "step_activity_name": "Start",
                },
            )


@pytest.mark.asyncio
async def test_forge_add_sequence_number_no_key_pair_fails_before_use_case_runs() -> (
    None
):
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(key_id=None, key_secret=None), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_add_sequence_number",
                {
                    "flow_id": "F1",
                    "field_name": "Case ID",
                    "section_name": "S",
                    "prefix": "CS-",
                    "padding": "0001",
                    "step_activity_name": "Start",
                    "app_id": "A1",
                },
            )
    assert flow.calls == []


@pytest.mark.asyncio
async def test_forge_add_field_validation_maps_arguments() -> None:
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    d = (
        FlowDraft.from_wire(_BARE_FORM)
        .apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT)])
        .to_wire()
    )
    before = FlowDraft.from_wire(d)
    after = before.add_field_validation("Notes", "CONTAINS", "important")

    flow = FakeFlowRepository()
    flow.results["get_draft"] = [before, after]
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_field_validation",
            {
                "flow_id": "F1",
                "rules": {"Notes": [["CONTAINS", "important"]]},
                "app_id": "A1",
            },
        )

    assert result.data.verified == [["CONTAINS", "important"]]
    # `app.infrastructure.kissflow.client.ValidationReport.as_tool_result()`'s own
    # key set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "field_name",
        "rules",
        "verified",
        "missing",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_add_field_validation_application_error_becomes_a_tool_error() -> (
    None
):
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_add_field_validation",
                {"flow_id": "F1", "rules": {"Notes": [["CONTAINS", "important"]]}},
            )


@pytest.mark.asyncio
async def test_forge_add_field_validation_no_key_pair_fails_before_use_case_runs() -> (
    None
):
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(key_id=None, key_secret=None), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_add_field_validation",
                {
                    "flow_id": "F1",
                    "rules": {"Notes": [["CONTAINS", "important"]]},
                    "app_id": "A1",
                },
            )
    assert flow.calls == []


@pytest.mark.asyncio
async def test_forge_set_styles_maps_arguments() -> None:
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    d = (
        FlowDraft.from_wire(_BARE_FORM)
        .apply_changes([FieldSpec(name="A", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("M", ["A"])]).to_wire()
    before = FlowDraft.from_wire(d)
    after = before.set_section_style({"M": {"Section.Bg.Color": "Color.Info.300"}})

    flow = FakeFlowRepository()
    flow.results["get_draft"] = [before, after]
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_styles",
            {
                "flow_id": "F1",
                "styles": {"M": {"Section.Bg.Color": "Color.Info.300"}},
                "app_id": "A1",
            },
        )

    assert result.data.verified == ["M"]
    # `app.infrastructure.kissflow.client.StyleReport.as_tool_result()`'s own key
    # set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "sections",
        "verified",
        "missing",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_set_styles_application_error_becomes_a_tool_error() -> None:
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_set_styles",
                {"flow_id": "F1", "styles": {"M": {"Section.Bg.Color": "x"}}},
            )


@pytest.mark.asyncio
async def test_forge_set_styles_no_key_pair_fails_before_the_use_case_runs() -> None:
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(key_id=None, key_secret=None), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_set_styles",
                {
                    "flow_id": "F1",
                    "styles": {"M": {"Section.Bg.Color": "x"}},
                    "app_id": "A1",
                },
            )
    assert flow.calls == []


@pytest.mark.asyncio
async def test_forge_set_events_maps_arguments() -> None:
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    d = (
        FlowDraft.from_wire(_BARE_FORM)
        .apply_changes([FieldSpec(name="Source", type=FieldType.TEXT)])
        .to_wire()
    )
    before = FlowDraft.from_wire(d)
    after = before.set_field_events({"Source": [("onChange", "kf.x();")]})

    flow = FakeFlowRepository()
    flow.results["get_draft"] = [before, after]
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_events",
            {
                "flow_id": "F1",
                "events": {"Source": [[None, "kf.x();"]]},
                "app_id": "A1",
            },
        )

    assert result.data.verified == ["Source"]
    # `app.infrastructure.kissflow.client.EventReport.as_tool_result()`'s own key
    # set, minus `isError`, plus `snapshot_version`.
    assert set(result.structured_content) == {
        "flow_id",
        "fields",
        "verified",
        "missing",
        "triggers",
        "derived",
        "unverified",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_set_events_application_error_becomes_a_tool_error() -> None:
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_set_events",
                {"flow_id": "F1", "events": {"Source": [[None, "kf.x();"]]}},
            )


@pytest.mark.asyncio
async def test_forge_set_events_no_key_pair_fails_before_the_use_case_runs() -> None:
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(key_id=None, key_secret=None), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_set_events",
                {
                    "flow_id": "F1",
                    "events": {"Source": [[None, "kf.x();"]]},
                    "app_id": "A1",
                },
            )
    assert flow.calls == []


@pytest.mark.asyncio
async def test_structure_tool_with_no_key_pair_fails_before_the_use_case_runs() -> None:
    flow = FakeFlowRepository()
    server = _structure_server(_st_settings(key_id=None, key_secret=None), flow)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_add_table",
                {"flow_id": "F1", "name": "Rounds", "columns": [["Round", "Number"]]},
            )

    assert flow.calls == []


# ============================================================================
# _register_lifecycle's own tools (Stage D group 4: flow, lifecycle).
# kf_get_flow_schema, kf_create_process, kf_publish, forge_create_process,
# forge_create_list, forge_publish, forge_doctor, forge_delete_flow,
# forge_create_flow. Appended here, never editing the generic tests or an
# earlier group's own section above -- same spacing convention those
# sections already use, so two groups' additions merge without touching the
# same lines.
# ============================================================================


def _lifecycle_server(settings: Settings, resources: AppResources) -> FastMCP:
    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": resources, "settings": settings}

    return create_server(_lifespan)


def _lifecycle_draft(version: str = "v1") -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "_meta_version": version,
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
        }
    )


@pytest.mark.asyncio
async def test_kf_get_flow_schema_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"Root": "M1"})]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "kf_get_flow_schema",
            {"flow_kind": "process", "flow_id": "F1", "app_id": "A1"},
        )

    assert result.data == {"Root": "M1"}
    assert flow.calls == [("get_draft", ("A1", "process", "F1"), {})]


@pytest.mark.asyncio
async def test_kf_publish_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_lifecycle_draft("v1")]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "kf_publish", {"flow_kind": "process", "flow_id": "F1", "app_id": "A1"}
        )

    assert result.structured_content["published"] is True
    assert result.structured_content["flow_id"] == "F1"
    assert flow.calls[-1] == ("publish", ("A1", "process", "F1"), {})


@pytest.mark.asyncio
async def test_kf_create_process_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [
        _lifecycle_draft("v1"),
        _lifecycle_draft("v2"),
        _lifecycle_draft("v2"),
    ]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "kf_create_process",
            {
                "name": "Expense Approval",
                "steps": ["Draft"],
                "fields": [],
                "app_id": "A1",
            },
        )

    assert result.structured_content["flow_id"] == "F1"
    assert flow.calls[0] == ("list_flows", ("A1", "process"), {})


@pytest.mark.asyncio
async def test_forge_create_process_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [
        _lifecycle_draft("v1"),
        _lifecycle_draft("v2"),
        _lifecycle_draft("v2"),
    ]
    flow.results["get_members"] = [[{"_id": "Ro1"}]]
    app = FakeAppRepository()
    app.results["create_app_role"] = ["Ro1"]
    server = _lifecycle_server(_settings(), replace(_resources(flow), app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_create_process", {"name": "N", "app_id": "A1"}
        )

    assert result.structured_content["flow_id"] == "F1"
    assert "full process template" in result.structured_content["note"]


def _full_template_run(
    existing_roles: list[dict[str, str]],
) -> tuple[FakeFlowRepository, FakeAppRepository, AppResources]:
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [
        _lifecycle_draft("v1"),
        _lifecycle_draft("v2"),
        _lifecycle_draft("v2"),
    ]
    flow.results["get_members"] = [[{"_id": "Ro1"}]]
    app = FakeAppRepository()
    app.results["list_app_roles"] = [existing_roles]
    app.results["create_app_role"] = ["Ro1"]
    return flow, app, replace(_resources(flow), app=app)


@pytest.mark.asyncio
async def test_forge_create_process_builds_the_full_template_with_its_own_role() -> (
    None
):
    """from_template=True writes the FULL template (real field ids, formulas) after
    granting exactly one AppRole, `<name> Role`, as a member."""
    flow, app, resources = _full_template_run([])
    server = _lifecycle_server(_settings(), resources)

    async with Client(server) as client:
        await client.call_tool("forge_create_process", {"name": "N", "app_id": "A1"})

    created = [c for c in app.calls if c[0] == "create_app_role"]
    assert [c[1] for c in created] == [("N Role",)]
    grants = [c for c in flow.calls if c[0] == "post_member_batch"]
    assert len(grants) == 1
    assert [m["_id"] for m in grants[0][1][3]] == ["Ro1"]
    written = next(c for c in flow.calls if c[0] == "put_draft")[1][3].to_wire()
    assert "requestor" in written and "is_public_form" in written
    assert "_is_public_form" in json.dumps(written, ensure_ascii=False)
    names = [c[0] for c in flow.calls]
    assert names.index("post_member_batch") < names.index("put_draft")


@pytest.mark.asyncio
async def test_forge_create_process_reuses_an_existing_template_role() -> None:
    _flow, app, resources = _full_template_run([{"_id": "Ro1", "Name": "N Role"}])
    server = _lifecycle_server(_settings(), resources)

    async with Client(server) as client:
        await client.call_tool("forge_create_process", {"name": "N", "app_id": "A1"})

    assert not [c for c in app.calls if c[0] == "create_app_role"]


@pytest.mark.asyncio
async def test_forge_create_list_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["list_lists"] = [[]]
    flow.results["create_list"] = [{"_id": "L1"}]
    flow.results["get_list_items"] = [["Low"]]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_create_list",
            {"name": "Priorities", "values": ["Low"], "app_id": "A1"},
        )

    assert result.structured_content["list_id"] == "L1"
    assert result.structured_content["verified_items"] == ["Low"]


@pytest.mark.asyncio
async def test_forge_publish_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_lifecycle_draft("v1")]
    flow.results["get_flow_detail"] = [{"Status": "Live"}]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_publish", {"kind": "process", "flow_id": "F1", "app_id": "A1"}
        )

    assert result.structured_content["status"] == "Live"


@pytest.mark.asyncio
async def test_forge_doctor_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"Root": "M1", "M1": {}})]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_doctor", {"flow_id": "F1", "app_id": "A1"}
        )

    assert result.structured_content["ok"] is True


@pytest.mark.asyncio
async def test_forge_delete_flow_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[], []]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_delete_flow",
            {"kind": "process", "flow_id": "F1", "app_id": "A1"},
        )

    assert result.structured_content["deleted"] is True
    assert result.structured_content["verified"] is True


@pytest.mark.asyncio
async def test_forge_create_flow_maps_arguments_to_the_request() -> None:
    flow = FakeFlowRepository()
    flow.results["create_dataset"] = [{"_id": "D1", "Status": "Live"}]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_create_flow",
            {"kind": "dataset", "name": "Orders", "app_id": "A1"},
        )

    assert result.structured_content["flow_id"] == "D1"
    assert result.structured_content["born_live"] is True


@pytest.mark.asyncio
async def test_lifecycle_tool_application_error_becomes_a_tool_error() -> None:
    server = _lifecycle_server(_settings(), _resources(FakeFlowRepository()))

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc:
            await client.call_tool(
                "kf_get_flow_schema", {"flow_kind": "process", "flow_id": "F1"}
            )
    assert "no app selected" in str(exc.value)


@pytest.mark.asyncio
async def test_lifecycle_tool_with_no_key_pair_fails_before_the_use_case_runs() -> None:
    flow = FakeFlowRepository()
    server = _lifecycle_server(
        _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None),
        _resources(flow),
    )

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc:
            await client.call_tool(
                "kf_get_flow_schema",
                {"flow_kind": "process", "flow_id": "F1", "app_id": "A1"},
            )
    assert "no Kissflow key pair" in str(exc.value)
    assert flow.calls == []


# ---- ported from tests/test_p2_server.py: a page targets the EXPLICIT app_id ---------


@pytest.mark.asyncio
async def test_kf_get_flow_schema_page_kind_routes_the_explicit_app_id() -> None:
    """The EXPLICIT app_id passed by the caller reaches get_page_draft, never a
    substituted KF_APP default."""
    page = FakePageRepository()
    page.results["get_page_draft"] = [PageDraft.from_wire({"Root": "Pg1"})]
    server = _lifecycle_server(_settings(kf_app="A_DEFAULT"), _resources(page=page))

    async with Client(server) as client:
        result = await client.call_tool(
            "kf_get_flow_schema",
            {"flow_kind": "page", "flow_id": "Page1", "app_id": "App_Other"},
        )

    assert result.structured_content == {"Root": "Pg1"}
    assert page.calls == [("get_page_draft", ("App_Other", "Page1"), {})]


@pytest.mark.asyncio
async def test_kf_get_flow_schema_page_kind_requires_app_id_even_with_kf_app_set() -> (
    None
):
    page = FakePageRepository()
    server = _lifecycle_server(_settings(kf_app="A_DEFAULT"), _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc:
            await client.call_tool(
                "kf_get_flow_schema", {"flow_kind": "page", "flow_id": "Page1"}
            )

    assert "app_id is required to read a page draft" in str(exc.value)
    assert page.calls == []


@pytest.mark.asyncio
async def test_forge_publish_page_kind_requires_app_id_even_with_kf_app_set() -> None:
    page = FakePageRepository()
    server = _lifecycle_server(_settings(kf_app="A_DEFAULT"), _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc:
            await client.call_tool(
                "forge_publish", {"kind": "page", "flow_id": "Page1"}
            )

    assert "app_id is required to publish a page" in str(exc.value)
    assert page.calls == []


@pytest.mark.asyncio
async def test_forge_delete_flow_page_kind_requires_app_id_even_with_kf_app_set() -> (
    None
):
    page = FakePageRepository()
    server = _lifecycle_server(_settings(kf_app="A_DEFAULT"), _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc:
            await client.call_tool(
                "forge_delete_flow", {"kind": "page", "flow_id": "Page1"}
            )

    assert "app_id is required to delete a page" in str(exc.value)
    assert page.calls == []


@pytest.mark.asyncio
async def test_a_non_page_kind_falls_back_to_kf_app() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"Root": "M1"})]
    server = _lifecycle_server(_settings(kf_app="A_DEFAULT"), _resources(flow))

    async with Client(server) as client:
        await client.call_tool(
            "kf_get_flow_schema", {"flow_kind": "process", "flow_id": "F1"}
        )

    assert flow.calls == [("get_draft", ("A_DEFAULT", "process", "F1"), {})]


@pytest.mark.asyncio
async def test_create_process_tools_pass_the_configured_template_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ported from tests/test_p2_server.py: the configured process template reaches
    the scaffold of both create-process tools. A tool that dropped this wiring
    would fall back to the shipped default template with nothing to signal it."""
    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1", "F2"]
    flow.results["get_draft"] = [
        _lifecycle_draft("v1"),
        _lifecycle_draft("v2"),
        _lifecycle_draft("v2"),
    ] * 2
    settings = _settings(kf_process_template="shapes/tenant_template.json")
    server = _lifecycle_server(settings, _resources(flow))

    async with Client(server) as client:
        await client.call_tool(
            "kf_create_process",
            {"name": "N", "steps": [], "fields": [], "app_id": "A1"},
        )
        await client.call_tool("forge_create_process", {"name": "N", "app_id": "A1"})

    assert captured == ["shapes/tenant_template.json"] * 2


@pytest.mark.asyncio
async def test_create_flow_tool_passes_the_configured_template_path_for_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ported from tests/test_p2_server.py: forge_create_flow(kind="process") must
    also honor settings.kf_process_template (P1), same as kf_create_process/
    forge_create_process -- it used to fall back to the shipped default template
    with nothing to signal it."""
    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [_lifecycle_draft("v1"), _lifecycle_draft("v2")]
    settings = _settings(kf_process_template="shapes/tenant_template.json")
    server = _lifecycle_server(settings, _resources(flow))

    async with Client(server) as client:
        await client.call_tool(
            "forge_create_flow", {"kind": "process", "name": "N", "app_id": "A1"}
        )

    assert captured == ["shapes/tenant_template.json"]


@pytest.mark.asyncio
async def test_create_flow_tool_leaves_a_caller_supplied_template_path_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit extra["template_path"] from the caller must win over the
    configured tenant default -- the settings value only fills a gap, it never
    overwrites one."""
    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [_lifecycle_draft("v1"), _lifecycle_draft("v2")]
    settings = _settings(kf_process_template="shapes/tenant_template.json")
    server = _lifecycle_server(settings, _resources(flow))

    async with Client(server) as client:
        await client.call_tool(
            "forge_create_flow",
            {
                "kind": "process",
                "name": "N",
                "app_id": "A1",
                "extra": {"template_path": "shapes/caller_template.json"},
            },
        )

    assert captured == ["shapes/caller_template.json"]


# ---- ported from tests/test_mcp_boundary.py: verdict vs. real failure ----------------


@pytest.mark.asyncio
async def test_a_health_verdict_is_not_promoted_to_a_protocol_error() -> None:
    """forge_doctor is a read-only audit: a run that finds problems has WORKED. The
    verdict is `ok: false` in the response, never a failed call. The old payload's
    own `isError` key is gone: the response DTO carries no isError."""
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [
        FlowDraft.from_wire(
            {
                "Root": "M1",
                "M1": {"Id": "M1", "Kind": "Model"},
                "A1": {"Id": "A1", "Kind": "Activity", "Name": "S1"},
                "R1": {"Id": "R1", "Kind": "Row", "Row::Column": ["C_a"]},
                "S1": {
                    "Id": "S1",
                    "Kind": "Column",
                    "Type": "Section",
                    "Name": "Ghost",
                    "Column::Row": ["R1"],
                },
                "C_a": {
                    "Id": "C_a",
                    "Kind": "Column",
                    "Type": "Field",
                    "Name": "F",
                    "Start": 0,
                    "End": 2,
                },
            }
        )
    ]
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_doctor", {"flow_id": "F1", "app_id": "A1"}, raise_on_error=False
        )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["ok"] is False
    assert result.structured_content["problems"]


@pytest.mark.asyncio
async def test_a_real_failure_is_still_promoted_end_to_end() -> None:
    """The control: a genuine failure still reaches the envelope."""
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_lifecycle_draft("v1")]

    async def _publish_fails(*args: object, **kwargs: object) -> None:
        raise RepositoryError("POST publish -> 500")

    flow.publish = _publish_fails  # type: ignore
    server = _lifecycle_server(_settings(), _resources(flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "kf_publish",
            {"flow_kind": "process", "flow_id": "X", "app_id": "A1"},
            raise_on_error=False,
        )

    assert result.is_error is True
    assert "POST publish -> 500" in str(result.content)
