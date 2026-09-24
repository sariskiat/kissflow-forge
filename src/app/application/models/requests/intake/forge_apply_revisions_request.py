"""app.application.models.requests.intake.forge_apply_revisions_request -- the
DTO for `forge_apply_revisions`: apply a customer's corrections to a spec.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgeApplyRevisionsRequest(BaseModel):
    """One `forge_apply_revisions` call. Offline, stateless.

    `spec` validates into a real `AppSpec` here (Pydantic) -- a malformed
    `spec` fails with `ValidationError` before the use case ever runs.
    """

    model_config = ConfigDict(frozen=True)

    spec: AppSpec
    revisions: dict[str, str]
