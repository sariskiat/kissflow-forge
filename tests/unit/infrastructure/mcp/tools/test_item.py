"""The item-family tool module: `register` calls its one work group.

Drives the tool through `create_server()` with a fake lifespan and an
in-process `fastmcp.Client` -- argument mapping, `ApplicationError` ->
`ToolError`, and the missing-key-pair guard, the same shape
`tests/unit/infrastructure/mcp/tools/test_flow.py` uses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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

from app.domain.entities.flow_draft import FlowDraft
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server
from app.infrastructure.mcp.tools import item as item_tools

_CONTEXT = [{"_context_activity_instance_id": "AIID-1"}]


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_the_work_group_without_error() -> None:
    mcp = FastMCP("test")
    item_tools.register(mcp)
    assert await _tool_names(mcp) == ["forge_simulate_case"]


@pytest.mark.asyncio
async def test_the_work_group_is_independently_callable() -> None:
    mcp = FastMCP("test")
    item_tools._register_all(mcp)
    assert set(await _tool_names(mcp)) == {"forge_simulate_case"}


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "ACC1",
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


def _resources(
    item: FakeItemService | None = None, flow: FakeFlowRepository | None = None
) -> AppResources:
    return AppResources(
        flow=flow or FakeFlowRepository(),
        app=FakeAppRepository(),
        page=FakePageRepository(),
        dataset=FakeDatasetRepository(),
        item=item or FakeItemService(),
        copilot=FakeCopilotService(),
        docs=FakeDocsReader(),
        artifacts=FakeArtifactWriter(),
    )


def _server(settings: Settings, resources: AppResources) -> FastMCP:
    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": resources, "settings": settings}

    return create_server(_lifespan)


def _named_draft() -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "M1": {"Id": "M1", "Kind": "Model", "FlowType": "Process"},
            "Field_a": {
                "Id": "Field_a",
                "Kind": "Field",
                "Name": "Business Unit ID",
                "Model": "M1",
            },
        }
    )


@pytest.mark.asyncio
async def test_maps_arguments_and_returns_the_response() -> None:
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [
        {"Field_a": "a1", "_current_context": _CONTEXT},
        {"Field_a": "a1", "_current_context": _CONTEXT},
    ]
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]
    server = _server(_settings(), _resources(item=item, flow=flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_simulate_case",
            {
                "flow_id": "Flow_1",
                "steps": [{"name": "step-1", "values": {"Field_a": "a1"}}],
                "poll": False,
                "app_id": "App1",
            },
        )

    assert result.data.advanced == ["step-1"]
    get_draft_calls = [c for c in flow.calls if c[0] == "get_draft"]
    assert get_draft_calls[0][1] == ("App1", "process", "Flow_1")
    # `server.py:1702-1713`'s own success dict, minus `isError`, plus
    # `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "flow_id",
        "iid",
        "created",
        "planned",
        "filled",
        "advanced",
        "rejected",
        "failed",
        "error",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_falls_back_to_settings_kf_app() -> None:
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [
        {"Field_a": "a1", "_current_context": _CONTEXT},
        {"Field_a": "a1", "_current_context": _CONTEXT},
    ]
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]
    server = _server(_settings(kf_app="App9"), _resources(item=item, flow=flow))

    async with Client(server) as client:
        await client.call_tool(
            "forge_simulate_case",
            {
                "flow_id": "Flow_1",
                "steps": [{"name": "step-1", "values": {"Field_a": "a1"}}],
                "poll": False,
            },
        )

    get_draft_calls = [c for c in flow.calls if c[0] == "get_draft"]
    assert get_draft_calls[0][1] == ("App9", "process", "Flow_1")


@pytest.mark.asyncio
async def test_application_error_becomes_a_tool_error() -> None:
    item = FakeItemService()
    flow = FakeFlowRepository()
    server = _server(_settings(), _resources(item=item, flow=flow))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_simulate_case",
                {"flow_id": "Flow_1", "steps": [], "poll": False},
            )


@pytest.mark.asyncio
async def test_a_malformed_step_becomes_a_tool_error_naming_the_index() -> None:
    """Review fix 3: the DTO's own shape-error text must still reach the
    caller through `ToolError`, the same as it did through the old
    `server.py`'s `coerce_case_steps` (`tests/test_mcp_boundary.py:596-603`,
    pre-refactor)."""
    item = FakeItemService()
    flow = FakeFlowRepository()
    server = _server(_settings(), _resources(item=item, flow=flow))

    async with Client(server) as client:
        with pytest.raises(ToolError, match=r"steps\[0\]\['name'\]"):
            await client.call_tool(
                "forge_simulate_case",
                {"flow_id": "F", "steps": [{"values": {}}], "app_id": "App1"},
            )
    assert item.calls == [] and flow.calls == []


@pytest.mark.asyncio
async def test_no_key_pair_fails_before_the_use_case_runs() -> None:
    item = FakeItemService()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    server = _server(settings, _resources(item=item))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_simulate_case",
                {"flow_id": "Flow_1", "steps": [], "app_id": "App1"},
            )
    assert item.calls == []
