"""app.application.models.requests.intake.kf_plan_step_visibility_request -- the
DTO for `kf_plan_step_visibility`: preview per-step section visibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class KfPlanStepVisibilityRequest(BaseModel):
    """One `kf_plan_step_visibility` call. Offline: no app id, no Kissflow call.

    `owners` maps a section NAME to the step names that own it.
    """

    model_config = ConfigDict(frozen=True)

    draft: dict[str, Any]
    owners: dict[str, list[str]]
