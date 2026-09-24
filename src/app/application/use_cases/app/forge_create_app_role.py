"""`ForgeCreateAppRole` -- create an AppRole scoped to an application.

Ports `KfClient.create_app_role` as called by `server.py`'s
`forge_create_app_role` (spec G11).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_create_app_role_request import (
    ForgeCreateAppRoleRequest,
)
from app.application.models.responses.app.forge_create_app_role_response import (
    ForgeCreateAppRoleResponse,
)
from app.application.use_cases.app._app_id import require_app_id


class ForgeCreateAppRole:
    """Use case behind `forge_create_app_role`."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The app port.
        """
        self._app = app

    async def execute(
        self, request: ForgeCreateAppRoleRequest
    ) -> ForgeCreateAppRoleResponse:
        """Create a new AppRole scoped to `request.app_id`.

        Args:
            request: The validated request.

        Returns:
            The new role's id and the scope it was created under.

        Raises:
            ApplicationError: `request.app_id` is empty, `code=REFUSED`.
        """
        app_id = require_app_id(request.app_id)

        # Snapshot before this write -- `create_app_role` has nothing of its
        # own to read back, so the roster it is about to join is the
        # snapshot.
        await self._app.list_app_roles(app_id)

        role_id = await self._app.create_app_role(request.name, app_id)

        return ForgeCreateAppRoleResponse(
            role_id=role_id,
            name=request.name,
            app_id=app_id,
            snapshot_version=None,
        )
