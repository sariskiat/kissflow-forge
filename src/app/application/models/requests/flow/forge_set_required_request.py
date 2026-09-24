"""app.application.models.requests.flow.forge_set_required_request — the DTO for
`forge_set_required` (today's `server.py`: `apply_required`, `client.py`): set which
root-model fields are Required.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import FlowKindArg


class ForgeSetRequiredRequest(BaseModel):
    """One `forge_set_required` call.

    `app_id` is already resolved by the tool: the per-call `app_id` argument,
    else `settings.kf_app`, else `""` (see `brief_stage_d_common.md`, "The
    app id").
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    required: list[str]
    kind: FlowKindArg = "process"
    publish: bool = False
    app_id: str
