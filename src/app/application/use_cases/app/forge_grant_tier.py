"""`ForgeGrantTier` -- grant an AppRole a named permission tier on a flow.

Ports `app.infrastructure.kissflow.client.apply_grant_tier` (spec G11).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.app.forge_grant_tier_request import (
    ForgeGrantTierRequest,
)
from app.application.models.responses.app.forge_grant_tier_response import (
    ForgeGrantTierResponse,
)
from app.application.use_cases.app._app_id import require_app_id
from app.application.use_cases.app._roles import grant_tier, raise_if_unverified_tier


class ForgeGrantTier:
    """Use case behind `forge_grant_tier`."""

    def __init__(self, flow: FlowRepository, app: AppRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow port (the grant/removal itself).
            app: The app port (the role's own `Name`).
        """
        self._flow = flow
        self._app = app

    async def execute(self, request: ForgeGrantTierRequest) -> ForgeGrantTierResponse:
        """Grant `request.role_id` the tier `request.tier` on `request.flow_id`.

        Args:
            request: The validated request.

        Returns:
            The grant's response.

        Raises:
            ApplicationError: `request.app_id` is empty, or `request.tier`
                is not valid for `request.kind` (`code=REFUSED`); the grant
                did not verify on read-back (`code=VERIFY_FAILED`).
        """
        app_id = require_app_id(request.app_id)

        outcome = await grant_tier(
            self._flow,
            self._app,
            app_id,
            request.kind,
            request.flow_id,
            request.role_id,
            request.tier,
        )

        raise_if_unverified_tier(outcome, "forge_grant_tier")

        return ForgeGrantTierResponse(
            flow_id=outcome.flow_id,
            kind=outcome.kind,
            role_id=outcome.role_id,
            tier=outcome.tier,
            verified=outcome.verified,
            snapshot_version=None,
        )
