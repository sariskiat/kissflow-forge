"""app.application.models.requests.page.forge_set_navigation_request — the
`forge_set_navigation` request DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeSetNavigationRequest(BaseModel):
    """One `forge_set_navigation` call: wire a page into the app's
    navigation.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    page_id: str
    label: str
    unify: bool = True
    sweep: bool = False
    publish: bool = False
