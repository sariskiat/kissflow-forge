"""app.application.models.responses.page.forge_set_navigation_response —
the `forge_set_navigation` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeSetNavigationResponse(BaseModel):
    """The output-invariant audit for `forge_set_navigation`: the new Menu
    entry is verified reachable from a Navigation on read-back, never
    trusted off the write response alone.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    menu_id: str | None
    unified_nav_ids: list[str]
    swept_orphans: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
