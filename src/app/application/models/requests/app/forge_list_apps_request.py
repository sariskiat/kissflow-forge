"""app.application.models.requests.app.forge_list_apps_request — the DTO for
`forge_list_apps` (today's `server.py`, `client.list_applications`): list every
application this credential can see.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeListAppsRequest(BaseModel):
    """One `forge_list_apps` call.

    Carries no field at all: `forge_list_apps` needs no app selected -- it is
    how a caller discovers which `app_id` to pass into every other
    app-scoped tool.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
