"""app.application.models.requests.dataset.forge_dataset_records_request —
the `forge_dataset_records` request DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import DatasetOp


class ForgeDatasetRecordsRequest(BaseModel):
    """One `forge_dataset_records` call: create, list, update or delete one
    dataform record.

    `app_id` is already resolved by the tool: the per-call `app_id`
    argument, else `settings.kf_app`, else `""` (see
    `brief_stage_d_common.md`, "The app id").
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    op: DatasetOp
    record: dict[str, Any] | None = None
    record_id: str | None = None
    app_id: str
