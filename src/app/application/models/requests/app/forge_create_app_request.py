"""app.application.models.requests.app.forge_create_app_request — the DTO for
`forge_create_app` (today's `server.py`: `create_application_verified`,
`client.py`): create a new application.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCreateAppRequest(BaseModel):
    """One `forge_create_app` call.

    Carries no `app_id`: the old tool built its client with
    `require_app=False` -- this is how a caller makes their FIRST
    application, so there is no existing one to select yet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
