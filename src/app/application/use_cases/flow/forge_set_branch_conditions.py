"""app.application.use_cases.flow.forge_set_branch_conditions — the
`forge_set_branch_conditions` use case.

Ported from `app.infrastructure.kissflow.client.apply_branch_conditions`
(refactor spec, Stage D group `d3_flow_workflow`): GET draft (the
`WriteOrder` snapshot) -> resolve the flow's single Parallel gateway's
branches BY NAME -> resolve the deciding field BY NAME -> when that field is
a Select backed by a `ReferredList`, fetch its REAL live options and
validate every literal in `branch_literals` against them before any write ->
for each named branch, offline remove any condition it already has and
attach the new one -> ONE guarded write -> read-back verify each branch's
condition landed -> optional publish.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_set_branch_conditions_request import (
    ForgeSetBranchConditionsRequest,
)
from app.application.models.responses.flow.forge_set_branch_conditions_response import (
    ForgeSetBranchConditionsResponse,
)
from app.application.use_cases.flow._branches import _uncovered_options
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._gates import _parallel_branches
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeSetBranchConditions:
    """Make an existing Parallel's branches conditional on one deciding field."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around the flow-family port.

        Args:
            flow: The `FlowRepository` adapter for this call's Kissflow tenant.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeSetBranchConditionsRequest
    ) -> ForgeSetBranchConditionsResponse:
        """Run one `forge_set_branch_conditions` call end to end.

        Args:
            request: The validated request DTO.

        Returns:
            The branch-condition report, with `snapshot_version` set. Only
            returned when every requested branch verified on read-back.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                gateway, a branch, or the field does not resolve, a literal
                is not a real live option, or a requested branch did not
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

        branches = _parallel_branches(wire)
        unknown = sorted(set(request.branch_literals) - set(branches))
        if unknown:
            raise ApplicationError(
                f"no branch(es) named {unknown} on the Parallel gateway (real "
                f"branches: {sorted(branches)})",
                code=VERIFY_FAILED,
            )

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

        options: list[str] | None = None
        field_node = wire[field_id]
        if field_node.get("Type") == "Select" and field_node.get("ReferredList"):
            items = await self._flow.get_list_items(
                request.app_id, field_node["ReferredList"]
            )
            options = list(items) if isinstance(items, list) else []

        new_flow = draft
        try:
            for branch_name, literal in request.branch_literals.items():
                pd_id = branches[branch_name]
                for existing_eid in new_flow.process_def_expression_ids(pd_id):
                    new_flow = new_flow.remove_condition(expression_id=existing_eid)
                new_flow = new_flow.build_branch_condition(
                    process_def_id=pd_id,
                    field_id=field_id,
                    literal=literal,
                    options=options,
                )
        except ValueError as exc:
            raise ApplicationError(
                f"offline build_branch_condition rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        await order.apply(new_flow)
        read_back = await order.read_back()
        read_wire = read_back.to_wire()

        def _landed(branch_name: str, literal: str) -> bool:
            pd = read_wire.get(branches[branch_name]) or {}
            for eid in pd.get("ProcessDef::Expression") or []:
                e = read_wire.get(eid) or {}
                for root_id in e.get("Expression::Node") or []:
                    children = [
                        read_wire.get(c) or {}
                        for c in (read_wire.get(root_id) or {}).get("Node::Node") or []
                    ]
                    has_field = any(
                        c.get("Type") == "Field" and c.get("Field") == field_id
                        for c in children
                    )
                    has_literal = any(
                        c.get("Type") == "Static" and c.get("Value") == literal
                        for c in children
                    )
                    if has_field and has_literal:
                        return True
            return False

        wanted = tuple(request.branch_literals)
        verified = tuple(b for b in wanted if _landed(b, request.branch_literals[b]))
        missing = tuple(b for b in wanted if b not in verified)
        # Against the FULL branch set (not just the ones this call touched) -- a
        # value some EARLIER call already covered on a different branch must never
        # re-appear here as a false alarm.
        uncovered = _uncovered_options(read_wire, branches.values(), field_id, options)

        published = False
        if request.publish and not missing:
            await order.publish()
            published = True

        raise_if_write_failed(published=published, missing=missing)

        return ForgeSetBranchConditionsResponse(
            flow_id=request.flow_id,
            field_name=request.field_name,
            branches=list(wanted),
            verified=list(verified),
            missing=list(missing),
            uncovered=list(uncovered),
            meta_version=read_wire.get("_meta_version"),
            published=published,
            snapshot_version=order.snapshot_version,
        )
