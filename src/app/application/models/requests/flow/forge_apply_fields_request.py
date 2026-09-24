"""app.application.models.requests.flow.forge_apply_fields_request — the DTO for
`forge_apply_fields` (today's `server.py`: `apply_fields_full`, `client.py`): add
fields, lay them into sections, and attach validation/computed/conditional-visibility,
in one guarded write.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.flow._field_spec_in import FieldSpecIn
from app.domain.value_objects.kinds import DataKind


class ForgeApplyFieldsRequest(BaseModel):
    """One `forge_apply_fields` call.

    `app_id` is already resolved by the tool: the per-call `app_id` argument,
    else `settings.kf_app`, else `""` (see `brief_stage_d_common.md`, "The
    app id").
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    fields: list[FieldSpecIn]
    sections: dict[str, list[str]] | None = None
    validation: dict[str, list[dict[str, str]]] | None = None
    computed: dict[str, dict[str, Any]] | None = None
    conditional_visibility: dict[str, dict[str, str]] | None = None
    kind: DataKind = "process"
    publish: bool = False
    app_id: str
