"""app.application.models.responses.page.forge_create_page_response — the
`forge_create_page` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCreatePageResponse(BaseModel):
    """The output-invariant audit for `forge_create_page`: the new page is
    verified via `list_pages`, never trusted off the create response alone
    (CLAUDE.md > Pages).
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    page_id: str | None
    name: str
    verified: bool
    published: bool
    snapshot_version: str | None = None
