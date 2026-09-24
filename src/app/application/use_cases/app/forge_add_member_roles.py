"""`ForgeAddMemberRoles` -- create-then-grant AppRoles onto a flow.

Ports `app.infrastructure.kissflow.client.apply_member_roles` (spec G11).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.app.forge_add_member_roles_request import (
    ForgeAddMemberRolesRequest,
)
from app.application.models.responses.app.forge_add_member_roles_response import (
    ForgeAddMemberRolesResponse,
)
from app.application.use_cases.app._app_id import require_app_id
from app.application.use_cases.app._members import (
    create_then_grant_roles,
    raise_if_incomplete,
)


class ForgeAddMemberRoles:
    """Use case behind `forge_add_member_roles`."""

    def __init__(self, flow: FlowRepository, app: AppRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow port (the grant itself).
            app: The app port (role lookup and creation).
        """
        self._flow = flow
        self._app = app

    async def execute(
        self, request: ForgeAddMemberRolesRequest
    ) -> ForgeAddMemberRolesResponse:
        """Grant AppRoles onto `request.target_flow_id`, creating each by name
        first when it does not already exist scoped to the app.

        Args:
            request: The validated request.

        Returns:
            The grant's response.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`), or
                a granted role did not verify on read-back
                (`code=VERIFY_FAILED`).
        """
        app_id = require_app_id(request.app_id)

        outcome = await create_then_grant_roles(
            self._app,
            self._flow,
            app_id,
            request.target_flow_id,
            request.roles,
            request.kind,
        )

        raise_if_incomplete(outcome, "forge_add_member_roles")

        return ForgeAddMemberRolesResponse(
            target_flow_id=outcome.target_flow_id,
            source_flow_id=outcome.source_flow_id,
            harvested=list(outcome.harvested),
            applied=list(outcome.applied),
            verified=list(outcome.verified),
            missing=list(outcome.missing),
            note=outcome.note,
            role_ids=list(outcome.role_ids),
            resolved=dict(outcome.resolved),
            roles_seen=outcome.roles_seen,
            roles_granted=outcome.roles_granted,
            roles_unusable=list(outcome.roles_unusable),
            snapshot_version=None,
        )
