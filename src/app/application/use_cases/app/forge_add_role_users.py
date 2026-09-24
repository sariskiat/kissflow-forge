"""`ForgeAddRoleUsers` -- grant users and/or groups onto an AppRole.

Ports `app.infrastructure.kissflow.client.apply_add_role_users` (spec G11).
Carries the one guard on this surface that protects people rather than the
graph: a `groups` grant is refused unless `confirm_group_notification` is
`True` (see `app.application.use_cases.app._roles.add_role_users`).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_add_role_users_request import (
    ForgeAddRoleUsersRequest,
)
from app.application.models.responses.app.forge_add_role_users_response import (
    ForgeAddRoleUsersResponse,
)
from app.application.use_cases.app._app_id import require_app_id
from app.application.use_cases.app._roles import add_role_users, raise_if_incomplete


class ForgeAddRoleUsers:
    """Use case behind `forge_add_role_users`."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The app port.
        """
        self._app = app

    async def execute(
        self, request: ForgeAddRoleUsersRequest
    ) -> ForgeAddRoleUsersResponse:
        """Grant `request`'s users and/or groups onto `request.role_id`.

        Args:
            request: The validated request.

        Returns:
            The grant's response.

        Raises:
            ApplicationError: No candidate was given, a `groups` grant was
                not confirmed, or a group dict is malformed
                (`code=REFUSED`); a user or group did not verify on
                read-back (`code=VERIFY_FAILED`).
        """
        app_id = require_app_id(request.app_id)

        outcome = await add_role_users(
            self._app,
            app_id,
            request.role_id,
            request.user_query,
            request.user_ids,
            request.groups,
            request.confirm_group_notification,
            request.force_regrant_groups,
        )

        raise_if_incomplete(outcome, "forge_add_role_users")

        return ForgeAddRoleUsersResponse(
            role_id=outcome.role_id,
            added=list(outcome.added),
            already_present=list(outcome.already_present),
            not_found=list(outcome.not_found),
            user_count=outcome.user_count,
            groups_added=list(outcome.groups_added),
            groups_already_present=list(outcome.groups_already_present),
            groups_unverified=list(outcome.groups_unverified),
            groups_refused=list(outcome.groups_refused),
            group_count=outcome.group_count,
            groups_note=outcome.groups_note,
            snapshot_version=None,
        )
