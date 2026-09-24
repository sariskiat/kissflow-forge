"""Direct (non-MCP) reads, plus the one MCP-client bridge, shared by the `live`-marked suites.

Mirrors the old tests/robot/ForgeKeywords.py "direct (non-MCP) reads" section — the same few facts
(`_current_step`, `_status`, the full item detail, live field/assignee ids) that forge_simulate_case's
own WalkReport never carries, because it echoes the PLANNED step names and never reads them back
(CLAUDE.md > THE RULE: an echo of the plan proves nothing about what actually landed).

Stage E switch: the pre-Stage-E version of this module called `app.infrastructure.mcp.server`'s
bare tool functions directly (module-level `mcp`, plain Python functions once imported) and built
`app.infrastructure.kissflow.client.KfClient`/`app.infrastructure.kissflow.dataplane.LiveDataPlane`
by hand. Both are gone: every tool now lives behind `create_server(lifespan)`, reached only through
`fastmcp.Client`. `build_server()` builds the real server against the real dev tenant (the same
shape `app.main` builds for a real run); `call_tool` is the one bridge from a plain sync test
function into that async client call. The five detail-read helpers below have no tool-surface
equivalent (no tool exposes a bare item-detail read) and still go straight at the `ItemService`
port's own httpx adapter, exactly as the old code went straight at `KfClient`/`LiveDataPlane`.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastmcp import Client, FastMCP

from app.infrastructure.config.settings import Settings, load_settings
from app.infrastructure.kissflow.item import KissflowItemService
from app.infrastructure.mcp.lifespan import app_lifespan
from app.infrastructure.mcp.server import create_server

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


def temporary_name(prefix: str) -> str:
    """Return a synthetic name that cannot collide with another live run."""
    return f"{prefix} {uuid.uuid4().hex}"


def create_temporary_app(server: FastMCP, prefix: str) -> tuple[str, str]:
    """Create an app through MCP and return its verified id and unique name."""
    name = temporary_name(prefix)
    result = call_tool(server, "forge_create_app", name=name)
    app_id = result.get("app_id") if isinstance(result, dict) else result.app_id
    if not isinstance(app_id, str) or not app_id:
        raise AssertionError(f"forge_create_app returned no app id: {result!r}")
    return app_id, name


def response_value(response: Any, name: str) -> Any:
    """Read a tool response field from either FastMCP response shape.

    FastMCP returns a plain dict when a response DTO has a custom serializer;
    ordinary response DTOs arrive as a typed root model. Live tests must handle
    both shapes because both are part of the in-process client contract.
    """
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name)


def load_env_file(path: str | pathlib.Path | None = None) -> None:
    """Parse `KEY=VALUE` lines from `.env` (repo root by default) into this process's `os.environ`.
    An already-set key is left untouched — same "already-exported wins" precedence as
    `set -a; . ./.env; set +a`.
    """
    env_path = pathlib.Path(path) if path else DEFAULT_ENV_FILE
    if not env_path.is_file():
        raise FileNotFoundError(f"no .env file at {env_path}")
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def build_server() -> FastMCP:
    """Build the real MCP server, wired to the real dev tenant.

    Wraps `app_lifespan` with the process `Settings` in an
    `asynccontextmanager`, the same shape `app.main.main` builds for a real
    run -- stdio mode (`settings.mcp_http` unset), so `caller_keys` reads
    the key pair straight off `Settings` rather than off request headers.

    Returns:
        A `FastMCP` instance with every family's tools registered, ready
        for an in-process `fastmcp.Client`.
    """
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> Any:
        async with app_lifespan(server, settings) as context:
            yield context

    return create_server(lifespan)


async def _call_tool_async(server: FastMCP, tool_name: str, **kwargs: Any) -> Any:
    async with Client(server) as client:
        result = await client.call_tool(tool_name, kwargs)
        return result.data


def call_tool(server: FastMCP, tool_name: str, **kwargs: Any) -> Any:
    """Call one tool on `server` in-process, synchronously.

    The one bridge from a plain sync `tests/test_live_*.py` test function
    into `fastmcp.Client`'s async call -- every test function keeps its own
    pre-Stage-E sync shape; this is the only place `asyncio.run` appears.
    A tool that raises `ApplicationError` surfaces here as a `ToolError`,
    same as any other MCP client would see.

    Args:
        server: A `FastMCP` instance built by `build_server()`.
        tool_name: The tool name.
        **kwargs: The tool's own arguments.

    Returns:
        `result.data` — the parsed response DTO (attribute access) for a
        `BaseModel` response, or a plain `dict` for a `RootModel[dict]`
        response (`kf_get_flow_schema`, `forge_set_visibility`).
    """
    return asyncio.run(_call_tool_async(server, tool_name, **kwargs))


def resolve_field_ids(
    server: FastMCP, flow_id: str, kind: str = "process", app_id: str | None = None
) -> dict[str, str]:
    """{field NAME: field ID} for every Field node on the flow's LIVE draft. forge_simulate_case's
    `values` payload must be keyed by field ID, never name (CLAUDE.md > Item data plane)."""
    kwargs: dict[str, Any] = {"flow_kind": kind, "flow_id": flow_id}
    if app_id is not None:
        kwargs["app_id"] = app_id
    draft = call_tool(server, "kf_get_flow_schema", **kwargs)
    return {
        node["Name"]: node_id
        for node_id, node in draft.items()
        if isinstance(node, dict) and node.get("Kind") == "Field" and node.get("Name")
    }


def resolve_assigned_role_ids(
    server: FastMCP, flow_id: str, kind: str = "process", app_id: str | None = None
) -> list[str]:
    """Live read-back of every step's real AppRole assignee (Resource nodes), in
    ProcessDef::Activity order — forge_build_workflow's own `assigned` is an echo of the input,
    never proof of what actually landed (CLAUDE.md > Members first)."""
    kwargs: dict[str, Any] = {"flow_kind": kind, "flow_id": flow_id}
    if app_id is not None:
        kwargs["app_id"] = app_id
    draft = call_tool(server, "kf_get_flow_schema", **kwargs)
    return [
        node["Value"]
        for node in draft.values()
        if isinstance(node, dict)
        and node.get("Kind") == "Resource"
        and node.get("ValueType") == "AppRole"
        and isinstance(node.get("Value"), str)
    ]


def _item_settings() -> Settings:
    settings = load_settings()
    if not settings.kf_dev_access_key_id or not settings.kf_dev_access_key_secret:
        raise RuntimeError(
            "KF_DEV_ACCESS_KEY_ID / KF_DEV_ACCESS_KEY_SECRET required for live tests"
        )
    return settings


async def _get_detail_async(flow_id: str, iid: str) -> dict[str, Any]:
    settings = _item_settings()
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds, follow_redirects=False
    ) as client:
        item = KissflowItemService(client, settings.base_url, settings)
        return await item.get_detail(flow_id, iid)


def get_item_status(flow_id: str, iid: str) -> str:
    """STRICT: raises if `_status` is missing — right for proving a real regression."""
    detail = asyncio.run(_get_detail_async(flow_id, iid))
    status = detail.get("_status")
    if not isinstance(status, str):
        raise TypeError(f"detail had no string _status field: {detail!r}")
    return status


def get_current_step(flow_id: str, iid: str) -> str:
    """STRICT: raises if `_current_step` is missing. Wrong choice for a case where the field is
    LEGITIMATELY absent — use get_item_detail for that (see the fail-open negative-control test)."""
    detail = asyncio.run(_get_detail_async(flow_id, iid))
    step = detail.get("_current_step")
    if not isinstance(step, str):
        raise TypeError(f"detail had no string _current_step field: {detail!r}")
    return step


def get_item_detail(flow_id: str, iid: str) -> dict[str, Any]:
    """General-purpose escape hatch: never raises on a missing key, unlike get_current_step/
    get_item_status. An item that skips a whole conditional Parallel has NO `_current_step` key at
    all (CLAUDE.md > Conditional routing's fail-open warning) — that's a legitimate value to
    observe, not a bug to hide behind a raise."""
    return asyncio.run(_get_detail_async(flow_id, iid))


async def _item_call_async(method: str, *args: Any) -> Any:
    settings = _item_settings()
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds, follow_redirects=False
    ) as client:
        item = KissflowItemService(client, settings.base_url, settings)
        return await getattr(item, method)(*args)


def create_item(flow_id: str) -> dict[str, Any]:
    """Create one item directly against the `ItemService` port.

    No tool exposes a bare item create -- `forge_simulate_case` composes
    this internally for its own declarative walk, but the template-app
    live suite needs fine-grained control (a probe item to discover the
    calling user, then a real item filled with dataset-record and computed
    field values `forge_simulate_case`'s plain `values` map cannot express).
    """
    return asyncio.run(_item_call_async("create_item", flow_id))


def put_fields_raw(flow_id: str, iid: str, values: dict[str, Any]) -> dict[str, Any]:
    """Fill an item's fields directly against the `ItemService` port. See `create_item`."""
    return asyncio.run(_item_call_async("put_fields", flow_id, iid, values))


def submit_item(flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
    """Submit one activity instance directly against the `ItemService` port. See `create_item`."""
    return asyncio.run(_item_call_async("submit", flow_id, iid, aiid))


def grant_calling_user_to_role(
    server: FastMCP, flow_id: str, role_id: str, app_id: str
) -> str:
    """Discover the caller from a probe item and grant that user to an AppRole.

    A newly created AppRole has no users. The item API assigns the caller to a
    probe item, which is the only stable caller identity available on this
    tenant. The application teardown removes the probe with the temporary app.
    """
    probe = create_item(flow_id)
    probe_id = probe.get("_id")
    if not isinstance(probe_id, str) or not probe_id:
        raise AssertionError(f"probe item returned no id: {probe!r}")
    detail = get_item_detail(flow_id, probe_id)
    assigned = detail.get("_current_assigned_to")
    caller = assigned[0] if isinstance(assigned, list) and assigned else None
    if not isinstance(caller, dict):
        raise AssertionError(
            f"could not discover the calling user from the item assignment: {detail}"
        )
    caller_id = caller.get("_id")
    if not isinstance(caller_id, str) or not caller_id:
        raise AssertionError(f"calling user assignment had no string _id: {detail}")

    granted = call_tool(
        server,
        "forge_add_role_users",
        role_id=role_id,
        user_ids=[caller],
        app_id=app_id,
    )
    added = response_value(granted, "added") or []
    already_present = response_value(granted, "already_present") or []
    if caller_id not in (*added, *already_present):
        raise AssertionError(
            f"caller {caller_id!r} was not confirmed on role {role_id!r}: {granted!r}"
        )
    return caller_id
