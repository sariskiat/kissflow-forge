"""`ForgeListAppRoles` -- list the AppRoles scoped to an application.

Ports `KfClient.list_app_roles` as called by `server.py`'s
`forge_list_app_roles` (spec G11). Read-only: no `snapshot_version`.
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_list_app_roles_request import (
    ForgeListAppRolesRequest,
)
from app.application.models.responses.app.forge_list_app_roles_response import (
    ForgeListAppRolesResponse,
)
from app.application.use_cases.app._app_id import require_app_id


class ForgeListAppRoles:
    """Use case behind `forge_list_app_roles`."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The app port.
        """
        self._app = app

    async def execute(
        self, request: ForgeListAppRolesRequest
    ) -> ForgeListAppRolesResponse:
        """List the AppRoles scoped to `request.app_id`.

        Args:
            request: The validated request.

        Returns:
            Every scoped role's `{_id, Name}`, and the resolved scope.

        Raises:
            ApplicationError: `request.app_id` is empty, `code=REFUSED`.
        """
        app_id = require_app_id(request.app_id)

        got = await self._app.list_app_roles(app_id)
        roles = [{"_id": r.get("_id"), "Name": r.get("Name")} for r in got]

        return ForgeListAppRolesResponse(
            roles=roles,
            count=len(roles),
            app_id=app_id,
        )
