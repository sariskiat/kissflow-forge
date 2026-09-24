"""app.application.use_cases.dataset.forge_dataset_records — the
`forge_dataset_records` use case.

Ported from `app.infrastructure.kissflow.client.apply_dataset_records`
(refactor spec, Stage D group `d7_page_data_item_copilot`): the THIRD
data-plane route family, dataform records. `create`/`update` resolve a
record's KEYS (field name or field id) against the dataform's own draft
before the write -- the raw route 404s FieldNotFound on a name key -- read
through the FLOW port (`FlowRepository.get_draft`, kind `"dataset"`), since
that draft is a flow family concern; the record CRUD itself goes through the
DATASET port.

READ-BACK exemption (review fix 2): `create`/`update`/`delete` write straight
through the DATASET port with no read-back verification afterward --
`apply_dataset_records` never had one either (`client.py:5748-5794`,
pre-refactor: `create_dataset_record`/`update_dataset_record`/
`delete_dataset_record`'s own response is trusted directly, no follow-up
GET). This use case keeps that exact behavior: the FLOW port's `get_draft`
read is for field-name resolution only, never a draft this call writes back
to, so `assert_write_order` (which expects a write's own port to read
before it writes) does not apply to the DATASET port here, by design.
"""

from __future__ import annotations

from typing import Any

from app.application.exceptions import (
    CONFLICT,
    REFUSED,
    VERIFY_FAILED,
    ApplicationError,
    RepositoryError,
)
from app.application.interfaces.dataset import DatasetRepository
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.dataset.forge_dataset_records_request import (
    ForgeDatasetRecordsRequest,
)
from app.application.models.responses.dataset.forge_dataset_records_response import (
    ForgeDatasetRecordsResponse,
)
from app.application.use_cases.dataset import _records

_NO_APP_SELECTED = (
    "no app selected — pass app_id (see forge_list_apps for valid ids), "
    "or set the KF_APP env var as a single-app default"
)
_NAME_PASSTHROUGH = frozenset({"Name"})


class ForgeDatasetRecords:
    """Create, list, update or delete one dataform record."""

    def __init__(self, dataset: DatasetRepository, flow: FlowRepository) -> None:
        """Build the use case around its two ports.

        Args:
            dataset: The dataform-record family port.
            flow: The flow/process/form/case/list family port, whose
                `get_draft` reads a dataform's own draft for field-name
                resolution.
        """
        self._dataset = dataset
        self._flow = flow

    async def execute(
        self, request: ForgeDatasetRecordsRequest
    ) -> ForgeDatasetRecordsResponse:
        """Run one `forge_dataset_records` call, on the requested `op`.

        Args:
            request: The validated `forge_dataset_records` request.

        Returns:
            The output-invariant audit.

        Raises:
            ApplicationError: `request.app_id` is empty, `record`/
                `record_id` is missing where the op requires it, a record
                key resolves to no field, or the dataform draft read for
                field-name resolution failed (`code=VERIFY_FAILED`); or a
                `create` names an already-existing record (`code=CONFLICT`).
            RepositoryError: A port call other than the field-name-
                resolution draft read failed.
        """
        if not request.app_id:
            raise ApplicationError(_NO_APP_SELECTED, code=REFUSED)

        if request.op == "create":
            return await self._create(request)
        if request.op == "update":
            return await self._update(request)
        if request.op == "delete":
            return await self._delete(request)
        return await self._list(request)

    async def _resolve(
        self, app_id: str, flow_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            draft = await self._flow.get_draft(app_id, "dataset", flow_id)
        except RepositoryError as exc:
            raise ApplicationError(
                f"cannot resolve dataform field names — draft read failed: "
                f"{exc.message}",
                code=VERIFY_FAILED,
            ) from exc
        index = _records.field_name_index(draft.to_wire())
        try:
            return _records.resolve_value_keys(
                record, index, passthrough=_NAME_PASSTHROUGH
            )
        except ValueError as exc:
            raise ApplicationError(str(exc), code=VERIFY_FAILED) from exc

    async def _create(
        self, request: ForgeDatasetRecordsRequest
    ) -> ForgeDatasetRecordsResponse:
        if not request.record:
            raise ApplicationError(
                "apply_dataset_records(op='create') requires a non-empty record",
                code=VERIFY_FAILED,
            )
        resolved = await self._resolve(request.app_id, request.flow_id, request.record)
        try:
            got = await self._dataset.create_dataset_record(
                request.app_id, request.flow_id, resolved
            )
        except RepositoryError as exc:
            if exc.code == CONFLICT:
                name = request.record.get("Name", "<unknown>")
                raise ApplicationError(
                    f"dataset record with Name={name!r} already exists "
                    f"(duplicate key) — {exc.message}",
                    code=CONFLICT,
                ) from exc
            raise
        return ForgeDatasetRecordsResponse(
            flow_id=request.flow_id, op=request.op, created=1, record=got
        )

    async def _update(
        self, request: ForgeDatasetRecordsRequest
    ) -> ForgeDatasetRecordsResponse:
        if not request.record:
            raise ApplicationError(
                "apply_dataset_records(op='update') requires a non-empty record",
                code=VERIFY_FAILED,
            )
        if not request.record_id:
            raise ApplicationError(
                "apply_dataset_records(op='update') requires record_id "
                "(the record's _id)",
                code=VERIFY_FAILED,
            )
        resolved = await self._resolve(request.app_id, request.flow_id, request.record)
        got = await self._dataset.update_dataset_record(
            request.app_id, request.flow_id, request.record_id, resolved
        )
        return ForgeDatasetRecordsResponse(
            flow_id=request.flow_id,
            op=request.op,
            updated=1,
            record_id=request.record_id,
            record=got,
        )

    async def _delete(
        self, request: ForgeDatasetRecordsRequest
    ) -> ForgeDatasetRecordsResponse:
        if not request.record_id:
            raise ApplicationError(
                "apply_dataset_records(op='delete') requires record_id "
                "(the record's _id)",
                code=VERIFY_FAILED,
            )
        name = (request.record or {}).get("Name")
        if not name:
            raise ApplicationError(
                "apply_dataset_records(op='delete') requires "
                "record={'Name': <key>} — the delete route mandates the "
                "Name body",
                code=VERIFY_FAILED,
            )
        await self._dataset.delete_dataset_record(
            request.app_id, request.flow_id, request.record_id, name
        )
        return ForgeDatasetRecordsResponse(
            flow_id=request.flow_id,
            op=request.op,
            deleted=1,
            record_id=request.record_id,
        )

    async def _list(
        self, request: ForgeDatasetRecordsRequest
    ) -> ForgeDatasetRecordsResponse:
        got = await self._dataset.list_dataset_records(request.app_id, request.flow_id)
        rows = got.get("Data", []) if isinstance(got, dict) else []
        columns = got.get("Columns", []) if isinstance(got, dict) else []
        return ForgeDatasetRecordsResponse(
            flow_id=request.flow_id,
            op=request.op,
            listed=len(rows),
            columns=columns,
            records=rows,
        )
