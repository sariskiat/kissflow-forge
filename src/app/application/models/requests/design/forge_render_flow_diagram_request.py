"""app.application.models.requests.design.forge_render_flow_diagram_request -- the
DTO for `forge_render_flow_diagram`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgeRenderFlowDiagramRequest(BaseModel):
    """One `forge_render_flow_diagram` call.

    `spec` is validated into a real `AppSpec` here (Pydantic), replacing the
    old tool's own manual `AppSpec.model_validate(spec)` / `isinstance(dict)`
    dance -- a malformed `spec` now fails with `ValidationError` before the
    use case ever runs.
    """

    model_config = ConfigDict(frozen=True)

    spec: AppSpec
    out_dir: str | None = None
