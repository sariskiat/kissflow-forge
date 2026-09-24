"""app.application.models.requests.app.forge_create_template_app_request — the
DTO for `forge_create_template_app` (today's `server.py`: `create_template_app`,
`client.py`): one call, create a fresh Template App carrying the transplanted
source template process, published end to end.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCreateTemplateAppRequest(BaseModel):
    """One `forge_create_template_app` call.

    Carries no `app_id`: this call MAKES the application, so there is no
    existing one to select yet (the same reasoning as
    `ForgeCreateAppRequest`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
