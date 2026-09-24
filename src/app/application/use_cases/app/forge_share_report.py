"""app.application.use_cases.app.forge_share_report — grant members on a flow
REPORT (CLAUDE.md Permissions: "flow REPORTS have the same member surface" as a
flow -- same member/batch body shape, `Role="Member"` ok).

Ported from `app.infrastructure.kissflow.client.apply_report_members` (Stage D
group 6, app family).
"""

from __future__ import annotations

from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.app.forge_share_report_request import (
    ForgeShareReportRequest,
)
from app.application.models.responses.app.forge_share_report_response import (
    ForgeShareReportResponse,
)
from app.application.use_cases.app._app_id import require_app_id

_REPORT_OWNER_KIND = "process"


class ForgeShareReport:
    """Use case behind the `forge_share_report` tool."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeShareReportRequest
    ) -> ForgeShareReportResponse:
        """Grant a batch of member permissions on one process flow's report.

        A report has no documented GET route of its own to read back
        against, unlike every other write in this engine -- the owning
        flow's own member roster is read FIRST, purely to satisfy the
        write-order invariant every write use case follows
        (`app.application.use_cases.flow._write_order`'s own module
        docstring); its value is otherwise unused, and the grant itself is
        honestly reported as `verified: None`, never a faked read-back
        audit.

        Args:
            request: The validated request.

        Returns:
            The grant's own (unverifiable) audit.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`). A
                `RepositoryError` from the port propagates unchanged.
        """
        require_app_id(request.app_id)
        await self._flow.get_members(
            request.app_id, _REPORT_OWNER_KIND, request.flow_id
        )
        posted = await self._flow.post_report_member_batch(
            request.app_id, request.flow_id, request.report_id, request.members
        )
        return ForgeShareReportResponse(
            flow_id=request.flow_id,
            report_id=request.report_id,
            requested=request.members,
            posted=posted,
            verified=None,
            note=(
                "no documented GET route for a report's own member list — not "
                "independently read-back verified, unlike every other apply_* "
                "in this module"
            ),
            snapshot_version=None,
        )
