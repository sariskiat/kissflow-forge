"""app.application.use_cases.page.forge_set_navigation — the
`forge_set_navigation` use case.

Ported from `app.infrastructure.kissflow.pages_live.apply_navigation`
(refactor spec, Stage D group `d7_page_data_item_copilot`). Wires a page into
the app's navigation via the APP port's own draft, which is the `Navigation`
entity (`app.application.interfaces.app.AppRepository.get_app_draft`) --
not the page port: Navigation lives under the application draft, a
different node-graph from any one page's own.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.app import AppRepository
from app.application.models.requests.page.forge_set_navigation_request import (
    ForgeSetNavigationRequest,
)
from app.application.models.responses.page.forge_set_navigation_response import (
    ForgeSetNavigationResponse,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.application.use_cases.page._app_id import require_app_id
from app.application.use_cases.page._navigation import menu_reachable, new_menu_ids
from app.application.use_cases.page._write_fail import raise_if_write_failed
from app.domain.entities.navigation import Navigation


class ForgeSetNavigation:
    """Wire a page into the app's navigation: Menu -> FieldMapping ->
    Property{Type:"Page"}.
    """

    def __init__(self, app: AppRepository) -> None:
        """Build the use case around its one port.

        Args:
            app: The application/app-role family port, whose own draft is
                the Navigation graph.
        """
        self._app = app

    async def execute(
        self, request: ForgeSetNavigationRequest
    ) -> ForgeSetNavigationResponse:
        """Add a Menu entry for `request.page_id`, optionally unify and sweep.

        Args:
            request: The validated `forge_set_navigation` request.

        Returns:
            The output-invariant audit. Only returned when the new Menu
            verified reachable from a Navigation on read-back.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`);
                the app draft has no Navigation node to attach a menu to,
                the offline build rejected the request, or the new Menu did
                not verify on read-back (`code=VERIFY_FAILED`, with
                `swept_orphans` folded into the message when `sweep=True`
                already dropped a Menu offline before the write).
            RepositoryError: A port call failed, including a version
                conflict on the write (`code=CONFLICT`).
        """
        require_app_id(request.app_id)

        order: WriteOrder[Navigation] = WriteOrder(
            get=lambda: self._app.get_app_draft(request.app_id),
            put=lambda new, version: self._app.put_app_draft(
                request.app_id, new, version
            ),
            version_of=lambda d: d.version,
            publish=lambda: self._app.publish_app(request.app_id),
        )
        snapshot = await order.snapshot()
        navs_before = snapshot.list_navigation()
        if not navs_before:
            raise ApplicationError(
                f"application {request.app_id!r} draft has no Navigation "
                "node to attach a menu to",
                code=VERIFY_FAILED,
            )
        nav_id = next(iter(navs_before))
        before_menu_ids = navs_before[nav_id]

        try:
            nav = snapshot.add_page_menu(
                nav_id=nav_id, page_id=request.page_id, label=request.label
            )
        except ValueError as exc:
            raise ApplicationError(
                f"offline navigation build rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        after_menu_ids = nav.list_navigation()[nav_id]
        added_ids = new_menu_ids(before_menu_ids, after_menu_ids)
        if len(added_ids) != 1:
            raise ApplicationError(
                f"expected exactly 1 new Menu id, got {len(added_ids)}: {added_ids}",
                code=VERIFY_FAILED,
            )
        menu_id = added_ids[0]

        swept: tuple[str, ...] = ()
        try:
            if request.unify:
                nav = nav.point_all_navs_at(menu_ids=list(after_menu_ids))
            if request.sweep:
                nav, dropped = nav.sweep_orphans()
                swept = tuple(dropped)
        except ValueError as exc:
            raise ApplicationError(
                f"offline navigation build rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        await order.apply(nav)
        read_back = await order.read_back()
        verified_id = (
            menu_id if menu_reachable(menu_id, read_back.list_navigation()) else None
        )

        published = False
        if request.publish and verified_id:
            await order.publish()
            published = True

        # Review fix 1: `sweep=True` already dropped every orphaned Menu
        # offline, before this write -- `swept_orphans` goes into
        # `collateral` so it is never lost on a failing call
        # (pages_live.py:370-379, pre-refactor, kept it in its own
        # `isError: true` dict).
        raise_if_write_failed(
            published=published,
            collateral=[f"swept_orphans={list(swept)}"],
            unverified=[] if verified_id is not None else [menu_id],
        )

        return ForgeSetNavigationResponse(
            app_id=request.app_id,
            menu_id=verified_id,
            unified_nav_ids=list(navs_before.keys()) if request.unify else [],
            swept_orphans=list(swept),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
