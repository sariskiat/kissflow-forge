"""app.application.models.requests.flow.kf_apply_field_change_request — the DTO for
`kf_apply_field_change` (today's `server.py`: `apply_fields`, `client.py`): add fields
to a flow, verified by read-back, optionally published.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.flow._field_spec_in import FieldSpecIn
from app.domain.value_objects.kinds import DataKind


class KfApplyFieldChangeRequest(BaseModel):
    """One `kf_apply_field_change` call.

    `app_id` is already resolved by the tool: the per-call `app_id` argument,
    else `settings.kf_app`, else `""` (see `brief_stage_d_common.md`, "The
    app id").
    """

    model_config = ConfigDict(frozen=True)

    flow_kind: DataKind
    flow_id: str
    changes: list[FieldSpecIn]
    publish: bool = False
    app_id: str
