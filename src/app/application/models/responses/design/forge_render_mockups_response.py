"""app.application.models.responses.design.forge_render_mockups_response -- the DTO
for `forge_render_mockups`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeRenderMockupsResponse(BaseModel):
    """The rendered HTML mockup bundle, inline and on disk, plus the spec's gaps.

    Attributes:
        html: The rendered HTML, inline.
        path: Where `html` was written on disk.
        summary: A short plain-text summary (stage/table/reference-list/
            persona-view counts) -- what a caller that cannot itself read
            rendered HTML can actually act on; a human opens `path` for the
            real mockup.
        gaps: Every dimension still insufficient on `spec` (all 11).
        blocking_gaps: Like `gaps`, excluding advisory dimensions.
    """

    model_config = ConfigDict(frozen=True)

    html: str
    path: str
    summary: str
    gaps: list[str]
    blocking_gaps: list[str]
