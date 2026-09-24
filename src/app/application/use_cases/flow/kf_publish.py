"""Use case for `kf_publish`."""

from __future__ import annotations

from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.kf_publish_request import KfPublishRequest
from app.application.models.responses.flow.kf_publish_response import KfPublishResponse
from app.application.use_cases.flow._fields import require_app_id


class KfPublish:
    """Compile a flow's draft graph to its live version."""

    def __init__(self, flow_repo: FlowRepository) -> None:
        """Build the use case around its port.

        Args:
            flow_repo: The flow port.
        """
        self._flow = flow_repo

    async def execute(self, request: KfPublishRequest) -> KfPublishResponse:
        """Publish the requested flow.

        Args:
            request: The resolved arguments.

        Returns:
            The publish result, carrying the pre-publish snapshot version.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`).
        """
        require_app_id(request.app_id)
        draft = await self._flow.get_draft(
            request.app_id, request.flow_kind, request.flow_id
        )
        await self._flow.publish(request.app_id, request.flow_kind, request.flow_id)
        return KfPublishResponse(
            published=True, flow_id=request.flow_id, snapshot_version=draft.version
        )
