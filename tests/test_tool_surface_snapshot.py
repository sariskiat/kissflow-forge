"""Snapshot of the MCP tool surface, frozen from `develop @ 9651283` (refactor spec, section 8,
gate 4: "the surface fixture equals the live surface"; HR3: 61 names, the same parameter
schemas, the same docstrings, unchanged through the refactor).

Regenerate the fixture with::

    uv run python tests/test_tool_surface_snapshot.py --write

Do that only when a change to the surface is intentional and reviewed -- see HR3 and D2. Before
writing, this file's own `__main__` block does not re-check `git diff 9651283 HEAD -- src`; the
writer confirmed that by hand before the first write (spec section 6, G0's TDD test) and it is
each future writer's job to confirm it again before a re-write.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tool_surface.json"
SOURCE_LABEL = "develop @ 9651283"
EXPECTED_TOOL_COUNT = 61  # spec section 15, independent of this file's own scan.


def _build_server() -> Any:
    """The FastMCP server this snapshot reads.

    G12 (Stage E) moved every tool off `server.py`'s own module-level `mcp` and into the
    nine family modules `create_server(lifespan)` registers -- this now builds that
    server with a fake lifespan (no real Kissflow adapter, no real network; a tool
    listing never calls one). Every other function in this file reaches the server only
    by calling this helper (directly, or through `_list_tools()`), never by importing
    `app.infrastructure.mcp.server` on their own.

    Returns:
        A `FastMCP` server instance with the full tool surface registered.
    """
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from fastmcp import FastMCP

    from app.infrastructure.mcp.server import create_server

    @asynccontextmanager
    async def _fake_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": None, "settings": None}

    return create_server(_fake_lifespan)


def _fixture_tool_names() -> list[str]:
    """Tool names read straight from the frozen fixture, for `@pytest.mark.parametrize`.

    A `parametrize` list is built at collection time, before any pytest fixture runs, so this
    reads `FIXTURE_PATH` directly rather than depending on the `fixture_data` fixture below.

    Used instead of a `dir()` scan of the live server module: once G12 moves every tool off
    `server.py`'s own namespace and into per-family modules, a `dir()`-based list goes empty, and
    an empty `parametrize` list makes pytest silently collect zero tests instead of failing --
    the fixture's own tool names stay non-empty regardless of where G12 puts the tool functions.

    Returns:
        The sorted tool names in `tests/fixtures/tool_surface.json`, or an empty list when that
        file does not exist yet (`test_fixture_holds_61_tools` below raises a clear assertion for
        that case as soon as any test in this module actually runs).
    """
    if not FIXTURE_PATH.is_file():
        return []
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return sorted(data.get("tools", {}))


def _list_tools() -> list[Any]:
    """The live tool listing, through FastMCP's in-memory client.

    Same technique as `tests/test_mcp_surface.py::_emitted`: no subprocess, no network.

    Returns:
        Every tool FastMCP's `list_tools()` reports for `_build_server()`.
    """
    from fastmcp import Client

    async def _run() -> list[Any]:
        async with Client(_build_server()) as client:
            return await client.list_tools()

    return asyncio.run(_run())


def _snapshot() -> dict[str, Any]:
    """The current live surface, shaped exactly like the fixture file.

    Returns:
        `{"source": ..., "tools": {name: {"docstring_sha256": ..., "parameters": ...}}}`.
    """
    tools: dict[str, Any] = {}
    for tool in _list_tools():
        description = tool.description or ""
        tools[tool.name] = {
            "docstring_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
            "parameters": tool.input_schema,
        }
    return {"source": SOURCE_LABEL, "tools": tools}


def _write_fixture() -> None:
    """Write the current live surface to `FIXTURE_PATH`: sorted keys, 2-space indent, trailing
    newline."""
    payload = _snapshot()
    FIXTURE_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, Any]:
    """The frozen `tests/fixtures/tool_surface.json`, or a clear assertion telling the reader how
    to create it."""
    assert FIXTURE_PATH.is_file(), (
        f"no fixture at {FIXTURE_PATH}. Run: "
        "uv run python tests/test_tool_surface_snapshot.py --write"
    )
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live_tools() -> dict[str, Any]:
    """name -> the real emitted MCP tool, built once per test module run."""
    return {t.name: t for t in _list_tools()}


def test_fixture_holds_61_tools(fixture_data: dict[str, Any]) -> None:
    """The fixture's tool count equals 61 (spec section 15, an independent number)."""
    assert len(fixture_data["tools"]) == EXPECTED_TOOL_COUNT


def test_fixture_tool_names_equal_the_live_surface(
    fixture_data: dict[str, Any], live_tools: dict[str, Any]
) -> None:
    """The fixture's tool names are exactly the live server's tool names, no more, no fewer."""
    assert set(fixture_data["tools"]) == set(live_tools)


@pytest.mark.parametrize("tool_name", _fixture_tool_names())
def test_tool_parameters_match_the_fixture(
    fixture_data: dict[str, Any], live_tools: dict[str, Any], tool_name: str
) -> None:
    """Each tool's live parameter JSON schema equals the schema frozen in the fixture."""
    assert tool_name in live_tools, f"{tool_name} is not registered on the live server"
    assert tool_name in fixture_data["tools"], (
        f"{tool_name} is missing from the fixture"
    )
    assert (
        live_tools[tool_name].input_schema
        == fixture_data["tools"][tool_name]["parameters"]
    )


@pytest.mark.parametrize("tool_name", _fixture_tool_names())
def test_tool_docstring_hash_matches_the_fixture(
    fixture_data: dict[str, Any], live_tools: dict[str, Any], tool_name: str
) -> None:
    """Each tool's live docstring hash equals the hash frozen in the fixture.

    The hash is over the description as the CLIENT sees it (FastMCP's own cleaned docstring),
    not the raw source text, so it stays stable when a later goal moves the same tool into a
    different function and the source indentation changes.
    """
    assert tool_name in live_tools, f"{tool_name} is not registered on the live server"
    assert tool_name in fixture_data["tools"], (
        f"{tool_name} is missing from the fixture"
    )
    live_description = live_tools[tool_name].description or ""
    digest = hashlib.sha256(live_description.encode("utf-8")).hexdigest()
    assert digest == fixture_data["tools"][tool_name]["docstring_sha256"]


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        _write_fixture()
        print(f"wrote {FIXTURE_PATH}")
    else:
        print(
            "usage: uv run python tests/test_tool_surface_snapshot.py --write",
            file=sys.stderr,
        )
        raise SystemExit(2)
