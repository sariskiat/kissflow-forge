"""app.application.models.requests.page.forge_create_page_request — the
`forge_create_page` request DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCreatePageRequest(BaseModel):
    """One `forge_create_page` call: a virgin app-page graph, optionally
    published straight away.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    name: str
    publish: bool = False
