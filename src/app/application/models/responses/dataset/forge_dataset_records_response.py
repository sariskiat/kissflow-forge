"""app.application.models.responses.dataset.forge_dataset_records_response —
the `forge_dataset_records` response DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler


class ForgeDatasetRecordsResponse(BaseModel):
    """The output-invariant audit for `forge_dataset_records`: exactly one of
    `created`/`listed`/`updated`/`deleted` is non-zero, per `op`.

    Attributes:
        flow_id: The dataform's flow id.
        op: The op that ran: "create", "update", "delete" or "list".
        created: `1` on a successful `create`, else `0`.
        listed: The row count on a `list`, else `0`.
        updated: `1` on a successful `update`, else `0`.
        deleted: `1` on a successful `delete`, else `0`.
        failed: Always `0` on a returned response -- a failed write is a
            raised `ApplicationError` instead (rule 7).
        record: The written record, present only for `create`/`update`
            (`apply_dataset_records` never adds this key for `delete`/
            `list`).
        record_id: The record id, present only for `update`/`delete`
            (`apply_dataset_records` never adds this key for `create`/
            `list`).
        columns: The dataform's columns, present only for `list`.
        records: The listed rows, present only for `list`.
        snapshot_version: Always `None` -- this write has no versioned
            draft to snapshot.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    op: str
    created: int = 0
    listed: int = 0
    updated: int = 0
    deleted: int = 0
    failed: int = 0
    record: dict[str, Any] | None = None
    record_id: str | None = None
    columns: list[Any] = []
    records: list[Any] = []
    snapshot_version: str | None = None

    @model_serializer(mode="wrap")
    def _drop_keys_the_old_dict_never_added_for_this_op(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Serialize with `record`/`record_id`/`columns`/`records` left out
        for the ops `apply_dataset_records` never added them for.

        The old dict is built as `{**base, ...}` per op branch: `record` is
        only ever added on `create`/`update`, `record_id` only on
        `update`/`delete`, and `columns`/`records` only on `list`. Matching
        that exactly (rather than a bare `None`/`[]`) matters because an
        empty `columns`/`records` list is a REAL, meaningful `list` result
        (a dataform with zero records) -- it must stay present -- while the
        same empty shape on a `create`/`update`/`delete` call is a key the
        old dict never had at all.

        Args:
            handler: The default pydantic-core serializer for this model.

        Returns:
            The serialized dict, with each op-specific key present only for
            the op that old code added it for.
        """
        data = handler(self)
        if self.op not in ("create", "update"):
            data.pop("record", None)
        if self.op not in ("update", "delete"):
            data.pop("record_id", None)
        if self.op != "list":
            data.pop("columns", None)
            data.pop("records", None)
        return data
