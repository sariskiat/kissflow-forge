"""`ForgeSetRolePreference` -- set an AppRole's own default page/navigation.

Ports `app.infrastructure.kissflow.client.apply_set_role_preference` (spec G11).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_set_role_preference_request import (
    ForgeSetRolePreferenceRequest,
)
from app.application.models.responses.app.forge_set_role_preference_response import (
    ForgeSetRolePreferenceResponse,
)
from app.application.use_cases.app._app_id import require_app_id
from app.application.use_cases.app._roles import (
    raise_if_unverified_preference,
    set_role_preference,
)


class ForgeSetRolePreference:
    """Use case behind `forge_set_role_preference`."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The app port.
        """
        self._app = app

    async def execute(
        self, request: ForgeSetRolePreferenceRequest
    ) -> ForgeSetRolePreferenceResponse:
        """Set `request.role_id`'s default page and/or navigation.

        Args:
            request: The validated request.

        Returns:
            The write's response.

        Raises:
            ApplicationError: `request.app_id` is empty, or neither
                `default_page` nor `default_navigation` was given
                (`code=REFUSED`); the write did not verify on read-back
                (`code=VERIFY_FAILED`).
        """
        app_id = require_app_id(request.app_id)

        outcome = await set_role_preference(
            self._app,
            app_id,
            request.role_id,
            request.default_page,
            request.default_navigation,
        )

        raise_if_unverified_preference(outcome, "forge_set_role_preference")

        return ForgeSetRolePreferenceResponse(
            role_id=outcome.role_id,
            default_page=outcome.default_page,
            default_navigation=outcome.default_navigation,
            verified=outcome.verified,
            snapshot_version=None,
        )
