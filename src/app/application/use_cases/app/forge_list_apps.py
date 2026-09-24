"""app.application.use_cases.app.forge_list_apps — list every application this
credential can see.

Ported from `app.infrastructure.mcp.server.forge_list_apps` (the tool body
itself; there is no separate `client.py` helper for this one) (Stage D group 6,
app family).
"""

from __future__ import annotations

from app.application.exceptions import RepositoryError
from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_list_apps_request import (
    ForgeListAppsRequest,
)
from app.application.models.responses.app.forge_list_apps_response import (
    ForgeListAppsResponse,
)


class ForgeListApps:
    """Use case behind the `forge_list_apps` tool."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The application/app-role port.
        """
        self._app = app

    async def execute(self, request: ForgeListAppsRequest) -> ForgeListAppsResponse:
        """List every application this credential can see.

        Needs no app selected -- this is how a caller discovers which
        `app_id` to pass into every other app-scoped tool.

        Args:
            request: The validated (empty) request.

        Returns:
            Every application, as `{"_id": ..., "Name": ...}` records.

        Raises:
            ApplicationError: A `RepositoryError` from the port, propagated
                unchanged.
            RepositoryError: `list_applications` answered something other
                than a list (old: `server.py:1742-1745`'s
                `Err("http", f"list_applications returned an unexpected
                shape: {got!r}")`).
        """
        del request
        got = await self._app.list_applications()
        if not isinstance(got, list):
            raise RepositoryError(
                f"list_applications returned an unexpected shape: {got!r}"
            )
        apps = [{"_id": a.get("_id"), "Name": a.get("Name")} for a in got]
        return ForgeListAppsResponse(apps=apps, count=len(apps))
