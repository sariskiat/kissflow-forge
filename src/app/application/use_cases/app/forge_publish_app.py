"""app.application.use_cases.app.forge_publish_app — publish an APPLICATION's
draft to live, WITH a genuine post-publish read-back (THE RULE: a 200 from
publish proves nothing by itself).

Ported from `app.infrastructure.kissflow.client.publish_application_verified`
(Stage D group 6, app family).
"""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.models.requests.app.forge_publish_app_request import (
    ForgePublishAppRequest,
)
from app.application.models.responses.app.forge_publish_app_response import (
    ForgePublishAppResponse,
)
from app.application.use_cases.app._app_id import require_app_id
from app.application.use_cases.app._apps import publish_application_verified


class ForgePublishApp:
    """Use case behind the `forge_publish_app` tool."""

    def __init__(self, app: AppRepository) -> None:
        """Build the use case.

        Args:
            app: The application/app-role port.
        """
        self._app = app

    async def execute(self, request: ForgePublishAppRequest) -> ForgePublishAppResponse:
        """Publish an application's draft to live and read back the result.

        Args:
            request: The validated request.

        Returns:
            The post-publish read-back audit: the fresh `meta_version` plus
            any `Runtime_`-prefixed node id found on the app draft (⚠️
            UNCAPTURED on this tenant -- never guessed).

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                publish succeeded but the read-back failed
                (`code=VERIFY_FAILED`). A `RepositoryError` from the publish
                call itself propagates unchanged.
        """
        require_app_id(request.app_id)
        (
            runtime_id,
            meta_version,
            note,
            snapshot_version,
        ) = await publish_application_verified(self._app, request.app_id)
        return ForgePublishAppResponse(
            app_id=request.app_id,
            published=True,
            runtime_id=runtime_id,
            meta_version=meta_version,
            note=note,
            snapshot_version=snapshot_version,
        )
