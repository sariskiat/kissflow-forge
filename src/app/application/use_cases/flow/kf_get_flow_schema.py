"""Use case for `kf_get_flow_schema`."""

from __future__ import annotations

from app.application.exceptions import ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.page import PageRepository
from app.application.models.requests.flow.kf_get_flow_schema_request import (
    KfGetFlowSchemaRequest,
)
from app.application.models.responses.flow.kf_get_flow_schema_response import (
    KfGetFlowSchemaResponse,
)
from app.application.use_cases.flow._fields import require_app_id


class KfGetFlowSchema:
    """Read a flow's (or a page's) draft graph, verbatim."""

    def __init__(self, flow_repo: FlowRepository, page_repo: PageRepository) -> None:
        """Build the use case around its two ports.

        Args:
            flow_repo: The flow port.
            page_repo: The page port.
        """
        self._flow = flow_repo
        self._page = page_repo

    async def execute(self, request: KfGetFlowSchemaRequest) -> KfGetFlowSchemaResponse:
        """Read the requested draft.

        Args:
            request: The resolved arguments.

        Returns:
            The draft graph, verbatim.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`), or
                `flow_kind="page"` and no `app_id` was explicitly given
                (`code="VERIFY_FAILED"`).
        """
        require_app_id(request.app_id)
        if request.flow_kind == "page":
            if not request.app_id_given:
                raise ApplicationError(
                    "app_id is required to read a page draft", code="VERIFY_FAILED"
                )
            page_draft = await self._page.get_page_draft(
                request.app_id, request.flow_id
            )
            return KfGetFlowSchemaResponse(page_draft.to_wire())

        flow_draft = await self._flow.get_draft(
            request.app_id, request.flow_kind, request.flow_id
        )
        return KfGetFlowSchemaResponse(flow_draft.to_wire())
