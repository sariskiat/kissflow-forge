"""app.application.use_cases.flow.forge_add_field_validation — the
`forge_add_field_validation` use case.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_add_field_validation_request import (
    ForgeAddFieldValidationRequest,
)
from app.application.models.responses.flow.forge_add_field_validation_response import (
    ForgeAddFieldValidationResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._validation import (
    _audit_all_field_rules,
    _calc_missing,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeAddFieldValidation:
    """Attach per-field validation rules: GET draft ->
    `FlowDraft.add_field_validation` offline, once per (field, operator,
    value) rule (one Condition per rule, reusing the field's existing
    Criteria) -> guarded PUT -> read-back verify each rule landed ->
    optional publish.
    """

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around its one port.

        Args:
            flow: The flow/process/form/case/list family port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeAddFieldValidationRequest
    ) -> ForgeAddFieldValidationResponse:
        """Run the add-field-validation write order and return its audit.

        Args:
            request: The validated `forge_add_field_validation` request.

        Returns:
            The output-invariant audit, only when every requested rule
            verified: `missing` is always empty on a returned response.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                offline `add_field_validation` rejected the spec
                (`code=VERIFY_FAILED`); or one or more rules did not verify
                on read-back (`code=VERIFY_FAILED`, naming the missing rules
                and whether anything published).
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
            new_draft = draft
            for field_name, field_rules in request.rules.items():
                for operator, value in field_rules:
                    new_draft = new_draft.add_field_validation(
                        field_name, operator, value
                    )
        except ValueError as exc:
            raise ApplicationError(
                f"offline add_field_validation rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc
        await order.apply(new_draft)

        read_back = await order.read_back()
        flat, verified = _audit_all_field_rules(read_back.to_wire(), request.rules)
        missing = _calc_missing(flat, verified)

        published = False
        if request.publish and not missing:
            await order.publish()
            published = True

        raise_if_write_failed(published=published, missing=missing)

        return ForgeAddFieldValidationResponse(
            flow_id=request.flow_id,
            field_name=",".join(request.rules),
            rules=flat,
            verified=verified,
            missing=list(missing),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
