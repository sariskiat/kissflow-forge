"""app.application.use_cases.page.forge_build_page — the `forge_build_page`
use case.

Ported from `app.infrastructure.kissflow.pages_live.apply_page_build` (the
raw `steps` primitive) and `.apply_build_page_op` (the governed `op`
executor). See `app.application.use_cases.page._build` for the pure
step-application and read-back-verification logic both entries share.
"""

from __future__ import annotations

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.interfaces.page import PageRepository
from app.application.models.requests.page.forge_build_page_request import (
    ForgeBuildPageRequest,
)
from app.application.models.responses.page.forge_build_page_response import (
    ForgeBuildPageResponse,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.application.use_cases.page import _build
from app.application.use_cases.page._app_id import require_app_id
from app.application.use_cases.page._build import PageBuildStep, PageOpState
from app.application.use_cases.page._write_fail import raise_if_write_failed
from app.domain.entities.page_draft import PageDraft


class ForgeBuildPage:
    """Build page content, through either of two entries: the governed `op`
    (creates-or-reuses the page by name) or the raw `steps` + `page_id`
    primitive.
    """

    def __init__(self, page: PageRepository) -> None:
        """Build the use case around its one port.

        Args:
            page: The app-page family port.
        """
        self._page = page

    async def execute(self, request: ForgeBuildPageRequest) -> ForgeBuildPageResponse:
        """Run one `forge_build_page` call, on whichever entry the request used.

        Args:
            request: The validated request DTO. Its own `model_validator`
                already guarantees exactly one of `op`/`steps`, and that
                `steps` carries a `page_id`.

        Returns:
            The output-invariant audit. Only returned when every requested
            item verified on read-back (and, on the `op` entry, nothing was
            refused).

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`);
                the offline build rejected the request; or one or more
                items did not verify on read-back (`code=VERIFY_FAILED`,
                with `page_id` and whatever already `applied`/`built`
                folded into the message -- the draft PUT may already have
                landed).
            RepositoryError: A port call failed, including a version
                conflict on the write (`code=CONFLICT`).
        """
        require_app_id(request.app_id)

        if request.op is not None:
            return await self._execute_op(request)
        return await self._execute_steps(request)

    def _order(self, app_id: str, page_id: str) -> WriteOrder[PageDraft]:
        return WriteOrder(
            get=lambda: self._page.get_page_draft(app_id, page_id),
            put=lambda new, version: self._page.put_page_draft(
                app_id, page_id, new, version
            ),
            version_of=lambda d: d.version,
            publish=lambda: self._page.publish_page(app_id, page_id),
        )

    async def _execute_steps(
        self, request: ForgeBuildPageRequest
    ) -> ForgeBuildPageResponse:
        # The DTO's own model_validator guarantees `page_id` is set here; the
        # check below is belt-and-braces type narrowing, not a live guard.
        page_id = request.page_id
        if page_id is None:
            raise ApplicationError("'steps' entry requires 'page_id'", code=REFUSED)

        order = self._order(request.app_id, page_id)
        draft = await order.snapshot()

        steps = [
            PageBuildStep(kind=s.kind, kwargs=s.kwargs or {})
            for s in (request.steps or [])
        ]
        try:
            new_page, applied, checks = _build.apply_build_steps(draft, steps)
        except ValueError as exc:
            raise ApplicationError(
                f"offline page build rejected step: {exc}", code=VERIFY_FAILED
            ) from exc

        await order.apply(new_page)
        read_back = await order.read_back()
        read_wire = read_back.to_wire()
        verified, missing = _build.evaluate_checks(read_wire, checks)

        published = False
        if request.publish and not missing:
            await order.publish()
            published = True

        # Review fix 1: the draft PUT already landed on the live page --
        # `page_id`/`applied` go into `collateral` so a retry never has to
        # guess and re-add every widget (pages_live.py:117-128,
        # pre-refactor, kept both fields in its own `isError: true` dict).
        raise_if_write_failed(
            published=published,
            collateral=[f"page_id={page_id}", f"applied={applied}"],
            missing=missing,
        )

        return ForgeBuildPageResponse(
            entry="steps",
            app_id=request.app_id,
            page_id=page_id,
            applied=applied,
            verified=verified,
            missing=missing,
            node_counts=read_back.page_summary()["counts"],
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )

    async def _execute_op(
        self, request: ForgeBuildPageRequest
    ) -> ForgeBuildPageResponse:
        op_args = request.op or {}
        name = op_args.get("name")
        if not name:
            raise ApplicationError("build_page op has no 'name'", code=VERIFY_FAILED)

        listed = await self._page.list_pages(request.app_id)
        page_id = _build.find_page_id(listed, name)
        page_created = False
        if page_id is None:
            page_id = await self._page.create_page(request.app_id, name)
            page_created = True

        order = self._order(request.app_id, page_id)
        draft = await order.snapshot()
        draft_wire = draft.to_wire()
        body = _build.find_body_container(draft_wire)
        if body is None:
            raise ApplicationError(
                f"page {page_id} has no Body container — not a page draft?",
                code=VERIFY_FAILED,
            )

        state = PageOpState(draft_wire, body)
        try:
            _build.populate_page_state(state, op_args)
        except ValueError as exc:
            raise ApplicationError(
                f"offline page build rejected the op: {exc}", code=VERIFY_FAILED
            ) from exc

        if state.built:
            await order.apply(state.page)
        read_back = await order.read_back()
        read_wire = read_back.to_wire()
        verified, missing = _build.evaluate_checks(read_wire, state.checks)

        published = False
        if request.publish and state.built and not missing and not state.refused:
            await order.publish()
            published = True

        # Review fix 1: the page may already be created, and its draft PUT
        # may already have landed -- `page_id`/`page_created`/`built` go
        # into `collateral` so a caller of a failing `op` never has to
        # guess whether it must run forge_create_page again
        # (pages_live.py:493-507, pre-refactor, kept all three in its own
        # `isError: true` dict).
        raise_if_write_failed(
            published=published,
            collateral=[
                f"page_id={page_id}",
                f"page_created={page_created}",
                f"built={list(state.built)}",
            ],
            missing=missing,
            refused=list(state.refused),
        )

        return ForgeBuildPageResponse(
            entry="op",
            app_id=request.app_id,
            page_id=page_id,
            page_name=name,
            page_created=page_created,
            built=list(state.built),
            skipped=list(state.skipped),
            refused=list(state.refused),
            verified=verified,
            missing=missing,
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
