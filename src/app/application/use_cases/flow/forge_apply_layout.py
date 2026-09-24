"""app.application.use_cases.flow.forge_apply_layout — re-place every field at exact
grid coordinates.

Ported from `app.infrastructure.kissflow.client.apply_layout` (Stage D group 1).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_apply_layout_request import (
    ForgeApplyLayoutRequest,
)
from app.application.models.responses.flow.forge_apply_layout_response import (
    ForgeApplyLayoutResponse,
)
from app.application.use_cases.flow._fields import require_app_id, section_field_names
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft, validate_layout_spans


class ForgeApplyLayout:
    """Use case behind the `forge_apply_layout` tool."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeApplyLayoutRequest
    ) -> ForgeApplyLayoutResponse:
        """Run one `forge_apply_layout` call: validate the spec offline, snapshot,
        rebuild the layout offline, guarded write, read-back, optional publish.

        Always writes: a re-layout is a real change even with no new fields.

        Args:
            request: The validated request.

        Returns:
            The output-invariant audit of what happened.

        Raises:
            ApplicationError: `request.app_id` is empty (`REFUSED`), or the
                layout spec was rejected, offline, either before or after
                the read (`VERIFY_FAILED`). A `RepositoryError` from the
                port (a read, write or conflict failure) propagates
                unchanged.
        """
        require_app_id(request.app_id)

        try:
            validate_layout_spans(request.layout)
        except ValueError as exc:
            raise ApplicationError(
                f"offline apply_exact_layout rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

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
        before_draft = snapshot.to_wire()

        collateral = tuple(
            f"{title!r}: {fname!r} was not named in the layout — re-tiled "
            "into a trailing row after the stated rows"
            for title, rows_spec in request.layout.items()
            for fname in section_field_names(before_draft, title)
            if fname not in {f for row in rows_spec for f, _s, _e in row}
        )

        try:
            new = snapshot.apply_exact_layout(
                request.layout, descriptions=request.descriptions
            )
        except ValueError as exc:
            raise ApplicationError(
                f"offline apply_exact_layout rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        await order.apply(new)
        read_back = await order.read_back()

        wanted_sections = tuple(request.layout)
        published = False
        if request.publish:
            await self._flow.publish(request.app_id, request.kind, request.flow_id)
            published = True

        return ForgeApplyLayoutResponse(
            flow_id=request.flow_id,
            added=[],
            skipped=list(wanted_sections),
            verified=list(wanted_sections),
            missing=[],
            changed_ignored=[],
            collateral=list(collateral),
            remediation=["forge_apply_layout"] if collateral else [],
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
