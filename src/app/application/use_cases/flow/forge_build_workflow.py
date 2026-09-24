"""app.application.use_cases.flow.forge_build_workflow — the `forge_build_workflow`
use case.

Ported from `app.infrastructure.kissflow.client.apply_workflow` (refactor spec,
Stage D group `d3_flow_workflow`): GET draft (the `WriteOrder` snapshot) ->
`FlowDraft.build_workflow` offline (DESTRUCTIVE -- every existing Activity/
ProcessDef/Resource/Permission is replaced) -> guarded write -> read-back
verify every step NAME landed -> optional publish. Callers must re-run
`forge_set_visibility` straight after this: the wiped Permission matrix is
`build_workflow`'s own documented behaviour, not a bug this use case papers
over.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_build_workflow_request import (
    ForgeBuildWorkflowRequest,
)
from app.application.models.responses.flow.forge_build_workflow_response import (
    ForgeBuildWorkflowResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._permissions import (
    _malformed_permissions,
    _permission_pairs,
)
from app.application.use_cases.flow._workflow import _sequence_step_stamps
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeBuildWorkflow:
    """Replace a flow's whole workflow: Start -> steps -> [Parallel branches] -> End."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around the flow-family port.

        Args:
            flow: The `FlowRepository` adapter for this call's Kissflow tenant.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeBuildWorkflowRequest
    ) -> ForgeBuildWorkflowResponse:
        """Run one `forge_build_workflow` call end to end.

        Args:
            request: The validated request DTO.

        Returns:
            The rebuilt workflow's report, with `snapshot_version` set. Only
            returned when every requested step verified on read-back.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                offline rebuild rejected the spec, or one or more requested
                steps did not verify on read-back (`code=VERIFY_FAILED`).
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
        draft_wire = draft.to_wire()
        permissions_before = _permission_pairs(draft_wire)
        malformed_before = _malformed_permissions(draft_wire)
        stamps_before = _sequence_step_stamps(draft_wire)

        try:
            new = draft.build_workflow(
                request.steps,
                parallel=request.parallel,
                parallel_after=request.parallel_after,
                roles=request.roles,
                step_meta=request.step_meta,
            )
        except ValueError as exc:
            raise ApplicationError(
                f"offline build_workflow rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        await order.apply(new)
        read_back = await order.read_back()
        read_wire = read_back.to_wire()

        live_names = {
            v.get("Name")
            for v in read_wire.values()
            if isinstance(v, dict) and v.get("Kind") == "Activity"
        }
        wanted = tuple(name for name, _role in request.steps)
        verified = tuple(n for n in wanted if n in live_names)
        missing = tuple(n for n in wanted if n not in live_names)
        assigned = tuple(name for name, role in request.steps if role)
        unassigned = tuple(name for name, role in request.steps if not role)

        # THE RULE: the damage is counted on what came BACK, never on what we sent.
        permissions_deleted = max(
            len(permissions_before) - len(_permission_pairs(read_wire)), 0
        )
        stamps_after = _sequence_step_stamps(read_wire)
        relocated = tuple(
            f"SequenceNumber {fname!r}: Step stamp relocated from step {was!r} to "
            f"{stamps_after.get(fname)!r} — build_workflow repoints a stranded stamp "
            "by NAME, falling back to StartEvent (#18: a dangling stamp is THE "
            "deterministic publish-500)"
            for fname, was in stamps_before.items()
            if stamps_after.get(fname) != was
        )
        collateral: list[str] = []
        remediation: list[str] = []
        if permissions_deleted > 0:
            collateral.append(
                f"{permissions_deleted} Permission node(s) deleted — build_workflow "
                "replaces every Activity, so the WHOLE per-step visibility matrix is "
                "gone (CLAUDE.md Workflow, Visibility)"
            )
            remediation.append("forge_set_visibility")
        if relocated:
            collateral.extend(relocated)
            remediation.append("forge_add_sequence_number")
        if malformed_before:
            # These never counted as pairs, so `permissions_deleted` cannot describe
            # them — and the rebuild destroyed them all the same. Named, not counted
            # into the pair total, so the two numbers stay honest and no Permission
            # node lands in zero buckets.
            collateral.append(
                f"{len(malformed_before)} malformed Permission node(s) deleted, "
                f"outside the {permissions_deleted} counted pair(s) (no readable "
                f"Column/Activity): {', '.join(malformed_before)}"
            )
            if "forge_set_visibility" not in remediation:
                remediation.append("forge_set_visibility")

        published = False
        if request.publish and not missing:
            await order.publish()
            published = True

        raise_if_write_failed(
            published=published,
            missing=missing,
            collateral=collateral,
            remediation=remediation,
        )

        return ForgeBuildWorkflowResponse(
            flow_id=request.flow_id,
            steps=list(wanted),
            verified_steps=list(verified),
            missing_steps=list(missing),
            assigned=list(assigned),
            unassigned=list(unassigned),
            permissions_deleted=permissions_deleted,
            collateral=collateral,
            remediation=remediation,
            meta_version=read_wire.get("_meta_version"),
            published=published,
            snapshot_version=order.snapshot_version,
        )
