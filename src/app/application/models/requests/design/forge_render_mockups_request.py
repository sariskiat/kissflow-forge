"""app.application.models.requests.design.forge_render_mockups_request -- the DTO
for `forge_render_mockups`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgeRenderMockupsRequest(BaseModel):
    """One `forge_render_mockups` call."""

    model_config = ConfigDict(frozen=True)

    spec: AppSpec
    out_dir: str | None = None
