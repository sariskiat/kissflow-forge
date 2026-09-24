"""The design-family tool module: `register` calls its one work group (Stage D
group 8), which fills every design tool. Offline (no Kissflow credentials, no
network) -- driven through an in-process `fastmcp.Client`, proving argument
mapping and `ApplicationError` -> `ToolError` through the thin tool, not just
through `_shared.run_use_case` in isolation (already covered by
`tests/unit/infrastructure/mcp/tools/test__shared.py`). Rule 23: an offline tool
that calls no Kissflow API skips the missing-key-pair case.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
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

from app.application.models.requests.intake.app_spec import AppSpec, blank_spec
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.tools import design as design_tools

_GOLDEN_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "app_spec_golden"


def _golden(name: str) -> dict[str, Any]:
    return json.loads((_GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _full_wire() -> dict[str, Any]:
    spec = AppSpec.model_validate(_golden("full")).model_copy(
        update={"approved": False}
    )
    return spec.model_dump(mode="json")


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_the_work_group_without_error() -> None:
    mcp = FastMCP("test")
    design_tools.register(mcp)
    assert set(await _tool_names(mcp)) == {
        "forge_render_flow_diagram",
        "forge_render_schema_diagram",
        "forge_render_mockups",
    }


@pytest.mark.asyncio
async def test_the_work_group_is_independently_callable() -> None:
    mcp = FastMCP("test")
    design_tools._register_all(mcp)
    assert set(await _tool_names(mcp)) == {
        "forge_render_flow_diagram",
        "forge_render_schema_diagram",
        "forge_render_mockups",
    }


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "A1",
        "kf_app": None,
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": None,
        "kf_dev_access_key_secret": None,
        "http_timeout_seconds": 10.0,
    }
    base.update(overrides)
    return Settings(**base)


def _lifespan(settings: Settings) -> Any:
    @asynccontextmanager
    async def _run(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        resources = AppResources(
            flow=FakeFlowRepository(),
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


def _server(settings: Settings) -> FastMCP:
    mcp = FastMCP("test", lifespan=_lifespan(settings))
    design_tools._register_all(mcp)
    return mcp


@pytest.mark.asyncio
async def test_forge_render_flow_diagram_maps_arguments_and_returns_the_response(
    tmp_path: Path,
) -> None:
    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "forge_render_flow_diagram",
            {"spec": _full_wire(), "out_dir": str(tmp_path)},
        )

    assert "<mxGraphModel" in result.structured_content["xml"]
    assert result.structured_content["path"].startswith(str(tmp_path))
    assert result.structured_content["gaps"] == []
    assert set(result.structured_content) == {"xml", "path", "gaps", "blocking_gaps"}


@pytest.mark.asyncio
async def test_forge_render_schema_diagram_maps_arguments_and_returns_the_response(
    tmp_path: Path,
) -> None:
    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "forge_render_schema_diagram",
            {"spec": _full_wire(), "out_dir": str(tmp_path)},
        )

    assert "<mxGraphModel" in result.structured_content["xml"]
    assert result.structured_content["path"].startswith(str(tmp_path))
    assert set(result.structured_content) == {"xml", "path", "gaps", "blocking_gaps"}


@pytest.mark.asyncio
async def test_forge_render_mockups_maps_arguments_and_returns_the_response(
    tmp_path: Path,
) -> None:
    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "forge_render_mockups", {"spec": _full_wire(), "out_dir": str(tmp_path)}
        )

    assert "<!doctype html>" in result.structured_content["html"]
    assert "5 stage(s)" in result.structured_content["summary"]
    assert set(result.structured_content) == {
        "html",
        "path",
        "summary",
        "gaps",
        "blocking_gaps",
    }


@pytest.mark.asyncio
async def test_a_malformed_spec_raises_a_tool_error(tmp_path: Path) -> None:
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "forge_render_flow_diagram",
                {"spec": {"not": "a spec"}, "out_dir": str(tmp_path)},
            )


@pytest.mark.asyncio
async def test_forge_render_mockups_runs_with_no_key_pair_at_all(
    tmp_path: Path,
) -> None:
    """Offline: no Kissflow credentials needed, so an absent key pair never blocks
    this call (rule 23)."""
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    async with Client(_server(settings)) as client:
        result = await client.call_tool(
            "forge_render_mockups",
            {"spec": blank_spec().model_dump(mode="json"), "out_dir": str(tmp_path)},
        )
    assert len(result.structured_content["blocking_gaps"]) == 10
