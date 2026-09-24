"""app.application.models.requests.intake.forge_intake_questions_request -- the
DTO for `forge_intake_questions`: the next questions to ask, for a spec's
current gaps.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgeIntakeQuestionsRequest(BaseModel):
    """One `forge_intake_questions` call. Offline, stateless.

    `spec=None` returns the OPENING questions (every one of the 11
    dimensions is a gap). `spec` validates into a real `AppSpec` here
    (Pydantic) when given -- a malformed `spec` fails with
    `ValidationError` before the use case ever runs.
    """

    model_config = ConfigDict(frozen=True)

    spec: AppSpec | None = None
    limit: int = 4
