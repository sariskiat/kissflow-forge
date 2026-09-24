"""app.application.use_cases.intake.forge_update_spec -- merge Q&A answers
into a spec.

Ported from `app.infrastructure.mcp.server`'s `forge_update_spec` tool body
(Stage D group 8).
"""

from __future__ import annotations

from pydantic import ValidationError

from app.application.exceptions import REFUSED, ApplicationError
from app.application.models.requests.intake.app_spec import AppSpec
from app.application.models.requests.intake.forge_update_spec_request import (
    ForgeUpdateSpecRequest,
)
from app.application.models.responses.intake.forge_update_spec_response import (
    ForgeUpdateSpecResponse,
)
from app.application.use_cases.intake._decode import spec_or_blank


class ForgeUpdateSpec:
    """Use case behind the `forge_update_spec` tool. Offline, no ports."""

    async def execute(self, request: ForgeUpdateSpecRequest) -> ForgeUpdateSpecResponse:
        """Run one `forge_update_spec` call.

        `patch` REPLACES each named top-level dimension wholesale; a key
        omitted from `patch` keeps whatever the base spec already had. This
        is deliberately NOT a deep merge.

        Args:
            request: The validated request.

        Returns:
            The merged spec (with `approved` forced False) plus its
            remaining gap lists.

        Raises:
            ApplicationError: `patch` names `approved` (`code=REFUSED`) --
                that flag is the confirmation gate, not a spec dimension;
                or the merged result does not validate as an `AppSpec`
                (`code=REFUSED`).
        """
        base = spec_or_blank(request.spec)
        if "approved" in request.patch:
            raise ApplicationError(
                "'approved' may not be set via forge_update_spec — it is "
                "the confirmation gate, not a spec dimension; strip it "
                "from the patch and call forge_approve_spec to grant it",
                code=REFUSED,
            )
        merged_wire = {**base.model_dump(mode="json"), **request.patch}
        try:
            merged = AppSpec.model_validate(merged_wire)
        except ValidationError as exc:
            raise ApplicationError(f"invalid patch: {exc}", code=REFUSED) from exc
        # an update is, by definition, unapproved
        merged = merged.model_copy(update={"approved": False})
        return ForgeUpdateSpecResponse(
            spec=merged.model_dump(mode="json"),
            gaps=list(merged.gaps()),
            blocking_gaps=list(merged.blocking_gaps()),
        )
