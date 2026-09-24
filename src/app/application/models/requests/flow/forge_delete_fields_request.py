"""app.application.models.requests.flow.forge_delete_fields_request — the DTO for
`forge_delete_fields` (today's `server.py`: `delete_fields`, `client.py`): delete
form fields and/or child tables by name.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import FlowKindArg


class ForgeDeleteFieldsRequest(BaseModel):
    """One `forge_delete_fields` call.

    `app_id` is already resolved by the tool: the per-call `app_id` argument,
    else `settings.kf_app`, else `""` (see `brief_stage_d_common.md`, "The
    app id").
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    fields: list[str] | None = None
    tables: list[str] | None = None
    kind: FlowKindArg = "process"
    publish: bool = False
    app_id: str
