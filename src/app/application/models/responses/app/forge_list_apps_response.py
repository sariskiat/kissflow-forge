"""app.application.models.responses.app.forge_list_apps_response — the DTO for
`forge_list_apps`'s result: today's success dict, minus `isError`. A pure read
-- no `snapshot_version`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeListAppsResponse(BaseModel):
    """Every application this credential can see, as `{"_id": ..., "Name": ...}`
    records."""

    model_config = ConfigDict(frozen=True)

    apps: list[dict[str, Any]]
    count: int
