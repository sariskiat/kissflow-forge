"""app.application.models.requests.intake.forge_update_spec_request -- the DTO
for `forge_update_spec`: merge Q&A answers into a spec.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.application.models.requests.intake.app_spec import AppSpec


class ForgeUpdateSpecRequest(BaseModel):
    """One `forge_update_spec` call. Offline, stateless.

    `spec=None` starts from a blank spec, validated into a real `AppSpec`
    here (Pydantic) when given. `patch` is a SHALLOW merge at `AppSpec`'s
    own top-level dimension keys -- necessarily a raw dict, since it is
    only ever a PARTIAL spec and its validity can only be known once it is
    merged onto the base spec (the use case's own job).
    """

    model_config = ConfigDict(frozen=True)

    spec: AppSpec | None
    patch: dict[str, Any]
