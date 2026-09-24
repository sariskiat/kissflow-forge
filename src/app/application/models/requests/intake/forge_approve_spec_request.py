"""app.application.models.requests.intake.forge_approve_spec_request -- the
DTO for `forge_approve_spec`: record approval and mint the ONLY value
`forge_plan_app` accepts.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec
from app.domain.value_objects.kinds import ApprovalDecision


class ForgeApproveSpecRequest(BaseModel):
    """One `forge_approve_spec` call. Offline.

    `spec` validates into a real `AppSpec` here (Pydantic). `decision` is
    the closed literal `"approve"` -- the same type the old tool already
    declared; any other value now fails with `ValidationError` before the
    use case runs, where before it depended on Python not enforcing its
    own type hints.
    """

    model_config = ConfigDict(frozen=True)

    spec: AppSpec
    digest: str
    decision: ApprovalDecision
