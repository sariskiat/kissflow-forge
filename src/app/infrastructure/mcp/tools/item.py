"""The item-family tool module (the runtime item data plane).

`register(mcp)` wires every item-family tool onto the new, thin server
(spec G12). One work group -- there is no second group in this family to
keep merge-distance from.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from app.application.models.requests.item.forge_simulate_case_request import (
    ForgeSimulateCaseRequest,
)
from app.application.models.responses.item.forge_simulate_case_response import (
    ForgeSimulateCaseResponse,
)
from app.application.use_cases.item.forge_simulate_case import ForgeSimulateCase
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every item-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_all(mcp)


def _register_all(mcp: FastMCP) -> None:
    """Item tools: simulate_case (create, fill, submit, reject an item end to end).
    Filled by the item family writer (Stage D)."""

    @mcp.tool(title="Simulate one item", annotations=_shared.LIVE_ADD_ONCE)
    async def forge_simulate_case(
        flow_id: str,
        steps: list[dict[str, Any]],
        poll: bool = True,
        poll_tries: int = 8,
        poll_delay: float = 0.9,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeSimulateCaseResponse:
        """LIVE (dev only, KF_APP): walk one item through the documented `/process` data-plane API —
        create, then per step fill-and-verify (never trusts a PUT 200 alone — a discarded/mismatched
        value is caught by re-reading), then advance (submit) or reject. Each step is
        `{"name": str, "values": {...}, "reject": bool, "comment": str}`. Stops at the FIRST failure,
        including a fill that PUT 200 but did not verify — the exact silent-discard trap this data
        plane exists to catch (CLAUDE.md Item data plane).

        `values` KEYS accept a field NAME ("Business Unit ID") OR a field id ("Field_ed539546e3") —
        they are auto-resolved to ids against the flow's live draft before the fill, so a caller does
        not have to hand-resolve name->id first. Mixed names and ids in one step are fine. A name that
        matches no field fails that step loud, listing every available field name. Only the key is
        resolved — a Select `value` must still be the exact option literal. Resolution is scoped to the
        flow's root-model fields (a child-table field is addressed differently), documented in
        `app.infrastructure.kissflow.dataplane.field_name_index`.

        `poll` (default True — this tool is live-only, there is no fake/offline caller that would pay
        for it needlessly) waits for the step transition to actually show up (`dataplane.wait_new_aiid`)
        after each advance/reject, before moving to the next step — closing the gap that a fresh submit
        does not always show a rolled-over activity context on the very next read. `poll_tries`/
        `poll_delay` mirror the proven reference implementation's own timing (8 tries, 0.9s apart).
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeSimulateCaseRequest(
                flow_id=flow_id,
                steps=steps,
                poll=poll,
                poll_tries=poll_tries,
                poll_delay=poll_delay,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeSimulateCase(
                item=resources.item, flow=resources.flow
            ),
        )
