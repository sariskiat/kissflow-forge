"""app.application.models.responses.intake.forge_update_spec_response -- the
DTO for `forge_update_spec`'s result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeUpdateSpecResponse(BaseModel):
    """The merged spec plus its remaining gaps.

    `spec["approved"]` is always `False`: updated content is, by
    definition, unapproved content.
    """

    model_config = ConfigDict(frozen=True)

    spec: dict[str, Any]
    gaps: list[str]
    blocking_gaps: list[str]
