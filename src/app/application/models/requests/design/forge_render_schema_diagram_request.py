"""app.application.models.requests.design.forge_render_schema_diagram_request --
the DTO for `forge_render_schema_diagram`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgeRenderSchemaDiagramRequest(BaseModel):
    """One `forge_render_schema_diagram` call."""

    model_config = ConfigDict(frozen=True)

    spec: AppSpec
    out_dir: str | None = None
