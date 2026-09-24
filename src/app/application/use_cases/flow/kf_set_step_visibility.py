"""app.application.use_cases.flow.kf_set_step_visibility — the
`kf_set_step_visibility` use case.

The older, simpler predecessor of `forge_set_visibility` (refactor spec,
Stage D group `d3_flow_workflow`): section-level only, always `kind="process"`,
no `field_owners`. Shares `app.application.use_cases.flow._permissions.
write_step_permissions` with `ForgeSetVisibility` -- the two tools always
shared the same underlying `apply_step_permissions` orchestration in the old
code too.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.kf_set_step_visibility_request import (
    KfSetStepVisibilityRequest,
)
from app.application.models.responses.flow.kf_set_step_visibility_response import (
    KfSetStepVisibilityResponse,
)
from app.application.use_cases.flow._fields import require_app_id
from app.application.use_cases.flow._permissions import write_step_permissions
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft, Matrix, progressive_matrix

_KIND = "process"


class KfSetStepVisibility:
    """Rebuild a process's per-step SECTION visibility (the section-only predecessor
    of `ForgeSetVisibility`)."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around the flow-family port.

        Args:
            flow: The `FlowRepository` adapter for this call's Kissflow tenant.
        """
        self._flow = flow

    async def execute(
        self, request: KfSetStepVisibilityRequest
    ) -> KfSetStepVisibilityResponse:
        """Run one `kf_set_step_visibility` call end to end.

        Args:
            request: The validated request DTO.

        Returns:
            The step-permission report (a free-form dict wrapped as a
            `RootModel`, see `KfSetStepVisibilityResponse`), with
            `snapshot_version` folded in. Only returned when every wanted
            pair verified on read-back.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); a
                section or step name in `owners` does not resolve, the
                offline rebuild was rejected, or a wanted pair did not
                verify on read-back (`code=VERIFY_FAILED`).
            RepositoryError: A port call failed, including a version
                conflict on the write (`code=CONFLICT`).
        """
        require_app_id(request.app_id)

        order: WriteOrder[FlowDraft] = WriteOrder(
            get=lambda: self._flow.get_draft(request.app_id, _KIND, request.flow_id),
            put=lambda new, version: self._flow.put_draft(
                request.app_id, _KIND, request.flow_id, new, version
            ),
            version_of=lambda d: d.version,
            publish=lambda: self._flow.publish(request.app_id, _KIND, request.flow_id),
        )
        draft = await order.snapshot()

        try:
            matrix: Matrix = progressive_matrix(draft, request.owners)
        except ValueError as exc:
            raise ApplicationError(str(exc), code=VERIFY_FAILED) from exc

        report = await write_step_permissions(
            order,
            draft,
            flow_id=request.flow_id,
            matrix=matrix,
            field_matrix=None,
            publish=request.publish,
            include_pairs=request.include_pairs,
        )
        report["snapshot_version"] = order.snapshot_version
        return KfSetStepVisibilityResponse(report)
