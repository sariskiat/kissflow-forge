"""app.application.models.requests.intake.kf_plan_field_change_request -- the DTO
for `kf_plan_field_change`: preview adding fields to a flow's draft graph.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake._field_change_in import FieldChangeIn


class KfPlanFieldChangeRequest(BaseModel):
    """One `kf_plan_field_change` call. Offline: no app id, no Kissflow call."""

    model_config = ConfigDict(frozen=True)

    draft: dict[str, Any]
    changes: list[FieldChangeIn]
