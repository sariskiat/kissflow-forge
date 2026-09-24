"""The copilot-family tool module (the in-builder AI copilot).

`register(mcp)` wires every copilot-family tool onto the new, thin server
(spec G12). One work group -- there is no second group in this family to
keep merge-distance from.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from app.application.models.requests.copilot.forge_copilot_ask_request import (
    ForgeCopilotAskRequest,
)
from app.application.models.requests.copilot.forge_copilot_check_request import (
    ForgeCopilotCheckRequest,
)
from app.application.models.responses.copilot.forge_copilot_ask_response import (
    ForgeCopilotAskResponse,
)
from app.application.models.responses.copilot.forge_copilot_check_response import (
    ForgeCopilotCheckResponse,
)
from app.application.use_cases.copilot.forge_copilot_ask import ForgeCopilotAsk
from app.application.use_cases.copilot.forge_copilot_check import ForgeCopilotCheck
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every copilot-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_all(mcp)


def _register_all(mcp: FastMCP) -> None:
    """Copilot tools: copilot_ask, copilot_check.
    Filled by the copilot family writer (Stage D)."""

    @mcp.tool(title="Ask the app copilot", annotations=_shared.LIVE_REPLACE_ONCE)
    async def forge_copilot_ask(
        app_id: str,
        message: str,
        expect: list[str] | None = None,
        *,
        ctx: Context,
    ) -> ForgeCopilotAskResponse:
        """LIVE (dev only): send one message to the app's in-builder AI copilot thread and do ONE
        immediate read-back — deliberately NOT a long poll (an MCP call has a budget; a structural
        build lands ~70s later per the live capture, far past any single-call wait). Returns the
        `conversation_id` to pass into `forge_copilot_check` after a real delay.

        ⚠️ THE RULE, harder here than anywhere else: the reply text is NEVER proof anything landed —
        the thread can still show an OLD clarifying question as newest while the real graph already
        has the change (memory note "REPLY LAGS THE GRAPH", proven live 2026-08-12). `expect`
        (optional: the node kinds this ask should produce, e.g. `["Field"]`) is echoed back for the
        caller's own bookkeeping — verification happens in forge_copilot_check, against a real graph
        read-back, never here.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCopilotAskRequest(
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                message=message,
                expect=expect,
            ),
            build_use_case=lambda resources: ForgeCopilotAsk(resources.copilot),
        )

    @mcp.tool(title="Check copilot result", annotations=_shared.LIVE_READ)
    async def forge_copilot_check(
        app_id: str,
        conversation_id: str,
        baseline_inventory: dict[str, list[str]] | None = None,
        *,
        ctx: Context,
    ) -> ForgeCopilotCheckResponse:
        """LIVE, read-only (dev only): the REAL verdict for a prior forge_copilot_ask call — read the
        thread's reply (never trusted alone) AND diff the app's current flow inventory against
        `baseline_inventory` (pass the `results.flows` dict from a `forge_sweep(scope="flows")` call
        made BEFORE the ask).

        Copilot is APP-scoped, not flow-scoped, and has been observed silently building into a
        DIFFERENT flow than the one asked about (memory note "SCATTER CAVEAT", field sweeps
        #45-47) — `scatter` names every flow id that showed up since the baseline, across every kind,
        so a caller never mistakes "nothing in MY target flow" for "copilot did nothing at all".
        `landed_nodes` is a cheap top-level node-count per scattered flow, not a full semantic diff —
        follow up with kf_get_flow_schema/forge_compare_to_spec on a flagged flow id for that.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCopilotCheckRequest(
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                conversation_id=conversation_id,
                baseline_inventory=baseline_inventory,
            ),
            build_use_case=lambda resources: ForgeCopilotCheck(
                copilot=resources.copilot, flow=resources.flow
            ),
        )
