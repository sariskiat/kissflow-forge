"""app.application.models.responses.app.forge_create_app_response — the DTO for
`forge_create_app`'s result: today's `client.create_application_verified`'s
success dict, minus `isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCreateAppResponse(BaseModel):
    """The verified-create audit of one `forge_create_app` call.

    Only returned once the new application id actually verified on the
    application-list read-back (rule 7, `brief_stage_d_common.md`: a write
    that did not fully land is a failure, never a success response) --
    `verified` is always `True` on this path.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    name: str
    verified: bool
    supported: bool
    note: str | None
    snapshot_version: str | None = None
