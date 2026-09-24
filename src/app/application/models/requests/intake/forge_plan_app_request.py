"""app.application.models.requests.intake.forge_plan_app_request -- the DTO
for `forge_plan_app`: compile an APPROVED, COMPLETE spec to its ordered
BuildPlan -- THE GATE.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgePlanAppRequest(BaseModel):
    """One `forge_plan_app` call. Offline.

    `spec` validates into a real `AppSpec` here (Pydantic).
    """

    model_config = ConfigDict(frozen=True)

    spec: AppSpec
    approval_token: str
