"""The meta-family tool module: `register` calls its one work group, `_register_all`.

Stage D group 9 fills it with the three offline meta tools. Each is driven through a
real `FastMCP` built with `_register_all` alone and a fake lifespan, called through an
in-process `fastmcp.Client`: argument mapping, `ApplicationError` -> `ToolError`, and
-- since none of the three calls Kissflow -- proof that each one runs with no key pair
at all, instead of the missing-pair refusal the Kissflow tools carry.
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

from app.application.exceptions import NOT_FOUND, ApplicationError
from app.application.interfaces.docs import DocsReader
from app.domain.value_objects.field_type import FieldType
from app.infrastructure.config.settings import Settings
from app.infrastructure.docs_reader import DocsReaderAdapter
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.tools import meta as meta_tools

_SOURCE = "skills/kissflow-forge-builder/SKILL.md"


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_the_work_group_without_error() -> None:
    mcp = FastMCP("test")
    meta_tools.register(mcp)
    assert set(await _tool_names(mcp)) == {
        "forge_playbook",
        "forge_capabilities",
        "kf_list_field_types",
    }


def test_the_work_group_is_independently_callable() -> None:
    mcp = FastMCP("test")
    meta_tools._register_all(mcp)


# =====================================================================================
# _register_all (Stage D group 9), driven through a real in-process MCP client.
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


_NO_KEY_PAIR = {"kf_dev_access_key_id": None, "kf_dev_access_key_secret": None}


def _lifespan(docs: DocsReader, settings: Settings) -> Any:
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
            docs=docs,
            artifacts=FakeArtifactWriter(),
        )
        yield {"resources": resources, "settings": settings}

    return _run


def _server(docs: DocsReader, settings: Settings | None = None) -> FastMCP:
    mcp = FastMCP("test", lifespan=_lifespan(docs, settings or _settings()))
    meta_tools._register_all(mcp)
    return mcp


# ---- forge_playbook ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_playbook_returns_the_response_without_is_error() -> None:
    """Ported from `tests/test_mcp_boundary.py`,
    `test_a_succeeding_tool_is_NOT_marked_an_error`: still a protocol success, and the
    payload no longer carries `isError` (spec G13)."""
    docs = FakeDocsReader()
    docs.results["playbook"] = [{"text": "# THE RULE\n", "source": _SOURCE}]

    async with Client(_server(docs)) as client:
        result = await client.call_tool("forge_playbook", {})

    assert result.is_error is False
    assert result.structured_content == {
        "text": "# THE RULE\n",
        "chars": 11,
        "source": _SOURCE,
    }
    assert docs.calls == [("playbook", (), {})]


@pytest.mark.asyncio
async def test_forge_playbook_not_found_becomes_a_tool_error() -> None:
    class _MissingPlaybook(FakeDocsReader):
        async def playbook(self) -> dict[str, str]:
            raise ApplicationError(
                f"vendored playbook not found at {_SOURCE}", code=NOT_FOUND
            )

    async with Client(_server(_MissingPlaybook())) as client:
        with pytest.raises(
            ToolError, match=f"^vendored playbook not found at {_SOURCE}$"
        ):
            await client.call_tool("forge_playbook", {})


@pytest.mark.asyncio
async def test_forge_playbook_runs_with_no_key_pair() -> None:
    """Offline: it never calls Kissflow, so a missing key pair does not stop it."""
    docs = FakeDocsReader()

    async with Client(_server(docs, _settings(**_NO_KEY_PAIR))) as client:
        result = await client.call_tool("forge_playbook", {})

    assert result.is_error is False
    assert docs.calls == [("playbook", (), {})]


# ---- forge_capabilities ------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_capabilities_maps_the_query_and_returns_entries() -> None:
    entry = {"id": "field.currency", "name": "Currency"}
    docs = FakeDocsReader()
    docs.results["capabilities"] = [{"docs": [entry], "errors": []}]

    async with Client(_server(docs)) as client:
        result = await client.call_tool("forge_capabilities", {"query": "currency"})

    assert result.is_error is False
    assert result.structured_content == {
        "query": "currency",
        "count": 1,
        "entries": [entry],
        "errors": [],
    }
    assert docs.calls == [("capabilities", (), {"query": "currency"})]


@pytest.mark.asyncio
async def test_forge_capabilities_defaults_to_the_full_index() -> None:
    docs = FakeDocsReader()

    async with Client(_server(docs)) as client:
        result = await client.call_tool("forge_capabilities", {})

    assert result.structured_content == {
        "query": "",
        "count": 0,
        "index": [],
        "errors": [],
    }
    assert docs.calls == [("capabilities", (), {"query": ""})]


@pytest.mark.asyncio
async def test_forge_capabilities_application_error_becomes_a_tool_error() -> None:
    class _FailingDocs(FakeDocsReader):
        async def capabilities(self, query: str = "") -> dict[str, Any]:
            raise ApplicationError("docs unavailable", code="REPOSITORY_ERROR")

    async with Client(_server(_FailingDocs())) as client:
        with pytest.raises(ToolError, match="^docs unavailable$"):
            await client.call_tool("forge_capabilities", {"query": "x"})


@pytest.mark.asyncio
async def test_forge_capabilities_runs_with_no_key_pair() -> None:
    docs = FakeDocsReader()

    async with Client(_server(docs, _settings(**_NO_KEY_PAIR))) as client:
        result = await client.call_tool("forge_capabilities", {"query": "x"})

    assert result.is_error is False
    assert docs.calls == [("capabilities", (), {"query": "x"})]


# ---- kf_list_field_types -----------------------------------------------------------


@pytest.mark.asyncio
async def test_kf_list_field_types_lists_the_engine_catalog() -> None:
    """Ported from `tests/test_mcp_boundary.py`,
    `test_kf_list_field_types_still_serves_the_engine_set_it_documents`: a bare list,
    no `isError` key, still the engine's own closed set."""
    async with Client(_server(FakeDocsReader())) as client:
        result = await client.call_tool("kf_list_field_types", {})

    assert result.is_error is False
    assert result.data == [t.value for t in FieldType]


@pytest.mark.asyncio
async def test_kf_list_field_types_runs_with_no_key_pair() -> None:
    """Offline: it calls no port and no Kissflow route, so a missing key pair does not
    stop it."""
    async with Client(_server(FakeDocsReader(), _settings(**_NO_KEY_PAIR))) as client:
        result = await client.call_tool("kf_list_field_types", {})

    assert result.is_error is False
    assert "Text" in result.data


# ---- all three tools, end to end over the real repo docs ----------------------------


@pytest.mark.asyncio
async def test_the_docs_tools_serve_the_repo_docs_through_the_real_adapter() -> None:
    """The lifespan's own `DocsReaderAdapter`, through the MCP protocol: the brain a
    remote client fetches at runtime, and a real capability doc with its shapes."""
    async with Client(_server(DocsReaderAdapter())) as client:
        playbook = await client.call_tool("forge_playbook", {})
        search = await client.call_tool(
            "forge_capabilities", {"query": "field.currency"}
        )
        types = await client.call_tool("kf_list_field_types", {})

    assert playbook.structured_content is not None
    assert "THE RULE" in playbook.structured_content["text"]
    assert playbook.structured_content["source"] == _SOURCE
    assert search.structured_content is not None
    ids = [e["id"] for e in search.structured_content["entries"]]
    assert "field.currency" in ids
    assert search.structured_content["errors"] == []
    assert types.data == [t.value for t in FieldType]
