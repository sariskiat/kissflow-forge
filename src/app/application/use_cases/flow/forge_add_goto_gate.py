"""app.application.use_cases.flow.forge_add_goto_gate — the `forge_add_goto_gate`
use case.

Ported from `app.infrastructure.kissflow.client.apply_goto_gate` (refactor
spec, Stage D group `d3_flow_workflow`): GET draft (the `WriteOrder`
snapshot) -> resolve the target workflow step + gating Boolean field BY NAME
-> ONE guarded write combining `FlowDraft.add_goto_task` (mints the GotoTask
edge node) + `FlowDraft.build_goto_gate` (attaches the `= false()` loop
condition, gate-polarity-checked: only a Boolean may gate a loop) ->
read-back verify the condition landed -> optional publish.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_add_goto_gate_request import (
    ForgeAddGotoGateRequest,
)
from app.application.models.responses.flow.forge_add_goto_gate_response import (
    ForgeAddGotoGateResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._gates import (
    _parallel_branches,
    _resolve_activity_by_name,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeAddGotoGate:
    """Add a backward-jump GotoTask, gated on a Boolean field."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around the flow-family port.

        Args:
            flow: The `FlowRepository` adapter for this call's Kissflow tenant.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeAddGotoGateRequest
    ) -> ForgeAddGotoGateResponse:
        """Run one `forge_add_goto_gate` call end to end.

        Args:
            request: The validated request DTO.

        Returns:
            The new gate's report, with `snapshot_version` set. Only returned
            when the loop condition verified on read-back.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                target step or field does not resolve, is ambiguous, the
                offline build was rejected, or the loop condition did not
                verify on read-back (`code=VERIFY_FAILED`).
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
        wire = draft.to_wire()

        branch_pd_id: str | None = None
        if request.branch_name is not None:
            branches = _parallel_branches(wire)
            branch_pd_id = branches.get(request.branch_name)
            if branch_pd_id is None:
                raise ApplicationError(
                    f"no branch named {request.branch_name!r} on the Parallel "
                    f"gateway (real branches: {sorted(branches)})",
                    code=VERIFY_FAILED,
                )
            target_id = _resolve_activity_by_name(
                wire, request.target_activity_name, process_def_id=branch_pd_id
            )
        else:
            target_id = _resolve_activity_by_name(wire, request.target_activity_name)

        field_id = next(
            (
                k
                for k, v in wire.items()
                if isinstance(v, dict)
                and v.get("Kind") == "Field"
                and v.get("Name") == request.field_name
            ),
            None,
        )
        if field_id is None:
            raise ApplicationError(
                f"no field named {request.field_name!r}", code=VERIFY_FAILED
            )

        try:
            with_goto, goto_id = draft.add_goto_task(
                target_activity_id=target_id, branch_process_def_id=branch_pd_id
            )
            new = with_goto.build_goto_gate(goto_activity_id=goto_id, field_id=field_id)
        except ValueError as exc:
            raise ApplicationError(
                f"offline goto-gate build rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        await order.apply(new)
        read_back = await order.read_back()
        read_wire = read_back.to_wire()
        goto_node = read_wire.get(goto_id) or {}
        verified = bool(goto_node.get("Activity::Expression"))

        published = False
        if request.publish and verified:
            await order.publish()
            published = True

        raise_if_write_failed(
            published=published,
            gate_unverified=()
            if verified
            else (
                f"target={request.target_activity_name!r} field={request.field_name!r}",
            ),
        )

        return ForgeAddGotoGateResponse(
            flow_id=request.flow_id,
            goto_activity_id=goto_id,
            target_activity=request.target_activity_name,
            field_name=request.field_name,
            branch_name=request.branch_name,
            verified=verified,
            meta_version=read_wire.get("_meta_version"),
            published=published,
            snapshot_version=order.snapshot_version,
        )
