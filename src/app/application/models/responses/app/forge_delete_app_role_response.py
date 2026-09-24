"""Response DTO for `forge_delete_app_role`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeDeleteAppRoleResponse(BaseModel):
    """The result of one `forge_delete_app_role` call.

    Attributes:
        role_id: The deleted AppRole's id.
        deleted: Always `True` on a normal return (the delete route's own
            failure raises `ApplicationError` instead).
        snapshot_version: Always `None` -- this write has no versioned
            draft to snapshot.
    """

    role_id: str
    deleted: bool
    snapshot_version: str | None = None
