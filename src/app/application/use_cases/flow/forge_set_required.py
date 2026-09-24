"""app.application.use_cases.flow.forge_set_required — set which root-model fields
are Required.

Ported from `app.infrastructure.kissflow.client.apply_required` (Stage D group 1).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_set_required_request import (
    ForgeSetRequiredRequest,
)
from app.application.models.responses.flow.forge_set_required_response import (
    ForgeSetRequiredResponse,
)
from app.application.use_cases.flow._fields import (
    audit_required_readback,
    cleared_required_fields,
    raise_if_write_failed,
    require_app_id,
    root_field_nodes,
    unsatisfiable_required_fields,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeSetRequired:
    """Use case behind the `forge_set_required` tool."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeSetRequiredRequest
    ) -> ForgeSetRequiredResponse:
        """Run one `forge_set_required` call: snapshot, refuse an un-fillable
        request, set the flag offline, guarded write, read-back the whole
        population, optional publish.

        SET semantics, not a patch: every root field not named in
        `request.required` comes back optional. Always writes.

        Args:
            request: The validated request.

        Returns:
            The output-invariant audit of what happened -- only when every
            root field's flag verified on read-back (rule 7: a write that
            did not fully land is a failure, never a success response with
            the failure sitting inside a bucket).

        Raises:
            ApplicationError: `request.app_id` is empty (`REFUSED`); a
                computed or SequenceNumber field was requested Required, or
                the offline set was rejected (`VERIFY_FAILED`); a root
                field's flag is `missing` on read-back (`VERIFY_FAILED`,
                naming the bucket, its items and whether anything
                published). A `RepositoryError` from the port (a read, write
                or conflict failure) propagates unchanged.
        """
        require_app_id(request.app_id)
        wanted = set(request.required)

        order = WriteOrder[FlowDraft](
            get=lambda: self._flow.get_draft(
                request.app_id, request.kind, request.flow_id
            ),
            put=lambda new, expect_version: self._flow.put_draft(
                request.app_id, request.kind, request.flow_id, new, expect_version
            ),
            version_of=lambda draft: draft.version,
        )
        snapshot = await order.snapshot()
        root_fields = root_field_nodes(snapshot.to_wire())

        unsatisfiable = unsatisfiable_required_fields(root_fields, wanted)
        if unsatisfiable:
            raise ApplicationError(
                f"refusing to mark un-fillable field(s) Required: "
                f"{unsatisfiable} — a value the user cannot type makes that "
                "step permanently unsubmittable (FlowDraft.set_required, "
                "CLAUDE.md Visibility)",
                code=VERIFY_FAILED,
            )
        cleared = cleared_required_fields(root_fields, wanted)

        try:
            new = snapshot.set_required(wanted)
        except ValueError as exc:
            raise ApplicationError(
                f"offline set_required rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        await order.apply(new)
        read_back = await order.read_back()
        verified, missing = audit_required_readback(
            root_field_nodes(read_back.to_wire()), wanted
        )

        published = False
        if request.publish and not missing:
            await self._flow.publish(request.app_id, request.kind, request.flow_id)
            published = True

        raise_if_write_failed(published=published, missing=missing)

        return ForgeSetRequiredResponse(
            flow_id=request.flow_id,
            required=list(request.required),
            verified=list(verified),
            missing=list(missing),
            cleared=list(cleared),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
