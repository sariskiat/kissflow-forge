"""app.application.use_cases.flow.forge_set_visibility — the
`forge_set_visibility` use case.

Ported from `app.infrastructure.kissflow.client.apply_step_permissions`,
together with the offline matrix computation the old `forge_set_visibility`
tool did in `server.py` (refactor spec, Stage D group `d3_flow_workflow`).

The old tool and `apply_step_permissions` each did their own `get_draft`
(one to compute the matrix, a second as `apply_step_permissions`'s own
snapshot) against the same live draft. This use case takes exactly ONE
snapshot -- the `WriteOrder`'s -- and computes the matrix from it, which
is observably identical (nothing else can write to the draft between two
sequential reads in the old code either) and keeps the "first port call is
a read" invariant to a single read instead of two.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_set_visibility_request import (
    ForgeSetVisibilityRequest,
)
from app.application.models.responses.flow.forge_set_visibility_response import (
    ForgeSetVisibilityResponse,
)
from app.application.use_cases.flow._fields import require_app_id
from app.application.use_cases.flow._permissions import write_step_permissions
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import (
    FlowDraft,
    Matrix,
    field_override_matrix,
    progressive_matrix,
)


class ForgeSetVisibility:
    """Rebuild a process's per-step visibility, section-level and/or field-level."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around the flow-family port.

        Args:
            flow: The `FlowRepository` adapter for this call's Kissflow tenant.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeSetVisibilityRequest
    ) -> ForgeSetVisibilityResponse:
        """Run one `forge_set_visibility` call end to end.

        Args:
            request: The validated request DTO.

        Returns:
            The step-permission report (a free-form dict wrapped as a
            `RootModel`, see `ForgeSetVisibilityResponse`), with
            `snapshot_version` folded in. Only returned when every wanted
            pair verified on read-back.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); a
                section, field or step name in `owners`/`field_owners` does
                not resolve, the offline rebuild was rejected, or a wanted
                pair did not verify on read-back (`code=VERIFY_FAILED`).
            RepositoryError: A port call failed, including a version
                conflict on the write (`code=CONFLICT`).
        """
        require_app_id(request.app_id)

        order: WriteOrder[FlowDraft] = WriteOrder(
            get=lambda: self._flow.get_draft(
                request.app_id, request.kind, request.flow_id
            ),
            put=lambda new, version: self._flow.put_draft(
                request.app_id, request.kind, request.flow_id, new, version
            ),
            version_of=lambda d: d.version,
            publish=lambda: self._flow.publish(
                request.app_id, request.kind, request.flow_id
            ),
        )
        draft = await order.snapshot()

        try:
            matrix: Matrix = progressive_matrix(draft, request.owners)
            field_matrix: Matrix | None = (
                field_override_matrix(draft, request.field_owners)
                if request.field_owners
                else None
            )
        except ValueError as exc:
            raise ApplicationError(str(exc), code=VERIFY_FAILED) from exc

        report = await write_step_permissions(
            order,
            draft,
            flow_id=request.flow_id,
            matrix=matrix,
            field_matrix=field_matrix,
            publish=request.publish,
            include_pairs=request.include_pairs,
        )
        report["snapshot_version"] = order.snapshot_version
        return ForgeSetVisibilityResponse(report)
