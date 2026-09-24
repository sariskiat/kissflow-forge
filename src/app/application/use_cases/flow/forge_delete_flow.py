"""Use case for `forge_delete_flow`."""

from __future__ import annotations

from app.application.exceptions import ApplicationError
from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.page import PageRepository
from app.application.models.requests.flow.forge_delete_flow_request import (
    ForgeDeleteFlowRequest,
)
from app.application.models.responses.flow.forge_delete_flow_response import (
    ForgeDeleteFlowResponse,
)
from app.application.use_cases.flow._delete import delete_anything
from app.application.use_cases.flow._fields import require_app_id


class ForgeDeleteFlow:
    """Archive+delete a flow, a page, or an application, verified via the
    appropriate list route."""

    def __init__(
        self,
        flow_repo: FlowRepository,
        app_repo: AppRepository,
        page_repo: PageRepository,
    ) -> None:
        """Build the use case around its three ports.

        Args:
            flow_repo: The flow port.
            app_repo: The app port.
            page_repo: The page port.
        """
        self._flow = flow_repo
        self._app = app_repo
        self._page = page_repo

    async def execute(self, request: ForgeDeleteFlowRequest) -> ForgeDeleteFlowResponse:
        """Delete the requested target.

        Args:
            request: The resolved arguments.

        Returns:
            Whether the delete landed, confirmed by a fresh list read.

        Raises:
            ApplicationError: No app is resolvable for a non-application
                kind (`code="REFUSED"`), or `kind="page"` with no `app_id`
                explicitly given (`code="VERIFY_FAILED"`).
        """
        if request.kind != "application":
            require_app_id(request.app_id)
        if request.kind == "page" and not request.app_id_given:
            raise ApplicationError(
                "app_id is required to delete a page", code="VERIFY_FAILED"
            )
        result = await delete_anything(
            self._flow,
            self._app,
            self._page,
            kind=request.kind,
            flow_id=request.flow_id,
            app_id=request.app_id,
        )
        return ForgeDeleteFlowResponse(
            kind=result.kind,
            id=result.id,
            deleted=result.deleted,
            verified=result.verified,
            snapshot_version=None,
        )
