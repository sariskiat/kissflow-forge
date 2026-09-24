"""app.application.models.responses.intake.forge_apply_revisions_response --
the DTO for `forge_apply_revisions`'s result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeApplyRevisionsResponse(BaseModel):
    """The revised spec plus its new digest and compilability probe.

    `spec["approved"]` is always `False`. `compiles=False` (with a non-None
    `compile_error`) is NOT a tool failure -- the revision was applied
    successfully; it just produced a spec `compile_spec` would reject.
    """

    model_config = ConfigDict(frozen=True)

    spec: dict[str, Any]
    digest: str
    compiles: bool
    compile_error: str | None
