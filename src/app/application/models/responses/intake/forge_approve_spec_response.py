"""app.application.models.responses.intake.forge_approve_spec_response -- the
DTO for `forge_approve_spec`'s result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeApproveSpecResponse(BaseModel):
    """The approved spec, its plain content digest, and the approval_token.

    `approval_token`: an HMAC of `digest` under a secret generated once per
    server process, never logged, never returned by any other tool.
    `forge_plan_app` demands this, never a plain `digest`.
    """

    model_config = ConfigDict(frozen=True)

    spec: dict[str, Any]
    approved: bool
    digest: str
    approval_token: str
