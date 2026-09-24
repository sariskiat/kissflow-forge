"""Response DTO for `forge_grant_tier`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeGrantTierResponse(BaseModel):
    """The result of one `forge_grant_tier` call.

    Attributes:
        flow_id: The flow the tier was granted on.
        kind: The flow kind.
        role_id: The AppRole's id.
        tier: The tier granted.
        verified: Always `True` on a normal return (an unverified grant
            raises `ApplicationError` instead, review rule 7).
        snapshot_version: Always `None` -- this write has no versioned
            draft to snapshot.
    """

    flow_id: str
    kind: str
    role_id: str
    tier: str
    verified: bool
    snapshot_version: str | None = None
