"""app.application.use_cases.flow.forge_add_table — the `forge_add_table`
use case.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_add_table_request import (
    ForgeAddTableRequest,
)
from app.application.models.responses.flow.forge_add_table_response import (
    ForgeAddTableResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._table import (
    _audit_table_columns,
    _find_table_host,
    _table_live_columns,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeAddTable:
    """Add a child table: GET draft -> `FlowDraft.add_table` offline
    (idempotent, no-op if a table of that name already exists) -> guarded
    PUT (skipped on the idempotent no-op path) -> read-back verify every
    child column NAME actually landed -> optional publish.
    """

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around its one port.

        Args:
            flow: The flow/process/form/case/list family port.
        """
        self._flow = flow

    async def execute(self, request: ForgeAddTableRequest) -> ForgeAddTableResponse:
        """Run the add-table write order and return its audit.

        Args:
            request: The validated `forge_add_table` request.

        Returns:
            The output-invariant audit, only when every requested column
            verified: `missing_columns` is always empty on a returned
            response.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                offline `add_table` rejected the spec (`code=VERIFY_FAILED`);
                or one or more columns did not verify on read-back
                (`code=VERIFY_FAILED`, naming the missing columns and
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
        already = _find_table_host(draft.to_wire(), request.name) is not None
        try:
            new_draft = draft.add_table(
                request.name,
                request.columns,
                max_rows=request.max_rows,
                allow_import=request.allow_import,
                after_section=request.after_section,
            )
        except ValueError as exc:
            raise ApplicationError(
                f"offline add_table rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc
        if not already:
            await order.apply(new_draft)

        read_back = await order.read_back()
        wanted_cols = tuple(c[0] for c in request.columns)
        live_cols = _table_live_columns(read_back.to_wire(), request.name)
        verified, missing = _audit_table_columns(wanted_cols, live_cols)

        published = False
        if request.publish and not missing:
            await order.publish()
            published = True

        raise_if_write_failed(published=published, missing_columns=missing)

        return ForgeAddTableResponse(
            flow_id=request.flow_id,
            table_name=request.name,
            created=not already,
            columns=list(wanted_cols),
            verified_columns=list(verified),
            missing_columns=list(missing),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
