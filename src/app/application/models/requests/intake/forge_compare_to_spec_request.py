"""app.application.models.requests.intake.forge_compare_to_spec_request -- the
DTO for `forge_compare_to_spec`: does the BUILT flow match what the INPUT
asked for?
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec
from app.domain.value_objects.kinds import FlowKindArg


class ForgeCompareToSpecRequest(BaseModel):
    """One `forge_compare_to_spec` call.

    `spec` validates into a real `AppSpec` here (Pydantic). `app_id` is
    already resolved by the tool: the per-call `app_id` argument, else
    `settings.kf_app`, else `""`.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    spec: AppSpec
    kind: FlowKindArg = "process"
    app_id: str
