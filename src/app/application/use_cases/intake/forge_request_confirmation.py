"""app.application.use_cases.intake.forge_request_confirmation -- build the
ConfirmationRequest a human signs off on before anything may write to
Kissflow.

Ported from `app.infrastructure.mcp.server`'s `forge_request_confirmation`
tool body (Stage D group 8).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.artifacts import ArtifactWriter
from app.application.models.requests.intake.forge_request_confirmation_request import (  # noqa: E501
    ForgeRequestConfirmationRequest,
)
from app.application.models.responses.intake.forge_request_confirmation_response import (  # noqa: E501
    ForgeRequestConfirmationResponse,
)
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.design._confirm import request_confirmation


class ForgeRequestConfirmation:
    """Use case behind `forge_request_confirmation`."""

    def __init__(self, artifacts: ArtifactWriter) -> None:
        """Build the use case.

        Args:
            artifacts: Writes both diagrams and the mockup bundle to disk.
        """
        self._artifacts = artifacts

    async def execute(
        self, request: ForgeRequestConfirmationRequest
    ) -> ForgeRequestConfirmationResponse:
        """Build both draw.io diagrams and the HTML mockup bundle, write
        them to disk, and derive one confirm/revise question per risky
        choice the spec makes.

        Never refuses on an incomplete spec -- a customer may reasonably
        want to see a partial design mid-interview -- but always echoes
        `gaps`/`blocking_gaps`, so a human handed only the artifacts still
        knows whether they are looking at a complete design.

        Args:
            request: The validated request.

        Returns:
            The content digest, the written artifact paths, the confirm/
            revise questions, and the spec's gap lists.

        Raises:
            ApplicationError: Building the confirmation request failed
                (`code=VERIFY_FAILED`).
        """
        spec = request.spec
        try:
            confirmation = request_confirmation(spec)
        except (ValueError, TypeError) as exc:
            raise ApplicationError(
                f"failed to build confirmation request: {exc}",
                code=VERIFY_FAILED,
            ) from exc
        digest = content_digest(spec)
        paths = {
            name: await self._artifacts.write(
                app_name=spec.app_name,
                digest=digest,
                out_dir=request.out_dir,
                filename=name,
                content=content,
            )
            for name, content in confirmation.artifacts.items()
        }
        return ForgeRequestConfirmationResponse(
            # content_digest, NOT confirmation.spec_digest: request_confirmation
            # hashes the spec AS GIVEN, so confirming an already-approved spec
            # would mint a digest forge_approve_spec always rejects as "the spec
            # changed" when nothing changed -- both sides must normalize
            # `approved` identically.
            digest=content_digest(spec),
            artifact_paths=paths,
            questions=list(confirmation.questions),
            gaps=list(spec.gaps()),
            blocking_gaps=list(spec.blocking_gaps()),
        )
