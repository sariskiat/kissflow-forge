"""app.application.models.requests.flow.forge_set_styles_request — the
`forge_set_styles` request DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import FlowKind


class ForgeSetStylesRequest(BaseModel):
    """Shape for `forge_set_styles`: per-section style properties, and
    (optionally) the root Model's own Appearance/Style chain.

    `styles`/`root_style` values are left as `dict[str, Any]`: a style
    property's legal shape (a bare token string, or an explicit
    `{"ref"|"value": ...}` dict) is a domain business invariant, checked
    when `FlowDraft.set_section_style` runs, not here -- `tools.py` never
    had a `coerce_styles` helper either.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: str
    styles: dict[str, dict[str, Any]]
    kind: FlowKind = "process"
    publish: bool = False
    root_style: dict[str, Any] | None = None
    hint_text_position: str | None = None
    app_id: str
