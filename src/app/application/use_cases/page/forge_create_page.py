"""app.application.use_cases.page.forge_create_page — the `forge_create_page`
use case.

Ported from `app.infrastructure.kissflow.pages_live.create_page_flow`
(refactor spec, Stage D group `d7_page_data_item_copilot`): POST the page
shell -> verify it exists via `list_pages` (never the create response alone,
CLAUDE.md > Pages) -> optionally publish it.

CREATE exemption (review fix 2, `brief_stage_d_common.md` rule 6's write-order
invariant): the first port call here is `create_page`, a write, never a
prior read. This matches `create_page_flow`'s own pre-refactor order exactly
(`pages_live.py:61`: `client.create_page(...)` is its first call too, with
`list_pages` only after) -- there is no live page to snapshot before one
exists, so `assert_write_order` (which requires a read first) does not apply
to this one use case, by design, not by oversight.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.page import PageRepository
from app.application.models.requests.page.forge_create_page_request import (
    ForgeCreatePageRequest,
)
from app.application.models.responses.page.forge_create_page_response import (
    ForgeCreatePageResponse,
)
from app.application.use_cases.page._app_id import require_app_id


class ForgeCreatePage:
    """Create a new app page, verified via `list_pages`."""

    def __init__(self, page: PageRepository) -> None:
        """Build the use case around its one port.

        Args:
            page: The app-page family port.
        """
        self._page = page

    async def execute(self, request: ForgeCreatePageRequest) -> ForgeCreatePageResponse:
        """Create the page and verify it landed.

        Args:
            request: The validated `forge_create_page` request.

        Returns:
            The output-invariant audit. Only returned when the new page
            verified via `list_pages`.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); or
                the created page did not verify on `list_pages`
                (`code=VERIFY_FAILED`).
            RepositoryError: A port call failed.
        """
        app_id = require_app_id(request.app_id)

        page_id = await self._page.create_page(app_id, request.name)

        listed = await self._page.list_pages(app_id)
        verified = any(isinstance(p, dict) and p.get("_id") == page_id for p in listed)

        published = False
        if request.publish and verified:
            await self._page.publish_page(app_id, page_id)
            published = True

        if not verified:
            raise ApplicationError(
                f"forge_create_page {request.name!r}: the created page "
                f"(page_id={page_id!r}) did not verify via list_pages",
                code=VERIFY_FAILED,
            )

        return ForgeCreatePageResponse(
            app_id=app_id,
            page_id=page_id,
            name=request.name,
            verified=verified,
            published=published,
            snapshot_version=None,
        )
