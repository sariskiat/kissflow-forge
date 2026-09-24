"""The dataset-family tool module: `register` calls its one work group.

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

from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server
from app.infrastructure.mcp.tools import dataset as dataset_tools


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_the_work_group_without_error() -> None:
    mcp = FastMCP("test")
    dataset_tools.register(mcp)
    assert await _tool_names(mcp) == ["forge_dataset_records"]


@pytest.mark.asyncio
async def test_the_work_group_is_independently_callable() -> None:
    mcp = FastMCP("test")
    dataset_tools._register_all(mcp)
    assert set(await _tool_names(mcp)) == {"forge_dataset_records"}


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
    dataset: FakeDatasetRepository | None = None, flow: FakeFlowRepository | None = None
) -> AppResources:
    return AppResources(
        flow=flow or FakeFlowRepository(),
        app=FakeAppRepository(),
        page=FakePageRepository(),
        dataset=dataset or FakeDatasetRepository(),
        item=FakeItemService(),
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


@pytest.mark.asyncio
async def test_maps_arguments_and_returns_the_response() -> None:
    dataset = FakeDatasetRepository()
    dataset.results["list_dataset_records"] = [
        {"Columns": [], "Data": [{"_id": "Rec_1"}]}
    ]
    server = _server(_settings(), _resources(dataset=dataset))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_dataset_records",
            {"flow_id": "Flow_1", "op": "list", "app_id": "App1"},
        )

    assert result.structured_content["listed"] == 1
    assert dataset.calls[0][1] == ("App1", "Flow_1")
    # `client.apply_dataset_records`'s own `base` dict plus the `list`
    # branch's own extra keys, minus `isError`, plus `snapshot_version`
    # (review fix 5; `client.py:5737-5817`, pre-refactor).
    assert set(result.structured_content) == {
        "flow_id",
        "op",
        "created",
        "listed",
        "updated",
        "deleted",
        "failed",
        "columns",
        "records",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_create_op_maps_arguments_and_returns_the_response() -> None:
    dataset = FakeDatasetRepository()
    dataset.results["create_dataset_record"] = [{"_id": "Rec_new"}]
    server = _server(_settings(), _resources(dataset=dataset))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_dataset_records",
            {
                "flow_id": "Flow_1",
                "op": "create",
                "app_id": "App1",
                "record": {"Name": "K1", "Field_a": "v"},
            },
        )

    assert result.structured_content["created"] == 1
    # `base` dict plus the `create` branch's own `record` key, minus
    # `isError`, plus `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "flow_id",
        "op",
        "created",
        "listed",
        "updated",
        "deleted",
        "failed",
        "record",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_update_op_maps_arguments_and_returns_the_response() -> None:
    dataset = FakeDatasetRepository()
    dataset.results["update_dataset_record"] = [{"_id": "Rec_9"}]
    server = _server(_settings(), _resources(dataset=dataset))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_dataset_records",
            {
                "flow_id": "Flow_1",
                "op": "update",
                "app_id": "App1",
                "record": {"Field_a": "v"},
                "record_id": "Rec_9",
            },
        )

    assert result.structured_content["updated"] == 1
    # `base` dict plus the `update` branch's own `record_id`/`record` keys,
    # minus `isError`, plus `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "flow_id",
        "op",
        "created",
        "listed",
        "updated",
        "deleted",
        "failed",
        "record_id",
        "record",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_delete_op_maps_arguments_and_returns_the_response() -> None:
    dataset = FakeDatasetRepository()
    server = _server(_settings(), _resources(dataset=dataset))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_dataset_records",
            {
                "flow_id": "Flow_1",
                "op": "delete",
                "app_id": "App1",
                "record": {"Name": "K1"},
                "record_id": "Rec_9",
            },
        )

    assert result.structured_content["deleted"] == 1
    # `base` dict plus the `delete` branch's own `record_id` key, minus
    # `isError`, plus `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "flow_id",
        "op",
        "created",
        "listed",
        "updated",
        "deleted",
        "failed",
        "record_id",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_falls_back_to_settings_kf_app() -> None:
    dataset = FakeDatasetRepository()
    dataset.results["list_dataset_records"] = [{"Columns": [], "Data": []}]
    server = _server(_settings(kf_app="App9"), _resources(dataset=dataset))

    async with Client(server) as client:
        await client.call_tool(
            "forge_dataset_records", {"flow_id": "Flow_1", "op": "list"}
        )

    assert dataset.calls[0][1] == ("App9", "Flow_1")


@pytest.mark.asyncio
async def test_application_error_becomes_a_tool_error() -> None:
    dataset = FakeDatasetRepository()
    server = _server(_settings(), _resources(dataset=dataset))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_dataset_records", {"flow_id": "Flow_1", "op": "list"}
            )


@pytest.mark.asyncio
async def test_no_key_pair_fails_before_the_use_case_runs() -> None:
    dataset = FakeDatasetRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    server = _server(settings, _resources(dataset=dataset))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_dataset_records",
                {"flow_id": "Flow_1", "op": "list", "app_id": "App1"},
            )
    assert dataset.calls == []
