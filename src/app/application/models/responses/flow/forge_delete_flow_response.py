"""Response DTO for `forge_delete_flow`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeDeleteFlowResponse(BaseModel):
    """`forge_delete_flow`'s success result.

    Attributes:
        kind: What was deleted.
        id: The target's id (for `kind="application"`, the app id itself).
        deleted: Always `True` on success.
        verified: Whether a fresh list read confirms the target is gone.
        snapshot_version: Always `None` -- delete is not a draft-shaped
            write (spec G11's additive field).
    """

    kind: str
    id: str
    deleted: bool
    verified: bool
    snapshot_version: str | None = None
