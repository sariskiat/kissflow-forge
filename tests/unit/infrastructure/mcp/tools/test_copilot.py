"""The copilot-family tool module: `register` calls its one work group.

Drives every tool through `create_server()` with a fake lifespan and an
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

from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server
from app.infrastructure.mcp.tools import copilot as copilot_tools


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_the_work_group_without_error() -> None:
    mcp = FastMCP("test")
    copilot_tools.register(mcp)
    assert set(await _tool_names(mcp)) == {"forge_copilot_ask", "forge_copilot_check"}


@pytest.mark.asyncio
async def test_the_work_group_is_independently_callable() -> None:
    mcp = FastMCP("test")
    copilot_tools._register_all(mcp)
    assert set(await _tool_names(mcp)) == {"forge_copilot_ask", "forge_copilot_check"}


# ============================================================================
# Argument mapping, ApplicationError -> ToolError, no key pair -> ToolError
# ============================================================================


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
    copilot: FakeCopilotService | None = None, flow: FakeFlowRepository | None = None
) -> AppResources:
    return AppResources(
        flow=flow or FakeFlowRepository(),
        app=FakeAppRepository(),
        page=FakePageRepository(),
        dataset=FakeDatasetRepository(),
        item=FakeItemService(),
        copilot=copilot or FakeCopilotService(),
        docs=FakeDocsReader(),
        artifacts=FakeArtifactWriter(),
    )


def _server(settings: Settings, resources: AppResources) -> FastMCP:
    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": resources, "settings": settings}

    return create_server(_lifespan)


@pytest.mark.asyncio
async def test_forge_copilot_ask_maps_arguments_and_returns_the_response() -> None:
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [
        [
            {
                "ConversationId": "C1",
                "UserMessage": "add a field",
                "SystemMessage": "which step?",
            }
        ]
    ]
    server = _server(_settings(), _resources(copilot=copilot))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_copilot_ask",
            {"app_id": "App1", "message": "add a field"},
        )

    assert result.data.conversation_id == "C1"
    assert result.data.immediate_reply == "which step?"
    assert copilot.calls[0] == ("copilot_send", ("App1", "add a field"), {})
    # `client.CopilotAskReport.as_tool_result()`'s own key set, minus
    # `isError`, plus `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "app_id",
        "message",
        "conversation_id",
        "immediate_reply",
        "expect",
        "reply_is_proof",
        "status",
        "note",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_copilot_ask_falls_back_to_settings_kf_app() -> None:
    copilot = FakeCopilotService()
    server = _server(_settings(kf_app="App9"), _resources(copilot=copilot))

    async with Client(server) as client:
        await client.call_tool(
            "forge_copilot_ask", {"app_id": "", "message": "add a field"}
        )

    assert copilot.calls[0] == ("copilot_send", ("App9", "add a field"), {})


@pytest.mark.asyncio
async def test_forge_copilot_ask_application_error_becomes_a_tool_error() -> None:
    copilot = FakeCopilotService()
    server = _server(_settings(kf_app=""), _resources(copilot=copilot))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_copilot_ask", {"app_id": "", "message": "add a field"}
            )


@pytest.mark.asyncio
async def test_forge_copilot_ask_no_key_pair_fails_before_the_use_case_runs() -> None:
    copilot = FakeCopilotService()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    server = _server(settings, _resources(copilot=copilot))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_copilot_ask", {"app_id": "App1", "message": "add a field"}
            )
    assert copilot.calls == []


@pytest.mark.asyncio
async def test_forge_copilot_check_maps_arguments_and_returns_the_response() -> None:
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [
        [{"ConversationId": "C1", "SystemMessage": "done"}]
    ]
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "P1"}], [], [], [], []]
    server = _server(_settings(), _resources(copilot=copilot, flow=flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_copilot_check",
            {
                "app_id": "App1",
                "conversation_id": "C1",
                "baseline_inventory": {
                    "process": ["P1"],
                    "form": [],
                    "case": [],
                    "list": [],
                    "dataset": [],
                },
            },
        )

    assert result.data.reply == "done"
    assert result.data.scatter == {}
    # `client.CopilotCheckReport.as_tool_result()`'s own key set, minus
    # `isError` (review fix 5) -- a read/verdict tool, no `snapshot_version`.
    assert set(result.structured_content) == {
        "app_id",
        "conversation_id",
        "reply",
        "reply_is_proof",
        "scatter",
        "landed_nodes",
        "note",
    }


@pytest.mark.asyncio
async def test_forge_copilot_check_reports_no_reply_never_a_tool_error() -> None:
    """Rule 7's verdict-tool exception: a still-pending ask is a successful
    call that reports `reply: None`, never a `ToolError`. The reply is
    never proof either way (THE RULE)."""
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [[]]
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[], [], [], [], []]
    server = _server(_settings(), _resources(copilot=copilot, flow=flow))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_copilot_check", {"app_id": "App1", "conversation_id": "C1"}
        )

    assert result.data.reply is None


@pytest.mark.asyncio
async def test_forge_copilot_check_falls_back_to_settings_kf_app() -> None:
    copilot = FakeCopilotService()
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[], [], [], [], []]
    server = _server(_settings(kf_app="App9"), _resources(copilot=copilot, flow=flow))

    async with Client(server) as client:
        await client.call_tool(
            "forge_copilot_check", {"app_id": "", "conversation_id": "C1"}
        )

    get_calls = [c for c in flow.calls if c[0] == "list_flows"]
    assert get_calls[0][1][0] == "App9"


@pytest.mark.asyncio
async def test_forge_copilot_check_no_key_pair_fails_before_the_use_case_runs() -> None:
    copilot = FakeCopilotService()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    server = _server(settings, _resources(copilot=copilot))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_copilot_check",
                {"app_id": "App1", "conversation_id": "C1"},
            )
    assert copilot.calls == []
