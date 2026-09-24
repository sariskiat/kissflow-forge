"""The page-family tool module (app pages, navigation).

`register(mcp)` wires every page-family tool onto the new, thin server
(spec G12). One work group -- there is no second group in this family to
keep merge-distance from.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from app.application.models.requests.page.forge_build_page_request import (
    ForgeBuildPageRequest,
)
from app.application.models.requests.page.forge_create_page_request import (
    ForgeCreatePageRequest,
)
from app.application.models.requests.page.forge_set_navigation_request import (
    ForgeSetNavigationRequest,
)
from app.application.models.responses.page.forge_build_page_response import (
    ForgeBuildPageResponse,
)
from app.application.models.responses.page.forge_create_page_response import (
    ForgeCreatePageResponse,
)
from app.application.models.responses.page.forge_set_navigation_response import (
    ForgeSetNavigationResponse,
)
from app.application.use_cases.page.forge_build_page import ForgeBuildPage
from app.application.use_cases.page.forge_create_page import ForgeCreatePage
from app.application.use_cases.page.forge_set_navigation import ForgeSetNavigation
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every page-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_all(mcp)


def _register_all(mcp: FastMCP) -> None:
    """Page tools: create page, build page, set navigation.
    Filled by the page family writer (Stage D)."""

    @mcp.tool(title="Create page", annotations=_shared.LIVE_ADD_ONCE)
    async def forge_create_page(
        app_id: str, name: str, publish: bool = False, *, ctx: Context
    ) -> ForgeCreatePageResponse:
        """LIVE (dev only): create a new app PAGE — a virgin 4-node page graph
        (Page/Container001/Style001) — and verify it via the page LIST route (never the create
        response alone, per CLAUDE.md Page CRUD). Follow with forge_build_page to add content and
        forge_set_navigation to make it reachable.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCreatePageRequest(
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                name=name,
                publish=publish,
            ),
            build_use_case=lambda resources: ForgeCreatePage(resources.page),
        )

    @mcp.tool(title="Build page content", annotations=_shared.LIVE_REPLACE_ONCE)
    async def forge_build_page(
        app_id: str,
        page_id: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        publish: bool = False,
        op: dict[str, Any] | None = None,
        *,
        ctx: Context,
    ) -> ForgeBuildPageResponse:
        """LIVE write (dev only). TWO entries, exactly one required:

        `op` — the GOVERNED path (#41, ADR-0005): pass a compiled `build_page` op's args verbatim
        (name/widgets/kpis/actions/popups/on_click/design from forge_plan_app). Creates-or-reuses the
        page by name, builds its beautiful-page `design` tree into the Body (nested styled containers
        wrapping the widgets — page.design.md), plus widgets, popups with their own widgets, one button
        per action, and the on-click EventMapping wiring (OpenPopup resolves the target popup id from
        this same run). Every sub-item lands in built/skipped/refused + read-back verified/missing — a
        KPI is skipped with its Known-Exclusion reason (#23), a dangling OpenPopup or malformed design
        is refused (D6), never a dead button or a silently-dropped design.

        `steps` + `page_id` — the raw primitive: each step is `{"kind": "container"|"widget"|
        "popup"|"event"|"style"|"bind"|"design", "kwargs": {...}}` passed straight to the matching
        app.domain.entities.page_draft builder. A widget whose binding is load-bearing (view/*, report/*, metrics,
        masterdetail, repeater) REQUIRES its full config — THE RULE: a placeholder binding publishes
        clean and renders broken, so it is rejected offline, before any write. `"bind"` repairs an
        ALREADY-BUILT widget's FieldMapping Values in place (`{"host": <container id or name>,
        "config": {<FieldMapping Name>: <value>, ...}}`) — the primitive for fixing a live widget that
        was added unbound (e.g. a `view/form` submit widget with no `flow_id` wired). `"design"`
        (`{"parent_id": <container id>, "design": {<DesignNode tree>}}`) builds a whole nested styled
        Container/Component tree from one design dict — the beautiful-page primitive (page.design.md).
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeBuildPageRequest(
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                page_id=page_id,
                steps=steps,
                publish=publish,
                op=op,
            ),
            build_use_case=lambda resources: ForgeBuildPage(resources.page),
        )

    @mcp.tool(title="Wire page into navigation", annotations=_shared.LIVE_REPLACE)
    async def forge_set_navigation(
        app_id: str,
        page_id: str,
        label: str,
        unify: bool = True,
        sweep: bool = False,
        publish: bool = False,
        *,
        ctx: Context,
    ) -> ForgeSetNavigationResponse:
        """LIVE write (dev only): wire a page into the app's navigation — Menu -> FieldMapping ->
        Property{Type:"Page"}. `unify=True` (default) points EVERY Navigation at the same Menu set
        ("same view for all roles", CLAUDE.md App pages — role -> Navigation binding lives OUTSIDE the
        app draft). `sweep=True` additionally drops any Menu no longer reachable from any Navigation.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeSetNavigationRequest(
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                page_id=page_id,
                label=label,
                unify=unify,
                sweep=sweep,
                publish=publish,
            ),
            build_use_case=lambda resources: ForgeSetNavigation(resources.app),
        )
