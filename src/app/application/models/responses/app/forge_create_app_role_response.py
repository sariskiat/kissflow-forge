"""Response DTO for `forge_create_app_role`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeCreateAppRoleResponse(BaseModel):
    """The result of one `forge_create_app_role` call.

    Attributes:
        role_id: The new AppRole's id.
        name: The AppRole's display name.
        app_id: The application the role was scoped to.
        snapshot_version: Always `None` -- this write has no versioned
            draft to snapshot.
    """

    role_id: str
    name: str
    app_id: str
    snapshot_version: str | None = None
