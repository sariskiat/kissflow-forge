"""Use case for `forge_publish`."""

from __future__ import annotations

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.page import PageRepository
from app.application.models.requests.flow.forge_publish_request import (
    ForgePublishRequest,
)
from app.application.models.responses.flow.forge_publish_response import (
    ForgePublishResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id


class ForgePublish:
    """Compile a draft (flow, page or application) to its live version."""

    def __init__(
        self,
        flow_repo: FlowRepository,
        page_repo: PageRepository,
        app_repo: AppRepository,
    ) -> None:
        """Build the use case around its three ports.

        Args:
            flow_repo: The flow port.
            page_repo: The page port.
            app_repo: The app port.
        """
        self._flow = flow_repo
        self._page = page_repo
        self._app = app_repo

    async def execute(self, request: ForgePublishRequest) -> ForgePublishResponse:
        """Publish the requested target.

        Args:
            request: The resolved arguments.

        Returns:
            The publish result, carrying the pre-publish snapshot version
            and, for a flow, its post-publish `Status`.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`);
                `kind="page"` with no `app_id` explicitly given
                (`code="VERIFY_FAILED"`); a flow whose status read-back
                failed or is not `"Live"` (`code="VERIFY_FAILED"`); or a
                port read or write failed (`RepositoryError`).
        """
        require_app_id(request.app_id)

        if request.kind == "page":
            if not request.app_id_given:
                raise ApplicationError(
                    "app_id is required to publish a page", code="VERIFY_FAILED"
                )
            page_draft = await self._page.get_page_draft(
                request.app_id, request.flow_id
            )
            await self._page.publish_page(request.app_id, request.flow_id)
            return ForgePublishResponse(
                kind=request.kind,
                id=request.flow_id,
                published=True,
                snapshot_version=page_draft.version,
            )

        if request.kind == "application":
            app_draft = await self._app.get_app_draft(request.flow_id)
            await self._app.publish_app(request.flow_id)
            return ForgePublishResponse(
                kind=request.kind,
                id=request.flow_id,
                published=True,
                snapshot_version=app_draft.version,
            )

        flow_draft = await self._flow.get_draft(
            request.app_id, request.kind, request.flow_id
        )
        await self._flow.publish(request.app_id, request.kind, request.flow_id)
        try:
            detail = await self._flow.get_flow_detail(
                request.app_id, request.kind, request.flow_id
            )
        except RepositoryError as exc:
            # the publish itself landed: say so, or a caller re-publishes blind
            # (the former tool's own "publish succeeded but ..." sentence).
            raise_if_write_failed(
                published=True,
                status_read_back_failed=(
                    f"publish succeeded but status read-back failed: {exc.message}",
                ),
            )
        status = detail.get("Status")
        if status != "Live":
            # lesson 7: a publish whose read-back status is not "Live" is a
            # failed write, never a success with a non-"Live" status (matching
            # the former dict shape's own `"isError": status != "Live"`).
            raise_if_write_failed(
                published=True,
                status=(f"{status!r} is not 'Live'",),
            )
        return ForgePublishResponse(
            kind=request.kind,
            id=request.flow_id,
            published=True,
            status=status,
            snapshot_version=flow_draft.version,
        )
