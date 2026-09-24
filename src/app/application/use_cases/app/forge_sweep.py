"""app.application.use_cases.app.forge_sweep — full-inventory discovery sweep,
read-only.

Ported from `app.infrastructure.kissflow.client.run_sweep` (Stage D group 6,
app family). `run_sweep` lists; it never deletes anything -- CLAUDE.md's own
"every batch operation ends with an output-invariant audit" applies to its READ
buckets (`read`/`error`/`skipped`), not to tenant deletion.
"""

from __future__ import annotations

from typing import Any

from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.page import PageRepository
from app.application.models.requests.app.forge_sweep_request import ForgeSweepRequest
from app.application.models.responses.app.forge_sweep_response import (
    ForgeSweepResponse,
)
from app.application.use_cases.app._app_id import require_app_id
from app.application.use_cases.app._sweep import (
    SWEEP_FLOW_KINDS,
    SWEEP_SCOPES,
    read_bucket,
)


class ForgeSweep:
    """Use case behind the `forge_sweep` tool."""

    def __init__(
        self, app: AppRepository, flow: FlowRepository, page: PageRepository
    ) -> None:
        """Build the use case.

        Args:
            app: The application/app-role port (`"apps"`, `"roles"`).
            flow: The flow/process/form/case/list port (`"flows"`,
                `"lists"`).
            page: The app-page port (`"pages"`).
        """
        self._app = app
        self._flow = flow
        self._page = page

    async def execute(self, request: ForgeSweepRequest) -> ForgeSweepResponse:
        """Run one discovery sweep across the requested scope(s).

        `forge_sweep` is a verdict tool (rule 7, `brief_stage_d_common.md`):
        a sub-scope's own read failure lands in that bucket's `"error"`
        status, named by `results` and folded into `ok=False` -- it never
        raises, because the call itself worked.

        The old tool (`server.py:2039`) resolved its client through
        `_client(app_id)` with `require_app=True`, refusing with the "no app
        selected" message before any tenant call at all -- for every scope,
        not only the ones that are actually app-scoped. `require_app_id`
        restores that same chokepoint here, before this method makes its
        first port call, so an unresolved app id can never reach
        `list_flows`/`list_lists` with an empty `_application_id` (CLAUDE.md
        names both as whole-account leaks without it).

        Args:
            request: The validated request.

        Returns:
            The per-scope inventory. Every requested sub-scope lands in
            exactly one bucket: `"read"` (with its item count + inventory),
            `"error"` (never swallowed), or `"skipped"` (`"pages"` only,
            when no app id is available at all).

        Raises:
            ApplicationError: `request.app_id` resolved to nothing,
                `code=REFUSED`, raised before any port call.
        """
        effective_app = require_app_id(request.app_id)
        wanted = SWEEP_SCOPES if request.scope == "all" else (request.scope,)
        results: dict[str, Any] = {}
        any_error = False

        for s in wanted:
            if s == "apps":
                bucket = await read_bucket(self._app.list_applications)
            elif s == "flows":
                by_kind: dict[str, Any] = {}
                for kind in SWEEP_FLOW_KINDS:
                    by_kind[kind] = await read_bucket(
                        lambda kind=kind: self._flow.list_flows(effective_app, kind)
                    )
                any_error = any_error or any(
                    v["status"] == "error" for v in by_kind.values()
                )
                results[s] = by_kind
                continue
            elif s == "pages":
                if not effective_app:
                    bucket = {
                        "status": "skipped",
                        "count": 0,
                        "items": [],
                        "error": "no app_id given or configured — pages are app-scoped",
                    }
                else:
                    bucket = await read_bucket(
                        lambda: self._page.list_pages(effective_app)
                    )
            elif s == "roles":
                bucket = await read_bucket(
                    lambda: self._app.list_app_roles(effective_app)
                )
            else:  # "lists"
                # `list_lists`'s raw route sometimes answers `{"Data": [...]}`
                # rather than a bare list (client.run_sweep's own defensive
                # unwrap, carried forward unchanged) -- `list_lists` shares the
                # "flows"/"roles" scopes' query-scoped safety CLAUDE.md
                # documents (no path-segment app id to break), so unlike
                # "pages" this never needs a skip guard of its own.
                async def _lists() -> list[Any]:
                    got: Any = await self._flow.list_lists(effective_app)
                    rows = got.get("Data", got) if isinstance(got, dict) else got
                    return rows

                bucket = await read_bucket(_lists)
            any_error = any_error or bucket["status"] == "error"
            results[s] = bucket

        return ForgeSweepResponse(
            scope=request.scope,
            app_id=effective_app,
            results=results,
            ok=not any_error,
        )
