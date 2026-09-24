"""The design-family tool module (diagrams, mockups, the confirm-before-you-build gate).

`register(mcp)` wires every design-family tool onto the new, thin server
(spec G12). One work group -- there is no second group in this family to
keep merge-distance from. Offline: no Kissflow credentials, no network
(spec D5).
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from app.application.models.requests.design.forge_render_flow_diagram_request import (
    ForgeRenderFlowDiagramRequest,
)
from app.application.models.requests.design.forge_render_mockups_request import (
    ForgeRenderMockupsRequest,
)
from app.application.models.requests.design.forge_render_schema_diagram_request import (
    ForgeRenderSchemaDiagramRequest,
)
from app.application.models.responses.design.forge_render_flow_diagram_response import (
    ForgeRenderFlowDiagramResponse,
)
from app.application.models.responses.design.forge_render_mockups_response import (
    ForgeRenderMockupsResponse,
)
from app.application.models.responses.design.forge_render_schema_diagram_response import (  # noqa: E501
    ForgeRenderSchemaDiagramResponse,
)
from app.application.use_cases.design.forge_render_flow_diagram import (
    ForgeRenderFlowDiagram,
)
from app.application.use_cases.design.forge_render_mockups import ForgeRenderMockups
from app.application.use_cases.design.forge_render_schema_diagram import (
    ForgeRenderSchemaDiagram,
)
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every design-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_all(mcp)


def _register_all(mcp: FastMCP) -> None:
    """Design tools: render_flow_diagram, render_schema_diagram, render_mockups."""

    @mcp.tool(title="Render flow diagram", annotations=_shared.OFFLINE_ARTIFACT)
    async def forge_render_flow_diagram(
        spec: dict[str, Any], out_dir: str | None = None, *, ctx: Context
    ) -> ForgeRenderFlowDiagramResponse:
        """OFFLINE: render the flow-shape draw.io diagram (app.application.design.flow_diagram_xml) — stage
        boxes down the spine, decision diamonds, dashed rework-loop back-edges, an unreachable stage
        flagged rather than silently drawn as fine. Written to
        `<out_dir>/<app_name>_<digest>/flow_diagram.drawio` (out_dir defaults to a namespaced folder
        under the system temp dir — see _artifact_dir) and returned inline too, so a caller can hand
        either the text or the path to a human. This tool never refuses on an incomplete spec — it
        renders whatever is there — but ALWAYS echoes `gaps`/`blocking_gaps` alongside the diagram, so
        a caller cannot hand a human a design artifact for a spec that still has gaps without also
        knowing it does.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeRenderFlowDiagramRequest(
                spec=spec, out_dir=out_dir
            ),
            build_use_case=lambda resources: ForgeRenderFlowDiagram(
                resources.artifacts
            ),
            needs_kissflow=False,
        )

    @mcp.tool(title="Render schema diagram", annotations=_shared.OFFLINE_ARTIFACT)
    async def forge_render_schema_diagram(
        spec: dict[str, Any], out_dir: str | None = None, *, ctx: Context
    ) -> ForgeRenderSchemaDiagramResponse:
        """OFFLINE: render the data-shape draw.io diagram (app.application.design.schema_diagram_xml) — fields
        grouped by stage, tables with their columns/row cap, reference lists with their REAL values.
        Same file-writing contract as forge_render_flow_diagram (see its docstring); file named
        schema_diagram.drawio. Same gaps/blocking_gaps echo too — see forge_render_flow_diagram.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeRenderSchemaDiagramRequest(
                spec=spec, out_dir=out_dir
            ),
            build_use_case=lambda resources: ForgeRenderSchemaDiagram(
                resources.artifacts
            ),
            needs_kissflow=False,
        )

    @mcp.tool(title="Render HTML mockups", annotations=_shared.OFFLINE_ARTIFACT)
    async def forge_render_mockups(
        spec: dict[str, Any], out_dir: str | None = None, *, ctx: Context
    ) -> ForgeRenderMockupsResponse:
        """OFFLINE: render the combined HTML mockup bundle (app.application.design.design_bundle_html) —
        per-stage form cards with FAITHFUL field rendering (a Hidden/ReadOnly/computed field never
        renders as a plain live input — CLAUDE.md THE RULE), tables, reference lists, a plain-language
        process summary, and both diagrams inline as collapsible draw.io XML. Written to
        `<out_dir>/<app_name>_<digest>/mockups.html`, same directory-naming contract as the diagram
        tools (see forge_render_flow_diagram). Also returns a short plain-text `summary` (stage/table/
        reference-list/persona-view counts) alongside the full HTML — an agent driving this tool
        cannot itself read rendered HTML, so `summary` and `path` are what it can actually act on; a
        human opens `path` for the real mockup. Same gaps/blocking_gaps echo as the diagram tools.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeRenderMockupsRequest(spec=spec, out_dir=out_dir),
            build_use_case=lambda resources: ForgeRenderMockups(resources.artifacts),
            needs_kissflow=False,
        )
