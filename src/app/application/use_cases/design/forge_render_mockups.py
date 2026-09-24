"""app.application.use_cases.design.forge_render_mockups -- render the combined
HTML mockup bundle.

Ported from `app.infrastructure.mcp.server.forge_render_mockups` (Stage D group 8).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.artifacts import ArtifactWriter
from app.application.models.requests.design.forge_render_mockups_request import (
    ForgeRenderMockupsRequest,
)
from app.application.models.responses.design.forge_render_mockups_response import (
    ForgeRenderMockupsResponse,
)
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.design._mockup import design_bundle_html


class ForgeRenderMockups:
    """Use case behind the `forge_render_mockups` tool."""

    def __init__(self, artifacts: ArtifactWriter) -> None:
        """Build the use case.

        Args:
            artifacts: Writes the rendered HTML bundle to disk.
        """
        self._artifacts = artifacts

    async def execute(
        self, request: ForgeRenderMockupsRequest
    ) -> ForgeRenderMockupsResponse:
        """Render the combined HTML mockup bundle and write it to disk.

        Args:
            request: The validated request.

        Returns:
            The rendered HTML, its path on disk, a short plain-text
            summary, and the spec's gaps.

        Raises:
            ApplicationError: The render itself failed (`code=VERIFY_FAILED`).
        """
        spec = request.spec
        try:
            html = design_bundle_html(spec)
        except (ValueError, TypeError) as exc:
            raise ApplicationError(
                f"failed to render mockups: {exc}", code=VERIFY_FAILED
            ) from exc
        path = await self._artifacts.write(
            app_name=spec.app_name,
            digest=content_digest(spec),
            out_dir=request.out_dir,
            filename="mockups.html",
            content=html,
        )
        summary = (
            f"{len(spec.stages.stages)} stage(s), "
            f"{len(spec.data_model.tables)} table(s), "
            f"{len(spec.master_data.lists)} reference list(s), "
            f"{len(spec.personas.views)} persona view(s)"
        )
        return ForgeRenderMockupsResponse(
            html=html,
            path=path,
            summary=summary,
            gaps=list(spec.gaps()),
            blocking_gaps=list(spec.blocking_gaps()),
        )
