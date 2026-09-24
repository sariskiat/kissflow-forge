"""The meta-family tool module (the builder playbook, capability docs, the engine's
own field-type catalog).

`register(mcp)` wires every meta-family tool onto the new, thin server (spec G12). One
work group (Stage D group 9) -- there is no second group in this family to keep
merge-distance from. `forge_sweep` (`tools/app.py`), `forge_doctor` (`tools/flow.py`),
`forge_compare_to_spec` (`tools/intake.py`) and `forge_copilot_check`
(`tools/copilot.py`) are not part of this group; other groups moved them off the old
`server.py` into their own families.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from app.application.models.requests.meta.forge_capabilities_request import (
    ForgeCapabilitiesRequest,
)
from app.application.models.requests.meta.forge_playbook_request import (
    ForgePlaybookRequest,
)
from app.application.models.requests.meta.kf_list_field_types_request import (
    KfListFieldTypesRequest,
)
from app.application.models.responses.meta.forge_capabilities_response import (
    ForgeCapabilitiesResponse,
)
from app.application.models.responses.meta.forge_playbook_response import (
    ForgePlaybookResponse,
)
from app.application.models.responses.meta.kf_list_field_types_response import (
    KfListFieldTypesResponse,
)
from app.application.use_cases.meta.forge_capabilities import ForgeCapabilities
from app.application.use_cases.meta.forge_playbook import ForgePlaybook
from app.application.use_cases.meta.kf_list_field_types import KfListFieldTypes
from app.domain.value_objects.kinds import PlaybookName
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every meta-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_all(mcp)


def _register_all(mcp: FastMCP) -> None:
    """Meta tools: forge_playbook, forge_capabilities, kf_list_field_types. All three
    are OFFLINE (no Kissflow tenant, no key pair) -- Stage D group 9."""

    @mcp.tool(title="Builder playbook", annotations=_shared.OFFLINE_PURE)
    async def forge_playbook(
        skill: Annotated[
            PlaybookName,
            Field(
                description=(
                    "Which vendored skill to return: 'builder' (default) = build "
                    "order; 'usage' = how to drive this MCP; 'design' = design an "
                    "app with a business owner."
                )
            ),
        ] = "builder",
        *,
        ctx: Context,
    ) -> ForgePlaybookResponse:
        """OFFLINE, read-only: return the full builder PLAYBOOK — the doctrine a fresh Claude needs to
        drive this engine correctly (THE RULE that a 200/publish proves nothing, the proven numbered
        build order, the intent->tool map, the refuse-loudly table, the copilot fallback). Call this
        FIRST when you have the forge_* tools but no local kissflow-forge-builder skill loaded — it is
        the brain that ships with the MCP so it travels even to a remote user with no local files. Deep
        wire shapes it references live in `forge_capabilities(<id>)`.

        `skill` selects one of three vendored skills: "builder" (default) = the build order above;
        "usage" = how to drive this MCP safely (session start, evidence, reading results, reporting);
        "design" = interview a business owner in plain words and turn the need into an approved spec.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgePlaybookRequest(skill=skill),
            build_use_case=lambda resources: ForgePlaybook(resources.docs),
            needs_kissflow=False,
        )

    @mcp.tool(title="Search capability docs", annotations=_shared.OFFLINE_PURE)
    async def forge_capabilities(
        query: str = "", *, ctx: Context
    ) -> ForgeCapabilitiesResponse:
        """OFFLINE, read-only: search the docs/capabilities/*.md capability docs + their linked
        shapes/*.json captures. Empty `query` returns the full index (`id`, `name`, `status`,
        `modules` per doc) — the cheapest way to see what is captured at all before building
        anything. A non-empty `query` matches (case-insensitive substring) against a doc's id, name,
        ui_path, status, or body text, and returns each match's full frontmatter + body + every
        linked shape's parsed JSON content inline, so a caller gets the real wire shape in the same
        call instead of a dangling file reference.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCapabilitiesRequest(query=query),
            build_use_case=lambda resources: ForgeCapabilities(resources.docs),
            needs_kissflow=False,
        )

    @mcp.tool(title="Engine field types", annotations=_shared.OFFLINE_PURE)
    async def kf_list_field_types(*, ctx: Context) -> KfListFieldTypesResponse:
        """List the field types THIS ENGINE can build — the set every `type` key in
        kf_plan_field_change / kf_apply_field_change / forge_apply_fields / forge_add_table is
        checked against, so a wrong type is refused offline instead of writing a broken field.

        NOT the platform's own catalog, which is considerably wider (Image, Rich text, Signature,
        Geolocation and the rest). These are the types whose wire shape is CAPTURED here; anything
        outside the list is refused at compile rather than guessed at (ADR-0004). To see what is
        known about the rest of the palette — including which types this engine deliberately
        refuses and why — call forge_capabilities.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: KfListFieldTypesRequest(),
            build_use_case=lambda resources: KfListFieldTypes(),
            needs_kissflow=False,
        )
