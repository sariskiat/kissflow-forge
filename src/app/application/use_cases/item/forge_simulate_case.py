"""app.application.use_cases.item.forge_simulate_case — the
`forge_simulate_case` use case.

Ported from `app.infrastructure.kissflow.dataplane.walk`, called the same
way the old `server.py` tool body did: resolve the flow's field-name index
through the FLOW port first (a read failure here is not fatal -- fall back
to no index, the old behaviour), then walk the item through the ITEM port.
"""

from __future__ import annotations

from app.application.exceptions import REFUSED, ApplicationError, RepositoryError
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.item import ItemService
from app.application.models.requests.item.forge_simulate_case_request import (
    ForgeSimulateCaseRequest,
)
from app.application.models.responses.item.forge_simulate_case_response import (
    ForgeSimulateCaseResponse,
)
from app.application.use_cases.item import _walk
from app.application.use_cases.item._write_fail import raise_if_write_failed

_NO_APP_SELECTED = (
    "no app selected — pass app_id (see forge_list_apps for valid ids), "
    "or set the KF_APP env var as a single-app default"
)


class ForgeSimulateCase:
    """Walk one item through the documented `/process` data-plane API:
    create, then per step fill-and-verify, then advance (submit) or reject.
    """

    def __init__(self, item: ItemService, flow: FlowRepository) -> None:
        """Build the use case around its two ports.

        Args:
            item: The item data-plane family port.
            flow: The flow/process/form/case/list family port, whose
                `get_draft` reads the flow's own draft for field-name
                resolution.
        """
        self._item = item
        self._flow = flow

    async def execute(
        self, request: ForgeSimulateCaseRequest
    ) -> ForgeSimulateCaseResponse:
        """Run one `forge_simulate_case` walk end to end.

        Args:
            request: The validated `forge_simulate_case` request.

        Returns:
            The output-invariant audit. Only returned when the walk created
            its item and never failed a step.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); or
                the walk stopped at a step (`code=VERIFY_FAILED`, naming the
                step and the cause, with the item's `iid` and its
                `filled`/`advanced`/`rejected` state folded into the message
                so a caller can still find what already landed).
        """
        if not request.app_id:
            raise ApplicationError(_NO_APP_SELECTED, code=REFUSED)

        # Resolve field NAMES -> ids from the flow's live draft, so a caller
        # may key `values` by either. A read failure here is not fatal: fall
        # back to no index (keys passed through verbatim, the old
        # behaviour) -- the flow's own draft is a helper for this call, not
        # its subject.
        index: dict[str, str] | None
        try:
            draft = await self._flow.get_draft(
                request.app_id, "process", request.flow_id
            )
            index = _walk.field_name_index(draft.to_wire())
        except RepositoryError:
            index = None

        plans = [
            _walk.StepPlan(
                name=s.name, values=s.values, reject=s.reject, comment=s.comment
            )
            for s in request.steps
        ]
        report = await _walk.walk(
            self._item,
            flow_id=request.flow_id,
            steps=plans,
            field_index=index,
            poll_after_transition=request.poll,
            poll_tries=request.poll_tries,
            poll_delay=request.poll_delay,
        )

        if not report.ok():
            # Rule 7 (brief_stage_d_common.md) and review fix 1: the item
            # may already be created, with steps already filled/advanced/
            # rejected before the one that stopped the walk -- that landed
            # state goes in `collateral` so it is never lost on this path
            # (server.py:1702-1713, pre-refactor, kept every one of these
            # fields in its own `isError: true` dict).
            raise_if_write_failed(
                published="n/a (item data-plane write, no publish step)",
                collateral=[
                    f"iid={report.iid}",
                    f"filled={list(report.filled)}",
                    f"advanced={list(report.advanced)}",
                    f"rejected={list(report.rejected)}",
                ],
                failed=(
                    [
                        *report.failed,
                        f"forge_simulate_case: {report.error}",
                    ]
                    if report.error
                    else list(report.failed)
                ),
            )

        return ForgeSimulateCaseResponse(
            flow_id=report.flow_id,
            iid=report.iid,
            created=report.created,
            planned=list(report.planned),
            filled=list(report.filled),
            advanced=list(report.advanced),
            rejected=list(report.rejected),
            failed=list(report.failed),
            error=report.error,
            snapshot_version=None,
        )
