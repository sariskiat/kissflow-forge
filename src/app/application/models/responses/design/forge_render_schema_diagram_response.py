"""app.application.models.responses.design.forge_render_schema_diagram_response --
the DTO for `forge_render_schema_diagram`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeRenderSchemaDiagramResponse(BaseModel):
    """The rendered schema diagram, inline and on disk, plus the spec's gaps.

    Attributes:
        xml: The rendered draw.io XML, inline.
        path: Where `xml` was written on disk.
        gaps: Every dimension still insufficient on `spec` (all 11).
        blocking_gaps: Like `gaps`, excluding advisory dimensions.
    """

    model_config = ConfigDict(frozen=True)

    xml: str
    path: str
    gaps: list[str]
    blocking_gaps: list[str]
