"""app.application.models.requests.intake.forge_request_confirmation_request --
the DTO for `forge_request_confirmation`: build the confirmation pack a human
signs off on.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgeRequestConfirmationRequest(BaseModel):
    """One `forge_request_confirmation` call. Offline.

    `spec` validates into a real `AppSpec` here (Pydantic) -- a malformed
    `spec` fails with `ValidationError` before the use case ever runs.
    """

    model_config = ConfigDict(frozen=True)

    spec: AppSpec
    out_dir: str | None = None
