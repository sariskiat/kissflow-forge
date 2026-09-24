"""The page-family tool module: `register` calls its one work group.

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

from app.domain.entities.navigation import Navigation
from app.domain.entities.page_draft import PageDraft
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server
from app.infrastructure.mcp.tools import page as page_tools


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_the_work_group_without_error() -> None:
    mcp = FastMCP("test")
    page_tools.register(mcp)
    assert set(await _tool_names(mcp)) == {
        "forge_create_page",
        "forge_build_page",
        "forge_set_navigation",
    }


@pytest.mark.asyncio
async def test_the_work_group_is_independently_callable() -> None:
    mcp = FastMCP("test")
    page_tools._register_all(mcp)
    assert set(await _tool_names(mcp)) == {
        "forge_create_page",
        "forge_build_page",
        "forge_set_navigation",
    }


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
    page: FakePageRepository | None = None, app: FakeAppRepository | None = None
) -> AppResources:
    return AppResources(
        flow=FakeFlowRepository(),
        app=app or FakeAppRepository(),
        page=page or FakePageRepository(),
        dataset=FakeDatasetRepository(),
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
async def test_forge_create_page_maps_arguments_and_returns_the_response() -> None:
    page = FakePageRepository()
    page.results["create_page"] = ["Page_1"]
    page.results["list_pages"] = [[{"_id": "Page_1", "Name": "Sample Page"}]]
    server = _server(_settings(), _resources(page=page))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_create_page", {"app_id": "App1", "name": "Sample Page"}
        )

    assert result.data.page_id == "Page_1"
    assert result.data.verified is True
    assert page.calls[0][1] == ("App1", "Sample Page")
    # `pages_live.PageReport.as_tool_result()`'s own key set, minus
    # `isError`, plus `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "app_id",
        "page_id",
        "name",
        "verified",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_create_page_falls_back_to_settings_kf_app() -> None:
    page = FakePageRepository()
    page.results["create_page"] = ["Page_1"]
    page.results["list_pages"] = [[{"_id": "Page_1", "Name": "Sample Page"}]]
    server = _server(_settings(kf_app="App9"), _resources(page=page))

    async with Client(server) as client:
        await client.call_tool(
            "forge_create_page", {"app_id": "", "name": "Sample Page"}
        )

    assert page.calls[0][1] == ("App9", "Sample Page")


@pytest.mark.asyncio
async def test_forge_create_page_application_error_becomes_a_tool_error() -> None:
    page = FakePageRepository()
    page.results["create_page"] = ["Page_1"]
    page.results["list_pages"] = [[]]  # never verifies
    server = _server(_settings(), _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="did not verify"):
            await client.call_tool(
                "forge_create_page", {"app_id": "App1", "name": "Sample Page"}
            )


@pytest.mark.asyncio
async def test_forge_create_page_no_key_pair_fails_before_the_use_case_runs() -> None:
    page = FakePageRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    server = _server(settings, _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_create_page", {"app_id": "App1", "name": "Sample Page"}
            )
    assert page.calls == []


def _bare_page() -> PageDraft:
    return PageDraft.new("Sample Page")


class _StatefulFakePageRepository(FakePageRepository):
    """Real stateful get/put: `PageDraft.add_container` mints a RANDOM node
    id, so a test cannot precompute the "after" draft and queue it -- the id
    would never match what the use case itself mints."""

    def __init__(self, initial: PageDraft) -> None:
        super().__init__()
        self._stored = initial

    async def get_page_draft(self, app_id: str, page_id: str) -> PageDraft:
        self.calls.append(("get_page_draft", (app_id, page_id), {}))
        return self._stored

    async def put_page_draft(
        self, app_id: str, page_id: str, new: PageDraft, expect_version: str | None
    ) -> PageDraft:
        self.calls.append(
            (
                "put_page_draft",
                (app_id, page_id, new),
                {"expect_version": expect_version},
            )
        )
        self._stored = new
        return new


class _StatefulFakeAppRepository(FakeAppRepository):
    """Real stateful get/put: `Navigation.add_page_menu` mints a RANDOM Menu
    id, so a test cannot precompute the "after" draft and queue it."""

    def __init__(self, initial: Navigation) -> None:
        super().__init__()
        self._stored = initial

    async def get_app_draft(self, app_id: str) -> Navigation:
        self.calls.append(("get_app_draft", (app_id,), {}))
        return self._stored

    async def put_app_draft(
        self, app_id: str, new: Navigation, expect_version: str | None
    ) -> Navigation:
        self.calls.append(
            ("put_app_draft", (app_id, new), {"expect_version": expect_version})
        )
        self._stored = new
        return new


@pytest.mark.asyncio
async def test_forge_build_page_maps_arguments_and_returns_the_response() -> None:
    page = _StatefulFakePageRepository(_bare_page())
    server = _server(_settings(), _resources(page=page))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_build_page",
            {
                "app_id": "App1",
                "page_id": "Page_1",
                "steps": [
                    {
                        "kind": "container",
                        "kwargs": {"parent_id": "Container001", "name": "Banner"},
                    }
                ],
            },
        )

    assert result.structured_content["missing"] == []
    get_calls = [c for c in page.calls if c[0] == "get_page_draft"]
    assert get_calls[0][1] == ("App1", "Page_1")
    # `pages_live.PageBuildReport.as_tool_result()`'s own key set (the
    # `steps` entry), minus `isError`, plus `snapshot_version` (review fix
    # 5).
    assert set(result.structured_content) == {
        "app_id",
        "page_id",
        "applied",
        "verified",
        "missing",
        "node_counts",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_build_page_op_entry_maps_arguments_and_returns_the_response() -> (
    None
):
    page = _StatefulFakePageRepository(_bare_page())
    page.results["list_pages"] = [[]]
    page.results["create_page"] = ["Page_new"]
    server = _server(_settings(), _resources(page=page))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_build_page",
            {"app_id": "App1", "op": {"name": "Ops Home"}},
        )

    assert result.structured_content["page_id"] == "Page_new"
    assert result.structured_content["page_created"] is True
    # `pages_live.BuildPageOpReport.as_tool_result()`'s own key set (the
    # `op` entry), minus `isError`, plus `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "app_id",
        "page_id",
        "page_name",
        "page_created",
        "built",
        "skipped",
        "refused",
        "verified",
        "missing",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_build_page_neither_op_nor_steps_is_a_tool_error() -> None:
    page = FakePageRepository()
    server = _server(_settings(), _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="pass exactly one of 'op'"):
            await client.call_tool("forge_build_page", {"app_id": "App1"})
    assert page.calls == []


@pytest.mark.asyncio
async def test_forge_build_page_malformed_step_becomes_a_tool_error() -> None:
    """Review fix 3: the DTO's own shape-error text must still reach the
    caller through `ToolError`, the same as it did through the old
    `server.py`'s `coerce_page_steps` (`tests/test_mcp_boundary.py:630-639`,
    pre-refactor)."""
    page = FakePageRepository()
    server = _server(_settings(), _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError, match=r"steps\[0\]\['kind'\]"):
            await client.call_tool(
                "forge_build_page",
                {"app_id": "App1", "page_id": "P", "steps": [{"kwargs": {}}]},
            )
    assert page.calls == []


@pytest.mark.asyncio
async def test_forge_build_page_no_key_pair_fails_before_the_use_case_runs() -> None:
    page = FakePageRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    server = _server(settings, _resources(page=page))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_build_page", {"app_id": "App1", "op": {"name": "Ops Home"}}
            )
    assert page.calls == []


@pytest.mark.asyncio
async def test_forge_set_navigation_maps_arguments_and_returns_the_response() -> None:
    seed = {
        "Root": "Model_Sample01",
        "_meta_version": "v1",
        "Model_Sample01": {
            "Id": "Model_Sample01",
            "Kind": "Application",
            "Application::Navigation": ["Navigation_Sample01"],
        },
        "Navigation_Sample01": {
            "Id": "Navigation_Sample01",
            "Kind": "Navigation",
            "Navigation::Menu": [],
        },
    }
    app_repo = _StatefulFakeAppRepository(Navigation.from_wire(seed))
    server = _server(_settings(), _resources(app=app_repo))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_navigation",
            {"app_id": "App1", "page_id": "Page_New", "label": "Sample Tab"},
        )

    assert result.data.menu_id is not None
    get_calls = [c for c in app_repo.calls if c[0] == "get_app_draft"]
    assert get_calls[0][1] == ("App1",)
    # `pages_live.NavigationReport.as_tool_result()`'s own key set, minus
    # `isError`, plus `snapshot_version` (review fix 5).
    assert set(result.structured_content) == {
        "app_id",
        "menu_id",
        "unified_nav_ids",
        "swept_orphans",
        "meta_version",
        "published",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_set_navigation_application_error_becomes_a_tool_error() -> None:
    app_repo = FakeAppRepository()
    app_repo.results["get_app_draft"] = [
        Navigation.from_wire({"Root": "M1", "M1": {"Id": "M1", "Kind": "Application"}})
    ]
    server = _server(_settings(), _resources(app=app_repo))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Navigation node"):
            await client.call_tool(
                "forge_set_navigation",
                {"app_id": "App1", "page_id": "Page_New", "label": "Sample Tab"},
            )


@pytest.mark.asyncio
async def test_forge_set_navigation_no_key_pair_fails_before_the_use_case_runs() -> (
    None
):
    app_repo = FakeAppRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    server = _server(settings, _resources(app=app_repo))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
            await client.call_tool(
                "forge_set_navigation",
                {"app_id": "App1", "page_id": "Page_New", "label": "Sample Tab"},
            )
    assert app_repo.calls == []
