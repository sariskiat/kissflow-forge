"""app.application.models.requests.flow.forge_rename_fields_request — the DTO for
`forge_rename_fields` (today's `server.py`: `rename_form_fields`, `client.py`):
rename form fields, `{current name: new name}`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import FlowKindArg


class ForgeRenameFieldsRequest(BaseModel):
    """One `forge_rename_fields` call.

    `app_id` is already resolved by the tool: the per-call `app_id` argument,
    else `settings.kf_app`, else `""` (see `brief_stage_d_common.md`, "The
    app id").
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    renames: dict[str, str]
    kind: FlowKindArg = "process"
    publish: bool = False
    app_id: str
