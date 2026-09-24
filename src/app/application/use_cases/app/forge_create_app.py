"""app.application.use_cases.app.forge_create_app — create a NEW application,
verified via the application list (never the create response alone).

Ported from `app.infrastructure.kissflow.client.create_application_verified`
(Stage D group 6, app family).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_create_app_request import (
    ForgeCreateAppRequest,
)
from app.application.models.responses.app.forge_create_app_response import (
    ForgeCreateAppResponse,
)
from app.application.use_cases.app._apps import create_application_verified


class ForgeCreateApp:
    """Use case behind the `forge_create_app` tool."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The application/app-role port.
        """
        self._app = app

    async def execute(self, request: ForgeCreateAppRequest) -> ForgeCreateAppResponse:
        """Create a new application and verify it landed.

        Account-level: needs no app selected -- this is how a caller makes
        their FIRST application.

        Args:
            request: The validated request.

        Returns:
            The verified-create audit.

        Raises:
            ApplicationError: The created id did not verify on the
                application-list read-back (`code=VERIFY_FAILED`). A
                `RepositoryError` from the port (for example the platform's
                own `FlowNameAlreadyExists`) propagates unchanged.
        """
        app_id = await create_application_verified(self._app, request.name)
        return ForgeCreateAppResponse(
            app_id=app_id,
            name=request.name,
            verified=True,
            supported=True,
            note=None,
            snapshot_version=None,
        )
