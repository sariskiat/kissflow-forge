"""app.application.use_cases.flow.forge_add_sequence_number — the
`forge_add_sequence_number` use case.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_add_sequence_number_request import (
    ForgeAddSequenceNumberRequest,
)
from app.application.models.responses.flow.forge_add_sequence_number_response import (
    ForgeAddSequenceNumberResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._sequence import _verify_sequence_number
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeAddSequenceNumber:
    """Add an auto-numbered item-id field: GET draft ->
    `FlowDraft.add_sequence_number` offline (resolves the Step-stamp
    activity by NAME) -> guarded PUT -> read-back verify the SequenceNumber
    Field + its 3 Property nodes landed -> optional publish.
    """

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around its one port.

        Args:
            flow: The flow/process/form/case/list family port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeAddSequenceNumberRequest
    ) -> ForgeAddSequenceNumberResponse:
        """Run the add-sequence-number write order and return its audit.

        Args:
            request: The validated `forge_add_sequence_number` request.

        Returns:
            The audit, only when the field verified: a returned response
            always carries `verified=True`, `missing=False`.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                offline `add_sequence_number` rejected the spec
                (`code=VERIFY_FAILED`); or the field did not verify on
                read-back (`code=VERIFY_FAILED`, naming the field and
                whether anything published).
        """
        require_app_id(request.app_id)

        order: WriteOrder[FlowDraft] = WriteOrder(
            get=lambda: self._flow.get_draft(
                request.app_id, request.kind, request.flow_id
            ),
            put=lambda new, expect_version: self._flow.put_draft(
                request.app_id, request.kind, request.flow_id, new, expect_version
            ),
            version_of=lambda d: d.version,
            publish=lambda: self._flow.publish(
                request.app_id, request.kind, request.flow_id
            ),
        )

        draft = await order.snapshot()
        try:
            new_draft = draft.add_sequence_number(
                request.field_name,
                request.section_name,
                request.prefix,
                request.padding,
                request.step_activity_name,
                start=request.start,
                end=request.end,
            )
        except ValueError as exc:
            raise ApplicationError(
                f"offline add_sequence_number rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc
        await order.apply(new_draft)

        read_back = await order.read_back()
        verified = _verify_sequence_number(read_back.to_wire(), request.field_name)

        published = False
        if request.publish and verified:
            await order.publish()
            published = True

        raise_if_write_failed(
            published=published,
            missing=() if verified else (request.field_name,),
        )

        return ForgeAddSequenceNumberResponse(
            flow_id=request.flow_id,
            field_name=request.field_name,
            section=request.section_name,
            verified=verified,
            missing=not verified,
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
