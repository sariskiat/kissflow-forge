"""app.application.use_cases.design.forge_render_flow_diagram -- render the
flow-shape draw.io diagram.

Ported from `app.infrastructure.mcp.server.forge_render_flow_diagram` (Stage D
group 8).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.artifacts import ArtifactWriter
from app.application.models.requests.design.forge_render_flow_diagram_request import (
    ForgeRenderFlowDiagramRequest,
)
from app.application.models.responses.design.forge_render_flow_diagram_response import (
    ForgeRenderFlowDiagramResponse,
)
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.design._diagram import flow_diagram_xml


class ForgeRenderFlowDiagram:
    """Use case behind the `forge_render_flow_diagram` tool."""

    def __init__(self, artifacts: ArtifactWriter) -> None:
        """Build the use case.

        Args:
            artifacts: Writes the rendered diagram to disk.
        """
        self._artifacts = artifacts

    async def execute(
        self, request: ForgeRenderFlowDiagramRequest
    ) -> ForgeRenderFlowDiagramResponse:
        """Render the flow-shape draw.io diagram and write it to disk.

        Never refuses on an incomplete spec -- it renders whatever is
        there -- but always echoes `gaps`/`blocking_gaps` alongside the
        diagram, so a caller cannot hand a human a design artifact for a
        spec that still has gaps without also knowing it does.

        Args:
            request: The validated request.

        Returns:
            The rendered XML, its path on disk, and the spec's gaps.

        Raises:
            ApplicationError: The render itself failed (`code=VERIFY_FAILED`).
        """
        spec = request.spec
        try:
            xml = flow_diagram_xml(spec)
        except (ValueError, TypeError) as exc:
            raise ApplicationError(
                f"failed to render flow diagram: {exc}", code=VERIFY_FAILED
            ) from exc
        path = await self._artifacts.write(
            app_name=spec.app_name,
            digest=content_digest(spec),
            out_dir=request.out_dir,
            filename="flow_diagram.drawio",
            content=xml,
        )
        return ForgeRenderFlowDiagramResponse(
            xml=xml,
            path=path,
            gaps=list(spec.gaps()),
            blocking_gaps=list(spec.blocking_gaps()),
        )
