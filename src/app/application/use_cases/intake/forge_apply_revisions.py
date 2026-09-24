"""app.application.use_cases.intake.forge_apply_revisions -- apply a
customer's corrections to a spec.

Ported from `app.infrastructure.mcp.server`'s `forge_apply_revisions` tool
body (Stage D group 8).
"""

from __future__ import annotations

from app.application.exceptions import REFUSED, ApplicationError
from app.application.models.requests.intake.forge_apply_revisions_request import (
    ForgeApplyRevisionsRequest,
)
from app.application.models.responses.intake.forge_apply_revisions_response import (
    ForgeApplyRevisionsResponse,
)
from app.application.use_cases.design._confirm import apply_revisions, spec_digest
from app.application.use_cases.intake._compile import compile_spec


class ForgeApplyRevisions:
    """Use case behind the `forge_apply_revisions` tool. Offline, no ports."""

    async def execute(
        self, request: ForgeApplyRevisionsRequest
    ) -> ForgeApplyRevisionsResponse:
        """Run one `forge_apply_revisions` call.

        Also reports whether the revised spec still compiles, tested
        against a TEMPORARILY force-approved COPY purely to probe
        structural validity -- that probe never affects the returned
        spec's own (always-False) `approved` flag.

        Args:
            request: The validated request.

        Returns:
            The revised spec (with `approved` forced False), its new
            digest, and the compilability probe.

        Raises:
            ApplicationError: The revision failed to APPLY -- an unknown
                key, or a key naming something not in this spec
                (`code=REFUSED`). A revision that applies but fails to
                COMPILE is not an error; it is reported in the response.
        """
        try:
            revised = apply_revisions(request.spec, request.revisions)
        except ValueError as exc:
            raise ApplicationError(
                f"failed to apply revisions: {exc}", code=REFUSED
            ) from exc
        # a revision is, by definition, unapproved
        revised = revised.model_copy(update={"approved": False})
        try:
            compile_spec(revised.model_copy(update={"approved": True}))
            compiles, compile_error = True, None
        except ValueError as exc:
            compiles, compile_error = False, str(exc)
        return ForgeApplyRevisionsResponse(
            spec=revised.model_dump(mode="json"),
            digest=spec_digest(revised),
            compiles=compiles,
            compile_error=compile_error,
        )
