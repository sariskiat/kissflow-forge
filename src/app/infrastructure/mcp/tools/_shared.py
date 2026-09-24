"""Shared pieces every thin tool module under `infrastructure/mcp/tools/` uses.

The seven `ToolAnnotations` profiles the old `server.py` used to define
locally (moved here so both the old tools, via an import, and the new ones
share one definition), and `run_use_case`, the one call every new thin tool
makes: read `Settings`/`AppResources` off the lifespan context, authenticate
before touching Kissflow, build the request DTO, run the use case, and
translate every failure into a `ToolError`. No tool module has any of that
logic inline (spec G12's "thin" rule) -- it all lives here, once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from app.application.exceptions import ApplicationError
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow.credentials import caller_keys
from app.infrastructure.mcp.lifespan import AppResources

# =====================================================================================
# Tool annotations (MCP `ToolAnnotations`). Seven profiles, derived from what each tool
# BODY actually does -- not from its description prefix, which was measured to be wrong:
# four tools announce themselves OFFLINE and then write files to disk.
#
# The rules, applied uniformly:
#   readOnlyHint    True only if the call writes NEITHER the tenant NOR the filesystem.
#   destructiveHint True if the call can REMOVE or OVERWRITE state that already
#                   exists, as opposed to only adding new state. A publish is
#                   deliberately NOT destructive: it compiles a draft the caller
#                   already authored into its live version -- it removes no node
#                   and replaces no draft state.
#   idempotentHint  True if calling twice with the same arguments leaves the same
#                   result -- which for a REPLACE-semantics tool (set_visibility,
#                   build_workflow, create_list) is still True, and for an
#                   ADD-semantics one that mints a new node every call (create_*,
#                   add_goto_gate, simulate_case) is False.
#   openWorldHint   True for anything that touches the Kissflow tenant.
# =====================================================================================

OFFLINE_PURE = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
# Offline, but genuinely writes files -- the render/confirm tools. Never
# destructive: each writes into a content-addressed folder of its own, so
# re-rendering the same spec rewrites the same bytes and two different
# specs cannot collide.
OFFLINE_ARTIFACT = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
LIVE_READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
LIVE_ADD = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
LIVE_ADD_ONCE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
LIVE_REPLACE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}
LIVE_REPLACE_ONCE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}


class _UseCase(Protocol):
    """The one shape `run_use_case` needs: `execute(request) -> response`."""

    async def execute(self, request: Any) -> Any: ...  # pragma: no cover


async def run_use_case(
    ctx: Context,
    *,
    build_request: Callable[[], Any],
    build_use_case: Callable[[AppResources], _UseCase],
    needs_kissflow: bool = True,
) -> Any:
    """Run one use case behind a thin tool: authenticate, build, execute, translate.

    Args:
        ctx: The tool's `Context`, carrying `ctx.lifespan_context["settings"]`
            and `["resources"]` (`app_lifespan`'s own two keys).
        build_request: Builds the request DTO from the tool's own arguments.
            Called after the key-pair check, so a malformed argument never
            masks a missing pair.
        build_use_case: Builds the use case from `AppResources`' ports.
        needs_kissflow: Whether this tool calls Kissflow at all. `True` for
            every family but `intake`/`design` (offline, no credentials).
            When `True`, `caller_keys(settings)` runs first, so a missing
            pair fails fast, before the request is even built.

    Returns:
        Whatever `use_case.execute(request)` returns.

    Raises:
        ToolError: No key pair is available for this call (when
            `needs_kissflow`); the built request failed Pydantic validation;
            or the use case raised an `ApplicationError`.
    """
    settings: Settings = ctx.lifespan_context["settings"]
    resources: AppResources = ctx.lifespan_context["resources"]

    if needs_kissflow:
        caller_keys(settings)

    try:
        request = build_request()
    except ValidationError as exc:
        raise ToolError(str(exc)) from exc

    use_case = build_use_case(resources)
    try:
        return await use_case.execute(request)
    except ApplicationError as exc:
        raise ToolError(exc.message) from exc
