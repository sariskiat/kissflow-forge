"""app.application.models.responses.flow.forge_set_styles_response — the
`forge_set_styles` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeSetStylesResponse(BaseModel):
    """The output-invariant audit for `forge_set_styles`: every requested
    section (plus `"<root>"` when `root_style`/`hint_text_position` was
    requested) lands in exactly one of `verified` / `missing`."""

    model_config = ConfigDict(frozen=True)

    flow_id: str
    sections: list[str]
    verified: list[str]
    missing: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
