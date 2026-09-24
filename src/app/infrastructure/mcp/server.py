"""The MCP adapter: `create_server(lifespan)` builds the whole tool surface.

Write/publish are LIVE (Kissflow AUP §1.10, 2026-08-03) and DEV-ONLY by
construction (HR1): `app.infrastructure.config.settings.load_settings()`
reads `KF_DEV_DOMAIN` and refuses any domain without "dev-" before any tool
can run. Every write is read-verify-write with a post-write read-back audit.

This file is thin by design (spec G12): it owns the FastMCP instance, the
one broadcast `_INSTRUCTIONS` string every connecting client receives, and
the `_CoerceJsonStringArgs` client-compat middleware. Every tool's own body
lives in its family module under `app.infrastructure.mcp.tools`; each family
module's own `register(mcp)` attaches its tools to the instance this file
builds. No business rule, no Kissflow client, no orchestration logic lives
here.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

from app.infrastructure.mcp.tools import app as app_tools
from app.infrastructure.mcp.tools import copilot as copilot_tools
from app.infrastructure.mcp.tools import dataset as dataset_tools
from app.infrastructure.mcp.tools import design as design_tools
from app.infrastructure.mcp.tools import flow as flow_tools
from app.infrastructure.mcp.tools import intake as intake_tools
from app.infrastructure.mcp.tools import item as item_tools
from app.infrastructure.mcp.tools import meta as meta_tools
from app.infrastructure.mcp.tools import page as page_tools

# `instructions` reaches EVERY connecting client in the initialize handshake, before any tool is
# listed or called. It is the only channel on this surface that an agent cannot fail to receive:
# a tool description is read only when that tool is considered, `forge_playbook` only when someone
# thinks to fetch it, and CLAUDE.md never deploys at all. So the one rule whose cost lands on
# OTHER PEOPLE — the group broadcast — lives here, not only in the tool that enforces it.
# Deliberately short: this is a briefing, not the manual. The manual is `forge_playbook`.
_INSTRUCTIONS = """Kissflow Forge builds real Kissflow apps on a DEV tenant through an
undocumented builder API. Read this before your first tool call.

🚨 NEVER GRANT A GROUP TO TEST ANYTHING. Granting a group to an AppRole or to app membership
makes Kissflow notify EVERY MEMBER of that group — on a whole-tenant group ("everyone", "All
users", any org-wide group) that is every person in the account, from an automated agent. It
happened on this tenant on 2026-08-20 and everyone got pinged. It CANNOT BE UNDONE: membership
writes are add-only, and nine removal shapes were probed live with none of them working. The
blast radius is other people's attention, which you cannot un-spend.
  * To test membership, grant ONE NAMED DEVELOPER: forge_add_role_users(user_query="<their name>").
  * `groups` is refused unless you also pass confirm_group_notification=True — set that flag ONLY
    after a human has confirmed the actual recipient list, exactly as you would before sending
    mail. "Make it visible to everyone" is a request for VISIBILITY, not for BROADCAST.

THE RULE: an HTTP 200 and a clean publish prove NOTHING. The builder UI is a stricter validator
than the write API — a flow can accept every write, publish clean, and still render as an error
screen. Trust a read-back, never a status code. Run forge_doctor after every edit.

Call forge_playbook FIRST for the build order, the intent->tool map and the refuse-loudly table.
forge_playbook(skill="usage") covers how to drive this MCP; forge_playbook(skill="design") covers
designing an app with a business owner before any build.
Deep wire shapes are in forge_capabilities(<id>)."""


# Some MCP clients (observed live: Cowork) serialize nested object/array tool args as a JSON
# STRING instead of a native object, so Pydantic rejects them with `dict_type`/`list_type` before
# our code ever runs — a client-compat bug, not a schema bug (our schemas are correct `anyOf
# [object|null]`). This middleware json.loads a string arg back into structure when, and only when,
# that param's schema actually wants an object or array. Covers every tool, present and future.
def _wants_structured(schema: object) -> bool:
    if not isinstance(schema, dict):
        return False
    if schema.get("type") in ("object", "array"):
        return True
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, []):
            if _wants_structured(sub):
                return True
    return False


class _CoerceJsonStringArgs(Middleware):
    def __init__(self, server: FastMCP) -> None:
        self._server = (
            server  # explicit dep, not the module global — testable against a fake
        )

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, ToolResult],
    ) -> ToolResult:
        args = getattr(context.message, "arguments", None)
        if args:
            try:
                tool = await self._server.get_tool(context.message.name)
                props: dict[str, Any] = (
                    (tool.parameters or {}).get("properties", {}) if tool else {}
                )
            except Exception as e:  # noqa: BLE001 — degrade to no-coercion, but say so
                print(
                    f"[kfforge] arg-coerce: get_tool({context.message.name!r}) failed, "
                    f"skipping coercion: {e!r}",
                    file=sys.stderr,
                    flush=True,
                )
                props = {}
            for k, v in list(args.items()):
                if (
                    isinstance(v, str)
                    and v.strip()[:1] in ("{", "[")
                    and _wants_structured(props.get(k))
                ):
                    # a genuine string that merely looks like JSON is left alone
                    with contextlib.suppress(ValueError):
                        args[k] = json.loads(v)
        return await call_next(context)


LifespanFactory = Callable[
    [FastMCP], contextlib.AbstractAsyncContextManager[dict[str, Any]]
]


def create_server(lifespan: LifespanFactory) -> FastMCP:
    """Build the MCP server: the nine family tool modules, nothing else.

    Mirrors the clone's `create_server()` shape: `FastMCP(name,
    lifespan=lifespan, mask_error_details=True)`, built inside the function
    body (never at module level, per spec G6's `module_level_fastmcp` scan).
    Registers `_CoerceJsonStringArgs`, since some MCP clients still
    serialize a nested object/array argument as a JSON string regardless of
    which server answers them.

    Args:
        lifespan: `app_lifespan`, wrapped in an `asynccontextmanager` by
            `main.py`.

    Returns:
        A `FastMCP` instance with every family's tools registered.
    """
    new_mcp = FastMCP(
        "kissflow-forge",
        instructions=_INSTRUCTIONS,
        lifespan=lifespan,
        mask_error_details=True,
    )
    new_mcp.add_middleware(_CoerceJsonStringArgs(new_mcp))

    flow_tools.register(new_mcp)
    app_tools.register(new_mcp)
    page_tools.register(new_mcp)
    dataset_tools.register(new_mcp)
    item_tools.register(new_mcp)
    copilot_tools.register(new_mcp)
    intake_tools.register(new_mcp)
    design_tools.register(new_mcp)
    meta_tools.register(new_mcp)

    return new_mcp
