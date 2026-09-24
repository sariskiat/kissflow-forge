"""Request DTO for `forge_grant_tier`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import Tier, TierKind


class ForgeGrantTierRequest(BaseModel):
    """One `forge_grant_tier` call.

    `kind` and `tier` are closed sets: an unknown value fails with a
    Pydantic `ValidationError` before the use case runs. The `(kind, tier)`
    COMBINATION -- for example `tier="Read-only"` on `kind="process"` -- is
    a separate business rule the use case still refuses loudly, since a
    `Tier` legal for one kind is not always legal for the other.

    Attributes:
        kind: The flow kind.
        flow_id: The flow's id.
        role_id: The AppRole's id.
        tier: The tier to grant.
        app_id: The resolved application id.
    """

    kind: TierKind
    flow_id: str
    role_id: str
    tier: Tier
    app_id: str
