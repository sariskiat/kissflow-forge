"""Request DTO for `forge_create_flow`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain.value_objects.kinds import CreateFlowKind


class ForgeCreateFlowRequest(BaseModel):
    """`forge_create_flow`'s arguments, the app id already resolved.

    Attributes:
        kind: The flow kind to create.
        name: The flow's display name.
        extra: `kind="process"` reads `from_template`/`template_path`/
            `steps`; `kind="case"` requires `item_type` and `prefix`. Left
            as a free-form mapping, matching today's tool -- its shape
            varies by `kind`, and each key is validated where it is
            consumed.
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`.
    """

    kind: CreateFlowKind
    name: str
    extra: dict[str, Any] | None = None
    app_id: str
