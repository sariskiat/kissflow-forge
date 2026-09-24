"""Use case for `forge_create_list`."""

from __future__ import annotations

from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_create_list_request import (
    ForgeCreateListRequest,
)
from app.application.models.responses.flow.forge_create_list_response import (
    ForgeCreateListResponse,
)
from app.application.use_cases.flow._fields import require_app_id
from app.application.use_cases.flow._lifecycle import apply_word_list


class ForgeCreateList:
    """Create-or-reuse a word list by name and set its item values."""

    def __init__(self, flow_repo: FlowRepository) -> None:
        """Build the use case around its port.

        Args:
            flow_repo: The flow port.
        """
        self._flow = flow_repo

    async def execute(self, request: ForgeCreateListRequest) -> ForgeCreateListResponse:
        """Create-or-reuse the list and set its items.

        Args:
            request: The resolved arguments.

        Returns:
            The list-apply audit.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`), or
                the list could not be resolved to an id.
        """
        require_app_id(request.app_id)
        result = await apply_word_list(
            self._flow, app_id=request.app_id, name=request.name, items=request.values
        )
        return ForgeCreateListResponse(
            list_id=result.list_id,
            name=result.name,
            created=result.created,
            items=list(result.items),
            verified_items=list(result.verified_items),
            missing_items=list(result.missing_items),
            snapshot_version=None,
        )
