"""`ForgeDeleteAppRole` -- delete an AppRole by id.

Ports `KfClient.delete_app_role` as called by `server.py`'s
`forge_delete_app_role` (spec G11).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_delete_app_role_request import (
    ForgeDeleteAppRoleRequest,
)
from app.application.models.responses.app.forge_delete_app_role_response import (
    ForgeDeleteAppRoleResponse,
)
from app.application.use_cases.app._app_id import require_app_id


class ForgeDeleteAppRole:
    """Use case behind `forge_delete_app_role`."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The app port.
        """
        self._app = app

    async def execute(
        self, request: ForgeDeleteAppRoleRequest
    ) -> ForgeDeleteAppRoleResponse:
        """Delete the AppRole `request.role_id`.

        Deletion itself is an account-level route, not app-scoped, but this
        tool has always refused when no app was resolvable (`_client()`'s
        blanket `require_app`), so the same refusal holds here. Verify the
        deletion via `forge_list_app_roles`, never this response alone (THE
        RULE: a write's own response proves nothing).

        Args:
            request: The validated request.

        Returns:
            The deleted role's id.

        Raises:
            ApplicationError: `request.app_id` is empty, `code=REFUSED`.
        """
        # Required to be resolvable (today's `_client()` refused every
        # app-scoped tool the same way), even though the delete route
        # itself carries no app id.
        require_app_id(request.app_id)

        # Snapshot before this write: confirm the role exists before deleting it.
        await self._app.get_app_role(request.role_id)

        await self._app.delete_app_role(request.role_id)

        return ForgeDeleteAppRoleResponse(
            role_id=request.role_id,
            deleted=True,
            snapshot_version=None,
        )
