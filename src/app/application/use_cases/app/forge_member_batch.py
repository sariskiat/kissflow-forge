"""`ForgeMemberBatch` -- grant AppRole members on a flow, members-first.

Ports `app.infrastructure.kissflow.client.apply_member_batch` (spec G11).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.app.forge_member_batch_request import (
    ForgeMemberBatchRequest,
)
from app.application.models.responses.app.forge_member_batch_response import (
    ForgeMemberBatchResponse,
)
from app.application.use_cases.app._app_id import require_app_id
from app.application.use_cases.app._members import (
    MemberOutcome,
    apply_own_app_roles,
    discover_member_source,
    harvest_from_source,
    raise_if_incomplete,
)


class ForgeMemberBatch:
    """Use case behind `forge_member_batch`."""

    def __init__(self, flow: FlowRepository, app: AppRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow port (the grant itself, and member reads).
            app: The app port (the account-level AppRole fallback).
        """
        self._flow = flow
        self._app = app

    async def execute(
        self, request: ForgeMemberBatchRequest
    ) -> ForgeMemberBatchResponse:
        """Grant AppRole members on `request.target_flow_id`.

        Two sources, tried in order: an explicit or auto-discovered sibling
        flow to harvest members from, else the app's own AppRoles at the
        account level.

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

        source_flow_id = request.source_flow_id
        if source_flow_id is None:
            source_flow_id = await discover_member_source(
                self._flow, app_id, request.kind, request.target_flow_id
            )

        outcome: MemberOutcome
        if source_flow_id is None:
            outcome = await apply_own_app_roles(
                self._flow, self._app, app_id, request.target_flow_id, request.kind
            )
        else:
            outcome = await harvest_from_source(
                self._flow, app_id, request.target_flow_id, source_flow_id, request.kind
            )

        raise_if_incomplete(outcome, "forge_member_batch")

        return ForgeMemberBatchResponse(
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
